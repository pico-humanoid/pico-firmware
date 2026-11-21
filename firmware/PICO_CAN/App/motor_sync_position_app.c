#include "protocol/robstride_spc.h"
/* Operator-triggered shared-clock position experiment. UART output never waits. */
#include "motor_enable_app.h"
#include "motor_sync_logic.h"
#include "transport/can_transport.h"
#include <stdio.h>
#include <string.h>
static MotorSync group;
static FDCAN_HandleTypeDef *bus;static UART_HandleTypeDef *serial;
static bool ready,result_reported,start_reported,can_reported;
static volatile bool uart_failed,rx_resync;
static uint8_t incoming;static volatile uint8_t rx_ring[128];
static volatile uint32_t wr,rd,uart_errors,uart_received,last_uart_error;
static uint8_t tx_ring[8192];static volatile uint32_t tx_write,tx_read;
static volatile uint16_t tx_active;static uint32_t tx_high_water;
static uint32_t next_health,session_uart_errors,normal_feedback_at[2],reported_phase[2],reported_segments;
static uint32_t pair_first_at,max_pair_skew;static unsigned pair_first_id;
static char token[9],command[64];static unsigned command_used;
static void kick_tx(void){
 if(tx_active||tx_read==tx_write)return;
 uint32_t index=tx_read%sizeof(tx_ring),n=tx_write-tx_read;
 if(n>sizeof(tx_ring)-index)n=sizeof(tx_ring)-index;
 if(n>128U)n=128U;
 tx_active=(uint16_t)n;
 if(HAL_UART_Transmit_IT(serial,tx_ring+index,(uint16_t)n)!=HAL_OK){tx_active=0;uart_failed=true;}
}
static void line(const char *s){
 /* Main is the only producer. Copy with interrupts enabled so long status
    lines cannot overrun incoming KEEP bytes. Publish only after the copy;
    the consumer never sees this reserved but unfinished tail. */
 size_t n=strlen(s);uint32_t tail=tx_write;
 if(n>sizeof(tx_ring)-(tail-tx_read)){uart_failed=true;return;}
 for(size_t i=0;i<n;++i)tx_ring[(tail+(uint32_t)i)%sizeof(tx_ring)]=(uint8_t)s[i];
 __DMB();uint32_t irq=__get_PRIMASK();__disable_irq();tx_write=tail+(uint32_t)n;
 uint32_t queued=tx_write-tx_read;if(queued>tx_high_water)tx_high_water=queued;
 kick_tx();__set_PRIMASK(irq);
}
void HAL_UART_TxCpltCallback(UART_HandleTypeDef *uart){if(uart==serial){tx_read+=tx_active;tx_active=0;kick_tx();}}
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *uart){
 if(uart!=serial)return;
 ++uart_received;uint32_t next=(wr+1U)%sizeof(rx_ring);
 if(next==rd){++uart_errors;rx_resync=true;}else{rx_ring[wr]=incoming;__DMB();wr=next;}
 if(HAL_UART_Receive_IT(serial,&incoming,1)!=HAL_OK)uart_failed=true;
}
void HAL_UART_ErrorCallback(UART_HandleTypeDef *uart){
 if(uart!=serial)return;
 ++uart_errors;last_uart_error=uart->ErrorCode;rx_resync=true;
 __HAL_UART_CLEAR_FLAG(serial,UART_CLEAR_OREF|UART_CLEAR_FEF|UART_CLEAR_NEF|UART_CLEAR_PEF);
 __HAL_UART_SEND_REQ(serial,UART_RXDATA_FLUSH_REQUEST);
 if(HAL_UART_Receive_IT(serial,&incoming,1)!=HAL_OK)uart_failed=true;
}
static void abort_pending(void){
 bool cancel=false;for(unsigned i=0;i<2;++i)if(group.motors[i].core.abort_pending){cancel=true;group.motors[i].core.abort_pending=false;}
 if(cancel)CanTransport_CancelPending(HAL_GetTick());
}
static void report_start(void){
 if(start_reported||!group.started)return;
 start_reported=true;
 char s[180];(void)snprintf(s,sizeof(s),"# SYNC_POSITION_START,t_ms=%lu,duration_ms=40000,segment_ms=2000,target_period_ms=50\r\n",(unsigned long)group.started_at);line(s);
 for(unsigned i=0;i<2;++i){(void)snprintf(s,sizeof(s),"# SYNC_POSITION_ORIGIN,id=%u,position_urad=%ld\r\n",i+1U,(long)(group.motors[i].origin*1000000.0f));line(s);}
}
static bool send_frame(void *context,const CanFrame *f,uint32_t now){
 (void)context;(void)now;abort_pending();report_start();uint32_t at=HAL_GetTick();
 if(group.started&&!group.motors[0].core.finishing&&(f->id>>24)==18U&&f->data[0]==0x16U){
  unsigned id=f->id&255U;
  if(id==1U){pair_first_at=at;pair_first_id=1;}
  else if(id==2U&&pair_first_id==1U){uint32_t skew=at-pair_first_at;if(skew>max_pair_skew)max_pair_skew=skew;pair_first_id=0;}
 }
 return CanTransport_Submit(f,at);
}
static void log_frame(const char *event,const CanFrame *f){
 if(strcmp(event,"TX_DONE")==0)return;
 unsigned id=strcmp(event,"RX")==0?(f->id>>8)&255U:f->id&255U;
 unsigned type=(f->id>>24)&31U,index=f->data[0]|((unsigned)f->data[1]<<8);
 if(id>=1U&&id<=2U){MotorPosition *p=&group.motors[id-1U];
  if(strcmp(event,"TX_SUBMIT")==0&&p->stage==MP_MOVE&&!p->core.finishing&&type==17U&&index>=0x7019U&&index<=0x701BU)return;
  /* Normal mode-2 acks repeat at target rate. Sample them at 1Hz, while all
     faults, parameter RX and submitted position targets remain in the log. */
  if(strcmp(event,"RX")==0&&type==2U&&((f->id>>22)&3U)==2U&&((f->id>>16)&63U)==0U&&group.started&&!p->core.finishing){
   if(f->timestamp_ms-normal_feedback_at[id-1U]<1000U)return;
   normal_feedback_at[id-1U]=f->timestamp_ms;
  }
 }
 char s[180];int used=snprintf(s,sizeof(s),"%lu,%s,FDCAN1,EXT,DATA,0x%08lX,%u,",(unsigned long)f->timestamp_ms,event,(unsigned long)f->id,(unsigned)f->dlc);
 for(unsigned i=0;i<f->dlc;++i)used+=snprintf(s+used,sizeof(s)-(size_t)used,"%s%02X",i?" ":"",f->data[i]);
 (void)snprintf(s+used,sizeof(s)-(size_t)used,"\r\n");line(s);
}
static void accept_command(uint32_t now){
 if(strcmp(command,"STOP")==0){MotorSync_Stop(&group,now,"MANUAL_STOP",false);return;}
 char candidate[9]={0},extra;unsigned id=0;
 if(sscanf(command,"SESSION %8[0-9A-F] %u %c",candidate,&id,&extra)==2&&strlen(candidate)==8U){
  if(id!=0U||group.motors[0].core.run_requested||group.motors[1].core.run_requested){line("# SESSION_REJECTED\r\n");return;}
  memcpy(token,candidate,9);session_uart_errors=uart_errors;MotorSync_Heartbeat(&group,now);
  char s[70];(void)snprintf(s,sizeof(s),"# SESSION_OK token=%s id=0\r\n",token);line(s);return;
 }
 if(!token[0])return;
 if(sscanf(command,"KEEP %8s %c",candidate,&extra)==1&&strcmp(candidate,token)==0){MotorSync_Heartbeat(&group,now);return;}
 if(sscanf(command,"RUN %8s %c",candidate,&extra)==1&&strcmp(candidate,token)==0){
  if(!MotorSync_Request(&group,now))line("# SYNC_POSITION_REJECTED both_motors_must_be_ready\r\n");
  return;
 }
 line("# COMMAND_REJECTED\r\n");
}
void MotorEnableApp_Init(FDCAN_HandleTypeDef *can,UART_HandleTypeDef *uart){
 bus=can;serial=uart;ready=result_reported=start_reported=can_reported=uart_failed=rx_resync=false;
 wr=rd=uart_errors=uart_received=last_uart_error=tx_write=tx_read=tx_high_water=0;tx_active=0;
 command_used=0;token[0]=0;session_uart_errors=reported_segments=max_pair_skew=pair_first_id=0;
 memset(normal_feedback_at,0,sizeof(normal_feedback_at));reported_phase[0]=reported_phase[1]=0xFFFFFFFFU;
 MotorSync_Init(&group,HAL_GetTick());
 __HAL_UART_CLEAR_FLAG(serial,UART_CLEAR_OREF|UART_CLEAR_FEF|UART_CLEAR_NEF|UART_CLEAR_PEF);
 __HAL_UART_SEND_REQ(serial,UART_RXDATA_FLUSH_REQUEST);HAL_NVIC_SetPriority(LPUART1_IRQn,0,0);HAL_NVIC_EnableIRQ(LPUART1_IRQn);
 if(HAL_UART_Receive_IT(serial,&incoming,1)!=HAL_OK){uart_failed=true;return;}
 line("# PICO_MOTOR_SYNC_POSITION=1; channel=FDCAN1 bitrate=1000000 models=RS10P,RS00 motor_ids=1,2 host_id=253 trajectory=QUINTIC_V1 angle1_deg=5 angle2_deg=-3 cycles=5 segment_ms=2000 duration_ms=40000 target_period_ms=50 max_enable_ms=90000 host_timeout_ms=500 speed_limit_rad_s=0.2 current_limit_A=0.5 tracking_peak_deg=2 tracking_rms_deg=1 arrival_policy=POSITION_WINDOW_V3 tx_policy=" CAN_TRANSPORT_TX_POLICY " tx_deadline_ms=300\r\n");
 line(ROBSTRIDE_SPC_BANNER);
 line("# TX=PA12 RX=PA11 AF9; boot=STOP_BOTH; manual_RUN_only; both_postchecks_and_live_samples_required; no flash-save/ID/baud/zero-cal; uart_tx=NONBLOCKING; parameter_RX_all target_TX_all running_mode2_RX_sampled_1Hz; no_hardware_sync_claim\r\n");
 if(!CanTransport_Init(can,1000000U,CAN_FILTER_MOTOR,253,log_frame)){line("# SYNC_POSITION_FATAL CAN initialization failed\r\n");return;}
 next_health=HAL_GetTick()+1000U;ready=true;line("# SYNC_POSITION_COMMAND_READY=1; protocol=2\r\n");
}
static const char *state_name(const MotorPosition *p){
 if(group.started&&p->core.phase==ME_ACTIVE&&!p->core.finishing&&p->stage==MP_MOVE)return group.settling?"SYNC_SETTLING":"SYNC_TRACKING";
 return MotorPosition_Name(p);
}
void MotorEnableApp_Step(void){
 if(!ready)return;
 uint32_t now=HAL_GetTick();
 if(rx_resync){uint32_t irq=__get_PRIMASK();__disable_irq();rd=wr;rx_resync=false;__set_PRIMASK(irq);command_used=0;}
 while(rd!=wr){uint8_t c=rx_ring[rd];rd=(rd+1U)%sizeof(rx_ring);
  if(c=='\n'){command[command_used]=0;accept_command(now);command_used=0;}
  else if(c!='\r'){if(command_used+1U<sizeof(command))command[command_used++]=(char)c;else{command_used=0;++uart_errors;rx_resync=true;}}
 }
 CanTransport_Service(now);CanFrame f;
 while(CanTransport_Receive(&f)){
  now=HAL_GetTick();log_frame("RX",&f);
  if(now-f.timestamp_ms>500U){MotorSync_Stop(&group,now,"STALE_RX_QUEUE",true);continue;}
  uint32_t before[2]={group.metrics[0].at[1],group.metrics[1].at[1]};MotorSync_OnFrame(&group,&f,now);
  for(unsigned i=0;i<2;++i)if(group.metrics[i].history&&group.metrics[i].at[1]!=before[i]){
   MotorPosition *p=&group.motors[i];MotorSyncMetrics *m=&group.metrics[i];
   float ref=p->amplitude_rad*MotorSync_UnitReference(f.timestamp_ms-group.started_at);
   char sample[200];(void)snprintf(sample,sizeof(sample),"# SYNC_POSITION_SAMPLE,t_ms=%lu,id=%u,reference_urad=%ld,actual_urad=%ld,error_urad=%ld\r\n",
    (unsigned long)f.timestamp_ms,i+1U,(long)(ref*1000000.0f),(long)((m->position[1]-p->origin)*1000000.0f),(long)(m->last_error*1000000.0f));line(sample);
  }
 }
 now=HAL_GetTick();CanTransportStats stats=CanTransport_GetStats();
 if(stats.tx_timed_out||stats.tx_rejected||stats.tx_event_lost||stats.tx_event_unknown||stats.bus_off||stats.rx_fifo_lost||stats.rx_queue_dropped||stats.rx_read_failed){
  MotorSync_Stop(&group,now,stats.tx_timed_out?"CAN_TX_TIMEOUT":"CAN_LINK_ERROR",true);
  if(!can_reported){char d[350];(void)snprintf(d,sizeof(d),"# CAN_FAULT_DETAIL,t_ms=%lu,tx_timed_out=%lu,tx_rejected=%lu,tx_event_lost=%lu,tx_event_unknown=%lu,bus_off=%lu,tx_pending=0x%lX,tx_transmitted=0x%lX,tx_cancelled=0x%lX,psr=0x%lX\r\n",
    (unsigned long)now,(unsigned long)stats.tx_timed_out,(unsigned long)stats.tx_rejected,(unsigned long)stats.tx_event_lost,(unsigned long)stats.tx_event_unknown,(unsigned long)stats.bus_off,
    (unsigned long)bus->Instance->TXBRP,(unsigned long)bus->Instance->TXBTO,(unsigned long)bus->Instance->TXBCF,(unsigned long)bus->Instance->PSR);line(d);can_reported=true;}
 }
 if(uart_failed||(token[0]&&uart_errors!=session_uart_errors))MotorSync_Stop(&group,now,"UART_LINK_ERROR",true);
 abort_pending();MotorSync_Step(&group,now,CanTransport_AvailableSlots(),send_frame,0);abort_pending();report_start();
 if(group.segments!=reported_segments){reported_segments=group.segments;char s[130];(void)snprintf(s,sizeof(s),"# SYNC_POSITION_SEGMENT,completed=%lu,total=20,elapsed_ms=%lu\r\n",(unsigned long)group.segments,(unsigned long)group.elapsed);line(s);}
 for(unsigned i=0;i<2;++i){MotorPosition *p=&group.motors[i];uint32_t phase=(uint32_t)p->core.phase*32U+(uint32_t)p->stage+(group.settling?512U:0U);
  if(phase!=reported_phase[i]){reported_phase[i]=phase;char s[160];(void)snprintf(s,sizeof(s),"# SYNC_POSITION_PHASE,id=%u,state=%s,reason=%s\r\n",i+1U,state_name(p),p->core.reason);line(s);}
 }
 bool done=group.motors[0].core.phase==ME_DONE&&group.motors[1].core.phase==ME_DONE;
 if((int32_t)(now-next_health)>=0||(done&&!result_reported)){
  next_health=now+1000U;FDCAN_ErrorCountersTypeDef errors={0};(void)HAL_FDCAN_GetErrorCounters(bus,&errors);
  for(unsigned i=0;i<2;++i){MotorPosition *p=&group.motors[i];MotorEnable *e=&p->core;MotorSyncMetrics *m=&group.metrics[i];char s[1050];
   (void)snprintf(s,sizeof(s),"# SYNC_POSITION_STATE,state=%s,id=%u,reason=%s,enable_confirmed=%u,stop_confirmed=%u,stop_unconfirmed=%u,error=%u,iq_mA=%ld,tec=%lu,rec=%lu,bus_off=%lu,uart_errors=%lu,uart_error=0x%lX,target_cleared=%u,motion_confirmed=%u,elapsed_ms=%lu,cycles_completed=%lu,segments_completed=%lu,delta_urad=%ld,target_delta_urad=%ld,tracking_peak_urad=%ld,tracking_rms_urad=%ld,tracking_samples=%lu,peak_iq_mA=%ld,tx_done=%lu,tx_cancelled=%lu,pairs=%lu,max_lateness_ms=%lu,max_pair_skew_ms=%lu,progress_valid=%u,progress_gap_ppm=%ld,max_progress_gap_ppm=%ld,progress_at_ms=%lu,uart_tx_high_water=%lu\r\n",
    state_name(p),i+1U,e->reason,e->enable_confirmed?1U:0U,e->stop_confirmed?1U:0U,e->stop_unconfirmed?1U:0U,e->error?1U:0U,(long)(e->iq*1000),
    (unsigned long)errors.TxErrorCnt,(unsigned long)errors.RxErrorCnt,(unsigned long)stats.bus_off,(unsigned long)uart_errors,(unsigned long)last_uart_error,e->target_cleared?1U:0U,e->motion_confirmed?1U:0U,
    (unsigned long)group.elapsed,(unsigned long)(group.segments/4U),(unsigned long)group.segments,(long)((p->actual-p->origin)*1000000),(long)((p->target-p->origin)*1000000),
    (long)(m->peak*1000000),(long)(MotorSync_Rms(m)*1000000),(unsigned long)m->samples,(long)(p->peak_iq*1000),(unsigned long)stats.tx_completed,(unsigned long)stats.tx_cancelled,
    (unsigned long)group.pairs,(unsigned long)group.max_lateness_ms,(unsigned long)max_pair_skew,group.progress_valid?1U:0U,(long)(group.progress_gap*1000000),(long)(group.max_progress_gap*1000000),
    (unsigned long)group.progress_at,(unsigned long)tx_high_water);line(s);
  }
 }
 if(done&&!result_reported){char s[300];bool pass=MotorSync_Passed(&group);(void)snprintf(s,sizeof(s),"# SYNC_POSITION_RESULT,result=%s,motor_ids=1,2,enable_confirmed=%u,stop_confirmed=%u,motion_confirmed=%u,target_cleared=%u,reason=%s\r\n",
   pass?"PASS":group.failure||group.motors[0].core.error||group.motors[1].core.error?"FAIL":"STOPPED",
   group.motors[0].core.enable_confirmed&&group.motors[1].core.enable_confirmed?1U:0U,group.motors[0].core.stop_confirmed&&group.motors[1].core.stop_confirmed?1U:0U,
   group.motors[0].core.motion_confirmed&&group.motors[1].core.motion_confirmed?1U:0U,group.motors[0].core.target_cleared&&group.motors[1].core.target_cleared?1U:0U,
   pass?"BOTH_SYNC_TRAJECTORY_COMPLETE":"SEE_PER_MOTOR_STATE");line(s);result_reported=true;
 }
}
