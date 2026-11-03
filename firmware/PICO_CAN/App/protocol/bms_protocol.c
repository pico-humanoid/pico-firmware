#include "bms_protocol.h"
#include <string.h>

const uint16_t bms_query_ids[BMS_QUERY_COUNT] = {0x100U, 0x101U, 0x102U, 0x103U, 0x105U};
static uint16_t be16(const uint8_t *p) { return (uint16_t)(((uint16_t)p[0] << 8) | p[1]); }
uint16_t Bms_Crc16(const uint8_t *data, uint8_t length) {
    uint16_t crc = 0xFFFFU;
    for (uint8_t i = 0; i < length; ++i) {
        crc ^= data[i];
        for (uint8_t bit = 0; bit < 8U; ++bit)
            crc = (uint16_t)((crc >> 1) ^ ((crc & 1U) ? 0xA001U : 0U));
    }
    return crc;
}
bool Bms_BuildQuery(uint16_t id, uint8_t requested_dlc, CanFrame *frame) {
    if (frame == NULL || (requested_dlc != 0U && requested_dlc != 8U)) return false;
    bool found = false;
    for (uint8_t i = 0; i < BMS_QUERY_COUNT; ++i) if (bms_query_ids[i] == id) found = true;
    if (!found) return false;
    memset(frame, 0, sizeof(*frame));
    frame->id = id;
    frame->remote = true;
    frame->dlc = requested_dlc;
    return true;
}
ProtocolResult Bms_Parse(const CanFrame *frame, ProtocolByteOrder crc_order,
                         BmsState *state, uint8_t *query_index) {
    if (frame == NULL || state == NULL || query_index == NULL) return PROTOCOL_INVALID;
    if (frame->extended) return PROTOCOL_IGNORED;
    uint8_t index;
    for (index = 0; index < BMS_QUERY_COUNT; ++index) if (frame->id == bms_query_ids[index]) break;
    if (index == BMS_QUERY_COUNT) return PROTOCOL_IGNORED;
    if (!CanFrame_IsValid(frame) || frame->remote || frame->dlc != 8U ||
        (crc_order != BYTE_ORDER_BIG && crc_order != BYTE_ORDER_LITTLE)) return PROTOCOL_INVALID;
    const uint16_t received = crc_order == BYTE_ORDER_BIG ? be16(frame->data + 6) :
        (uint16_t)(((uint16_t)frame->data[7] << 8) | frame->data[6]);
    if (Bms_Crc16(frame->data, 6) != received) return PROTOCOL_INVALID;
    const uint16_t a = be16(frame->data), b = be16(frame->data + 2), c = be16(frame->data + 4);
    if (frame->id == 0x101U && c > 100U) return PROTOCOL_INVALID;
    switch (frame->id) {
    case 0x100U:
        state->voltage_mv = (uint32_t)a * 10U;
        /* Avoid implementation-defined unsigned-to-signed conversion on the host. */
        state->current_ma = (b < 0x8000U ? (int32_t)b : (int32_t)b - 65536) * 10;
        state->remaining_mah = (uint32_t)c * 10U;
        break;
    case 0x101U: state->full_mah = (uint32_t)a * 10U; state->cycles = b; state->soc_percent = c; break;
    case 0x102U: state->balance_low = a; state->balance_high = b; state->protection = c; break;
    case 0x103U: state->mos_status = a; state->production_date_raw = b; state->software_version = c; break;
    case 0x105U:
        state->temperature_decic[0] = (int32_t)a - 2731;
        state->temperature_decic[1] = (int32_t)b - 2731;
        state->temperature_decic[2] = (int32_t)c - 2731;
        break;
    default: return PROTOCOL_IGNORED;
    }
    *query_index = index;
    return PROTOCOL_OK;
}
