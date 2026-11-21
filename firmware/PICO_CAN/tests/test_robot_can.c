/* Compile the real three-bus transport against deterministic HAL fakes. */
#include "Communicate/robot_can.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
FDCAN_GlobalTypeDef fake_fdcan1, fake_fdcan2, fake_fdcan3;
FDCAN_HandleTypeDef hfdcan1 = {.Instance = FDCAN1},
                    hfdcan2 = {.Instance = FDCAN2},
                    hfdcan3 = {.Instance = FDCAN3};
static uint32_t clock_hz = 80000000, now, filters[3], pending[3], aborted[3],
                latest[3], queued;
static unsigned rx_bus;
static FDCAN_RxHeaderTypeDef incoming;
static uint8_t payload[64];
static unsigned bus(const FDCAN_HandleTypeDef *h) {
  assert(h == &hfdcan1 || h == &hfdcan2 || h == &hfdcan3);
  return h == &hfdcan1 ? 0 : h == &hfdcan2 ? 1 : 2;
}
uint32_t HAL_GetTick(void) { return now; }
uint32_t HAL_RCC_GetPCLK1Freq(void) { return clock_hz; }
HAL_StatusTypeDef HAL_FDCAN_ConfigFilter(FDCAN_HandleTypeDef *h,
                                         FDCAN_FilterTypeDef *f) {
  unsigned b = bus(h);
  filters[b]++;
  if (b == 0 && f->IdType == FDCAN_STANDARD_ID) {
    assert(f->FilterID1 == 0x100 && f->FilterID2 == 0x105);
  } else {
    assert(f->IdType == FDCAN_EXTENDED_ID);
    assert(f->FilterID1 == (b == 0 ? 0xAA0000U : 0xFD));
    assert(f->FilterID2 == (b == 0 ? 0xFF0000U : 0xFF));
  }
  return HAL_OK;
}
HAL_StatusTypeDef HAL_FDCAN_ConfigGlobalFilter(FDCAN_HandleTypeDef *h,
                                               uint32_t a, uint32_t b,
                                               uint32_t c, uint32_t d) {
  (void)h;
  assert(a == FDCAN_REJECT && b == FDCAN_REJECT && c == FDCAN_REJECT_REMOTE &&
         d == FDCAN_REJECT_REMOTE);
  return HAL_OK;
}
HAL_StatusTypeDef HAL_FDCAN_ActivateNotification(FDCAN_HandleTypeDef *h,
                                                 uint32_t f, uint32_t ignored) {
  (void)h;
  (void)ignored;
  assert(f & FDCAN_IT_BUS_OFF);
  return HAL_OK;
}
HAL_StatusTypeDef HAL_FDCAN_Start(FDCAN_HandleTypeDef *h) {
  (void)h;
  return HAL_OK;
}
uint32_t HAL_FDCAN_GetTxFifoFreeLevel(const FDCAN_HandleTypeDef *h) {
  return pending[bus(h)] == 7 ? 0 : 1;
}
HAL_StatusTypeDef HAL_FDCAN_AddMessageToTxFifoQ(FDCAN_HandleTypeDef *h,
                                                const FDCAN_TxHeaderTypeDef *f,
                                                const uint8_t *data) {
  (void)data;
  unsigned b = bus(h);
  assert(f->FDFormat == FDCAN_CLASSIC_CAN && f->DataLength <= 8);
  for (unsigned i = 0; i < 3; i++)
    if (!(pending[b] & (1U << i))) {
      latest[b] = 1U << i;
      pending[b] |= latest[b];
      return HAL_OK;
    }
  return HAL_ERROR;
}
uint32_t HAL_FDCAN_GetLatestTxFifoQRequestBuffer(const FDCAN_HandleTypeDef *h) {
  return latest[bus(h)];
}
uint32_t HAL_FDCAN_IsTxBufferMessagePending(const FDCAN_HandleTypeDef *h,
                                            uint32_t m) {
  return pending[bus(h)] & m;
}
HAL_StatusTypeDef HAL_FDCAN_AbortTxRequest(FDCAN_HandleTypeDef *h, uint32_t m) {
  unsigned b = bus(h);
  aborted[b] |= m;
  pending[b] &= ~m;
  return HAL_OK;
}
uint32_t HAL_FDCAN_GetRxFifoFillLevel(const FDCAN_HandleTypeDef *h,
                                      uint32_t fifo) {
  (void)fifo;
  return bus(h) == rx_bus ? queued : 0;
}
HAL_StatusTypeDef HAL_FDCAN_GetRxMessage(FDCAN_HandleTypeDef *h, uint32_t fifo,
                                         FDCAN_RxHeaderTypeDef *f,
                                         uint8_t *data) {
  (void)fifo;
  assert(bus(h) == rx_bus && queued);
  queued--;
  *f = incoming;
  memcpy(data, payload, 64);
  return HAL_OK;
}
int main(void) {
  FDCAN_HandleTypeDef *handles[] = {&hfdcan1, &hfdcan2, &hfdcan3};
  for (unsigned i = 0; i < 3; i++)
    handles[i]->Init = (FDCAN_InitTypeDef){.Mode = FDCAN_MODE_NORMAL,
                                           .AutoRetransmission = ENABLE,
                                           .ClockDivider = FDCAN_CLOCK_DIV1,
                                           .FrameFormat = FDCAN_FRAME_CLASSIC,
                                           .NominalPrescaler = i == 0 ? 10 : 5,
                                           .NominalTimeSeg1 = 13,
                                           .NominalTimeSeg2 = 2};
  clock_hz = 16000000;
  assert(!RobotCan_Start());
  clock_hz = 80000000;
  assert(RobotCan_Start());
  assert(filters[0] == 2 && filters[1] == 1 && filters[2] == 1);
  CanFrame f = {.id = 0x01000001, .extended = true, .dlc = 8}, out;
  for (unsigned b = 1; b <= 3; b++)
    assert(RobotCan_Send(NULL, (uint8_t)b, &f, 0));
  pending[0] = 0;
  RobotCan_Service(20);
  assert(RobotCan_GetStats(2).tx_expired == 0);
  RobotCan_Service(21);
  assert(RobotCan_GetStats(1).tx_expired == 0 &&
         RobotCan_GetStats(2).tx_expired == 1 &&
         RobotCan_GetStats(3).tx_expired == 1);
  assert(RobotCan_GetStats(1).tx_done == 1);
  assert(RobotCan_BusActive(1) && !RobotCan_BusActive(2) &&
         !RobotCan_BusActive(3));
  assert(!RobotCan_BusFatal(1));
  /* Timeouts on buses that never carried a frame are just empty-bus probes. */
  assert(!RobotCan_BusFatal(2) && !RobotCan_BusFatal(3));
  assert(aborted[1] == 1 && aborted[2] == 1);
  for (unsigned i = 0; i < 3; i++)
    assert(RobotCan_Send(NULL, 2, &f, 30));
  assert(!RobotCan_Send(NULL, 2, &f, 30));
  RobotCan_AbortMotors();
  assert(!pending[1] && aborted[1] == 7 && aborted[2] == 7);
  f.remote = true;
  assert(!RobotCan_Send(NULL, 2, &f, 31));
  f.remote = false;
  incoming = (FDCAN_RxHeaderTypeDef){.Identifier = 0x020001FD,
                                     .IdType = FDCAN_EXTENDED_ID,
                                     .DataLength = 8,
                                     .FDFormat = FDCAN_CLASSIC_CAN};
  payload[0] = 42;
  rx_bus = 1;
  queued = 1;
  now = 32;
  HAL_FDCAN_RxFifo0Callback(&hfdcan2, FDCAN_IT_RX_FIFO0_NEW_MESSAGE);
  assert(!RobotCan_Receive(1, &out) && !RobotCan_Receive(3, &out));
  assert(RobotCan_Receive(2, &out) && out.timestamp_ms == 32 &&
         out.data[0] == 42 && out.extended);
  queued = 64;
  HAL_FDCAN_RxFifo0Callback(&hfdcan2, FDCAN_IT_RX_FIFO0_NEW_MESSAGE |
                                          FDCAN_IT_RX_FIFO0_MESSAGE_LOST);
  assert(RobotCan_GetStats(2).rx_dropped == 1 &&
         RobotCan_GetStats(2).fifo_lost == 1);
  unsigned received = 0;
  while (RobotCan_Receive(2, &out))
    received++;
  assert(received == 63);
  incoming.RxFrameType = FDCAN_REMOTE_FRAME;
  queued = 1;
  HAL_FDCAN_RxFifo0Callback(&hfdcan2, 1);
  assert(!RobotCan_Receive(2, &out) && RobotCan_GetStats(2).rx_invalid == 1);
  HAL_FDCAN_ErrorStatusCallback(&hfdcan3, FDCAN_IT_BUS_OFF);
  assert(!RobotCan_Send(NULL, 3, &f, 40) && RobotCan_GetStats(3).bus_off == 1);
  /* Bus 3 never carried traffic: its bus-off is isolated, not fatal. */
  assert(!RobotCan_BusActive(3) && !RobotCan_BusFatal(3));
  assert(RobotCan_Send(NULL, 2, &f, 40));
  /* A timeout after the bus proved it was connected is a real loss. */
  assert(RobotCan_Send(NULL, 1, &f, 41));
  RobotCan_Service(62);
  assert(RobotCan_GetStats(1).tx_expired == 1 && RobotCan_BusFatal(1));
  puts("robot CAN: filters, rings, FIFO limits, TX deadlines, abort, empty-bus "
       "isolation and post-activation fault detection PASS");
  return 0;
}
