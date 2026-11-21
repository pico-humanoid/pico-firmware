#ifndef ROBOT_APP_H
#define ROBOT_APP_H
#include "Communicate/robot_can.h"
#include "Modules/motor_network.h"
#include "dual_device_reader.h"
typedef struct {
  MotorNetwork network;
  DualDeviceReader devices;
  RobotCanStats can[3];
  uint32_t uptime_ms, command_rejected, task_overruns;
} RobotSnapshot;
/* Thread APIs: true = enqueued, not permission/drive completion. Observe phase.
   Commands use output-shaft rad, rad/s, Nm; RS10P values are not divided by 25.
 */
bool Robot_RequestEnable(uint8_t id);
bool Robot_SetCommand(uint8_t id, const RsCommand *command);
/* Global latched stop, reboot required to re-arm. */
void Robot_RequestStop(void);
bool Robot_GetSnapshot(RobotSnapshot *snapshot);
void RobotComm_Task(void *argument);
void RobotTelemetry_Task(void *argument);
#endif
