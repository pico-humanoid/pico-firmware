#include "motor_position_logic.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
typedef struct {uint32_t tick,id;uint8_t data[8];} ReplayFrame;
#include "fixtures/rs00_settle_20261113.h"
static float scalar(const uint8_t *d){uint32_t b=0;for(unsigned i=0;i<4;++i)b|=(uint32_t)d[i]<<(8*i);float v;memcpy(&v,&b,4);return v;}
static void init(MotorPosition *p,uint32_t dwell){
 MotorPosition_Init(p,2,253,0);p->core.phase=ME_ACTIVE;p->core.enable_confirmed=true;
 p->core.run_requested=true;p->stage=MP_MOVE;p->dwell_ms=dwell;p->target=p->origin=0;
}
static void frame(MotorPosition *p,unsigned index,float value,uint32_t now){
 CanFrame f={.id=0x110002FD,.extended=true,.dlc=8,.timestamp_ms=now};f.data[0]=(uint8_t)index;f.data[1]=(uint8_t)(index>>8);
 uint32_t b;memcpy(&b,&value,4);for(unsigned i=0;i<4;++i)f.data[i+4]=(uint8_t)(b>>(8*i));MotorPosition_OnFrame(p,&f,now);
}
static void sample(MotorPosition *p,float pos,float vel,uint32_t now){frame(p,0x701A,0.1f,now);frame(p,0x701B,vel,now);frame(p,0x7019,pos,now);}
static void replay(const ReplayFrame *frames,size_t count,float origin,float target,uint32_t start,bool expect_v2_failure){
 MotorPosition p;init(&p,800);p.origin=origin;p.target=target;p.leg_at=start;
 bool completed=false,old_qualified=false,old_settled=false;float velocity=0;uint32_t old_at=0,qualified_at=0;
 float history[5]={0};unsigned history_count=0,history_cursor=0;
 bool v2_settled=false,v2_qualified=false;uint32_t v2_at=0,v2_longest=0;
 for(size_t i=0;i<count;++i){
  const ReplayFrame *r=&frames[i];CanFrame f={.id=r->id,.timestamp_ms=r->tick,.extended=true,.dlc=8};memcpy(f.data,r->data,8);
  if(r->id==0x110002FD){
   unsigned index=r->data[0]|((unsigned)r->data[1]<<8);float value=scalar(r->data+4);
   if(index==0x701B){velocity=value;history[history_cursor]=fabsf(value);history_cursor=(history_cursor+1U)%5U;if(history_count<5U)++history_count;}
   if(index==0x7019){
    bool good=fabsf(value-target)<=0.0087266463f&&fabsf(velocity)<0.03f;
    if(!good)old_settled=false;
    else if(!old_settled){old_settled=true;old_at=r->tick;}
    else if(r->tick-old_at>=800)old_qualified=true;
    float sorted[5];memcpy(sorted,history,sizeof(sorted));
    for(unsigned a=1;a<history_count;++a){float v=sorted[a];unsigned b=a;while(b>0U&&sorted[b-1U]>v){sorted[b]=sorted[b-1U];--b;}sorted[b]=v;}
    bool v2_good=fabsf(value-target)<=0.0087266463f&&history_count==5U&&sorted[2]<0.03f;
    if(!v2_good)v2_settled=false;
    else if(!v2_settled){v2_settled=true;v2_at=r->tick;}
    else{if(r->tick-v2_at>v2_longest)v2_longest=r->tick-v2_at;if(r->tick-v2_at>=800)v2_qualified=true;}
   }
  }
  if(!completed){MotorPosition_OnFrame(&p,&f,r->tick);CHECK(!p.core.error);if(p.waypoints==1){completed=true;qualified_at=r->tick;}}
 }
 CHECK(completed&&!old_qualified);CHECK(qualified_at-start<5000);
 if(expect_v2_failure)CHECK(!v2_qualified);
 printf("RS00 log replay: V3 qualified after %lums; V2 median-speed longest candidate %lums\n",(unsigned long)(qualified_at-start),(unsigned long)v2_longest);
}
int main(void){
 replay(replay_0,sizeof(replay_0)/sizeof(replay_0[0]),replay_origin_0,replay_target_0,replay_start_0,false);
 replay(replay_1,sizeof(replay_1)/sizeof(replay_1[0]),replay_origin_1,replay_target_1,replay_start_1,false);
 replay(replay_2,sizeof(replay_2)/sizeof(replay_2[0]),replay_origin_2,replay_target_2,replay_start_2,true);
 MotorPosition p;
 init(&p,800);for(unsigned i=0;i<12;++i)sample(&p,(i%2?0.0001f:-0.0001f),(i%5==0?0.12f:0.005f),100+i*180);CHECK(p.waypoints==1);
 init(&p,800);for(unsigned i=0;i<12;++i)sample(&p,0,i%2?0.12f:-0.07f,100+i*180);CHECK(p.waypoints==1&&!p.core.error); /* reported velocity disagreement, sampled position stationary */
 init(&p,800);for(unsigned i=0;i<70;++i)sample(&p,i%2?0.00075f:-0.00075f,0,100+i*20);CHECK(p.waypoints==0); /* small-range motion with fast position increments */
 init(&p,800);for(unsigned i=0;i<10;++i)sample(&p,i*0.0005f,0,100+i*180);CHECK(p.waypoints==0); /* slow drift, all inside target tolerance */
 init(&p,800);for(unsigned i=0;i<10;++i)sample(&p,i%2?0.0014f:-0.0014f,0,100+i*180);CHECK(p.waypoints==0); /* oscillation exceeds stable range */
 init(&p,800);for(unsigned i=0;i<10;++i)sample(&p,0.01f,0,100+i*180);CHECK(p.waypoints==0);
 init(&p,800);for(unsigned i=0;i<5;++i)frame(&p,0x701B,0,10+i);sample(&p,0,0,100);sample(&p,0,0,100);sample(&p,0,0,100);CHECK(p.stable_samples==1&&p.waypoints==0);
 sample(&p,0,0,1000);CHECK(p.stable_samples==1&&p.waypoints==0); /* data gap resets dwell */
 init(&p,500);for(unsigned i=0;i<5;++i)frame(&p,0x701B,0,10+i);sample(&p,0,0,100);sample(&p,0,0,600);CHECK(p.waypoints==0); /* two samples are insufficient */
 init(&p,500);sample(&p,0,0.5f,100);CHECK(p.core.error&&p.core.finishing); /* raw overspeed still trips */
 init(&p,500);frame(&p,0x701A,0.9f,100);CHECK(p.core.error);
 init(&p,500);frame(&p,0x701B,NAN,100);CHECK(p.core.error);
 init(&p,800);p.leg_at=0xFFFFFE00U;for(unsigned i=0;i<12;++i)sample(&p,0,0,(uint32_t)(0xFFFFFE00U+i*180U));CHECK(p.waypoints==1);
 puts("Stationary noise accepted; drift/oscillation/gaps/out-of-tolerance rejected; current/velocity trips retained: PASS");return 0;
}
