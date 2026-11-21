#ifndef CAN_PIN_TRACE_H
#define CAN_PIN_TRACE_H
#include "stm32g4xx_hal.h"
void CanPinTrace_Init(void);
void CanPinTrace_Begin(FDCAN_HandleTypeDef *bus);
void CanPinTrace_Capture(FDCAN_HandleTypeDef *bus);
void CanPinTrace_Dump(UART_HandleTypeDef *uart);
#endif
