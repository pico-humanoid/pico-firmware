#ifndef MOTOR_ENABLE_APP_H
#define MOTOR_ENABLE_APP_H
#include "stm32g4xx_hal.h"
void MotorEnableApp_Init(FDCAN_HandleTypeDef *can,UART_HandleTypeDef *uart);
void MotorEnableApp_Step(void);
#endif
