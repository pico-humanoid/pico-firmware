/* Actual HAL glue, protocol and core under a 115200-baud asynchronous UART. */
#include "../App/motor_tuning_app.c"
#include <assert.h>
#include <math.h>
static uint32_t clock_ms,tx_due;static uint8_t *rx_byte;static uint8_t tx_copy[128];static uint16_t tx_n;
static char captured[2000000];static unsigned captured_n,enable_count;static bool peer_run[2],keep_host,stall_setup,drop_second,same_uid;
static CanFrame frames[32];static unsigned fw,fr;static float regs_values[2][0x30];static CanTransportLog logger;
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
 assert(CanFrame_IsValid(f));logger("TX_SUBMIT",f);unsigned type=f->id>>24,index=f->data[0]|((unsigned)f->data[1]<<8),id=f->id&255U;assert(id==1||id==2);unsigned i=id-1;
 if(i==1&&drop_second)return true;
 CanFrame r={.dlc=8,.extended=true,.timestamp_ms=at};
 if(type==0){r.id=(id<<8)|254;memcpy(r.data,"UID12345",8);if(i==1&&!same_uid)++r.data[0];}
 else if(type==3||type==4||type==18){
  if(type==3){assert(motor.parameter==5&&motor2.parameter==5);assert(!motor.hold_enable&&!motor2.hold_enable);peer_run[i]=true;++enable_count;}
  if(type==4)peer_run[i]=false;
  if(type==18){assert(index==0x7005||index==0x700A||index==0x7016||index==0x7017||index==0x7018||index==0x7022);float v=index==0x7005?f->data[4]:RsSpc_Float(f->data+4);
   if((index==0x700A&&v!=0)||(index==0x7016&&fabsf(v-regs_values[i][0x19])>.0001f&&peer_run[i])){assert(motor.enabled&&motor2.enabled&&!motor.hold_control&&!motor2.hold_control);}
   regs_values[i][index-0x7000]=v;
  }
  r.id=(2UL<<24)|(id<<8)|253|(peer_run[i]?2UL<<22:0);
 }else{assert(type==17);if(i==1&&stall_setup&&index==0x7017)return true;
  r.id=(17UL<<24)|(id<<8)|253;r.data[0]=index&255;r.data[1]=index>>8;if(index==0x7005)r.data[4]=(uint8_t)regs_values[i][5];else memcpy(r.data+4,&regs_values[i][index-0x7000],4);
 }
 assert(fw-fr<32);frames[fw++%32]=r;return true;
}
static void input(const char *text){while(*text){assert(rx_byte);*rx_byte=(uint8_t)*text++;HAL_UART_RxCpltCallback(&test_uart);}}
static void advance(unsigned n){while(n--){++clock_ms;if(tx_n&&clock_ms>=tx_due){assert(captured_n+tx_n<sizeof(captured));memcpy(captured+captured_n,tx_copy,tx_n);captured_n+=tx_n;captured[captured_n]=0;tx_n=0;HAL_UART_TxCpltCallback(&test_uart);}if(keep_host&&clock_ms%100==0)input("KEEP AABBCCDD\n");MotorEnableApp_Step();}}
static void boot(void){clock_ms=tx_due=tx_n=captured_n=enable_count=fw=fr=0;peer_run[0]=peer_run[1]=keep_host=stall_setup=drop_second=same_uid=false;memset(regs_values,0,sizeof(regs_values));regs_values[0][0x19]=1;regs_values[1][0x19]=2;MotorEnableApp_Init(&test_can,&test_uart);input("SESSION AABBCCDD 0\n");keep_host=true;advance(1500);assert(motor.stage==TU_READY&&motor2.stage==TU_READY&&enable_count==0);}
int main(void){
 boot();input("ARM2 AABBCCDD POS 1 5000 200 -3000 200 2000\n");advance(750);assert(enable_count==2&&motor.applied_seq==1&&motor2.applied_seq==1);assert(motor.run_ms==2000&&motor2.run_ms==2000);
 input("SET2 AABBCCDD 2 10000 100 -10000 301\n");advance(150);assert(motor.accepted_seq==1&&motor2.accepted_seq==1);
 input("SET2 AABBCCDD 3 10000 100 -10000 100\n");advance(300);assert(motor.applied_seq==3&&motor2.applied_seq==3);advance(2500);assert(motor.stage==TU_DONE&&motor2.stage==TU_DONE&&motor.stopped&&motor2.stopped&&motor.target_cleared&&motor2.target_cleared);assert(strstr(captured,"TUNE_GROUP_RESULT,result=STOPPED"));assert(!uart_failed&&tx_high_water<8192);
 boot();input("ARM2 AABBCCDD SPD 1 100 0 -100 0 10000\n");advance(5500);assert(motor.stage==TU_ACTIVE&&motor2.stage==TU_ACTIVE&&enable_count==2);advance(6000);assert(motor.stage==TU_DONE&&motor2.stage==TU_DONE&&motor.stopped&&motor2.stopped&&regs_values[0][0xA]==0&&regs_values[1][0xA]==0);
 boot();stall_setup=true;input("ARM2 AABBCCDD POS 1 5000 200 -3000 200 3000\n");advance(450);assert(enable_count==0);advance(1800);assert(motor.error&&motor2.error&&motor.stopped&&motor2.stopped&&enable_count==0);
 boot();input("ARM2 AABBCCDD SPD 1 100 0 -100 0 60001\n");advance(100);assert(enable_count==0&&motor.stage==TU_READY&&motor2.stage==TU_READY);
 input("ARM2 AABBCCDD SPD 1 100 0 -100 0 10000\n");advance(750);regs_values[1][0x1A]=6.1f;advance(1200);assert(motor.stage==TU_DONE&&motor2.stage==TU_DONE&&motor.error&&motor2.error&&motor.stopped&&motor2.stopped);
 boot();input("ARM2 AABBCCDD SPD 1 100 0 -100 0 10000\n");advance(750);drop_second=true;advance(3000);assert(motor.stage==TU_DONE&&motor2.stage==TU_DONE&&motor.stopped&&!motor2.stopped);assert(strstr(captured,"TUNE_GROUP_RESULT,result=ERROR"));assert(strstr(captured,"stop_confirmed=0"));
 boot();memcpy(motor2.uid,motor.uid,8);input("ARM2 AABBCCDD POS 1 5000 200 -3000 200 3000\n");advance(100);assert(enable_count==0);
 boot();input("ARM2 AABBCCDD POS 1 0 200 0 200 300000\n");advance(62000);assert(motor.stage==TU_ACTIVE&&motor2.stage==TU_ACTIVE&&!uart_failed&&tx_high_water<8192);input("STOP\n");advance(1000);assert(motor.stopped&&motor2.stopped);
 puts("dual tuning: preparation barrier, atomic targets, timed run, peer faults, missing stop and 62s UART capacity OK");return 0;
}
