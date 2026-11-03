#include "device_read_app.h"
#if defined(PICO_POWER_BAUD_TEST)
#include "power_baud_test.h"
static unsigned completed;
#endif
#include "transport/can_transport.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned checks;
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr,"%s:%d: %s\n",__FILE__,__LINE__,#x); exit(1); } } while(0)
FDCAN_GlobalTypeDef fake_fdcan1;
FDCAN_HandleTypeDef hfdcan1={.Instance=FDCAN1};
static UART_HandleTypeDef uart;
static uint32_t tick;
static CanTransportLog logger;
static bool init_ok=true, off, rx_ready;
static HAL_StatusTypeDef uart_status=HAL_OK;
static CanFrame received, sent;
static unsigned sends;
static GPIO_PinState led;
static char output[262144]; static size_t output_size;
uint32_t HAL_GetTick(void) { return tick; }
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *h,const uint8_t *data,uint16_t length,uint32_t timeout) {
    (void)h; (void)timeout;
    if(uart_status!=HAL_OK) return uart_status;
    CHECK(output_size+length < sizeof(output));
    memcpy(output+output_size,data,length); output_size+=length; output[output_size]=0;
    return HAL_OK;
}
void HAL_GPIO_WritePin(void *port,uint16_t pin,GPIO_PinState state) { (void)port; (void)pin; led=state; }
HAL_StatusTypeDef HAL_FDCAN_GetErrorCounters(const FDCAN_HandleTypeDef *h,FDCAN_ErrorCountersTypeDef *c) {
    (void)h; c->TxErrorCnt=0; c->RxErrorCnt=0; return HAL_OK;
}
bool CanTransport_Init(FDCAN_HandleTypeDef *h,uint32_t bitrate,CanTransportFilter filter,uint8_t id,CanTransportLog log) {
    CHECK(h==&hfdcan1 && bitrate==PICO_DEVICE_BITRATE && id==0xAA);
    CHECK(filter==(PICO_DEVICE_KIND==0 ? CAN_FILTER_BMS : CAN_FILTER_POWER)); logger=log; return init_ok;
}
bool CanTransport_Submit(const CanFrame *frame,uint32_t now) {
    if(off)return false;
    sent=*frame; sent.timestamp_ms=now; ++sends; logger("TX_SUBMIT",&sent); return true;
}
void CanTransport_Service(uint32_t now) {
    (void)now;
#if defined(PICO_POWER_BAUD_TEST)
    if(completed<sends) { logger("TX_DONE",&sent); completed=sends; }
#endif
}
bool CanTransport_Receive(CanFrame *frame) { if(!rx_ready)return false; *frame=received; rx_ready=false; return true; }
CanTransportStats CanTransport_GetStats(void) { return (CanTransportStats){.tx_submitted=sends,
#if defined(PICO_POWER_BAUD_TEST)
    .tx_completed=completed,
#endif
    .bus_off=off ? 1U : 0U}; }
bool CanTransport_IsBusOff(void) { return off; }
static void inject_reply(uint8_t job,uint32_t now) {
#if PICO_DEVICE_KIND == 0
    received=(CanFrame){.id=bms_query_ids[job],.dlc=8,.timestamp_ms=now};
    uint16_t crc=Bms_Crc16(received.data,6); received.data[6]=(uint8_t)(crc>>8); received.data[7]=(uint8_t)crc;
#else
    uint8_t type=job==0 ? 5 : job==1 ? 3 : job==2 ? 4 : 7;
    received=(CanFrame){.id=((uint32_t)type<<24)|0x00AA0000U,.dlc=8,.extended=true,.timestamp_ms=now};
    if(job==0)memcpy(received.data,"PBV1.00",7);
    if(job>=3){
        const uint16_t parameter=power_parameter_indices[job-3];
        received.data[0]=(uint8_t)parameter;received.data[1]=(uint8_t)(parameter>>8);received.data[4]=1;
    }
#endif
    rx_ready=true;
}
int main(void) {
    tick=0; DeviceRead_Init(&hfdcan1,&uart);
#if defined(PICO_POWER_BAUD_TEST)
    CHECK(strstr(output,"EXPLICITLY GATED BAUD TEST") && strstr(output,"default=READ_ONLY"));
#else
    CHECK(strstr(output,"READ ONLY") && strstr(output,"no automatic configuration writes"));
#endif
    CHECK(strstr(output,"t_ms,event,channel,format,kind,id,dlc,data"));
    uint8_t count=PICO_DEVICE_KIND==0 ? BMS_QUERY_COUNT : POWER_QUERY_COUNT;
    for(uint8_t i=0;i<count;++i) {
        tick=1000U+210U*i; DeviceRead_Step(); CHECK(sends==(unsigned)i+1U);
#if PICO_DEVICE_KIND == 0
        CHECK(sent.remote && !sent.extended && sent.id==bms_query_ids[i]);
#else
        CHECK(sent.extended && !sent.remote && ((sent.id>>24)==5 || (sent.id>>24)==2 || (sent.id>>24)==7));
#endif
        tick+=10; inject_reply(i,tick); DeviceRead_Step();
    }
    CHECK(g_device_reader.valid_mask==(PICO_DEVICE_KIND==0 ? 31U : POWER_ALL_FRESH_MASK));
    CHECK(led==GPIO_PIN_SET);
    /* A UART fault must clear the freshness LED, even with otherwise fresh data. */
    uart_status=HAL_ERROR; tick=4000; inject_reply(0,tick); DeviceRead_Step();
    CHECK(led==GPIO_PIN_RESET);
    unsigned halted=sends; tick=4200; DeviceRead_Step(); CHECK(sends==halted);
    uart_status=HAL_OK; tick=0; DeviceRead_Init(&hfdcan1,&uart);
    CHECK(led==GPIO_PIN_RESET);
#if PICO_DEVICE_KIND == 0
    CHECK(strstr(output,"FDCAN1,STD,RTR,0x00000100,8,\r\n"));
    CHECK(strstr(output,"# BMS,voltage_mv=0,current_ma=0,remaining_mah=0"));
    CHECK(strstr(output,"temperature_decic=-2731/-2731/-2731"));
#else
    CHECK(strstr(output,"FDCAN1,EXT,DATA,0x050000AA,8,"));
#if PICO_POWER_STATUS_ORDER == 0
    CHECK(strstr(output,"status03_numeric=UNCONFIRMED_ENDIAN"));
#else
    CHECK(strstr(output,"# POWER,battery_mv="));
#endif
    CHECK(strstr(output,"name=POWER_ID,value_u8=1") && strstr(output,"id_mismatch=1"));
    CHECK(strstr(output,"name=arTime") && strstr(output,"units=UNCONFIRMED"));
    CHECK(strstr(output,"name=Can_baud,value_u8=1"));
#endif
    off=true; tick=5000; DeviceRead_Step();
    CHECK(strstr(output,"BUS_OFF latched") && strstr(output,"# HEALTH,") && strstr(output,"bus_off=1"));
    CHECK(led==GPIO_PIN_RESET);
    tick=20000; DeviceRead_Step(); CHECK(g_device_reader.valid_mask==0);
    /* A UART error halts the application; it cannot silently continue unlogged traffic. */
    uart_status=HAL_ERROR; tick=25000; DeviceRead_Step();
    unsigned before=sends; off=false; tick=26000; DeviceRead_Step(); CHECK(sends==before);
    uart_status=HAL_OK; init_ok=false; tick=0; DeviceRead_Init(&hfdcan1,&uart);
    CHECK(strstr(output,"FATAL initialization failed"));
    before=sends; tick=1000; DeviceRead_Step(); CHECK(sends==before);
#if defined(PICO_POWER_BAUD_TEST)
    off=false; init_ok=true; uart_status=HAL_OK; sends=completed=0; output_size=0; output[0]=0;
    tick=0; DeviceRead_Init(&hfdcan1,&uart);
    for(uint32_t t=0;t<=60050;t+=10) {
        tick=t; DeviceRead_Step();
        if(g_device_reader.pending) {
            tick=t+1; inject_reply(g_device_reader.query_index,tick); DeviceRead_Step();
        }
    }
    CHECK(sends>250 && g_power_baud_stage==POWER_BAUD_IDLE && g_device_reader.stats.timeouts==0);
    CHECK(!strstr(output,"0x080000AA"));
    g_power_baud_command=POWER_BAUD_ARM; tick=60060; DeviceRead_Step();
    CHECK(g_power_baud_stage==POWER_BAUD_ARMED);
    unsigned baseline_sends=sends;
    g_power_baud_command=POWER_BAUD_COMMIT; tick=60061; DeviceRead_Step();
    CHECK(sends==baseline_sends+1 && sent.id==0x080000AA && sent.data[4]==2);
    tick=60062; DeviceRead_Step();
    CHECK(g_power_baud_stage==POWER_BAUD_READ_WAIT && sends==baseline_sends+2);
    tick=60063; inject_reply(3,tick); DeviceRead_Step();
    CHECK(g_power_baud_stage==POWER_BAUD_DONE && strstr(output,"NOT a migration PASS"));
    tick=80000; DeviceRead_Step();
    CHECK(sends==baseline_sends+2 && g_device_reader.valid_mask==0 && led==GPIO_PIN_RESET);
#endif
    printf("application(kind=%u): %u checks passed\n",(unsigned)PICO_DEVICE_KIND,checks);
    return 0;
}
