#include "motor_enable_logic.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
static MotorEnable e;
static uint32_t now,enables,stops,first_enable;
static uint8_t run_mode,motor_mode;
static float iq_ref;
static bool pending,wrong_mode,wrong_zero,no_responses,wrong_id,reject_enable;
static CanFrame reply;
static void put_float(uint8_t *p,float f){uint32_t b;memcpy(&b,&f,4);for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(b>>(8U*i));}
static bool sender(void *ctx,const CanFrame *f,uint32_t tick){
    (void)ctx;CHECK(tick==now);CHECK(f->extended&&!f->remote&&f->dlc==8);
    CHECK((f->id&255U)==e.id&&((f->id>>8)&255U)==e.host);
    uint8_t type=(uint8_t)(f->id>>24);uint16_t index=(uint16_t)(f->data[0]|(f->data[1]<<8));
    CHECK(type==3||type==4||type==17||type==18);
    reply=(CanFrame){.extended=true,.dlc=8,.timestamp_ms=now+1U};
    if(type==3||type==4){
        for(unsigned i=0;i<8;++i)CHECK(f->data[i]==0);
        if(type==3){if(reject_enable)return false;++enables;first_enable=now;motor_mode=2;}
        else{++stops;motor_mode=0;}
    }else if(type==18){
        CHECK(index==0x7005||index==0x7006);
        if(index==0x7005){CHECK(f->data[4]==3);if(!wrong_mode)run_mode=3;}
        else{for(unsigned i=4;i<8;++i)CHECK(f->data[i]==0);if(!wrong_zero)iq_ref=0;}
    }
    if(type==17){
        CHECK(index==0x7005||index==0x7006||index==0x701A);
        reply.id=0x11000000U|((uint32_t)e.id<<8)|e.host;reply.data[0]=f->data[0];reply.data[1]=f->data[1];
        if(index==0x7005)reply.data[4]=run_mode;else put_float(reply.data+4,index==0x7006?iq_ref:0.0f);
    }else reply.id=0x02000000U|((uint32_t)motor_mode<<22)|((uint32_t)e.id<<8)|e.host;
    if(wrong_id)reply.id^=0x100U;
    pending=!no_responses;return true;
}
static void init(uint8_t id){
    memset(&e,0,sizeof(e));now=enables=stops=first_enable=0;run_mode=motor_mode=0;iq_ref=1.5f;
    pending=wrong_mode=wrong_zero=no_responses=wrong_id=reject_enable=false;
    MotorEnable_Init(&e,id,0xFD,now);
}
static void tick(bool heartbeat){
    ++now;
    if(heartbeat)MotorEnable_Heartbeat(&e,now);
    if(pending){pending=false;MotorEnable_OnFrame(&e,&reply,now);}
    MotorEnable_Step(&e,now,sender,0);
}
static void advance(unsigned ms,bool heartbeat){for(unsigned i=0;i<ms;++i)tick(heartbeat);}
static void precheck(void){advance(400,true);CHECK(e.phase==ME_READY);CHECK(enables==0);}
int main(void){
    for(uint8_t id=1;id<=2;++id){
        init(id);advance(5000,false);CHECK(enables==0);CHECK(e.phase==ME_READY);
        CHECK(!MotorEnable_Request(&e,now));MotorEnable_Heartbeat(&e,now);CHECK(MotorEnable_Request(&e,now));
        advance(4000,true);CHECK(e.phase==ME_DONE&&e.enable_confirmed&&e.stop_confirmed&&!e.error&&e.iq_samples>0);
        CHECK(enables==1&&motor_mode==0);CHECK(now-first_enable>=3000);CHECK(strcmp(e.reason,"AUTO_STOP")==0);
        CHECK(!MotorEnable_Request(&e,now));
    }
    init(1);wrong_id=true;advance(3000,true);CHECK(e.phase==ME_STOPPING&&e.stop_unconfirmed&&enables==0);
    init(1);precheck();wrong_mode=true;CHECK(MotorEnable_Request(&e,now));advance(1000,true);
    CHECK(e.phase==ME_DONE&&e.error&&enables==0);
    init(2);precheck();wrong_zero=true;CHECK(MotorEnable_Request(&e,now));advance(1000,true);
    CHECK(e.phase==ME_DONE&&e.error&&enables==0);
    init(2);precheck();CHECK(MotorEnable_Request(&e,now));advance(1000,false);
    CHECK(e.phase==ME_DONE&&e.error&&strcmp(e.reason,"HOST_TIMEOUT")==0&&motor_mode==0);
    init(2);precheck();CHECK(MotorEnable_Request(&e,now));advance(300,true);CHECK(e.phase==ME_ACTIVE);
    MotorEnable_Stop(&e,now,"MANUAL_STOP",false);advance(10,true);CHECK(e.phase==ME_DONE&&motor_mode==0);
    init(1);precheck();CHECK(MotorEnable_Request(&e,now));advance(300,true);no_responses=true;pending=false;
    advance(2800,true);CHECK(e.phase==ME_STOPPING&&e.error&&e.stop_unconfirmed);
    CHECK(strcmp(e.reason,"FEEDBACK_TIMEOUT")==0);
    init(1);precheck();CHECK(MotorEnable_Request(&e,now));advance(300,true);
    CanFrame bad={.extended=true,.dlc=8,.id=0x110001FDU,.timestamp_ms=now};bad.data[0]=0x1A;bad.data[1]=0x70;
    put_float(bad.data+4,0.3f);MotorEnable_OnFrame(&e,&bad,now);CHECK(e.finishing&&e.error);
    init(1);precheck();CHECK(MotorEnable_Request(&e,now));advance(300,true);
    bad.timestamp_ms=now;put_float(bad.data+4,NAN);MotorEnable_OnFrame(&e,&bad,now);CHECK(e.error&&isfinite(e.iq));
    init(1);precheck();reject_enable=true;CHECK(MotorEnable_Request(&e,now));advance(1000,true);
    CHECK(e.error&&e.phase==ME_DONE&&enables==0);
    /* Timer rollover must not extend the enabled interval. */
    init(2);precheck();CHECK(MotorEnable_Request(&e,now));advance(300,true);
    now=0xFFFFFF00U;e.enable_at=now;e.sent_at=0;e.last_feedback=now;e.last_heartbeat=now;
    e.next_zero=now;e.next_iq=now;pending=false;
    advance(3500,true);CHECK(e.phase==ME_DONE&&!e.error&&motor_mode==0);
    puts("Motor enable protocol, readback gates, deadman, faults and stop tests PASS");return 0;
}
