#include "motor_read_app.h"
#include "transport/can_transport.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"%s:%d: %s\n",__FILE__,__LINE__,#x); exit(1); } } while(0)
FDCAN_GlobalTypeDef fake_fdcan1, fake_fdcan3;
static FDCAN_HandleTypeDef handle={.Instance=FDCAN3};
static UART_HandleTypeDef uart;
static uint32_t tick,sends,done;
static CanFrame sent;
static CanTransportLog logger;
static bool delivered,off,init_ok=true,uart_ok=true;
static GPIO_PinState led;
static char output[250000]; static size_t used;
uint32_t HAL_GetTick(void) { return tick; }
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *h,const uint8_t *data,uint16_t n,uint32_t timeout) {
    (void)timeout; CHECK(h==&uart);
    if(!uart_ok) return HAL_ERROR;
    CHECK(used+n<sizeof(output)); memcpy(output+used,data,n); used+=n; output[used]=0; return HAL_OK;
}
void HAL_GPIO_WritePin(void *port,uint16_t pin,GPIO_PinState state) { CHECK(port==GPIOA && pin==GPIO_PIN_5); led=state; }
HAL_StatusTypeDef HAL_FDCAN_GetErrorCounters(const FDCAN_HandleTypeDef *h,FDCAN_ErrorCountersTypeDef *e) {
    CHECK(h==&handle); *e=(FDCAN_ErrorCountersTypeDef){0}; return HAL_OK;
}
bool CanTransport_Init(FDCAN_HandleTypeDef *h,uint32_t rate,CanTransportFilter filter,uint8_t id,CanTransportLog log) {
    CHECK(h==&handle && rate==1000000 && filter==CAN_FILTER_MOTOR && id==0xFD);
    logger=log; delivered=true; return init_ok;
}
bool CanTransport_Submit(const CanFrame *f,uint32_t now) {
    CHECK(!off && f->extended && !f->remote && f->dlc==8 && f->id>>24==0x11);
    CHECK(f->data[2]==0 && f->data[3]==0 && f->data[4]==0 && f->data[5]==0 && f->data[6]==0 && f->data[7]==0);
    sent=*f; sent.timestamp_ms=now; ++sends; delivered=false; logger("TX_SUBMIT",&sent); return true;
}
void CanTransport_Service(uint32_t now) {
    if(done<sends) { CanFrame f=sent; f.timestamp_ms=now; logger("TX_DONE",&f); done=sends; }
}
bool CanTransport_Receive(CanFrame *f) {
    if(delivered) return false;
    delivered=true;
    *f=sent; f->id=0x11000000U|((sent.id&255U)<<8)|0xFDU; f->timestamp_ms=tick;
    f->data[4]=0; f->data[5]=0; f->data[6]=0xC0; f->data[7]=0x3F; return true;
}
CanTransportStats CanTransport_GetStats(void) { return (CanTransportStats){.tx_submitted=sends,.tx_completed=done,.bus_off=off}; }
bool CanTransport_IsBusOff(void) { return off; }
int main(void) {
    MotorRead_Init(&handle,&uart);
    CHECK(strstr(output,"channel=FDCAN3 device=MOTOR bitrate=1000000"));
    CHECK(strstr(output,"no enable/control/write"));
    tick=999; MotorRead_Step(); CHECK(!sends);
    for(tick=1000;tick<=65000;tick+=10) MotorRead_Step();
    for(uint8_t n=0;n<PICO_MOTOR_COUNT;++n) CHECK(g_motor_reader.nodes[n].valid==0x0F && g_motor_reader.nodes[n].timeouts==0);
    CHECK(strstr(output,"# MOTOR,device=MOTOR1") && strstr(output,"position_millirad=1500"));
    char expected[100];
    (void)snprintf(expected,sizeof(expected),"FDCAN3,EXT,DATA,0x1100FD%02X,8,19 70 00 00 00 00 00 00",PICO_MOTOR1_ID);
    CHECK(strstr(output,expected));
    CHECK(strstr(output,"# DEVICE_HEALTH") && strstr(output,"tec=0,rec=0,counters_ok=1"));
    CHECK(led==GPIO_PIN_SET);
    /* Error-class observations belong to the actual active CAN3 instance. */
    fake_fdcan3.PSR=3;
    logger("TX_TIMEOUT",&sent);
    CHECK(strstr(output,"# CAN_DIAG,event=TX_TIMEOUT,channel=FDCAN3,psr=0x00000003,lec=3"));
    uint32_t stopped_sends=sends;
    tick+=1000; MotorRead_Step(); CHECK(sends==stopped_sends && led==GPIO_PIN_RESET);
    CHECK(strstr(output,"# STOP,reason=TX_TIMEOUT"));
    fake_fdcan3.PSR=0x85;
    off=true; uint32_t before=sends; tick=80000; MotorRead_Step();
    CHECK(sends==before && led==GPIO_PIN_RESET && g_motor_reader.nodes[0].valid==0);
    CHECK(strstr(output,"# CAN_DIAG,event=BUS_OFF,channel=FDCAN3,psr=0x00000085,lec=5"));
    off=false; tick=0; MotorRead_Init(&handle,&uart); uart_ok=false;
    tick=1000; MotorRead_Step(); before=sends; tick=2000; MotorRead_Step(); CHECK(sends==before);
    uart_ok=true; init_ok=false; tick=0; MotorRead_Init(&handle,&uart);
    before=sends; tick=1000; MotorRead_Step(); CHECK(sends==before && strstr(output,"FATAL initialization failed"));
    puts("Motor application: CAN3 read-only output, UART, aging and bus-off checks passed");
    return 0;
}
