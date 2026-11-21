#include "Communicate/robot_uart.h"
#include "usart.h"
#include <string.h>
#define RX_COUNT 512U
#define TX_COUNT 16U
typedef struct {
  uint32_t ms;
  uint8_t byte;
} RxByte;
typedef struct {
  uint16_t size;
  uint8_t bytes[ROBOT_LINK_MAX_PACKET];
} Packet;
static RxByte rx[RX_COUNT];
static Packet tx[TX_COUNT];
static volatile uint16_t rx_head, rx_tail, tx_head, tx_tail;
static volatile bool broken, fault;
static uint8_t incoming;
static uint32_t lock(void) {
  uint32_t p = __get_PRIMASK();
  __disable_irq();
  return p;
}
static void unlock(uint32_t p) { __set_PRIMASK(p); }
bool RobotUart_Start(void) {
  HAL_NVIC_SetPriority(LPUART1_IRQn, 5, 0);
  HAL_NVIC_EnableIRQ(LPUART1_IRQn);
  return HAL_UART_Receive_IT(&hlpuart1, &incoming, 1) == HAL_OK;
}
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *h) {
  if (h != &hlpuart1)
    return;
  uint16_t next = (rx_head + 1U) % RX_COUNT;
  if (next == rx_tail)
    fault = true;
  else {
    rx[rx_head] = (RxByte){HAL_GetTick(), incoming};
    __DMB();
    rx_head = next;
  }
  if (HAL_UART_Receive_IT(h, &incoming, 1) != HAL_OK)
    broken = true;
}
void HAL_UART_ErrorCallback(UART_HandleTypeDef *h) {
  if (h == &hlpuart1)
    broken = true;
}
bool RobotUart_Read(uint8_t *byte, uint32_t *arrival_ms) {
  if (rx_tail == rx_head)
    return false;
  __DMB();
  RxByte b = rx[rx_tail];
  rx_tail = (rx_tail + 1U) % RX_COUNT;
  *byte = b.byte;
  *arrival_ms = b.ms;
  return true;
}
bool RobotUart_TakeFault(void) {
  uint32_t p = lock();
  bool result = fault || broken;
  fault = false;
  if (result)
    rx_tail = rx_head; /* Discard backlog, never replay old commands. */
  if (broken) {
    broken = false;
    (void)HAL_UART_AbortReceive(&hlpuart1);
    if (HAL_UART_Receive_IT(&hlpuart1, &incoming, 1) != HAL_OK)
      broken = true;
  }
  unlock(p);
  return result;
}
bool RobotUart_Write(void *unused, const uint8_t *bytes, uint16_t size) {
  (void)unused;
  if (size > ROBOT_LINK_MAX_PACKET || size < 16)
    return false;
  uint32_t p = lock();
  uint16_t used = (tx_head + TX_COUNT - tx_tail) % TX_COUNT;
  /* Drop stale-able telemetry before it crowds out HELLO/ACK replies. */
  if (used >= TX_COUNT - 1U || (used >= 10 && bytes[3] >= R14_STATE)) {
    unlock(p);
    return false;
  }
  tx[tx_head].size = size;
  memcpy(tx[tx_head].bytes, bytes, size);
  __DMB();
  tx_head = (tx_head + 1U) % TX_COUNT;
  unlock(p);
  return true;
}
void RobotUart_Transmit(void) {
  Packet packet;
  uint32_t p = lock();
  if (tx_head == tx_tail) {
    unlock(p);
    return;
  }
  packet = tx[tx_tail];
  tx_tail = (tx_tail + 1U) % TX_COUNT;
  unlock(p);
  if (HAL_UART_Transmit(&hlpuart1, packet.bytes, packet.size, 25) != HAL_OK) {
    p = lock();
    fault = true;
    tx_tail = tx_head;
    unlock(p);
  }
}
