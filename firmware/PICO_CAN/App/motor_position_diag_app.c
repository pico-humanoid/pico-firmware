#include "protocol/robstride_spc.h"
#include "motor_enable_app.h"
#include "motor_position_diag.h"
#include "transport/can_transport.h"
#include <stdio.h>
#include <string.h>
static MotorPositionDiag diagnostic;
static FDCAN_HandleTypeDef *bus;static UART_HandleTypeDef *serial;
static bool ready,uart_failed;static uint32_t next_health,session_errors;
static uint8_t incoming;static volatile uint8_t ring[128];static volatile uint32_t received_at[128],wr,rd,uart_errors;
static volatile bool resync;static char token[9],command[64];static unsigned used;
static void line(const char *text){if(HAL_UART_Transmit(serial,(const uint8_t *)text,(uint16_t)strlen(text),100U)!=HAL_OK)uart_failed=true;}
static void cancel_pending(void){if(diagnostic.cancel_pending){diagnostic.cancel_pending=false;CanTransport_CancelPending(HAL_GetTick());}}
static bool submit(void *context,const CanFrame *frame,uint32_t now){(void)context;cancel_pending();return CanTransport_Submit(frame,now);}
static void log_frame(const char *event,const CanFrame *f){
 if(strcmp(event,"TX_DONE")==0)return;
 char s[180];int n=snprintf(s,sizeof(s),"%lu,%s,FDCAN1,EXT,DATA,0x%08lX,%u,",(unsigned long)f->timestamp_ms,event,(unsigned long)f->id,(unsigned)f->dlc);
 for(unsigned i=0;i<f->dlc;++i)n+=snprintf(s+n,sizeof(s)-(size_t)n,"%s%02X",i?" ":"",f->data[i]);
 (void)snprintf(s+n,sizeof(s)-(size_t)n,"\r\n");line(s);
}
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *uart){
 if(uart!=serial)return;
 uint32_t next=(wr+1U)%sizeof(ring);
 if(next==rd){++uart_errors;resync=true;}else{ring[wr]=incoming;received_at[wr]=HAL_GetTick();__DMB();wr=next;}
 if(HAL_UART_Receive_IT(serial,&incoming,1)!=HAL_OK)uart_failed=true;
}
void HAL_UART_ErrorCallback(UART_HandleTypeDef *uart){
 if(uart!=serial)return;
 ++uart_errors;resync=true;
 __HAL_UART_CLEAR_FLAG(serial,UART_CLEAR_OREF|UART_CLEAR_FEF|UART_CLEAR_NEF|UART_CLEAR_PEF);
 __HAL_UART_SEND_REQ(serial,UART_RXDATA_FLUSH_REQUEST);
 if(HAL_UART_Receive_IT(serial,&incoming,1)!=HAL_OK)uart_failed=true;
}
static void accept(uint32_t stamp){
 uint32_t now=HAL_GetTick();if(now-stamp>500U){line("# DIAG_REJECTED reason=STALE_UART_COMMAND\r\n");return;}
 if(strcmp(command,"STOP")==0){MotorPositionDiag_Stop(&diagnostic,now,"USER_STOP",false);return;}
 char candidate[9]={0},extra;unsigned id;
 if(sscanf(command,"SESSION %8[0-9A-F] %u %c",candidate,&id,&extra)==2&&strlen(candidate)==8U){
  if(id!=PICO_DIAG_MOTOR_ID||diagnostic.echo_active||diagnostic.echo_requested||diagnostic.echo_finished){line("# SESSION_REJECTED\r\n");return;}
  memcpy(token,candidate,9);session_errors=uart_errors;MotorPositionDiag_Heartbeat(&diagnostic,stamp);
  char s[80];(void)snprintf(s,sizeof(s),"# SESSION_OK token=%s id=%u\r\n",token,(unsigned)PICO_DIAG_MOTOR_ID);line(s);return;
 }
 if(!token[0])return;
 if(sscanf(command,"KEEP %8s %c",candidate,&extra)==1&&strcmp(candidate,token)==0){MotorPositionDiag_Heartbeat(&diagnostic,stamp);return;}
 if(sscanf(command,"VERIFY %8s %c",candidate,&extra)==1&&strcmp(candidate,token)==0){
  line(MotorPositionDiag_RequestEcho(&diagnostic,now)?"# DIAG_VERIFY_ACCEPTED\r\n":"# DIAG_REJECTED reason=STOP_UID_MODE_OR_SESSION_NOT_READY\r\n");return;
 }
 line("# DIAG_REJECTED reason=UNKNOWN_COMMAND\r\n");
}
void MotorEnableApp_Init(FDCAN_HandleTypeDef *can,UART_HandleTypeDef *uart){
 bus=can;serial=uart;ready=uart_failed=resync=false;wr=rd=uart_errors=session_errors=used=0;token[0]=0;
 __HAL_UART_CLEAR_FLAG(serial,UART_CLEAR_OREF|UART_CLEAR_FEF|UART_CLEAR_NEF|UART_CLEAR_PEF);
 __HAL_UART_SEND_REQ(serial,UART_RXDATA_FLUSH_REQUEST);HAL_NVIC_SetPriority(LPUART1_IRQn,0,0);HAL_NVIC_EnableIRQ(LPUART1_IRQn);
 if(HAL_UART_Receive_IT(serial,&incoming,1)!=HAL_OK){line("# DIAG_FATAL UART_RX\r\n");return;}
 char s[350];(void)snprintf(s,sizeof(s),"# PICO_MOTOR_POSITION_DIAG=1; channel=FDCAN1 bitrate=1000000 motor_id=%u model=" PICO_DIAG_MODEL " host_id=253 policy=STOPPED_ECHO_V1 no_enable=1 target_write=manual_current_position_only tx_policy=" CAN_TRANSPORT_TX_POLICY "\r\n",(unsigned)PICO_DIAG_MOTOR_ID);line(s);
 line(ROBSTRIDE_SPC_BANNER);
 line("# Baseline=STOP_UID_VERSION_PARAMETER_READS; VERIFY=manual_3_rounds_loc_ref_from_fresh_mechPos; no mode/limit/gain/ID/baud/zero/save writes\r\n");
 if(!CanTransport_Init(can,1000000U,CAN_FILTER_MOTOR_DIAG,253,log_frame)){line("# DIAG_FATAL CAN_INIT\r\n");return;}
 MotorPositionDiag_Init(&diagnostic,PICO_DIAG_MOTOR_ID,HAL_GetTick(),line);next_health=HAL_GetTick()+500U;ready=true;line("# DIAG_COMMAND_READY=1; protocol=2\r\n");
}
void MotorEnableApp_Step(void){
 if(!ready)return;
 if(resync){uint32_t irq=__get_PRIMASK();__disable_irq();rd=wr;resync=false;__set_PRIMASK(irq);used=0;}
 while(rd!=wr){uint8_t c=ring[rd];uint32_t stamp=received_at[rd];rd=(rd+1U)%sizeof(ring);
  if(c=='\n'){command[used]=0;accept(stamp);used=0;}
  else if(c!='\r'){if(used+1U<sizeof(command))command[used++]=(char)c;else{used=0;++uart_errors;resync=true;}}
 }
 uint32_t now=HAL_GetTick();CanTransport_Service(now);CanFrame f;
 while(CanTransport_Receive(&f)){log_frame("RX",&f);MotorPositionDiag_OnFrame(&diagnostic,&f,HAL_GetTick());}
 now=HAL_GetTick();CanTransportStats stats=CanTransport_GetStats();
 if(stats.tx_timed_out||stats.tx_rejected||stats.tx_event_lost||stats.tx_event_unknown||stats.bus_off||stats.rx_fifo_lost||stats.rx_queue_dropped||stats.rx_read_failed)MotorPositionDiag_Stop(&diagnostic,now,"CAN_LINK_ERROR",true);
 if(uart_failed||(token[0]&&uart_errors!=session_errors))MotorPositionDiag_Stop(&diagnostic,now,"UART_LINK_ERROR",true);
 cancel_pending();MotorPositionDiag_Step(&diagnostic,now,submit,0);cancel_pending();
 if((int32_t)(now-next_health)>=0){
  next_health=now+500U;FDCAN_ErrorCountersTypeDef ec={0};(void)HAL_FDCAN_GetErrorCounters(bus,&ec);char s[500];
  (void)snprintf(s,sizeof(s),"# DIAG_STATE,state=%s,id=%u,reason=%s,stop_confirmed=%u,uid_stable=%u,uid_samples=%u,echo_allowed=%u,echo_active=%u,echo_finished=%u,target_cleared=%u,error=%u,tec=%lu,rec=%lu,bus_off=%lu,uart_errors=%lu,no_enable=1\r\n",
   MotorPositionDiag_Name(&diagnostic),(unsigned)PICO_DIAG_MOTOR_ID,diagnostic.reason,diagnostic.stop_confirmed?1U:0U,diagnostic.uid_valid&&!diagnostic.uid_conflict?1U:0U,diagnostic.uid_samples,MotorPositionDiag_EchoAllowed(&diagnostic,now)?1U:0U,
   diagnostic.echo_active||diagnostic.echo_requested?1U:0U,diagnostic.echo_finished?1U:0U,diagnostic.target_cleared?1U:0U,diagnostic.failed?1U:0U,(unsigned long)ec.TxErrorCnt,(unsigned long)ec.RxErrorCnt,(unsigned long)stats.bus_off,(unsigned long)uart_errors);line(s);
 }
}
