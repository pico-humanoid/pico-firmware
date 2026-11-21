#include "Communicate/robot_link.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static RobotLink link;
static MotorNetwork network;
static uint32_t clock_ms = 100, sequence;
static uint8_t wire[ROBOT_LINK_MAX_PACKET], answer[ROBOT_LINK_MAX_PACKET];
static uint16_t answer_size;
static unsigned answers;
static void w16(uint8_t *p, uint16_t v) {
  p[0] = (uint8_t)v;
  p[1] = (uint8_t)(v >> 8);
}
static void w32(uint8_t *p, uint32_t v) {
  w16(p, (uint16_t)v);
  w16(p + 2, (uint16_t)(v >> 16));
}
static uint32_t r32(const uint8_t *p) {
  return p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
         ((uint32_t)p[3] << 24);
}
static bool capture(void *ctx, const uint8_t *p, uint16_t size) {
  (void)ctx;
  assert(size <= sizeof(answer));
  memcpy(answer, p, size);
  answer_size = size;
  answers++;
  return true;
}
static void init(void) {
  const uint8_t uid[12] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12};
  MotorNetwork_Init(&network);
  RobotLink_Init(&link, uid, 123);
  clock_ms = 100;
  sequence = 0;
  answers = 0;
}
static uint16_t make(unsigned type, const uint8_t *data, uint16_t size,
                     uint32_t token, uint32_t seq) {
  memset(wire, 0, sizeof(wire));
  wire[0] = 'R';
  wire[1] = '4';
  wire[2] = 1;
  wire[3] = (uint8_t)type;
  w16(wire + 4, size);
  w32(wire + 6, seq);
  w32(wire + 10, token);
  if (size)
    memcpy(wire + 14, data, size);
  w16(wire + 14 + size, RobotLink_Crc(wire, (uint16_t)(14 + size)));
  return (uint16_t)(16 + size);
}
static void feed(uint16_t size) {
  for (unsigned i = 0; i < size; i++)
    RobotLink_Feed(&link, &network, wire[i], clock_ms, capture, NULL);
}
static void command(unsigned type, const uint8_t *data, uint16_t size) {
  feed(make(type, data, size, link.token, ++sequence));
}
static void hello(uint32_t nonce) {
  feed(make(R14_HELLO, NULL, 0, nonce, 0));
  assert(link.session);
  assert(answer[3] == R14_INFO);
}
static void idle(unsigned id) {
  RobotMotor *m = &network.motors[id - 1];
  m->position_seen = m->velocity_seen = true;
  m->position_ms = m->velocity_ms = clock_ms;
}
static void active(unsigned id) {
  idle(id);
  RobotMotor *m = &network.motors[id - 1];
  m->phase = MOTOR_ACTIVE;
  m->feedback_seen = true;
  m->feedback_ms = m->command_ms = clock_ms;
  link.controlled |= (uint16_t)(1U << (id - 1));
}
static CanFrame feedback(unsigned id, unsigned mode, uint32_t ms) {
  CanFrame f = {.extended = true,
                .dlc = 8,
                .timestamp_ms = ms,
                .id = (2UL << 24) | (mode << 22) | (id << 8) | ROBOT_HOST_ID};
  for (unsigned i = 0; i < 6; i += 2) {
    f.data[i] = 0x7f;
    f.data[i + 1] = 0xff;
  }
  return f;
}
static bool sent(void *ctx, uint8_t bus, const CanFrame *f, uint32_t ms) {
  (void)ctx;
  (void)bus;
  (void)f;
  (void)ms;
  return true;
}
static void parser_tests(void) {
  init();
  assert(RobotLink_Crc((const uint8_t *)"123456789", 9) == 0x29b1);
  uint16_t size = make(R14_HELLO, NULL, 0, 7, 0);
  wire[size - 1] ^= 1;
  feed(size);
  assert(!link.session);
  size = make(R14_HELLO, NULL, 0, 7, 0);
  for (unsigned i = 0; i < size; i++) {
    feed(0);
    RobotLink_Feed(&link, &network, wire[i], clock_ms, capture, NULL);
  }
  assert(link.session);
  assert(answer_size == 44 && r32(answer + 14) == 7 &&
         r32(answer + 30) == 160000000 &&
         r32(answer + 34) == ROBOT_LINK_SIGNATURE);
  uint32_t token = link.token;
  hello(7);
  assert(link.token == token);
  assert(network.motors[0].phase == MOTOR_IDLE && !network.fault_latched);
  const uint8_t id = 1;
  idle(id);
  feed(make(R14_ENABLE, &id, 1, token + 1, 1));
  assert(network.motors[0].phase == MOTOR_IDLE);
  command(R14_ENABLE, &id, 1);
  assert(network.motors[0].phase == MOTOR_STOP_WAIT);
  unsigned rejected = link.rejected;
  feed(make(R14_ENABLE, &id, 1, token, sequence));
  assert(link.rejected == rejected + 1);
  /* Empty batches, mismatched count, unauthorized node, and nonzero during
   * handshake. */
  uint8_t batch[12] = {1, 0};
  command(R14_SET, batch, sizeof(batch));
  assert(!network.fault_latched);
  batch[2] = 1;
  command(R14_SET, batch, sizeof(batch));
  assert(network.fault_latched);
  init();
  hello(9);
  active(1);
  feed(make(R14_STOP, NULL, 0, 0, 0));
  assert(network.fault_latched && link.controlled == 0);
  init();
  hello(9);
  active(1);
  hello(10);
  assert(network.fault_latched);
  init();
  uint16_t n = make(R14_HELLO, NULL, 0, 22, 0);
  RobotLink_Feed(&link, &network, wire[0], 0, capture, NULL);
  clock_ms = 60;
  for (unsigned i = 1; i < n; i++)
    RobotLink_Feed(&link, &network, wire[i], clock_ms, capture, NULL);
  assert(!link.session);
  hello(22);
  assert(link.session);
}
static void lease_batch_tests(void) {
  init();
  hello(44);
  uint8_t b[142] = {0xff, 0x3f};
  for (unsigned id = 1; id <= 14; id++)
    active(id);
  for (unsigned step = 0; step < 100; step++) {
    clock_ms += 20;
    for (unsigned i = 0; i < 14; i++)
      network.motors[i].feedback_ms = clock_ms;
    command(R14_SET, b, sizeof(b));
    assert(!network.fault_latched);
    for (unsigned i = 0; i < 14; i++)
      assert(network.motors[i].command_ms == clock_ms);
    MotorNetwork_CheckSafety(&network, clock_ms);
  }
  /* Last entry invalid: even earlier axes must not get the new first target. */
  w16(b + 2, 100);
  w16(b + 132 + 8, 1001);
  uint32_t old = network.motors[0].command_ms;
  clock_ms++;
  command(R14_SET, b, sizeof(b));
  assert(network.fault_latched && network.motors[0].command_ms == old);
  init();
  hello(44);
  active(1);
  clock_ms += 101;
  command(R14_PING, NULL, 0);
  network.motors[0].feedback_ms = clock_ms;
  MotorNetwork_CheckSafety(&network, clock_ms);
  assert(network.fault_latched);
  init();
  hello(44);
  active(1);
  clock_ms += 151;
  RobotLinkHealth h = {0};
  RobotLink_Step(&link, &network, &h, clock_ms, capture, NULL);
  assert(network.fault_latched &&
         link.session); /* Still reports STOP confirmation. */
  assert(answer[3] == R14_STATE && answer[18]);
  init();
  hello(44);
  active(1);
  RobotLink_TransportFault(&link, &network, clock_ms);
  assert(network.fault_latched);
}
static void disable_tests(void) {
  init();
  hello(55);
  active(1);
  uint8_t id = 1;
  command(R14_DISABLE, &id, 1);
  assert(network.motors[0].phase == MOTOR_STOP_WAIT);
  assert(network.stop_generation == 1 && !network.fault_latched);
  CanFrame f = feedback(1, 0, clock_ms);
  MotorNetwork_OnFrame(&network, 2, &f);
  assert(network.motors[0].phase == MOTOR_STOP_WAIT);
  MotorNetwork_Step(&network, ++clock_ms, sent, NULL);
  assert(network.motors[0].stop_submitted);
  f = feedback(1, 0, clock_ms - 1);
  MotorNetwork_OnFrame(&network, 2, &f);
  assert(network.motors[0].phase == MOTOR_STOP_WAIT);
  f = feedback(1, 0, clock_ms);
  MotorNetwork_OnFrame(&network, 2, &f);
  assert(network.motors[0].phase == MOTOR_IDLE);
  idle(1);
  command(R14_ENABLE, &id, 1);
  assert(network.motors[0].phase == MOTOR_STOP_WAIT);
  command(R14_DISABLE, &id, 1);
  MotorNetwork_Step(&network, ++clock_ms, sent, NULL);
  f = feedback(1, 0, clock_ms);
  MotorNetwork_OnFrame(&network, 2, &f);
  assert(network.motors[0].phase == MOTOR_IDLE);
  active(1);
  command(R14_DISABLE, &id, 1);
  clock_ms += 301;
  MotorNetwork_CheckSafety(&network, clock_ms);
  assert(network.fault_latched);
}
static void telemetry_tests(bool dump) {
  init();
  hello(777);
  if (dump) {
    for (unsigned i = 0; i < answer_size; i++)
      printf("%02x", answer[i]);
    puts("");
  }
  idle(1);
  network.motors[0].measured_position = 1.25f;
  network.motors[0].measured_velocity = -0.1f;
  RobotLinkHealth h = {
      .bms_valid = 1, .bms_mv = 48000, .power_valid = 2, .power_mv = 47900};
  /* Capture selected NODE without STATE overwriting it. */
  link.next_state = 1000;
  link.next_node = 1000;
  RobotLink_Step(&link, &network, &h, clock_ms, capture, NULL);
  assert(answer[3] == R14_NODE && answer_size == 62 &&
         r32(answer + 22) == 1250);
  if (dump) {
    for (unsigned i = 0; i < answer_size; i++)
      printf("%02x", answer[i]);
    puts("");
  }
  link.next_state = 0;
  link.next_node = 1000;
  link.next_selected = 1000;
  RobotLink_Step(&link, &network, &h, clock_ms, capture, NULL);
  assert(answer[3] == R14_STATE && answer_size == 111);
  if (dump) {
    for (unsigned i = 0; i < answer_size; i++)
      printf("%02x", answer[i]);
    puts("");
  }
}
static void fuzz(void) {
  init();
  uint32_t random = 12;
  for (unsigned i = 0; i < 200000; i++) {
    random = random * 1664525U + 1013904223U;
    RobotLink_Feed(&link, &network, (uint8_t)(random >> 24), i / 100, capture,
                   NULL);
    assert(link.used < ROBOT_LINK_MAX_PACKET);
  }
  clock_ms = 3000;
  hello(22);
  assert(!network.fault_latched);
}
int main(int argc, char **argv) {
  if (argc == 2 && !strcmp(argv[1], "--wire")) {
    telemetry_tests(true);
    return 0;
  }
  parser_tests();
  lease_batch_tests();
  disable_tests();
  telemetry_tests(false);
  fuzz();
  puts("Robot14 binary session/batch/leases/disable/telemetry/fuzz passed");
  return 0;
}
