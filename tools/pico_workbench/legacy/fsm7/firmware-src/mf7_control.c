#include "mf7_control.h"
#include <math.h>
#include <string.h>

enum {
    ALL = (1U << MF7_COUNT) - 1U, KEEP_LIMIT_MS = 350, MAX_RUN_MS = 15000,
    ENABLE_GAP_MS = 180, START_LIMIT_MS = 5500, MODE_LIMIT_MS = 350,
    STOP_LIMIT_MS = 750, UID_TIMEOUT_MS = 400, UID_GAP_MS = 25
};

static void transition(Mf7 *f, Mf7State s, uint32_t now, const char *reason) {
    f->state = f->target = s;
    f->entered_ms = now;
    f->reason = reason;
}

void Mf7_Init(Mf7 *f) {
    memset(f, 0, sizeof *f);
    MotorNetwork_Init(&f->net);
    f->kd_milli = MF7_KD_DEFAULT_MILLI;
    transition(f, MF7_SELF_CHECK, 0, "READ_UID");
}

const char *Mf7_Name(Mf7State s) {
    static const char *const names[] = {"SELF_CHECK", "READY", "STARTING", "ZERO_TORQUE",
        "DAMPING", "DEBUG_RESERVED", "STOPPING", "FAULT_LOCKED"};
    return (unsigned)s < sizeof names / sizeof names[0] ? names[s] : "UNKNOWN";
}

unsigned Mf7_Ready(const Mf7 *f, uint32_t now) {
    if (f->state != MF7_READY || !f->stop_confirmed) return 0;
    unsigned n = 0;
    for (unsigned i = 0; i < MF7_COUNT; ++i) {
        const RobotMotor *m = &f->net.motors[i];
        n += m->position_seen && m->velocity_seen &&
             now - m->position_ms < 500U && now - m->velocity_ms < 500U &&
             fabsf(m->measured_velocity) <= 0.1f && fabsf(m->measured_position) <= 1000.0f;
    }
    return n;
}

unsigned Mf7_Active(const Mf7 *f) {
    unsigned n = 0;
    for (unsigned i = 0; i < MF7_COUNT; ++i) n += f->net.motors[i].phase == MOTOR_ACTIVE;
    return n;
}

unsigned Mf7_Stopped(const Mf7 *f) {
    if (f->stop_confirmed) return MF7_COUNT;
    if (!f->uid_complete || !f->net.fault_latched) return 0;
    unsigned n = 0;
    for (unsigned i = 0; i < MF7_COUNT; ++i) n += !(f->net.stop_pending & (1U << i));
    return n;
}

static void halt_to(Mf7 *f, uint32_t now, const char *reason, Mf7State after) {
    if (f->state == MF7_FAULT_LOCKED) return;
    if (f->state == MF7_STOPPING) {
        if (after == MF7_FAULT_LOCKED && f->after_stop != MF7_FAULT_LOCKED) {
            f->reason = reason;
            f->after_stop = after;
        }
        return;
    }
    if (!f->uid_complete) {
        transition(f, MF7_FAULT_LOCKED, now, reason);
        return;
    }
    f->stop_confirmed = false;
    if (f->state == MF7_DEBUG_RESERVED) f->net.fault_latched = false;
    MotorNetwork_StopAllCode(&f->net, now, MOTOR_STOP_REQUEST, 0);
    transition(f, MF7_STOPPING, now, reason);
    f->after_stop = after;
}

void Mf7_Halt(Mf7 *f, uint32_t now, const char *reason) {
    f->resume_mode = MF7_SELF_CHECK;
    halt_to(f, now, reason, MF7_FAULT_LOCKED);
}

static bool leased(const Mf7 *f, uint32_t now) {
    return f->heartbeat_seen && now - f->heartbeat_ms <= KEEP_LIMIT_MS;
}

Mf7KdResult Mf7_SetKd(Mf7 *f, unsigned milli, uint32_t now) {
    if (milli > MF7_KD_MAX_MILLI || milli % MF7_KD_STEP_MILLI)
        return MF7_KD_OUT_OF_RANGE;
    if (!leased(f, now) || f->net.fault_latched || f->target != f->state ||
        !((f->state == MF7_READY && Mf7_Ready(f, now) == MF7_COUNT) ||
          (f->state == MF7_ZERO_TORQUE && Mf7_Active(f) == MF7_COUNT)))
        return MF7_KD_NOT_READY;
    f->kd_milli = (uint16_t)milli;
    return MF7_KD_ACCEPTED;
}

static bool quiet(const Mf7 *f, uint32_t now) {
    for (unsigned i = 0; i < MF7_COUNT; ++i)
        if (f->net.motors[i].phase != MOTOR_ACTIVE || !f->net.motors[i].feedback_seen ||
            now - f->net.motors[i].feedback_ms > ROBOT_FEEDBACK_TIMEOUT_MS ||
            fabsf(f->net.motors[i].feedback.velocity) > 0.15f) return false;
    return true;
}

static void request_mode(Mf7 *f, Mf7State s, uint32_t now) {
    f->target = s;
    f->entered_ms = now;
    f->submitted = 0;
    f->reason = "MODE_PENDING";
}

static void start_group(Mf7 *f, uint32_t now) {
    f->arm_count = 0;
    f->arm_ms = f->next_arm_ms = now;
    f->stop_confirmed = false;
    transition(f, MF7_STARTING, now, "ARMING");
}

void Mf7_Command(Mf7 *f, const char *cmd, uint32_t now) {
    if (strcmp(cmd, "KEEP") == 0) {
        f->heartbeat_ms = now;
        f->heartbeat_seen = true;
        return;
    }
    if (strcmp(cmd, "STOP") == 0) {
        Mf7_Halt(f, now, "STOP_REQUEST");
        return;
    }
    if (!leased(f, now)) return;

    if (strcmp(cmd, "ARM") == 0 && Mf7_Ready(f, now) == MF7_COUNT) {
        start_group(f, now);
    } else if (f->state == MF7_DEBUG_RESERVED && f->stop_confirmed &&
               (strcmp(cmd, "ZERO") == 0 || strcmp(cmd, "DAMP") == 0)) {
        /* This specific operator request authorizes re-enable after fresh preflight. */
        const Mf7State destination = strcmp(cmd, "DAMP") == 0 ? MF7_DAMPING : MF7_ZERO_TORQUE;
        const uint32_t generation = f->net.stop_generation;
        const uint16_t kd_milli = f->kd_milli;
        Mf7_Init(f);
        f->net.stop_generation = generation;
        f->kd_milli = kd_milli;
        f->heartbeat_ms = now;
        f->heartbeat_seen = true;
        f->uid_ms = f->resume_ms = now;
        f->resume_mode = destination;
    } else if (f->state == MF7_ZERO_TORQUE || f->state == MF7_DAMPING) {
        if (strcmp(cmd, "DEBUG") == 0) {
            halt_to(f, now, "DEBUG_REQUEST", MF7_DEBUG_RESERVED);
        } else if (strcmp(cmd, "ZERO") == 0) {
            if (f->target != MF7_ZERO_TORQUE) request_mode(f, MF7_ZERO_TORQUE, now);
        } else if (strcmp(cmd, "DAMP") == 0 && f->state == MF7_ZERO_TORQUE &&
                   f->target == f->state) {
            if (quiet(f, now)) request_mode(f, MF7_DAMPING, now);
            else f->reason = "MOTORS_MOVING";
        }
    }
}

void Mf7_OnFrame(Mf7 *f, const CanFrame *frame) {
    if (!CanFrame_IsValid(frame) || !frame->extended || frame->remote || frame->dlc != 8U) return;
    const uint8_t type = (uint8_t)(frame->id >> 24), id = (uint8_t)(frame->id >> 8);
    const uint8_t dest = (uint8_t)frame->id;
    const uint32_t now = frame->timestamp_ms;
    if (!id || id > MF7_COUNT) return;
    if (type == 0U && (dest == 0xFEU || dest == ROBOT_HOST_ID)) {
        if (id <= f->uid_count && memcmp(f->uid[id - 1U], frame->data, 8) != 0) {
            Mf7_Halt(f, now, "UID_CONFLICT");
            return;
        }
        if (f->state != MF7_SELF_CHECK || id != f->uid_count + 1U ||
            !f->uid_waiting || (int32_t)(now - f->uid_ms) < 0) return;
        uint8_t bits = 0, inverted = 0;
        for (unsigned i = 0; i < 8; ++i) {
            bits |= frame->data[i];
            inverted |= (uint8_t)~frame->data[i];
        }
        if (!bits || !inverted ||
            (f->uid_reads && memcmp(f->uid[id - 1U], frame->data, 8) != 0)) {
            Mf7_Halt(f, now, "UID_CONFLICT");
            return;
        }
        for (unsigned i = 0; i < f->uid_count; ++i)
            if (memcmp(f->uid[i], frame->data, 8) == 0) {
                Mf7_Halt(f, now, "UID_CONFLICT");
                return;
            }
        memcpy(f->uid[id - 1U], frame->data, 8);
        if (++f->uid_reads == 2U) {
            ++f->uid_count;
            f->uid_reads = 0;
        }
        f->uid_waiting = false;
        f->uid_ms = now;
        return;
    }
    if (!f->uid_complete || dest != ROBOT_HOST_ID || f->state == MF7_FAULT_LOCKED) return;
    if (type == 17U && ((frame->id >> 16) & 0xFFU) != 0U) return; // rejected readback
    RsFeedback fb;
    if (type == 2U && RsMotor_Feedback(&robot_motor_config[id - 1U], frame, &fb)) {
        if ((f->state == MF7_READY || f->state == MF7_DEBUG_RESERVED) && fb.mode == 2U) {
            Mf7_Halt(f, now, "UNEXPECTED_ENABLE");
            return;
        }
        ++f->feedback_seq[id - 1U];
    }
    if (f->state != MF7_DEBUG_RESERVED) MotorNetwork_OnFrame(&f->net, MF7_BUS, frame);
}

typedef struct {
    Mf7 *f;
    RobotMotorSend send;
    void *ctx;
} Gate;

static bool gate(void *ctx, uint8_t bus, const CanFrame *frame, uint32_t now) {
    Gate *g = ctx;
    if (bus != MF7_BUS || !g->f->uid_complete) return false;
    const uint8_t type = (uint8_t)(frame->id >> 24), id = (uint8_t)frame->id;
    if (!id || id > MF7_COUNT || !g->send(g->ctx, bus, frame, now)) return false;
    Mf7 *f = g->f;
    if (type == 1U && f->target != f->state && f->net.motors[id-1U].phase == MOTOR_ACTIVE &&
        !(f->submitted & (1U << (id-1U)))) {
        f->apply_feedback[id-1U] = f->feedback_seq[id-1U];
        f->submitted |= (uint8_t)(1U << (id-1U));
    }
    return true;
}

static const char *network_reason(const MotorNetwork *n) {
    switch (n->stop_reason) {
        case MOTOR_STOP_FEEDBACK_AGE: return "FEEDBACK_LOST";
        case MOTOR_STOP_MOTOR_FAULT: return "MOTOR_FAULT";
        case MOTOR_STOP_EFFORT: return "EFFORT_LIMIT";
        case MOTOR_STOP_HANDSHAKE: return "HANDSHAKE_FAILED";
        default: return "MOTOR_NETWORK_STOP";
    }
}

static void service_stop(Mf7 *f, uint32_t now, Gate *g) {
    if (Mf7_Stopped(f) == MF7_COUNT) {
        const char *reason = f->reason;
        f->stop_confirmed = true;
        transition(f, f->after_stop, now, f->after_stop == MF7_READY ? "WAIT_ARM" : reason);
        if (f->state == MF7_READY) {
            /* Keep the generation monotonic for the application's cancel barrier. */
            uint32_t generation = f->net.stop_generation;
            MotorNetwork_Init(&f->net);
            f->net.stop_generation = generation;
        }
        return;
    }
    if (now - f->entered_ms >= STOP_LIMIT_MS) {
        transition(f, MF7_FAULT_LOCKED, now, "STOP_UNCONFIRMED");
        return;
    }
    MotorNetwork_Step(&f->net, now, gate, g);
}

void Mf7_Step(Mf7 *f, uint32_t now, RobotMotorSend send, void *ctx) {
    if (f->have_step && now == f->last_step_ms) return;
    f->have_step = true;
    f->last_step_ms = now;
    Gate g = {f, send, ctx};

    if (f->resume_mode != MF7_SELF_CHECK) {
        if (!leased(f, now)) Mf7_Halt(f, now, "HOST_TIMEOUT");
        else if (now - f->resume_ms >= 10000U) Mf7_Halt(f, now, "MODE_TIMEOUT");
    }

    if (f->state == MF7_SELF_CHECK) {
        if (!leased(f, now)) return;
        if (f->uid_count == MF7_COUNT) {
            f->uid_complete = true;
            halt_to(f, now, "PREFLIGHT_STOP", MF7_READY);
        } else {
            if (f->uid_waiting && now - f->uid_ms >= UID_TIMEOUT_MS) {
                Mf7_Halt(f, now, "UID_TIMEOUT");
            } else if (!f->uid_waiting && now - f->uid_ms >= UID_GAP_MS) {
                CanFrame frame = RsMotor_Simple((uint8_t)(f->uid_count + 1U), 0U);
                if (send(ctx, MF7_BUS, &frame, now)) {
                    f->uid_waiting = true;
                    f->uid_ms = now;
                }
            }
            return;
        }
    }
    if (f->net.fault_latched && f->state != MF7_STOPPING &&
        f->state != MF7_FAULT_LOCKED && f->state != MF7_DEBUG_RESERVED)
        Mf7_Halt(f, now, network_reason(&f->net));
    if (f->state == MF7_STOPPING) {
        service_stop(f, now, &g);
        return;
    }
    if (f->state == MF7_FAULT_LOCKED || f->state == MF7_DEBUG_RESERVED) return;
    if (f->state == MF7_READY) {
        if (leased(f, now)) {
            if (f->resume_mode != MF7_SELF_CHECK && Mf7_Ready(f, now) == MF7_COUNT)
                start_group(f, now);
            else
                MotorNetwork_Step(&f->net, now, gate, &g);
        }
        return;
    }

    if (!leased(f, now)) Mf7_Halt(f, now, "HOST_TIMEOUT");
    else if (now - f->arm_ms >= MAX_RUN_MS) Mf7_Halt(f, now, "MAX_RUN");
    else if (f->state == MF7_STARTING && now - f->arm_ms >= START_LIMIT_MS)
        Mf7_Halt(f, now, "HANDSHAKE_FAILED");
    else if (f->state != MF7_STARTING && f->state != f->target && now - f->entered_ms >= MODE_LIMIT_MS)
        Mf7_Halt(f, now, "MODE_TIMEOUT");

    if (f->state == MF7_STARTING) {
        if (f->arm_count == MF7_COUNT && Mf7_Active(f) == MF7_COUNT) {
            const bool damp = f->resume_mode == MF7_DAMPING;
            f->resume_mode = MF7_SELF_CHECK;
            transition(f, MF7_ZERO_TORQUE, now, "OK");
            if (damp) {
                if (quiet(f, now)) request_mode(f, MF7_DAMPING, now);
                else Mf7_Halt(f, now, "MOTORS_MOVING");
            }
        } else if (f->arm_count < MF7_COUNT && (int32_t)(now - f->next_arm_ms) >= 0 &&
                   Mf7_Active(f) == f->arm_count &&
                   MotorNetwork_Enable(&f->net, f->arm_count + 1U, now)) {
            ++f->arm_count;
            f->next_arm_ms = now + ENABLE_GAP_MS;
        }
    }

    if (f->state == MF7_STARTING || f->state == MF7_ZERO_TORQUE || f->state == MF7_DAMPING) {
        const RsCommand c = {.kd = f->target == MF7_DAMPING ? f->kd_milli / 1000.0f : 0.0f};
        bool applied = f->submitted == ALL;
        for (unsigned i = 0; i < MF7_COUNT; ++i) {
            RobotMotor *m = &f->net.motors[i];
            if (m->phase != MOTOR_ACTIVE) {
                applied = false;
                continue;
            }
            if (now - m->feedback_ms > ROBOT_FEEDBACK_TIMEOUT_MS) {
                Mf7_Halt(f, now, "FEEDBACK_LOST");
                break;
            }
            if (fabsf(m->feedback.velocity) > 1.0f) {
                Mf7_Halt(f, now, "SPEED_LIMIT");
                break;
            }
            if (fabsf(m->feedback.torque) > 0.9f || m->feedback.temperature > 55.0f ||
                !MotorNetwork_SetCommand(&f->net, (uint8_t)(i + 1U), &c, now)) {
                Mf7_Halt(f, now, "EFFORT_LIMIT");
                break;
            }
            applied &= f->feedback_seq[i] != f->apply_feedback[i];
        }
        if (f->state != f->target && f->state != MF7_STOPPING && applied)
            transition(f, f->target, now, "OK");
    }
    if (f->state == MF7_STOPPING) service_stop(f, now, &g);
    else MotorNetwork_Step(&f->net, now, gate, &g);
}
