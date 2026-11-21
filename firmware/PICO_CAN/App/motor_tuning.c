#include "motor_tuning.h"
#include <math.h>
#include <stdio.h>
#include <string.h>
#define RAD_PER_MDEG 0.00001745329252f
static void enter(MotorTuning *t,TuningStage stage,uint32_t now){t->stage=stage;t->sent=false;t->due=now;t->attempts=0;}
const char *MotorTuning_Name(const MotorTuning *t){
 static const char *const names[]={"CONFIRM_STOP","READ_UID","BASELINE","READY","ARM_CONFIRM_STOP","READ_ORIGIN","SETUP_WRITE","SETUP_READ","WAIT_ENABLED","POSTCHECK","RUNNING","APPLY_WRITE","APPLY_READ","STOPPING","READ_STOP_POSITION","CLEAR_TARGET","VERIFY_CLEARED_TARGET","DONE"};
 return (unsigned)t->stage<sizeof(names)/sizeof(names[0])?names[t->stage]:"ERROR";
}
static bool fresh_host(const MotorTuning *t,uint32_t now){return t->host_seen&&now-t->last_host<=500U;}
static bool valid_command(TuningMode mode,int32_t value,int32_t limit){
 return mode==TUNING_POSITION?(value>=-30000&&value<=30000&&limit>=10&&limit<=300):mode==TUNING_SPEED&&value>=-300&&value<=300&&limit==0;
}
void MotorTuning_Init(MotorTuning *t,uint8_t id,uint32_t now,TuningLog log){
 memset(t,0,sizeof(*t));t->id=id;t->mode=TUNING_POSITION;t->reason="BOOT_STOP";t->log=log;t->limit=0.5f;t->current_limit_ma=500;enter(t,TU_BOOT_STOP,now+200U);
}
void MotorTuning_Heartbeat(MotorTuning *t,uint32_t now){t->host_seen=true;t->last_host=now;}
bool MotorTuning_CanArmTimed(const MotorTuning *t,TuningMode mode,uint32_t seq,int32_t value,int32_t limit,uint32_t duration,uint32_t now){
 return t->stage==TU_READY&&fresh_host(t,now)&&t->uid_valid&&t->stopped&&!t->error&&seq>0&&valid_command(mode,value,limit)&&duration>=1000U&&duration<=(mode==TUNING_POSITION?300000U:60000U);
}
bool MotorTuning_ArmTimed(MotorTuning *t,TuningMode mode,uint32_t seq,int32_t value,int32_t limit,uint32_t duration,uint32_t now){
 if(!MotorTuning_CanArmTimed(t,mode,seq,value,limit,duration,now))return false;
 t->run_ms=duration;t->mode=mode;t->accepted_seq=seq;t->command_angle_mdeg=mode==TUNING_POSITION?value:0;t->command_velocity_mrad=mode==TUNING_SPEED?value:0;t->command_speed_mrad=limit;
 t->reason="PREPARING";t->stopped=false;t->cancel_pending=true;enter(t,TU_ARM_STOP,now);return true;
}
bool MotorTuning_Arm(MotorTuning *t,TuningMode mode,uint32_t seq,int32_t value,int32_t limit,uint32_t now){
 return MotorTuning_ArmTimed(t,mode,seq,value,limit,mode==TUNING_POSITION?60000U:3000U,now);
}
bool MotorTuning_CanSet(const MotorTuning *t,uint32_t seq,int32_t value,int32_t limit,uint32_t now){
 return (t->stage==TU_ACTIVE||t->stage==TU_CONTROL_WRITE||t->stage==TU_CONTROL_READ)&&fresh_host(t,now)&&t->enabled&&!t->error&&seq>t->accepted_seq&&valid_command(t->mode,value,limit);
}
bool MotorTuning_Set(MotorTuning *t,uint32_t seq,int32_t value,int32_t limit,uint32_t now){
 if(!MotorTuning_CanSet(t,seq,value,limit,now))return false;
 t->accepted_seq=seq;t->command_angle_mdeg=t->mode==TUNING_POSITION?value:0;t->command_velocity_mrad=t->mode==TUNING_SPEED?value:0;t->command_speed_mrad=limit;return true;
}

void MotorTuning_Stop(MotorTuning *t,uint32_t now,const char *reason,bool error){
 if(t->stage==TU_DONE)return;
 if(t->stage>=TU_STOP){t->error|=error;return;}
 t->stop_at=now;t->error|=error;t->reason=reason;t->stopped=false;t->cancel_pending=true;enter(t,TU_STOP,now);
}
static void finish(MotorTuning *t){
 char line[230];(void)snprintf(line,sizeof(line),"# TUNE_RESULT,result=%s,reason=%s,id=%u,stop_confirmed=%u,target_cleared=%u,accepted_seq=%lu,applied_seq=%lu\r\n",t->error?"ERROR":"STOPPED",t->reason,t->id,t->stopped?1U:0U,t->target_cleared?1U:0U,(unsigned long)t->accepted_seq,(unsigned long)t->applied_seq);t->log(line);t->stage=TU_DONE;
}
static bool stable(MotorTuning *t,float value){
 if(t->stable_count==0)t->stable_low=t->stable_high=value;
 else{t->stable_low=fminf(t->stable_low,value);t->stable_high=fmaxf(t->stable_high,value);}
 ++t->stable_count;return t->stable_high-t->stable_low<=0.0017453293f;
}
static void setup_parameter(MotorTuning *t,bool post,uint16_t *index,float *value){
 static const uint16_t pos[]={0x7016,0x7005,0x7018,0x7017,0x7016},pos_post[]={0x7005,0x7018,0x7017,0x7016};
 static const uint16_t speed[]={0x700A,0x7005,0x7018,0x7022,0x700A},speed_post[]={0x7005,0x7018,0x7022,0x700A};
 *index=t->mode==TUNING_POSITION?(post?pos_post[t->parameter]:pos[t->parameter]):(post?speed_post[t->parameter]:speed[t->parameter]);
 *value=*index==0x7005?(float)t->mode:*index==0x7018?(float)t->current_limit_ma/1000:*index==0x7022?0.5f:*index==0x7017?(float)t->command_speed_mrad/1000:*index==0x7016?t->origin:0;
}
static unsigned parameter_count(const MotorTuning *t,bool post){return t->mode==TUNING_POSITION?(post?4U:5U):(post?4U:5U);}
static void control_parameter(MotorTuning *t,uint16_t *index,float *value){
 *index=t->mode==TUNING_SPEED?0x700A:t->control_parameter==0?0x7017:0x7016;
 *value=*index==0x700A?(float)t->transaction_velocity_mrad/1000:*index==0x7017?(float)t->transaction_speed_mrad/1000:t->origin+(float)t->transaction_angle_mdeg*RAD_PER_MDEG;
}
static void request_read(MotorTuning *t,uint16_t index){t->pending_index=index;}
void MotorTuning_OnFrame(MotorTuning *t,const CanFrame *f,uint32_t now){
 if(!CanFrame_IsValid(f)||!f->extended||f->remote||f->dlc!=8||t->stage==TU_DONE)return;
 unsigned type=(f->id>>24)&31U,source=(f->id>>8)&255U;if(source!=t->id)return;
 if(type==0&&(f->id&255U)==254U){
  if(t->uid_valid&&memcmp(t->uid,f->data,8)){MotorTuning_Stop(t,now,"UID_CHANGED",true);return;}
  if(t->stage!=TU_UID||!t->sent||(int32_t)(f->timestamp_ms-t->sent_at)<0)return;
  unsigned a=0,b=0;for(unsigned i=0;i<8;++i){a|=f->data[i];b|=f->data[i]^255U;}
  if(!a||!b){MotorTuning_Stop(t,now,"UID_INVALID",true);return;}
  memcpy(t->uid,f->data,8);t->uid_valid=true;++t->uid_count;
  char s[170];(void)snprintf(s,sizeof(s),"# TUNE_UID,id=%u,uid=%02X%02X%02X%02X%02X%02X%02X%02X,samples=%u\r\n",t->id,t->uid[0],t->uid[1],t->uid[2],t->uid[3],t->uid[4],t->uid[5],t->uid[6],t->uid[7],t->uid_count);t->log(s);
  enter(t,t->uid_count<3?TU_UID:TU_BASE,now+40U);return;
 }
 if((f->id&255U)!=253U)return;
 if(type==21){if(f->data[0]||f->data[1]||f->data[2]||f->data[3])MotorTuning_Stop(t,now,"MOTOR_FAULT",true);return;}
 if(type==2){
  uint8_t mode,fault;if(!RsSpc_FeedbackStatus(f,&mode,&fault)){MotorTuning_Stop(t,now,"INVALID_FEEDBACK_MODE",true);return;}
  if(fault){MotorTuning_Stop(t,now,"MOTOR_FAULT",true);return;}t->last_feedback=now;
  bool waiting=t->sent&&(int32_t)(f->timestamp_ms-t->sent_at)>=0;
  if(waiting&&mode==0&&(t->stage==TU_BOOT_STOP||t->stage==TU_ARM_STOP||t->stage==TU_STOP)){
   t->stopped=true;t->stable_count=0;
   if(t->stage==TU_STOP){enter(t,t->enabled&&t->mode==TUNING_POSITION?TU_CLEAN_POS:TU_CLEAN_WRITE,now+20U);return;}
   enter(t,t->stage==TU_BOOT_STOP?TU_UID:TU_ORIGIN,now+20U);return;
  }
  if(t->stage==TU_ENABLE&&waiting&&mode==2){t->enabled=true;t->parameter=0;enter(t,TU_POST,now+20U);return;}
  if(t->enabled&&t->stage<TU_STOP&&mode!=2)MotorTuning_Stop(t,now,"UNEXPECTED_MOTOR_MODE",true);
  if(!t->enabled&&t->stage!=TU_ENABLE&&t->stage<TU_STOP&&mode!=0)MotorTuning_Stop(t,now,"MOTOR_NOT_STOPPED",true);
  return;
 }
 if(type!=17||!t->sent||(int32_t)(f->timestamp_ms-t->sent_at)<0)return;
 uint16_t index=(uint16_t)(f->data[0]|((unsigned)f->data[1]<<8));if(index!=t->pending_index)return;
 float value=RsSpc_Float(f->data+4);if(index==0x7005)value=f->data[4];
 if(((f->id>>16)&255U)||f->data[2]||f->data[3]||!isfinite(value)||fabsf(value)>1000){
  if(t->stage>=TU_CLEAN_POS){t->error=true;t->reason="STOPPED_TARGET_CLEAR_FAILED";finish(t);}else MotorTuning_Stop(t,now,"PARAMETER_READ_FAILED",true);return;
 }
 if(t->stage==TU_BASE||t->stage==TU_ORIGIN||t->stage==TU_CLEAN_POS){
  if(!stable(t,value)){
   if(t->stage==TU_CLEAN_POS){t->error=true;t->reason="STOPPED_POSITION_UNSTABLE";finish(t);}else MotorTuning_Stop(t,now,"POSITION_UNSTABLE",true);return;
  }
  t->actual=value;t->last_position=now;t->pos_valid=true;
  if(t->stable_count<5){enter(t,t->stage,now+30U);return;}
  if(t->stage==TU_CLEAN_POS){t->expected=value;enter(t,TU_CLEAN_WRITE,now+10U);return;}
  t->origin=t->target=value;
  if(t->stage==TU_BASE){t->reason="WAIT_MANUAL_ARM";enter(t,TU_READY,now+20U);return;}
  t->parameter=0;t->speed_target=0;t->applied_seq=0;
  char s[110];(void)snprintf(s,sizeof(s),"# TUNE_ORIGIN,id=%u,position_urad=%ld\r\n",t->id,(long)(value*1000000));t->log(s);enter(t,TU_WRITE,now+10U);return;
 }
 if(t->stage==TU_READ||t->stage==TU_POST||t->stage==TU_CONTROL_READ||t->stage==TU_CLEAN_READ){
  float tolerance=index==0x7016?0.0005f:0.00001f;
  if(fabsf(value-t->expected)>tolerance){
   if(t->stage==TU_CLEAN_READ){t->error=true;t->reason="STOPPED_TARGET_CLEAR_FAILED";finish(t);}else MotorTuning_Stop(t,now,"PARAMETER_MISMATCH",true);return;
  }
  if(t->stage==TU_CLEAN_READ){t->target_cleared=true;finish(t);return;}
  if(t->stage==TU_CONTROL_READ){
   if(index==0x7017)t->speed_target=value;else if(index==0x7016)t->target=value;else t->speed_target=value;
   if(t->mode==TUNING_POSITION&&t->control_parameter++==0){enter(t,TU_CONTROL_WRITE,now+10U);return;}
   t->applied_seq=t->transaction_seq;t->telemetry=0;t->telemetry_required=true;t->reason="TRACKING";enter(t,TU_ACTIVE,now+10U);return;
  }
  bool post=t->stage==TU_POST;++t->parameter;
  if(t->parameter<parameter_count(t,post)){enter(t,post?TU_POST:TU_WRITE,now+10U);return;}
  if(!post){enter(t,TU_ENABLE,now+10U);return;}
  t->limit=(float)t->current_limit_ma/1000;t->speed_target=t->mode==TUNING_POSITION?(float)t->command_speed_mrad/1000:0;
  t->iq_valid=t->velocity_valid=false;t->last_iq=t->last_velocity=t->last_position=now;t->telemetry=0;t->next_refresh=now+100U;enter(t,TU_ACTIVE,now+10U);return;
 }
 if(t->stage==TU_READY||t->stage==TU_ACTIVE){
  if(index==0x7019){
   float bound=0.5f*((float)(now-t->last_position)/1000)+0.01f;
   if(t->pos_valid&&fabsf(value-t->actual)>bound){MotorTuning_Stop(t,now,"POSITION_SAMPLE_JUMP",true);return;}
   t->actual=value;t->last_position=now;t->pos_valid=true;
   if(t->enabled&&fabsf(value-t->origin)>(t->mode==TUNING_POSITION?0.55850536f:0.3f*((float)t->run_ms/1000)+0.17453293f)){MotorTuning_Stop(t,now,"DISPLACEMENT_LIMIT",true);return;}
  }else if(index==0x701A){t->iq=value;t->last_iq=now;t->iq_valid=true;if(t->enabled&&fabsf(value)>fminf(6.0f,t->limit*1.2f+0.1f)){MotorTuning_Stop(t,now,"CURRENT_LIMIT",true);return;}}
  else if(index==0x701B){t->velocity=value;t->last_velocity=now;t->velocity_valid=true;if(t->enabled&&fabsf(value)>0.5f){MotorTuning_Stop(t,now,"SPEED_LIMIT",true);return;}}
  /* Suspected obstruction: sustained near-zero speed at near-limit current.
     Evaluate only complete, fresh telemetry sets; allow startup to settle. */
  if(t->telemetry==2&&t->enabled&&t->stage==TU_ACTIVE){
   bool demand=t->mode==TUNING_POSITION?fabsf(t->target-t->actual)>0.034906585f:fabsf(t->speed_target)>=0.08f;
   bool blocked=demand&&fabsf(t->velocity)<0.02f&&fabsf(t->iq)>=t->limit*0.8f&&now-t->enable_at>=1000U&&now-t->last_position<=200U&&now-t->last_iq<=200U;
   if(blocked){if(!t->stall_since)t->stall_since=now;if(now-t->stall_since>=700U){MotorTuning_Stop(t,now,"SUSPECTED_OBSTRUCTION",true);return;}}
   else t->stall_since=0;
  }
  if(++t->telemetry==3){t->telemetry=0;t->telemetry_required=false;++t->samples;}
  enter(t,t->stage,now+10U);return;
 }
}
void MotorTuning_Step(MotorTuning *t,uint32_t now,TuningSend send,void *context){
 if(t->stage==TU_DONE||!send)return;
 bool armed=t->stage>=TU_ARM_STOP&&t->stage<TU_STOP;
 if(armed&&!fresh_host(t,now))MotorTuning_Stop(t,now,"HOST_TIMEOUT",true);
 if(t->enabled&&t->stage<TU_STOP){
  if(now-t->enable_at>=t->run_ms)MotorTuning_Stop(t,now,"AUTO_STOP",false);
  else if(now-t->last_feedback>500U)MotorTuning_Stop(t,now,"FEEDBACK_TIMEOUT",true);
  else if((t->stage>=TU_ACTIVE)&&(now-t->last_position>500U||now-t->last_iq>500U||now-t->last_velocity>500U))MotorTuning_Stop(t,now,"TELEMETRY_TIMEOUT",true);
 }
 if(t->sent){
  if(now-t->sent_at<500U)return;
  if(t->stage==TU_BOOT_STOP||t->stage==TU_ARM_STOP||t->stage==TU_STOP){
   if(++t->attempts<3U){t->sent=false;t->due=now;return;}t->stopped=false;t->error=true;t->reason="STOP_UNCONFIRMED";finish(t);return;
  }
  if(t->stage>=TU_CLEAN_POS){t->error=true;t->reason="STOPPED_TARGET_CLEAR_FAILED";finish(t);}else MotorTuning_Stop(t,now,"REPLY_TIMEOUT",true);return;
 }
 if((int32_t)(now-t->due)<0)return;
 if(t->stage==TU_ENABLE&&t->hold_enable)return;
 CanFrame f={.dlc=9};uint16_t index=0;float value=0;bool write=false;
 if(t->stage==TU_BOOT_STOP||t->stage==TU_ARM_STOP||t->stage==TU_STOP)f=RsSpc_Frame(t->id,253,4,0,0);
 else if(t->stage==TU_UID)f=RsSpc_Frame(t->id,253,0,0,0);
 else if(t->stage==TU_ENABLE)f=RsSpc_Frame(t->id,253,3,0,0);
 else{
  if(t->stage==TU_BASE||t->stage==TU_ORIGIN||t->stage==TU_CLEAN_POS)index=0x7019;
  else if(t->stage==TU_WRITE||t->stage==TU_READ||t->stage==TU_POST){setup_parameter(t,t->stage==TU_POST,&index,&value);write=t->stage==TU_WRITE;}
  else if(t->stage==TU_CONTROL_WRITE||t->stage==TU_CONTROL_READ){control_parameter(t,&index,&value);write=t->stage==TU_CONTROL_WRITE;}
  else if(t->stage==TU_CLEAN_WRITE||t->stage==TU_CLEAN_READ){index=t->mode==TUNING_POSITION&&t->enabled?0x7016:0x700A;value=index==0x7016?t->expected:0;write=t->stage==TU_CLEAN_WRITE;}
  else if(t->stage==TU_READY||t->stage==TU_ACTIVE){
   if(t->stage==TU_ACTIVE&&t->accepted_seq>t->applied_seq&&!t->telemetry_required&&!t->hold_control){
    t->transaction_seq=t->accepted_seq;t->transaction_angle_mdeg=t->command_angle_mdeg;t->transaction_speed_mrad=t->command_speed_mrad;t->transaction_velocity_mrad=t->command_velocity_mrad;t->control_parameter=0;enter(t,TU_CONTROL_WRITE,now);return;
   }
   if(t->stage==TU_ACTIVE&&(int32_t)(now-t->next_refresh)>=0){
    CanFrame refresh=RsSpc_Frame(t->id,253,18,t->mode==TUNING_POSITION?0x7016:0x700A,t->mode==TUNING_POSITION?t->target:t->speed_target);
    if(!send(context,&refresh,now))MotorTuning_Stop(t,now,"CAN_SUBMIT_FAILED",true);
    t->next_refresh=now+100U;return;
   }
   static const uint16_t indices[]={0x7019,0x701A,0x701B};index=indices[t->telemetry];
  }else return;
  if(t->stage==TU_POST)t->expected=value;
  if(write){t->expected=value;f=RsSpc_Frame(t->id,253,18,index,value);}else{request_read(t,index);f=RsSpc_Frame(t->id,253,17,index,0);}
 }
 if(!send(context,&f,now)){
  if(t->stage==TU_STOP||t->stage==TU_BOOT_STOP||t->stage==TU_ARM_STOP){if(++t->attempts>=3){t->error=true;t->reason="STOP_UNCONFIRMED";finish(t);}else t->due=now+100U;}
  else {MotorTuning_Stop(t,now,"CAN_SUBMIT_FAILED",true);}
  return;
 }
 t->sent=true;t->sent_at=now;
 if(t->stage==TU_ENABLE){t->stopped=false;t->enable_at=now;t->last_feedback=now;}
 else if(t->stage==TU_WRITE)enter(t,TU_READ,now+20U);
 else if(t->stage==TU_CONTROL_WRITE)enter(t,TU_CONTROL_READ,now+20U);
 else if(t->stage==TU_CLEAN_WRITE)enter(t,TU_CLEAN_READ,now+20U);
}
