#include "Communicate/robot_uart.h"
#include "usart.h"
#include <assert.h>
#include <stdio.h>
UART_HandleTypeDef hlpuart1;
static uint8_t *receive;
static uint32_t now;
static unsigned sent, aborts;
static bool fail;
uint32_t HAL_GetTick(void) { return now; }
void HAL_NVIC_SetPriority(int i, int p, int s) {
  (void)i;
  assert(p == 5 && s == 0);
}
void HAL_NVIC_EnableIRQ(int i) { (void)i; }
HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *h, uint8_t *p,
                                      uint16_t n) {
  assert(h == &hlpuart1 && n == 1);
  receive = p;
  return HAL_OK;
}
HAL_StatusTypeDef HAL_UART_AbortReceive(UART_HandleTypeDef *h) {
  (void)h;
  aborts++;
  return HAL_OK;
}
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *h, const uint8_t *p,
                                    uint16_t n, uint32_t t) {
  assert(h == &hlpuart1 && n == 16 && p[0] == 'R' && t == 25);
  sent++;
  return fail ? HAL_ERROR : HAL_OK;
}
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *h);
void HAL_UART_ErrorCallback(UART_HandleTypeDef *h);
int main(void) {
  assert(RobotUart_Start());
  uint8_t byte;
  uint32_t at;
  *receive = 42;
  now = 99;
  HAL_UART_RxCpltCallback(&hlpuart1);
  assert(RobotUart_Read(&byte, &at) && byte == 42 && at == 99);
  assert(!RobotUart_Read(&byte, &at));
  for (unsigned i = 0; i < 520; i++) {
    *receive = (uint8_t)i;
    HAL_UART_RxCpltCallback(&hlpuart1);
  }
  assert(RobotUart_TakeFault() && !RobotUart_Read(&byte, &at));
  assert(!RobotUart_TakeFault());
  HAL_UART_ErrorCallback(&hlpuart1);
  assert(RobotUart_TakeFault() && aborts == 1);
  uint8_t p[16] = {'R', '4', 1, R14_NODE};
  for (unsigned i = 0; i < 10; i++)
    assert(RobotUart_Write(NULL, p, 16));
  assert(!RobotUart_Write(NULL, p, 16));
  p[3] = R14_ACK;
  for (unsigned i = 0; i < 5; i++)
    assert(RobotUart_Write(NULL, p, 16));
  assert(!RobotUart_Write(NULL, p, 16));
  for (unsigned i = 0; i < 16; i++)
    RobotUart_Transmit();
  assert(sent == 15);
  assert(RobotUart_Write(NULL, p, 16));
  fail = true;
  RobotUart_Transmit();
  assert(RobotUart_TakeFault());
  puts("Robot14 UART ring timestamps/overflow/RX repair/TX reserve/error "
       "passed");
  return 0;
}
