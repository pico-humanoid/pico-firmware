/* Shared-clock quintic trajectory. No HAL, no host-scheduled motion. */
#include "motor_sync_logic.h"
#include "protocol/robstride_spc.h"
#include <math.h>
#include <string.h>
#define DEG 0.01745329252f
float MotorSync_UnitReference(uint32_t elapsed){
 static const float knot[]={0,1,0,-1,0};
 if(elapsed>=MOTOR_SYNC_DURATION_MS)return 0;
 unsigned leg=(elapsed/MOTOR_SYNC_SEGMENT_MS)%4U;
 float u=(float)(elapsed%MOTOR_SYNC_SEGMENT_MS)/(float)MOTOR_SYNC_SEGMENT_MS;
 float h=u*u*u*(10.0f+u*(-15.0f+6.0f*u));
 return knot[leg]+(knot[leg+1U]-knot[leg])*h;
}
float MotorSync_Rms(const MotorSyncMetrics *m){return m->samples?sqrtf(m->sum_square/(float)m->samples):0;}
void MotorSync_Init(MotorSync *s,uint32_t now){
 memset(s,0,sizeof(*s));
 for(unsigned i=0;i<2;++i){
  MotorPosition *p=&s->motors[i];MotorPosition_Init(p,(uint8_t)(i+1U),253,now);
  p->stream_control=true;p->amplitude_rad=i==0?5*DEG:-3*DEG;
  p->dwell_ms=500U;p->core.query_ms=60U;p->core.due+=i*20U;
 }
}
void MotorSync_Heartbeat(MotorSync *s,uint32_t now){for(unsigned i=0;i<2;++i)MotorPosition_Heartbeat(&s->motors[i],now);}
void MotorSync_Stop(MotorSync *s,uint32_t now,const char *reason,bool error){
 s->failure|=error;
 for(unsigned i=0;i<2;++i)MotorPosition_Stop(&s->motors[i],now,reason,error);
}
bool MotorSync_Request(MotorSync *s,uint32_t now){
 for(unsigned i=0;i<2;++i){MotorEnable *e=&s->motors[i].core;
  if(e->phase!=ME_READY||!e->host_seen||now-e->last_heartbeat>500U||e->run_requested||e->error)return false;
 }
 for(unsigned i=0;i<2;++i)if(!MotorPosition_Request(&s->motors[i],now)){MotorSync_Stop(s,now,"GROUP_START_REJECTED",true);return false;}
 return true;
}
static void interlock(MotorSync *s,uint32_t now){
 for(unsigned i=0;i<2;++i){MotorEnable *e=&s->motors[i].core;
  if(e->error)s->failure=true;
  if(e->finishing)for(unsigned j=0;j<2;++j)if(!s->motors[j].core.finishing&&s->motors[j].core.phase!=ME_DONE)
   MotorPosition_Stop(&s->motors[j],now,e->reason,e->error);
 }
}
static void progress(MotorSync *s){
 MotorSyncMetrics *a=&s->metrics[0],*b=&s->metrics[1];s->progress_valid=false;
 if(a->history<2U||b->history<2U)return;
 uint32_t t=(int32_t)(a->at[1]-b->at[1])<0?a->at[1]:b->at[1];
 float normalized[2];
 for(unsigned i=0;i<2;++i){MotorSyncMetrics *m=&s->metrics[i];
  uint32_t dt=m->at[1]-m->at[0];
  if(dt==0U||dt>500U||(int32_t)(t-m->at[0])<0||(int32_t)(m->at[1]-t)<0)return;
  float q=m->position[0]+(m->position[1]-m->position[0])*(float)(t-m->at[0])/(float)dt;
  normalized[i]=(q-s->motors[i].origin)/s->motors[i].amplitude_rad;
 }
 s->progress_gap=normalized[0]-normalized[1];s->progress_at=t;s->progress_valid=true;
 s->max_progress_gap=fmaxf(s->max_progress_gap,fabsf(s->progress_gap));
}
void MotorSync_OnFrame(MotorSync *s,const CanFrame *f,uint32_t now){
 for(unsigned i=0;i<2;++i)MotorPosition_OnFrame(&s->motors[i],f,now);
 interlock(s,now);
 if(!s->started||s->complete||!CanFrame_IsValid(f)||!f->extended||f->remote||f->dlc!=8U||
    ((f->id>>24)&31U)!=17U||(f->id&255U)!=253U||f->data[0]!=0x19U||f->data[1]!=0x70U)return;
 unsigned id=(f->id>>8)&255U;if(id<1U||id>2U)return;
 MotorPosition *p=&s->motors[id-1U];MotorEnable *e=&p->core;MotorSyncMetrics *m=&s->metrics[id-1U];
 if(e->finishing||e->error||(int32_t)(f->timestamp_ms-s->started_at)<0||
    (m->history>0U&&(int32_t)(f->timestamp_ms-m->at[1])<=0))return;
 float value=RsSpc_Float(f->data+4);if(!isfinite(value))return;
 if(m->history>0U){m->position[0]=m->position[1];m->at[0]=m->at[1];}
 m->position[1]=value;m->at[1]=f->timestamp_ms;if(m->history<2U)++m->history;
 float error=value-p->origin-p->amplitude_rad*MotorSync_UnitReference(f->timestamp_ms-s->started_at);
 m->last_error=error;
 if(f->timestamp_ms-s->started_at<=MOTOR_SYNC_DURATION_MS){
  ++m->samples;m->sum_square+=error*error;m->peak=fmaxf(m->peak,fabsf(error));
  m->minimum=fminf(m->minimum,value-p->origin);m->maximum=fmaxf(m->maximum,value-p->origin);
 }
 if(fabsf(error)>2*DEG){
  if(!m->bad_tracking){m->bad_tracking=true;m->bad_since=f->timestamp_ms;}
  else if(f->timestamp_ms-m->bad_since>=500U)MotorSync_Stop(s,now,"TRACKING_ERROR_OVER_2_DEG",true);
 }else m->bad_tracking=false;
 progress(s);
}
static bool prepared(const MotorPosition *p){const MotorEnable *e=&p->core;return e->phase==ME_ACTIVE&&p->stage==MP_MOVE&&e->enable_confirmed&&!e->finishing&&e->iq_samples&&e->velocity_samples&&e->position_samples;}
static bool quality(const MotorSync *s){
 for(unsigned i=0;i<2;++i){const MotorSyncMetrics *m=&s->metrics[i];float a=fabsf(s->motors[i].amplitude_rad);
  if(m->samples<100U||m->peak>2*DEG||MotorSync_Rms(m)>DEG||m->maximum<a-0.5f*DEG||m->minimum> -a+0.5f*DEG)return false;
 }return true;
}
typedef struct {MotorSync *sync;MotorEnableSend send;void *context;} Emitter;
static bool emit(void *context,const CanFrame *f,uint32_t now){
 Emitter *e=context;if(e->sync->tx_budget==0U)return false;
 --e->sync->tx_budget;return e->send(e->context,f,now);
}
void MotorSync_Step(MotorSync *s,uint32_t now,unsigned tx_budget,MotorEnableSend send,void *context){
 if(!send)return;
 s->tx_budget=tx_budget;Emitter emitter={s,send,context};
 for(unsigned i=0;i<2;++i)MotorPosition_CheckSafety(&s->motors[i],now);
 interlock(s,now);
 if(s->motors[0].stage==MP_TARGET&&s->motors[1].stage==MP_TARGET)s->barrier_released=true;
 bool active=true;for(unsigned i=0;i<2;++i)if(s->motors[i].core.finishing||s->motors[i].core.phase==ME_DONE)active=false;
 if(active&&!s->started&&prepared(&s->motors[0])&&prepared(&s->motors[1])){
  for(unsigned i=0;i<2;++i)if(fabsf(s->motors[i].actual-s->motors[i].origin)>0.5f*DEG){MotorSync_Stop(s,now,"ORIGIN_MOVED_BEFORE_STREAM",true);active=false;}
  if(active){s->started=true;s->started_at=s->next_pair=now;for(unsigned i=0;i<2;++i)s->motors[i].core.reason="SYNC_TRACKING";}
 }
 if(active&&s->started){
  s->elapsed=now-s->started_at;s->segments=s->elapsed/MOTOR_SYNC_SEGMENT_MS;if(s->segments>20U)s->segments=20U;
  if((int32_t)(now-s->next_pair)>=0){
   uint32_t late=now-s->next_pair;s->max_lateness_ms=late>s->max_lateness_ms?late:s->max_lateness_ms;
   if(late>200U){MotorSync_Stop(s,now,"TARGET_SCHEDULER_OVERRUN",true);active=false;}
   else if(s->tx_budget>=2U){
    float unit=MotorSync_UnitReference(s->elapsed);
    for(unsigned i=0;i<2;++i){
     MotorPosition *p=&s->motors[i];p->target=p->origin+p->amplitude_rad*unit;
     CanFrame f=RsSpc_Frame(p->core.id,p->core.host,18,0x7016,p->target);
     if(!emit(&emitter,&f,now)){MotorSync_Stop(s,now,"CAN_SUBMIT_REJECTED",true);active=false;break;}
    }
    if(active){++s->pairs;s->next_pair=s->started_at+(s->elapsed/MOTOR_SYNC_PERIOD_MS+1U)*MOTOR_SYNC_PERIOD_MS;}
   }
  }
  if(active&&s->elapsed>=MOTOR_SYNC_DURATION_MS){
   if(!s->settling){s->settling=true;for(unsigned i=0;i<2;++i){MotorPosition *p=&s->motors[i];p->stream_settling=true;p->settled=false;p->stable_samples=0;p->core.reason="SYNC_SETTLING";}}
   if(s->motors[0].stream_settled&&s->motors[1].stream_settled){
    s->complete=quality(s);
    for(unsigned i=0;i<2;++i)s->motors[i].core.motion_confirmed=s->complete;
    MotorSync_Stop(s,now,s->complete?"SYNC_TRAJECTORY_COMPLETE":"TRACKING_QUALITY_FAILED",!s->complete);
   }else if(s->elapsed>=MOTOR_SYNC_DURATION_MS+3000U)MotorSync_Stop(s,now,"FINAL_SETTLE_TIMEOUT",true);
  }
 }
 for(unsigned i=0;i<2;++i){
  if(s->tx_budget>0U&&(s->motors[i].stage!=MP_TARGET||s->barrier_released||s->motors[i].core.finishing))MotorPosition_Step(&s->motors[i],now,emit,&emitter);
  interlock(s,now);
 }
}
bool MotorSync_Passed(const MotorSync *s){
 if(!s->complete||s->failure||s->segments!=20U)return false;
 for(unsigned i=0;i<2;++i){const MotorEnable *e=&s->motors[i].core;
  if(e->phase!=ME_DONE||!e->enable_confirmed||!e->stop_confirmed||!e->target_cleared||e->error||strcmp(e->reason,"SYNC_TRAJECTORY_COMPLETE")!=0)return false;
 }return true;
}
