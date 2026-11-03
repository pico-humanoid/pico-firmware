#include "power_protocol.h"
#include <string.h>
#include <float.h>

_Static_assert(sizeof(float) == 4 && FLT_RADIX == 2 && FLT_MANT_DIG == 24 && FLT_MAX_EXP == 128,
               "Power float parameters require IEEE binary32");
const uint16_t power_parameter_indices[POWER_PARAMETER_COUNT] = {
    0x6001, 0x6002, 0x6004, 0x6005, 0x6006, 0x6007, 0x8001, 0x8003, 0x8004
};
const char *const power_parameter_names[POWER_PARAMETER_COUNT] = {
    "Can_baud", "Com_baud", "remoteCtrl", "fanspeedCtrl", "POWER_ID", "soundEffect",
    "currocpt", "sdT", "arTime"
};
static uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint16_t le16(const uint8_t *p) { return (uint16_t)(((uint16_t)p[1] << 8) | p[0]); }
static uint16_t word(const uint8_t *p, ProtocolByteOrder order) {
    return order == BYTE_ORDER_BIG ? (uint16_t)(((uint16_t)p[0] << 8) | p[1]) : le16(p);
}
bool Power_BuildQuery(uint8_t device_id, uint8_t query_index, CanFrame *frame) {
    if (frame == NULL || query_index >= POWER_QUERY_COUNT) return false;
    memset(frame, 0, sizeof(*frame));
    frame->id = ((uint32_t)(query_index == 0U ? 5U : query_index < 3U ? 2U : 7U) << 24) | device_id;
    frame->extended = true;
    frame->dlc = 8U;
    if (query_index == 2U) frame->data[0] = 0xCAU;
    if (query_index >= 3U) {
        const uint16_t parameter = power_parameter_indices[query_index - 3U];
        frame->data[0] = (uint8_t)parameter;
        frame->data[1] = (uint8_t)(parameter >> 8);
    }
    return true;
}
ProtocolResult Power_Parse(const CanFrame *frame, uint8_t device_id,
                           ProtocolByteOrder status_order, PowerState *state,
                           uint8_t *query_index) {
    if (frame == NULL || state == NULL || query_index == NULL) return PROTOCOL_INVALID;
    if (!frame->extended || ((frame->id >> 16) & 0xFFU) != device_id) return PROTOCOL_IGNORED;
    const uint8_t type = (uint8_t)((frame->id >> 24) & 0x1FU);
    if (type != 3U && type != 4U && type != 5U && type != 7U) return PROTOCOL_IGNORED;
    if (!CanFrame_IsValid(frame) || frame->remote || frame->dlc != 8U ||
        status_order > BYTE_ORDER_LITTLE) return PROTOCOL_INVALID;
    if (type == 7U) {
        const uint16_t parameter = le16(frame->data);
        uint8_t slot = 0;
        while (slot < POWER_PARAMETER_COUNT && power_parameter_indices[slot] != parameter) ++slot;
        if (slot == POWER_PARAMETER_COUNT) return PROTOCOL_IGNORED;
        /* V1.08 returns meaningful uint8 in Byte4, with nonzero Byte5..7.
           Keep all four bytes; never interpret a uint8 parameter as LE32. */
        PowerParameter value = {0};
        memcpy(value.raw, frame->data + 4, 4);
        value.bits_le = le32(value.raw);
        value.value_u8 = value.raw[0];
        value.upper_bytes_nonzero = (value.raw[1] | value.raw[2] | value.raw[3]) != 0U;
        value.numeric_valid = true;
        if (slot == 0U || slot == 1U)
            value.numeric_valid = value.value_u8 >= 1U && value.value_u8 <= 4U;
        else if (slot == 2U || slot == 5U)
            value.numeric_valid = value.value_u8 <= 1U;
        else if (slot == 3U)
            value.numeric_valid = value.value_u8 >= 1U && value.value_u8 <= 5U;
        else if (slot >= 6U) {
            memcpy(&value.value_float, &value.bits_le, sizeof(value.value_float));
            value.numeric_valid = (value.bits_le & 0x7F800000UL) != 0x7F800000UL;
        }
        if (slot == 0U && !value.numeric_valid) return PROTOCOL_INVALID;
        state->parameters[slot] = value;
        if (slot == 0U) state->can_baud_code = value.value_u8;
        if (slot == 4U) state->reported_id_mismatch = value.value_u8 != device_id;
        *query_index = (uint8_t)(3U + slot);
    } else if (type == 5U) {
        for (uint8_t i = 0; i < 8U; ++i) {
            uint8_t c = frame->data[i];
            if (c != 0U && (c < 32U || c > 126U)) return PROTOCOL_INVALID;
        }
        if (frame->data[0] == 0U) return PROTOCOL_INVALID;
        memcpy(state->version, frame->data, 8);
        state->version[8] = '\0';
        *query_index = 0U;
    } else if (type == 3U) {
        memcpy(state->status03_raw, frame->data, 8);
        state->status03_id = frame->id;
        state->temperature_c = frame->data[4];
        if (status_order != BYTE_ORDER_UNCONFIRMED) {
            state->battery_mv = (uint32_t)word(frame->data, status_order) * 10U;
            state->motor_mv = (uint32_t)word(frame->data + 2, status_order) * 10U;
            state->fault_and_switch_bits = status_order == BYTE_ORDER_BIG ?
                ((uint32_t)frame->data[5] << 16) | ((uint32_t)frame->data[6] << 8) | frame->data[7] :
                ((uint32_t)frame->data[7] << 16) | ((uint32_t)frame->data[6] << 8) | frame->data[5];
        }
        *query_index = 1U;
    } else {
        memcpy(state->status04_raw, frame->data, 8);
        state->status04_id = frame->id;
        if (status_order != BYTE_ORDER_UNCONFIRMED)
            for (uint8_t i = 0; i < 4U; ++i)
                state->branch_current_ma[i] = (uint32_t)word(frame->data + 2U * i, status_order) * 10U;
        *query_index = 2U;
    }
    state->numeric_status_confirmed = status_order != BYTE_ORDER_UNCONFIRMED;
    return PROTOCOL_OK;
}
