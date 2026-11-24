#include "mf7_control.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    Mf7 f;
    CanFrame reply;
    bool has_reply, drop_feedback, deny_last_stop, bad_watchdog, duplicate_uid;
    uint8_t running[MF7_COUNT], enable_count[MF7_COUNT];
    unsigned controls, stops, enables, starts_after_bad_watchdog;
    uint32_t t, last_enable;
    uint16_t kd[MF7_COUNT];
    bool keep;
} Rig;

static void as_le(uint8_t *dst, uint32_t value) {
    for (unsigned q = 0; q < 4; ++q) dst[q] = (uint8_t)(value >> (q * 8U));
}
static CanFrame feedback(uint8_t id, uint8_t mode) {
    return (CanFrame){.extended = true, .dlc = 8, .id = 0x020000FDU | ((uint32_t)id << 8) | ((uint32_t)mode << 22),
        .data = {127, 255, 127, 255, 127, 255, 1, 4}};
}

static bool peer(void *data, uint8_t bus, const CanFrame *frame, uint32_t now) {
    Rig *r = data;
    unsigned id = frame->id & 255U;
    assert(bus == MF7_BUS && id >= 1U && id <= MF7_COUNT && frame->extended && frame->dlc == 8U);
    unsigned i = id - 1U;
    unsigned type = frame->id >> 24;
    uint16_t index = (uint16_t)((uint16_t)frame->data[1] << 8 | frame->data[0]);
    r->has_reply = false;
    switch (type) {
        case 0:
            r->reply = (CanFrame){.extended = true, .dlc = 8, .id = (id << 8) | 0xFEU,
                .data = {1, 2, 3, 4, 5, 6, 7, r->duplicate_uid ? 0U : (uint8_t)id}};
            r->has_reply = true;
            break;
        case 4:
            assert(r->f.uid_count == MF7_COUNT);
            r->stops++;
            if (r->deny_last_stop && id == MF7_COUNT) break;
            r->running[i] = 0;
            r->reply = feedback((uint8_t)id, 0);
            r->has_reply = true;
            break;
        case 18:
            assert((index == 0x7005 || index == 0x7028) && !r->running[i]);
            break;
        case 17: {
            assert(index == 0x7005 || index == 0x7028 || index == 0x7019 || index == 0x701B);
            r->reply = (CanFrame){.extended = true, .dlc = 8, .id = 0x110000FDU | (id << 8),
                .data = {frame->data[0], frame->data[1]}};
            as_le(r->reply.data + 4, index == 0x7028 && !(r->bad_watchdog && id == 1U) ? ROBOT_DEVICE_WATCHDOG : 0);
            r->has_reply = true;
            break;
        }
        case 1:
            assert((uint16_t)(frame->id >> 8) == 0x7FFF);
            assert(frame->data[0] == 127 && frame->data[1] == 255);
            assert(frame->data[2] == 127 && frame->data[3] == 255); // v_ref=0 encoded
            assert(!frame->data[4] && !frame->data[5]); // Kp=0
            r->kd[i] = (uint16_t)((uint16_t)frame->data[6] << 8 | frame->data[7]);
            if (r->kd[i]) {
                assert(Mf7_Active(&r->f) == MF7_COUNT);
                assert(r->kd[i] == (uint16_t)((r->f.kd_milli / 1000.0f) * 65535.f / 5.f));
            }
            ++r->controls;
            if (r->running[i] && !r->drop_feedback) {
                r->reply = feedback((uint8_t)id, 2);
                r->has_reply = true;
            }
            break;
        case 3:
            assert(r->f.state == MF7_STARTING);
            assert(Mf7_Active(&r->f) == i);
            if (r->enables) assert(now - r->last_enable >= 180U);
            r->last_enable = now;
            r->enables++;
            if (r->bad_watchdog) r->starts_after_bad_watchdog++;
            r->enable_count[i]++;
            r->running[i] = 2;
            r->reply = feedback((uint8_t)id, 2);
            r->has_reply = true;
            break;
        default: assert(false);
    }
    if (r->has_reply) r->reply.timestamp_ms = now + 1U;
    return true;
}
static void advance(Rig *r, uint32_t ticks) {
    for (uint32_t k = 0; k < ticks; ++k) {
        ++r->t;
        if (r->has_reply) {
            r->has_reply = false;
            Mf7_OnFrame(&r->f, &r->reply);
        }
        if (r->keep && r->t % 100U == 0) Mf7_Command(&r->f, "KEEP", r->t);
        Mf7_Step(&r->f, r->t, peer, r);
    }
}
static void init(Rig *r) {
    memset(r, 0, sizeof *r);
    Mf7_Init(&r->f);
    advance(r, 450);
    assert(r->f.state == MF7_SELF_CHECK && !r->controls && !r->stops && !r->enables);
    r->keep = true;
}
static void arm(Rig *r) {
    advance(r, 800);
    assert(Mf7_Ready(&r->f, r->t) == MF7_COUNT && Mf7_Stopped(&r->f) == MF7_COUNT);
    Mf7_Command(&r->f, "DAMP", r->t);
    assert(r->f.state == MF7_READY);
    Mf7_Command(&r->f, "ARM", r->t);
    advance(r, 2100);
    assert(r->f.state == MF7_ZERO_TORQUE && Mf7_Active(&r->f) == MF7_COUNT);
    for (unsigned i = 0; i < MF7_COUNT; ++i) {
        assert(r->enable_count[i] == 1);
        assert(!r->kd[i]);
    }
}

int main(void) {
    Rig r;
    init(&r);
    assert(r.f.kd_milli == MF7_KD_DEFAULT_MILLI);
    assert(Mf7_SetKd(&r.f, 200U, r.t) == MF7_KD_NOT_READY);
    advance(&r, 800);
    assert(Mf7_SetKd(&r.f, 200U, r.t) == MF7_KD_ACCEPTED);
    assert(Mf7_SetKd(&r.f, 801U, r.t) == MF7_KD_OUT_OF_RANGE);
    assert(Mf7_SetKd(&r.f, 351U, r.t) == MF7_KD_OUT_OF_RANGE);
    assert(r.f.kd_milli == 200U);
    arm(&r);
    assert(Mf7_SetKd(&r.f, 800U, r.t) == MF7_KD_ACCEPTED);
    advance(&r, 60);
    for (unsigned i = 0; i < MF7_COUNT; ++i) assert(!r.kd[i]);
    Mf7_Command(&r.f, "DAMP", r.t);
    assert(Mf7_SetKd(&r.f, 500U, r.t) == MF7_KD_NOT_READY);
    assert(r.f.state == MF7_ZERO_TORQUE);
    advance(&r, 60);
    assert(r.f.state == MF7_DAMPING);
    for (unsigned i = 0; i < MF7_COUNT; ++i) assert(r.kd[i] == (uint16_t)(0.8f * 65535.f / 5.f));
    assert(Mf7_SetKd(&r.f, 0U, r.t) == MF7_KD_NOT_READY);
    assert(r.f.kd_milli == 800U);
    Mf7_Command(&r.f, "ZERO", r.t);
    advance(&r, 60);
    assert(r.f.state == MF7_ZERO_TORQUE);
    for (unsigned i = 0; i < MF7_COUNT; ++i) assert(!r.kd[i]);
    Mf7_Command(&r.f, "DEBUG", r.t);
    advance(&r, 200);
    assert(r.f.state == MF7_DEBUG_RESERVED && Mf7_Stopped(&r.f) == MF7_COUNT);
    unsigned controls = r.controls;
    advance(&r, 500);
    assert(r.controls == controls);
    Mf7_Command(&r.f, "ZERO", r.t);
    advance(&r, 2600);
    assert(r.f.state == MF7_ZERO_TORQUE && r.enables == 2U*MF7_COUNT && r.f.kd_milli == 800U);
    Mf7_Command(&r.f, "DEBUG", r.t);
    advance(&r, 200);
    assert(r.f.state == MF7_DEBUG_RESERVED);
    Mf7_Command(&r.f, "DAMP", r.t);
    advance(&r, 2600);
    assert(r.f.state == MF7_DAMPING && r.enables == 3U*MF7_COUNT);
    for (unsigned i = 0; i < MF7_COUNT; ++i) assert(r.kd[i]);

    init(&r);
    arm(&r);
    Mf7_Command(&r.f, "DEBUG", r.t);
    advance(&r, 200);
    r.keep = false;
    Mf7_Command(&r.f, "DAMP", r.t);
    advance(&r, 950);
    assert(r.f.state == MF7_FAULT_LOCKED && r.enables == MF7_COUNT);
    r.keep = true;
    advance(&r, 2800);
    assert(r.enables == MF7_COUNT);

    init(&r);
    arm(&r);
    Mf7_Command(&r.f, "DEBUG", r.t);
    advance(&r, 200);
    Mf7_Command(&r.f, "ZERO", r.t);
    advance(&r, 60);
    Mf7_Command(&r.f, "STOP", r.t);
    advance(&r, 2200);
    assert(r.f.state == MF7_FAULT_LOCKED && r.enables == MF7_COUNT);

    init(&r);
    r.duplicate_uid = true;
    advance(&r, 900);
    assert(r.f.state == MF7_FAULT_LOCKED && strcmp(r.f.reason, "UID_CONFLICT") == 0);
    assert(!r.enables && !r.controls && !r.stops);

    init(&r);
    r.bad_watchdog = true;
    advance(&r, 800);
    Mf7_Command(&r.f, "ARM", r.t);
    advance(&r, 950);
    assert(r.f.state == MF7_FAULT_LOCKED && !r.starts_after_bad_watchdog);

    init(&r);
    arm(&r);
    Mf7_Command(&r.f, "DAMP", r.t);
    advance(&r, 60);
    r.deny_last_stop = true;
    r.drop_feedback = true;
    advance(&r, 1100);
    assert(r.f.state == MF7_FAULT_LOCKED && Mf7_Stopped(&r.f) == 6U);
    assert(strcmp(r.f.reason, "STOP_UNCONFIRMED") == 0);
    controls = r.controls;
    advance(&r, 300);
    assert(r.controls == controls);

    init(&r);
    arm(&r);
    r.keep = false;
    advance(&r, 850);
    assert(r.f.state == MF7_FAULT_LOCKED && Mf7_Stopped(&r.f) == MF7_COUNT);
    assert(strcmp(r.f.reason, "HOST_TIMEOUT") == 0);
    puts("PASS: seven-motor FSM (CAN2 scope, UID, watchdog, damping, stop, host lease)");
}
