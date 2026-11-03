#ifndef PICO_DEVICE_READER_H
#define PICO_DEVICE_READER_H
#include "protocol/bms_protocol.h"
#include "protocol/power_protocol.h"

typedef enum { READER_BMS, READER_POWER } ReaderKind;
typedef struct {
    ReaderKind kind;
    uint8_t power_id, bms_rtr_dlc, max_attempts;
    ProtocolByteOrder bms_crc_order, power_status_order;
    uint32_t timeout_ms, interval_ms, stale_ms;
} ReaderConfig;
typedef struct {
    uint32_t tx_submitted, tx_rejected, replies, invalid, ignored;
    uint32_t timeouts, query_failures, cycles;
} ReaderStats;
typedef struct {
    ReaderConfig config;
    ReaderStats stats;
    BmsState bms;
    PowerState power;
    uint32_t last_ok_ms[(BMS_QUERY_COUNT > POWER_QUERY_COUNT) ? BMS_QUERY_COUNT : POWER_QUERY_COUNT], seen_mask, valid_mask;
    uint32_t sent_at, next_due;
    uint8_t query_index, attempts;
    bool pending;
} DeviceReader;
typedef bool (*ReaderSend)(void *context, const CanFrame *frame, uint32_t now);
bool DeviceReader_Init(DeviceReader *reader, const ReaderConfig *config, uint32_t now);
/* Age freshness without scheduling or retrying a request. */
void DeviceReader_Age(DeviceReader *reader, uint32_t now);
void DeviceReader_Step(DeviceReader *reader, uint32_t now, ReaderSend send, void *context);
/* Returns the accepted query index or -1. Timestamp must be local receive time. */
int DeviceReader_OnFrame(DeviceReader *reader, const CanFrame *frame);
#endif
