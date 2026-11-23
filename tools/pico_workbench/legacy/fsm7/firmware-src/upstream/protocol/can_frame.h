#ifndef PICO_CAN_FRAME_H
#define PICO_CAN_FRAME_H
#include <stdbool.h>
#include <stdint.h>

/* Classic CAN only. RTR has a requested DLC but no data payload. */
typedef struct {
    uint32_t id;
    uint32_t timestamp_ms;
    bool extended;
    bool remote;
    uint8_t dlc;
    uint8_t data[8];
} CanFrame;

typedef enum { PROTOCOL_IGNORED, PROTOCOL_INVALID, PROTOCOL_OK } ProtocolResult;
typedef enum { BYTE_ORDER_UNCONFIRMED, BYTE_ORDER_BIG, BYTE_ORDER_LITTLE } ProtocolByteOrder;
static inline bool CanFrame_IsValid(const CanFrame *frame) {
    return frame != 0 && frame->dlc <= 8U &&
           frame->id <= (frame->extended ? 0x1FFFFFFFU : 0x7FFU);
}
#endif
