#include "can_transport.h"
#include <string.h>

#define RX_QUEUE_SIZE 32U
#define TX_SLOTS 3U
#define TX_DEADLINE_MS 300U

typedef struct {
    bool used, cancelling;
    uint8_t marker;
    uint32_t buffer_mask, submitted_at, serial;
    CanFrame frame;
} TxSlot;
static FDCAN_HandleTypeDef *bus;
static CanTransportLog logger;
static CanFrame rx_queue[RX_QUEUE_SIZE];
static volatile uint32_t rx_write, rx_read;
static volatile CanTransportStats stats;
static TxSlot tx_slots[TX_SLOTS];
static uint8_t next_marker;
static uint32_t tx_serial;
static bool ready;

bool CanTransport_Init(FDCAN_HandleTypeDef *handle, uint32_t bitrate,
                       CanTransportFilter filter, uint8_t power_id, CanTransportLog log) {
    if (handle == NULL || handle->Instance != FDCAN1 ||
        (bitrate != 500000U && bitrate != 1000000U) ||
        (filter != CAN_FILTER_BMS && filter != CAN_FILTER_POWER && filter != CAN_FILTER_DUAL) ||
        HAL_RCC_GetPCLK1Freq() != 16000000U) return false;
    ready = false;
    bus = NULL;
    if (HAL_FDCAN_DeInit(handle) != HAL_OK) return false;
    memset((void *)&stats, 0, sizeof(stats));
    memset(tx_slots, 0, sizeof(tx_slots));
    rx_write = rx_read = 0;
    next_marker = 0;
    tx_serial = 0;
    logger = log;
    handle->Init.ClockDivider = FDCAN_CLOCK_DIV1;
    handle->Init.FrameFormat = FDCAN_FRAME_CLASSIC;
    handle->Init.Mode = FDCAN_MODE_NORMAL;
    /* Bound retries in DeviceReader, not indefinitely in the controller. */
    handle->Init.AutoRetransmission = DISABLE;
    handle->Init.TransmitPause = DISABLE;
    handle->Init.ProtocolException = DISABLE;
    handle->Init.NominalPrescaler = bitrate == 500000U ? 2U : 1U;
    handle->Init.NominalSyncJumpWidth = 2U;
    handle->Init.NominalTimeSeg1 = 13U;
    handle->Init.NominalTimeSeg2 = 2U;
    handle->Init.StdFiltersNbr = (filter == CAN_FILTER_BMS || filter == CAN_FILTER_DUAL) ? 1U : 0U;
    handle->Init.ExtFiltersNbr = (filter == CAN_FILTER_POWER || filter == CAN_FILTER_DUAL) ? 1U : 0U;
    handle->Init.TxFifoQueueMode = FDCAN_TX_FIFO_OPERATION;
    if (HAL_FDCAN_Init(handle) != HAL_OK) return false;
    FDCAN_FilterTypeDef f = {0};
    f.FilterIndex = 0;
    f.FilterConfig = FDCAN_FILTER_TO_RXFIFO0;
    if (filter == CAN_FILTER_BMS || filter == CAN_FILTER_DUAL) {
        f.IdType = FDCAN_STANDARD_ID;
        f.FilterType = FDCAN_FILTER_RANGE;
        f.FilterID1 = 0x100U;
        f.FilterID2 = 0x105U;
        if (HAL_FDCAN_ConfigFilter(handle, &f) != HAL_OK) return false;
    }
    if (filter == CAN_FILTER_POWER || filter == CAN_FILTER_DUAL) {
        /* Standard and extended filter lists are independent in the FDCAN
           message RAM; both use their own index 0. */
        FDCAN_FilterTypeDef ext = {0};
        ext.FilterIndex = 0;
        ext.FilterConfig = FDCAN_FILTER_TO_RXFIFO0;
        ext.IdType = FDCAN_EXTENDED_ID;
        ext.FilterType = FDCAN_FILTER_MASK;
        ext.FilterID1 = (uint32_t)power_id << 16;
        ext.FilterID2 = 0x00FF0000U;
        if (HAL_FDCAN_ConfigFilter(handle, &ext) != HAL_OK) return false;
    }
    if (HAL_FDCAN_ConfigGlobalFilter(handle, FDCAN_REJECT, FDCAN_REJECT,
                                    FDCAN_REJECT_REMOTE, FDCAN_REJECT_REMOTE) != HAL_OK) return false;
    bus = handle;
    if (HAL_FDCAN_ActivateNotification(handle, FDCAN_IT_RX_FIFO0_NEW_MESSAGE |
        FDCAN_IT_RX_FIFO0_MESSAGE_LOST | FDCAN_IT_BUS_OFF | FDCAN_IT_TX_EVT_FIFO_ELT_LOST, 0) != HAL_OK ||
        HAL_FDCAN_Start(handle) != HAL_OK) { bus = NULL; return false; }
    ready = true;
    return true;
}
bool CanTransport_Submit(const CanFrame *frame, uint32_t now) {
    if (!ready || stats.bus_off != 0U || !CanFrame_IsValid(frame)) { ++stats.tx_rejected; return false; }
    /* Drain completions before admitting more work (main context only). */
    CanTransport_Service(now);
    uint8_t slot;
    for (slot = 0; slot < TX_SLOTS; ++slot) if (!tx_slots[slot].used) break;
    if (slot == TX_SLOTS || HAL_FDCAN_GetTxFifoFreeLevel(bus) == 0U) { ++stats.tx_rejected; return false; }
    FDCAN_TxHeaderTypeDef header = {0};
    header.Identifier = frame->id;
    header.IdType = frame->extended ? FDCAN_EXTENDED_ID : FDCAN_STANDARD_ID;
    header.TxFrameType = frame->remote ? FDCAN_REMOTE_FRAME : FDCAN_DATA_FRAME;
    /* HAL G4 V1.6.3 represents DLC 0..8 as unshifted 0..8, unlike some other HALs. */
    header.DataLength = frame->dlc;
    header.ErrorStateIndicator = FDCAN_ESI_ACTIVE;
    header.BitRateSwitch = FDCAN_BRS_OFF;
    header.FDFormat = FDCAN_CLASSIC_CAN;
    header.TxEventFifoControl = FDCAN_STORE_TX_EVENTS;
    /* Markers may wrap, but must not collide with any live transmission. */
    bool collision;
    do {
        collision = false;
        for (uint8_t i = 0; i < TX_SLOTS; ++i)
            if (tx_slots[i].used && tx_slots[i].marker == next_marker) collision = true;
        if (collision) ++next_marker;
    } while (collision);
    header.MessageMarker = next_marker++;
    uint8_t payload[8] = {0};
    if (!frame->remote) memcpy(payload, frame->data, frame->dlc);
    if (HAL_FDCAN_AddMessageToTxFifoQ(bus, &header, payload) != HAL_OK) { ++stats.tx_rejected; return false; }
    TxSlot *s = &tx_slots[slot];
    s->used = true;
    s->cancelling = false;
    s->marker = (uint8_t)header.MessageMarker;
    s->buffer_mask = HAL_FDCAN_GetLatestTxFifoQRequestBuffer(bus);
    s->submitted_at = now;
    s->serial = tx_serial++;
    s->frame = *frame;
    s->frame.timestamp_ms = now;
    ++stats.tx_submitted;
    if (logger != NULL) logger("TX_SUBMIT", &s->frame);
    return true;
}
void CanTransport_Service(uint32_t now) {
    if (!ready) return;
    /* Only main consumes Tx events; ISR records overflow but never logs UART. */
    for (uint8_t n = 0; n < TX_SLOTS && (bus->Instance->TXEFS & FDCAN_TXEFS_EFFL) != 0U; ++n) {
        FDCAN_TxEventFifoTypeDef event = {0};
        if (HAL_FDCAN_GetTxEvent(bus, &event) != HAL_OK) { ++stats.tx_event_unknown; break; }
        bool found = false;
        for (uint8_t i = 0; i < TX_SLOTS; ++i) {
            TxSlot *s = &tx_slots[i];
            if (!s->used || s->marker != event.MessageMarker || s->frame.id != event.Identifier) continue;
            found = true;
            ++stats.tx_completed;
            CanFrame completed = s->frame;
            completed.timestamp_ms = now; /* service time, not hardware Tx timestamp */
            s->used = false;
            if (logger != NULL) logger("TX_DONE", &completed);
            break;
        }
        if (!found) ++stats.tx_event_unknown;
    }
    for (uint8_t i = 0; i < TX_SLOTS; ++i) {
        TxSlot *s = &tx_slots[i];
        if (!s->used || (uint32_t)(now - s->submitted_at) < TX_DEADLINE_MS) continue;
        if (!s->cancelling) {
            s->cancelling = true;
            ++stats.tx_timed_out;
            CanFrame expired = s->frame;
            expired.timestamp_ms = now;
            if (logger != NULL) logger("TX_TIMEOUT", &expired);
        }
        /* A hardware buffer can be reused before its older Tx event is read
           (or if that event was lost). Never abort a newer frame using an old
           frame's saved buffer mask. Iteration order is not submission order. */
        bool newer_owner = false;
        for (uint8_t j = 0; j < TX_SLOTS; ++j) {
            if (j != i && tx_slots[j].used && tx_slots[j].buffer_mask == s->buffer_mask &&
                (int32_t)(tx_slots[j].serial - s->serial) > 0)
                newer_owner = true;
        }
        if (newer_owner || HAL_FDCAN_IsTxBufferMessagePending(bus, s->buffer_mask) == 0U)
            s->used = false;
        else
            (void)HAL_FDCAN_AbortTxRequest(bus, s->buffer_mask);
    }
}
bool CanTransport_Receive(CanFrame *frame) {
    if (frame == NULL || rx_read == rx_write) return false;
    __DMB();
    *frame = rx_queue[rx_read];
    __DMB();
    rx_read = (rx_read + 1U) % RX_QUEUE_SIZE;
    return true;
}
CanTransportStats CanTransport_GetStats(void) {
    uint32_t irq = __get_PRIMASK();
    __disable_irq();
    CanTransportStats copy = stats;
    __set_PRIMASK(irq);
    return copy;
}
bool CanTransport_IsBusOff(void) { return stats.bus_off != 0U; }
void HAL_FDCAN_RxFifo0Callback(FDCAN_HandleTypeDef *handle, uint32_t flags) {
    if (handle != bus) return;
    if (flags & FDCAN_IT_RX_FIFO0_MESSAGE_LOST) ++stats.rx_fifo_lost;
    while (HAL_FDCAN_GetRxFifoFillLevel(handle, FDCAN_RX_FIFO0) != 0U) {
        FDCAN_RxHeaderTypeDef header = {0};
        uint8_t data[64] = {0}; /* HAL can copy FD payload before we reject the frame. */
        const uint32_t received_at = HAL_GetTick();
        if (HAL_FDCAN_GetRxMessage(handle, FDCAN_RX_FIFO0, &header, data) != HAL_OK) {
            ++stats.rx_read_failed; break;
        }
        if (header.FDFormat != FDCAN_CLASSIC_CAN || header.DataLength > 8U) { ++stats.rx_unsupported; continue; }
        CanFrame frame = {.id = header.Identifier, .timestamp_ms = received_at,
            .extended = header.IdType == FDCAN_EXTENDED_ID,
            .remote = header.RxFrameType == FDCAN_REMOTE_FRAME, .dlc = (uint8_t)header.DataLength};
        if (!CanFrame_IsValid(&frame)) { ++stats.rx_unsupported; continue; }
        if (!frame.remote) memcpy(frame.data, data, frame.dlc);
        ++stats.rx_received;
        uint32_t next = (rx_write + 1U) % RX_QUEUE_SIZE;
        if (next == rx_read) { ++stats.rx_queue_dropped; continue; }
        rx_queue[rx_write] = frame;
        __DMB();
        rx_write = next;
    }
}
void HAL_FDCAN_ErrorStatusCallback(FDCAN_HandleTypeDef *handle, uint32_t flags) {
    if (handle == bus && (flags & FDCAN_IT_BUS_OFF)) ++stats.bus_off;
}
void HAL_FDCAN_TxEventFifoCallback(FDCAN_HandleTypeDef *handle, uint32_t flags) {
    if (handle == bus && (flags & FDCAN_IT_TX_EVT_FIFO_ELT_LOST)) ++stats.tx_event_lost;
}
