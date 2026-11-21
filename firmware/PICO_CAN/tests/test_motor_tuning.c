#include "motor_tuning.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static MotorTuning t;static CanFrame pending;static bool queued,drop,host=true,fail_read,jump;static uint32_t now;static float values[0x30];static unsigned enables,writes,refreshes;static bool running;
static void logline(const char *s){(void)s;}
static bool sendframe(void *ctx,const CanFrame *f,uint32_t at){(void)ctx;(void)at;assert(!queued);assert(CanFrame_IsValid(f));pending=*f;queued=true;return true;}
static void reply(void){
 CanFrame f=pending;queued=false;if(drop)return;unsigned type=f.id>>24;uint16_t idx=f.data[0]|((unsigned)f.data[1]<<8);
 CanFrame r={.extended=true,.dlc=8,.timestamp_ms=now};
 if(type==0){r.id=(1U<<8)|254;memcpy(r.data,"UID12345",8);}
 else if(type==4||type==3||type==18){
  if(type==3){++enables;running=true;}if(type==4)running=false;
  if(type==18){++writes;assert(idx==0x7005||idx==0x700A||idx==0x7016||idx==0x7017||idx==0x7018||idx==0x7022);values[idx-0x7000]=idx==0x7005?f.data[4]:RsSpc_Float(f.data+4);if(idx==0x700A||idx==0x7016)++refreshes;}
  r.id=(2UL<<24)|((running?2UL:0UL)<<22)|(1U<<8)|253;
 }else{assert(type==17);r.id=(17UL<<24)|(1U<<8)|253;r.data[0]=idx&255;r.data[1]=idx>>8;
  float v=values[idx-0x7000];if(idx==0x7019&&jump)v+=0.3f;
  if(idx==0x7005)r.data[4]=(uint8_t)v;else memcpy(r.data+4,&v,4);
  if(fail_read)r.id|=1UL<<16;
 }
 MotorTuning_OnFrame(&t,&r,now);
}
static void tick(unsigned duration){for(unsigned n=0;n<duration;n++){++now;if(queued)reply();if(host)MotorTuning_Heartbeat(&t,now);MotorTuning_Step(&t,now,sendframe,NULL);}}
static void init(void){memset(values,0,sizeof(values));values[0x19]=1.0f;now=0;queued=drop=fail_read=jump=running=false;host=true;enables=writes=refreshes=0;MotorTuning_Init(&t,1,0,logline);tick(1200);assert(t.stage==TU_READY);assert(enables==0&&writes==0);}
static void arm(TuningMode mode){assert(MotorTuning_Arm(&t,mode,1,0,mode==TUNING_POSITION?200:0,now));tick(700);assert(t.stage==TU_ACTIVE);assert(t.enabled&&!t.stopped&&enables==1);}
int main(void){
 init();assert(!MotorTuning_Arm(&t,TUNING_POSITION,1,30001,200,now));assert(!MotorTuning_Arm(&t,TUNING_SPEED,1,301,0,now));assert(!MotorTuning_Arm(&t,TUNING_POSITION,1,0,700,now));arm(TUNING_POSITION);
 assert(!MotorTuning_Arm(&t,TUNING_SPEED,2,10,0,now));assert(MotorTuning_Set(&t,2,5000,100,now));assert(!MotorTuning_Set(&t,2,0,100,now));
 tick(24);assert(t.applied_seq<2);assert(MotorTuning_Set(&t,3,-3000,300,now));tick(500);assert(t.applied_seq==3&&fabsf(t.target-(1.0f-0.05235988f))<0.0001f);assert(t.samples>5&&refreshes>5);
 /* Latest commands must not starve actual telemetry. */
 for(unsigned i=4;i<100;i++){assert(MotorTuning_Set(&t,i,0,200,now));tick(5);}tick(150);assert(t.stage==TU_ACTIVE&&t.samples>10);
 MotorTuning_Stop(&t,now,"USER_STOP",false);tick(400);assert(t.stage==TU_DONE&&t.stopped&&t.target_cleared&&!t.error);assert(fabsf(values[0x16]-values[0x19])<0.0001f);
 init();arm(TUNING_SPEED);assert(MotorTuning_Set(&t,2,-150,0,now));tick(200);assert(t.applied_seq==2&&fabsf(t.speed_target+0.15f)<0.00001f);tick(3000);assert(t.stage==TU_DONE&&t.stopped&&t.target_cleared&&!t.error);assert(values[0xA]==0);
 init();arm(TUNING_SPEED);host=false;tick(1000);assert(t.stage==TU_DONE&&t.stopped&&t.target_cleared&&t.error&&!strcmp(t.reason,"HOST_TIMEOUT"));
 init();arm(TUNING_POSITION);jump=true;tick(500);assert(t.stage==TU_DONE&&t.stopped&&t.error);assert(!strcmp(t.reason,"POSITION_SAMPLE_JUMP"));
 init();arm(TUNING_POSITION);drop=true;tick(2500);assert(t.stage==TU_DONE&&!t.stopped&&!t.target_cleared&&t.error);
 init();fail_read=true;assert(MotorTuning_Arm(&t,TUNING_POSITION,1,0,200,now));tick(1000);assert(t.stage==TU_DONE&&enables==0&&t.error);
 init();arm(TUNING_POSITION);values[0x1A]=1.1f;tick(800);assert(t.stage==TU_DONE&&t.error&&t.stopped&&!strcmp(t.reason,"CURRENT_LIMIT"));
 init();arm(TUNING_POSITION);assert(MotorTuning_Set(&t,2,30000,10,now));tick(250);assert(t.applied_seq==2&&fabsf(values[0x16]-(1+0.52359878f))<0.0001f&&fabsf(values[0x17]-.01f)<0.00001f);assert(values[0x18]==.5f);
 assert(MotorTuning_Set(&t,3,-30000,300,now));tick(250);assert(t.applied_seq==3&&fabsf(values[0x16]-(1-0.52359878f))<0.0001f);
 init();arm(TUNING_POSITION);for(unsigned n=0;n<120&&t.stage<TU_STOP;n++){values[0x19]+=.005f;tick(30);}tick(500);assert(t.stopped&&t.error&&!strcmp(t.reason,"DISPLACEMENT_LIMIT"));
 init();arm(TUNING_SPEED);assert(values[5]==2&&values[0x18]==.5f&&values[0x22]==.5f);assert(MotorTuning_Set(&t,2,300,0,now));tick(200);assert(t.applied_seq==2&&fabsf(values[0xA]-.3f)<.00001f);
 values[0x1B]=.51f;tick(500);assert(t.stopped&&t.error&&!strcmp(t.reason,"SPEED_LIMIT"));assert(values[0xA]==0);
 init();arm(TUNING_SPEED);assert(MotorTuning_Set(&t,2,200,0,now));values[0x1A]=.45f;tick(2000);assert(t.error&&t.stopped&&!strcmp(t.reason,"SUSPECTED_OBSTRUCTION"));
 init();arm(TUNING_SPEED);assert(MotorTuning_Set(&t,2,200,0,now));values[0x1A]=.45f;tick(500);values[0x1A]=0;tick(300);assert(!t.error);
 puts("tuning: no-auto-enable, bounds, readbacks, coalescing, refresh, telemetry, both cleanup modes and fault stops OK");return 0;
}
