#ifndef ROBOT_MOTOR_NETWORK_H
#define ROBOT_MOTOR_NETWORK_H
#include "Peripheral/rs_motor.h"
typedef enum {
  MOTOR_IDLE,
  MOTOR_STOP_WAIT,
  MOTOR_MODE_WRITE,
  MOTOR_MODE_QUERY,
  MOTOR_MODE_WAIT,
  MOTOR_WD_WRITE,
  MOTOR_WD_QUERY,
  MOTOR_WD_WAIT,
  MOTOR_ZERO,
  MOTOR_ENABLE,
  MOTOR_ENABLE_WAIT,
  MOTOR_ACTIVE,
  MOTOR_FAULT
} MotorPhase;
typedef struct {
  MotorPhase phase;
  RsFeedback feedback;
  RsCommand command;
  float measured_position, measured_velocity;
  uint32_t position_ms, velocity_ms, feedback_ms, phase_ms, next_tx_ms,
      command_ms, stop_sent_ms;
  uint32_t rx_count, invalid, fault_word, warning_word;
  bool position_seen, velocity_seen, feedback_seen, enable_after_stop,
      stop_submitted;
} RobotMotor;
enum {
  MOTOR_STOP_UNKNOWN = 0,
  MOTOR_STOP_FEEDBACK_AGE,
  MOTOR_STOP_COMMAND_AGE,
  MOTOR_STOP_EFFORT,
  MOTOR_STOP_HANDSHAKE,
  MOTOR_STOP_MOTOR_FAULT,
  MOTOR_STOP_SET_REJECT,
  MOTOR_STOP_TRANSPORT,
  MOTOR_STOP_REQUEST,
  MOTOR_STOP_CAN_FATAL,
  MOTOR_STOP_NEW_SESSION,
  MOTOR_STOP_HOST_LEASE
};
typedef struct {
  RobotMotor motors[ROBOT_MOTOR_COUNT];
  uint8_t cursor[2];
  uint32_t next_poll_ms[2];
  uint16_t stop_pending;
  bool fault_latched;
  uint32_t stop_generation;
  /* First stop reason, for the diagnostic R14_DEBUG frame. */
  uint8_t stop_reason, stop_motor;
} MotorNetwork;
typedef bool (*RobotMotorSend)(void *context, uint8_t bus,
                               const CanFrame *frame, uint32_t now);
void MotorNetwork_Init(MotorNetwork *n);
bool MotorNetwork_Enable(MotorNetwork *n, uint8_t id, uint32_t now);
bool MotorNetwork_Disable(MotorNetwork *n, uint8_t id, uint32_t now);
bool MotorNetwork_SetCommand(MotorNetwork *n, uint8_t id, const RsCommand *c,
                             uint32_t now);
void MotorNetwork_StopAll(MotorNetwork *n, uint32_t now);
void MotorNetwork_StopAllCode(MotorNetwork *n, uint32_t now, uint8_t reason,
                              uint8_t motor);
void MotorNetwork_OnFrame(MotorNetwork *n, uint8_t bus, const CanFrame *f);
void MotorNetwork_CheckSafety(MotorNetwork *n, uint32_t now);
void MotorNetwork_Step(MotorNetwork *n, uint32_t now, RobotMotorSend send,
                       void *ctx);
#endif
