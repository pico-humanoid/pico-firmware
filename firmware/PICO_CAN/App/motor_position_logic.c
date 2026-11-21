#include "motor_position_logic.h"
#include "protocol/robstride_spc.h"
#include <math.h>
#include <string.h>
#define ANGLE 0.0872664626f
#define TOLERANCE 0.0087266463f
static float scalar(const uint8_t *d){return RsSpc_Float(d);}
static CanFrame packet(MotorPosition *p,unsigned type,unsigned index){
 return RsSpc_Frame(p->core.id,p->core.host,type,(uint16_t)index,0);
}
static CanFrame write_parameter(MotorPosition *p,unsigned index,float value){return RsSpc_Frame(p->core.id,p->core.host,18,(uint16_t)index,value);}
static void stage(MotorPosition *p,MotorPositionStage s,uint32_t now){p->stage=s;p->core.sent=false;p->core.due=now;}
static void parameter(MotorPosition *p,bool post,unsigned *index,float *value){
 static const unsigned setup[]={0x7016,0x7005,0x7018,0x7017,0x7016};
 static const unsigned check[]={0x7005,0x7018,0x7017,0x7016};
 *index=post?check[p->parameter]:setup[p->parameter];
 *value=*index==0x7005?5:*index==0x7018?0.5f:*index==0x7017?0.2f:p->origin;
}
void MotorPosition_Init(MotorPosition *p,uint8_t id,uint8_t host,uint32_t now){
 memset(p,0,sizeof(*p));MotorEnable_Init(&p->core,id,host,now);
 p->amplitude_rad=ANGLE;p->dwell_ms=500U;p->core.refresh_ms=200U;p->core.query_ms=50U;
}
void MotorPosition_Heartbeat(MotorPosition *p,uint32_t now){MotorEnable_Heartbeat(&p->core,now);}
void MotorPosition_Stop(MotorPosition *p,uint32_t now,const char *reason,bool error){MotorEnable_Stop(&p->core,now,reason,error);}
bool MotorPosition_Request(MotorPosition *p,uint32_t now){
 MotorEnable *e=&p->core;
 if(e->phase!=ME_READY||!e->host_seen||now-e->last_heartbeat>500U||e->run_requested||e->error)return false;
 e->run_requested=true;e->stop_confirmed=false;e->reason="PREPARING_POSITION";e->phase=ME_ACTIVE;stage(p,MP_START,now);return true;
}
const char *MotorPosition_Name(const MotorPosition *p){
 if(p->core.phase!=ME_ACTIVE)return MotorEnable_Name(p->core.phase);
 static const char *const names[]={"READ_ORIGIN","POSITION_WRITE","POSITION_READ","CHECK_START_POSITION","WAIT_ENABLED","POSITION_POSTCHECK","SET_POSITION_TARGET","VERIFY_POSITION_TARGET","POSITION_MOVING","READ_STOP_POSITION","HOLD_STOP_POSITION","VERIFY_STOP_TARGET"};
 return (unsigned)p->stage<sizeof(names)/sizeof(names[0])?names[p->stage]:"ERROR";
}
static bool valid_position(float value){return isfinite(value)&&fabsf(value)<=1000.0f;}
static bool target_matches(float actual,float expected){return isfinite(actual)&&fabsf(actual-expected)<=MOTOR_POSITION_READBACK_TOLERANCE_RAD;}
static void cleanup_failed(MotorPosition *p){
 p->neutralize_failed=true;
 if(!p->core.error)p->core.reason="STOPPED_TARGET_NEUTRALIZE_FAILED";
 p->core.error=true;p->core.phase=ME_DONE;
}
static bool stable_position(MotorPosition *p,float value,float error,uint32_t now){
 MotorEnable *e=&p->core;
 /* Use position increments for sampled settling speed; the separately
    reported velocity remains fresh, logged, and subject to the raw trip.
    Do not let its noisy near-zero median veto stationary position windows. */
 if(error>TOLERANCE||p->velocity_count<5U||e->iq_samples==0U||
    now-e->last_velocity>500U||now-e->last_iq>500U){
  p->settled=false;p->stable_samples=0;p->stable_span=0;
  p->sampled_position_speed=p->mean_position_speed=0;return false;
 }
 if(p->settled&&now==p->stable_last_at)return false;
 uint32_t gap=now-p->stable_last_at;
 float step=p->settled?fabsf(value-p->stable_last_position):0.0f;
 p->sampled_position_speed=p->settled&&gap>0U?step*1000.0f/(float)gap:0.0f;
 float low=fminf(p->stable_min,value),high=fmaxf(p->stable_max,value);
 if(!p->settled||gap>500U||high-low>MOTOR_POSITION_STABLE_SPAN_RAD||p->sampled_position_speed>=0.03f){
  p->settled=true;p->settle_at=now;p->stable_last_at=now;
  p->stable_last_position=value;p->stable_position_travel=p->mean_position_speed=0;
  p->stable_min=p->stable_max=value;p->stable_span=0;p->stable_samples=1;return false;
 }
 p->stable_min=low;p->stable_max=high;p->stable_span=high-low;
 p->stable_position_travel+=step;p->stable_last_position=value;
 p->mean_position_speed=p->stable_position_travel*1000.0f/(float)(now-p->settle_at);
 p->stable_last_at=now;++p->stable_samples;
 return p->stable_samples>=4U&&now-p->settle_at>=p->dwell_ms;
}
static void filter_velocity(MotorPosition *p,float value){
 p->velocity_history[p->velocity_cursor]=fabsf(value);p->velocity_cursor=(p->velocity_cursor+1U)%5U;
 if(p->velocity_count<5U)++p->velocity_count;
 float sorted[5];memcpy(sorted,p->velocity_history,sizeof(sorted));
 for(unsigned i=1;i<p->velocity_count;++i){float v=sorted[i];unsigned j=i;while(j>0U&&sorted[j-1U]>v){sorted[j]=sorted[j-1U];--j;}sorted[j]=v;}
 p->stable_velocity=sorted[p->velocity_count/2U];
}
void MotorPosition_OnFrame(MotorPosition *p,const CanFrame *f,uint32_t now){
 MotorEnable *e=&p->core;
 if(!CanFrame_IsValid(f)||!f->extended||f->remote||f->dlc!=8U||(f->id&255U)!=e->host||((f->id>>8)&255U)!=e->id)return;
 if(e->phase==ME_STOPPING||e->phase==ME_BASELINE){
  MotorEnable_OnFrame(e,f,now);
  if(e->phase==ME_DONE){e->phase=ME_ACTIVE;stage(p,MP_CLEAN_POSITION,now);}
  return;
 }
 unsigned type=(unsigned)((f->id>>24)&31U);
 if(type==2U){
  uint8_t mode,fault;if(!RsSpc_FeedbackStatus(f,&mode,&fault)){MotorPosition_Stop(p,now,"INVALID_FEEDBACK_MODE",true);return;}
  ++e->feedbacks;e->last_feedback=now;
  if(fault){MotorPosition_Stop(p,now,"MOTOR_FAULT",true);return;}
  if(e->phase==ME_ACTIVE&&p->stage==MP_ENABLE&&e->sent&&mode==2U&&(int32_t)(f->timestamp_ms-e->sent_at)>=0){
   e->enable_confirmed=true;e->last_iq=e->last_velocity=e->last_position=now;
   p->parameter=0;stage(p,MP_POSTCHECK,now);
  }else if(e->enable_confirmed&&!e->finishing&&mode!=2U)MotorPosition_Stop(p,now,"UNEXPECTED_MOTOR_MODE",true);
  else if(e->finishing&&e->phase==ME_ACTIVE&&mode!=0U){e->finishing=false;MotorPosition_Stop(p,now,"UNEXPECTED_MOTOR_MODE",true);}
  return;
 }
 if(type==21U){if(f->data[0]||f->data[1]||f->data[2]||f->data[3])MotorPosition_Stop(p,now,"FAULT_REPORT",true);return;}
 if(type!=17U||e->phase!=ME_ACTIVE)return;
 if(((f->id>>16)&255U)!=0U){MotorPosition_Stop(p,now,"PARAMETER_READ_REJECTED",true);return;}
 unsigned index=f->data[0]|((unsigned)f->data[1]<<8);float value=scalar(f->data+4);
 if(p->stage==MP_MOVE&&(index==0x701A||index==0x701B||index==0x7019)){
  if((int32_t)(f->timestamp_ms-p->leg_at)<0)return;
  if(!valid_position(value)){MotorPosition_Stop(p,now,"INVALID_TELEMETRY",true);return;}
  if(index==0x701A){e->iq=value;e->last_iq=now;++e->iq_samples;p->peak_iq=fmaxf(p->peak_iq,fabsf(value));if(fabsf(value)>0.8f)MotorPosition_Stop(p,now,"IQ_OVER_0.8A",true);}
  if(index==0x701B){e->velocity=value;e->last_velocity=now;++e->velocity_samples;filter_velocity(p,value);if(fabsf(value)>0.4f)MotorPosition_Stop(p,now,"SPEED_OVER_0.4",true);}
  if(index==0x7019){
   p->actual=value;e->position_delta=value-p->origin;e->last_position=now;++e->position_samples;
   if(fabsf(e->position_delta)>0.13962634f){MotorPosition_Stop(p,now,"DISPLACEMENT_OVER_8_DEG",true);return;}
   if(e->finishing)return;
   float error=fabsf(value-p->target);
   if(p->stream_control){
    if(p->stream_settling)p->stream_settled=stable_position(p,value,error,now);
    return;
   }
   if(stable_position(p,value,error,now)){
    p->last_arrival_error=value-p->target;p->last_target=p->target;
    p->max_arrival_error=fmaxf(p->max_arrival_error,error);
    if((p->waypoints&1U)!=0U)p->max_return_error=fmaxf(p->max_return_error,fabsf(value-p->origin));
    ++p->waypoints;
    if(p->waypoints==40U){e->motion_confirmed=true;MotorPosition_Stop(p,now,"POSITION_COMPLETE",false);}
    else stage(p,MP_TARGET,now);
   }
  }return;
 }
 if(!e->sent||(int32_t)(f->timestamp_ms-e->sent_at)<0)return;
 if(p->stage==MP_START&&index==0x7019){
  if(!valid_position(value)){MotorPosition_Stop(p,now,"INVALID_ORIGIN",true);return;}
  p->origin=p->target=p->actual=value;e->position_start=value;p->parameter=0;stage(p,MP_WRITE,now);
 }else if((p->stage==MP_READ||p->stage==MP_POSTCHECK)){
  unsigned wanted;float expected;parameter(p,p->stage==MP_POSTCHECK,&wanted,&expected);if(index!=wanted)return;
  bool match=wanted==0x7005?f->data[4]==5U:wanted==0x7016?target_matches(value,expected):isfinite(value)&&fabsf(value-expected)<0.00001f;
  if(!match){MotorPosition_Stop(p,now,"POSITION_PARAMETER_MISMATCH",true);return;}
  ++p->parameter;
  if(p->stage==MP_READ)stage(p,p->parameter<5U?MP_WRITE:MP_CHECK_START,now+20U);
  else stage(p,p->parameter<4U?MP_POSTCHECK:MP_TARGET,now+20U);
 }else if(p->stage==MP_CHECK_START&&index==0x7019){
  if(!valid_position(value)||fabsf(value-p->origin)>TOLERANCE){MotorPosition_Stop(p,now,"ORIGIN_MOVED_BEFORE_ENABLE",true);return;}
  stage(p,MP_ENABLE,now);
 }else if(p->stage==MP_TARGET_READ&&index==0x7016){
  if(!target_matches(value,p->target)){MotorPosition_Stop(p,now,"POSITION_TARGET_MISMATCH",true);return;}
  stage(p,MP_MOVE,now);p->leg_at=now;p->settled=false;p->stable_samples=0;p->stable_span=0;
  p->sampled_position_speed=p->mean_position_speed=p->stable_position_travel=0;e->next_zero=e->next_iq=now;
 }else if(p->stage==MP_CLEAN_POSITION&&index==0x7019){
  if(!valid_position(value)){cleanup_failed(p);return;}
  p->actual=p->target=value;stage(p,MP_CLEAN_WRITE,now);
 }else if(p->stage==MP_CLEAN_READ&&index==0x7016){
  if(!target_matches(value,p->target)){cleanup_failed(p);return;}
  e->target_cleared=true;e->phase=ME_DONE;
 }
}
void MotorPosition_CheckSafety(MotorPosition *p,uint32_t now){
 MotorEnable *e=&p->core;
 if(e->run_requested&&!e->finishing){
  if(now-e->last_heartbeat>500U)MotorPosition_Stop(p,now,"HOST_TIMEOUT",true);
  else if(e->enable_confirmed&&now-e->last_feedback>500U)MotorPosition_Stop(p,now,"FEEDBACK_TIMEOUT",true);
  else if(e->enable_confirmed&&now-e->enable_at>=90000U)MotorPosition_Stop(p,now,"TOTAL_TIMEOUT",true);
  else if(e->enable_confirmed&&(now-e->last_iq>500U||now-e->last_velocity>500U||now-e->last_position>500U))MotorPosition_Stop(p,now,"TELEMETRY_TIMEOUT",true);
  else if(p->stage==MP_MOVE&&!p->stream_control){
   if(now-p->leg_at>=5000U)MotorPosition_Stop(p,now,"WAYPOINT_TIMEOUT",true);
  }
 }
}
void MotorPosition_Step(MotorPosition *p,uint32_t now,MotorEnableSend send,void *context){
 MotorEnable *e=&p->core;if(e->phase==ME_DONE||!send)return;
 MotorPosition_CheckSafety(p,now);
 if(e->phase!=ME_ACTIVE){MotorEnable_Step(e,now,send,context);return;}
 if(p->stage==MP_MOVE){
  CanFrame f;
  if(!p->stream_control&&(int32_t)(now-e->next_zero)>=0){f=write_parameter(p,0x7016,p->target);e->next_zero=now+e->refresh_ms;}
  else if((int32_t)(now-e->next_iq)>=0){static const unsigned indices[]={0x701A,0x701B,0x7019};f=packet(p,17,indices[e->telemetry_step]);e->telemetry_step=(uint8_t)((e->telemetry_step+1U)%3U);e->next_iq=now+e->query_ms;}
  else return;
  if(!send(context,&f,now))MotorPosition_Stop(p,now,"CAN_SUBMIT_REJECTED",true);
  return;
 }
 if(e->sent){if(now-e->sent_at>500U){if(e->finishing)cleanup_failed(p);else MotorPosition_Stop(p,now,"STAGE_TIMEOUT",true);}return;}
 if((int32_t)(now-e->due)<0)return;
 CanFrame f;unsigned index;float value;
 switch(p->stage){
 case MP_START:case MP_CHECK_START:case MP_CLEAN_POSITION:f=packet(p,17,0x7019);break;
 case MP_WRITE:case MP_READ:case MP_POSTCHECK:
  parameter(p,p->stage==MP_POSTCHECK,&index,&value);f=p->stage==MP_WRITE?write_parameter(p,index,value):packet(p,17,index);break;
 case MP_ENABLE:f=packet(p,3,0);break;
 case MP_TARGET:{static const float offsets[]={1,0,-1,0};p->target=p->stream_control?p->origin:p->origin+p->amplitude_rad*offsets[p->waypoints%4U];f=write_parameter(p,0x7016,p->target);break;}
 case MP_TARGET_READ:case MP_CLEAN_READ:f=packet(p,17,0x7016);break;
 case MP_CLEAN_WRITE:f=write_parameter(p,0x7016,p->target);break;
 default:return;
 }
 if(!send(context,&f,now)){if(e->finishing)cleanup_failed(p);else MotorPosition_Stop(p,now,"CAN_SUBMIT_REJECTED",true);return;}
 e->sent=true;e->sent_at=now;
 if(p->stage==MP_WRITE)stage(p,MP_READ,now+50U);
 else if(p->stage==MP_TARGET)stage(p,MP_TARGET_READ,now+50U);
 else if(p->stage==MP_CLEAN_WRITE)stage(p,MP_CLEAN_READ,now+50U);
 else if(p->stage==MP_ENABLE)e->enable_at=now;
}
bool MotorPosition_Passed(const MotorPosition *p){const MotorEnable *e=&p->core;return e->phase==ME_DONE&&p->waypoints==40U&&e->enable_confirmed&&e->stop_confirmed&&e->target_cleared&&!e->error&&strcmp(e->reason,"POSITION_COMPLETE")==0;}
