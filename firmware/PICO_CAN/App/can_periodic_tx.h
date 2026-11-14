#ifndef CAN_PERIODIC_TX_H
#define CAN_PERIODIC_TX_H
#include "stm32g4xx_hal.h"
void CanPeriodicTx_Init(FDCAN_HandleTypeDef *can,UART_HandleTypeDef *uart);
void CanPeriodicTx_Step(void);
#endif
