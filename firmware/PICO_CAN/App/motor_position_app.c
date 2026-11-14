#include "protocol/robstride_spc.h"
#include "motor_enable_app.h"
#include "motor_position_logic.h"
#include "transport/can_transport.h"
#include <stdio.h>
#include <string.h>
#define EXPERIMENT_TAG "POSITION"
#define EXPERIMENT_COMMAND "RUN"
#define EXPERIMENT_PARAMETERS "cycles=10 angle_deg=5 current_limit_A=0.5 speed_limit_rad_s=0.2 dwell_ms=500 arrival_policy=POSITION_WINDOW_V3"
static MotorPosition experiment;
static FDCAN_HandleTypeDef *bus;
static UART_HandleTypeDef *serial;
static bool ready,uart_failed,result_reported;
static uint32_t next_health,old_phase=0xFFFFFFFFU,reported_waypoints;
static char token[9],command[64];static unsigned command_used;
static uint8_t incoming;
static volatile uint8_t ring[128];static volatile uint32_t wr,rd,uart_errors,uart_received,last_uart_error;
static uint32_t session_uart_errors;
static volatile bool rx_resync;
static void line(const char *s){
    if(HAL_UART_Transmit(serial,(const uint8_t *)s,(uint16_t)strlen(s),100U)!=HAL_OK)uart_failed=true;
}
static void log_frame(const char *event,const CanFrame *f){
    if(strcmp(event,"TX_DONE")==0)return;
    if(strcmp(event,"TX_SUBMIT")==0){
        unsigned destination=(unsigned)(f->id&255U),type=(unsigned)((f->id>>24)&31U);
        unsigned index=f->data[0]|((unsigned)f->data[1]<<8);
        MotorPosition *p=&experiment;
        if(destination==p->core.id&&p->core.phase==ME_ACTIVE&&p->stage==MP_MOVE&&!p->core.finishing&&
           ((type==17U&&(index==0x7019U||index==0x701AU||index==0x701BU))||(type==18U&&index==0x7016U)))return;
    }

    char s[200];int used=snprintf(s,sizeof(s),"%lu,%s,FDCAN1,EXT,DATA,0x%08lX,%u,",
        (unsigned long)f->timestamp_ms,event,(unsigned long)f->id,(unsigned)f->dlc);
    for(uint32_t i=0;i<f->dlc;++i)used+=snprintf(s+used,sizeof(s)-(size_t)used,"%s%02X",i?" ":"",f->data[i]);
    (void)snprintf(s+used,sizeof(s)-(size_t)used,"\r\n");line(s);
}
static bool send_frame(void *context,const CanFrame *f,uint32_t now){
    (void)context;
    if((f->id>>24)==4U && experiment.core.abort_pending){
        uint32_t pending=bus->Instance->TXBRP;
        if(pending)(void)HAL_FDCAN_AbortTxRequest(bus,pending);
        experiment.core.abort_pending=false;
    }
    return CanTransport_Submit(f,now);
}
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *uart){
    if(uart!=serial)return;
    ++uart_received;
    uint32_t next=(wr+1U)%sizeof(ring);
    if(next==rd)++uart_errors;else{ring[wr]=incoming;__DMB();wr=next;}
    (void)HAL_UART_Receive_IT(serial,&incoming,1);
}
void HAL_UART_ErrorCallback(UART_HandleTypeDef *uart){
    if(uart!=serial)return;
    ++uart_errors;last_uart_error=uart->ErrorCode;rx_resync=true;
    __HAL_UART_CLEAR_FLAG(serial,UART_CLEAR_OREF|UART_CLEAR_FEF|UART_CLEAR_NEF|UART_CLEAR_PEF);
    __HAL_UART_SEND_REQ(serial,UART_RXDATA_FLUSH_REQUEST);
    (void)HAL_UART_Receive_IT(serial,&incoming,1);
}
static void accept_command(uint32_t now){
    if(strcmp(command,"STOP")==0){MotorPosition_Stop(&experiment,now,"MANUAL_STOP",false);return;}
    char candidate[9]={0},extra;unsigned id=0;
    if(sscanf(command,"SESSION %8[0-9A-F] %u %c",candidate,&id,&extra)==2 && strlen(candidate)==8U){
        if(id!=PICO_ENABLE_MOTOR_ID || experiment.core.run_requested){line("# SESSION_REJECTED\r\n");return;}
        memcpy(token,candidate,9);session_uart_errors=uart_errors;MotorPosition_Heartbeat(&experiment,now);
        char s[100];(void)snprintf(s,sizeof(s),"# SESSION_OK token=%s id=%u\r\n",token,id);line(s);return;
    }
    if(!token[0])return;
    if(sscanf(command,"KEEP %8s %c",candidate,&extra)==1 && strcmp(candidate,token)==0){
        MotorPosition_Heartbeat(&experiment,now);return;
    }
    if(sscanf(command,EXPERIMENT_COMMAND " %8s %c",candidate,&extra)==1 && strcmp(candidate,token)==0){
        if(!MotorPosition_Request(&experiment,now))line("# " EXPERIMENT_TAG "_REJECTED not_ready_or_stale_session\r\n");
        return;
    }
    line("# COMMAND_REJECTED\r\n");
}
void MotorEnableApp_Init(FDCAN_HandleTypeDef *can,UART_HandleTypeDef *uart){
    bus=can;serial=uart;
    /* Arm RX before printing any banner: the PC may answer its first line
       while we are still transmitting the remaining startup text. */
    __HAL_UART_CLEAR_FLAG(serial,UART_CLEAR_OREF|UART_CLEAR_FEF|UART_CLEAR_NEF|UART_CLEAR_PEF);
    __HAL_UART_SEND_REQ(serial,UART_RXDATA_FLUSH_REQUEST);
    HAL_NVIC_SetPriority(LPUART1_IRQn,0,0);HAL_NVIC_EnableIRQ(LPUART1_IRQn);
    if(HAL_UART_Receive_IT(serial,&incoming,1)!=HAL_OK){line("# ENABLE_FATAL UART RX initialization failed\r\n");return;}
    char s[400];(void)snprintf(s,sizeof(s),
        "# PICO_MOTOR_" EXPERIMENT_TAG "=1; channel=FDCAN1 bitrate=1000000 model=%s motor_id=%u host_id=253 max_enable_ms=90000 host_timeout_ms=500 " EXPERIMENT_PARAMETERS "\r\n",
        PICO_ENABLE_MODEL,(unsigned)PICO_ENABLE_MOTOR_ID);line(s);
 line(ROBSTRIDE_SPC_BANNER);
    line("# TX=PA12 RX=PA11 AF9; boot=STOP; run_mode=5; origin=measured; no flash-save/ID/baud/zero-cal commands\r\n");
    if(!CanTransport_Init(can,1000000U,CAN_FILTER_MOTOR,0xFDU,log_frame)){
        line("# ENABLE_FATAL CAN initialization failed\r\n");return;
    }
    MotorPosition_Init(&experiment,PICO_ENABLE_MOTOR_ID,0xFD,HAL_GetTick());
    next_health=HAL_GetTick()+500U;ready=true;
    line("# " EXPERIMENT_TAG "_COMMAND_READY=1; protocol=2\r\n");
}
void MotorEnableApp_Step(void){
    if(!ready)return;
    uint32_t now=HAL_GetTick();
    if(rx_resync){
        /* A partial command must never be interpreted after UART data loss.
           Before authentication the host can retry SESSION; after it, fail closed. */
        uint32_t irq=__get_PRIMASK();__disable_irq();rd=wr;rx_resync=false;__set_PRIMASK(irq);
        command_used=0;
    }
    while(rd!=wr){
        uint8_t c=ring[rd];rd=(rd+1U)%sizeof(ring);
        if(c=='\n'){
            command[command_used]=0;accept_command(now);command_used=0;
        }else if(c!='\r'){
            if(command_used+1U<sizeof(command))command[command_used++]=(char)c;
            else{command_used=0;++uart_errors;}
        }
    }
    CanTransport_Service(now);CanFrame f;
    while(CanTransport_Receive(&f)){log_frame("RX",&f);MotorPosition_OnFrame(&experiment,&f,now);}
    CanTransportStats stats=CanTransport_GetStats();
    if((stats.tx_timed_out||stats.bus_off||stats.rx_fifo_lost||stats.rx_queue_dropped||stats.rx_read_failed||
        stats.tx_event_lost||stats.tx_event_unknown||stats.tx_rejected) && !experiment.core.finishing)
        MotorPosition_Stop(&experiment,now,"CAN_LINK_ERROR",true);
    if((uart_failed || (token[0] && uart_errors!=session_uart_errors)) && !experiment.core.finishing)
        MotorPosition_Stop(&experiment,now,"UART_LINK_ERROR",true);
    if(experiment.core.abort_pending){
        uint32_t pending=bus->Instance->TXBRP;
        if(pending)(void)HAL_FDCAN_AbortTxRequest(bus,pending);
        experiment.core.abort_pending=false;
    }
    MotorPosition_Step(&experiment,now,send_frame,0);
    if(old_phase!=(uint32_t)experiment.core.phase || reported_waypoints!=experiment.waypoints || (int32_t)(now-next_health)>=0){
        if(reported_waypoints!=experiment.waypoints){
            char record[220];(void)snprintf(record,sizeof(record),
                "# POSITION_WAYPOINT,id=%u,completed=%u,cycle=%u,leg=%u,target_delta_urad=%ld,arrival_error_urad=%ld\r\n",
                (unsigned)experiment.core.id,experiment.waypoints,(experiment.waypoints-1U)/4U+1U,(experiment.waypoints-1U)%4U+1U,
                (long)((experiment.last_target-experiment.origin)*1000000.0f),(long)(experiment.last_arrival_error*1000000.0f));line(record);
        }
        old_phase=(uint32_t)experiment.core.phase;reported_waypoints=experiment.waypoints;next_health=now+500U;
        FDCAN_ErrorCountersTypeDef errors={0};(void)HAL_FDCAN_GetErrorCounters(bus,&errors);
        char s[1000];(void)snprintf(s,sizeof(s),
            "# " EXPERIMENT_TAG "_STATE,state=%s,id=%u,reason=%s,enable_confirmed=%u,stop_confirmed=%u,stop_unconfirmed=%u,error=%u,iq_mA=%ld,iq_samples=%lu,feedbacks=%lu,tx_done=%lu,tec=%lu,rec=%lu,bus_off=%lu,uart_rx=%lu,uart_errors=%lu,uart_error=0x%lX,velocity_mrad_s=%ld,delta_mrad=%ld,motion_confirmed=%u,target_cleared=%u,cycles_completed=%u,waypoints_completed=%u,target_delta_mrad=%ld,max_arrival_error_mrad=%ld,max_return_error_mrad=%ld,peak_iq_mA=%ld,neutralize_failed=%u,stable_span_urad=%ld,stable_elapsed_ms=%lu,stable_samples=%lu,stable_velocity_mrad_s=%ld,position_step_speed_mrad_s=%ld,position_mean_speed_mrad_s=%ld\r\n",
            MotorPosition_Name(&experiment),(unsigned)experiment.core.id,experiment.core.reason,
            experiment.core.enable_confirmed?1U:0U,experiment.core.stop_confirmed?1U:0U,experiment.core.stop_unconfirmed?1U:0U,experiment.core.error?1U:0U,
            (long)(experiment.core.iq*1000.0f),(unsigned long)experiment.core.iq_samples,(unsigned long)experiment.core.feedbacks,
            (unsigned long)stats.tx_completed,(unsigned long)errors.TxErrorCnt,(unsigned long)errors.RxErrorCnt,(unsigned long)stats.bus_off,
            (unsigned long)uart_received,(unsigned long)uart_errors,(unsigned long)last_uart_error,
            (long)(experiment.core.velocity*1000.0f),(long)(experiment.core.position_delta*1000.0f),
            experiment.core.motion_confirmed?1U:0U,experiment.core.target_cleared?1U:0U,experiment.waypoints/4U,experiment.waypoints,
            (long)((experiment.target-experiment.origin)*1000.0f),(long)(experiment.max_arrival_error*1000.0f),
            (long)(experiment.max_return_error*1000.0f),(long)(experiment.peak_iq*1000.0f),experiment.neutralize_failed?1U:0U,(long)(experiment.stable_span*1000000.0f),
            (unsigned long)(experiment.settled?experiment.stable_last_at-experiment.settle_at:0U),(unsigned long)experiment.stable_samples,(long)(experiment.stable_velocity*1000.0f),(long)(experiment.sampled_position_speed*1000.0f),(long)(experiment.mean_position_speed*1000.0f));line(s);
    }
    if(experiment.core.phase==ME_DONE && !result_reported){
        bool pass=MotorPosition_Passed(&experiment);
        char s[300];(void)snprintf(s,sizeof(s),"# " EXPERIMENT_TAG "_RESULT,result=%s,id=%u,enable_confirmed=%u,stop_confirmed=%u,reason=%s,motion_confirmed=%u,target_cleared=%u\r\n",
            pass?"PASS":experiment.core.error?"FAIL":"STOPPED",(unsigned)experiment.core.id,
            experiment.core.enable_confirmed?1U:0U,experiment.core.stop_confirmed?1U:0U,experiment.core.reason,
            experiment.core.motion_confirmed?1U:0U,experiment.core.target_cleared?1U:0U);line(s);result_reported=true;
    }
}
