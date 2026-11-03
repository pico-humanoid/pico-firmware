/* Deliberately linked only by PICO_APP=PowerBaud. No reset, output control,
 * address write, default restore, automatic baud scan or write retry. */
#include "power_baud_test.h"
#include "transport/can_transport.h"
#include <stdio.h>
#include <string.h>

#if PICO_DEVICE_KIND != 1 || !defined(PICO_POWER_BAUD_TEST)
#error "Power baud test must not be linked into an ordinary reader"
#endif
#if !((PICO_DEVICE_BITRATE == 1000000 && PICO_POWER_BAUD_TARGET == 500000) || \
      (PICO_DEVICE_BITRATE == 500000 && PICO_POWER_BAUD_TARGET == 1000000))
#error "Only explicit 1M <-> 500K transitions are permitted"
#endif

volatile uint32_t g_power_baud_command;
volatile uint32_t g_power_baud_stage;
static uint32_t started, stage_at, read_at;
static bool write_done, write_timeout, read_received;
static uint8_t read_code;
static PowerBaudLog logger;

static uint8_t baud_code(uint32_t bitrate) { return bitrate == 1000000U ? 1U : 2U; }
static void stop(const char *why) {
    g_power_baud_stage = POWER_BAUD_STOPPED;
    if (logger != NULL) (void)logger(why);
}
static bool note(const char *text) {
    if (logger != NULL && logger(text)) return true;
    g_power_baud_stage = POWER_BAUD_STOPPED;
    return false;
}
void PowerBaudTest_Init(uint32_t now, PowerBaudLog log) {
    g_power_baud_command = 0U;
    g_power_baud_stage = POWER_BAUD_IDLE;
    started = stage_at = now;
    write_done = write_timeout = read_received = false;
    read_code = 0U;
    logger = log;
    char text[320];
#if defined(PICO_POWER_BAUD_FORCE_OPERATOR) && PICO_POWER_BAUD_FORCE_OPERATOR
    (void)snprintf(text, sizeof(text),
        "# BAUD_TEST,stage=IDLE,FORCE_OPERATOR=1,baseline_min_ms=%lu,arm_window_ms=%lu; no readiness guarantee; SWD ARM then COMMIT required; ONE write submission only, no retry/restart\r\n",
        (unsigned long)POWER_BAUD_BASELINE_MS, (unsigned long)POWER_BAUD_ARM_MS);
#elif defined(PICO_POWER_BAUD_ALLOW_QUERY_TIMEOUTS) && PICO_POWER_BAUD_ALLOW_QUERY_TIMEOUTS
    (void)snprintf(text, sizeof(text),
        "# BAUD_TEST,stage=IDLE,default=READ_ONLY,baseline_min_ms=%lu,arm_window_ms=%lu,historical_timeout_override=EXPLICIT_OPERATOR; SWD ARM then COMMIT required; one write only, no retry/restart\r\n",
        (unsigned long)POWER_BAUD_BASELINE_MS, (unsigned long)POWER_BAUD_ARM_MS);
#else
    (void)snprintf(text, sizeof(text),
        "# BAUD_TEST,stage=IDLE,default=READ_ONLY,baseline_min_ms=%lu,arm_window_ms=%lu; SWD ARM then COMMIT required; no automatic write or restart\r\n",
        (unsigned long)POWER_BAUD_BASELINE_MS, (unsigned long)POWER_BAUD_ARM_MS);
#endif
    (void)note(text);
}
#if !(defined(PICO_POWER_BAUD_FORCE_OPERATOR) && PICO_POWER_BAUD_FORCE_OPERATOR)
static bool fresh(const DeviceReader *r, uint32_t now) {
    if (r->config.kind != READER_POWER || r->valid_mask != POWER_ALL_FRESH_MASK ||
        r->seen_mask != POWER_ALL_FRESH_MASK) return false;
    for (uint8_t i = 0U; i < POWER_QUERY_COUNT; ++i)
        if ((uint32_t)(now - r->last_ok_ms[i]) > r->config.stale_ms) return false;
    return true;
}
static bool clean(const DeviceReader *r) {
    CanTransportStats s = CanTransport_GetStats();
    FDCAN_ErrorCountersTypeDef e = {0};
    extern FDCAN_HandleTypeDef hfdcan1;
    return HAL_FDCAN_GetErrorCounters(&hfdcan1, &e) == HAL_OK &&
        e.TxErrorCnt == 0U && e.RxErrorCnt == 0U && !CanTransport_IsBusOff() &&
#if defined(PICO_POWER_BAUD_ALLOW_QUERY_TIMEOUTS) && PICO_POWER_BAUD_ALLOW_QUERY_TIMEOUTS
        /* Explicit operator override: historical application reply and Tx-event
         * completion timeouts remain logged but do not block this one-shot write.
         * Current CAN counters, freshness, query failures, bus-off and every
         * other transport fault still block it. */
        r->stats.query_failures == 0U &&
#else
        r->stats.timeouts == 0U && r->stats.query_failures == 0U &&
#endif
        r->stats.invalid == 0U && r->stats.tx_rejected == 0U &&
        s.tx_rejected == 0U &&
#if !(defined(PICO_POWER_BAUD_ALLOW_QUERY_TIMEOUTS) && PICO_POWER_BAUD_ALLOW_QUERY_TIMEOUTS)
        s.tx_timed_out == 0U &&
#endif
        s.rx_fifo_lost == 0U &&
        s.rx_queue_dropped == 0U && s.rx_read_failed == 0U && s.rx_unsupported == 0U &&
        s.tx_event_lost == 0U && s.tx_event_unknown == 0U && s.bus_off == 0U;
}
static bool ready(const DeviceReader *r, uint32_t now) {
    return (uint32_t)(now - started) >= POWER_BAUD_BASELINE_MS &&
        r->stats.cycles >= 2U && fresh(r, now) && clean(r) &&
        r->power.can_baud_code == baud_code(PICO_DEVICE_BITRATE);
}
#endif
static bool operator_permits_write(const DeviceReader *r, uint32_t now) {
#if defined(PICO_POWER_BAUD_FORCE_OPERATOR) && PICO_POWER_BAUD_FORCE_OPERATOR
    (void)r;
    (void)now;
    return true;
#else
    return ready(r, now);
#endif
}
void PowerBaudTest_OnTxEvent(const char *event, const CanFrame *frame) {
    if (g_power_baud_stage != POWER_BAUD_WRITE_WAIT ||
        frame->id != (0x08000000UL | PICO_POWER_ID)) return;
    if (strcmp(event, "TX_DONE") == 0) write_done = true;
    if (strcmp(event, "TX_TIMEOUT") == 0) write_timeout = true;
}
void PowerBaudTest_OnFrame(const CanFrame *f) {
    /* Type03 is shared status, not a unique write acknowledgement. */
    if ((g_power_baud_stage == POWER_BAUD_WRITE_WAIT ||
         g_power_baud_stage == POWER_BAUD_READ_WAIT) &&
        f->extended && !f->remote && f->dlc == 8U &&
        ((f->id >> 16) & 0xFFU) == PICO_POWER_ID &&
        ((f->id >> 24) & 0x1FU) == 3U &&
        (uint32_t)(f->timestamp_ms - stage_at) < 1500U) {
        (void)note("# BAUD_TEST,type03_candidate=1; shared status after write, NOT unique ACK or persistence proof\r\n");
    }
    if (g_power_baud_stage != POWER_BAUD_READ_WAIT || !f->extended || f->remote ||
        f->dlc != 8U || ((f->id >> 16) & 0xFFU) != PICO_POWER_ID ||
        ((f->id >> 24) & 0x1FU) != 7U || f->data[0] != 1U || f->data[1] != 0x60U ||
        (uint32_t)(f->timestamp_ms - read_at) >= 1000U) return;
    read_code = f->data[4];
    read_received = true;
}
bool PowerBaudTest_Step(DeviceReader *r, uint32_t now, bool uart_ok) {
    uint32_t command = g_power_baud_command;
    g_power_baud_command = 0U; /* consume once; a held/old token never repeats */
    if (!uart_ok) { g_power_baud_stage = POWER_BAUD_STOPPED; return false; }
    if (command == POWER_BAUD_CANCEL) {
        stop("# BAUD_TEST,stage=STOPPED,reason=operator_cancel; any already submitted frame may still transmit; no rollback performed\r\n");
        return false;
    }
    if (command != 0U && command != POWER_BAUD_ARM && command != POWER_BAUD_COMMIT) {
        stop("# BAUD_TEST,stage=STOPPED,reason=invalid_command\r\n"); return false;
    }
    if (g_power_baud_stage == POWER_BAUD_IDLE) {
        if (command == POWER_BAUD_COMMIT) {
            stop("# BAUD_TEST,stage=STOPPED,reason=commit_without_arm; no write\r\n"); return false;
        }
        if (command == POWER_BAUD_ARM) {
            if (!operator_permits_write(r, now)) {
                (void)note("# BAUD_TEST,stage=IDLE,arm=REJECTED,reason=baseline_not_ready; no write\r\n");
                return g_power_baud_stage == POWER_BAUD_IDLE;
            }
            g_power_baud_stage = POWER_BAUD_DRAIN;
            stage_at = now;
            if (!note("# BAUD_TEST,stage=DRAIN; polling paused, waiting for read request and Tx completion\r\n")) return false;
        } else {
#if defined(PICO_POWER_BAUD_FORCE_OPERATOR) && PICO_POWER_BAUD_FORCE_OPERATOR
            return false; /* Direct write diagnosis: no pre-write read traffic. */
#else
            return true;
#endif
        }
    } else if (command == POWER_BAUD_ARM ||
               (command == POWER_BAUD_COMMIT && g_power_baud_stage != POWER_BAUD_ARMED)) {
        stop("# BAUD_TEST,stage=STOPPED,reason=command_in_wrong_stage; no additional write\r\n"); return false;
    }
    if (g_power_baud_stage == POWER_BAUD_DRAIN) {
        CanTransportStats s = CanTransport_GetStats();
        if (!operator_permits_write(r, now) || (uint32_t)(now - stage_at) >= 1000U) {
            stop("# BAUD_TEST,stage=STOPPED,reason=drain_failed; no write\r\n");
        } else if (!r->pending && s.tx_submitted == s.tx_completed) {
            g_power_baud_stage = POWER_BAUD_ARMED;
            stage_at = now;
            (void)note("# BAUD_TEST,stage=ARMED; COMMIT must arrive within 5000ms; no write yet\r\n");
        }
    } else if (g_power_baud_stage == POWER_BAUD_ARMED) {
        if ((uint32_t)(now - stage_at) >= POWER_BAUD_ARM_MS || !operator_permits_write(r, now) || r->pending) {
            stop("# BAUD_TEST,stage=STOPPED,reason=arm_expired_or_baseline_changed; no write\r\n");
        } else if (command == POWER_BAUD_COMMIT) {
            /* Consume permission BEFORE logging/submission; even a HAL rejection
               or missing confirmation cannot cause an automatic second write. */
            g_power_baud_stage = POWER_BAUD_WRITE_WAIT;
            stage_at = now;
            if (!note("# BAUD_TEST,stage=WRITE_INTENT,index=0x6001; ONE submission only, no retry, no reboot; wait for separate power-cycle instruction\r\n")) return false;
            CanFrame frame = {.id = 0x08000000UL | PICO_POWER_ID, .extended = true, .dlc = 8U,
                .data = {1U, 0x60U, 0U, 0U, 0U, 0U, 0U, 0U}};
            frame.data[4] = baud_code(PICO_POWER_BAUD_TARGET);
            if (!CanTransport_Submit(&frame, now))
                stop("# BAUD_TEST,stage=STOPPED,reason=write_submit_rejected; NOT retried\r\n");
        }
    } else if (g_power_baud_stage == POWER_BAUD_WRITE_WAIT) {
        if (write_timeout || CanTransport_IsBusOff() || (uint32_t)(now - stage_at) >= 1000U) {
            stop("# BAUD_TEST,stage=STOPPED,reason=write_completion_unconfirmed; do NOT blindly retry\r\n");
        } else if (write_done) {
            if (!note("# BAUD_TEST,write_tx_done=1; proves controller completion only, NOT parameter persistence or new bitrate\r\n")) return false;
            CanFrame query;
            if (!Power_BuildQuery(PICO_POWER_ID, 3U, &query)) {
                stop("# BAUD_TEST,stage=STOPPED,reason=readback_build_failed\r\n"); return false;
            }
            g_power_baud_stage = POWER_BAUD_READ_WAIT;
            read_at = now;
            if (!CanTransport_Submit(&query, now))
                stop("# BAUD_TEST,stage=STOPPED,reason=readback_submit_rejected; no write retry\r\n");
        }
    } else if (g_power_baud_stage == POWER_BAUD_READ_WAIT) {
        if (read_received) {
            char text[240];
            (void)snprintf(text, sizeof(text), "# BAUD_TEST,stage=DONE,old_link_readback_code=%u,target_code=%u; NOT a migration PASS; polling stopped, manual power cycle and target-rate validation required\r\n",
                (unsigned)read_code, (unsigned)baud_code(PICO_POWER_BAUD_TARGET));
            g_power_baud_stage = POWER_BAUD_DONE;
            (void)note(text);
        } else if ((uint32_t)(now - read_at) >= 1000U || CanTransport_IsBusOff()) {
            stop("# BAUD_TEST,stage=STOPPED,reason=old_link_readback_unconfirmed; new bitrate NOT proven, no retry\r\n");
        }
    }
    return false;
}
