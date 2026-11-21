#ifndef PICO_MOTOR_PROTOCOL_H
#define PICO_MOTOR_PROTOCOL_H
#include "can_frame.h"

#define MOTOR_QUERY_COUNT 4U
extern const uint16_t motor_read_indices[MOTOR_QUERY_COUNT];
extern const char *const motor_read_fields[MOTOR_QUERY_COUNT];
typedef struct {
    uint8_t query;
    uint32_t raw_bits;
    int32_t value_milli;
} MotorReading;

/* RobStride private Classic-CAN protocol only. Type 0x11 reads four
   read-only float registers; no control, enable, ID, zero or parameter writes. */
bool Motor_MakeRead(uint8_t motor_id, uint8_t host_id, uint8_t query, CanFrame *frame);
ProtocolResult Motor_ParseRead(const CanFrame *frame, uint8_t motor_id,
                              uint8_t host_id, MotorReading *reading);
#endif
