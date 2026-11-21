#include "Communicate/robot_link.h"
#include <math.h>
#include <string.h>
static uint16_t u16(const uint8_t *p) {
  return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}
static uint32_t u32(const uint8_t *p) {
  return (uint32_t)u16(p) | ((uint32_t)u16(p + 2) << 16);
}
static void w16(uint8_t *p, uint16_t v) {
  p[0] = (uint8_t)v;
  p[1] = (uint8_t)(v >> 8);
}
static void w32(uint8_t *p, uint32_t v) {
  w16(p, (uint16_t)v);
  w16(p + 2, (uint16_t)(v >> 16));
}
static bool due(uint32_t n, uint32_t t) { return (int32_t)(n - t) >= 0; }
uint16_t RobotLink_Crc(const uint8_t *p, uint16_t size) {
  uint16_t c = 0xffff;
  for (unsigned i = 0; i < size; i++) {
    c ^= (uint16_t)p[i] << 8;
    for (unsigned k = 0; k < 8; k++)
      c = (uint16_t)((c & 0x8000) ? (c << 1) ^ 0x1021 : c << 1);
  }
  return c;
}
static bool emit(RobotLink *l, unsigned type, uint32_t seq, const uint8_t *p,
                 uint16_t len, RobotLinkWrite write, void *ctx) {
  uint8_t b[ROBOT_LINK_MAX_PACKET] = {'R', '4', 1, (uint8_t)type};
  w16(b + 4, len);
  w32(b + 6, seq);
  w32(b + 10, l->token);
  if (len)
    memcpy(b + 14, p, len);
  w16(b + 14 + len, RobotLink_Crc(b, (uint16_t)(14 + len)));
  return write(ctx, b, (uint16_t)(16 + len));
}
static bool driving(const MotorNetwork *n) {
  for (unsigned i = 0; i < 14; i++)
    if (n->motors[i].phase != MOTOR_IDLE && n->motors[i].phase != MOTOR_FAULT)
      return true;
  return false;
}
void RobotLink_Init(RobotLink *l, const uint8_t uid[12], uint32_t seed) {
  memset(l, 0, sizeof(*l));
  memcpy(l->uid, uid, 12);
  l->seed = seed;
  l->selected = 1;
}
void RobotLink_TransportFault(RobotLink *l, MotorNetwork *n, uint32_t now) {
  l->bad_frames++;
  l->used = 0;
  if (l->controlled && driving(n))
    MotorNetwork_StopAllCode(n, now, MOTOR_STOP_TRANSPORT, 0);
}
enum {
  SET_REASON_OK = 0,
  SET_REASON_SIZE,
  SET_REASON_MASK,
  SET_REASON_LATCHED,
  SET_REASON_COMMAND,
  SET_REASON_PHASE,
  SET_REASON_HANDSHAKE,
  SET_REASON_NOT_SEEN,
  SET_REASON_AGE,
  SET_REASON_EFFORT,
  SET_REASON_APPLY
};
/* Last rejected batch, reported once in an R14_DEBUG frame before StopAll. */
static uint8_t set_reason, set_motor;
static uint16_t set_age, set_command_age;
static int32_t set_effort_milli;
static bool set_fail(uint8_t reason, unsigned index, uint16_t age,
                     uint16_t command_age, float effort) {
  set_reason = reason;
  set_motor = (uint8_t)(index + 1U);
  set_age = age;
  set_command_age = command_age;
  float scaled = effort * 1000.0f;
  set_effort_milli = scaled > 32767.0f ? 32767 :
                     scaled < -32768.0f ? -32768 : (int32_t)scaled;
  return false;
}
static bool batch(MotorNetwork *n, const uint8_t *p, uint16_t size,
                  uint32_t now) {
  if (size < 2)
    return set_fail(SET_REASON_SIZE, 0, 0, 0, 0);
  uint16_t mask = u16(p);
  if ((mask & 0xc000U) || !mask)
    return set_fail(SET_REASON_MASK, 0, 0, 0, 0);
  if (n->fault_latched)
    return set_fail(SET_REASON_LATCHED, 0, 0, 0, 0);
  unsigned count = 0;
  for (unsigned i = 0; i < 14; i++)
    if (mask & (1U << i))
      count++;
  if (size != 2 + 10 * count)
    return set_fail(SET_REASON_SIZE, 0, 0, 0, 0);
  RsCommand commands[14];
  unsigned offset = 2;
  /* Validate the WHOLE batch before committing any target. */
  for (unsigned i = 0; i < 14; i++)
    if (mask & (1U << i)) {
      float v[5];
      for (unsigned k = 0; k < 5; k++)
        v[k] = (float)(int16_t)u16(p + offset + 2 * k) / 1000.0f;
      offset += 10;
      commands[i] = (RsCommand){v[0], v[1], v[2], v[3], v[4]};
      RobotMotor *m = &n->motors[i];
      uint16_t age = (uint16_t)(now - m->feedback_ms);
      uint16_t cmd_age = (uint16_t)(now - m->command_ms);
      CanFrame f;
      if (!RsMotor_Command(&robot_motor_config[i], &commands[i], &f))
        return set_fail(SET_REASON_COMMAND, i, age, cmd_age, 0);
      if (m->phase == MOTOR_ACTIVE) {
        float effort = fabsf(v[2]) + v[3] * fabsf(v[0] - m->feedback.position) +
                       v[4] * fabsf(v[1] - m->feedback.velocity);
        if (!m->feedback_seen)
          return set_fail(SET_REASON_NOT_SEEN, i, age, cmd_age, effort);
        if (now - m->feedback_ms > ROBOT_FEEDBACK_TIMEOUT_MS)
          return set_fail(SET_REASON_AGE, i, age, cmd_age, effort);
        if (effort > 2.0f)
          return set_fail(SET_REASON_EFFORT, i, age, cmd_age, effort);
      } else {
        if (m->phase == MOTOR_IDLE || m->phase == MOTOR_FAULT ||
            !m->enable_after_stop)
          return set_fail(SET_REASON_PHASE, i, age, cmd_age, 0);
        for (unsigned k = 0; k < 5; k++)
          if (v[k] != 0.0f)
            return set_fail(SET_REASON_HANDSHAKE, i, age, cmd_age, 0);
      }
    }
  for (unsigned i = 0; i < 14; i++)
    if ((mask & (1U << i)) && n->motors[i].phase == MOTOR_ACTIVE)
      if (!MotorNetwork_SetCommand(n, (uint8_t)(i + 1), &commands[i], now))
        return set_fail(SET_REASON_APPLY, i,
                        (uint16_t)(now - n->motors[i].feedback_ms),
                        (uint16_t)(now - n->motors[i].command_ms), 0);
  return true;
}
static void debug_frame(RobotLink *l, MotorNetwork *n, uint32_t now,
                        uint8_t kind, RobotLinkWrite write, void *ctx) {
  uint8_t d[10] = {0};
  uint8_t reason = kind == 1U ? n->stop_reason : set_reason;
  uint8_t motor = kind == 1U ? n->stop_motor : set_motor;
  RobotMotor *m = motor >= 1 && motor <= 14 ? &n->motors[motor - 1] : NULL;
  d[0] = kind;
  d[1] = reason;
  d[2] = motor;
  d[3] = m ? (uint8_t)m->phase : 0xffU;
  w16(d + 4, m ? (uint16_t)(now - m->feedback_ms) : 0);
  w16(d + 6, m ? (uint16_t)(now - m->command_ms) : 0);
  w16(d + 8, kind == 2U ? (uint16_t)(int16_t)set_effort_milli : 0);
  (void)emit(l, R14_DEBUG, now, d, sizeof(d), write, ctx);
}
static void process(RobotLink *l, MotorNetwork *n, uint32_t now,
                    RobotLinkWrite write, void *ctx) {
  const uint8_t *b = l->bytes, *p = b + 14;
  uint16_t len = u16(b + 4);
  uint32_t seq = u32(b + 6), token = u32(b + 10);
  uint8_t type = b[3];
  bool ok = false;
  if (type == R14_STOP && !len) {
    MotorNetwork_StopAllCode(n, now, MOTOR_STOP_REQUEST, 0);
    l->controlled = 0;
    ok = true;
  } else if (type == R14_HELLO && !len && token) {
    if (!l->session || token != l->host_nonce) {
      /* A new client must never inherit a running controller. */
      if (driving(n))
        MotorNetwork_StopAllCode(n, now, MOTOR_STOP_NEW_SESSION, 0);
      l->seed = l->seed * 1664525U + 1013904223U + now + token;
      l->token = l->seed ? l->seed : 1;
      l->host_nonce = token;
      l->sequence = 0;
      l->controlled = 0;
      l->session = true;
    }
    l->host_ms = now;
    uint8_t info[28];
    w32(info, l->host_nonce);
    memcpy(info + 4, l->uid, 12);
    w32(info + 16, 160000000);
    w32(info + 20, ROBOT_LINK_SIGNATURE);
    w16(info + 24, ROBOT_COMMAND_LEASE_MS);
    w16(info + 26, 200);
    (void)emit(l, R14_INFO, seq, info, 28, write, ctx);
    return;
  } else if (l->session && token == l->token && seq != 0 &&
             (int32_t)(seq - l->sequence) > 0) {
    l->sequence = seq;
    if (type == R14_PING && !len)
      ok = true;
    else if (type == R14_ENABLE && len == 1 && p[0] >= 1 && p[0] <= 14) {
      ok = MotorNetwork_Enable(n, p[0], now);
      if (ok) {
        l->controlled |= (uint16_t)(1U << (p[0] - 1));
        l->selected = p[0];
      }
    } else if (type == R14_DISABLE && len == 1) {
      ok = p[0] >= 1 && p[0] <= 14 && (l->controlled & (1U << (p[0] - 1))) &&
           MotorNetwork_Disable(n, p[0], now);
      /* Keep ownership until STOP_WAIT has actually confirmed idle. */
    } else if (type == R14_SELECT && len == 1 && p[0] >= 1 && p[0] <= 14) {
      l->selected = p[0];
      ok = true;
    } else if (type == R14_SET) {
      if (len < 2 || (u16(p) & ~l->controlled))
        set_fail(SET_REASON_MASK, 0, 0, 0, 0);
      else
        ok = batch(n, p, len, now);
      if (!ok) {
        debug_frame(l, n, now, 2, write, ctx);
        if (l->controlled && driving(n))
          MotorNetwork_StopAllCode(n, now, MOTOR_STOP_SET_REJECT, set_motor);
      }
    }
    if (ok)
      l->host_ms = now;
  }
  if (!ok)
    l->rejected++;
  if (type != R14_PING && type != R14_SELECT && (type != R14_SET || !ok)) {
    uint8_t ack[3] = {type, ok ? 0 : 1, len == 1 ? p[0] : 0};
    (void)emit(l, R14_ACK, seq, ack, 3, write, ctx);
  }
}
void RobotLink_Feed(RobotLink *l, MotorNetwork *n, uint8_t byte, uint32_t now,
                    RobotLinkWrite write, void *ctx) {
  if (l->used && now - l->partial_ms > 50) {
    l->bad_frames++;
    l->used = 0;
  }
  if (!l->used)
    l->partial_ms = now;
  l->bytes[l->used++] = byte;
  for (;;) {
    if (l->used < 2)
      return;
    if (l->bytes[0] != 'R' || l->bytes[1] != '4' ||
        (l->used >= 3 && l->bytes[2] != 1)) {
      memmove(l->bytes, l->bytes + 1, --l->used);
      continue;
    }
    if (l->used < 6)
      return;
    uint16_t len = u16(l->bytes + 4);
    if (len > ROBOT_LINK_MAX_PAYLOAD) {
      l->bad_frames++;
      memmove(l->bytes, l->bytes + 1, --l->used);
      continue;
    }
    uint16_t total = (uint16_t)(16 + len);
    if (l->used < total)
      return;
    if (RobotLink_Crc(l->bytes, (uint16_t)(total - 2)) !=
        u16(l->bytes + total - 2)) {
      l->bad_frames++;
      memmove(l->bytes, l->bytes + 1, --l->used);
      continue;
    }
    process(l, n, now, write, ctx);
    l->used -= total;
    memmove(l->bytes, l->bytes + total, l->used);
  }
}
static uint16_t age(uint32_t now, uint32_t then, bool seen) {
  uint32_t a = now - then;
  return !seen || a > 65534 ? 65535 : (uint16_t)a;
}
static int32_t milli(float f) {
  if (!isfinite(f))
    return 0;
  double d = (double)f * 1000.0;
  if (d > 2147483647.0)
    return INT32_MAX;
  if (d < -2147483648.0)
    return INT32_MIN;
  return (int32_t)d;
}
static void node(RobotLink *l, MotorNetwork *n, unsigned i, uint32_t now,
                 RobotLinkWrite write, void *ctx) {
  RobotMotor *m = &n->motors[i];
  const RsMotorConfig *c = &robot_motor_config[i];
  uint8_t b[46] = {
      c->id, c->bus,           (uint8_t)c->model,  (uint8_t)m->phase,
      0,     m->feedback.mode, m->feedback.faults, 0};
  bool active = m->phase == MOTOR_ACTIVE;
  b[4] = (m->position_seen ? 1 : 0) | (m->velocity_seen ? 2 : 0) |
         (m->feedback_seen ? 4 : 0) | (active ? 8 : 0);
  w32(b + 8,
      (uint32_t)milli(active ? m->feedback.position : m->measured_position));
  w32(b + 12,
      (uint32_t)milli(active ? m->feedback.velocity : m->measured_velocity));
  w32(b + 16, (uint32_t)milli(m->feedback.torque));
  w16(b + 20, (uint16_t)(milli(m->feedback.temperature) / 100));
  const float v[5] = {m->command.position, m->command.velocity,
                      m->command.torque, m->command.kp, m->command.kd};
  for (unsigned k = 0; k < 5; k++)
    w16(b + 22 + 2 * k, (uint16_t)(int16_t)milli(v[k]));
  w16(b + 32, age(now, m->feedback_ms, m->feedback_seen));
  w16(b + 34, age(now, m->position_ms, m->position_seen));
  w32(b + 36, m->fault_word);
  w32(b + 40, m->warning_word);
  w16(b + 44, age(now, m->velocity_ms, m->velocity_seen));
  (void)emit(l, R14_NODE, now, b, 46, write, ctx);
}
void RobotLink_Step(RobotLink *l, MotorNetwork *n, const RobotLinkHealth *h,
                    uint32_t now, RobotLinkWrite write, void *ctx) {
  for (unsigned i = 0; i < 14; i++)
    if (n->motors[i].phase == MOTOR_IDLE)
      l->controlled &= (uint16_t) ~(1U << i);
  if (l->session && l->controlled && now - l->host_ms > ROBOT_LINK_HOST_MS) {
    MotorNetwork_StopAllCode(n, now, MOTOR_STOP_HOST_LEASE, 0);
    l->controlled = 0; /* Keep telemetry alive to report the latched stop. */
  }
  if (!l->session)
    return;
  if (n->fault_latched && !l->latched_reported) {
    l->latched_reported = true;
    debug_frame(l, n, now, 1, write, ctx);
  }
  if (due(now, l->next_node)) {
    node(l, n, l->cursor, now, write, ctx);
    l->cursor = (l->cursor + 1) % 14;
    l->next_node = now + 10;
  }
  if (due(now, l->next_selected)) {
    node(l, n, l->selected - 1U, now, write, ctx);
    l->next_selected = now + 40;
  }
  if (due(now, l->next_state)) {
    uint8_t b[95];
    w32(b, now);
    b[4] = n->fault_latched;
    w16(b + 5, n->stop_pending);
    w32(b + 7, h->rejected + l->rejected);
    w32(b + 11, h->overruns);
    w32(b + 15, l->bad_frames);
    w32(b + 19, h->bms_valid);
    w32(b + 23, h->power_valid);
    w32(b + 27, h->bms_mv);
    w32(b + 31, h->power_mv);
    unsigned off = 35;
    for (unsigned bus = 0; bus < 3; bus++)
      for (unsigned k = 0; k < 5; k++, off += 4)
        w32(b + off, h->can[bus][k]);
    (void)emit(l, R14_STATE, now, b, 95, write, ctx);
    l->next_state = now + 200;
  }
}
