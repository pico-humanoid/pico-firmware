#ifndef CAN_BRINGUP_H
#define CAN_BRINGUP_H
#include "stm32g4xx_hal.h"

typedef struct {
    uint32_t result; /* 0 running/waiting, 1 pass, 2 fail */
    uint32_t tx_submitted, tx_completed, tx_submit_failed;
    uint32_t rx_unique, rx_duplicate, rx_invalid;
    uint32_t rx_fifo_lost_events, rx_queue_dropped, rx_read_failed;
    uint32_t tx_event_lost_events, bus_off_events, fatal;
} CanTestStatus;
extern volatile CanTestStatus g_can_test;
void CanTest_Init(FDCAN_HandleTypeDef *can, UART_HandleTypeDef *uart);
void CanTest_Step(void);
#endif
