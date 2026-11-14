#ifndef PICO_MOTOR_READ_APP_H
#define PICO_MOTOR_READ_APP_H
#include "stm32g4xx_hal.h"
#include "motor_reader.h"
extern MotorReader g_motor_reader;
void MotorRead_Init(FDCAN_HandleTypeDef *can, UART_HandleTypeDef *uart);
void MotorRead_Step(void);
#endif
