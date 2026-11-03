#ifndef PICO_DEVICE_READ_APP_H
#define PICO_DEVICE_READ_APP_H
#include "stm32g4xx_hal.h"
#include "device_reader.h"
#if defined(PICO_DEVICE_DUAL)
#include "dual_device_reader.h"
extern DualDeviceReader g_dual_device_reader;
#else
extern DeviceReader g_device_reader;
#endif
void DeviceRead_Init(FDCAN_HandleTypeDef *can, UART_HandleTypeDef *uart);
void DeviceRead_Step(void);
#endif
