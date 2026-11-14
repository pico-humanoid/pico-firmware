#include "motor_protocol.h"
#include "robstride_spc.h"
#include <string.h>

/* Official RS10P 261016 / RS00 261009 manuals: read-only parameter table. */
const uint16_t motor_read_indices[MOTOR_QUERY_COUNT] = {0x7019, 0x701B, 0x701A, 0x701C};
const char *const motor_read_fields[MOTOR_QUERY_COUNT] = {
    "position_millirad", "velocity_millirad_s", "iq_ma", "vbus_mv"
};
static bool ids_valid(uint8_t motor, uint8_t host) {
    return motor > 0U && motor <= 0x7FU && host > 0U && host != motor && host < 0xFEU;
}
bool Motor_MakeRead(uint8_t motor, uint8_t host, uint8_t query, CanFrame *frame) {
    if (!frame || !ids_valid(motor, host) || query >= MOTOR_QUERY_COUNT) return false;
    *frame=RsSpc_Frame(motor,host,17,motor_read_indices[query],0);
    return CanFrame_IsValid(frame);
}
ProtocolResult Motor_ParseRead(const CanFrame *frame, uint8_t motor,
                              uint8_t host, MotorReading *reading) {
    if (!frame || !reading || !ids_valid(motor, host)) return PROTOCOL_INVALID;
    if (!frame->extended || (frame->id >> 24) != 0x11U ||
        (frame->id & 0xFFU) != host || ((frame->id >> 8) & 0xFFU) != motor)
        return PROTOCOL_IGNORED;
    if (!CanFrame_IsValid(frame) || frame->remote || frame->dlc != 8U ||
        ((frame->id >> 16) & 0xFFU) != 0U || frame->data[2] != 0U || frame->data[3] != 0U)
        return PROTOCOL_INVALID;
    uint16_t index = (uint16_t)(frame->data[0] | ((uint16_t)frame->data[1] << 8));
    uint8_t query;
    for (query = 0; query < MOTOR_QUERY_COUNT && motor_read_indices[query] != index; ++query) { }
    if (query == MOTOR_QUERY_COUNT) return PROTOCOL_IGNORED;
    uint32_t bits = (uint32_t)frame->data[4] | ((uint32_t)frame->data[5] << 8) |
                    ((uint32_t)frame->data[6] << 16) | ((uint32_t)frame->data[7] << 24);
    if ((bits & 0x7F800000UL) == 0x7F800000UL) return PROTOCOL_INVALID;
    float value;
    _Static_assert(sizeof(value) == sizeof(bits), "Motor parameter requires binary32 float");
    value=RsSpc_Float(frame->data+4);
    /* Prevent undefined conversion while retaining raw bits for diagnosis. */
    if (value > 2147483.0f || value < -2147483.0f) return PROTOCOL_INVALID;
    *reading = (MotorReading){.query=query, .raw_bits=bits, .value_milli=(int32_t)(value * 1000.0f)};
    return PROTOCOL_OK;
}
