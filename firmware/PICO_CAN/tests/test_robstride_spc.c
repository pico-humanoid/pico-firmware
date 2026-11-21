/* Golden private-protocol frames, upstream API capture and motor isolation. */
#include "protocol/robstride_spc.h"
#include "vendor/robstride_spc/ported/robstride_spc_port.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
static void expected(CanFrame f,uint32_t id,const uint8_t data[8]){
 CHECK(CanFrame_IsValid(&f)&&f.extended&&!f.remote&&f.dlc==8&&f.id==id);CHECK(memcmp(f.data,data,8)==0);
}
int main(void){
 const uint8_t zeros[]={0,0,0,0,0,0,0,0};
 const uint8_t read_pos[]={0x19,0x70,0,0,0,0,0,0};
 const uint8_t mode2[]={5,0x70,0,0,2,0,0,0};
 const uint8_t mode5[]={5,0x70,0,0,5,0,0,0};
 const uint8_t limit700[]={0x18,0x70,0,0,0x33,0x33,0x33,0x3F};
 const uint8_t limit500[]={0x18,0x70,0,0,0,0,0,0x3F};
 const uint8_t speed[]={0x0A,0x70,0,0,0x9A,0x99,0x99,0x3E};
 const uint8_t position[]={0x16,0x70,0,0,0,0,0xC0,0xBF};
 const uint8_t version[]={0,0xC4,0,0,0,0,0,0};
 expected(RsSpc_Frame(1,253,3,0,0),0x0300FD01,zeros);
 expected(RsSpc_Frame(2,253,4,0,0),0x0400FD02,zeros);
 expected(RsSpc_Frame(1,253,18,0x7005,2),0x1200FD01,mode2);
 expected(RsSpc_Frame(2,253,18,0x7005,5),0x1200FD02,mode5);
 expected(RsSpc_Frame(1,253,18,0x7018,0.7f),0x1200FD01,limit700);
 expected(RsSpc_Frame(2,253,18,0x7018,0.5f),0x1200FD02,limit500);
 expected(RsSpc_Frame(1,253,18,0x700A,0.3f),0x1200FD01,speed);
 expected(RsSpc_Frame(1,253,17,0x7019,0),0x1100FD01,read_pos); /* No stale float bytes. */
 expected(RsSpc_Frame(2,253,18,0x7016,-1.5f),0x1200FD02,position);
 expected(RsSpc_Frame(127,198,17,0x7019,0),0x1100C67F,read_pos);
 expected(RsSpc_Frame(1,253,0,0,0),0x0000FD01,zeros);
 expected(RsSpc_VersionFrame(1,253),0x0400FD01,version);
 for(unsigned i=0;i<1000;++i){
  expected(RsSpc_Frame(1,253,18,0x700A,0.3f),0x1200FD01,speed);
  expected(RsSpc_Frame(2,198,4,0,0),0x0400C602,zeros);
  expected(RsSpc_Frame(2,198,17,0x7019,0),0x1100C602,read_pos);
 }
 unsigned forbidden[]={1,5,6,7,21,22,23,24,25,255};
 for(unsigned i=0;i<sizeof(forbidden)/sizeof(forbidden[0]);++i){CanFrame f=RsSpc_Frame(1,253,forbidden[i],0,0);CHECK(!CanFrame_IsValid(&f));}
 uint16_t protected[]={0x2005,0x7029,0x702B,0x702D};
 for(unsigned i=0;i<sizeof(protected)/sizeof(protected[0]);++i){CanFrame f=RsSpc_Frame(1,253,18,protected[i],1);CHECK(!CanFrame_IsValid(&f));}
 CanFrame invalid=RsSpc_Frame(1,253,18,0x7016,NAN);CHECK(!CanFrame_IsValid(&invalid));
 invalid=RsSpc_Frame(1,253,18,0x7005,4);CHECK(!CanFrame_IsValid(&invalid));
 invalid=RsSpc_Frame(1,253,18,0x7005,2.5f);CHECK(!CanFrame_IsValid(&invalid));
 invalid=RsSpc_Frame(128,253,3,0,0);CHECK(!CanFrame_IsValid(&invalid));
 invalid=RsSpc_Frame(1,254,3,0,0);CHECK(!CanFrame_IsValid(&invalid));
 invalid=RsSpc_Frame(1,1,3,0,0);CHECK(!CanFrame_IsValid(&invalid));
 const uint8_t negative[]={0,0,0xC0,0xBF};CHECK(RsSpc_Float(negative)==-1.5f);
 const uint8_t nan_bytes[]={0,0,0xC0,0x7F};CHECK(isnan(RsSpc_Float(nan_bytes)));
 uint8_t mode,fault;
 CanFrame feedback={.id=0x02BF7FFD,.extended=true,.dlc=8};
 CHECK(RsSpc_FeedbackStatus(&feedback,&mode,&fault)&&mode==2&&fault==63);
 for(unsigned bit=0;bit<6;++bit){feedback.id=0x020001FD|(1U<<(16+bit));CHECK(RsSpc_FeedbackStatus(&feedback,&mode,&fault)&&mode==0&&fault==(1U<<bit));}
 feedback.id=0x02C001FD;CHECK(!RsSpc_FeedbackStatus(&feedback,&mode,&fault)); /* Reserved mode must never confirm STOP. */
 feedback.id=0x110001FD;CHECK(!RsSpc_FeedbackStatus(&feedback,&mode,&fault));
 /* Official compound functions create multiple commands, so the bounded
    capture contract rejects using them as one application send operation. */
 CHECK(RobStrideSpc_Begin(1,253,false));RobStride_Motor_Speed_control(0.7f,0.5f,0.3f);CHECK(!RobStrideSpc_End(&invalid));
 expected(RsSpc_Frame(2,253,4,0,0),0x0400FD02,zeros);
 CHECK(RobStrideSpc_Begin(1,253,false));RobStride_Motor_MIT_enable();CHECK(!RobStrideSpc_End(&invalid));
 expected(RsSpc_Frame(1,253,3,0,0),0x0300FD01,zeros);
 puts("Pinned RobStrideSPC: golden frames, dynamic IDs, stale-data isolation, feedback faults, prohibited operations, bounded capture: PASS");return 0;
}
