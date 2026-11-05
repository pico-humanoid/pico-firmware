#include "can_bringup.h"
#include <stdio.h>
#include <string.h>

#ifndef PICO_EXTERNAL_CAN
#define PICO_EXTERNAL_CAN 0
#endif
#define FRAME_COUNT 100U
#define RX_QUEUE_SIZE 32U

typedef struct { FDCAN_RxHeaderTypeDef header; uint8_t data[64]; uint32_t ms; } RxFrame;
volatile CanTestStatus g_can_test;
static FDCAN_HandleTypeDef *bus;
static UART_HandleTypeDef *serial;
static RxFrame queue[RX_QUEUE_SIZE];
static volatile uint32_t write_pos, read_pos;
static uint8_t received[FRAME_COUNT], tx_confirmed[FRAME_COUNT];
static uint32_t started, start_ms, next_tx_ms, next_sequence, last_blink;

static void log_line(const char *text) {
    if (HAL_UART_Transmit(serial, (const uint8_t *)text, (uint16_t)strlen(text), 100) != HAL_OK)
        g_can_test.fatal = 3;
}

static void log_frame(uint32_t ms, const char *event, uint32_t id, const uint8_t data[8]) {
    char line[160];
    (void)snprintf(line, sizeof(line), "%lu,%s,STD,0x%03lX,8,%02X %02X %02X %02X %02X %02X %02X %02X\r\n",
        (unsigned long)ms, event, (unsigned long)id,
        data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7]);
    log_line(line);
}

static void fail(uint32_t code) {
    g_can_test.fatal = code;
    g_can_test.result = 2;
}

void CanTest_Init(FDCAN_HandleTypeDef *can, UART_HandleTypeDef *uart) {
    bus = can;
    serial = uart;
    log_line("# PICO G474 CAN bring-up; timestamps are board uptime milliseconds\r\n");
    log_line(PICO_EXTERNAL_CAN ? "# mode=EXTERNAL_NORMAL; wait for first valid 0x321 frame\r\n"
                              : "# mode=INTERNAL_LOOPBACK; no transceiver required\r\n");
    log_line("t_ms,event,format,id,dlc,data\r\n");
    if (HAL_RCC_GetPCLK1Freq() != 16000000U || can->Init.ClockDivider != FDCAN_CLOCK_DIV1) {
        fail(1); log_line("# ERROR expected FDCAN=PCLK1=16MHz and clock divider=1\r\n"); return;
    }
    const uint32_t mode = PICO_EXTERNAL_CAN ? FDCAN_MODE_NORMAL : FDCAN_MODE_INTERNAL_LOOPBACK;
    if (can->Init.Mode != mode) {
        if (HAL_FDCAN_DeInit(can) != HAL_OK) { fail(2); return; }
        can->Init.Mode = mode;
        if (HAL_FDCAN_Init(can) != HAL_OK) { fail(2); return; }
    }
    FDCAN_FilterTypeDef filter = {0};
    filter.IdType = FDCAN_STANDARD_ID;
    filter.FilterIndex = 0;
    filter.FilterType = FDCAN_FILTER_MASK;
    filter.FilterConfig = FDCAN_FILTER_TO_RXFIFO0;
    filter.FilterID1 = PICO_EXTERNAL_CAN ? 0x321U : 0x123U;
    filter.FilterID2 = 0x7FFU;
    if (HAL_FDCAN_ConfigFilter(can, &filter) != HAL_OK ||
        HAL_FDCAN_ConfigGlobalFilter(can, FDCAN_REJECT, FDCAN_REJECT,
                                    FDCAN_REJECT_REMOTE, FDCAN_REJECT_REMOTE) != HAL_OK ||
        HAL_FDCAN_ActivateNotification(can, FDCAN_IT_RX_FIFO0_NEW_MESSAGE |
            FDCAN_IT_RX_FIFO0_MESSAGE_LOST | FDCAN_IT_BUS_OFF | FDCAN_IT_TX_EVT_FIFO_ELT_LOST, 0) != HAL_OK ||
        HAL_FDCAN_Start(can) != HAL_OK) {
        fail(2); log_line("# ERROR FDCAN start/filter/notification\r\n"); return;
    }
    if (!PICO_EXTERNAL_CAN) { started = 1; start_ms = HAL_GetTick() + 2000U; next_tx_ms = start_ms; }
}

void HAL_FDCAN_RxFifo0Callback(FDCAN_HandleTypeDef *can, uint32_t flags) {
    if (can != bus) return;
    if ((flags & FDCAN_IT_RX_FIFO0_MESSAGE_LOST) != 0U) ++g_can_test.rx_fifo_lost_events;
    while (HAL_FDCAN_GetRxFifoFillLevel(can, FDCAN_RX_FIFO0) != 0U) {
        RxFrame frame;
        frame.ms = HAL_GetTick();
        if (HAL_FDCAN_GetRxMessage(can, FDCAN_RX_FIFO0, &frame.header, frame.data) != HAL_OK) {
            ++g_can_test.rx_read_failed; break;
        }
        uint32_t next = (write_pos + 1U) % RX_QUEUE_SIZE;
        if (next == read_pos) { ++g_can_test.rx_queue_dropped; continue; }
        queue[write_pos] = frame;
        __DMB();
        write_pos = next;
    }
}

void HAL_FDCAN_ErrorStatusCallback(FDCAN_HandleTypeDef *can, uint32_t flags) {
    if (can == bus && (flags & FDCAN_IT_BUS_OFF) != 0U) ++g_can_test.bus_off_events;
}

void HAL_FDCAN_TxEventFifoCallback(FDCAN_HandleTypeDef *can, uint32_t flags) {
    if (can == bus && (flags & FDCAN_IT_TX_EVT_FIFO_ELT_LOST) != 0U) ++g_can_test.tx_event_lost_events;
}

void CanTest_Step(void) {
    uint32_t now = HAL_GetTick();
    if (g_can_test.result == 0 && g_can_test.fatal != 0) g_can_test.result = 2;
    if (g_can_test.result != 0) {
        if (g_can_test.result == 1) HAL_GPIO_WritePin(GPIOA, GPIO_PIN_5, GPIO_PIN_SET);
        else if (now - last_blink >= 150U) { last_blink = now; HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_5); }
        return;
    }
    while (read_pos != write_pos) {
        RxFrame frame = queue[read_pos];
        __DMB();
        read_pos = (read_pos + 1U) % RX_QUEUE_SIZE;
        const uint8_t internal_tail[7] = {0x22,0x33,0x44,0x55,0x66,0x77,0x88};
        const uint8_t external_tail[7] = {0x88,0x77,0x66,0x55,0x44,0x33,0x22};
        if (frame.header.IdType != FDCAN_STANDARD_ID || frame.header.RxFrameType != FDCAN_DATA_FRAME ||
            frame.header.FDFormat != FDCAN_CLASSIC_CAN || frame.header.DataLength != FDCAN_DLC_BYTES_8 ||
            frame.header.Identifier != (PICO_EXTERNAL_CAN ? 0x321U : 0x123U) ||
            frame.data[0] >= FRAME_COUNT || memcmp(frame.data + 1, PICO_EXTERNAL_CAN ? external_tail : internal_tail, 7) != 0) {
            ++g_can_test.rx_invalid; log_line("# INVALID received frame\r\n"); continue;
        }
        if (!started) { started = 1; start_ms = now; next_tx_ms = now; }
        if (received[frame.data[0]]) ++g_can_test.rx_duplicate;
        else { received[frame.data[0]] = 1; ++g_can_test.rx_unique; }
        log_frame(frame.ms, "RX", frame.header.Identifier, frame.data);
    }
    /* Reading the hardware fill field avoids treating an empty Tx event FIFO as a HAL error. */
    while ((bus->Instance->TXEFS & FDCAN_TXEFS_EFFL) != 0U) {
        FDCAN_TxEventFifoTypeDef event;
        if (HAL_FDCAN_GetTxEvent(bus, &event) != HAL_OK) { fail(4); return; }
        uint32_t seq = event.MessageMarker;
        if (event.Identifier != 0x123U || seq >= FRAME_COUNT || tx_confirmed[seq]) { fail(4); return; }
        tx_confirmed[seq] = 1;
        ++g_can_test.tx_completed;
        uint8_t data[8] = {(uint8_t)seq,0x22,0x33,0x44,0x55,0x66,0x77,0x88};
        log_frame(HAL_GetTick(), "TX_DONE", 0x123U, data);
    }
    if (started && next_sequence < FRAME_COUNT && (int32_t)(now - next_tx_ms) >= 0) {
        FDCAN_TxHeaderTypeDef header = {0};
        header.Identifier = 0x123U;
        header.IdType = FDCAN_STANDARD_ID;
        header.TxFrameType = FDCAN_DATA_FRAME;
        header.DataLength = FDCAN_DLC_BYTES_8;
        header.ErrorStateIndicator = FDCAN_ESI_ACTIVE;
        header.BitRateSwitch = FDCAN_BRS_OFF;
        header.FDFormat = FDCAN_CLASSIC_CAN;
        header.TxEventFifoControl = FDCAN_STORE_TX_EVENTS;
        header.MessageMarker = next_sequence;
        uint8_t data[8] = {(uint8_t)next_sequence,0x22,0x33,0x44,0x55,0x66,0x77,0x88};
        if (HAL_FDCAN_GetTxFifoFreeLevel(bus) != 0U && HAL_FDCAN_AddMessageToTxFifoQ(bus, &header, data) == HAL_OK) {
            ++g_can_test.tx_submitted;
            log_frame(HAL_GetTick(), "TX_SUBMIT", 0x123U, data);
        } else ++g_can_test.tx_submit_failed;
        ++next_sequence;
        next_tx_ms = now + 100U;
    }
    if (now - last_blink >= 500U) { last_blink = now; HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_5); }
    if (started && (int32_t)(now - start_ms) >= 13000) {
        FDCAN_ErrorCountersTypeDef errors = {0};
        FDCAN_ProtocolStatusTypeDef status = {0};
        if (HAL_FDCAN_GetErrorCounters(bus, &errors) != HAL_OK || HAL_FDCAN_GetProtocolStatus(bus, &status) != HAL_OK)
            g_can_test.fatal = 5;
        uint32_t pass = g_can_test.tx_submitted == FRAME_COUNT && g_can_test.tx_completed == FRAME_COUNT &&
            g_can_test.rx_unique == FRAME_COUNT && g_can_test.rx_duplicate == 0 && g_can_test.rx_invalid == 0 &&
            g_can_test.tx_submit_failed == 0 && g_can_test.rx_fifo_lost_events == 0 &&
            g_can_test.rx_queue_dropped == 0 && g_can_test.rx_read_failed == 0 &&
            g_can_test.tx_event_lost_events == 0 && g_can_test.bus_off_events == 0 && g_can_test.fatal == 0 &&
            errors.TxErrorCnt == 0 && errors.RxErrorCnt == 0 && status.BusOff == 0;
        char summary[512];
        (void)snprintf(summary, sizeof(summary),
            "# RESULT=%s tx_submit=%lu tx_done=%lu rx_unique=%lu rx_missing=%lu rx_duplicate=%lu rx_invalid=%lu tx_submit_failed=%lu rx_fifo_lost_events=%lu rx_queue_dropped=%lu rx_read_failed=%lu tx_event_lost_events=%lu bus_off_events=%lu fatal=%lu tec=%lu rec=%lu\r\n",
            pass ? "PASS" : "FAIL", (unsigned long)g_can_test.tx_submitted, (unsigned long)g_can_test.tx_completed,
            (unsigned long)g_can_test.rx_unique, (unsigned long)(FRAME_COUNT-g_can_test.rx_unique),
            (unsigned long)g_can_test.rx_duplicate, (unsigned long)g_can_test.rx_invalid,
            (unsigned long)g_can_test.tx_submit_failed, (unsigned long)g_can_test.rx_fifo_lost_events,
            (unsigned long)g_can_test.rx_queue_dropped, (unsigned long)g_can_test.rx_read_failed,
            (unsigned long)g_can_test.tx_event_lost_events, (unsigned long)g_can_test.bus_off_events,
            (unsigned long)g_can_test.fatal, (unsigned long)errors.TxErrorCnt, (unsigned long)errors.RxErrorCnt);
        log_line(summary);
        g_can_test.result = pass && g_can_test.fatal == 0 ? 1U : 2U;
    }
}
