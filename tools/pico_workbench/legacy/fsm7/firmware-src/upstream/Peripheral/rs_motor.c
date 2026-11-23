#include "Peripheral/rs_motor.h"
#include <math.h>
#include <string.h>
const RsMotorConfig robot_motor_config[ROBOT_MOTOR_COUNT] = {
    {1, 2, RS_MODEL_00},   {2, 2, RS_MODEL_00},   {3, 2, RS_MODEL_00},
    {4, 2, RS_MODEL_10P},  {5, 2, RS_MODEL_10P},  {6, 2, RS_MODEL_10P},
    {7, 2, RS_MODEL_10P},  {8, 3, RS_MODEL_00},   {9, 3, RS_MODEL_00},
    {10, 3, RS_MODEL_00},  {11, 3, RS_MODEL_10P}, {12, 3, RS_MODEL_10P},
    {13, 3, RS_MODEL_10P}, {14, 3, RS_MODEL_10P}};
const RsMotorConfig *RsMotor_Find(uint8_t bus, uint8_t id) {
  if (id < 1U || id > ROBOT_MOTOR_COUNT)
    return NULL;
  const RsMotorConfig *m = &robot_motor_config[id - 1U];
  return m->bus == bus ? m : NULL;
}
CanFrame RsMotor_Simple(uint8_t id, uint8_t type) {
  return (CanFrame){.extended = true,
                    .dlc = 8,
                    .id = ((uint32_t)type << 24) |
                          ((uint32_t)ROBOT_HOST_ID << 8) | id};
}
CanFrame RsMotor_Read(uint8_t id, uint16_t index) {
  CanFrame f = RsMotor_Simple(id, 17);
  f.data[0] = (uint8_t)index;
  f.data[1] = (uint8_t)(index >> 8);
  return f;
}
CanFrame RsMotor_WriteU32(uint8_t id, uint16_t index, uint32_t value) {
  CanFrame f = RsMotor_Simple(id, 18);
  f.data[0] = (uint8_t)index;
  f.data[1] = (uint8_t)(index >> 8);
  for (unsigned i = 0; i < 4; i++) {
    f.data[4 + i] = (uint8_t)(value >> (8 * i));
  }
  return f;
}
static uint16_t encode(float value, float low, float high) {
  return (uint16_t)((value - low) * 65535.0f / (high - low));
}
static void be16(uint8_t *p, uint16_t n) {
  p[0] = (uint8_t)(n >> 8);
  p[1] = (uint8_t)n;
}
static float decode(const uint8_t *p, float low, float high) {
  return (float)(((uint16_t)p[0] << 8) | p[1]) * (high - low) / 65535.0f + low;
}
bool RsMotor_Command(const RsMotorConfig *m, const RsCommand *c, CanFrame *f) {
  if (!m || !c || !f || !RsMotor_Find(m->bus, m->id))
    return false;
  /* Conservative commissioning caps, NOT rated limits. No silent NaN/clamp. */
  if (!isfinite(c->position) || !isfinite(c->velocity) ||
      !isfinite(c->torque) || !isfinite(c->kp) || !isfinite(c->kd) ||
      fabsf(c->position) > 12.57f || fabsf(c->velocity) > 1.0f ||
      fabsf(c->torque) > 1.0f || c->kp < 0 || c->kp > 5 || c->kd < 0 ||
      c->kd > 1)
    return false;
  float v = m->model == RS_MODEL_00 ? 33.0f : 13.0f,
        t = m->model == RS_MODEL_00 ? 14.0f : 42.0f;
  *f = RsMotor_Simple(m->id, 1);
  f->id = (1UL << 24) | ((uint32_t)encode(c->torque, -t, t) << 8) | m->id;
  be16(f->data, encode(c->position, -12.57f, 12.57f));
  be16(f->data + 2, encode(c->velocity, -v, v));
  be16(f->data + 4, encode(c->kp, 0, 500));
  be16(f->data + 6, encode(c->kd, 0, 5));
  return true;
}
static bool reply(const RsMotorConfig *m, const CanFrame *f, uint8_t type) {
  return m && f && CanFrame_IsValid(f) && f->extended && !f->remote &&
         f->dlc == 8 && (f->id >> 24) == type &&
         (uint8_t)(f->id >> 8) == m->id && (uint8_t)f->id == ROBOT_HOST_ID;
}
bool RsMotor_Feedback(const RsMotorConfig *m, const CanFrame *f,
                      RsFeedback *o) {
  if (!o || !reply(m, f, 2) || ((f->id >> 22) & 3U) > 2U)
    return false;
  float v = m->model == RS_MODEL_00 ? 33.0f : 13.0f,
        t = m->model == RS_MODEL_00 ? 14.0f : 42.0f;
  *o = (RsFeedback){
      .position = decode(f->data, -12.57f, 12.57f),
      .velocity = decode(f->data + 2, -v, v),
      .torque = decode(f->data + 4, -t, t),
      .temperature = (float)(((uint16_t)f->data[6] << 8) | f->data[7]) / 10.0f,
      .mode = (uint8_t)((f->id >> 22) & 3U),
      .faults = (uint8_t)((f->id >> 16) & 63U)};
  return true;
}
bool RsMotor_ReadReply(const RsMotorConfig *m, const CanFrame *f,
                       uint16_t index, uint32_t *value) {
  if (!value || !reply(m, f, 17) || f->data[0] != (uint8_t)index ||
      f->data[1] != (uint8_t)(index >> 8) || f->data[2] || f->data[3])
    return false;
  *value = 0;
  for (unsigned i = 0; i < 4; i++)
    *value |= (uint32_t)f->data[4 + i] << (8 * i);
  return true;
}
