#include "protocol/robstride_spc.h"
#include "motor_enable_app.h"
#include "motor_enable_logic.h"
#include "transport/can_transport.h"
#include <stdio.h>
#include <string.h>
#if defined(PICO_MOTOR_SPEED)
#define EXPERIMENT_TAG "SPEED"
#define EXPERIMENT_COMMAND "RUN"
#define EXPERIMENT_PARAMETERS "target_rad_s=0.3 current_limit_A=" SPEED_CURRENT_LIMIT_TEXT " accel_rad_s2=0.5 iq_trip_A=0.8 current_policy=" SPEED_CURRENT_POLICY
#else
#define EXPERIMENT_TAG "ENABLE"
#define EXPERIMENT_COMMAND "ENABLE"
#define EXPERIMENT_PARAMETERS "iq_ref_A=0"
#endif
static MotorEnable experiment;
static FDCAN_HandleTypeDef *bus;
static UART_HandleTypeDef *serial;
static bool ready,uart_failed,result_reported;
static uint32_t next_health,old_phase=0xFFFFFFFFU;
static char token[9],command[64];static unsigned command_used;
static uint8_t incoming;
static volatile uint8_t ring[128];static volatile uint32_t wr,rd,uart_errors,uart_received,last_uart_error;
static uint32_t session_uart_errors;
static volatile bool rx_resync;
static void line(const char *s){
    if(HAL_UART_Transmit(serial,(const uint8_t *)s,(uint16_t)strlen(s),100U)!=HAL_OK)uart_failed=true;
}
static void log_frame(const char *event,const CanFrame *f){
    char s[200];int used=snprintf(s,sizeof(s),"%lu,%s,FDCAN1,EXT,DATA,0x%08lX,%u,",
        (unsigned long)f->timestamp_ms,event,(unsigned long)f->id,(unsigned)f->dlc);
    for(uint32_t i=0;i<f->dlc;++i)used+=snprintf(s+used,sizeof(s)-(size_t)used,"%s%02X",i?" ":"",f->data[i]);
    (void)snprintf(s+used,sizeof(s)-(size_t)used,"\r\n");line(s);
}
static bool send_frame(void *context,const CanFrame *f,uint32_t now){
    (void)context;
    if((f->id>>24)==4U && experiment.abort_pending){
        uint32_t pending=bus->Instance->TXBRP;
        if(pending)(void)HAL_FDCAN_AbortTxRequest(bus,pending);
        experiment.abort_pending=false;
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
    if(strcmp(command,"STOP")==0){MotorEnable_Stop(&experiment,now,"MANUAL_STOP",false);return;}
    char candidate[9]={0},extra;unsigned id=0;
    if(sscanf(command,"SESSION %8[0-9A-F] %u %c",candidate,&id,&extra)==2 && strlen(candidate)==8U){
        if(id!=PICO_ENABLE_MOTOR_ID || experiment.run_requested){line("# SESSION_REJECTED\r\n");return;}
        memcpy(token,candidate,9);session_uart_errors=uart_errors;MotorEnable_Heartbeat(&experiment,now);
        char s[100];(void)snprintf(s,sizeof(s),"# SESSION_OK token=%s id=%u\r\n",token,id);line(s);return;
    }
    if(!token[0])return;
    if(sscanf(command,"KEEP %8s %c",candidate,&extra)==1 && strcmp(candidate,token)==0){
        MotorEnable_Heartbeat(&experiment,now);return;
    }
    if(sscanf(command,EXPERIMENT_COMMAND " %8s %c",candidate,&extra)==1 && strcmp(candidate,token)==0){
        if(!MotorEnable_Request(&experiment,now))line("# " EXPERIMENT_TAG "_REJECTED not_ready_or_stale_session\r\n");
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
        "# PICO_MOTOR_" EXPERIMENT_TAG "=1; channel=FDCAN1 bitrate=1000000 model=%s motor_id=%u host_id=253 max_enable_ms=3000 host_timeout_ms=500 " EXPERIMENT_PARAMETERS "\r\n",
        PICO_ENABLE_MODEL,(unsigned)PICO_ENABLE_MOTOR_ID);line(s);
 line(ROBSTRIDE_SPC_BANNER);
#if defined(PICO_MOTOR_SPEED)
    line("# SPEED_LIMITS,target_rad_s=0.3,current_limit_A=" SPEED_CURRENT_LIMIT_TEXT ",accel_rad_s2=0.5,iq_trip_A=0.8,speed_trip_rad_s=0.6,displacement_trip_rad=1.2\r\n");
    line("# TX=PA12 RX=PA11 AF9; boot=STOP; zero speed and limits readback required before motion; no flash-save/ID/baud/zero-cal commands\r\n");
#else
    line("# TX=PA12 RX=PA11 AF9; boot=STOP; run_mode=3 and iq_ref=0 readback required before enable; no flash-save/ID/baud/zero-cal commands\r\n");
#endif
    if(!CanTransport_Init(can,1000000U,CAN_FILTER_MOTOR,0xFDU,log_frame)){
        line("# ENABLE_FATAL CAN initialization failed\r\n");return;
    }
#if defined(PICO_MOTOR_SPEED)
    MotorEnable_InitSpeed(&experiment,PICO_ENABLE_MOTOR_ID,0xFD,HAL_GetTick());
#else
    MotorEnable_Init(&experiment,PICO_ENABLE_MOTOR_ID,0xFD,HAL_GetTick());
#endif
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
    while(CanTransport_Receive(&f)){log_frame("RX",&f);MotorEnable_OnFrame(&experiment,&f,now);}
    CanTransportStats stats=CanTransport_GetStats();
    if((stats.tx_timed_out||stats.bus_off||stats.rx_fifo_lost||stats.rx_queue_dropped||stats.rx_read_failed||
        stats.tx_event_lost||stats.tx_event_unknown||stats.tx_rejected) && !experiment.finishing)
        MotorEnable_Stop(&experiment,now,"CAN_LINK_ERROR",true);
    if((uart_failed || (token[0] && uart_errors!=session_uart_errors)) && !experiment.finishing)
        MotorEnable_Stop(&experiment,now,"UART_LINK_ERROR",true);
    if(experiment.abort_pending){
        uint32_t pending=bus->Instance->TXBRP;
        if(pending)(void)HAL_FDCAN_AbortTxRequest(bus,pending);
        experiment.abort_pending=false;
    }
    MotorEnable_Step(&experiment,now,send_frame,0);
    if(old_phase!=(uint32_t)experiment.phase || (int32_t)(now-next_health)>=0){
        old_phase=(uint32_t)experiment.phase;next_health=now+500U;
        FDCAN_ErrorCountersTypeDef errors={0};(void)HAL_FDCAN_GetErrorCounters(bus,&errors);
        char s[600];(void)snprintf(s,sizeof(s),
            "# " EXPERIMENT_TAG "_STATE,state=%s,id=%u,reason=%s,enable_confirmed=%u,stop_confirmed=%u,stop_unconfirmed=%u,error=%u,iq_mA=%ld,iq_samples=%lu,feedbacks=%lu,tx_done=%lu,tec=%lu,rec=%lu,bus_off=%lu,uart_rx=%lu,uart_errors=%lu,uart_error=0x%lX,velocity_mrad_s=%ld,delta_mrad=%ld,motion_confirmed=%u,target_cleared=%u\r\n",
            MotorEnable_Name(experiment.phase),(unsigned)experiment.id,experiment.reason,
            experiment.enable_confirmed?1U:0U,experiment.stop_confirmed?1U:0U,experiment.stop_unconfirmed?1U:0U,experiment.error?1U:0U,
            (long)(experiment.iq*1000.0f),(unsigned long)experiment.iq_samples,(unsigned long)experiment.feedbacks,
            (unsigned long)stats.tx_completed,(unsigned long)errors.TxErrorCnt,(unsigned long)errors.RxErrorCnt,(unsigned long)stats.bus_off,
            (unsigned long)uart_received,(unsigned long)uart_errors,(unsigned long)last_uart_error,
            (long)(experiment.velocity*1000.0f),(long)(experiment.position_delta*1000.0f),
            experiment.motion_confirmed?1U:0U,experiment.target_cleared?1U:0U);line(s);
    }
    if(experiment.phase==ME_DONE && !result_reported){
        bool pass=experiment.run_requested && experiment.enable_confirmed && experiment.stop_confirmed &&
            experiment.iq_samples>0U && !experiment.error && strcmp(experiment.reason,"AUTO_STOP")==0 &&
            (!experiment.speed_test||(experiment.motion_confirmed&&experiment.target_cleared&&experiment.velocity_samples>0U&&experiment.position_samples>0U));
        char s[300];(void)snprintf(s,sizeof(s),"# " EXPERIMENT_TAG "_RESULT,result=%s,id=%u,enable_confirmed=%u,stop_confirmed=%u,reason=%s,motion_confirmed=%u,target_cleared=%u\r\n",
            pass?"PASS":experiment.error?"FAIL":"STOPPED",(unsigned)experiment.id,
            experiment.enable_confirmed?1U:0U,experiment.stop_confirmed?1U:0U,experiment.reason,
            experiment.motion_confirmed?1U:0U,experiment.target_cleared?1U:0U);line(s);result_reported=true;
    }
}
