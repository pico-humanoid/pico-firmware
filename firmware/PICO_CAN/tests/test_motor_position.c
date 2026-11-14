#include "motor_position_logic.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line %d t=%lu %s\n",__LINE__,(unsigned long)now,#x);exit(1);}}while(0)
static MotorPosition p;
static uint32_t now,enables,targets;
static float actual,target,velocity,current,limit,speed,readback_bias;
static unsigned mode,motor_mode;
static bool pending,bad_limit,frozen,drop_feedback,drop_position;
static CanFrame reply;
static float get(const uint8_t *d){uint32_t b=0;for(unsigned i=0;i<4;++i)b|=(uint32_t)d[i]<<(8*i);float v;memcpy(&v,&b,4);return v;}
static void put(uint8_t *d,float v){uint32_t b;memcpy(&b,&v,4);for(unsigned i=0;i<4;++i)d[i]=(uint8_t)(b>>(8*i));}
static bool sender(void *ctx,const CanFrame *f,uint32_t tick){
 (void)ctx;CHECK(now==tick&&f->extended&&!f->remote&&f->dlc==8);CHECK((f->id&255U)==p.core.id&&((f->id>>8)&255U)==253U);
 unsigned type=f->id>>24,index=f->data[0]|((unsigned)f->data[1]<<8);CHECK(type==3||type==4||type==17||type==18);
 if(type==3||type==4){for(unsigned i=0;i<8;++i)CHECK(f->data[i]==0);}
 if(type==3){CHECK(mode==5&&limit==0.5f&&speed==0.2f&&fabsf(target-actual)<0.00873f);++enables;motor_mode=2;}
 else if(type==4)motor_mode=0;
 else if(type==18){
  CHECK(index==0x7016||index==0x7005||index==0x7018||index==0x7017);
  if(index==0x7005){CHECK(f->data[4]==5&&motor_mode==0);mode=5;}
  else if(index==0x7018){if(!bad_limit)limit=get(f->data+4);}
  else if(index==0x7017)speed=get(f->data+4);
  else{target=get(f->data+4);CHECK(fabsf(target-1.25f)<0.14f);if(p.stage==MP_TARGET)++targets;}
 }
 reply=(CanFrame){.extended=true,.dlc=8,.timestamp_ms=now+1};
 if(type==17){
  CHECK(index==0x7005||index==0x7018||index==0x7017||index==0x7016||index==0x7019||index==0x701A||index==0x701B);
  reply.id=0x11000000U|((uint32_t)p.core.id<<8)|253;reply.data[0]=f->data[0];reply.data[1]=f->data[1];
  if(index==0x7005)reply.data[4]=(uint8_t)mode;
  else put(reply.data+4,index==0x7018?limit:index==0x7017?speed:index==0x7016?target+readback_bias:index==0x7019?actual:index==0x701A?current:velocity);
 }else reply.id=0x02000000U|((uint32_t)motor_mode<<22)|((uint32_t)p.core.id<<8)|253;
 pending=!(drop_feedback&&type!=17)&&!(drop_position&&type==17&&index==0x7019);return true;
}
static void tick(bool hb){
 ++now;if(hb)MotorPosition_Heartbeat(&p,now);
 velocity=0;
 if(motor_mode==2&&!frozen){float d=target-actual;float step=fminf(fabsf(d),0.0002f);velocity=copysignf(step*1000,d);actual+=copysignf(step,d);}
 if(pending){pending=false;MotorPosition_OnFrame(&p,&reply,now);}
 MotorPosition_Step(&p,now,sender,0);
}
static void advance(unsigned ms,bool hb){while(ms--)tick(hb);}
static void init(unsigned id){
 now=enables=targets=0;actual=1.25f;target=-5;velocity=0;current=0.1f;limit=10;speed=2;mode=motor_mode=0;
 readback_bias=0;
 pending=bad_limit=frozen=drop_feedback=drop_position=false;MotorPosition_Init(&p,(uint8_t)id,253,now);
}
static void start(void){advance(500,true);CHECK(p.core.phase==ME_READY&&enables==0);CHECK(MotorPosition_Request(&p,now));}
int main(void){
 /* Exact real-board readback pairs from the failed 10P/00 log. */
 static const uint8_t wanted[][4]={{0x5B,0xCA,0xC3,0x40},{0x9B,0xCA,0xC3,0x40},{0x01,0x0F,0x94,0x40},{0x01,0x0F,0x94,0x40}};
 static const uint8_t returned[][4]={{0xFB,0xCA,0xC3,0x40},{0xBB,0xCA,0xC3,0x40},{0x52,0x0F,0x94,0x40},{0xF3,0x0F,0x94,0x40}};
 for(unsigned i=0;i<4;++i){
  init(1);p.core.phase=ME_ACTIVE;p.core.sent=true;p.core.sent_at=10;p.origin=get(wanted[i]);p.stage=MP_READ;p.parameter=0;
  CanFrame f={.id=0x110001FD,.timestamp_ms=11,.extended=true,.dlc=8};f.data[0]=0x16;f.data[1]=0x70;memcpy(f.data+4,returned[i],4);
  MotorPosition_OnFrame(&p,&f,11);CHECK(!p.core.error&&p.stage==MP_WRITE&&p.parameter==1);
 }
 init(1);readback_bias=0.000115395f;start();advance(85000,true);CHECK(MotorPosition_Passed(&p));
 init(2);readback_bias=0.001f;start();advance(2000,true);CHECK(enables==0&&p.core.error&&!MotorPosition_Passed(&p)&&p.neutralize_failed);CHECK(strcmp(p.core.reason,"POSITION_PARAMETER_MISMATCH")==0);
 init(1);readback_bias=NAN;start();advance(2000,true);CHECK(enables==0&&p.core.error&&!MotorPosition_Passed(&p));
 for(unsigned id=1;id<=2;++id){init(id);advance(1000,false);CHECK(enables==0&&!MotorPosition_Request(&p,now));start();advance(85000,true);
  CHECK(MotorPosition_Passed(&p)&&p.waypoints==40&&targets==40&&enables==1&&motor_mode==0&&fabsf(actual-1.25f)<0.00873f);CHECK(fabsf(target-actual)<0.0001f);
 }
 init(1);bad_limit=true;start();advance(2000,true);CHECK(enables==0&&p.core.error&&p.core.stop_confirmed&&!MotorPosition_Passed(&p));
 init(1);frozen=true;start();advance(10000,true);CHECK(p.core.error&&p.waypoints==0&&strcmp(p.core.reason,"WAYPOINT_TIMEOUT")==0&&motor_mode==0);
 init(1);start();advance(2000,true);advance(1000,false);CHECK(strcmp(p.core.reason,"HOST_TIMEOUT")==0&&p.core.stop_confirmed);
 init(2);start();advance(2000,true);drop_feedback=true;advance(1000,true);CHECK(strcmp(p.core.reason,"FEEDBACK_TIMEOUT")==0&&!p.core.stop_confirmed&&!MotorPosition_Passed(&p));
 init(1);start();advance(2000,true);drop_position=true;advance(1000,true);CHECK(p.core.error&&p.core.stop_confirmed&&!p.core.target_cleared&&!MotorPosition_Passed(&p));
 init(1);start();advance(2000,true);current=0.9f;advance(1000,true);CHECK(p.core.error&&strcmp(p.core.reason,"IQ_OVER_0.8A")==0&&motor_mode==0);
 init(1);start();advance(2000,true);MotorPosition_Stop(&p,now,"MANUAL_STOP",false);advance(300,true);CHECK(p.core.stop_confirmed&&p.core.target_cleared&&!MotorPosition_Passed(&p));
 init(2);now=0xFFFFF000U;MotorPosition_Init(&p,2,253,now);start();advance(85000,true);CHECK(MotorPosition_Passed(&p));
 puts("Position: nonzero origin, +/-5deg x10, dwell, limits, missing telemetry, stop cleanup and clock wrap: PASS");return 0;
}
