/* Robot14 CMSIS-RTOS2 tasks. Stack sizes in BYTES, tick in milliseconds. */
#include "freertos.h"
#include "Application/robot_app.h"
#include "FreeRTOS.h"
#include "cmsis_os2.h"
#include "main.h"
#include "task.h"
void MX_FREERTOS_Init(void) {
  const osThreadAttr_t comm = {
      .name = "RobotComm", .priority = osPriorityHigh, .stack_size = 4096};
  const osThreadAttr_t telemetry = {
      .name = "Telemetry", .priority = osPriorityNormal, .stack_size = 2048};
  if (!osThreadNew(RobotComm_Task, NULL, &comm) ||
      !osThreadNew(RobotTelemetry_Task, NULL, &telemetry))
    Error_Handler();
}
void vApplicationStackOverflowHook(TaskHandle_t task, char *name) {
  (void)task;
  (void)name;
  Error_Handler();
}
void vApplicationMallocFailedHook(void) { Error_Handler(); }
void vApplicationGetIdleTaskMemory(StaticTask_t **t, StackType_t **s,
                                   uint32_t *size) {
  static StaticTask_t task;
  static StackType_t stack[configMINIMAL_STACK_SIZE];
  *t = &task;
  *s = stack;
  *size = configMINIMAL_STACK_SIZE;
}
void vApplicationGetTimerTaskMemory(StaticTask_t **t, StackType_t **s,
                                    uint32_t *size) {
  static StaticTask_t task;
  static StackType_t stack[configTIMER_TASK_STACK_DEPTH];
  *t = &task;
  *s = stack;
  *size = configTIMER_TASK_STACK_DEPTH;
}
