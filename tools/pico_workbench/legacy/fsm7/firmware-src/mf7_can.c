/* STM32G474: independent polled controllers. No application command timing,
   motor confirmation, or claims about stop status belong in this layer. */
#include "mf7_can.h"

#include <string.h>

#define MF7_TX_DEADLINE_MS 20U
#define MF7_TX_MASK (FDCAN_TX_BUFFER0 | FDCAN_TX_BUFFER1 | FDCAN_TX_BUFFER2)

typedef struct {
    FDCAN_HandleTypeDef *h;
    uint32_t submitted_at[3];
    uint32_t tracked;
    uint32_t cancelling;
    uint32_t faults;
    uint8_t host;
    bool started;
} Bus;

static Bus buses[3];

static Bus *get_bus(uint8_t bus)
{
    return bus >= 1U && bus <= 3U ? &buses[bus - 1U] : NULL;
}

static void service(Bus *b, uint32_t now)
{
    if (!b->started) return;
    FDCAN_GlobalTypeDef *r = b->h->Instance;
    const uint32_t watched = FDCAN_IR_BO | FDCAN_IR_EP | FDCAN_IR_EW |
                             FDCAN_IR_RF0L | FDCAN_IR_PEA | FDCAN_IR_PED | FDCAN_IR_MRAF;
    const uint32_t events = r->IR & watched;
    const uint32_t psr = r->PSR;
    if ((events & FDCAN_IR_BO) || (psr & FDCAN_PSR_BO))
        b->faults |= MF7_CAN_FAULT_BUS_OFF;
    if ((events & (FDCAN_IR_EP | FDCAN_IR_EW)) || (psr & (FDCAN_PSR_EP | FDCAN_PSR_EW)))
        b->faults |= MF7_CAN_FAULT_WARNING;
    if (events & FDCAN_IR_RF0L) b->faults |= MF7_CAN_FAULT_RX_LOST;
    if (events & (FDCAN_IR_PEA | FDCAN_IR_PED)) b->faults |= MF7_CAN_FAULT_PROTOCOL;
    if (events & FDCAN_IR_MRAF) b->faults |= MF7_CAN_FAULT_HAL;
    if (events) r->IR = events; /* Write-one-to-clear; leave other flags alone. */

    const uint32_t pending = r->TXBRP & MF7_TX_MASK;
    b->tracked &= pending;
    b->cancelling &= pending;
    uint32_t expired = 0;
    for (unsigned i = 0; i < 3U; ++i) {
        const uint32_t bit = 1UL << i;
        if ((b->tracked & bit) && now - b->submitted_at[i] >= MF7_TX_DEADLINE_MS)
            expired |= bit;
    }
    if (expired) {
        b->faults |= MF7_CAN_FAULT_TX_TIMEOUT;
        if ((expired & ~b->cancelling) &&
            HAL_FDCAN_AbortTxRequest(b->h, expired & ~b->cancelling) != HAL_OK)
            b->faults |= MF7_CAN_FAULT_HAL;
        b->cancelling |= expired;
    }
}

static bool match(FDCAN_HandleTypeDef *h, unsigned n, unsigned type, uint8_t dst)
{
    FDCAN_FilterTypeDef f = {
        .IdType = FDCAN_EXTENDED_ID,
        .FilterIndex = n,
        .FilterType = FDCAN_FILTER_MASK,
        .FilterConfig = FDCAN_FILTER_TO_RXFIFO0,
        .FilterID1 = ((uint32_t)type << 24) | dst,
        .FilterID2 = 0x1F0000FFU
    };
    return HAL_FDCAN_ConfigFilter(h, &f) == HAL_OK;
}

bool Mf7Can_Init(uint8_t bus, FDCAN_HandleTypeDef *h, uint8_t host)
{
    Bus *b = get_bus(bus);
    if (!b || b->started) return false;
    *b = (Bus){.faults = MF7_CAN_FAULT_INIT};
    if (!h || !host || host >= 0xFEU || HAL_RCC_GetPCLK1Freq() != 16000000U ||
        h->State != HAL_FDCAN_STATE_RESET) return false;
    for (unsigned i = 0; i < 3U; ++i)
        if (buses[i].h == h) return false;

    FDCAN_GlobalTypeDef *const instances[] = {FDCAN1, FDCAN2, FDCAN3};
    const IRQn_Type it0[] = {FDCAN1_IT0_IRQn, FDCAN2_IT0_IRQn, FDCAN3_IT0_IRQn};
    const IRQn_Type it1[] = {FDCAN1_IT1_IRQn, FDCAN2_IT1_IRQn, FDCAN3_IT1_IRQn};
    b->h = h;
    b->host = host;
    h->Instance = instances[bus - 1U];
    h->Init = (FDCAN_InitTypeDef){
        .ClockDivider = FDCAN_CLOCK_DIV1,
        .FrameFormat = FDCAN_FRAME_CLASSIC,
        .Mode = FDCAN_MODE_NORMAL,
        .AutoRetransmission = DISABLE,
        .TransmitPause = DISABLE,
        .ProtocolException = DISABLE,
        .NominalPrescaler = 1,
        .NominalSyncJumpWidth = 2,
        .NominalTimeSeg1 = 13,
        .NominalTimeSeg2 = 2,
        .DataPrescaler = 1,
        .DataSyncJumpWidth = 1,
        .DataTimeSeg1 = 1,
        .DataTimeSeg2 = 1,
        .StdFiltersNbr = 0,
        .ExtFiltersNbr = 5,
        .TxFifoQueueMode = FDCAN_TX_FIFO_OPERATION
    };
    const HAL_StatusTypeDef result = HAL_FDCAN_Init(h);
    HAL_NVIC_DisableIRQ(it0[bus - 1U]);
    HAL_NVIC_DisableIRQ(it1[bus - 1U]);
    if (result != HAL_OK ||
        !match(h, 0, 2, host) || !match(h, 1, 17, host) || !match(h, 2, 21, host) ||
        !match(h, 3, 0, 0xFEU) || !match(h, 4, 0, host) ||
        HAL_FDCAN_ConfigGlobalFilter(h, FDCAN_REJECT, FDCAN_REJECT,
                                     FDCAN_REJECT_REMOTE, FDCAN_REJECT_REMOTE) != HAL_OK ||
        HAL_FDCAN_ConfigRxFifoOverwrite(h, FDCAN_RX_FIFO0, FDCAN_RX_FIFO_BLOCKING) != HAL_OK ||
        HAL_FDCAN_Start(h) != HAL_OK) return false;
    b->faults = 0U;
    b->started = true;
    return true;
}

bool Mf7Can_Send(uint8_t bus, const CanFrame *f)
{
    Bus *b = get_bus(bus);
    if (!b || !b->started || !CanFrame_IsValid(f) || !f->extended || f->remote || f->dlc != 8U)
        return false;
    const uint32_t type = f->id >> 24;
    const uint8_t motor = (uint8_t)f->id;
    if (!motor || motor > 127U || motor == b->host) return false;
    if (type != 0U && type != 1U && type != 3U && type != 4U && type != 17U && type != 18U)
        return false;

    const uint32_t now = HAL_GetTick();
    service(b, now);
    /* Stop requests remain possible on a faulted bus. A cancel barrier prevents
       a pending old effort frame from following a new stop. */
    if ((b->faults && type != 4U) || b->cancelling || !HAL_FDCAN_GetTxFifoFreeLevel(b->h))
        return false;
    FDCAN_TxHeaderTypeDef h = {
        .Identifier = f->id,
        .IdType = FDCAN_EXTENDED_ID,
        .TxFrameType = FDCAN_DATA_FRAME,
        .DataLength = FDCAN_DLC_BYTES_8,
        .ErrorStateIndicator = FDCAN_ESI_ACTIVE,
        .BitRateSwitch = FDCAN_BRS_OFF,
        .FDFormat = FDCAN_CLASSIC_CAN,
        .TxEventFifoControl = FDCAN_NO_TX_EVENTS
    };
    if (HAL_FDCAN_AddMessageToTxFifoQ(b->h, &h, f->data) != HAL_OK) {
        b->faults |= MF7_CAN_FAULT_HAL;
        return false;
    }
    const uint32_t bit = HAL_FDCAN_GetLatestTxFifoQRequestBuffer(b->h);
    for (unsigned i = 0; i < 3U; ++i) {
        if (bit == (1UL << i)) {
            b->submitted_at[i] = now;
            b->tracked |= bit;
            return true; /* Queue submit only; not a controller TX or motor ACK. */
        }
    }
    b->faults |= MF7_CAN_FAULT_HAL;
    Mf7Can_Cancel(bus);
    return false;
}

bool Mf7Can_Poll(uint8_t bus, CanFrame *f)
{
    Bus *b = get_bus(bus);
    if (!b || !b->started || !f) return false;
    for (unsigned i = 0; i < 3U && HAL_FDCAN_GetRxFifoFillLevel(b->h, FDCAN_RX_FIFO0); ++i) {
        FDCAN_RxHeaderTypeDef h = {0};
        uint8_t data[64]; /* HAL copies according to DLC before validating frame format. */
        if (HAL_FDCAN_GetRxMessage(b->h, FDCAN_RX_FIFO0, &h, data) != HAL_OK) {
            b->faults |= MF7_CAN_FAULT_HAL;
            return false;
        }
        const unsigned type = h.Identifier >> 24;
        const uint8_t dst = (uint8_t)h.Identifier;
        if (!((type == 0U && (dst == 0xFEU || dst == b->host)) ||
              ((type == 2U || type == 17U || type == 21U) && dst == b->host))) continue;
        if (h.IdType != FDCAN_EXTENDED_ID || h.RxFrameType != FDCAN_DATA_FRAME ||
            h.FDFormat != FDCAN_CLASSIC_CAN || h.DataLength != FDCAN_DLC_BYTES_8) {
            b->faults |= MF7_CAN_FAULT_MALFORMED;
            continue;
        }
        *f = (CanFrame){.id = h.Identifier, .timestamp_ms = HAL_GetTick(), .extended = true, .dlc = 8};
        memcpy(f->data, data, sizeof f->data);
        return true;
    }
    return false;
}

uint32_t Mf7Can_Faults(uint8_t bus)
{
    Bus *b = get_bus(bus);
    if (!b || !b->started) return MF7_CAN_FAULT_INIT;
    service(b, HAL_GetTick());
    return b->faults;
}

bool Mf7Can_Healthy(uint8_t bus)
{
    return Mf7Can_Faults(bus) == 0U;
}

void Mf7Can_Cancel(uint8_t bus)
{
    Bus *b = get_bus(bus);
    if (!b || !b->started) return;
    const uint32_t pending = b->h->Instance->TXBRP & MF7_TX_MASK;
    if (pending) {
        if (HAL_FDCAN_AbortTxRequest(b->h, pending) != HAL_OK)
            b->faults |= MF7_CAN_FAULT_HAL;
        b->cancelling |= pending;
    }
}
