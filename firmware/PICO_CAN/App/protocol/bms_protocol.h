#ifndef PICO_BMS_PROTOCOL_H
#define PICO_BMS_PROTOCOL_H
#include "can_frame.h"

#define BMS_QUERY_COUNT 5U
/* Only the documented read-only telemetry IDs; no EEPROM/protection writes. */
extern const uint16_t bms_query_ids[BMS_QUERY_COUNT];
typedef struct {
    uint32_t voltage_mv;
    int32_t current_ma;
    uint32_t remaining_mah, full_mah;
    uint16_t cycles, soc_percent;
    uint16_t balance_low, balance_high, protection;
    uint16_t mos_status, production_date_raw, software_version;
    int32_t temperature_decic[3];
} BmsState;

uint16_t Bms_Crc16(const uint8_t *data, uint8_t length);
bool Bms_BuildQuery(uint16_t id, uint8_t requested_dlc, CanFrame *frame);
ProtocolResult Bms_Parse(const CanFrame *frame, ProtocolByteOrder crc_order,
                         BmsState *state, uint8_t *query_index);
#endif
