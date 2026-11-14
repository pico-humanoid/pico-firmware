/* Diagnostic only: type 0 UID, type 4 STOP/version, type 17 reads. The only
   parameter write is opt-in loc_ref=current measured position while stopped.
   No enable, mode/limit/gain/zero/ID/baud/save command exists in this module. */
#include "motor_position_diag.h"
#include "protocol/robstride_spc.h"
#include <math.h>
#include <stdio.h>
#include <string.h>
const uint16_t diag_indices[DIAG_PARAM_COUNT]={0x7005,0x7016,0x7019,0x7029,0x702B,0x2005,0x7017,0x7018};
static const unsigned delays[]={10,50,200};
static void enter(MotorPositionDiag *d,DiagStage stage,uint32_t now){d->stage=stage;d->sent=false;d->due=now;d->attempts=0;}
static void value_log(MotorPositionDiag *d,unsigned index,float value,bool valid,uint32_t now){
 char s[230];uint32_t bits=0;memcpy(&bits,&value,4);
 (void)snprintf(s,sizeof(s),"# DIAG_VALUE,t_ms=%lu,index=0x%04X,status=%s,value_micro=%ld,raw_bits=0x%08lX\r\n",(unsigned long)now,index,valid?"OK":"UNAVAILABLE",valid?(long)(value*1000000.0f):0L,(unsigned long)bits);d->log(s);
}
void MotorPositionDiag_Init(MotorPositionDiag *d,uint8_t id,uint32_t now,DiagLog log){
 memset(d,0,sizeof(*d));d->id=id;d->reason="READ_ONLY_BASELINE";d->log=log;d->uid_remaining=3;enter(d,DG_STOP,now+200U);
}
void MotorPositionDiag_Heartbeat(MotorPositionDiag *d,uint32_t now){d->last_host=now;d->host_seen=true;}
bool MotorPositionDiag_EchoAllowed(const MotorPositionDiag *d,uint32_t now){
 return d->stage==DG_MONITOR&&d->snapshot_done&&d->stop_confirmed&&d->uid_valid&&!d->uid_conflict&&d->uid_samples>=3U&&
  d->valid[0]&&d->values[0]==5.0f&&d->valid[2]&&!d->failed&&!d->echo_requested&&!d->echo_finished&&
  now-d->last_uid<10000U&&d->host_seen&&now-d->last_host<=500U;
}
bool MotorPositionDiag_RequestEcho(MotorPositionDiag *d,uint32_t now){
 if(!MotorPositionDiag_EchoAllowed(d,now))return false;
 d->echo_requested=true;d->reason="ECHO_REQUESTED";return true;
}
void MotorPositionDiag_Stop(MotorPositionDiag *d,uint32_t now,const char *reason,bool error){
 if(d->stage==DG_HALTED)return;
 if(d->stage==DG_FAILURE_STOP){d->failed|=error;return;}
 d->failed|=error;d->reason=reason;d->echo_requested=d->echo_active=false;d->stop_confirmed=false;d->cancel_pending=true;
 enter(d,DG_FAILURE_STOP,now);
}
const char *MotorPositionDiag_Name(const MotorPositionDiag *d){
 static const char *const names[]={"CONFIRM_STOP","READ_UID","READ_VERSION","READ_PARAMETERS","MONITOR","ECHO_CONFIRM_STOP","ECHO_READ_MODE","ECHO_READ_ACTUAL","ECHO_WRITE_CURRENT_POSITION","ECHO_READBACK","ECHO_READ_ACTUAL_AFTER","STOPPING","DONE"};
 return (unsigned)d->stage<sizeof(names)/sizeof(names[0])?names[d->stage]:"ERROR";
}
static void finish_failure(MotorPositionDiag *d){
 char s[200];(void)snprintf(s,sizeof(s),"# DIAG_RESULT,result=%s,reason=%s,stop_confirmed=%u,no_enable=1,target_cleared=%u\r\n",d->failed?"ERROR":"STOPPED",d->reason,d->stop_confirmed?1U:0U,d->target_cleared?1U:0U);d->log(s);d->stage=DG_HALTED;
}
static void advance_parameter(MotorPositionDiag *d,uint32_t now){
 if(d->stage==DG_SNAPSHOT){
  if(++d->parameter==DIAG_PARAM_COUNT){d->snapshot_done=true;enter(d,DG_MONITOR,now+100U);}
  else enter(d,DG_SNAPSHOT,now+60U);
 }else{d->monitor_query^=1U;enter(d,DG_MONITOR,now+200U);}
}
void MotorPositionDiag_OnFrame(MotorPositionDiag *d,const CanFrame *f,uint32_t now){
 if(!CanFrame_IsValid(f)||!f->extended||f->remote||f->dlc!=8U||d->stage==DG_HALTED)return;
 unsigned type=(f->id>>24)&31U,source=(f->id>>8)&255U;
 if(source!=d->id)return;
 if(type==0U&&(f->id&255U)==0xFEU){
  if(d->uid_valid&&memcmp(d->uid,f->data,8)!=0){d->uid_conflict=true;MotorPositionDiag_Stop(d,now,"UID_CHANGED",true);return;}
  if(d->stage!=DG_UID||!d->sent||(int32_t)(f->timestamp_ms-d->sent_at)<0)return;
  unsigned nz=0,nf=0;for(unsigned i=0;i<8;++i){nz|=f->data[i];nf|=f->data[i]^255U;}
  if(!nz||!nf){MotorPositionDiag_Stop(d,now,"UID_INVALID",true);return;}
  memcpy(d->uid,f->data,8);d->uid_valid=true;++d->uid_samples;d->last_uid=now;
  char s[160];(void)snprintf(s,sizeof(s),"# DIAG_UID,id=%u,uid=%02X%02X%02X%02X%02X%02X%02X%02X,samples=%u\r\n",d->id,f->data[0],f->data[1],f->data[2],f->data[3],f->data[4],f->data[5],f->data[6],f->data[7],d->uid_samples);d->log(s);
  if(--d->uid_remaining)enter(d,DG_UID,now+100U);else enter(d,d->snapshot_done?DG_MONITOR:DG_VERSION,now+100U);return;
 }
 if((f->id&255U)!=253U)return;
 if(type==21U){if(f->data[0]||f->data[1]||f->data[2]||f->data[3])MotorPositionDiag_Stop(d,now,"MOTOR_FAULT",true);return;}
 if(type==2U){
  uint8_t mode,fault;if(!RsSpc_FeedbackStatus(f,&mode,&fault)){MotorPositionDiag_Stop(d,now,"INVALID_FEEDBACK_MODE",true);return;}
  if(fault){MotorPositionDiag_Stop(d,now,"MOTOR_FAULT",true);return;}
  if(d->stage==DG_VERSION&&d->sent&&f->data[0]==0&&f->data[1]==0xC4&&f->data[2]==0x56&&(int32_t)(f->timestamp_ms-d->sent_at)>=0){
   char s[100];(void)snprintf(s,sizeof(s),"# DIAG_VERSION,value=%u.%u.%u.%u\r\n",f->data[3],f->data[4],f->data[5],f->data[6]);d->log(s);enter(d,DG_SNAPSHOT,now+100U);return;
  }
  if(mode!=0U){MotorPositionDiag_Stop(d,now,"MOTOR_NOT_STOPPED",true);return;}
  if(d->sent&&(d->stage==DG_STOP||d->stage==DG_ECHO_STOP||d->stage==DG_FAILURE_STOP)&&(int32_t)(f->timestamp_ms-d->sent_at)>=0){
   d->stop_confirmed=true;d->last_stop=now;
   if(d->stage==DG_FAILURE_STOP){finish_failure(d);return;}
   enter(d,d->stage==DG_STOP?DG_UID:DG_ECHO_MODE,now+50U);
  }return;
 }
 if(type!=17U||!d->sent||(int32_t)(f->timestamp_ms-d->sent_at)<0)return;
 unsigned index=f->data[0]|((unsigned)f->data[1]<<8);if(index!=d->pending_index||f->data[2]||f->data[3])return;
 float value=RsSpc_Float(f->data+4);if(index==0x7005U||index==0x7029U)value=(float)f->data[4];
 /* Type 17 bit23..16 is a read status, not payload. Error replies often
    contain zero bytes; those bytes are not a successful parameter value. */
 bool read_ok=((f->id>>16)&255U)==0U;
 bool valid=read_ok&&isfinite(value)&&fabsf(value)<=1000.0f;
 if(d->stage==DG_SNAPSHOT||d->stage==DG_MONITOR){
  unsigned p=0;while(p<DIAG_PARAM_COUNT&&diag_indices[p]!=index)++p;
  if(p<DIAG_PARAM_COUNT){d->values[p]=value;d->valid[p]=valid;value_log(d,index,value,valid,f->timestamp_ms);}
  advance_parameter(d,now);return;
 }
 if(!valid){MotorPositionDiag_Stop(d,now,read_ok?"INVALID_PARAMETER_VALUE":"PARAMETER_READ_REJECTED",true);return;}
 if(d->stage==DG_ECHO_MODE){
  if(value!=5.0f){MotorPositionDiag_Stop(d,now,"CSP_NOT_SELECTED",true);return;}
  enter(d,DG_ECHO_POS,now+30U);
 }else if(d->stage==DG_ECHO_POS){d->expected=value;enter(d,DG_ECHO_WRITE,now+30U);}
 else if(d->stage==DG_ECHO_READ){
  float error=fabsf(value-d->expected);d->last_read=value;d->last_match=error<=0.0005f;d->echo_mismatch|=!d->last_match;d->max_error=fmaxf(d->max_error,error);++d->echo_samples;
  char s[260];(void)snprintf(s,sizeof(s),"# DIAG_ECHO,round=%u,nominal_ms=%u,age_ms=%lu,expected_urad=%ld,read_urad=%ld,error_urad=%ld,status=%s\r\n",d->round+1U,delays[d->read_number],(unsigned long)(f->timestamp_ms-d->write_at),(long)(d->expected*1000000),(long)(value*1000000),(long)((value-d->expected)*1000000),d->last_match?"MATCH":"MISMATCH");d->log(s);
  if(++d->read_number<3U){enter(d,DG_ECHO_READ,d->write_at+delays[d->read_number]);}
  else enter(d,DG_ECHO_AFTER,now+30U);
 }else if(d->stage==DG_ECHO_AFTER){
  d->values[2]=value;d->valid[2]=true;value_log(d,0x7019,value,true,f->timestamp_ms);
  d->target_cleared=d->last_match&&fabsf(value-d->last_read)<=0.0005f;
  if(fabsf(value-d->expected)>0.0087266463f){MotorPositionDiag_Stop(d,now,"POSITION_MOVED_WHILE_STOPPED",true);return;}
  if(++d->round<3U)enter(d,DG_ECHO_STOP,now+100U);
  else{
   d->echo_active=false;d->echo_finished=true;d->reason=d->echo_mismatch?"READBACK_MISMATCH":"READBACK_CONSISTENT";
   char s[230];(void)snprintf(s,sizeof(s),"# DIAG_ECHO_RESULT,result=%s,rounds=3,samples=%lu,max_error_urad=%ld,stop_confirmed=%u,target_cleared=%u,no_enable=1\r\n",d->echo_mismatch?"MISMATCH":"CONSISTENT",(unsigned long)d->echo_samples,(long)(d->max_error*1000000),d->stop_confirmed?1U:0U,d->target_cleared?1U:0U);d->log(s);d->stage=DG_HALTED;
  }
 }
}
void MotorPositionDiag_Step(MotorPositionDiag *d,uint32_t now,DiagSend send,void *context){
 if(d->stage==DG_HALTED||!send)return;
 if((d->echo_active||d->echo_requested)&&(!d->host_seen||now-d->last_host>500U)){MotorPositionDiag_Stop(d,now,"HOST_TIMEOUT",true);}
 if(d->sent){
  if(now-d->sent_at<700U)return;
  if(d->stage==DG_STOP||d->stage==DG_ECHO_STOP||d->stage==DG_FAILURE_STOP){
   if(++d->attempts<3U){d->sent=false;d->due=now;return;}
   d->stop_confirmed=false;d->failed=true;d->reason="STOP_UNCONFIRMED";finish_failure(d);return;
  }
  if(d->stage==DG_UID){d->log("# DIAG_UID,status=UNAVAILABLE\r\n");d->last_uid=now;enter(d,d->snapshot_done?DG_MONITOR:DG_VERSION,now);}
  else if(d->stage==DG_VERSION){d->log("# DIAG_VERSION,value=UNAVAILABLE\r\n");enter(d,DG_SNAPSHOT,now);}
  else if(d->stage==DG_SNAPSHOT||d->stage==DG_MONITOR){
   unsigned p=0;while(p<DIAG_PARAM_COUNT&&diag_indices[p]!=d->pending_index)++p;
   if(p<DIAG_PARAM_COUNT)d->valid[p]=false;
   value_log(d,d->pending_index,0,false,now);advance_parameter(d,now);
  }else{MotorPositionDiag_Stop(d,now,"DIAGNOSTIC_REPLY_TIMEOUT",true);return;}
 }
 if(d->stage==DG_MONITOR&&!d->sent){
  if(d->echo_requested){d->echo_active=true;d->echo_requested=false;d->round=d->read_number=0;d->reason="STOPPED_ECHO_TEST";enter(d,DG_ECHO_STOP,now);}
  else if(now-d->last_uid>=5000U){d->uid_remaining=1;enter(d,DG_UID,now);}
 }
 if((int32_t)(now-d->due)<0)return;
 CanFrame f;
 if(d->stage==DG_STOP||d->stage==DG_ECHO_STOP||d->stage==DG_FAILURE_STOP)f=RsSpc_Frame(d->id,253,4,0,0);
 else if(d->stage==DG_VERSION)f=RsSpc_VersionFrame(d->id,253);
 else if(d->stage==DG_UID)f=RsSpc_Frame(d->id,253,0,0,0);
 else if(d->stage==DG_ECHO_WRITE){
  if(!d->stop_confirmed||now-d->last_stop>500U||!d->uid_valid||d->uid_conflict){MotorPositionDiag_Stop(d,now,"WRITE_INTERLOCK_FAILED",true);return;}
  f=RsSpc_Frame(d->id,253,18,0x7016,d->expected);
 }else{
  unsigned index=d->stage==DG_SNAPSHOT?diag_indices[d->parameter]:d->stage==DG_MONITOR?(d->monitor_query?0x7019U:0x7016U):d->stage==DG_ECHO_MODE?0x7005U:d->stage==DG_ECHO_POS||d->stage==DG_ECHO_AFTER?0x7019U:0x7016U;
  d->pending_index=(uint16_t)index;f=RsSpc_Frame(d->id,253,17,(uint16_t)index,0);
 }
 if(!send(context,&f,now)){
  if(d->stage==DG_STOP||d->stage==DG_ECHO_STOP||d->stage==DG_FAILURE_STOP){
   if(++d->attempts>=3U){d->failed=true;d->reason="STOP_UNCONFIRMED";d->stop_confirmed=false;finish_failure(d);}
   else d->due=now+100U;
  }else MotorPositionDiag_Stop(d,now,"CAN_SUBMIT_REJECTED",true);
  return;
 }
 d->sent=true;d->sent_at=now;
 if(d->stage==DG_ECHO_WRITE){d->write_at=now;d->read_number=0;enter(d,DG_ECHO_READ,now+delays[0]);}
}
