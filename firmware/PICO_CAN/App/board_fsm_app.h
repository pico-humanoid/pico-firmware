#ifndef PICO_BOARD_FSM_APP_H
#define PICO_BOARD_FSM_APP_H

#include "stm32g4xx_hal.h"

void BoardFsmApp_Init(UART_HandleTypeDef *uart);
void BoardFsmApp_Step(void);
void BoardFsmApp_UartIrq(void);

#endif
