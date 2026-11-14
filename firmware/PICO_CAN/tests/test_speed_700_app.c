/* Full 700mA application: real UART blocking time, commands and CAN peer. */
#include "motor_enable_app.h"
#include "transport/can_transport.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"tick %lu line %d: %s\n",(unsigned long)tick,__LINE__,#x);exit(1);}}while(0)
static UART_HandleTypeDef uart;static uint8_t *armed;
static uint32_t tick,next_keep,completed,enables,enable_at;
static unsigned scenario,mode,motor_mode;
static bool heartbeat;
static float reference,limit,acceleration,position=1.0f;
static CanFrame frames[32];static unsigned wr,rd;
static char output[150000];static size_t used;
static CanTransportLog logger;
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *h);
static void command(const char *s){while(*s){CHECK(armed);*armed=(uint8_t)*s++;HAL_UART_RxCpltCallback(&uart);}}
static void clock_tick(void){++tick;if(motor_mode==2&&scenario!=1)position+=reference/1000.0f;if(heartbeat&&tick>=next_keep){command("KEEP AABBCCDD\n");next_keep=tick+100;}}
uint32_t HAL_GetTick(void){return tick;}
void HAL_NVIC_SetPriority(int a,int b,int c){(void)a;(void)b;(void)c;}
void HAL_NVIC_EnableIRQ(int a){(void)a;}
HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *h,uint8_t *p,uint16_t n){CHECK(h==&uart&&n==1);armed=p;return HAL_OK;}
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *h,const uint8_t *p,uint16_t n,uint32_t timeout){
 (void)timeout;CHECK(h==&uart&&used+n<sizeof(output));memcpy(output+used,p,n);used+=n;output[used]=0;
 for(unsigned i=0;i<((unsigned)n*10000U+115199U)/115200U;++i)clock_tick();
 return HAL_OK;
}
HAL_StatusTypeDef HAL_FDCAN_AbortTxRequest(FDCAN_HandleTypeDef *h,uint32_t mask){(void)h;(void)mask;return HAL_OK;}
HAL_StatusTypeDef HAL_FDCAN_GetErrorCounters(const FDCAN_HandleTypeDef *h,FDCAN_ErrorCountersTypeDef *e){(void)h;memset(e,0,sizeof(*e));return HAL_OK;}
bool CanTransport_Init(FDCAN_HandleTypeDef *h,uint32_t b,CanTransportFilter f,uint8_t id,CanTransportLog log){(void)h;CHECK(b==1000000&&f==CAN_FILTER_MOTOR&&id==253);logger=log;return true;}
static float scalar(const uint8_t *p){float f;memcpy(&f,p,4);return f;}
bool CanTransport_Submit(const CanFrame *f,uint32_t now){
 unsigned type=f->id>>24,index=f->data[0]|((unsigned)f->data[1]<<8);
 CHECK(f->extended&&!f->remote&&f->dlc==8&&(f->id&255)==1&&((f->id>>8)&255)==253);
 CHECK(type==3||type==4||type==17||type==18);
 CanFrame logged=*f;logged.timestamp_ms=now;logger("TX_SUBMIT",&logged);++completed;
 if(type==3){CHECK(mode==2&&reference==0&&limit==0.7f&&acceleration==0.5f);++enables;enable_at=tick;motor_mode=2;}
 else if(type==4)motor_mode=0;
 else if(type==18){
  CHECK(index==0x7005||index==0x700A||index==0x7018||index==0x7022);
  if(index==0x7005){CHECK(motor_mode==0&&f->data[4]==2);mode=2;}
  else if(index==0x7018){CHECK(scalar(f->data+4)==0.7f);limit=scenario==5?0.5f:0.7f;}
  else if(index==0x7022){CHECK(scalar(f->data+4)==0.5f);acceleration=0.5f;}
  else{float v=scalar(f->data+4);CHECK(v==0||v==0.3f);if(v)CHECK(motor_mode==2&&limit==0.7f);reference=v;}
 }
 CanFrame r={.extended=true,.dlc=8,.timestamp_ms=tick,.id=0x020001FDU|((uint32_t)motor_mode<<22)};
 if(type==17){
  r.id=0x110001FD;r.data[0]=f->data[0];r.data[1]=f->data[1];float value=0;
  if(index==0x7005)r.data[4]=(uint8_t)mode;
  else{
   if(index==0x700A)value=reference;
   else if(index==0x7018)value=limit;
   else if(index==0x7022)value=acceleration;
   else if(index==0x7019)value=position+((scenario==3&&motor_mode==2&&tick-enable_at>600)?0.2513f:0);
   else if(index==0x701B)value=scenario==1?0:reference;
   else if(index==0x701A)value=scenario==4?0.81f:scenario==1?0.69f:0.4f;
   else CHECK(false);
   memcpy(r.data+4,&value,4);
  }
 }
 CHECK(wr-rd<32);frames[wr++%32]=r;return true;
}
void CanTransport_Service(uint32_t now){(void)now;}
bool CanTransport_Receive(CanFrame *f){if(rd==wr)return false;*f=frames[rd++%32];return true;}
CanTransportStats CanTransport_GetStats(void){return (CanTransportStats){.tx_completed=completed};}
static void advance(unsigned ms){uint32_t end=tick+ms;while((int32_t)(tick-end)<0){clock_tick();MotorEnableApp_Step();}}
int main(int argc,char **argv){
 CHECK(argc==2);scenario=(unsigned)atoi(argv[1]);FDCAN_GlobalTypeDef regs={0};FDCAN_HandleTypeDef can={.Instance=&regs};
 MotorEnableApp_Init(&can,&uart);command("SESSION AABBCCDD 1\n");heartbeat=true;next_keep=tick+50;advance(1500);
 CHECK(enables==0&&strstr(output,"state=READY"));CHECK(strstr(output,"current_limit_A=0.7"));command("RUN AABBCCDD\n");advance(1300);
 if(scenario==2)heartbeat=false;
 advance(4000);CHECK(motor_mode==0&&reference==0);CHECK(strstr(output,"stop_confirmed=1"));
 const char *expected[]={"SPEED_RESULT,result=PASS","reason=NO_MOTION","reason=HOST_TIMEOUT","reason=POSITION_SAMPLE_JUMP","reason=MEASURED_IQ_OVER_0.8A","reason=SPEED_PARAMETER_READBACK_MISMATCH"};
 CHECK(scenario<6&&strstr(output,expected[scenario]));if(scenario)CHECK(!strstr(output,"SPEED_RESULT,result=PASS"));
 if(scenario==5)CHECK(enables==0);else CHECK(enables==1);
 puts("700mA full application, UART at 115200 baud and stop cleanup: PASS");return 0;
}
