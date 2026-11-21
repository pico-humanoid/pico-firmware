#include "Communicate/robot_can.h"
#include "System/robot_config.h"
#include <string.h>
#define RX_SIZE 64U
#define TX_TIMEOUT_MS 20U
typedef struct {
  FDCAN_HandleTypeDef *hal;
  CanFrame rx[RX_SIZE];
  volatile uint32_t rd, wr;
  volatile RobotCanStats stats;
  uint32_t tx_since[3];
  uint8_t tracked;
  bool ready;
  bool active;              /* At least one ACKed TX or one received frame. */
  uint32_t activate_expired; /* tx_expired captured when the bus went active. */
} RobotBus;
static RobotBus buses[3];
/* Logical bus 1 is the BMS/power reader, 2/3 are motor buses. A diagnostic
   build can swap the two physical FDCAN instances while keeping the logical
   topology (and therefore the host protocol) unchanged. */
static FDCAN_HandleTypeDef *bus_hal(unsigned index) {
#if PICO_ROBOT_SWAP_CAN12
  static FDCAN_HandleTypeDef *const map[3] = {&hfdcan2, &hfdcan1, &hfdcan3};
#else
  static FDCAN_HandleTypeDef *const map[3] = {&hfdcan1, &hfdcan2, &hfdcan3};
#endif
  return map[index];
}
static RobotBus *get(uint8_t bus) {
  return bus >= 1 && bus <= 3 ? &buses[bus - 1] : NULL;
}
static RobotBus *from_hal(FDCAN_HandleTypeDef *h) {
  for (unsigned i = 0; i < 3; i++)
    if (buses[i].hal == h)
      return &buses[i];
  return NULL;
}
bool RobotCan_Start(void) {
  if (HAL_RCC_GetPCLK1Freq() != 80000000U)
    return false;
  memset(buses, 0, sizeof(buses));
  for (unsigned i = 0; i < 3; i++)
    buses[i].hal = bus_hal(i);
  for (unsigned i = 0; i < 3; i++) {
    FDCAN_HandleTypeDef *h = buses[i].hal;
    uint32_t rate = i == 0 ? ROBOT_CAN1_BITRATE : ROBOT_MOTOR_BITRATE;
    if (h->Init.FrameFormat != FDCAN_FRAME_CLASSIC ||
        h->Init.Mode != FDCAN_MODE_NORMAL ||
        h->Init.AutoRetransmission != ENABLE ||
        h->Init.ClockDivider != FDCAN_CLOCK_DIV1 ||
        h->Init.NominalPrescaler == 0 ||
        80000000U / h->Init.NominalPrescaler /
                (1U + h->Init.NominalTimeSeg1 + h->Init.NominalTimeSeg2) !=
            rate)
      return false;
    /* All three instances are initialized before starting the shared FDCAN
     * clock. */
    FDCAN_FilterTypeDef f = {.FilterIndex = 0,
                             .FilterConfig = FDCAN_FILTER_TO_RXFIFO0};
    if (i == 0) {
      f.IdType = FDCAN_STANDARD_ID;
      f.FilterType = FDCAN_FILTER_RANGE;
      f.FilterID1 = 0x100;
      f.FilterID2 = 0x105;
      if (HAL_FDCAN_ConfigFilter(h, &f) != HAL_OK)
        return false;
    }
    f.IdType = FDCAN_EXTENDED_ID;
    f.FilterType = FDCAN_FILTER_MASK;
    f.FilterID1 = i == 0 ? (ROBOT_POWER_ID << 16) : ROBOT_HOST_ID;
    f.FilterID2 = i == 0 ? 0x00FF0000U : 0xFFU;
    if (HAL_FDCAN_ConfigFilter(h, &f) != HAL_OK ||
        HAL_FDCAN_ConfigGlobalFilter(h, FDCAN_REJECT, FDCAN_REJECT,
                                     FDCAN_REJECT_REMOTE,
                                     FDCAN_REJECT_REMOTE) != HAL_OK ||
        HAL_FDCAN_ActivateNotification(h,
                                       FDCAN_IT_RX_FIFO0_NEW_MESSAGE |
                                           FDCAN_IT_RX_FIFO0_MESSAGE_LOST |
                                           FDCAN_IT_BUS_OFF,
                                       0) != HAL_OK ||
        HAL_FDCAN_Start(h) != HAL_OK)
      return false;
    buses[i].ready = true;
  }
  return true;
}
bool RobotCan_Send(void *unused, uint8_t bus, const CanFrame *f, uint32_t now) {
  (void)unused;
  RobotBus *b = get(bus);
  if (!b || !b->ready || b->stats.bus_off || !CanFrame_IsValid(f) ||
      HAL_FDCAN_GetTxFifoFreeLevel(b->hal) == 0)
    return false;
  if (bus != 1 && (!f->extended || f->remote || f->dlc != 8))
    return false;
  FDCAN_TxHeaderTypeDef h = {
      .Identifier = f->id,
      .IdType = f->extended ? FDCAN_EXTENDED_ID : FDCAN_STANDARD_ID,
      .TxFrameType = f->remote ? FDCAN_REMOTE_FRAME : FDCAN_DATA_FRAME,
      .DataLength = f->dlc,
      .ErrorStateIndicator = FDCAN_ESI_ACTIVE,
      .BitRateSwitch = FDCAN_BRS_OFF,
      .FDFormat = FDCAN_CLASSIC_CAN,
      .TxEventFifoControl = FDCAN_NO_TX_EVENTS,
      .MessageMarker = 0};
  if (HAL_FDCAN_AddMessageToTxFifoQ(b->hal, &h, f->data) != HAL_OK)
    return false;
  uint32_t mask = HAL_FDCAN_GetLatestTxFifoQRequestBuffer(b->hal);
  for (unsigned i = 0; i < 3; i++)
    if (mask & (1U << i)) {
      b->tx_since[i] = now;
      b->tracked |= (uint8_t)(1U << i);
    }
  b->stats.tx_submitted++;
  return true;
}
static void activate(RobotBus *b) {
  if (b->active)
    return;
  b->active = true;
  b->activate_expired = b->stats.tx_expired;
}
void RobotCan_Service(uint32_t now) {
  for (unsigned bus = 0; bus < 3; bus++) {
    RobotBus *b = &buses[bus];
    if (!b->ready)
      continue;
    /* Completions first: a buffer that left the pending set was acknowledged
       on the wire. Activating here keeps the "already connected" baseline
       before this tick's deadline aborts are accounted. */
    for (unsigned i = 0; i < 3; i++)
      if (b->tracked & (1U << i)) {
        uint32_t mask = 1U << i;
        if (!HAL_FDCAN_IsTxBufferMessagePending(b->hal, mask)) {
          b->stats.tx_done++;
          activate(b);
          b->tracked &= (uint8_t)~mask;
        }
      }
    for (unsigned i = 0; i < 3; i++)
      if (b->tracked & (1U << i)) {
        uint32_t mask = 1U << i;
        if (now - b->tx_since[i] > TX_TIMEOUT_MS) {
          (void)HAL_FDCAN_AbortTxRequest(b->hal, mask);
          b->stats.tx_expired++;
          b->tracked &= (uint8_t)~mask;
        }
      }
    /* A received frame also proves that another node is on this bus. */
    if (!b->active && b->stats.rx_received)
      activate(b);
  }
}
bool RobotCan_BusActive(uint8_t bus) {
  RobotBus *b = get(bus);
  return b && b->active;
}
bool RobotCan_BusFatal(uint8_t bus) {
  RobotBus *b = get(bus);
  if (!b)
    return false;
  uint32_t irq = __get_PRIMASK();
  __disable_irq();
  RobotCanStats s = b->stats;
  bool active = b->active;
  uint32_t base = b->activate_expired;
  __set_PRIMASK(irq);
  if (!active)
    return false;
  return s.bus_off || s.rx_dropped || s.fifo_lost || s.tx_expired > base;
}
void RobotCan_AbortMotors(void) {
  for (unsigned i = 1; i < 3; i++)
    if (buses[i].ready) {
      (void)HAL_FDCAN_AbortTxRequest(buses[i].hal, 7U);
      buses[i].tracked = 0;
    }
}
bool RobotCan_Receive(uint8_t bus, CanFrame *f) {
  RobotBus *b = get(bus);
  if (!b || !f || b->rd == b->wr)
    return false;
  __DMB();
  *f = b->rx[b->rd];
  __DMB();
  b->rd = (b->rd + 1) % RX_SIZE;
  return true;
}
RobotCanStats RobotCan_GetStats(uint8_t bus) {
  RobotCanStats s = {0};
  RobotBus *b = get(bus);
  if (!b)
    return s;
  uint32_t irq = __get_PRIMASK();
  __disable_irq();
  s = b->stats;
  __set_PRIMASK(irq);
  return s;
}
void HAL_FDCAN_RxFifo0Callback(FDCAN_HandleTypeDef *h, uint32_t flags) {
  RobotBus *b = from_hal(h);
  if (!b)
    return;
  if (flags & FDCAN_IT_RX_FIFO0_MESSAGE_LOST)
    b->stats.fifo_lost++;
  while (HAL_FDCAN_GetRxFifoFillLevel(h, FDCAN_RX_FIFO0)) {
    FDCAN_RxHeaderTypeDef rh = {0};
    uint8_t data[64];
    if (HAL_FDCAN_GetRxMessage(h, FDCAN_RX_FIFO0, &rh, data) != HAL_OK) {
      b->stats.rx_invalid++;
      break;
    }
    if (rh.FDFormat != FDCAN_CLASSIC_CAN || rh.DataLength > 8 ||
        rh.RxFrameType == FDCAN_REMOTE_FRAME) {
      b->stats.rx_invalid++;
      continue;
    }
    CanFrame f = {.id = rh.Identifier,
                  .timestamp_ms = HAL_GetTick(),
                  .extended = rh.IdType == FDCAN_EXTENDED_ID,
                  .dlc = (uint8_t)rh.DataLength};
    if (!CanFrame_IsValid(&f)) {
      b->stats.rx_invalid++;
      continue;
    }
    memcpy(f.data, data, f.dlc);
    b->stats.rx_received++;
    uint32_t next = (b->wr + 1) % RX_SIZE;
    if (next == b->rd) {
      b->stats.rx_dropped++;
      continue;
    }
    b->rx[b->wr] = f;
    __DMB();
    b->wr = next;
  }
}
void HAL_FDCAN_ErrorStatusCallback(FDCAN_HandleTypeDef *h, uint32_t flags) {
  RobotBus *b = from_hal(h);
  if (b && (flags & FDCAN_IT_BUS_OFF))
    b->stats.bus_off++;
}
