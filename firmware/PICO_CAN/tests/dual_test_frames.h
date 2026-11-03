#ifndef DUAL_TEST_FRAMES_H
#define DUAL_TEST_FRAMES_H
#include "dual_device_reader.h"
#include <string.h>
/* Representative replies for scheduler/glue tests, not hardware measurements. */
static CanFrame dual_test_reply(ReaderKind kind, uint8_t job, uint32_t now) {
    CanFrame f = {.dlc=8, .timestamp_ms=now};
    if (kind == READER_BMS) {
        static const uint8_t words[5][6] = {
            {0x11,0xEA,0,0,0x01,0xE4}, {0x04,0xB0,0,0,0,40},
            {0,0,0,0,0,0}, {0,3,0x35,0x3C,0,36},
            {0x0B,0x82,0x0B,0x7E,0x0B,0x81}
        };
        f.id = bms_query_ids[job];
        memcpy(f.data, words[job], 6);
        uint16_t crc = Bms_Crc16(f.data, 6);
        f.data[6] = (uint8_t)(crc >> 8); f.data[7] = (uint8_t)crc;
    } else {
        uint8_t type = job == 0U ? 5U : job == 1U ? 3U : job == 2U ? 4U : 7U;
        f.id = ((uint32_t)type << 24) | 0x00AA0000U;
        f.extended = true;
        if (job == 0U) memcpy(f.data, "V1.08", 5);
        if (job >= 3U) {
            uint16_t parameter = power_parameter_indices[job - 3U];
            f.data[0] = (uint8_t)parameter; f.data[1] = (uint8_t)(parameter >> 8);
            f.data[4] = parameter == POWER_CAN_BAUD_INDEX ? 2U : 1U;
        }
    }
    return f;
}
#endif
