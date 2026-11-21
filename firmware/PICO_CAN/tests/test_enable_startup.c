#include "motor_enable_app.h"
#include "transport/can_transport.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
static UART_HandleTypeDef uart;
static uint32_t tick,enables;
static uint8_t *armed;
static bool injected,pending;
static CanFrame response;
static char output[50000];static size_t used;
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *h);
void HAL_UART_ErrorCallback(UART_HandleTypeDef *h);
uint32_t HAL_GetTick(void){return tick;}
void HAL_NVIC_SetPriority(int a,int b,int c){(void)a;(void)b;(void)c;}
void HAL_NVIC_EnableIRQ(int a){(void)a;}
HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *h,uint8_t *p,uint16_t n){CHECK(h==&uart&&n==1);armed=p;return HAL_OK;}
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *h,const uint8_t *p,uint16_t n,uint32_t timeout){
    (void)timeout;CHECK(h==&uart);CHECK(used+n<sizeof(output));memcpy(output+used,p,n);used+=n;output[used]=0;
    if(!injected){
        injected=true;
        /* An old/fast client answers while the first banner is being printed. */
        CHECK(armed!=NULL);
        const char *cmd="SESSION AABBCCDD 1\n";
        while(*cmd){*armed=(uint8_t)*cmd++;HAL_UART_RxCpltCallback(&uart);}
    }return HAL_OK;
}
HAL_StatusTypeDef HAL_FDCAN_AbortTxRequest(FDCAN_HandleTypeDef *h,uint32_t m){(void)h;(void)m;return HAL_OK;}
HAL_StatusTypeDef HAL_FDCAN_GetErrorCounters(const FDCAN_HandleTypeDef *h,FDCAN_ErrorCountersTypeDef *e){(void)h;memset(e,0,sizeof(*e));return HAL_OK;}
bool CanTransport_Init(FDCAN_HandleTypeDef *h,uint32_t b,CanTransportFilter f,uint8_t id,CanTransportLog log){(void)h;(void)b;(void)f;(void)id;(void)log;return true;}
bool CanTransport_Submit(const CanFrame *f,uint32_t now){
    uint32_t type=f->id>>24;if(type==3)++enables;
    response=(CanFrame){.id=0x020001FD,.extended=true,.dlc=8,.timestamp_ms=now};
    if(type==17){response.id=0x110001FD;response.data[0]=f->data[0];response.data[1]=f->data[1];}
    pending=true;return true;
}
void CanTransport_Service(uint32_t now){(void)now;}
bool CanTransport_Receive(CanFrame *f){if(!pending)return false;pending=false;*f=response;return true;}
CanTransportStats CanTransport_GetStats(void){return (CanTransportStats){0};}
int main(void){
    FDCAN_GlobalTypeDef regs={0};FDCAN_HandleTypeDef can={.Instance=&regs};
    MotorEnableApp_Init(&can,&uart);
    for(tick=0;tick<1000;++tick)MotorEnableApp_Step();
#if defined(PICO_MOTOR_POSITION)
    CHECK(strstr(output,"PICO_MOTOR_POSITION=1;"));CHECK(strstr(output,"POSITION_COMMAND_READY=1"));
    CHECK(strstr(output,"max_enable_ms=90000"));
#elif defined(PICO_MOTOR_SPEED)
    CHECK(strstr(output,"PICO_MOTOR_SPEED=1;"));CHECK(strstr(output,"SPEED_COMMAND_READY=1"));
#if defined(PICO_SPEED_LIMIT_MA) && PICO_SPEED_LIMIT_MA == 700
    CHECK(strstr(output,"target_rad_s=0.3 current_limit_A=0.7 accel_rad_s2=0.5 iq_trip_A=0.8 current_policy=STARTUP_0700_V1\r\n"));
#else
    CHECK(strstr(output,"target_rad_s=0.3 current_limit_A=0.5 accel_rad_s2=0.5 iq_trip_A=0.8 current_policy=BASE_0500_V1\r\n"));
#endif
#else
    CHECK(strstr(output,"ENABLE_COMMAND_READY=1"));
#endif
    CHECK(strstr(output,"SESSION_OK token=AABBCCDD id=1"));
    CHECK(strstr(output,"state=READY"));CHECK(!strstr(output,"UART_LINK_ERROR"));CHECK(enables==0);
    uart.ErrorCode=8;HAL_UART_ErrorCallback(&uart);
    for(;tick<1100;++tick)MotorEnableApp_Step();
    CHECK(strstr(output,"reason=UART_LINK_ERROR"));CHECK(strstr(output,"stop_confirmed=1"));CHECK(enables==0);
    puts("RX armed before banner; early SESSION accepted; runtime overrun still stops: PASS");return 0;
}
