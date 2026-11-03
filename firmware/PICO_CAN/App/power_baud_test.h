#ifndef PICO_POWER_BAUD_TEST_H
#define PICO_POWER_BAUD_TEST_H
#include "device_reader.h"

/* Test images only. Neither command is read from the CAN bus or UART.
 * Explicit SWD mailbox writes are required after every MCU reset. */
#define POWER_BAUD_ARM 0x50424152UL
#define POWER_BAUD_COMMIT 0x5042434DUL
#define POWER_BAUD_CANCEL 0x50425354UL
#ifndef POWER_BAUD_BASELINE_MS
#define POWER_BAUD_BASELINE_MS 60000UL
#endif
#define POWER_BAUD_ARM_MS 5000UL

typedef enum {
    POWER_BAUD_IDLE, POWER_BAUD_DRAIN, POWER_BAUD_ARMED,
    POWER_BAUD_WRITE_WAIT, POWER_BAUD_READ_WAIT,
    POWER_BAUD_DONE, POWER_BAUD_STOPPED
} PowerBaudStage;
extern volatile uint32_t g_power_baud_command;
extern volatile uint32_t g_power_baud_stage;

typedef bool (*PowerBaudLog)(const char *text);
void PowerBaudTest_Init(uint32_t now, PowerBaudLog log);
/* Return true only when ordinary read polling is allowed. */
bool PowerBaudTest_Step(DeviceReader *reader, uint32_t now, bool uart_ok);
void PowerBaudTest_OnTxEvent(const char *event, const CanFrame *frame);
void PowerBaudTest_OnFrame(const CanFrame *frame);
#endif
