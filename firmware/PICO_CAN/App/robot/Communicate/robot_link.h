#ifndef ROBOT_LINK_H
#define ROBOT_LINK_H
#include "Modules/motor_network.h"
#define ROBOT_LINK_MAX_PAYLOAD 160U
#define ROBOT_LINK_MAX_PACKET (16U + ROBOT_LINK_MAX_PAYLOAD)
#define ROBOT_LINK_SIGNATURE 0x14A20C02UL
#define ROBOT_LINK_HOST_MS 150U
/* CRC16-CCITT, LE fields. Binary only; see docs/Robot14_Tuning.md. */
enum {
  R14_HELLO = 1,
  R14_ENABLE,
  R14_SET,
  R14_PING,
  R14_STOP,
  R14_DISABLE,
  R14_SELECT,
  R14_INFO = 0x81,
  R14_ACK = 0x82,
  R14_STATE = 0x90,
  R14_NODE = 0x91,
  /* Diagnostic-only: stop / SET rejection reason; hosts may ignore it.
     Below R14_STATE so the UART queue does not drop it as telemetry. */
  R14_DEBUG = 0x8F
};
typedef bool (*RobotLinkWrite)(void *ctx, const uint8_t *bytes, uint16_t size);
typedef struct {
  uint32_t rejected, overruns, bms_valid, power_valid, bms_mv, power_mv;
  /* rx, tx submitted, bus off, RX dropped/FIFO lost, TX expired, for CAN1..3 */
  uint32_t can[3][5];
} RobotLinkHealth;
typedef struct {
  uint8_t bytes[ROBOT_LINK_MAX_PACKET], uid[12], cursor, selected;
  uint16_t used, controlled;
  uint32_t seed, token, host_nonce, sequence, host_ms, partial_ms;
  uint32_t bad_frames, rejected, next_node, next_selected, next_state;
  bool session, latched_reported;
} RobotLink;
void RobotLink_Init(RobotLink *l, const uint8_t uid[12], uint32_t seed);
void RobotLink_Feed(RobotLink *l, MotorNetwork *n, uint8_t byte, uint32_t now,
                    RobotLinkWrite write, void *ctx);
void RobotLink_Step(RobotLink *l, MotorNetwork *n,
                    const RobotLinkHealth *health, uint32_t now,
                    RobotLinkWrite write, void *ctx);
void RobotLink_TransportFault(RobotLink *l, MotorNetwork *n, uint32_t now);
uint16_t RobotLink_Crc(const uint8_t *bytes, uint16_t size);
#endif
