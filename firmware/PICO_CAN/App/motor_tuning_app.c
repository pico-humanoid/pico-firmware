#include "motor_enable_app.h"
#include "motor_tuning.h"
#include "transport/can_transport.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#ifndef PICO_TUNE_MOTOR_ID
#define PICO_TUNE_MOTOR_ID 1
#endif
#ifndef PICO_TUNE_MODEL
#define PICO_TUNE_MODEL "RS10P"
#endif
#ifndef PICO_TUNE_COUNT
#define PICO_TUNE_COUNT 1
#endif
static MotorTuning motor,motor2;
static bool group_stopping,group_reported;static unsigned first_motor;
static MotorTuning *item(unsigned i){return i?&motor2:&motor;}
static FDCAN_HandleTypeDef *bus;static UART_HandleTypeDef *serial;
static bool ready;static volatile bool uart_failed,rx_resync;
static uint8_t incoming;static volatile uint8_t rx_ring[256];static volatile uint32_t rx_at[256];
static volatile uint32_t wr,rd,uart_errors,uart_received,last_uart_error;
static uint8_t tx_ring[8192];static volatile uint32_t tx_write,tx_read;
static volatile uint16_t tx_active;static uint32_t tx_high_water,session_uart_errors,next_health,last_sample[2],last_emit[2],command_at;
static char token[9],command[128];static unsigned command_used;
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
 if(next==rd){++uart_errors;rx_resync=true;}else{rx_ring[wr]=incoming;rx_at[wr]=HAL_GetTick();__DMB();wr=next;}
 if(HAL_UART_Receive_IT(serial,&incoming,1)!=HAL_OK)uart_failed=true;
}
void HAL_UART_ErrorCallback(UART_HandleTypeDef *uart){
 if(uart!=serial)return;
 ++uart_errors;last_uart_error=uart->ErrorCode;rx_resync=true;
 __HAL_UART_CLEAR_FLAG(serial,UART_CLEAR_OREF|UART_CLEAR_FEF|UART_CLEAR_NEF|UART_CLEAR_PEF);
 __HAL_UART_SEND_REQ(serial,UART_RXDATA_FLUSH_REQUEST);
 if(HAL_UART_Receive_IT(serial,&incoming,1)!=HAL_OK)uart_failed=true;
}


static void stop_all(uint32_t now,const char *reason,bool error){for(unsigned i=0;i<PICO_TUNE_COUNT;++i)MotorTuning_Stop(item(i),now,reason,error);}
static void peer_guard(uint32_t now){
 if(PICO_TUNE_COUNT!=2||group_stopping)return;
 for(unsigned i=0;i<2;++i){MotorTuning *t=item(i);if(t->error||t->stage>=TU_STOP){group_stopping=true;stop_all(now,t->reason,t->error);return;}}
}
static void cancel(void){bool needed=false;for(unsigned i=0;i<PICO_TUNE_COUNT;++i){needed|=item(i)->cancel_pending;item(i)->cancel_pending=false;}if(needed)CanTransport_CancelPending(HAL_GetTick());}
static bool send_frame(void *ctx,const CanFrame *f,uint32_t now){
 MotorTuning *t=ctx;peer_guard(now);cancel();
 if(group_stopping&&t&&t->stage==TU_STOP&&(f->id>>24)!=4U)return false;
 return CanTransport_Submit(f,now);
}
static void log_frame(const char *event,const CanFrame *f){
 if(!strcmp(event,"TX_DONE"))return;
 unsigned type=(f->id>>24)&31U;bool rx=!strcmp(event,"RX");unsigned id=rx?(f->id>>8)&255U:f->id&255U;
 MotorTuning *t=NULL;for(unsigned i=0;i<PICO_TUNE_COUNT;++i)if(item(i)->id==id)t=item(i);
 if(t&&(t->stage==TU_ACTIVE||t->stage==TU_READY)){
  if(type==17U&&(!rx||((f->id>>16)&255U)==0))return;
  if(rx&&type==2U&&((f->id>>16)&63U)==0)return;
  if(!rx&&type==18U&&t->stage==TU_ACTIVE)return;
 }
 char s[170];int n=snprintf(s,sizeof(s),"%lu,%s,FDCAN1,EXT,DATA,0x%08lX,%u,",(unsigned long)f->timestamp_ms,event,(unsigned long)f->id,f->dlc);
 for(unsigned i=0;i<f->dlc&&i<8;i++)n+=snprintf(s+n,sizeof(s)-(size_t)n,"%s%02X",i?" ":"",f->data[i]);
 (void)snprintf(s+n,sizeof(s)-(size_t)n,"\r\n");line(s);
}
static bool number(const char *s,long lo,long hi,long *v){char *end;errno=0;*v=strtol(s,&end,10);return *s&&!*end&&!errno&&*v>=lo&&*v<=hi;}
static void accept_command(uint32_t now,uint32_t received){
 if(!strcmp(command,"STOP")){stop_all(now,"USER_STOP",false);return;}
 if(now-received>500U){stop_all(now,"STALE_HOST_COMMAND",true);return;}
 char *a[12],*p=strtok(command," ");unsigned n=0;while(p&&n<12){a[n++]=p;p=strtok(NULL," ");}if(p||n<2)goto rejected;
 if(!strcmp(a[0],"SESSION")&&n==3){
  long id;if(strlen(a[1])!=8||strspn(a[1],"0123456789ABCDEF")!=8||!number(a[2],0,127,&id)||id!=(PICO_TUNE_COUNT==2?0:motor.id))goto rejected;
  for(unsigned i=0;i<PICO_TUNE_COUNT;++i)if(item(i)->stage>=TU_ARM_STOP)goto rejected;
  memcpy(token,a[1],9);session_uart_errors=uart_errors;for(unsigned i=0;i<PICO_TUNE_COUNT;++i)MotorTuning_Heartbeat(item(i),now);
  char s[80];(void)snprintf(s,sizeof(s),"# SESSION_OK token=%s id=%ld\r\n",token,id);line(s);return;
 }
 if(!token[0]||strcmp(a[1],token))goto rejected;
 if(n==2&&!strcmp(a[0],"KEEP")){for(unsigned i=0;i<PICO_TUNE_COUNT;++i)MotorTuning_Heartbeat(item(i),now);return;}
 if(!strcmp(a[0],"LIMIT")&&n==4){
  long id,ma;if(!number(a[2],1,127,&id)||!number(a[3],100,5300,&ma))goto rejected;
  for(unsigned i=0;i<PICO_TUNE_COUNT;++i)if(item(i)->id==id&&item(i)->stage==TU_READY&&ma<=(PICO_TUNE_COUNT==2?(i==0?5300:4700):(!strcmp(PICO_TUNE_MODEL,"RS00")?4700:5300))){item(i)->current_limit_ma=(int32_t)ma;line("# LIMIT_ACCEPTED; readback_required_on_ARM\r\n");return;}
  goto rejected;
 }
 long seq=0,values[2]={0},limits[2]={0},duration=0;bool ok=false;
 if((PICO_TUNE_COUNT==1&&!strcmp(a[0],"ARM")&&n==7)||(PICO_TUNE_COUNT==2&&!strcmp(a[0],"ARM2")&&n==9)){
  TuningMode mode=!strcmp(a[2],"POS")?TUNING_POSITION:!strcmp(a[2],"SPD")?TUNING_SPEED:0;
  if(!mode||!number(a[3],1,1000000000,&seq)||!number(a[n-1],1000,300000,&duration))goto rejected;
  for(unsigned i=0;i<PICO_TUNE_COUNT;++i){
   if(!number(a[4+i*2],-30000,30000,&values[i])||!number(a[5+i*2],0,300,&limits[i])||!MotorTuning_CanArmTimed(item(i),mode,(uint32_t)seq,(int32_t)values[i],(int32_t)limits[i],(uint32_t)duration,now))goto rejected;
  }
  if(PICO_TUNE_COUNT==2&&!memcmp(motor.uid,motor2.uid,8))goto rejected;
  for(unsigned i=0;i<PICO_TUNE_COUNT;++i){ok=MotorTuning_ArmTimed(item(i),mode,(uint32_t)seq,(int32_t)values[i],(int32_t)limits[i],(uint32_t)duration,now);item(i)->hold_enable=item(i)->hold_control=PICO_TUNE_COUNT==2;}
 }else if(PICO_TUNE_COUNT==2&&!strcmp(a[0],"SET2")&&n==7){
  if(!number(a[2],1,1000000000,&seq))goto rejected;
  for(unsigned i=0;i<2;++i)if(!number(a[3+i*2],-30000,30000,&values[i])||!number(a[4+i*2],0,300,&limits[i])||!MotorTuning_CanSet(item(i),(uint32_t)seq,(int32_t)values[i],(int32_t)limits[i],now))goto rejected;
  for(unsigned i=0;i<2;++i)ok=MotorTuning_Set(item(i),(uint32_t)seq,(int32_t)values[i],(int32_t)limits[i],now);
 }else if(PICO_TUNE_COUNT==1&&!strcmp(a[0],"SET")&&n==5&&motor.mode==TUNING_POSITION){
  if(!number(a[2],1,1000000000,&seq)||!number(a[3],-30000,30000,&values[0])||!number(a[4],10,300,&limits[0]))goto rejected;
  ok=MotorTuning_Set(&motor,(uint32_t)seq,(int32_t)values[0],(int32_t)limits[0],now);
 }else if(PICO_TUNE_COUNT==1&&!strcmp(a[0],"SETSPEED")&&n==4&&motor.mode==TUNING_SPEED){
  if(!number(a[2],1,1000000000,&seq)||!number(a[3],-300,300,&values[0]))goto rejected;
  ok=MotorTuning_Set(&motor,(uint32_t)seq,(int32_t)values[0],0,now);
 }
 if(ok){char s[100];(void)snprintf(s,sizeof(s),"# TUNE_ACCEPTED,seq=%ld,duration_ms=%lu\r\n",seq,(unsigned long)motor.run_ms);line(s);return;}
 rejected:line("# COMMAND_REJECTED\r\n");
}
void MotorEnableApp_Init(FDCAN_HandleTypeDef *can,UART_HandleTypeDef *uart){
 bus=can;serial=uart;ready=uart_failed=rx_resync=group_stopping=group_reported=false;first_motor=0;wr=rd=uart_errors=uart_received=last_uart_error=tx_write=tx_read=tx_high_water=0;tx_active=0;
 token[0]=0;command_used=0;session_uart_errors=next_health=0;memset(last_sample,0,sizeof(last_sample));memset(last_emit,0,sizeof(last_emit));
 for(unsigned i=0;i<PICO_TUNE_COUNT;++i){MotorTuning_Init(item(i),(uint8_t)(PICO_TUNE_COUNT==2?i+1:PICO_TUNE_MOTOR_ID),HAL_GetTick(),line);item(i)->current_limit_ma=PICO_TUNE_COUNT==2?(i==0?5300:4700):(!strcmp(PICO_TUNE_MODEL,"RS00")?4700:5300);}
 __HAL_UART_CLEAR_FLAG(serial,UART_CLEAR_OREF|UART_CLEAR_FEF|UART_CLEAR_NEF|UART_CLEAR_PEF);
 __HAL_UART_SEND_REQ(serial,UART_RXDATA_FLUSH_REQUEST);HAL_NVIC_SetPriority(LPUART1_IRQn,0,0);HAL_NVIC_EnableIRQ(LPUART1_IRQn);
 if(HAL_UART_Receive_IT(serial,&incoming,1)!=HAL_OK){uart_failed=true;return;}
 char s[500];(void)snprintf(s,sizeof(s),"# PICO_MOTOR_TUNING=1; channel=FDCAN1 bitrate=1000000 model=%s motor_id=%u motor_count=%u host_id=253 protocol=6 position_limit_mdeg=30000 current_limit_ma=5300 speed_limit_mrad=300 max_position_ms=300000 max_speed_ms=60000 host_timeout_ms=500\r\n",PICO_TUNE_COUNT==2?"RS10P,RS00":PICO_TUNE_MODEL,PICO_TUNE_COUNT==2?0:PICO_TUNE_MOTOR_ID,PICO_TUNE_COUNT);line(s);line(ROBSTRIDE_SPC_BANNER);
 line("# TX=PA12 RX=PA11 AF9; manual_ARM_only; mode_switch_requires_reset; uart_tx=NONBLOCKING; dual_enable_barrier=1; sample_output_max_hz_per_motor=10; no_hardware_sync_claim\r\n");
 if(!CanTransport_Init(can,1000000U,CAN_FILTER_MOTOR_DIAG,253,log_frame)){line("# TUNE_FATAL CAN initialization failed\r\n");return;}
 ready=true;line("# TUNE_COMMAND_READY=1; protocol=6\r\n");
}
static void sample(MotorTuning *t,uint32_t now){
 char s[640],ra[30],ta[30],ea[30],rv[30],tv[30],vl[30];
 if(t->mode==TUNING_SPEED){strcpy(ra,"NA");strcpy(ta,"NA");strcpy(ea,"NA");strcpy(vl,"NA");(void)snprintf(rv,sizeof(rv),"%ld",(long)t->command_velocity_mrad);(void)snprintf(tv,sizeof(tv),"%ld",(long)(t->speed_target*1000));}
 else{(void)snprintf(ra,sizeof(ra),"%ld",(long)t->command_angle_mdeg);(void)snprintf(ta,sizeof(ta),"%ld",(long)((t->target-t->origin)/0.00001745329252f));(void)snprintf(ea,sizeof(ea),"%ld",(long)((t->target-t->actual)/0.00001745329252f));(void)snprintf(vl,sizeof(vl),"%ld",(long)(t->speed_target*1000));strcpy(rv,"NA");strcpy(tv,"NA");}
 (void)snprintf(s,sizeof(s),"# TUNE_SAMPLE,t_ms=%lu,id=%u,mode=%s,accepted_seq=%lu,applied_seq=%lu,command_angle_mdeg=%s,target_angle_mdeg=%s,actual_angle_mdeg=%ld,error_mdeg=%s,iq_mA=%ld,limit_mA=%ld,velocity_mrad_s=%ld,command_velocity_mrad_s=%s,target_velocity_mrad_s=%s,speed_limit_mrad_s=%s\r\n",(unsigned long)now,t->id,t->mode==TUNING_POSITION?"POS":"SPD",(unsigned long)t->accepted_seq,(unsigned long)t->applied_seq,ra,ta,(long)((t->actual-t->origin)/0.00001745329252f),ea,(long)(t->iq*1000),(long)(t->limit*1000),(long)(t->velocity*1000),rv,tv,vl);line(s);
}
static void health(uint32_t now,CanTransportStats stats){
 bool done=true,stopped=true,cleared=true,error=false,all_ready=true,all_running=true;uint32_t accepted=UINT32_MAX,applied=UINT32_MAX,elapsed=0;const char *group_reason=motor.reason;
 for(unsigned i=0;i<PICO_TUNE_COUNT;++i){MotorTuning *t=item(i);char s[500];uint32_t e=t->enabled?(t->stage>=TU_STOP?t->stop_at:now)-t->enable_at:0;
  (void)snprintf(s,sizeof(s),"# TUNE_STATE,state=%s,mode=%s,id=%u,reason=%s,accepted_seq=%lu,applied_seq=%lu,enable_confirmed=%u,stop_confirmed=%u,target_cleared=%u,error=%u,bus_off=%lu,uart_errors=%lu,duration_ms=%lu,elapsed_ms=%lu\r\n",MotorTuning_Name(t),t->mode==TUNING_POSITION?"POS":"SPD",t->id,t->reason,(unsigned long)t->accepted_seq,(unsigned long)t->applied_seq,t->enabled?1U:0U,t->stopped?1U:0U,t->target_cleared?1U:0U,t->error?1U:0U,(unsigned long)stats.bus_off,(unsigned long)uart_errors,(unsigned long)t->run_ms,(unsigned long)e);line(s);
  if(t->error)group_reason=t->reason;
  done&=t->stage==TU_DONE;stopped&=t->stopped;cleared&=t->target_cleared;error|=t->error;all_ready&=t->stage==TU_READY;all_running&=t->stage==TU_ACTIVE||t->stage==TU_CONTROL_READ||t->stage==TU_CONTROL_WRITE;
  if(t->accepted_seq<accepted)accepted=t->accepted_seq;
  if(t->applied_seq<applied)applied=t->applied_seq;
  if(e>elapsed)elapsed=e;
 }
 if(PICO_TUNE_COUNT==2){char s[500];const char *name=done?"DONE":group_stopping?"STOPPING":all_ready?"READY":all_running?"RUNNING":"PREPARING";
  (void)snprintf(s,sizeof(s),"# TUNE_GROUP_STATE,state=%s,id=0,reason=%s,stop_confirmed=%u,target_cleared=%u,error=%u,accepted_seq=%lu,applied_seq=%lu,duration_ms=%lu,elapsed_ms=%lu\r\n",name,error?group_reason:group_stopping?motor.reason:"BOTH_MOTORS",stopped?1U:0U,cleared?1U:0U,error?1U:0U,(unsigned long)accepted,(unsigned long)applied,(unsigned long)motor.run_ms,(unsigned long)elapsed);line(s);
  if(done&&!group_reported){(void)snprintf(s,sizeof(s),"# TUNE_GROUP_RESULT,result=%s,id=0,reason=%s,stop_confirmed=%u,target_cleared=%u,error=%u\r\n",error?"ERROR":"STOPPED",group_reason,stopped?1U:0U,cleared?1U:0U,error?1U:0U);line(s);group_reported=true;}
 }
}
void MotorEnableApp_Step(void){
 if(!ready)return;
 uint32_t now=HAL_GetTick();
 if(rx_resync){uint32_t irq=__get_PRIMASK();__disable_irq();rd=wr;rx_resync=false;__set_PRIMASK(irq);command_used=0;}
 while(rd!=wr){uint32_t at=rx_at[rd];uint8_t c=rx_ring[rd];rd=(rd+1U)%sizeof(rx_ring);
  if(c=='\n'){command[command_used]=0;accept_command(now,command_used?command_at:at);command_used=0;}
  else if(c!='\r'){if(!command_used)command_at=at;if(command_used+1<sizeof(command))command[command_used++]=(char)c;else{++uart_errors;rx_resync=true;command_used=0;}}
 }
 CanTransport_Service(now);CanFrame f;
 while(CanTransport_Receive(&f)){now=HAL_GetTick();log_frame("RX",&f);if(now-f.timestamp_ms>500U)stop_all(now,"STALE_CAN_FRAME",true);else for(unsigned i=0;i<PICO_TUNE_COUNT;++i)MotorTuning_OnFrame(item(i),&f,now);}
 now=HAL_GetTick();CanTransportStats stats=CanTransport_GetStats();
 if(stats.tx_timed_out||stats.tx_rejected||stats.tx_event_lost||stats.tx_event_unknown||stats.bus_off||stats.rx_fifo_lost||stats.rx_queue_dropped||stats.rx_read_failed)stop_all(now,"CAN_LINK_ERROR",true);
 if(uart_failed||(token[0]&&uart_errors!=session_uart_errors))stop_all(now,"UART_LINK_ERROR",true);
 peer_guard(now);cancel();
 if(PICO_TUNE_COUNT==2&&motor.stage==TU_ENABLE&&motor2.stage==TU_ENABLE){motor.hold_enable=motor2.hold_enable=false;}
 if(PICO_TUNE_COUNT==2&&motor.stage==TU_ACTIVE&&motor2.stage==TU_ACTIVE){motor.hold_control=motor2.hold_control=false;}
 for(unsigned j=0;j<PICO_TUNE_COUNT;++j){unsigned i=(first_motor+j)%PICO_TUNE_COUNT;MotorTuning *t=item(i);MotorTuning_Step(t,now,send_frame,t);peer_guard(now);}
 first_motor=(first_motor+1U)%PICO_TUNE_COUNT;
 for(unsigned i=0;i<PICO_TUNE_COUNT;++i){MotorTuning *t=item(i);if(t->samples!=last_sample[i]&&now-last_emit[i]>=100U){last_sample[i]=t->samples;last_emit[i]=now;sample(t,now);}}
 if((int32_t)(now-next_health)>=0){next_health=now+500U;health(now,stats);}
}
