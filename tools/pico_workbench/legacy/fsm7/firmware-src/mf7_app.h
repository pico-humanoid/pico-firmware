#ifndef MF7_APP_H
#define MF7_APP_H
#include "stm32g4xx_hal.h"
void Mf7App_Init(UART_HandleTypeDef *uart);
void Mf7App_Step(void);
void Mf7App_UartIrq(void);
#endif
