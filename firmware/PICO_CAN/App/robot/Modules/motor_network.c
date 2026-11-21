#include "Modules/motor_network.h"
#include <math.h>
#include <string.h>
static bool due(uint32_t now, uint32_t deadline) {
  return (int32_t)(now - deadline) >= 0;
}
static void phase(RobotMotor *m, MotorPhase p, uint32_t now) {
  m->phase = p;
  m->phase_ms = now;
  m->next_tx_ms = now;
}
void MotorNetwork_Init(MotorNetwork *n) { memset(n, 0, sizeof(*n)); }
void MotorNetwork_StopAllCode(MotorNetwork *n, uint32_t now, uint8_t reason,
                              uint8_t motor) {
  if (n->fault_latched)
    return;
  n->fault_latched = true;
  n->stop_reason = reason;
  n->stop_motor = motor;
  n->stop_generation++;
  n->stop_pending = (1U << ROBOT_MOTOR_COUNT) - 1U;
  for (unsigned i = 0; i < ROBOT_MOTOR_COUNT; i++) {
    RobotMotor *m = &n->motors[i];
    memset(&m->command, 0, sizeof(m->command));
    m->enable_after_stop = false;
    m->stop_submitted = false;
    phase(m, MOTOR_FAULT, now);
  }
}
void MotorNetwork_StopAll(MotorNetwork *n, uint32_t now) {
  MotorNetwork_StopAllCode(n, now, MOTOR_STOP_UNKNOWN, 0);
}
bool MotorNetwork_Enable(MotorNetwork *n, uint8_t id, uint32_t now) {
  if (!n || n->fault_latched || id < 1 || id > ROBOT_MOTOR_COUNT)
    return false;
  RobotMotor *m = &n->motors[id - 1];
  if (m->phase != MOTOR_IDLE || !m->position_seen || !m->velocity_seen ||
      now - m->position_ms > 500U || now - m->velocity_ms > 500U ||
      fabsf(m->measured_velocity) > 0.1f ||
      (m->feedback_seen && m->feedback.faults))
    return false;
  m->enable_after_stop = true;
  m->stop_submitted = false;
  m->command = (RsCommand){0};
  phase(m, MOTOR_STOP_WAIT, now);
  return true;
}
bool MotorNetwork_Disable(MotorNetwork *n, uint8_t id, uint32_t now) {
  if (!n || n->fault_latched || id < 1 || id > ROBOT_MOTOR_COUNT)
    return false;
  RobotMotor *m = &n->motors[id - 1];
  if (m->phase == MOTOR_IDLE)
    return true;
  n->stop_generation++; /* Cancel any in-flight control before normal disable.
                         */
  m->enable_after_stop = false;
  m->stop_submitted = false;
  m->command = (RsCommand){0};
  phase(m, MOTOR_STOP_WAIT, now);
  return true;
}
bool MotorNetwork_SetCommand(MotorNetwork *n, uint8_t id, const RsCommand *c,
                             uint32_t now) {
  if (!n || n->fault_latched || id < 1 || id > ROBOT_MOTOR_COUNT || !c)
    return false;
  RobotMotor *m = &n->motors[id - 1];
  CanFrame f;
  if (m->phase != MOTOR_ACTIVE ||
      !RsMotor_Command(&robot_motor_config[id - 1], c, &f))
    return false;
  /* Also bound initial/observed impedance error. These are commissioning
     guards, not a certified torque limit; the plant and quantization still
     matter. */
  float effort = fabsf(c->torque) +
                 c->kp * fabsf(c->position - m->feedback.position) +
                 c->kd * fabsf(c->velocity - m->feedback.velocity);
  if (effort > 2.0f)
    return false;
  m->command = *c;
  m->command_ms = now;
  return true;
}
void MotorNetwork_OnFrame(MotorNetwork *n, uint8_t bus, const CanFrame *f) {
  if (!n || !f || !f->extended || f->remote || !CanFrame_IsValid(f))
    return;
  uint8_t id = (uint8_t)(f->id >> 8);
  const RsMotorConfig *cfg = RsMotor_Find(bus, id);
  if (!cfg)
    return;
  RobotMotor *m = &n->motors[id - 1];
  uint32_t now = f->timestamp_ms;
  RsFeedback fb;
  if (RsMotor_Feedback(cfg, f, &fb)) {
    m->feedback = fb;
    m->feedback_ms = now;
    m->feedback_seen = true;
    m->rx_count++;
    if (fb.faults) {
      MotorNetwork_StopAllCode(n, now, MOTOR_STOP_MOTOR_FAULT, id);
      return;
    }
    if (n->fault_latched) {
      if (fb.mode == 0 && m->stop_submitted && due(now, m->stop_sent_ms))
        n->stop_pending &= (uint16_t) ~(1U << (id - 1));
      return;
    }
    if (m->phase == MOTOR_STOP_WAIT && m->stop_submitted && fb.mode == 0 &&
        due(now, m->stop_sent_ms))
      phase(m, m->enable_after_stop ? MOTOR_MODE_WRITE : MOTOR_IDLE, now);
    else if (m->phase == MOTOR_ENABLE_WAIT && fb.mode == 2 &&
             due(now, m->phase_ms)) {
      phase(m, MOTOR_ACTIVE, now);
      m->command_ms = now;
    } else if (m->phase == MOTOR_ACTIVE && fb.mode != 2)
      MotorNetwork_StopAll(n, now);
    return;
  }
  if ((f->id >> 24) == 21U && (uint8_t)f->id == ROBOT_HOST_ID && f->dlc == 8) {
    m->fault_word = 0;
    m->warning_word = 0;
    for (unsigned i = 0; i < 4; i++) {
      m->fault_word |= (uint32_t)f->data[i] << (8 * i);
      m->warning_word |= (uint32_t)f->data[4 + i] << (8 * i);
    }
    if (m->fault_word)
      MotorNetwork_StopAll(n, now);
    return;
  }
  uint32_t raw;
  if (RsMotor_ReadReply(cfg, f, 0x7019, &raw) ||
      RsMotor_ReadReply(cfg, f, 0x701B, &raw)) {
    float value;
    memcpy(&value, &raw, 4);
    if (!isfinite(value)) {
      m->invalid++;
      return;
    }
    if (f->data[0] == 0x19) {
      m->measured_position = value;
      m->position_ms = now;
      m->position_seen = true;
    } else {
      m->measured_velocity = value;
      m->velocity_ms = now;
      m->velocity_seen = true;
    }
    m->rx_count++;
    return;
  }
  if (m->phase == MOTOR_MODE_WAIT && due(now, m->phase_ms) &&
      RsMotor_ReadReply(cfg, f, 0x7005, &raw)) {
    if (raw != 0)
      MotorNetwork_StopAll(n, now);
    else
      phase(m, MOTOR_WD_WRITE, now);
  } else if (m->phase == MOTOR_WD_WAIT && due(now, m->phase_ms) &&
             RsMotor_ReadReply(cfg, f, 0x7028, &raw)) {
    if (raw != ROBOT_DEVICE_WATCHDOG)
      MotorNetwork_StopAll(n, now);
    else
      phase(m, MOTOR_ZERO, now);
  }
}
static bool send_motor(MotorNetwork *n, unsigned i, uint32_t now,
                       RobotMotorSend send, void *ctx) {
  RobotMotor *m = &n->motors[i];
  const RsMotorConfig *c = &robot_motor_config[i];
  CanFrame f;
  MotorPhase next = m->phase;
  switch (m->phase) {
  case MOTOR_STOP_WAIT:
    f = RsMotor_Simple(c->id, 4);
    break;
  case MOTOR_MODE_WRITE:
    f = RsMotor_WriteU32(c->id, 0x7005, 0);
    next = MOTOR_MODE_QUERY;
    break;
  case MOTOR_MODE_QUERY:
    f = RsMotor_Read(c->id, 0x7005);
    next = MOTOR_MODE_WAIT;
    break;
  case MOTOR_WD_WRITE:
    f = RsMotor_WriteU32(c->id, 0x7028, ROBOT_DEVICE_WATCHDOG);
    next = MOTOR_WD_QUERY;
    break;
  case MOTOR_WD_QUERY:
    f = RsMotor_Read(c->id, 0x7028);
    next = MOTOR_WD_WAIT;
    break;
  case MOTOR_ZERO: {
    RsCommand zero = {0};
    if (!RsMotor_Command(c, &zero, &f))
      return false;
    next = MOTOR_ENABLE;
    break;
  }
  case MOTOR_ENABLE:
    f = RsMotor_Simple(c->id, 3);
    next = MOTOR_ENABLE_WAIT;
    break;
  case MOTOR_ACTIVE:
    if (!RsMotor_Command(c, &m->command, &f))
      return false;
    break;
  default:
    return false;
  }
  if (!send(ctx, c->bus, &f, now))
    return false;
  if (m->phase == MOTOR_STOP_WAIT && !m->stop_submitted) {
    m->stop_sent_ms = now;
    m->stop_submitted = true;
  }
  if (next != m->phase)
    phase(m, next, now);
  m->next_tx_ms =
      now + (m->phase == MOTOR_STOP_WAIT ? 50U : ROBOT_CONTROL_PERIOD_MS);
  return true;
}
void MotorNetwork_CheckSafety(MotorNetwork *n, uint32_t now) {
  if (!n)
    return;
  for (unsigned i = 0; i < ROBOT_MOTOR_COUNT; i++) {
    RobotMotor *m = &n->motors[i];
    if (m->phase == MOTOR_ACTIVE) {
      bool stale_feedback = !m->feedback_seen ||
                            now - m->feedback_ms > ROBOT_FEEDBACK_TIMEOUT_MS;
      bool stale_command = now - m->command_ms > ROBOT_COMMAND_LEASE_MS;
      float effort = fabsf(m->command.torque) +
                     m->command.kp *
                         fabsf(m->command.position - m->feedback.position) +
                     m->command.kd *
                         fabsf(m->command.velocity - m->feedback.velocity);
      if (stale_feedback)
        MotorNetwork_StopAllCode(n, now, MOTOR_STOP_FEEDBACK_AGE,
                                 (uint8_t)(i + 1));
      else if (stale_command)
        MotorNetwork_StopAllCode(n, now, MOTOR_STOP_COMMAND_AGE,
                                 (uint8_t)(i + 1));
      else if (effort > 2.0f)
        MotorNetwork_StopAllCode(n, now, MOTOR_STOP_EFFORT, (uint8_t)(i + 1));
      else
        continue;
      break;
    } else if (m->phase != MOTOR_IDLE && m->phase != MOTOR_FAULT &&
               now - m->phase_ms > ROBOT_HANDSHAKE_MS) {
      MotorNetwork_StopAllCode(n, now, MOTOR_STOP_HANDSHAKE, (uint8_t)(i + 1));
      break;
    }
  }
}
void MotorNetwork_Step(MotorNetwork *n, uint32_t now, RobotMotorSend send,
                       void *ctx) {
  if (!n || !send)
    return;
  MotorNetwork_CheckSafety(n, now);
  for (unsigned bus = 2; bus <= 3; bus++) {
    unsigned b = bus - 2, start = b * 7;
    bool sent = false;
    for (unsigned k = 0; k < 7; k++) {
      unsigned slot = (n->cursor[b] + k) % 7, i = start + slot;
      RobotMotor *m = &n->motors[i];
      if (!due(now, m->next_tx_ms))
        continue;
      if (n->fault_latched) {
        if (!(n->stop_pending & (1U << i)))
          continue;
        CanFrame f = RsMotor_Simple((uint8_t)(i + 1), 4);
        sent = send(ctx, (uint8_t)bus, &f, now);
        if (sent) {
          if (!m->stop_submitted)
            m->stop_sent_ms = now;
          m->stop_submitted = true;
          m->next_tx_ms = now + 50;
        }
      } else
        sent = send_motor(n, i, now, send, ctx);
      if (sent) {
        n->cursor[b] = (uint8_t)((slot + 1) % 7);
        break;
      }
    }
    if (sent || n->fault_latched || !due(now, n->next_poll_ms[b]))
      continue;
    /* Read-only idle polling. Type 17 never enables or alters settings. */
    for (unsigned k = 0; k < 7; k++) {
      unsigned slot = (n->cursor[b] + k) % 7, i = start + slot;
      RobotMotor *m = &n->motors[i];
      if (m->phase != MOTOR_IDLE)
        continue;
      uint16_t index =
          (!m->position_seen ||
           (m->velocity_seen && due(m->velocity_ms, m->position_ms)))
              ? 0x7019
              : 0x701B;
      CanFrame f = RsMotor_Read((uint8_t)(i + 1), index);
      if (send(ctx, (uint8_t)bus, &f, now)) {
        n->cursor[b] = (uint8_t)((slot + 1) % 7);
        n->next_poll_ms[b] = now + 5;
      }
      break;
    }
  }
}
