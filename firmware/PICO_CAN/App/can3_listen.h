#ifndef CAN3_LISTEN_H
#define CAN3_LISTEN_H
#include "stm32g4xx_hal.h"
void Can3Listen_Init(FDCAN_HandleTypeDef *can,UART_HandleTypeDef *uart);
void Can3Listen_Step(void);
#endif
