#include "motor_enable_app.h"
#include "transport/can_transport.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line %d tick %lu: %s\n",__LINE__,(unsigned long)tick,#x);exit(1);}}while(0)
static UART_HandleTypeDef uart;
static uint8_t *armed;
static uint32_t tick,next_keep,completed,enable_at[2],stop_at[2],enables[2],motions[2];
static uint8_t mode[2],motor_mode[2];
static float speed[2],limit[2],accel[2],position[2];
static CanFrame frames[128];static unsigned wr,rd;
static unsigned absent,missing_feedback,overcurrent,bad_limit,still_motor;
static bool stopping,auto_keep,fault_on_stop;
static CanTransportLog logger;
static char output[300000];static size_t used;
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *h);
void HAL_UART_ErrorCallback(UART_HandleTypeDef *h);
static void command(const char *s){while(*s){CHECK(armed);*armed=(uint8_t)*s++;HAL_UART_RxCpltCallback(&uart);}}
static void clock_tick(void){
    ++tick;
    for(unsigned i=0;i<2;++i)if(motor_mode[i]==2&&still_motor!=i+1)position[i]+=speed[i]/1000;
    if(auto_keep&&tick>=next_keep){command("KEEP AABBCCDD\n");next_keep=tick+100;}
}
uint32_t HAL_GetTick(void){return tick;}
void HAL_NVIC_SetPriority(int a,int b,int c){(void)a;(void)b;(void)c;}
void HAL_NVIC_EnableIRQ(int a){(void)a;}
HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *h,uint8_t *p,uint16_t n){CHECK(h==&uart&&n==1);armed=p;return HAL_OK;}
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *h,const uint8_t *p,uint16_t n,uint32_t timeout){
    (void)timeout;CHECK(h==&uart&&used+n<sizeof(output));memcpy(output+used,p,n);used+=n;output[used]=0;
    /* Include real 115200-baud blocking output time and incoming heartbeats. */
    for(unsigned ms=0;ms<((unsigned)n*10000U+115199U)/115200U;++ms)clock_tick();
    return HAL_OK;
}
HAL_StatusTypeDef HAL_FDCAN_AbortTxRequest(FDCAN_HandleTypeDef *h,uint32_t m){(void)h;(void)m;return HAL_OK;}
HAL_StatusTypeDef HAL_FDCAN_GetErrorCounters(const FDCAN_HandleTypeDef *h,FDCAN_ErrorCountersTypeDef *e){(void)h;memset(e,0,sizeof(*e));return HAL_OK;}
bool CanTransport_Init(FDCAN_HandleTypeDef *h,uint32_t b,CanTransportFilter f,uint8_t id,CanTransportLog log){
    (void)h;CHECK(b==1000000&&f==CAN_FILTER_MOTOR&&id==253);logger=log;return true;
}
static void put(uint8_t *p,float f){uint32_t u;memcpy(&u,&f,4);for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(u>>(8*i));}
static float get(const uint8_t *p){uint32_t u=0;for(unsigned i=0;i<4;++i)u|=(uint32_t)p[i]<<(8*i);float f;memcpy(&f,&u,4);return f;}
bool CanTransport_Submit(const CanFrame *f,uint32_t now){
    unsigned id=f->id&255,type=f->id>>24,index=f->data[0]|((unsigned)f->data[1]<<8);
    CHECK(id==1||id==2);unsigned i=id-1;CHECK(((f->id>>8)&255)==253&&f->extended&&f->dlc==8&&!f->remote);
    CHECK(type==3||type==4||type==17||type==18);
    CanFrame logged=*f;logged.timestamp_ms=now;logger("TX_SUBMIT",&logged);++completed;
    if(type==3){
        CHECK(speed[i]==0&&mode[i]==2&&limit[i]==0.5f&&accel[i]==0.5f);++enables[i];enable_at[i]=tick;motor_mode[i]=2;
    }else if(type==4){motor_mode[i]=0;if(enables[0]||enables[1]){stopping=true;stop_at[i]=tick;}}
    else if(type==18){
        CHECK(index==0x7005||index==0x700A||index==0x7018||index==0x7022);
        if(index==0x7005){CHECK(f->data[4]==2);mode[i]=2;}
        else if(index==0x7018){if(bad_limit!=id)limit[i]=get(f->data+4);}
        else if(index==0x7022)accel[i]=get(f->data+4);
        else{
            float value=get(f->data+4);CHECK(value==0||value==0.3f);
            if(value!=0){CHECK(!stopping&&motor_mode[0]==2&&motor_mode[1]==2&&limit[0]==0.5f&&limit[1]==0.5f);++motions[i];}
            speed[i]=value;
        }
    }
    if(absent==id||(missing_feedback==id&&type!=17))return true;
    CanFrame r={.extended=true,.dlc=8,.timestamp_ms=tick};
    if(type==17){
        CHECK(index==0x7005||index==0x700A||index==0x7018||index==0x7022||index==0x701A||index==0x701B||index==0x7019);
        r.id=0x11000000U|(id<<8)|253;r.data[0]=f->data[0];r.data[1]=f->data[1];
        if(index==0x7005)r.data[4]=mode[i];
        else put(r.data+4,index==0x700A?speed[i]:index==0x7018?limit[i]:index==0x7022?accel[i]:
            index==0x7019?position[i]:index==0x701B?(motor_mode[i]==2&&still_motor!=id?speed[i]:0):overcurrent==id?0.9f:0.1f);
    }else r.id=0x02000000U|((uint32_t)motor_mode[i]<<22)|(id<<8)|253;
    if(fault_on_stop&&stopping&&type==4)r.id|=0x10000U;
    CHECK(wr-rd<128);frames[wr++%128]=r;return true;
}
void CanTransport_Service(uint32_t now){(void)now;}
bool CanTransport_Receive(CanFrame *f){if(rd==wr)return false;*f=frames[rd++%128];return true;}
CanTransportStats CanTransport_GetStats(void){return (CanTransportStats){.tx_completed=completed};}
static FDCAN_GlobalTypeDef regs;
static FDCAN_HandleTypeDef can={.Instance=&regs};
static void init(void){
    tick=next_keep=completed=wr=rd=used=absent=missing_feedback=overcurrent=bad_limit=still_motor=0;
    armed=NULL;stopping=auto_keep=fault_on_stop=false;output[0]=0;memset(&uart,0,sizeof(uart));
    for(unsigned i=0;i<2;++i){enable_at[i]=stop_at[i]=enables[i]=motions[i]=0;mode[i]=motor_mode[i]=0;speed[i]=5;limit[i]=10;accel[i]=20;position[i]=5;}
    MotorEnableApp_Init(&can,&uart);command("SESSION AABBCCDD 0\n");auto_keep=true;next_keep=tick+50;
}
static void advance(unsigned ms){uint32_t end=tick+ms;while((int32_t)(tick-end)<0){clock_tick();MotorEnableApp_Step();}}
static void run(void){advance(1000);CHECK(enables[0]==0&&enables[1]==0);command("RUN AABBCCDD\n");}
static void both_stopped(void){CHECK(motor_mode[0]==0&&motor_mode[1]==0&&speed[0]==0&&speed[1]==0);}
int main(void){
#if defined(PICO_FAULT_TARGET)
    init();run();advance(5500);both_stopped();CHECK(motions[0]>0&&motions[1]>0);
    CHECK(strstr(output,"DUAL_FAULT_RESULT,result=PASS"));CHECK(strstr(output,"FAULT_INJECT"));CHECK(strstr(output,"FAULT_DETECTED"));
    init();fault_on_stop=true;run();advance(5500);both_stopped();CHECK(!strstr(output,"result=PASS"));
    init();overcurrent=PICO_FAULT_TARGET;run();advance(5500);both_stopped();CHECK(!strstr(output,"result=PASS"));
    init();absent=2;run();advance(2000);CHECK(enables[0]==0&&enables[1]==0);CHECK(!strstr(output,"result=PASS"));
    init();run();advance(700);auto_keep=false;advance(2000);CHECK(!strstr(output,"result=PASS"));
    puts("Injected feedback timeout, both STOP and zero-target confirmations; real error/missing motor never PASS: PASS");return 0;
#else

    init();run();advance(5500);both_stopped();CHECK(motions[0]>0&&motions[1]>0);
    CHECK(strstr(output,"DUAL_SPEED_RESULT,result=PASS"));CHECK(stop_at[0]-enable_at[0]<3300&&stop_at[1]-enable_at[1]<3300);
    init();bad_limit=2;run();advance(3500);both_stopped();CHECK(enables[0]==0||motions[0]==0);CHECK(motions[1]==0);CHECK(strstr(output,"result=FAIL"));
    init();absent=2;run();advance(1500);CHECK(enables[0]==0&&enables[1]==0);CHECK(!strstr(output,"result=PASS"));
    init();run();advance(1800);CHECK(motions[0]>0&&motions[1]>0);command("STOP\n");advance(1200);both_stopped();CHECK(strstr(output,"result=STOPPED"));
    init();run();advance(1800);overcurrent=1;advance(1500);both_stopped();CHECK(strstr(output,"result=FAIL"));
    init();run();advance(1800);auto_keep=false;advance(1600);both_stopped();CHECK(strstr(output,"HOST_TIMEOUT"));CHECK(strstr(output,"result=FAIL"));
    init();still_motor=2;run();advance(5500);both_stopped();CHECK(strstr(output,"result=FAIL"));CHECK(!strstr(output,"result=PASS"));
    init();run();advance(1800);uart.ErrorCode=8;HAL_UART_ErrorCallback(&uart);advance(1200);both_stopped();CHECK(strstr(output,"UART_LINK_ERROR"));
    init();run();advance(1800);missing_feedback=1;advance(1300);CHECK(motor_mode[0]==0&&motor_mode[1]==0);CHECK(!strstr(output,"result=PASS"));
    puts("Dual speed at simulated 115200 baud: barrier, both move, peer stop, absent motor, bad limits, UART/heartbeat loss, and no false PASS: PASS");return 0;
#endif
}
