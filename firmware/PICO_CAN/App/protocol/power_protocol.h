#ifndef PICO_POWER_PROTOCOL_H
#define PICO_POWER_PROTOCOL_H
#include "can_frame.h"

#define POWER_PARAMETER_COUNT 9U
#define POWER_QUERY_COUNT (3U + POWER_PARAMETER_COUNT)
#define POWER_ALL_FRESH_MASK ((1UL << POWER_QUERY_COUNT) - 1UL)
extern const uint16_t power_parameter_indices[POWER_PARAMETER_COUNT];
extern const char *const power_parameter_names[POWER_PARAMETER_COUNT];
typedef struct {
    uint8_t raw[4]; /* Never discard unexpected trailing bytes in uint8 parameters. */
    uint8_t value_u8;
    bool upper_bytes_nonzero;
    bool numeric_valid; /* Does not guarantee units or physical correctness. */
    uint32_t bits_le;
    float value_float;
} PowerParameter;
#define POWER_CAN_BAUD_INDEX 0x6001U
/* Order: version, status03, status04, then the nine read-only parameter indices. */
typedef struct {
    char version[9];
    uint8_t status03_raw[8], status04_raw[8];
    uint32_t status03_id, status04_id;
    uint8_t temperature_c;
    bool numeric_status_confirmed;
    uint32_t battery_mv, motor_mv, fault_and_switch_bits;
    uint32_t branch_current_ma[4];
    uint32_t can_baud_code;
    PowerParameter parameters[POWER_PARAMETER_COUNT];
    bool reported_id_mismatch; /* Parameter 0x6006 differs from actual reply source. */
    /* Type03 ID contains contradictory current-field descriptions: never decode it. */
} PowerState;

bool Power_BuildQuery(uint8_t device_id, uint8_t query_index, CanFrame *frame);
ProtocolResult Power_Parse(const CanFrame *frame, uint8_t device_id,
                           ProtocolByteOrder status_order, PowerState *state,
                           uint8_t *query_index);
#endif
