#include "device_read_app.h"
#include "transport/can_transport.h"
#include "dual_test_frames.h"
#include <stdio.h>
#include <stdlib.h>

static unsigned checks, sends, completed;
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr,"%s:%d: %s\n",__FILE__,__LINE__,#x); exit(1); } } while(0)
FDCAN_GlobalTypeDef fake_fdcan1;
FDCAN_HandleTypeDef hfdcan1={.Instance=FDCAN1};
static UART_HandleTypeDef uart;
static uint32_t tick;
static CanTransportLog logger;
static bool off, rx_ready, init_ok=true;
static HAL_StatusTypeDef uart_status=HAL_OK;
static CanFrame rx, sent;
static GPIO_PinState led;
static char output[524288]; static size_t used;
uint32_t HAL_GetTick(void) { return tick; }
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *h,const uint8_t *data,uint16_t n,uint32_t timeout) {
    (void)h; (void)timeout;
    if (uart_status!=HAL_OK) return uart_status;
    CHECK(used+n<sizeof(output)); memcpy(output+used,data,n); used+=n; output[used]=0;
    return HAL_OK;
}
void HAL_GPIO_WritePin(void *port,uint16_t pin,GPIO_PinState state) { (void)port; (void)pin; led=state; }
HAL_StatusTypeDef HAL_FDCAN_GetErrorCounters(const FDCAN_HandleTypeDef *h,FDCAN_ErrorCountersTypeDef *c) {
    (void)h; c->TxErrorCnt=0; c->RxErrorCnt=0; return HAL_OK;
}
bool CanTransport_Init(FDCAN_HandleTypeDef *h,uint32_t bitrate,CanTransportFilter filter,uint8_t id,CanTransportLog log) {
    CHECK(h==&hfdcan1 && bitrate==500000 && filter==CAN_FILTER_DUAL && id==0xAA);
    logger=log; return init_ok;
}
bool CanTransport_Submit(const CanFrame *f,uint32_t now) {
    CHECK(!off); sent=*f; sent.timestamp_ms=now; ++sends; logger("TX_SUBMIT",&sent);
    CHECK(f->extended ? (!f->remote && (f->id>>24==2 || f->id>>24==5 || f->id>>24==7)) :
          (f->remote && f->dlc==0 && f->id!=0x104));
    return true;
}
void CanTransport_Service(uint32_t now) {
    if (completed<sends) { CanFrame f=sent; f.timestamp_ms=now; logger("TX_DONE",&f); completed=sends; }
}
bool CanTransport_Receive(CanFrame *f) { if (!rx_ready) return false; *f=rx; rx_ready=false; return true; }
CanTransportStats CanTransport_GetStats(void) { return (CanTransportStats){.tx_submitted=sends,.tx_completed=completed,.bus_off=off}; }
bool CanTransport_IsBusOff(void) { return off; }
static void respond(DeviceReader *r) {
    ++tick; rx=dual_test_reply(r->config.kind,r->query_index,tick); rx_ready=true; DeviceRead_Step();
}
static void run(uint32_t begin,uint32_t end,bool power_only) {
    for (uint32_t t=begin;t<=end;t+=10) {
        tick=t; DeviceRead_Step();
        CHECK(!(g_dual_device_reader.bms.pending && g_dual_device_reader.power.pending));
        if (g_dual_device_reader.bms.pending && !power_only) respond(&g_dual_device_reader.bms);
        if (g_dual_device_reader.power.pending) respond(&g_dual_device_reader.power);
    }
}
int main(void) {
    DeviceRead_Init(&hfdcan1,&uart);
    CHECK(strstr(output,"READ ONLY DUAL") && strstr(output,"device=BMS+POWER bitrate=500000"));
    CHECK(strstr(output,"no automatic configuration writes") && strstr(output,"one_pending_total=1"));
    tick=999; DeviceRead_Step(); CHECK(sends==0);
    run(1000,65000,false);
    CHECK(g_dual_device_reader.bms.valid_mask==0x1F && g_dual_device_reader.power.valid_mask==0xFFF);
    CHECK(led==GPIO_PIN_SET && g_dual_device_reader.power.power.can_baud_code==2);
    CHECK(strstr(output,"FDCAN1,STD,RTR,0x00000100,0,") && strstr(output,"FDCAN1,EXT,DATA,0x050000AA,8,"));
    CHECK(strstr(output,"# BMS,voltage_mv=45860") && strstr(output,"# POWER,version=V1.08"));
    CHECK(strstr(output,"# DEVICE_HEALTH,t_ms=5000,device=BMS") && strstr(output,"device=POWER,seen="));
    CHECK(strstr(output,"device=DUAL,tx_submit=") && strstr(output,"tec=0,rec=0,counters_ok=1"));
    CHECK(g_dual_device_reader.bms.stats.timeouts==0 && g_dual_device_reader.power.stats.timeouts==0);
    /* An unsolicited power frame while waiting for BMS must not complete BMS. */
    tick=0; DeviceRead_Init(&hfdcan1,&uart); tick=1000; DeviceRead_Step();
    rx=dual_test_reply(READER_POWER,0,1001); rx_ready=true; tick=1001; DeviceRead_Step();
    CHECK(g_dual_device_reader.bms.pending && g_dual_device_reader.bms.stats.replies==0);
    CHECK(g_dual_device_reader.power.stats.replies==1 && led==GPIO_PIN_RESET);
    run(1010,20000,true);
    CHECK(g_dual_device_reader.bms.stats.timeouts>0 && g_dual_device_reader.power.stats.replies>12);
    CHECK(led==GPIO_PIN_RESET);
    /* Bus-off halts both transmit schedulers, but still ages both devices. */
    off=true; unsigned before=sends; tick=25000; DeviceRead_Step(); tick=40000; DeviceRead_Step();
    CHECK(sends==before && led==GPIO_PIN_RESET);
    CHECK(g_dual_device_reader.bms.valid_mask==0 && g_dual_device_reader.power.valid_mask==0);
    CHECK(strstr(output,"BUS_OFF latched"));
    off=false; tick=0; DeviceRead_Init(&hfdcan1,&uart);
    uart_status=HAL_ERROR; tick=5000; DeviceRead_Step(); before=sends;
    tick=6000; DeviceRead_Step(); CHECK(sends==before && led==GPIO_PIN_RESET);
    uart_status=HAL_OK; init_ok=false; tick=0; DeviceRead_Init(&hfdcan1,&uart);
    CHECK(strstr(output,"FATAL initialization failed"));
    before=sends; tick=1000; DeviceRead_Step(); CHECK(sends==before);
    printf("dual application: %u checks passed\n",checks);
    return 0;
}
