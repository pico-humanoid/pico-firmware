#include "motor_sync_logic.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
static MotorSync group;static uint32_t first_at,last_pair;static unsigned writes,pairs,last_id;static bool exact_cadence;
static void fresh(uint32_t now){
 for(unsigned i=0;i<2;++i){MotorEnable *e=&group.motors[i].core;e->last_heartbeat=e->last_iq=e->last_velocity=e->last_position=e->last_feedback=now;}
}
static void prepare(uint32_t now){
 MotorSync_Init(&group,now);writes=pairs=last_id=0;exact_cadence=false;first_at=now;
 for(unsigned i=0;i<2;++i){MotorPosition *p=&group.motors[i];MotorEnable *e=&p->core;
  e->phase=ME_ACTIVE;e->host_seen=e->run_requested=e->enable_confirmed=true;e->enable_at=now;
  e->iq_samples=e->velocity_samples=e->position_samples=1;p->velocity_count=5;p->stage=MP_MOVE;
  p->origin=p->actual=p->target=i==0?5.0f:-2.0f;
 }fresh(now);
}
static bool send_frame(void *ctx,const CanFrame *f,uint32_t now){
 (void)ctx;unsigned type=f->id>>24,id=f->id&255U,index=f->data[0]|((unsigned)f->data[1]<<8);
 CHECK(id==1U||id==2U);CHECK(type==18U||type==17U||type==4U);
 if(type==18U&&index==0x7016U){
  float value;memcpy(&value,f->data+4,4);MotorPosition *p=&group.motors[id-1U];
  CHECK(fabsf(value-p->origin-p->amplitude_rad*MotorSync_UnitReference(now-first_at))<0.000001f);
  ++writes;
  if(id==1U){CHECK(last_id!=1U);if(pairs&&exact_cadence)CHECK(now-last_pair==50U);last_pair=now;last_id=1U;}
  else{CHECK(last_id==1U&&now==last_pair);last_id=2U;++pairs;}
 }return true;
}
static void positions(uint32_t now){
 for(unsigned i=0;i<2;++i){MotorPosition *p=&group.motors[i];float q=p->origin+p->amplitude_rad*MotorSync_UnitReference(now-first_at);
  CanFrame f={.id=0x110000FDU|((i+1U)<<8),.timestamp_ms=now,.extended=true,.dlc=8,.data={0x19,0x70}};
  memcpy(f.data+4,&q,4);MotorSync_OnFrame(&group,&f,now);
 }
}
int main(void){
 /* Endpoint position, zero endpoint slopes, amplitude and speed bound. */
 const float knots[]={0,1,0,-1,0};float previous=MotorSync_UnitReference(0),peak_speed=0;
 for(unsigned t=1;t<=40000U;++t){float v=MotorSync_UnitReference(t);CHECK(fabsf(v)<=1.000001f);
  float speed=fabsf(v-previous)*1000*0.0872664626f;peak_speed=fmaxf(peak_speed,speed);previous=v;
  if(t%2000U==0U){CHECK(fabsf(v-knots[(t/2000U)%4U])<0.000001f);CHECK(speed<0.0001f);}
 }
 CHECK(peak_speed<0.083f);CHECK(MotorSync_UnitReference(45000U)==0);
 /* Complete common-clock scheduling, including HAL tick wraparound. */
 for(unsigned wrap=0;wrap<2;++wrap){
  uint32_t start=wrap?0xFFFFF000U:1000U;prepare(start);exact_cadence=true;
  for(unsigned dt=0;dt<=40000U;++dt){uint32_t now=start+dt;fresh(now);if(dt%100U==0U)positions(now);MotorSync_Step(&group,now,3,send_frame,0);}
  CHECK(!group.failure&&group.settling&&group.segments==20U&&pairs==801U&&writes==1602U);
  CHECK(group.max_lateness_ms==0U&&group.metrics[0].samples>=399U&&group.metrics[1].samples>=399U);
  CHECK(MotorSync_Rms(&group.metrics[0])<0.00001f&&group.max_progress_gap<0.0001f);
 }
 /* Wait for room for the whole pair; skip obsolete ticks, never burst. */
 prepare(1000U);MotorSync_Step(&group,1000U,3,send_frame,0);fresh(1050U);MotorSync_Step(&group,1050U,1,send_frame,0);CHECK(pairs==1U);
 fresh(1070U);MotorSync_Step(&group,1070U,2,send_frame,0);CHECK(pairs==2U&&group.max_lateness_ms==20U);
 fresh(1100U);MotorSync_Step(&group,1100U,3,send_frame,0);CHECK(pairs==3U);
 fresh(1351U);MotorSync_Step(&group,1351U,0,send_frame,0);CHECK(group.failure&&group.motors[0].core.finishing&&group.motors[1].core.finishing);
 CHECK(strcmp(group.motors[0].core.reason,"TARGET_SCHEDULER_OVERRUN")==0);
 puts("Quintic endpoints/speed, 801 common pairs, 40s x tick wrap, RMS/interpolation, capacity deferral and stale-target overrun: PASS");return 0;
}
