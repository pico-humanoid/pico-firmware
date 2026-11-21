#ifndef ROBOT_UART_H
#define ROBOT_UART_H
#include "Communicate/robot_link.h"
bool RobotUart_Start(void);
bool RobotUart_Read(uint8_t *byte, uint32_t *arrival_ms);
/* Single owner (RobotComm) checks transport errors and repairs RX. */
bool RobotUart_TakeFault(void);
bool RobotUart_Write(void *unused, const uint8_t *bytes, uint16_t size);
/* Low priority telemetry task only; never block the CAN owner on UART. */
void RobotUart_Transmit(void);
#endif
