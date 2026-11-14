#ifndef CAN_MULTI_TEST_H
#define CAN_MULTI_TEST_H
#include "stm32g4xx_hal.h"
void CanMultiTest_Init(UART_HandleTypeDef *uart);
void CanMultiTest_Step(void);
#endif
