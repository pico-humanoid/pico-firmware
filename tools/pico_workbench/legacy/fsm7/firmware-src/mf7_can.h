#ifndef MF7_CAN_H
#define MF7_CAN_H

#include "protocol/can_frame.h"
#include "stm32g4xx_hal.h"

enum {
    MF7_CAN_FAULT_INIT = 1U << 0,
    MF7_CAN_FAULT_BUS_OFF = 1U << 1,
    MF7_CAN_FAULT_WARNING = 1U << 2,
    MF7_CAN_FAULT_RX_LOST = 1U << 3,
    MF7_CAN_FAULT_PROTOCOL = 1U << 4,
    MF7_CAN_FAULT_TX_TIMEOUT = 1U << 5,
    MF7_CAN_FAULT_HAL = 1U << 6,
    MF7_CAN_FAULT_MALFORMED = 1U << 7
};

/* Main loop only. Buses are numbered 1, 2, 3; handles are owned by this
   transport after Init and should start reset. Do not activate HAL CAN IRQs. */
bool Mf7Can_Init(uint8_t bus, FDCAN_HandleTypeDef *h, uint8_t host);
bool Mf7Can_Send(uint8_t bus, const CanFrame *f);
bool Mf7Can_Poll(uint8_t bus, CanFrame *f);
bool Mf7Can_Healthy(uint8_t bus);
uint32_t Mf7Can_Faults(uint8_t bus);
void Mf7Can_Cancel(uint8_t bus);

#endif
