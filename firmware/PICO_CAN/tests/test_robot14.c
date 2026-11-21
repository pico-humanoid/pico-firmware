#include "Modules/motor_network.h"
#include "dual_device_reader.h"
#include "dual_test_frames.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static CanFrame response(uint8_t id, uint8_t type, uint32_t now) {
  return (CanFrame){.extended = true,
                    .dlc = 8,
                    .timestamp_ms = now,
                    .id = ((uint32_t)type << 24) | ((uint32_t)id << 8) |
                          ROBOT_HOST_ID};
}
static CanFrame parameter(uint8_t id, uint16_t index, uint32_t raw,
                          uint32_t now) {
  CanFrame f = response(id, 17, now);
  f.data[0] = (uint8_t)index;
  f.data[1] = (uint8_t)(index >> 8);
  for (unsigned j = 0; j < 4; j++) {
    f.data[4 + j] = (uint8_t)(raw >> (8 * j));
  }
  return f;
}
static CanFrame feedback(uint8_t id, unsigned mode, unsigned faults,
                         uint32_t now) {
  CanFrame f = response(id, 2, now);
  f.id |= (mode << 22) | (faults << 16);
  for (unsigned i = 0; i < 6; i += 2) {
    f.data[i] = 0x7F;
    f.data[i + 1] = 0xFF;
  }
  f.data[6] = 1;
  f.data[7] = 44;
  return f;
}
typedef struct {
  uint8_t bus;
  CanFrame frame;
} Sent;
static Sent sent[32];
static unsigned count, controls, stops, enables;
static bool busy;
static bool send(void *ctx, uint8_t bus, const CanFrame *f, uint32_t now) {
  (void)ctx;
  (void)now;
  if (busy)
    return false;
  assert(count < 32);
  assert(bus == 2 || bus == 3);
  assert(RsMotor_Find(bus, (uint8_t)f->id));
  sent[count++] = (Sent){bus, *f};
  if (f->id >> 24 == 1)
    controls++;
  if (f->id >> 24 == 3)
    enables++;
  if (f->id >> 24 == 4)
    stops++;
  return true;
}
static bool motor_running[15];
static bool corrupt_wd;
static void simulate(MotorNetwork *n, uint32_t now) {
  count = 0;
  MotorNetwork_Step(n, now, send, NULL);
  for (unsigned i = 0; i < count; i++) {
    CanFrame request = sent[i].frame, f;
    uint8_t id = (uint8_t)request.id;
    uint8_t type = (uint8_t)(request.id >> 24);
    if (type == 17) {
      uint16_t index =
          (uint16_t)request.data[0] | ((uint16_t)request.data[1] << 8);
      f = parameter(
          id, index,
          index == 0x7028 ? (corrupt_wd ? 0 : ROBOT_DEVICE_WATCHDOG) : 0, now);
    } else {
      if (type == 3)
        motor_running[id] = true;
      if (type == 4)
        motor_running[id] = false;
      f = feedback(id, motor_running[id] ? 2 : 0, 0, now);
    }
    MotorNetwork_OnFrame(n, sent[i].bus, &f);
  }
}
static void codec(void) {
  unsigned rs00 = 0, rs10 = 0;
  for (unsigned i = 0; i < 14; i++) {
    const RsMotorConfig *m = &robot_motor_config[i];
    assert(m->id == i + 1);
    assert(m->bus == (i < 7 ? 2 : 3));
    if (m->model == RS_MODEL_00)
      rs00++;
    else
      rs10++;
    assert(!RsMotor_Find(m->bus == 2 ? 3 : 2, m->id));
  }
  assert(rs00 == 6 && rs10 == 8);
  CanFrame a, b;
  RsCommand c = {.velocity = 1, .torque = 1, .kp = 5, .kd = 1};
  assert(RsMotor_Command(&robot_motor_config[0], &c, &a));
  assert(RsMotor_Command(&robot_motor_config[3], &c, &b));
  assert(a.id != b.id);
  assert(memcmp(a.data + 2, b.data + 2, 2) != 0);
  assert(a.data[4] == 2 && a.data[5] == 143); /* 5 / 500 * 65535 truncation */
  c.velocity = NAN;
  assert(!RsMotor_Command(&robot_motor_config[0], &c, &a));
  c.velocity = 1.1f;
  assert(!RsMotor_Command(&robot_motor_config[0], &c, &a));
  CanFrame f = feedback(4, 2, 8, 1);
  RsFeedback fb;
  assert(RsMotor_Feedback(&robot_motor_config[3], &f, &fb));
  assert(fb.mode == 2 && fb.faults == 8 && fb.temperature == 30);
  f.id = (f.id & ~255U) | 0xFE;
  assert(!RsMotor_Feedback(&robot_motor_config[3], &f, &fb));
  f = parameter(4, 0x7028, 4000, 1);
  uint32_t raw;
  assert(RsMotor_ReadReply(&robot_motor_config[3], &f, 0x7028, &raw) &&
         raw == 4000);
  f.remote = true;
  assert(!RsMotor_ReadReply(&robot_motor_config[3], &f, 0x7028, &raw));
}
static void exercise(void) {
  MotorNetwork n;
  MotorNetwork_Init(&n);
  memset(motor_running, 0, sizeof(motor_running));
  controls = stops = enables = 0;
  corrupt_wd = false;
  for (uint32_t t = 0; t < 500; t++)
    simulate(&n, t);
  assert(!controls && !stops &&
         !enables); /* cold boot is genuinely read-only */
  for (unsigned id = 1; id <= 14; id++)
    assert(MotorNetwork_Enable(&n, (uint8_t)id, 500));
  for (uint32_t t = 500; t < 1500; t++) {
    for (unsigned id = 1; id <= 14; id++)
      if (n.motors[id - 1].phase == MOTOR_ACTIVE) {
        RsCommand c = {0};
        assert(MotorNetwork_SetCommand(&n, (uint8_t)id, &c, t));
      }
    simulate(&n, t);
    assert(!n.fault_latched);
  }
  for (unsigned i = 0; i < 14; i++)
    assert(n.motors[i].phase == MOTOR_ACTIVE);
  assert(enables == 14 && controls > 1000);
  /* Expired command lease -> global fault; no more type 1, all 14 stop. */
  for (uint32_t t = 1500; t < 1700; t++)
    simulate(&n, t);
  assert(n.fault_latched && n.stop_pending == 0);
  unsigned before = controls;
  for (uint32_t t = 1700; t < 1800; t++)
    simulate(&n, t);
  assert(controls == before);
  assert(!MotorNetwork_Enable(&n, 1, 1800));
}
static void negative(void) {
  MotorNetwork n;
  MotorNetwork_Init(&n);
  corrupt_wd = true;
  memset(motor_running, 0, sizeof(motor_running));
  enables = 0;
  for (uint32_t t = 0; t < 500; t++)
    simulate(&n, t);
  assert(!MotorNetwork_Enable(&n, 0, 500));
  assert(!MotorNetwork_Enable(&n, 15, 500));
  assert(MotorNetwork_Enable(&n, 1, 500));
  busy = true;
  count = 0;
  MotorNetwork_Step(&n, 500, send, NULL);
  assert(!n.motors[0].stop_submitted);
  CanFrame f = feedback(1, 0, 0, 500);
  MotorNetwork_OnFrame(&n, 2, &f);
  assert(n.motors[0].phase == MOTOR_STOP_WAIT);
  busy = false;
  for (uint32_t t = 501; t < 750; t++)
    simulate(&n, t);
  assert(n.fault_latched && !enables); /* watchdog mismatch never enables */
  MotorNetwork_Init(&n);
  f = feedback(1, 0, 8, 1);
  MotorNetwork_OnFrame(&n, 3, &f);
  assert(!n.fault_latched); /* wrong bus ignored */
  MotorNetwork_OnFrame(&n, 2, &f);
  assert(n.fault_latched); /* magnetic encoder fault stops peers */
  MotorNetwork_Init(&n);
  n.motors[0].phase = MOTOR_ACTIVE;
  n.motors[0].feedback_seen = true;
  n.motors[0].feedback_ms = 10;
  n.motors[0].command_ms = 110;
  MotorNetwork_CheckSafety(&n, 111);
  assert(n.fault_latched); /* feedback loss */
  f = feedback(1, 0, 0, 112);
  MotorNetwork_OnFrame(&n, 2, &f);
  assert(n.stop_pending ==
         0x3FFF); /* queued stop-mode feedback is not a stop acknowledgement */
  count = 0;
  MotorNetwork_Step(&n, 112, send, NULL);
  assert(n.motors[0].stop_submitted);
  f.timestamp_ms = 111;
  MotorNetwork_OnFrame(&n, 2, &f);
  assert(n.stop_pending &
         1U); /* feedback predating the actual stop submission */
  f.timestamp_ms = 112;
  MotorNetwork_OnFrame(&n, 2, &f);
  assert(!(n.stop_pending & 1U));
  MotorNetwork_Init(&n);
  n.motors[0].phase = MOTOR_MODE_WAIT;
  n.motors[0].phase_ms = 0xFFFFFF00U;
  MotorNetwork_CheckSafety(&n, 50);
  assert(n.fault_latched); /* uint32 ms wrap */
}

static bool device_send(void *ctx, const CanFrame *f, uint32_t now) {
  (void)ctx;
  (void)now;
  assert(f->extended ? !f->remote : (f->remote && f->dlc == 0));
  return true;
}
static void integrated(void) {
  MotorNetwork n;
  MotorNetwork_Init(&n);
  DualDeviceReader d;
  ReaderConfig b = {.kind = READER_BMS,
                    .power_id = 0xAA,
                    .bms_rtr_dlc = 0,
                    .max_attempts = 2,
                    .bms_crc_order = BYTE_ORDER_BIG,
                    .power_status_order = BYTE_ORDER_BIG,
                    .timeout_ms = 700,
                    .interval_ms = 200,
                    .stale_ms = 10000};
  ReaderConfig p = b;
  p.kind = READER_POWER;
  assert(DualDeviceReader_InitWithDelay(&d, &b, &p, 0, 3000));
  corrupt_wd = false;
  busy = false;
  memset(motor_running, 0, sizeof(motor_running));
  for (uint32_t t = 0; t < 15000; t++) {
    if (t == 500)
      for (unsigned id = 1; id <= 14; id++)
        assert(MotorNetwork_Enable(&n, (uint8_t)id, t));
    for (unsigned id = 1; id <= 14; id++)
      if (n.motors[id - 1].phase == MOTOR_ACTIVE) {
        RsCommand c = {0};
        assert(MotorNetwork_SetCommand(&n, (uint8_t)id, &c, t));
      }
    simulate(&n, t);
    assert(!n.fault_latched);
    DualDeviceReader_Step(&d, t, device_send, NULL);
    assert(!(d.bms.pending && d.power.pending));
    DeviceReader *r = d.bms.pending     ? &d.bms
                      : d.power.pending ? &d.power
                                        : NULL;
    if (r) {
      CanFrame f = dual_test_reply(r->config.kind, r->query_index, t);
      assert(DeviceReader_OnFrame(r, &f) >= 0);
    }
    if (t < 3000)
      assert(d.bms.stats.tx_submitted == 0 && d.power.stats.tx_submitted == 0);
  }
  assert(d.bms.valid_mask == 0x1F &&
         d.power.valid_mask == POWER_ALL_FRESH_MASK);
  assert(d.bms.stats.timeouts == 0 && d.power.stats.timeouts == 0);
  for (unsigned i = 0; i < 14; i++)
    assert(n.motors[i].phase == MOTOR_ACTIVE);
}

int main(void) {
  codec();
  exercise();
  negative();
  integrated();
  puts("robot14 codec/topology/read-only/14-way handshake/deadman/faults PASS");
  return 0;
}
