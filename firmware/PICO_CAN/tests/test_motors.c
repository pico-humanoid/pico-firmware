#include "motor_reader.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"%s:%d: %s\n",__FILE__,__LINE__,#x); exit(1); } } while(0)
static unsigned sends;
static bool accept=true;
static CanFrame sent;
static uint32_t last_send;
static bool send_fake(void *context,const CanFrame *f,uint32_t now) {
    (void)context;
    CHECK(f->extended && !f->remote && f->dlc==8 && (f->id>>24)==0x11);
    CHECK(f->data[2]==0 && f->data[3]==0 && f->data[4]==0 && f->data[5]==0 && f->data[6]==0 && f->data[7]==0);
    if (sends) CHECK((uint32_t)(now-last_send)>=200U);
    last_send=now; sent=*f; ++sends; return accept;
}
static CanFrame reply(const CanFrame *request,uint32_t now,uint32_t bits) {
    CanFrame f={.id=0x11000000U|((request->id&0xFFU)<<8)|((request->id>>8)&0xFFU),
        .timestamp_ms=now,.extended=true,.dlc=8};
    f.data[0]=request->data[0]; f.data[1]=request->data[1];
    for(unsigned i=0;i<4;++i) f.data[4+i]=(uint8_t)(bits>>(8*i));
    return f;
}
int main(void) {
    CanFrame f; MotorReading v; uint8_t node;
    CHECK(Motor_MakeRead(0x7F,0xFD,0,&f));
    CHECK(f.id==0x1100FD7FU && f.data[0]==0x19 && f.data[1]==0x70 && f.data[7]==0);
    CHECK(!Motor_MakeRead(0,0xFD,0,&f) && !Motor_MakeRead(0xFF,0xFD,0,&f));
    CHECK(!Motor_MakeRead(1,1,0,&f) && !Motor_MakeRead(1,0xFE,0,&f));
    CHECK(!Motor_MakeRead(1,0xFD,4,&f));
    f=reply(&f,1001,0x3FC00000U);
    CHECK(Motor_ParseRead(&f,0x7F,0xFD,&v)==PROTOCOL_OK && v.value_milli==1500 && v.query==0);
    CHECK(Motor_ParseRead(&f,1,0xFD,&v)==PROTOCOL_IGNORED);
    CHECK(Motor_ParseRead(&f,0x7F,0xFC,&v)==PROTOCOL_IGNORED);
    CanFrame bad=f; bad.id|=1U<<16;
    CHECK(Motor_ParseRead(&bad,0x7F,0xFD,&v)==PROTOCOL_INVALID);
    bad=f; bad.dlc=7; CHECK(Motor_ParseRead(&bad,0x7F,0xFD,&v)==PROTOCOL_INVALID);
    bad=f; bad.remote=true; CHECK(Motor_ParseRead(&bad,0x7F,0xFD,&v)==PROTOCOL_INVALID);
    bad=f; bad.data[2]=1; CHECK(Motor_ParseRead(&bad,0x7F,0xFD,&v)==PROTOCOL_INVALID);
    bad=f; bad.data[0]=0; CHECK(Motor_ParseRead(&bad,0x7F,0xFD,&v)==PROTOCOL_IGNORED);
    bad=f; bad.data[6]=0xC0; bad.data[7]=0x7F;
    CHECK(Motor_ParseRead(&bad,0x7F,0xFD,&v)==PROTOCOL_INVALID); /* NaN */
    CHECK(Motor_MakeRead(1,0xFD,1,&f));
    f=reply(&f,1001,0xBE000000U);
    CHECK(Motor_ParseRead(&f,1,0xFD,&v)==PROTOCOL_OK && v.value_milli==-125);

    MotorReader r;
    CHECK(!MotorReader_Init(&r,2,1,1,0xFD,0));
    CHECK(!MotorReader_Init(&r,0,1,2,0xFD,0));
    CHECK(MotorReader_Init(&r,2,1,2,0xFD,0));
    MotorReader_Step(&r,999,send_fake,NULL); CHECK(sends==0);
    for(uint32_t now=1000;now<=65000;now+=10) {
        MotorReader_Step(&r,now,send_fake,NULL);
        if(r.pending) {
            f=reply(&sent,now+1,0x42410000U);
            CHECK(MotorReader_OnFrame(&r,&f,&node,&v));
        }
    }
    CHECK(r.nodes[0].valid==0x0F && r.nodes[1].valid==0x0F);
    CHECK(r.nodes[0].replies>150 && r.nodes[1].replies>150);
    CHECK(!r.nodes[0].timeouts && !r.nodes[1].timeouts);
    MotorReader_Age(&r,76001); CHECK(r.nodes[0].valid==0 && r.nodes[1].valid==0);
    /* A missing first motor must not block reading the second motor. */
    sends=0; CHECK(MotorReader_Init(&r,2,1,2,0xFD,0));
    for(uint32_t now=1000;now<=65000;now+=10) {
        MotorReader_Step(&r,now,send_fake,NULL);
        if(r.pending && r.pending_node==1) {
            f=reply(&sent,now+1,0x42410000U);
            CHECK(MotorReader_OnFrame(&r,&f,&node,&v));
        }
    }
    CHECK(r.nodes[0].timeouts>20 && r.nodes[0].valid==0);
    CHECK(r.nodes[1].timeouts==0 && r.nodes[1].valid==0x0F && r.nodes[1].replies>40);
    /* Wrong source, failed read and stale timestamp do not finish a query. */
    sends=0; CHECK(MotorReader_Init(&r,2,1,2,0xFD,0));
    MotorReader_Step(&r,1000,send_fake,NULL);
    f=reply(&sent,1001,0x3FC00000U); f.id=0x110002FD;
    CHECK(!MotorReader_OnFrame(&r,&f,&node,&v) && r.pending && !r.nodes[1].replies);
    f=reply(&sent,999,0x3FC00000U);
    CHECK(!MotorReader_OnFrame(&r,&f,&node,&v) && r.pending);
    f=reply(&sent,1001,0x3FC00000U); f.id|=1U<<16;
    CHECK(!MotorReader_OnFrame(&r,&f,&node,&v) && r.pending && r.nodes[0].invalid==1);
    f=reply(&sent,1001,0x3FC00000U);
    CHECK(MotorReader_OnFrame(&r,&f,&node,&v) && node==0 && !r.pending);
    sends=0; accept=false; CHECK(MotorReader_Init(&r,1,1,2,0xFD,0));
    MotorReader_Step(&r,1000,send_fake,NULL);
    CHECK(!r.pending && r.nodes[0].rejected==1 && !r.nodes[0].submitted);
    /* Startup deadline and age calculation survive HAL tick wraparound. */
    sends=0; accept=true; uint32_t origin=0xFFFFFF00U;
    CHECK(MotorReader_Init(&r,1,1,2,0xFD,origin));
    MotorReader_Step(&r,origin+999U,send_fake,NULL); CHECK(!sends);
    MotorReader_Step(&r,origin+1000U,send_fake,NULL); CHECK(sends==1);
    f=reply(&sent,origin+1001U,0x3FC00000U);
    CHECK(MotorReader_OnFrame(&r,&f,&node,&v));
    MotorReader_Age(&r,origin+11002U); CHECK(!r.nodes[0].valid);
    puts("Motor protocol, isolation, 65-second polling, stale data and wraparound passed");
    return 0;
}
