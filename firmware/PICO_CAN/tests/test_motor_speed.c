#include "motor_enable_logic.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
static MotorEnable e;
#ifndef TEST_EXPECTED_LIMIT_A
#define TEST_EXPECTED_LIMIT_A 0.5f
#endif
static uint32_t now,enables,motions,enable_at,stop_at;
static uint8_t mode,motor_mode;
static float speed_ref,limit,accel,position;
static bool pending,bad_limit,no_motion,drop_feedback,drop_iq,drop_clear,reject_motion,reset_limit_on_enable,wrong_id;
static CanFrame response;
static void put(uint8_t *p,float f){uint32_t u;memcpy(&u,&f,4);for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(u>>(8*i));}
static float get(const uint8_t *p){uint32_t u=0;for(unsigned i=0;i<4;++i)u|=(uint32_t)p[i]<<(8*i);float f;memcpy(&f,&u,4);return f;}
static bool send_frame(void *ctx,const CanFrame *f,uint32_t t){
    (void)ctx;CHECK(now==t&&f->extended&&!f->remote&&f->dlc==8);
    CHECK((f->id&255)==e.id&&((f->id>>8)&255)==e.host);
    unsigned type=f->id>>24,index=f->data[0]|((unsigned)f->data[1]<<8);
    CHECK(type==3||type==4||type==17||type==18);
    response=(CanFrame){.extended=true,.dlc=8,.timestamp_ms=now+1};
    if(type==3||type==4){
        for(unsigned i=0;i<8;++i)CHECK(f->data[i]==0);
        if(type==3){
            CHECK(speed_ref==0&&mode==2&&limit==TEST_EXPECTED_LIMIT_A&&accel==0.5f);
            ++enables;enable_at=now;motor_mode=2;
            if(reset_limit_on_enable)limit=10;
        }else{motor_mode=0;if(enables)stop_at=now;}
    }else if(type==18){
        CHECK(index==0x7005||index==0x700A||index==0x7018||index==0x7022);
        if(index==0x7005){CHECK(f->data[4]==2&&motor_mode==0);mode=2;}
        else if(index==0x7018){CHECK(get(f->data+4)==TEST_EXPECTED_LIMIT_A);if(!bad_limit)limit=TEST_EXPECTED_LIMIT_A;}
        else if(index==0x7022){CHECK(get(f->data+4)==0.5f);accel=0.5f;}
        else{
            float value=get(f->data+4);CHECK(value==0||value==0.3f);
            if(value!=0){
                CHECK(motor_mode==2&&e.enable_confirmed&&!e.finishing&&limit==TEST_EXPECTED_LIMIT_A&&accel==0.5f);
                if(reject_motion)return false;
                ++motions;
            }
            speed_ref=value;
        }
    }
    if(type==17){
        CHECK(index==0x7005||index==0x700A||index==0x7018||index==0x7022||index==0x701A||index==0x701B||index==0x7019);
        response.id=0x11000000U|((uint32_t)e.id<<8)|e.host;response.data[0]=f->data[0];response.data[1]=f->data[1];
        if(index==0x7005)response.data[4]=mode;
        else put(response.data+4,index==0x700A?speed_ref:index==0x7018?limit:index==0x7022?accel:
            index==0x7019?position:index==0x701B?(motor_mode==2&&!no_motion?speed_ref:0):0.1f);
    }else response.id=0x02000000U|((uint32_t)motor_mode<<22)|((uint32_t)e.id<<8)|e.host;
    if(wrong_id)response.id^=0x100;
    pending=!(drop_feedback&&type!=17)&&!(drop_iq&&type==17&&index==0x701A)&&!(drop_clear&&e.phase==ME_SPEED_CLEAR_READ);
    return true;
}
static void tick(bool heartbeat){
    ++now;if(heartbeat)MotorEnable_Heartbeat(&e,now);
    if(motor_mode==2&&!no_motion)position+=speed_ref/1000;
    if(pending){pending=false;MotorEnable_OnFrame(&e,&response,now);}
    MotorEnable_Step(&e,now,send_frame,0);
}
static void advance(unsigned ms,bool heartbeat){while(ms--)tick(heartbeat);}
static void init(uint8_t id){
    now=enables=motions=enable_at=stop_at=0;mode=motor_mode=0;
    speed_ref=4;limit=10;accel=20;position=5;
    pending=bad_limit=no_motion=drop_feedback=drop_iq=drop_clear=reject_motion=reset_limit_on_enable=wrong_id=false;
    MotorEnable_InitSpeed(&e,id,0xFD,now);
}
static void ready(void){advance(400,true);CHECK(e.phase==ME_READY&&enables==0&&motions==0);CHECK(MotorEnable_Request(&e,now));}
static void active(void){ready();advance(800,true);CHECK(e.phase==ME_ACTIVE&&enables==1&&motions>0);}
static void inject(unsigned index,float value){
    CanFrame f={.id=0x11000000U|((uint32_t)e.id<<8)|e.host,.timestamp_ms=now,.extended=true,.dlc=8};
    f.data[0]=(uint8_t)index;f.data[1]=(uint8_t)(index>>8);put(f.data+4,value);MotorEnable_OnFrame(&e,&f,now);
}
int main(void){
    for(uint8_t id=1;id<=2;++id){
        init(id);advance(1000,false);CHECK(e.phase==ME_READY&&enables==0&&motions==0);CHECK(!MotorEnable_Request(&e,now));
        MotorEnable_Heartbeat(&e,now);CHECK(MotorEnable_Request(&e,now));advance(4500,true);
        CHECK(e.phase==ME_DONE&&e.enable_confirmed&&e.stop_confirmed&&e.motion_confirmed&&e.target_cleared&&!e.error);
        CHECK(e.velocity_samples>0&&e.position_samples>0&&e.iq_samples>0);
        CHECK(speed_ref==0&&motor_mode==0&&enables==1&&stop_at-enable_at==3000);
        CHECK(!MotorEnable_Request(&e,now));
    }
    init(1);bad_limit=true;ready();advance(1500,true);CHECK(e.error&&enables==0&&motions==0&&e.stop_confirmed);
    init(1);reset_limit_on_enable=true;ready();advance(1500,true);CHECK(e.error&&enables==1&&motions==0&&e.stop_confirmed);
    init(1);no_motion=true;ready();advance(4500,true);CHECK(e.error&&!e.motion_confirmed&&strcmp(e.reason,"NO_MOTION")==0&&e.target_cleared);
    init(1);active();advance(1000,false);CHECK(e.error&&strcmp(e.reason,"HOST_TIMEOUT")==0&&e.stop_confirmed&&speed_ref==0);
    init(2);active();drop_feedback=true;advance(700,true);CHECK(e.error&&strcmp(e.reason,"FEEDBACK_TIMEOUT")==0&&e.phase==ME_STOPPING);
    init(1);active();drop_iq=true;advance(700,true);CHECK(e.error&&strcmp(e.reason,"TELEMETRY_TIMEOUT")==0&&e.stop_confirmed);
    init(1);active();inject(0x701A,0.9f);CHECK(e.error&&e.finishing);advance(200,true);CHECK(e.stop_confirmed&&e.target_cleared);
    init(1);active();inject(0x701B,0.7f);CHECK(e.error&&e.finishing);
    init(1);active();inject(0x7019,NAN);CHECK(e.error&&isfinite(e.position_delta));
    init(1);active();inject(0x7019,e.position_start+1.3f);CHECK(e.error&&e.finishing);
    init(1);active();MotorEnable_Stop(&e,now,"MANUAL_STOP",false);advance(200,true);CHECK(e.stop_confirmed&&e.target_cleared&&speed_ref==0);
    init(1);active();drop_clear=true;MotorEnable_Stop(&e,now,"MANUAL_STOP",false);advance(700,true);
    CHECK(e.phase==ME_DONE&&e.stop_confirmed&&e.error&&!e.target_cleared);
    init(1);reject_motion=true;ready();advance(1500,true);CHECK(e.error&&motions==0&&e.stop_confirmed);
    init(1);wrong_id=true;advance(2500,true);CHECK(enables==0&&motions==0&&e.stop_unconfirmed);
    init(2);active();now=0xFFFFFF00U;e.enable_at=e.last_feedback=e.last_heartbeat=e.last_iq=e.last_velocity=e.last_position=now;
    e.next_zero=e.next_iq=now;pending=false;position=e.position_start;e.position_delta=0;advance(3500,true);
    CHECK(e.phase==ME_DONE&&!e.error&&e.stop_confirmed&&e.target_cleared);
    init(1);active();
    CanFrame failed={.id=0x110101FDU,.timestamp_ms=now,.extended=true,.dlc=8,.data={0x1A,0x70,0,0,0,0,0,0}};
    MotorEnable_OnFrame(&e,&failed,now);CHECK(e.finishing&&e.error&&strcmp(e.reason,"PARAMETER_READ_REJECTED")==0);advance(200,true);CHECK(e.stop_confirmed&&e.target_cleared);
#if defined(TEST_STARTUP_700)
    init(1);active();inject(0x7019,e.position_start+e.position_delta+0.2513f);
    CHECK(e.finishing&&e.error&&strcmp(e.reason,"POSITION_SAMPLE_JUMP")==0);advance(200,true);CHECK(e.stop_confirmed&&e.target_cleared);
    init(1);active();inject(0x701A,0.79f);CHECK(!e.finishing);inject(0x701A,0.81f);CHECK(e.finishing&&e.error);
#endif
    puts("Low-speed gates, motion evidence, limits, telemetry deadman, stop and target cleanup: PASS");return 0;
}
