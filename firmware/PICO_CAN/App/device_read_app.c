#include "device_read_app.h"
#include "transport/can_transport.h"
#if defined(PICO_POWER_BAUD_TEST)
#include "power_baud_test.h"
#endif
#include <stdio.h>
#include <string.h>

#if defined(PICO_DEVICE_DUAL)
DualDeviceReader g_dual_device_reader;
#else
DeviceReader g_device_reader;
#endif
static UART_HandleTypeDef *serial;
static bool initialized, uart_failed, reported_bus_off;
static uint32_t next_summary;

static void line(const char *text) {
    if (uart_failed) return;
    if (HAL_UART_Transmit(serial, (const uint8_t *)text, (uint16_t)strlen(text), 100U) != HAL_OK)
        uart_failed = true;
}
#if defined(PICO_POWER_BAUD_TEST)
static bool baud_log(const char *text) { line(text); return !uart_failed; }
#endif
static void log_frame(const char *event, const CanFrame *frame) {
#if defined(PICO_POWER_BAUD_TEST)
    /* Snapshot before slow UART output. PSR/ECR reads may clear sticky fields;
       these are discrete observations, not a continuous error history. */
    extern FDCAN_HandleTypeDef hfdcan1;
    bool diagnostic = frame->id == (0x08000000UL | PICO_POWER_ID);
    uint32_t psr=0, ecr=0, brp=0, bto=0, bcf=0, efs=0, ir=0, cccr=0, nbtp=0;
    if (diagnostic) {
        psr=hfdcan1.Instance->PSR; ecr=hfdcan1.Instance->ECR;
        brp=hfdcan1.Instance->TXBRP; bto=hfdcan1.Instance->TXBTO;
        bcf=hfdcan1.Instance->TXBCF; efs=hfdcan1.Instance->TXEFS;
        ir=hfdcan1.Instance->IR; cccr=hfdcan1.Instance->CCCR; nbtp=hfdcan1.Instance->NBTP;
    }
#endif
    char text[360];
    int used = snprintf(text, sizeof(text), "%lu,%s,FDCAN1,%s,%s,0x%08lX,%u,",
        (unsigned long)frame->timestamp_ms, event, frame->extended ? "EXT" : "STD",
        frame->remote ? "RTR" : "DATA", (unsigned long)frame->id, (unsigned)frame->dlc);
    if (!frame->remote)
        for (uint8_t i = 0; i < frame->dlc; ++i)
            used += snprintf(text + used, sizeof(text) - (size_t)used, "%s%02X", i ? " " : "", frame->data[i]);
    (void)snprintf(text + used, sizeof(text) - (size_t)used, "\r\n");
    line(text);
#if defined(PICO_POWER_BAUD_TEST)
    if (diagnostic) {
        (void)snprintf(text, sizeof(text),
            "# CAN_DIAG,event=%s,PSR=0x%08lX,LEC=%lu,ACT=%lu,EP=%lu,EW=%lu,BO=%lu,ECR=0x%08lX,TXBRP=0x%08lX,TXBTO=0x%08lX,TXBCF=0x%08lX,TXEFS=0x%08lX,IR=0x%08lX,CCCR=0x%08lX,NBTP=0x%08lX\r\n",
            event, (unsigned long)psr, (unsigned long)(psr&7U),
            (unsigned long)((psr>>3)&3U), (unsigned long)((psr>>5)&1U),
            (unsigned long)((psr>>6)&1U), (unsigned long)((psr>>7)&1U),
            (unsigned long)ecr, (unsigned long)brp, (unsigned long)bto,
            (unsigned long)bcf, (unsigned long)efs, (unsigned long)ir,
            (unsigned long)cccr, (unsigned long)nbtp);
        line(text);
    }
    PowerBaudTest_OnTxEvent(event, frame);
#endif
}
static bool send_request(void *context, const CanFrame *frame, uint32_t now) {
    (void)context;
    return !uart_failed && CanTransport_Submit(frame, now);
}
static void sample(DeviceReader *r, int index) {
    char text[256];
    if (r->config.kind == READER_BMS) {
        switch (index) {
        case 0:
            (void)snprintf(text, sizeof(text), "# BMS,voltage_mv=%lu,current_ma=%ld,remaining_mah=%lu\r\n",
                (unsigned long)r->bms.voltage_mv, (long)r->bms.current_ma, (unsigned long)r->bms.remaining_mah);
            break;
        case 1:
            (void)snprintf(text, sizeof(text), "# BMS,full_mah=%lu,cycles=%u,soc_percent=%u\r\n",
                (unsigned long)r->bms.full_mah, r->bms.cycles, r->bms.soc_percent);
            break;
        case 2:
            (void)snprintf(text, sizeof(text), "# BMS,balance_low=0x%04X,balance_high=0x%04X,protection=0x%04X\r\n",
                r->bms.balance_low, r->bms.balance_high, r->bms.protection);
            break;
        case 3:
            (void)snprintf(text, sizeof(text), "# BMS,mos=0x%04X,date_raw=0x%04X,version_raw=0x%04X\r\n",
                r->bms.mos_status, r->bms.production_date_raw, r->bms.software_version);
            break;
        default:
            (void)snprintf(text, sizeof(text), "# BMS,temperature_decic=%ld/%ld/%ld\r\n",
                (long)r->bms.temperature_decic[0], (long)r->bms.temperature_decic[1], (long)r->bms.temperature_decic[2]);
            break;
        }
    } else {
        switch (index) {
        case 0:
            (void)snprintf(text, sizeof(text), "# POWER,version=%s\r\n", r->power.version);
            break;
        case 1:
            if (r->power.numeric_status_confirmed)
                (void)snprintf(text, sizeof(text), "# POWER,battery_mv=%lu,motor_mv=%lu,temp_c=%u,fault_switch_bits=0x%06lX,type03_current=UNCONFIRMED\r\n",
                    (unsigned long)r->power.battery_mv, (unsigned long)r->power.motor_mv,
                    r->power.temperature_c, (unsigned long)r->power.fault_and_switch_bits);
            else
                (void)snprintf(text, sizeof(text), "# POWER,temp_c=%u,status03_numeric=UNCONFIRMED_ENDIAN,type03_current=UNCONFIRMED; see raw RX\r\n",
                    r->power.temperature_c);
            break;
        case 2:
            if (r->power.numeric_status_confirmed)
                (void)snprintf(text, sizeof(text), "# POWER,branch_current_ma=%lu/%lu/%lu/%lu\r\n",
                    (unsigned long)r->power.branch_current_ma[0], (unsigned long)r->power.branch_current_ma[1],
                    (unsigned long)r->power.branch_current_ma[2], (unsigned long)r->power.branch_current_ma[3]);
            else
                (void)snprintf(text, sizeof(text), "# POWER,status04_numeric=UNCONFIRMED_ENDIAN; see raw RX\r\n");
            break;
        default: {
            const unsigned slot = (unsigned)index - 3U;
            if (slot >= POWER_PARAMETER_COUNT) return;
            const PowerParameter *p = &r->power.parameters[slot];
            if (slot < 6U)
                (void)snprintf(text, sizeof(text),
                    "# POWER,param=0x%04X,name=%s,value_u8=%u,raw=%02X %02X %02X %02X,tail_nonzero=%u,numeric_valid=%u,id_mismatch=%u\r\n",
                    power_parameter_indices[slot], power_parameter_names[slot], p->value_u8,
                    p->raw[0], p->raw[1], p->raw[2], p->raw[3], p->upper_bytes_nonzero,
                    p->numeric_valid, slot == 4U && r->power.reported_id_mismatch);
            else {
                /* nano printf has no float formatting by default. Print a bounded
                   milli-scaled candidate, keep full IEEE bits for exact recovery. */
                const bool printable = p->numeric_valid && p->value_float > -1000000.0f && p->value_float < 1000000.0f;
                const long milli = printable ? (long)(p->value_float * 1000.0f) : 0L;
                (void)snprintf(text, sizeof(text),
                    "# POWER,param=0x%04X,name=%s,float_bits_le=0x%08lX,value_milli_candidate=%ld,milli_valid=%u,numeric_valid=%u,units=%s\r\n",
                    power_parameter_indices[slot], power_parameter_names[slot], (unsigned long)p->bits_le,
                    milli, printable, p->numeric_valid, slot == 6U ? "A" : slot == 7U ? "V" : "UNCONFIRMED");
            }
            break;
        }
        }
    }
    line(text);
}
void DeviceRead_Init(FDCAN_HandleTypeDef *can, UART_HandleTypeDef *uart) {
    initialized = uart_failed = reported_bus_off = false;
    serial = uart;
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_5, GPIO_PIN_RESET);
    char text[256];
    ReaderConfig config = {
        .kind = PICO_DEVICE_KIND, .power_id = PICO_POWER_ID,
        .bms_rtr_dlc = PICO_BMS_RTR_DLC, .max_attempts = 3U,
        .bms_crc_order = PICO_BMS_CRC_ORDER, .power_status_order = PICO_POWER_STATUS_ORDER,
        .timeout_ms = 500U, .interval_ms = 200U, .stale_ms = 10000U
    };
#if defined(PICO_DEVICE_DUAL)
    config.kind = READER_BMS;
    config.max_attempts = 1U; /* No automatic retry within a query. */
    config.timeout_ms = 700U;
#endif
#if defined(PICO_POWER_BAUD_TEST)
    const char *mode = "EXPLICITLY GATED BAUD TEST (boots read-only)";
#else
#if defined(PICO_DEVICE_DUAL)
    const char *mode = "READ ONLY DUAL (BMS+POWER, shared FDCAN1)";
#else
    const char *mode = "READ ONLY";
#endif
#endif
    (void)snprintf(text, sizeof(text), "# PICO device-read v1; %s; device=%s bitrate=%lu power_id=0x%02X rtr_dlc=%u crc_order=%u status_order=%u\r\n",
        mode,
#if defined(PICO_DEVICE_DUAL)
        "BMS+POWER",
#else
        config.kind == READER_BMS ? "BMS" : "POWER",
#endif
        (unsigned long)PICO_DEVICE_BITRATE,
        (unsigned)config.power_id, (unsigned)config.bms_rtr_dlc,
        (unsigned)config.bms_crc_order, (unsigned)config.power_status_order);
    line(text);
    line("# timestamps=MCU uptime ms; TX_DONE=software observation time; no automatic configuration writes\r\n");
    line("t_ms,event,channel,format,kind,id,dlc,data\r\n");
#if defined(PICO_DEVICE_DUAL)
    line("# DUAL,poll=round_robin,one_pending_total=1,min_query_gap_ms=200,timeout_ms=700,max_attempts=1,stale_ms=10000\r\n");
    ReaderConfig power_config = config;
    power_config.kind = READER_POWER;
    bool readers_ok = DualDeviceReader_Init(&g_dual_device_reader, &config, &power_config, HAL_GetTick());
    CanTransportFilter filter = CAN_FILTER_DUAL;
#else
    bool readers_ok = DeviceReader_Init(&g_device_reader, &config, HAL_GetTick());
    CanTransportFilter filter = config.kind == READER_BMS ? CAN_FILTER_BMS : CAN_FILTER_POWER;
#endif
    if (!readers_ok || !CanTransport_Init(can, PICO_DEVICE_BITRATE, filter, config.power_id, log_frame)) {
        line("# FATAL initialization failed; expected FDCAN1=PCLK1=16MHz; no requests will be sent\r\n");
        return;
    }
#if defined(PICO_POWER_BAUD_TEST)
    PowerBaudTest_Init(HAL_GetTick(), baud_log);
#endif
    next_summary = HAL_GetTick() + 5000U;
    initialized = true;
}
void DeviceRead_Step(void) {
    if (!initialized || uart_failed) {
#if defined(PICO_POWER_BAUD_TEST)
        if (initialized) (void)PowerBaudTest_Step(&g_device_reader, HAL_GetTick(), false);
#endif
        HAL_GPIO_WritePin(GPIOA, GPIO_PIN_5, GPIO_PIN_RESET);
        return;
    }
    CanTransport_Service(HAL_GetTick());
    CanFrame frame;
    /* Bound UART work per iteration; ISR never formats or writes logs. */
    for (uint8_t n = 0; n < 8U && CanTransport_Receive(&frame); ++n) {
        log_frame("RX", &frame);
#if defined(PICO_POWER_BAUD_TEST)
        PowerBaudTest_OnFrame(&frame);
#endif
#if defined(PICO_DEVICE_DUAL)
        DeviceReader *reader = frame.extended ? &g_dual_device_reader.power : &g_dual_device_reader.bms;
#else
        DeviceReader *reader = &g_device_reader;
#endif
        int index = DeviceReader_OnFrame(reader, &frame);
        if (index >= 0) sample(reader, index);
    }
    uint32_t now = HAL_GetTick();
    bool off = CanTransport_IsBusOff();
    if (off && !reported_bus_off) {
        reported_bus_off = true;
        line("# BUS_OFF latched; inspect bitrate/wiring/termination; reset after correcting fault\r\n");
    }
    /* Always age samples, even during a bus fault. */
#if defined(PICO_DEVICE_DUAL)
    if (off) DualDeviceReader_Age(&g_dual_device_reader, now);
    else DualDeviceReader_Step(&g_dual_device_reader, now, send_request, NULL);
#else
#if defined(PICO_POWER_BAUD_TEST)
    DeviceReader_Age(&g_device_reader, now);
    if (PowerBaudTest_Step(&g_device_reader, now, !uart_failed))
#endif
        DeviceReader_Step(&g_device_reader, now, send_request, NULL);
#endif
    if ((int32_t)(now - next_summary) >= 0) {
        CanTransportStats s = CanTransport_GetStats();
        char text[768], prefix[300];
#if defined(PICO_DEVICE_DUAL)
        (void)snprintf(prefix, sizeof(prefix), "# HEALTH,t_ms=%lu,device=DUAL", (unsigned long)now);
#else
        ReaderStats *r = &g_device_reader.stats;
        (void)snprintf(prefix, sizeof(prefix), "# HEALTH,t_ms=%lu,seen=0x%02lX,valid=0x%02lX,replies=%lu,invalid=%lu,ignored=%lu,query_timeouts=%lu,query_failures=%lu",
            (unsigned long)now, (unsigned long)g_device_reader.seen_mask, (unsigned long)g_device_reader.valid_mask,
            (unsigned long)r->replies, (unsigned long)r->invalid, (unsigned long)r->ignored,
            (unsigned long)r->timeouts, (unsigned long)r->query_failures);
#endif
        FDCAN_ErrorCountersTypeDef errors = {0};
        extern FDCAN_HandleTypeDef hfdcan1;
        bool counters_ok = HAL_FDCAN_GetErrorCounters(&hfdcan1, &errors) == HAL_OK;
        (void)snprintf(text, sizeof(text), "%s,tx_submit=%lu,tx_done=%lu,tx_rejected=%lu,tx_timeout=%lu,rx_fifo_lost=%lu,rx_queue_drop=%lu,rx_read_fail=%lu,rx_unsupported=%lu,tx_event_lost=%lu,tx_event_unknown=%lu,bus_off=%lu,tec=%lu,rec=%lu,counters_ok=%u\r\n",
            prefix, (unsigned long)s.tx_submitted, (unsigned long)s.tx_completed,
            (unsigned long)s.tx_rejected, (unsigned long)s.tx_timed_out,
            (unsigned long)s.rx_fifo_lost, (unsigned long)s.rx_queue_dropped,
            (unsigned long)s.rx_read_failed, (unsigned long)s.rx_unsupported,
            (unsigned long)s.tx_event_lost, (unsigned long)s.tx_event_unknown, (unsigned long)s.bus_off,
            (unsigned long)errors.TxErrorCnt, (unsigned long)errors.RxErrorCnt, counters_ok ? 1U : 0U);
        line(text);
#if defined(PICO_DEVICE_DUAL)
        DeviceReader *readers[] = {&g_dual_device_reader.bms, &g_dual_device_reader.power};
        for (uint8_t i = 0; i < 2U; ++i) {
            DeviceReader *reader = readers[i];
            ReaderStats *r = &reader->stats;
            (void)snprintf(text, sizeof(text),
                "# DEVICE_HEALTH,t_ms=%lu,device=%s,seen=0x%03lX,valid=0x%03lX,cycles=%lu,replies=%lu,invalid=%lu,ignored=%lu,query_timeouts=%lu,query_failures=%lu,tx_submit=%lu,tx_rejected=%lu,pending=%u,query_index=%u\r\n",
                (unsigned long)now, i == 0U ? "BMS" : "POWER",
                (unsigned long)reader->seen_mask, (unsigned long)reader->valid_mask,
                (unsigned long)r->cycles, (unsigned long)r->replies, (unsigned long)r->invalid,
                (unsigned long)r->ignored, (unsigned long)r->timeouts, (unsigned long)r->query_failures,
                (unsigned long)r->tx_submitted, (unsigned long)r->tx_rejected,
                (unsigned)reader->pending, (unsigned)reader->query_index);
            line(text);
        }
#endif
        next_summary = now + 5000U;
    }
    /* LD2 is only a freshness indicator, never proof of hardware validation. */
#if defined(PICO_DEVICE_DUAL)
    bool fresh = g_dual_device_reader.bms.valid_mask == 0x1FU &&
                 g_dual_device_reader.power.valid_mask == POWER_ALL_FRESH_MASK;
#else
    uint32_t all = g_device_reader.config.kind == READER_BMS ? 0x1FU : POWER_ALL_FRESH_MASK;
    bool fresh = g_device_reader.valid_mask == all;
#endif
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_5,
        !uart_failed && !off && fresh ? GPIO_PIN_SET : GPIO_PIN_RESET);
}
