#include "protocol/robstride_spc.h"
/* Two independent velocity loops on CAN1. This is a joint bus test, not synchronized motion. */
#include "motor_enable_app.h"
#include "motor_enable_logic.h"
#include "transport/can_transport.h"
#include <stdio.h>
#include <string.h>
#if defined(PICO_FAULT_TARGET)
#define EXP_TAG "DUAL_FAULT"
#else
#define EXP_TAG "DUAL_SPEED"
#endif
static MotorEnable motors[2];
static FDCAN_HandleTypeDef *bus;
static UART_HandleTypeDef *serial;
static bool ready,uart_failed,result_reported,motion_released;
static uint32_t next_health,old_phase[2],session_uart_errors;
static char token[9],command[64];static unsigned command_used;
static uint8_t incoming;
static volatile uint8_t ring[128];
static volatile uint32_t wr,rd,uart_errors,uart_received,last_uart_error;
static volatile bool rx_resync;
#if defined(PICO_FAULT_TARGET)
static bool injected,detected,unexpected_fault;
static uint32_t injected_at,feedback_before_injection,detected_at,dropped;
#endif
static void line(const char *s){
    if(HAL_UART_Transmit(serial,(const uint8_t *)s,(uint16_t)strlen(s),100U)!=HAL_OK)uart_failed=true;
}
static void stop_all(uint32_t now,const char *reason,bool error){
    for(unsigned i=0;i<2;++i)MotorEnable_Stop(&motors[i],now,reason,error);
}
static void interlock(uint32_t now){
    for(unsigned i=0;i<2;++i)if(motors[i].finishing){
        bool automatic=strcmp(motors[i].reason,"AUTO_STOP")==0||strcmp(motors[i].reason,"GROUP_AUTO_STOP")==0;
        for(unsigned j=0;j<2;++j)if(j!=i&&!motors[j].finishing){
            bool no_motion=automatic&&!motors[j].motion_confirmed;
            MotorEnable_Stop(&motors[j],now,no_motion?"NO_MOTION":automatic?"GROUP_AUTO_STOP":"PEER_STOP",motors[i].error||no_motion);
        }
    }
}
static void abort_pending(void){
    bool abort=false;
    for(unsigned i=0;i<2;++i)if(motors[i].abort_pending){abort=true;motors[i].abort_pending=false;}
    if(abort&&bus->Instance->TXBRP)(void)HAL_FDCAN_AbortTxRequest(bus,bus->Instance->TXBRP);
}
static void log_frame(const char *event,const CanFrame *f){
    /* With two motors, per-frame TX_DONE text would saturate 115200 baud.
       Keep raw TX_SUBMIT/RX; completed TX is still counted in each health line. */
    if(strcmp(event,"TX_DONE")==0)return;
    char s[200];int used=snprintf(s,sizeof(s),"%lu,%s,FDCAN1,EXT,DATA,0x%08lX,%u,",
        (unsigned long)f->timestamp_ms,event,(unsigned long)f->id,(unsigned)f->dlc);
    for(unsigned i=0;i<f->dlc;++i)used+=snprintf(s+used,sizeof(s)-(size_t)used,"%s%02X",i?" ":"",f->data[i]);
    (void)snprintf(s+used,sizeof(s)-(size_t)used,"\r\n");line(s);
}
static bool send_frame(void *context,const CanFrame *f,uint32_t now){
    (void)context;return CanTransport_Submit(f,now);
}
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *uart){
    if(uart!=serial)return;
    ++uart_received;uint32_t next=(wr+1U)%sizeof(ring);
    if(next==rd){++uart_errors;rx_resync=true;}else{ring[wr]=incoming;__DMB();wr=next;}
    (void)HAL_UART_Receive_IT(serial,&incoming,1);
}
void HAL_UART_ErrorCallback(UART_HandleTypeDef *uart){
    if(uart!=serial)return;
    ++uart_errors;last_uart_error=uart->ErrorCode;rx_resync=true;
    __HAL_UART_CLEAR_FLAG(serial,UART_CLEAR_OREF|UART_CLEAR_FEF|UART_CLEAR_NEF|UART_CLEAR_PEF);
    __HAL_UART_SEND_REQ(serial,UART_RXDATA_FLUSH_REQUEST);
    (void)HAL_UART_Receive_IT(serial,&incoming,1);
}
static void heartbeat(uint32_t now){for(unsigned i=0;i<2;++i)MotorEnable_Heartbeat(&motors[i],now);}
static void accept_command(uint32_t now){
    if(strcmp(command,"STOP")==0){stop_all(now,"MANUAL_STOP",false);return;}
    char candidate[9]={0},extra;unsigned id=0;
    if(sscanf(command,"SESSION %8[0-9A-F] %u %c",candidate,&id,&extra)==2&&strlen(candidate)==8U){
        /* Group session ID 0 is a UART selector, never a CAN broadcast ID. */
        if(id!=0U||motors[0].run_requested||motors[1].run_requested){line("# SESSION_REJECTED\r\n");return;}
        memcpy(token,candidate,9);session_uart_errors=uart_errors;heartbeat(now);
        char s[90];(void)snprintf(s,sizeof(s),"# SESSION_OK token=%s id=0\r\n",token);line(s);return;
    }
    if(!token[0])return;
    if(sscanf(command,"KEEP %8s %c",candidate,&extra)==1&&strcmp(candidate,token)==0){heartbeat(now);return;}
    if(sscanf(command,"RUN %8s %c",candidate,&extra)==1&&strcmp(candidate,token)==0){
        if(motors[0].phase!=ME_READY||motors[1].phase!=ME_READY){line("# " EXP_TAG "_REJECTED both_motors_must_be_ready\r\n");return;}
        bool first=MotorEnable_Request(&motors[0],now),second=MotorEnable_Request(&motors[1],now);
        if(!first||!second)stop_all(now,"GROUP_START_REJECTED",true);
        return;
    }
    line("# COMMAND_REJECTED\r\n");
}
void MotorEnableApp_Init(FDCAN_HandleTypeDef *can,UART_HandleTypeDef *uart){
    bus=can;serial=uart;ready=uart_failed=result_reported=motion_released=false;
#if defined(PICO_FAULT_TARGET)
    injected=detected=unexpected_fault=false;injected_at=feedback_before_injection=detected_at=dropped=0;
#endif
    wr=rd=uart_errors=uart_received=last_uart_error=session_uart_errors=0;
    command_used=0;token[0]=0;rx_resync=false;old_phase[0]=old_phase[1]=0xFFFFFFFFU;
    __HAL_UART_CLEAR_FLAG(serial,UART_CLEAR_OREF|UART_CLEAR_FEF|UART_CLEAR_NEF|UART_CLEAR_PEF);
    __HAL_UART_SEND_REQ(serial,UART_RXDATA_FLUSH_REQUEST);
    HAL_NVIC_SetPriority(LPUART1_IRQn,0,0);HAL_NVIC_EnableIRQ(LPUART1_IRQn);
    if(HAL_UART_Receive_IT(serial,&incoming,1)!=HAL_OK){line("# " EXP_TAG "_FATAL UART RX initialization failed\r\n");return;}
    line("# PICO_MOTOR_" EXP_TAG "=1; channel=FDCAN1 bitrate=1000000 models=RS10P,RS00 motor_ids=1,2 host_id=253 max_enable_ms=3000 host_timeout_ms=500 target_rad_s=0.3 current_limit_A=0.5 accel_rad_s2=0.5\r\n");
#if defined(PICO_FAULT_TARGET)
    char target[100];(void)snprintf(target,sizeof(target),"# FAULT_CONFIG,target_id=%u,method=DROP_VALID_RUNNING_FEEDBACK,timeout_ms=500\r\n",PICO_FAULT_TARGET);line(target);
#endif
 line(ROBSTRIDE_SPC_BANNER);
    line("# TX=PA12 RX=PA11 AF9; boot=STOP_BOTH; manual_RUN_only; both_postchecks_required; any_error_stops_both; TX_SUBMIT_and_RX_logged; tx_done_is_shared_bus_counter; no flash-save/ID/baud/zero-cal\r\n");
    if(!CanTransport_Init(can,1000000U,CAN_FILTER_MOTOR,0xFD,log_frame)){line("# " EXP_TAG "_FATAL CAN initialization failed\r\n");return;}
    for(unsigned i=0;i<2;++i){
        MotorEnable_InitSpeed(&motors[i],(uint8_t)(i+1),0xFD,HAL_GetTick());
        motors[i].refresh_ms=200U;motors[i].query_ms=60U;
        motors[i].due+=i*20U;
    }
    next_health=HAL_GetTick()+1000U;ready=true;line("# " EXP_TAG "_COMMAND_READY=1; protocol=2\r\n");
}
static bool passed(const MotorEnable *e){
    return e->phase==ME_DONE&&e->run_requested&&e->enable_confirmed&&e->stop_confirmed&&
        e->motion_confirmed&&e->target_cleared&&e->iq_samples&&e->velocity_samples&&e->position_samples&&!e->error&&
        (strcmp(e->reason,"AUTO_STOP")==0||strcmp(e->reason,"GROUP_AUTO_STOP")==0);
}
void MotorEnableApp_Step(void){
    if(!ready)return;
    uint32_t now=HAL_GetTick();
    if(rx_resync){
        uint32_t irq=__get_PRIMASK();__disable_irq();rd=wr;rx_resync=false;__set_PRIMASK(irq);command_used=0;
    }
    while(rd!=wr){
        uint8_t c=ring[rd];rd=(rd+1U)%sizeof(ring);
        if(c=='\n'){command[command_used]=0;accept_command(now);command_used=0;}
        else if(c!='\r'){
            if(command_used+1U<sizeof(command))command[command_used++]=(char)c;
            else{command_used=0;++uart_errors;rx_resync=true;}
        }
    }
    CanTransport_Service(now);CanFrame f;
    while(CanTransport_Receive(&f)){
        log_frame("RX",&f);
#if defined(PICO_FAULT_TARGET)
        if(CanFrame_IsValid(&f)&&f.extended&&!f.remote&&f.dlc==8U&&(f.id&255U)==253U&&
           (((f.id>>8)&255U)==1U||((f.id>>8)&255U)==2U)){
            unsigned type=(unsigned)((f.id>>24)&31U);
            if((type==2U&&((f.id>>16)&63U)!=0U)||
               (type==21U&&(f.data[0]||f.data[1]||f.data[2]||f.data[3])))unexpected_fault=true;
        }
#endif
        for(unsigned i=0;i<2;++i){
#if defined(PICO_FAULT_TARGET)
            /* Drop only valid normal RUNNING feedback. Faults and STOP responses
               must always reach the policy, even while the injection is active. */
            if(injected && i==PICO_FAULT_TARGET-1U && !motors[i].finishing &&
               CanFrame_IsValid(&f)&&f.extended&&!f.remote&&f.dlc==8U&&
               (f.id&255U)==253U&&((f.id>>8)&255U)==PICO_FAULT_TARGET&&
               ((f.id>>24)&31U)==2U&&((f.id>>22)&3U)==2U&&((f.id>>16)&63U)==0U){++dropped;continue;}
#endif
            MotorEnable_OnFrame(&motors[i],&f,now);
        }
    }
    CanTransportStats stats=CanTransport_GetStats();
    if(stats.tx_timed_out||stats.bus_off||stats.rx_fifo_lost||stats.rx_queue_dropped||stats.rx_read_failed||
       stats.tx_event_lost||stats.tx_event_unknown||stats.tx_rejected)stop_all(now,"CAN_LINK_ERROR",true);
    if(uart_failed||(token[0]&&uart_errors!=session_uart_errors))stop_all(now,"UART_LINK_ERROR",true);
#if defined(PICO_FAULT_TARGET)
    if(!injected&&motors[0].phase==ME_ACTIVE&&motors[1].phase==ME_ACTIVE&&
       motors[0].motion_confirmed&&motors[1].motion_confirmed&&
       now-motors[0].active_at>=800U&&now-motors[1].active_at>=800U){
        injected=true;injected_at=now;feedback_before_injection=motors[PICO_FAULT_TARGET-1].last_feedback;
        char s[130];(void)snprintf(s,sizeof(s),"# FAULT_INJECT,target_id=%u,t_ms=%lu,last_feedback_ms=%lu\r\n",PICO_FAULT_TARGET,(unsigned long)now,(unsigned long)feedback_before_injection);line(s);
    }
#endif
    /* Check BOTH policies before either may submit the next motion frame. */
    for(unsigned i=0;i<2;++i)MotorEnable_CheckSafety(&motors[i],now);
#if defined(PICO_FAULT_TARGET)
    if(injected&&!detected&&strcmp(motors[PICO_FAULT_TARGET-1].reason,"FEEDBACK_TIMEOUT")==0){
        detected=true;detected_at=now;
        char s[180];(void)snprintf(s,sizeof(s),"# FAULT_DETECTED,target_id=%u,t_ms=%lu,since_last_feedback_ms=%lu,dropped=%lu\r\n",PICO_FAULT_TARGET,(unsigned long)now,(unsigned long)(now-feedback_before_injection),(unsigned long)dropped);line(s);
    }
#endif
    interlock(now);abort_pending();
    if(motors[0].phase==ME_SPEED_TARGET&&motors[1].phase==ME_SPEED_TARGET)motion_released=true;
    for(unsigned i=0;i<2;++i){
        if(motors[i].phase!=ME_SPEED_TARGET||motion_released)MotorEnable_Step(&motors[i],now,send_frame,0);
        interlock(now);abort_pending();
    }
    if(old_phase[0]!=(uint32_t)motors[0].phase||old_phase[1]!=(uint32_t)motors[1].phase||(int32_t)(now-next_health)>=0){
        next_health=now+1000U;
        FDCAN_ErrorCountersTypeDef errors={0};(void)HAL_FDCAN_GetErrorCounters(bus,&errors);
        for(unsigned i=0;i<2;++i){
            MotorEnable *e=&motors[i];old_phase[i]=(uint32_t)e->phase;
            char s[650];(void)snprintf(s,sizeof(s),
                "# " EXP_TAG "_STATE,state=%s,id=%u,reason=%s,enable_confirmed=%u,stop_confirmed=%u,stop_unconfirmed=%u,error=%u,iq_mA=%ld,iq_samples=%lu,velocity_samples=%lu,position_samples=%lu,feedbacks=%lu,tx_done=%lu,tec=%lu,rec=%lu,bus_off=%lu,uart_rx=%lu,uart_errors=%lu,uart_error=0x%lX,velocity_mrad_s=%ld,delta_mrad=%ld,motion_confirmed=%u,target_cleared=%u\r\n",
                MotorEnable_Name(e->phase),(unsigned)e->id,e->reason,e->enable_confirmed?1U:0U,e->stop_confirmed?1U:0U,
                e->stop_unconfirmed?1U:0U,e->error?1U:0U,(long)(e->iq*1000.0f),(unsigned long)e->iq_samples,
                (unsigned long)e->velocity_samples,(unsigned long)e->position_samples,(unsigned long)e->feedbacks,
                (unsigned long)stats.tx_completed,(unsigned long)errors.TxErrorCnt,(unsigned long)errors.RxErrorCnt,
                (unsigned long)stats.bus_off,(unsigned long)uart_received,(unsigned long)uart_errors,(unsigned long)last_uart_error,
                (long)(e->velocity*1000.0f),(long)(e->position_delta*1000.0f),e->motion_confirmed?1U:0U,e->target_cleared?1U:0U);line(s);
        }
    }
    if(motors[0].phase==ME_DONE&&motors[1].phase==ME_DONE&&!result_reported){
        bool pass=passed(&motors[0])&&passed(&motors[1]);
#if defined(PICO_FAULT_TARGET)
        MotorEnable *victim=&motors[PICO_FAULT_TARGET-1],*peer=&motors[2-PICO_FAULT_TARGET];
        pass=injected&&detected&&!unexpected_fault&&dropped>0U&&detected_at-injected_at<1000U&&
            detected_at-feedback_before_injection>500U&&detected_at-feedback_before_injection<=800U&&
            strcmp(victim->reason,"FEEDBACK_TIMEOUT")==0&&strcmp(peer->reason,"PEER_STOP")==0&&
            !uart_failed&&uart_errors==session_uart_errors&&!stats.tx_timed_out&&!stats.bus_off&&
            !stats.rx_fifo_lost&&!stats.rx_queue_dropped&&!stats.rx_read_failed&&!stats.tx_event_lost&&!stats.tx_event_unknown&&!stats.tx_rejected;
        for(unsigned i=0;i<2;++i)pass=pass&&motors[i].enable_confirmed&&motors[i].motion_confirmed&&motors[i].stop_confirmed&&motors[i].target_cleared;
#endif
        char s[260];(void)snprintf(s,sizeof(s),
            "# " EXP_TAG "_RESULT,result=%s,motor_ids=1,2,enable_confirmed=%u,stop_confirmed=%u,motion_confirmed=%u,target_cleared=%u,reason=%s\r\n",
            pass?"PASS":motors[0].error||motors[1].error?"FAIL":"STOPPED",
            motors[0].enable_confirmed&&motors[1].enable_confirmed?1U:0U,
            motors[0].stop_confirmed&&motors[1].stop_confirmed?1U:0U,
            motors[0].motion_confirmed&&motors[1].motion_confirmed?1U:0U,
            motors[0].target_cleared&&motors[1].target_cleared?1U:0U,
            pass?
#if defined(PICO_FAULT_TARGET)
            "EXPECTED_FEEDBACK_TIMEOUT_BOTH_STOPPED"
#else
            "AUTO_STOP"
#endif
            :"SEE_PER_MOTOR_STATE");line(s);result_reported=true;
    }
}
