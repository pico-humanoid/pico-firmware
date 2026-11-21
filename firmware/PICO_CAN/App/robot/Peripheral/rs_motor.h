#ifndef ROBOT_RS_MOTOR_H
#define ROBOT_RS_MOTOR_H
#include "System/robot_config.h"
#include "protocol/can_frame.h"
typedef enum { RS_MODEL_00, RS_MODEL_10P } RsModel;
typedef struct {
  uint8_t id, bus;
  RsModel model;
} RsMotorConfig;
extern const RsMotorConfig robot_motor_config[ROBOT_MOTOR_COUNT];
typedef struct {
  float position, velocity, torque, kp, kd;
} RsCommand;
typedef struct {
  float position, velocity, torque, temperature;
  uint8_t mode, faults;
} RsFeedback;
const RsMotorConfig *RsMotor_Find(uint8_t bus, uint8_t id);
CanFrame RsMotor_Read(uint8_t id, uint16_t index);
CanFrame RsMotor_Simple(uint8_t id, uint8_t type);
CanFrame RsMotor_WriteU32(uint8_t id, uint16_t index, uint32_t value);
bool RsMotor_Command(const RsMotorConfig *motor, const RsCommand *command,
                     CanFrame *frame);
bool RsMotor_Feedback(const RsMotorConfig *motor, const CanFrame *frame,
                      RsFeedback *feedback);
bool RsMotor_ReadReply(const RsMotorConfig *motor, const CanFrame *frame,
                       uint16_t index, uint32_t *value);
#endif
