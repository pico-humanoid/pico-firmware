#include "protocol/robstride_spc.h"
#include "motor_read_app.h"
#include "transport/can_transport.h"
#include <stdio.h>
#include <string.h>
#if PICO_MOTOR_CAN_CHANNEL == 1
#define MOTOR_CAN_NAME "FDCAN1"
#define MOTOR_CAN_PINS "TX=PA12 RX=PA11 AF9"
#else
#define MOTOR_CAN_NAME "FDCAN3"
#define MOTOR_CAN_PINS "TX=PA15 RX=PA8 AF11"
#endif
#if defined(PICO_CAN_PIN_TRACE)
#include "can_pin_trace.h"
#endif

MotorReader g_motor_reader;
static UART_HandleTypeDef *serial;
static FDCAN_HandleTypeDef *bus;
static bool ready, uart_failed, reported_off, link_failed;
static uint32_t next_health;
static const char *const models[2]={PICO_MOTOR1_MODEL,PICO_MOTOR2_MODEL};
static void line(const char *text) {
    if (!uart_failed && HAL_UART_Transmit(serial,(const uint8_t *)text,(uint16_t)strlen(text),100U)!=HAL_OK)
        uart_failed=true;
}
static void log_can_error(const char *event) {
    /* Capture before slow UART output. Reading PSR changes sticky LEC fields;
       this is a discrete observation, not a continuous error history. */
    const uint32_t psr=bus->Instance->PSR;
    FDCAN_ErrorCountersTypeDef errors={0};
    bool counters=HAL_FDCAN_GetErrorCounters(bus,&errors)==HAL_OK;
    char text[256];
    (void)snprintf(text,sizeof(text),
        "# CAN_DIAG,event=%s,channel=" MOTOR_CAN_NAME ",psr=0x%08lX,lec=%lu,act=%lu,bus_off=%lu,tec=%lu,rec=%lu,counters_ok=%u\r\n",
        event,(unsigned long)psr,(unsigned long)(psr&7U),(unsigned long)((psr>>3)&3U),
        (unsigned long)((psr>>7)&1U),(unsigned long)errors.TxErrorCnt,
        (unsigned long)errors.RxErrorCnt,counters?1U:0U);
    line(text);
}
static void log_frame(const char *event,const CanFrame *f) {
    if (strcmp(event,"TX_TIMEOUT")==0) {
        log_can_error(event);
        if (!link_failed) line("# STOP,reason=TX_TIMEOUT; motor reads stopped until RESET; no automatic bitrate changes\r\n");
        link_failed=true;
    }
    char text[192];
    int used=snprintf(text,sizeof(text),"%lu,%s," MOTOR_CAN_NAME ",%s,%s,0x%08lX,%u,",
        (unsigned long)f->timestamp_ms,event,f->extended?"EXT":"STD",f->remote?"RTR":"DATA",
        (unsigned long)f->id,(unsigned)f->dlc);
    if (!f->remote) for(uint8_t i=0;i<f->dlc;++i)
        used+=snprintf(text+used,sizeof(text)-(size_t)used,"%s%02X",i?" ":"",f->data[i]);
    (void)snprintf(text+used,sizeof(text)-(size_t)used,"\r\n");
    line(text);
}
static bool send_read(void *context,const CanFrame *f,uint32_t now) {
    (void)context;
    return !uart_failed && CanTransport_Submit(f,now);
}
void MotorRead_Init(FDCAN_HandleTypeDef *can,UART_HandleTypeDef *uart) {
    serial=uart; bus=can; ready=false; uart_failed=false; reported_off=false; link_failed=false;
#if defined(PICO_CAN_PIN_TRACE)
    CanPinTrace_Init();
#endif
    HAL_GPIO_WritePin(GPIOA,GPIO_PIN_5,GPIO_PIN_RESET);
    if (!can || !uart) return;
    char text[320];
    (void)snprintf(text,sizeof(text),
        "# PICO device-read v1; READ ONLY MOTOR; channel=" MOTOR_CAN_NAME " device=MOTOR bitrate=1000000 count=%u host_id=0x%02X motor1_id=0x%02X motor2_id=0x%02X motor1_model=%s motor2_model=%s\r\n",
        PICO_MOTOR_COUNT,PICO_MOTOR_HOST_ID,PICO_MOTOR1_ID,PICO_MOTOR2_ID,models[0],models[1]);
    line(text);
 line(ROBSTRIDE_SPC_BANNER);
    line("# MOTOR_CAN_PINS " MOTOR_CAN_PINS "\r\n");
    line("# queries=type17:7019/701B/701A/701C; no enable/control/write; timestamps=MCU uptime ms\r\n");
    line("t_ms,event,channel,format,kind,id,dlc,data\r\n");
    if (!MotorReader_Init(&g_motor_reader,PICO_MOTOR_COUNT,PICO_MOTOR1_ID,PICO_MOTOR2_ID,
                          PICO_MOTOR_HOST_ID,HAL_GetTick()) ||
        !CanTransport_Init(can,1000000U,CAN_FILTER_MOTOR,PICO_MOTOR_HOST_ID,log_frame)) {
        line("# FATAL initialization failed; expected " MOTOR_CAN_NAME " / PCLK1 16MHz; no requests sent\r\n");
        return;
    }
    for (uint8_t n=0;n<g_motor_reader.count;++n) {
        (void)snprintf(text,sizeof(text),"# MOTOR_CONFIG,device=MOTOR%u,model=%s,id=0x%02X,model_source=configured_not_detected\r\n",
            n+1U,models[n],g_motor_reader.nodes[n].id);
        line(text);
    }
    next_health=HAL_GetTick()+5000U;
    ready=!uart_failed;
}
void MotorRead_Step(void) {
    if (!ready || uart_failed) { HAL_GPIO_WritePin(GPIOA,GPIO_PIN_5,GPIO_PIN_RESET); return; }
    uint32_t now=HAL_GetTick();
    CanTransport_Service(now);
#if defined(PICO_CAN_PIN_TRACE)
    CanPinTrace_Dump(serial);
#endif
    CanFrame frame;
    for (uint8_t i=0;i<31U && CanTransport_Receive(&frame);++i) {
        log_frame("RX",&frame);
        uint8_t node; MotorReading reading;
        if (MotorReader_OnFrame(&g_motor_reader,&frame,&node,&reading)) {
            char text[256];
            (void)snprintf(text,sizeof(text),
                "# MOTOR,device=MOTOR%u,model=%s,id=0x%02X,index=0x%04X,%s=%ld,raw_bits=0x%08lX\r\n",
                node+1U,models[node],g_motor_reader.nodes[node].id,motor_read_indices[reading.query],
                motor_read_fields[reading.query],(long)reading.value_milli,(unsigned long)reading.raw_bits);
            line(text);
        }
    }
    MotorReader_Age(&g_motor_reader,now);
    bool off=CanTransport_IsBusOff();
    if (off && !reported_off) {
        log_can_error("BUS_OFF");
        line("# FATAL bus_off; requests stopped; check bus then RESET\r\n"); reported_off=true;
    }
    if (!off && !uart_failed && !link_failed) MotorReader_Step(&g_motor_reader,now,send_read,NULL);
    bool fresh=!off && !uart_failed && !link_failed;
    for (uint8_t n=0;n<g_motor_reader.count;++n) fresh=fresh && g_motor_reader.nodes[n].valid==0x0FU;
    HAL_GPIO_WritePin(GPIOA,GPIO_PIN_5,fresh?GPIO_PIN_SET:GPIO_PIN_RESET);
    if ((int32_t)(now-next_health)>=0) {
        CanTransportStats s=CanTransport_GetStats(); FDCAN_ErrorCountersTypeDef errors={0};
        bool counters=HAL_FDCAN_GetErrorCounters(bus,&errors)==HAL_OK;
        char text[768];
        (void)snprintf(text,sizeof(text),
            "# HEALTH,t_ms=%lu,device=MOTOR,tx_submit=%lu,tx_done=%lu,tx_rejected=%lu,tx_timeout=%lu,rx_fifo_lost=%lu,rx_queue_drop=%lu,rx_read_fail=%lu,rx_unsupported=%lu,tx_event_lost=%lu,tx_event_unknown=%lu,bus_off=%lu,tec=%lu,rec=%lu,counters_ok=%u\r\n",
            (unsigned long)now,(unsigned long)s.tx_submitted,(unsigned long)s.tx_completed,
            (unsigned long)s.tx_rejected,(unsigned long)s.tx_timed_out,(unsigned long)s.rx_fifo_lost,
            (unsigned long)s.rx_queue_dropped,(unsigned long)s.rx_read_failed,(unsigned long)s.rx_unsupported,
            (unsigned long)s.tx_event_lost,(unsigned long)s.tx_event_unknown,(unsigned long)s.bus_off,
            (unsigned long)errors.TxErrorCnt,(unsigned long)errors.RxErrorCnt,counters?1U:0U);
        line(text);
        for (uint8_t n=0;n<g_motor_reader.count;++n) {
            MotorNode *m=&g_motor_reader.nodes[n];
            (void)snprintf(text,sizeof(text),
                "# DEVICE_HEALTH,t_ms=%lu,device=MOTOR%u,model=%s,id=0x%02X,seen=0x%02X,valid=0x%02X,cycles=%lu,replies=%lu,invalid=%lu,ignored=%lu,query_timeouts=%lu,tx_submit=%lu,tx_rejected=%lu,pending=%u\r\n",
                (unsigned long)now,n+1U,models[n],m->id,m->seen,m->valid,(unsigned long)m->cycles,
                (unsigned long)m->replies,(unsigned long)m->invalid,(unsigned long)m->ignored,
                (unsigned long)m->timeouts,(unsigned long)m->submitted,(unsigned long)m->rejected,
                g_motor_reader.pending && g_motor_reader.pending_node==n?1U:0U);
            line(text);
        }
        next_health=now+5000U;
    }
}
