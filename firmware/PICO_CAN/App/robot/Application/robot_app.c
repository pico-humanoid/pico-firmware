#include "Application/robot_app.h"
#include "Communicate/robot_uart.h"
#include "FreeRTOS.h"
#include "cmsis_os2.h"
#include "task.h"
#include <string.h>
typedef struct {
  uint8_t id;
  bool enable;
  uint32_t timestamp;
  RsCommand command;
} AppRequest;
static osMessageQueueId_t commands;
static MotorNetwork network;
static DualDeviceReader devices;
static RobotLink link;
/* Published inspection point for debugger; write via API, never poke state. */
static RobotSnapshot snapshot;
static volatile bool ready, stop_requested;
static uint32_t rejected, overruns;
static bool device_send(void *ctx, const CanFrame *f, uint32_t now) {
  return RobotCan_Send(ctx, 1, f, now);
}
bool Robot_RequestEnable(uint8_t id) {
  if (!ready || id < 1 || id > ROBOT_MOTOR_COUNT)
    return false;
  AppRequest r = {.id = id, .enable = true, .timestamp = HAL_GetTick()};
  return osMessageQueuePut(commands, &r, 0, 0) == osOK;
}
bool Robot_SetCommand(uint8_t id, const RsCommand *c) {
  if (!ready || !c || id < 1 || id > ROBOT_MOTOR_COUNT)
    return false;
  CanFrame validation;
  if (!RsMotor_Command(&robot_motor_config[id - 1], c, &validation))
    return false;
  AppRequest r = {.id = id, .timestamp = HAL_GetTick(), .command = *c};
  return osMessageQueuePut(commands, &r, 0, 0) == osOK;
}
void Robot_RequestStop(void) { stop_requested = true; }
bool Robot_GetSnapshot(RobotSnapshot *s) {
  if (!ready || !s)
    return false;
  taskENTER_CRITICAL();
  *s = snapshot;
  taskEXIT_CRITICAL();
  return true;
}
void RobotComm_Task(void *argument) {
  (void)argument;
  MotorNetwork_Init(&network);
  ReaderConfig bms = {.kind = READER_BMS,
                      .power_id = ROBOT_POWER_ID,
                      .bms_rtr_dlc = 0,
                      .max_attempts = 2,
                      .bms_crc_order = BYTE_ORDER_BIG,
                      .power_status_order = BYTE_ORDER_BIG,
                      .timeout_ms = 700,
                      .interval_ms = 200,
                      .stale_ms = 10000};
  ReaderConfig power = bms;
  power.kind = READER_POWER;
  commands = osMessageQueueNew(32, sizeof(AppRequest), NULL);
  if (!commands ||
      !DualDeviceReader_InitWithDelay(&devices, &bms, &power, HAL_GetTick(),
                                      3000) ||
      !RobotCan_Start())
    Error_Handler();
  uint8_t uid[12];
  uint32_t words[3] = {HAL_GetUIDw0(), HAL_GetUIDw1(), HAL_GetUIDw2()};
  memcpy(uid, words, sizeof(uid));
  RobotLink_Init(&link, uid,
                 words[0] ^ words[1] ^ words[2] ^ HAL_GetTick() ^ SysTick->VAL);
  if (!RobotUart_Start())
    Error_Handler();
  ready = true;
  uint32_t tick = osKernelGetTickCount(), published = 0, stop_generation = 0;
  for (;;) {
    uint32_t now = HAL_GetTick();
    RobotCan_Service(now);
    if (stop_requested) {
      stop_requested = false;
      MotorNetwork_StopAllCode(&network, now, MOTOR_STOP_REQUEST, 0);
    }
    for (uint8_t bus = 1; bus <= 3; bus++) {
      /* Only a bus that has already carried traffic can be "lost". An empty
         motor bus keeps probing but must not latch a stop for the other one. */
      if (bus > 1 && RobotCan_BusFatal(bus))
        MotorNetwork_StopAllCode(&network, now, MOTOR_STOP_CAN_FATAL, bus);
      CanFrame f;
      for (unsigned budget = 0; budget < 63 && RobotCan_Receive(bus, &f);
           budget++) {
        if (bus == 1) {
          (void)DeviceReader_OnFrame(&devices.bms, &f);
          (void)DeviceReader_OnFrame(&devices.power, &f);
        } else
          MotorNetwork_OnFrame(&network, bus, &f);
      }
    }
    MotorNetwork_CheckSafety(&network, now);
    AppRequest r;
    for (unsigned budget = 0;
         budget < 32 && osMessageQueueGet(commands, &r, NULL, 0) == osOK;
         budget++) {
      if (now - r.timestamp > ROBOT_COMMAND_LEASE_MS ||
          !(r.enable
                ? MotorNetwork_Enable(&network, r.id, now)
                : MotorNetwork_SetCommand(&network, r.id, &r.command, now)))
        rejected++;
    }
    if (RobotUart_TakeFault())
      RobotLink_TransportFault(&link, &network, now);
    uint8_t byte;
    uint32_t arrival;
    for (unsigned budget = 0; budget < 256 && RobotUart_Read(&byte, &arrival);
         budget++) {
      if (now - arrival > 50) {
        RobotLink_TransportFault(&link, &network, now);
        break;
      }
      RobotLink_Feed(&link, &network, byte, now, RobotUart_Write, NULL);
    }
    RobotLinkHealth health = {.rejected = rejected,
                              .overruns = overruns,
                              .bms_valid = devices.bms.valid_mask,
                              .power_valid = devices.power.valid_mask,
                              .bms_mv = devices.bms.bms.voltage_mv,
                              .power_mv = devices.power.power.battery_mv};
    for (uint8_t bus = 1; bus <= 3; bus++) {
      RobotCanStats s = RobotCan_GetStats(bus);
      uint32_t values[5] = {s.rx_received, s.tx_submitted, s.bus_off,
                            s.rx_dropped + s.fifo_lost, s.tx_expired};
      memcpy(health.can[bus - 1], values, sizeof(values));
    }
    RobotLink_Step(&link, &network, &health, now, RobotUart_Write, NULL);
    /* Detect lease/handshake failure BEFORE dispatching any further controls.
     */
    MotorNetwork_CheckSafety(&network, now);
    if (network.stop_generation != stop_generation) {
      RobotCan_AbortMotors();
      stop_generation = network.stop_generation;
    }
    MotorNetwork_Step(&network, now, RobotCan_Send, NULL);
    DualDeviceReader_Step(&devices, now, device_send, NULL);
    if (now - published >= 20) {
      taskENTER_CRITICAL();
      snapshot.network = network;
      snapshot.devices = devices;
      snapshot.uptime_ms = now;
      snapshot.command_rejected = rejected;
      snapshot.task_overruns = overruns;
      for (uint8_t bus = 1; bus <= 3; bus++)
        snapshot.can[bus - 1] = RobotCan_GetStats(bus);
      taskEXIT_CRITICAL();
      published = now;
    }
    tick++;
    if ((int32_t)(osKernelGetTickCount() - tick) >= 0) {
      overruns++;
      tick = osKernelGetTickCount();
      osDelay(1);
    } else
      (void)osDelayUntil(tick);
  }
}
void RobotTelemetry_Task(void *argument) {
  (void)argument;
  for (;;) {
    RobotUart_Transmit();
    osDelay(1);
  }
}
