/* Full application, fake CAN peer and UART at 115200 baud. No hardware I/O. */
#include "motor_enable_app.h"
#include "transport/can_transport.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line %d tick %lu: %s\n",__LINE__,(unsigned long)tick,#x);exit(1);}}while(0)
static UART_HandleTypeDef uart;
static uint8_t *armed;
static uint32_t tick,next_keep,completed;
static bool heartbeat,no_uid,no_stop,reject_send,invalid_position,mismatch,change_uid,missing_optional;
static unsigned control_mode,writes,reads,stops,rejected_index;
static float position,target;
static CanFrame replies[32];static unsigned wr,rd;
static char output[300000];static size_t used;
static CanTransportLog logger;
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *h);
static void command(const char *text){while(*text){CHECK(armed);*armed=(uint8_t)*text++;HAL_UART_RxCpltCallback(&uart);}}
static void clock_tick(void){++tick;if(heartbeat&&tick>=next_keep){command("KEEP AABBCCDD\n");next_keep=tick+100;}}
uint32_t HAL_GetTick(void){return tick;}
void HAL_NVIC_SetPriority(int a,int b,int c){(void)a;(void)b;(void)c;}
void HAL_NVIC_EnableIRQ(int a){(void)a;}
HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *h,uint8_t *p,uint16_t n){CHECK(h==&uart&&n==1);armed=p;return HAL_OK;}
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *h,const uint8_t *p,uint16_t n,uint32_t timeout){
 (void)timeout;CHECK(h==&uart&&used+n<sizeof(output));memcpy(output+used,p,n);used+=n;output[used]=0;
 for(unsigned ms=0;ms<((unsigned)n*10000U+115199U)/115200U;++ms)clock_tick();
 return HAL_OK;
}
HAL_StatusTypeDef HAL_FDCAN_GetErrorCounters(const FDCAN_HandleTypeDef *h,FDCAN_ErrorCountersTypeDef *e){(void)h;memset(e,0,sizeof(*e));return HAL_OK;}
bool CanTransport_Init(FDCAN_HandleTypeDef *h,uint32_t bitrate,CanTransportFilter filter,uint8_t id,CanTransportLog log){
 (void)h;CHECK(bitrate==1000000&&filter==CAN_FILTER_MOTOR_DIAG&&id==253);logger=log;return true;
}
void CanTransport_Service(uint32_t now){(void)now;}
void CanTransport_CancelPending(uint32_t now){(void)now;}
CanTransportStats CanTransport_GetStats(void){return (CanTransportStats){.tx_completed=completed};}
bool CanTransport_Receive(CanFrame *f){if(rd==wr)return false;*f=replies[rd++%32];return true;}
static void put(uint8_t *p,float value){memcpy(p,&value,4);}
bool CanTransport_Submit(const CanFrame *f,uint32_t now){
 unsigned type=f->id>>24,index=f->data[0]|((unsigned)f->data[1]<<8);
 CHECK(f->extended&&!f->remote&&f->dlc==8&&(f->id&255)==1&&((f->id>>8)&255)==253);
 CHECK(type==0||type==4||type==17||type==18); /* Never enable or change ID/zero/baud/save. */
 if(reject_send)return false;
 CanFrame logged=*f;logged.timestamp_ms=now;logger("TX_SUBMIT",&logged);++completed;
 CanFrame r={.extended=true,.dlc=8,.timestamp_ms=tick,.id=0x020001FDU};
 if(type==0){
  if(no_uid)return true;
  r.id=0x000001FE;for(unsigned i=0;i<8;++i)r.data[i]=(uint8_t)(i+1);
  if(change_uid)++r.data[0];
 }else if(type==4){
  if(f->data[1]==0xC4){const uint8_t v[]={0,0xC4,0x56,0,10,0,4,0};memcpy(r.data,v,8);}
  else{++stops;if(no_stop)return true;}
 }else if(type==18){
  CHECK(index==0x7016&&stops>=2);float value;memcpy(&value,f->data+4,4);
  CHECK(value==position);++writes;target=value+(mismatch&&writes==2?0.2513427734f:0.0f);
 }else{
  ++reads;r.id=0x110001FD;r.data[0]=f->data[0];r.data[1]=f->data[1];
  if(index==0x2005&&missing_optional)return true;
  if(index==0x2005||index==rejected_index)r.id|=0x00010000U;
  if(index==0x7005)r.data[4]=(uint8_t)control_mode;
  else if(index==0x7029)r.data[4]=0;
  else put(r.data+4,index==0x7016?target:index==0x7019?(invalid_position?NAN:position):index==0x7017?0.2f:index==0x7018?0.5f:0.0f);
 }
 CHECK(wr-rd<32);replies[wr++%32]=r;return true;
}
static FDCAN_GlobalTypeDef regs;static FDCAN_HandleTypeDef can={.Instance=&regs};
static void init(void){
 tick=next_keep=completed=wr=rd=writes=reads=stops=0;used=0;output[0]=0;armed=NULL;memset(&uart,0,sizeof(uart));
 heartbeat=no_uid=no_stop=reject_send=invalid_position=mismatch=change_uid=missing_optional=false;rejected_index=0;control_mode=5;position=-1.694788f;target=position;
 MotorEnableApp_Init(&can,&uart);command("SESSION AABBCCDD 1\n");heartbeat=true;next_keep=tick+100;
}
static void advance(unsigned ms){uint32_t end=tick+ms;while((int32_t)(tick-end)<0){clock_tick();MotorEnableApp_Step();}}
static void baseline(void){advance(5000);CHECK(strstr(output,"echo_allowed=1"));CHECK(writes==0&&reads>9);}
int main(void){
 init();baseline();advance(12000);CHECK(writes==0);CHECK(strstr(output,"DIAG_VERSION,value=0.10.0.4"));CHECK(strstr(output,"index=0x2005,status=UNAVAILABLE"));
 command("RUN AABBCCDD\n");advance(100);CHECK(writes==0);command("VERIFY BADTOKEN\n");advance(100);CHECK(writes==0);
 command("VERIFY AABBCCDD\n");advance(6000);CHECK(writes==3);CHECK(strstr(output,"result=CONSISTENT,rounds=3,samples=9"));CHECK(strstr(output,"stop_confirmed=1,target_cleared=1,no_enable=1"));
 init();mismatch=true;baseline();command("VERIFY AABBCCDD\n");advance(6000);CHECK(writes==3);CHECK(strstr(output,"result=MISMATCH,rounds=3,samples=9"));CHECK(strstr(output,"status=MISMATCH"));
 init();missing_optional=true;baseline();CHECK(strstr(output,"index=0x2005,status=UNAVAILABLE"));
 init();baseline();rejected_index=0x7019;command("VERIFY AABBCCDD\n");advance(2000);CHECK(writes==0);CHECK(strstr(output,"reason=PARAMETER_READ_REJECTED,stop_confirmed=1"));
 init();control_mode=0;advance(5000);command("VERIFY AABBCCDD\n");advance(1000);CHECK(writes==0);CHECK(strstr(output,"STOP_UID_MODE_OR_SESSION_NOT_READY"));
 init();no_uid=true;advance(6000);command("VERIFY AABBCCDD\n");advance(1000);CHECK(reads>9&&writes==0);CHECK(strstr(output,"DIAG_UID,status=UNAVAILABLE"));
 init();baseline();change_uid=true;advance(7000);CHECK(writes==0);CHECK(strstr(output,"reason=UID_CHANGED,stop_confirmed=1"));
 init();baseline();command("VERIFY AABBCCDD\n");heartbeat=false;advance(3000);CHECK(strstr(output,"reason=HOST_TIMEOUT,stop_confirmed=1"));CHECK(writes<=1);
 init();baseline();invalid_position=true;command("VERIFY AABBCCDD\n");advance(2000);CHECK(writes==0);CHECK(strstr(output,"reason=INVALID_PARAMETER_VALUE,stop_confirmed=1"));
 init();no_stop=true;advance(4000);CHECK(writes==0&&stops==3);CHECK(strstr(output,"reason=STOP_UNCONFIRMED,stop_confirmed=0"));
 init();reject_send=true;advance(2000);CHECK(strstr(output,"reason=STOP_UNCONFIRMED,stop_confirmed=0"));CHECK(writes==0);
 init();baseline();command("STOP\n");advance(1000);CHECK(strstr(output,"result=STOPPED,reason=USER_STOP,stop_confirmed=1"));CHECK(writes==0);
 init();baseline();command("VERIFY AABBCCDD\n");for(unsigned i=0;i<600;++i)clock_tick();advance(2000);CHECK(writes==0);CHECK(strstr(output,"STALE_UART_COMMAND"));
 puts("Stopped position diagnostic: manual writes only, three-round echo, 14.4-degree mismatch, UID/session/stop/heartbeat interlocks: PASS");return 0;
}
