#include "protocol/robstride_spc.h"
/* Two independent position trajectories. Shared safety; no mechanical synchronization. */
#include "motor_enable_app.h"
#include "motor_position_logic.h"
#include "transport/can_transport.h"
#include <stdio.h>
#include <string.h>
#define EXP_TAG "DUAL_POSITION"
static MotorPosition motors[2];
static FDCAN_HandleTypeDef *bus;
static UART_HandleTypeDef *serial;
static bool ready,uart_failed,result_reported,motion_released;
static bool can_error_reported;
static uint32_t next_health,old_phase[2],reported_waypoints[2],session_uart_errors;
static char token[9],command[64];static unsigned command_used;
static uint8_t incoming;
static volatile uint8_t ring[128];
static volatile uint32_t wr,rd,uart_errors,uart_received,last_uart_error;
static volatile bool rx_resync;
static void line(const char *s){
    if(HAL_UART_Transmit(serial,(const uint8_t *)s,(uint16_t)strlen(s),100U)!=HAL_OK)uart_failed=true;
}
static void stop_all(uint32_t now,const char *reason,bool error){
    for(unsigned i=0;i<2;++i)MotorPosition_Stop(&motors[i],now,reason,error);
}
static bool failure_latched;
static void interlock(uint32_t now){
    for(unsigned i=0;i<2;++i){
        MotorEnable *e=&motors[i].core;
        if(e->error)failure_latched=true;
        /* A normally completed axis may stop and remain idle while its peer finishes. */
        if(e->finishing&&(e->error||strcmp(e->reason,"POSITION_COMPLETE")!=0)){
            for(unsigned j=0;j<2;++j)if(j!=i&&!motors[j].core.finishing)
                MotorPosition_Stop(&motors[j],now,"PEER_STOP",e->error);
        }
    }
}
static void abort_pending(void){
    bool abort=false;
    for(unsigned i=0;i<2;++i)if(motors[i].core.abort_pending){
        /* Normal completion has no pending enable or new waypoint. Its final
           target is already reached; preserve the peer's shared-bus requests. */
        if(motors[i].core.error||strcmp(motors[i].core.reason,"POSITION_COMPLETE")!=0)abort=true;
        motors[i].core.abort_pending=false;
    }
    if(abort&&bus->Instance->TXBRP)(void)HAL_FDCAN_AbortTxRequest(bus,bus->Instance->TXBRP);
}
static void log_frame(const char *event,const CanFrame *f){
    /* With two motors, per-frame TX_DONE text would saturate 115200 baud.
       Keep raw TX_SUBMIT/RX; completed TX is still counted in each health line. */
    if(strcmp(event,"TX_DONE")==0)return;
    if(strcmp(event,"TX_SUBMIT")==0){
        unsigned destination=(unsigned)(f->id&255U),type=(unsigned)((f->id>>24)&31U);
        unsigned index=f->data[0]|((unsigned)f->data[1]<<8);
        MotorPosition *p=(destination>=1U&&destination<=2U)?&motors[destination-1U]:NULL;
        if(p!=NULL&&p->core.phase==ME_ACTIVE&&p->stage==MP_MOVE&&!p->core.finishing&&
           ((type==17U&&(index==0x7019U||index==0x701AU||index==0x701BU))||(type==18U&&index==0x7016U)))return;
    }

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
static void heartbeat(uint32_t now){for(unsigned i=0;i<2;++i)MotorPosition_Heartbeat(&motors[i],now);}
static void accept_command(uint32_t now){
    if(strcmp(command,"STOP")==0){stop_all(now,"MANUAL_STOP",false);return;}
    char candidate[9]={0},extra;unsigned id=0;
    if(sscanf(command,"SESSION %8[0-9A-F] %u %c",candidate,&id,&extra)==2&&strlen(candidate)==8U){
        /* Group session ID 0 is a UART selector, never a CAN broadcast ID. */
        if(id!=0U||motors[0].core.run_requested||motors[1].core.run_requested){line("# SESSION_REJECTED\r\n");return;}
        memcpy(token,candidate,9);session_uart_errors=uart_errors;heartbeat(now);
        char s[90];(void)snprintf(s,sizeof(s),"# SESSION_OK token=%s id=0\r\n",token);line(s);return;
    }
    if(!token[0])return;
    if(sscanf(command,"KEEP %8s %c",candidate,&extra)==1&&strcmp(candidate,token)==0){heartbeat(now);return;}
    if(sscanf(command,"RUN %8s %c",candidate,&extra)==1&&strcmp(candidate,token)==0){
        if(motors[0].core.phase!=ME_READY||motors[1].core.phase!=ME_READY){line("# " EXP_TAG "_REJECTED both_motors_must_be_ready\r\n");return;}
        bool first=MotorPosition_Request(&motors[0],now),second=MotorPosition_Request(&motors[1],now);
        if(!first||!second)stop_all(now,"GROUP_START_REJECTED",true);
        return;
    }
    line("# COMMAND_REJECTED\r\n");
}
void MotorEnableApp_Init(FDCAN_HandleTypeDef *can,UART_HandleTypeDef *uart){
    can_error_reported=false;failure_latched=false;bus=can;serial=uart;ready=uart_failed=result_reported=motion_released=false;
    reported_waypoints[0]=reported_waypoints[1]=0;wr=rd=uart_errors=uart_received=last_uart_error=session_uart_errors=0;
    command_used=0;token[0]=0;rx_resync=false;old_phase[0]=old_phase[1]=0xFFFFFFFFU;
    __HAL_UART_CLEAR_FLAG(serial,UART_CLEAR_OREF|UART_CLEAR_FEF|UART_CLEAR_NEF|UART_CLEAR_PEF);
    __HAL_UART_SEND_REQ(serial,UART_RXDATA_FLUSH_REQUEST);
    HAL_NVIC_SetPriority(LPUART1_IRQn,0,0);HAL_NVIC_EnableIRQ(LPUART1_IRQn);
    if(HAL_UART_Receive_IT(serial,&incoming,1)!=HAL_OK){line("# " EXP_TAG "_FATAL UART RX initialization failed\r\n");return;}
    line("# PICO_MOTOR_" EXP_TAG "=1; channel=FDCAN1 bitrate=1000000 models=RS10P,RS00 motor_ids=1,2 host_id=253 max_enable_ms=90000 host_timeout_ms=500 angle1_deg=5 angle2_deg=-3 dwell1_ms=500 dwell2_ms=800 cycles=10 speed_limit_rad_s=0.2 current_limit_A=0.5 arrival_policy=POSITION_WINDOW_V3 tx_policy=" CAN_TRANSPORT_TX_POLICY " tx_deadline_ms=300\r\n");
 line(ROBSTRIDE_SPC_BANNER);
    line("# TX=PA12 RX=PA11 AF9; boot=STOP_BOTH; manual_RUN_only; both_postchecks_required; any_error_stops_both; RX_all_and_control_TX_logged_cyclic_TX_counted; tx_done_is_shared_bus_counter; no flash-save/ID/baud/zero-cal\r\n");
    if(!CanTransport_Init(can,1000000U,CAN_FILTER_MOTOR,0xFD,log_frame)){line("# " EXP_TAG "_FATAL CAN initialization failed\r\n");return;}
    for(unsigned i=0;i<2;++i){
        MotorPosition_Init(&motors[i],(uint8_t)(i+1),0xFD,HAL_GetTick());
        motors[i].core.refresh_ms=200U;motors[i].core.query_ms=60U;
        motors[i].amplitude_rad=i==0?0.0872664626f:-0.0523598776f;
        motors[i].dwell_ms=i==0?500U:800U;
        motors[i].core.due+=i*20U;
    }
    next_health=HAL_GetTick()+1000U;ready=true;line("# " EXP_TAG "_COMMAND_READY=1; protocol=2\r\n");
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
        if(CanFrame_IsValid(&f)&&f.extended&&!f.remote&&f.dlc==8U&&(f.id&255U)==253U&&
           (((f.id>>8)&255U)==1U||((f.id>>8)&255U)==2U)){
            unsigned type=(unsigned)((f.id>>24)&31U);
            if((type==2U&&((f.id>>16)&63U)!=0U)||(type==21U&&(f.data[0]||f.data[1]||f.data[2]||f.data[3]))){failure_latched=true;stop_all(now,"MOTOR_FAULT",true);}
        }
        for(unsigned i=0;i<2;++i){
            MotorPosition_OnFrame(&motors[i],&f,now);
        }
    }
    CanTransportStats stats=CanTransport_GetStats();
    bool link_error=stats.tx_timed_out||stats.bus_off||stats.rx_fifo_lost||stats.rx_queue_dropped||stats.rx_read_failed||
       stats.tx_event_lost||stats.tx_event_unknown||stats.tx_rejected;
    uint32_t fault_pending=0,fault_transmitted=0,fault_cancelled=0,fault_psr=0;
    if(link_error){
        fault_pending=bus->Instance->TXBRP;fault_transmitted=bus->Instance->TXBTO;
        fault_cancelled=bus->Instance->TXBCF;fault_psr=bus->Instance->PSR;
        const char *reason=stats.tx_timed_out?"CAN_TX_TIMEOUT":stats.tx_event_lost?"CAN_TX_EVENT_LOST":
            stats.tx_event_unknown?"CAN_TX_EVENT_UNKNOWN":stats.tx_rejected?"CAN_TX_REJECTED":"CAN_LINK_ERROR";
        stop_all(now,reason,true);
    }
    if(uart_failed||(token[0]&&uart_errors!=session_uart_errors))stop_all(now,"UART_LINK_ERROR",true);
    /* Check BOTH policies before either may submit the next motion frame. */
    for(unsigned i=0;i<2;++i)MotorPosition_CheckSafety(&motors[i],now);
    interlock(now);abort_pending();
    if(motors[0].stage==MP_TARGET&&motors[1].stage==MP_TARGET)motion_released=true;
    for(unsigned i=0;i<2;++i){
        if(motors[i].stage!=MP_TARGET||motion_released)MotorPosition_Step(&motors[i],now,send_frame,0);
        interlock(now);abort_pending();
    }
    if(link_error&&!can_error_reported){
        char detail[500];(void)snprintf(detail,sizeof(detail),
            "# CAN_FAULT_DETAIL,t_ms=%lu,tx_timed_out=%lu,tx_rejected=%lu,tx_event_lost=%lu,tx_event_unknown=%lu,rx_fifo_lost=%lu,rx_queue_dropped=%lu,rx_read_failed=%lu,bus_off=%lu,tx_pending=0x%lX,tx_transmitted=0x%lX,tx_cancelled=0x%lX,psr=0x%lX\r\n",
            (unsigned long)now,(unsigned long)stats.tx_timed_out,(unsigned long)stats.tx_rejected,
            (unsigned long)stats.tx_event_lost,(unsigned long)stats.tx_event_unknown,(unsigned long)stats.rx_fifo_lost,
            (unsigned long)stats.rx_queue_dropped,(unsigned long)stats.rx_read_failed,(unsigned long)stats.bus_off,
            (unsigned long)fault_pending,(unsigned long)fault_transmitted,(unsigned long)fault_cancelled,(unsigned long)fault_psr);
        line(detail);can_error_reported=true;
    }
    for(unsigned i=0;i<2;++i)if(reported_waypoints[i]!=motors[i].waypoints){
        MotorPosition *p=&motors[i];reported_waypoints[i]=p->waypoints;
        char record[220];(void)snprintf(record,sizeof(record),"# DUAL_POSITION_WAYPOINT,id=%u,completed=%u,cycle=%u,leg=%u,target_delta_urad=%ld,arrival_error_urad=%ld\r\n",
            (unsigned)p->core.id,p->waypoints,(p->waypoints-1U)/4U+1U,(p->waypoints-1U)%4U+1U,
            (long)((p->last_target-p->origin)*1000000.0f),(long)(p->last_arrival_error*1000000.0f));line(record);
    }
    for(unsigned i=0;i<2;++i)if(old_phase[i]!=(uint32_t)motors[i].core.phase){
        old_phase[i]=(uint32_t)motors[i].core.phase;
        char phase_event[160];(void)snprintf(phase_event,sizeof(phase_event),
            "# DUAL_POSITION_PHASE,id=%u,state=%s,reason=%s\r\n",(unsigned)motors[i].core.id,
            MotorPosition_Name(&motors[i]),motors[i].core.reason);line(phase_event);
    }
    /* A burst of two full status lines at every cleanup transition could
       starve the still-running peer's 500ms telemetry deadline. */
    if((int32_t)(now-next_health)>=0||
       (motors[0].core.phase==ME_DONE&&motors[1].core.phase==ME_DONE&&!result_reported)){
        next_health=now+1000U;
        FDCAN_ErrorCountersTypeDef errors={0};(void)HAL_FDCAN_GetErrorCounters(bus,&errors);
        for(unsigned i=0;i<2;++i){
            MotorPosition *p=&motors[i];MotorEnable *e=&p->core;old_phase[i]=(uint32_t)e->phase;
            char s[1050];(void)snprintf(s,sizeof(s),
                "# " EXP_TAG "_STATE,state=%s,id=%u,reason=%s,enable_confirmed=%u,stop_confirmed=%u,stop_unconfirmed=%u,error=%u,iq_mA=%ld,iq_samples=%lu,velocity_samples=%lu,position_samples=%lu,feedbacks=%lu,tx_done=%lu,tec=%lu,rec=%lu,bus_off=%lu,uart_rx=%lu,uart_errors=%lu,uart_error=0x%lX,velocity_mrad_s=%ld,delta_mrad=%ld,motion_confirmed=%u,target_cleared=%u,cycles_completed=%u,waypoints_completed=%u,target_delta_mrad=%ld,max_arrival_error_mrad=%ld,max_return_error_mrad=%ld,peak_iq_mA=%ld,neutralize_failed=%u,stable_span_urad=%ld,stable_elapsed_ms=%lu,stable_samples=%lu,stable_velocity_mrad_s=%ld,position_step_speed_mrad_s=%ld,position_mean_speed_mrad_s=%ld\r\n",
                MotorPosition_Name(p),(unsigned)e->id,e->reason,e->enable_confirmed?1U:0U,e->stop_confirmed?1U:0U,
                e->stop_unconfirmed?1U:0U,e->error?1U:0U,(long)(e->iq*1000.0f),(unsigned long)e->iq_samples,
                (unsigned long)e->velocity_samples,(unsigned long)e->position_samples,(unsigned long)e->feedbacks,
                (unsigned long)stats.tx_completed,(unsigned long)errors.TxErrorCnt,(unsigned long)errors.RxErrorCnt,
                (unsigned long)stats.bus_off,(unsigned long)uart_received,(unsigned long)uart_errors,(unsigned long)last_uart_error,
                (long)(e->velocity*1000.0f),(long)(e->position_delta*1000.0f),e->motion_confirmed?1U:0U,e->target_cleared?1U:0U,p->waypoints/4U,p->waypoints,(long)((p->target-p->origin)*1000.0f),
                (long)(p->max_arrival_error*1000.0f),(long)(p->max_return_error*1000.0f),(long)(p->peak_iq*1000.0f),p->neutralize_failed?1U:0U,(long)(p->stable_span*1000000.0f),
                (unsigned long)(p->settled?p->stable_last_at-p->settle_at:0U),(unsigned long)p->stable_samples,(long)(p->stable_velocity*1000.0f),(long)(p->sampled_position_speed*1000.0f),(long)(p->mean_position_speed*1000.0f));line(s);
        }
    }
    if(motors[0].core.phase==ME_DONE&&motors[1].core.phase==ME_DONE&&!result_reported){
        bool pass=!failure_latched&&MotorPosition_Passed(&motors[0])&&MotorPosition_Passed(&motors[1]);
        char s[260];(void)snprintf(s,sizeof(s),
            "# " EXP_TAG "_RESULT,result=%s,motor_ids=1,2,enable_confirmed=%u,stop_confirmed=%u,motion_confirmed=%u,target_cleared=%u,reason=%s\r\n",
            pass?"PASS":failure_latched||motors[0].core.error||motors[1].core.error?"FAIL":"STOPPED",
            motors[0].core.enable_confirmed&&motors[1].core.enable_confirmed?1U:0U,
            motors[0].core.stop_confirmed&&motors[1].core.stop_confirmed?1U:0U,
            motors[0].core.motion_confirmed&&motors[1].core.motion_confirmed?1U:0U,
            motors[0].core.target_cleared&&motors[1].core.target_cleared?1U:0U,
            pass?
            "BOTH_POSITION_COMPLETE"
            :"SEE_PER_MOTOR_STATE");line(s);result_reported=true;
    }
}
