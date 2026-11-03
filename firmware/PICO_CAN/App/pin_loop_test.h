#ifndef PICO_PIN_LOOP_TEST_H
#define PICO_PIN_LOOP_TEST_H
#include "main.h"

/* Test-only image: PA12 output, PA11 input, no FDCAN/CAN traffic. */
void PinLoopTest_Init(UART_HandleTypeDef *uart);
void PinLoopTest_Step(void);
#endif
