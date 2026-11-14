#ifndef PICO_CAN_TRANSPORT_H
#define PICO_CAN_TRANSPORT_H
#include "stm32g4xx_hal.h"
#include "protocol/can_frame.h"

#define CAN_TRANSPORT_TX_DEADLINE_MS 300U
#if defined(PICO_CAN_BOUNDED_TX_RETRY) && PICO_CAN_BOUNDED_TX_RETRY
#define CAN_TRANSPORT_TX_POLICY "BOUNDED_RETRY_V1"
#else
#define CAN_TRANSPORT_TX_POLICY "SINGLE_ATTEMPT_V1"
#endif

typedef enum { CAN_FILTER_BMS, CAN_FILTER_POWER, CAN_FILTER_DUAL, CAN_FILTER_MOTOR, CAN_FILTER_MOTOR_DIAG } CanTransportFilter;
typedef struct {
    uint32_t rx_received, rx_read_failed, rx_unsupported;
    uint32_t rx_fifo_lost, rx_queue_dropped;
    uint32_t tx_submitted, tx_completed, tx_rejected, tx_timed_out;
    uint32_t tx_event_lost, tx_event_unknown, bus_off;
    uint32_t tx_cancelled;
} CanTransportStats;
typedef void (*CanTransportLog)(const char *event, const CanFrame *frame);

/* One FDCAN3 instance per device/motor image: BMS, Power, Dual and Motor.
   This is not a simultaneous multi-bus driver.
   Init/Submit/Service/Receive/Stats are main-loop only; HAL callbacks are ISR-only. */
bool CanTransport_Init(FDCAN_HandleTypeDef *handle, uint32_t bitrate,
                       CanTransportFilter filter, uint8_t power_id, CanTransportLog log);
bool CanTransport_Submit(const CanFrame *frame, uint32_t now);
void CanTransport_Service(uint32_t now);
/* Main context: cancel obsolete queued commands before issuing a group STOP. */
void CanTransport_CancelPending(uint32_t now);
uint32_t CanTransport_AvailableSlots(void);
bool CanTransport_Receive(CanFrame *frame);
CanTransportStats CanTransport_GetStats(void);
bool CanTransport_IsBusOff(void);
#endif
