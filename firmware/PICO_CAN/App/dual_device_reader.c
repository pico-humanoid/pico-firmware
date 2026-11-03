#include "dual_device_reader.h"
#include <string.h>

bool DualDeviceReader_Init(DualDeviceReader *pair, const ReaderConfig *bms,
                           const ReaderConfig *power, uint32_t now) {
    if (pair == NULL || bms == NULL || power == NULL ||
        bms->kind != READER_BMS || power->kind != READER_POWER) return false;
    memset(pair, 0, sizeof(*pair));
    if (!DeviceReader_Init(&pair->bms, bms, now) ||
        !DeviceReader_Init(&pair->power, power, now)) return false;
    pair->next_due = now + 1000U;
    return true;
}
void DualDeviceReader_Age(DualDeviceReader *pair, uint32_t now) {
    DeviceReader_Age(&pair->bms, now);
    DeviceReader_Age(&pair->power, now);
}
void DualDeviceReader_Step(DualDeviceReader *pair, uint32_t now,
                           ReaderSend send, void *context) {
    DualDeviceReader_Age(pair, now);
    /* Handle the outstanding request (including timeout/retry scheduling) before
       considering the other device. OnFrame clears pending on a matching reply. */
    if (pair->bms.pending) {
        DeviceReader_Step(&pair->bms, now, send, context);
        return;
    }
    if (pair->power.pending) {
        DeviceReader_Step(&pair->power, now, send, context);
        return;
    }
    if ((int32_t)(now - pair->next_due) < 0) return;
    for (uint8_t n = 0; n < 2U; ++n) {
        uint8_t slot = (pair->next_reader + n) % 2U;
        DeviceReader *reader = slot == 0U ? &pair->bms : &pair->power;
        uint32_t before = reader->stats.tx_submitted + reader->stats.tx_rejected;
        DeviceReader_Step(reader, now, send, context);
        if (reader->stats.tx_submitted + reader->stats.tx_rejected != before) {
            pair->next_reader = 1U - slot;
            pair->next_due = now + reader->config.interval_ms;
            return;
        }
    }
}
