#ifndef PICO_CAN_TRANSPORT_H
#define PICO_CAN_TRANSPORT_H
#include "stm32g4xx_hal.h"
#include "protocol/can_frame.h"

typedef enum { CAN_FILTER_BMS, CAN_FILTER_POWER, CAN_FILTER_DUAL } CanTransportFilter;
typedef struct {
    uint32_t rx_received, rx_read_failed, rx_unsupported;
    uint32_t rx_fifo_lost, rx_queue_dropped;
    uint32_t tx_submitted, tx_completed, tx_rejected, tx_timed_out;
    uint32_t tx_event_lost, tx_event_unknown, bus_off;
} CanTransportStats;
typedef void (*CanTransportLog)(const char *event, const CanFrame *frame);

/* Current board implementation owns ONE FDCAN1 instance; not a dual-bus driver.
   Init/Submit/Service/Receive/Stats are main-loop only; HAL callbacks are ISR-only. */
bool CanTransport_Init(FDCAN_HandleTypeDef *handle, uint32_t bitrate,
                       CanTransportFilter filter, uint8_t power_id, CanTransportLog log);
bool CanTransport_Submit(const CanFrame *frame, uint32_t now);
void CanTransport_Service(uint32_t now);
bool CanTransport_Receive(CanFrame *frame);
CanTransportStats CanTransport_GetStats(void);
bool CanTransport_IsBusOff(void);
#endif
