/* Actual HAL glue, protocol and core under a 115200-baud asynchronous UART. */
#include "../App/motor_tuning_app.c"
#include <assert.h>
#include <math.h>
static uint32_t clock_ms,tx_due;static uint8_t *rx_byte;static uint8_t tx_copy[128];static uint16_t tx_n;
static char captured[2000000];static unsigned captured_n,enable_count;static bool peer_run,keep_host;
static CanFrame frames[32];static unsigned fw,fr;static float regs_values[0x30];static CanTransportLog logger;
static UART_HandleTypeDef test_uart;static FDCAN_GlobalTypeDef test_regs;static FDCAN_HandleTypeDef test_can={.Instance=&test_regs};
uint32_t HAL_GetTick(void){return clock_ms;}
void HAL_NVIC_SetPriority(int a,int b,int c){(void)a;(void)b;(void)c;}
void HAL_NVIC_EnableIRQ(int a){(void)a;}
HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *h,uint8_t *p,uint16_t n){assert(h==&test_uart&&n==1);rx_byte=p;return HAL_OK;}
HAL_StatusTypeDef HAL_UART_Transmit_IT(UART_HandleTypeDef *h,const uint8_t *p,uint16_t n){assert(h==&test_uart&&n<=128&&!tx_n);memcpy(tx_copy,p,n);tx_n=n;tx_due=clock_ms+((uint32_t)n*10000+115199)/115200;return HAL_OK;}
bool CanTransport_Init(FDCAN_HandleTypeDef *h,uint32_t rate,CanTransportFilter filter,uint8_t id,CanTransportLog log){assert(h==&test_can&&rate==1000000&&filter==CAN_FILTER_MOTOR_DIAG&&id==253);logger=log;return true;}
void CanTransport_Service(uint32_t at){(void)at;}
void CanTransport_CancelPending(uint32_t at){(void)at;}
CanTransportStats CanTransport_GetStats(void){return (CanTransportStats){0};}
bool CanTransport_Receive(CanFrame *f){if(fr==fw)return false;*f=frames[fr++%32];return true;}
bool CanTransport_Submit(const CanFrame *f,uint32_t at){
 assert(CanFrame_IsValid(f));logger("TX_SUBMIT",f);unsigned type=f->id>>24,index=f->data[0]|((unsigned)f->data[1]<<8);
 CanFrame r={.dlc=8,.extended=true,.timestamp_ms=at};
 if(type==0){r.id=0x1FE;memcpy(r.data,"UID12345",8);}
 else if(type==3||type==4||type==18){
  if(type==3){peer_run=true;++enable_count;}if(type==4)peer_run=false;
  if(type==18){assert(index==0x7005||index==0x700A||index==0x7016||index==0x7017||index==0x7018||index==0x7022);regs_values[index-0x7000]=index==0x7005?f->data[4]:RsSpc_Float(f->data+4);}
  r.id=0x020001FD|(peer_run?2UL<<22:0);
 }else{assert(type==17);r.id=0x110001FD;r.data[0]=index&255;r.data[1]=index>>8;if(index==0x7005)r.data[4]=(uint8_t)regs_values[5];else memcpy(r.data+4,&regs_values[index-0x7000],4);}
 assert(fw-fr<32);frames[fw++%32]=r;return true;
}
static void input(const char *text){while(*text){assert(rx_byte);*rx_byte=(uint8_t)*text++;HAL_UART_RxCpltCallback(&test_uart);}}
static void advance(unsigned n){while(n--){++clock_ms;if(tx_n&&clock_ms>=tx_due){assert(captured_n+tx_n<sizeof(captured));memcpy(captured+captured_n,tx_copy,tx_n);captured_n+=tx_n;captured[captured_n]=0;tx_n=0;HAL_UART_TxCpltCallback(&test_uart);}if(keep_host&&clock_ms%100==0)input("KEEP AABBCCDD\n");MotorEnableApp_Step();}}
static void boot(void){clock_ms=tx_due=tx_n=captured_n=enable_count=fw=fr=0;peer_run=keep_host=false;memset(regs_values,0,sizeof(regs_values));regs_values[0x19]=1;MotorEnableApp_Init(&test_can,&test_uart);input("SESSION AABBCCDD 1\n");keep_host=true;advance(1500);assert(motor.stage==TU_READY&&enable_count==0);}
int main(void){
 boot();input("ARM BADTOKEN POS 1 0 200 60000\n");advance(100);assert(enable_count==0);
 input("ARM AABBCCDD POS 999999999999999999999999999999999 0 200 60000\n");advance(100);assert(enable_count==0);
 input("ARM AABBCCDD SPD 1 301 0 3000\n");advance(100);assert(enable_count==0);
 input("LIMIT AABBCCDD 1 5000\n");input("ARM AABBCCDD POS 1 0 200 60000\n");advance(750);assert(motor.stage==TU_ACTIVE&&enable_count==1);assert(regs_values[0x18]==5.0f);
 input("SET AABBCCDD 2 5000 100\n");advance(200);assert(motor.applied_seq==2);
 input("ARM AABBCCDD SPD 3 100 0 3000\n");advance(100);assert(motor.mode==TUNING_POSITION&&enable_count==1);
 input("STOP\n");advance(1000);assert(motor.stage==TU_DONE&&motor.stopped&&motor.target_cleared);assert(strstr(captured,"TUNE_RESULT,result=STOPPED"));assert(!uart_errors&&!uart_failed&&tx_high_water<8192);
 boot();input("ARM AABBCCDD SPD 1 0 0 3000\n");advance(750);input("SETSPEED AABBCCDD 2 -100\n");advance(200);assert(motor.applied_seq==2&&motor.speed_target<-.099f);advance(3500);assert(motor.stage==TU_DONE&&motor.stopped&&motor.target_cleared);
 boot();input("ARM AABBCCDD POS 1 0 200 60000\n");clock_ms+=600;MotorEnableApp_Step();advance(1000);assert(enable_count==0&&motor.stage==TU_DONE);
 boot();input("ARM AABBCCDD POS 1 0 200 60000\n");advance(62000);assert(motor.stage==TU_DONE&&motor.stopped&&motor.target_cleared&&!motor.error);assert(!uart_errors&&!uart_failed&&tx_high_water<8192);
 boot();input("ARM AABBCCDD SPD 1 0 0 3000\n");advance(750);test_uart.ErrorCode=8;HAL_UART_ErrorCallback(&test_uart);advance(1000);assert(motor.error&&motor.stage==TU_DONE&&motor.stopped&&!strcmp(motor.reason,"UART_LINK_ERROR"));
 puts("full tuning app: session/overflow/stale-byte/mode interlocks, nonblocking UART and both STOP cleanups OK");return 0;
}
