#include "device_reader.h"
#include <string.h>

static bool due(uint32_t now, uint32_t deadline) { return (int32_t)(now - deadline) >= 0; }
static uint8_t count(const DeviceReader *r) {
    return r->config.kind == READER_BMS ? BMS_QUERY_COUNT : POWER_QUERY_COUNT;
}
static void advance(DeviceReader *r, uint32_t now) {
    r->pending = false;
    r->attempts = 0;
    if (++r->query_index == count(r)) { r->query_index = 0; ++r->stats.cycles; }
    r->next_due = now + r->config.interval_ms;
}
bool DeviceReader_Init(DeviceReader *r, const ReaderConfig *c, uint32_t now) {
    if (r == NULL || c == NULL || (c->kind != READER_BMS && c->kind != READER_POWER) ||
        (c->bms_rtr_dlc != 0U && c->bms_rtr_dlc != 8U) || c->max_attempts == 0U ||
        (c->bms_crc_order != BYTE_ORDER_BIG && c->bms_crc_order != BYTE_ORDER_LITTLE) ||
        c->power_status_order > BYTE_ORDER_LITTLE || c->timeout_ms == 0U ||
        c->interval_ms == 0U || c->stale_ms < c->timeout_ms ||
        c->timeout_ms >= 0x80000000U || c->interval_ms >= 0x80000000U || c->stale_ms >= 0x80000000U)
        return false;
    memset(r, 0, sizeof(*r));
    r->config = *c;
    r->next_due = now + 1000U; /* Open the logger before reset; allow startup to settle. */
    return true;
}
void DeviceReader_Age(DeviceReader *r, uint32_t now) {
    for (uint8_t i = 0; i < count(r); ++i)
        if ((r->valid_mask & (1UL << i)) && (uint32_t)(now - r->last_ok_ms[i]) > r->config.stale_ms)
            r->valid_mask &= ~(1UL << i);
}
void DeviceReader_Step(DeviceReader *r, uint32_t now, ReaderSend send, void *context) {
    DeviceReader_Age(r, now);
    if (r->pending) {
        if ((uint32_t)(now - r->sent_at) < r->config.timeout_ms) return;
        ++r->stats.timeouts;
        r->pending = false;
        if (r->attempts >= r->config.max_attempts) {
            ++r->stats.query_failures;
            advance(r, now);
            return;
        }
        r->next_due = now + r->config.interval_ms;
    }
    if (!due(now, r->next_due)) return;
    CanFrame request;
    const bool built = r->config.kind == READER_BMS ?
        Bms_BuildQuery(bms_query_ids[r->query_index], r->config.bms_rtr_dlc, &request) :
        Power_BuildQuery(r->config.power_id, r->query_index, &request);
    ++r->attempts;
    if (built && send != NULL && send(context, &request, now)) {
        ++r->stats.tx_submitted;
        r->sent_at = now;
        r->pending = true;
    } else {
        ++r->stats.tx_rejected;
        if (r->attempts >= r->config.max_attempts) { ++r->stats.query_failures; advance(r, now); }
        else r->next_due = now + r->config.interval_ms;
    }
}
int DeviceReader_OnFrame(DeviceReader *r, const CanFrame *frame) {
    if (frame == NULL) { ++r->stats.invalid; return -1; }
    uint8_t index = 0;
    const ProtocolResult result = r->config.kind == READER_BMS ?
        Bms_Parse(frame, r->config.bms_crc_order, &r->bms, &index) :
        Power_Parse(frame, r->config.power_id, r->config.power_status_order, &r->power, &index);
    if (result == PROTOCOL_INVALID) { ++r->stats.invalid; return -1; }
    if (result == PROTOCOL_IGNORED) { ++r->stats.ignored; return -1; }
    ++r->stats.replies;
    r->last_ok_ms[index] = frame->timestamp_ms;
    r->seen_mask |= 1UL << index;
    r->valid_mask |= 1UL << index;
    /* A stale queued frame cannot complete a request submitted after it arrived.
       These protocols have no transaction token: a late response to a retry
       cannot be distinguished from a response to the current attempt. */
    if (r->pending && index == r->query_index &&
        (uint32_t)(frame->timestamp_ms - r->sent_at) < r->config.timeout_ms)
        advance(r, frame->timestamp_ms);
    return (int)index;
}
