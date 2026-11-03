#include "power_baud_test.h"
#include "transport/can_transport.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned checks, sends;
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); exit(1); } } while (0)
FDCAN_HandleTypeDef hfdcan1;
static CanTransportStats stats;
static CanFrame sent[4];
static char output[4096];
static DeviceReader reader;

HAL_StatusTypeDef HAL_FDCAN_GetErrorCounters(const FDCAN_HandleTypeDef *h, FDCAN_ErrorCountersTypeDef *e) {
    (void)h; e->TxErrorCnt = 255; e->RxErrorCnt = 255; return HAL_OK;
}
CanTransportStats CanTransport_GetStats(void) { return stats; }
bool CanTransport_IsBusOff(void) { return false; }
bool CanTransport_Submit(const CanFrame *frame, uint32_t now) {
    CHECK(sends < 4); sent[sends] = *frame; sent[sends++].timestamp_ms = now; ++stats.tx_submitted; return true;
}
static bool log_text(const char *text) {
    CHECK(strlen(output) + strlen(text) < sizeof(output)); strcat(output, text); return true;
}
static void setup(void) {
    memset(&reader, 0, sizeof(reader)); memset(&stats, 0, sizeof(stats)); memset(sent, 0, sizeof(sent));
    sends = 0; output[0] = 0; reader.config.kind = READER_POWER; PowerBaudTest_Init(0, log_text);
}
static void arm_and_commit(void) {
    g_power_baud_command = POWER_BAUD_ARM;
    CHECK(!PowerBaudTest_Step(&reader, 1, true));
    CHECK(g_power_baud_stage == POWER_BAUD_ARMED && sends == 0);
    g_power_baud_command = POWER_BAUD_COMMIT;
    CHECK(!PowerBaudTest_Step(&reader, 2, true));
    CHECK(g_power_baud_stage == POWER_BAUD_WRITE_WAIT && sends == 1);
    const uint8_t expected[8] = {1, 0x60, 0, 0, 2, 0, 0, 0};
    CHECK(sent[0].id == 0x080000AA && sent[0].extended && !sent[0].remote && sent[0].dlc == 8);
    CHECK(memcmp(sent[0].data, expected, sizeof(expected)) == 0);
}
int main(void) {
    setup();
    CHECK(strstr(output, "FORCE_OPERATOR=1") != NULL);
    CHECK(strstr(output, "no readiness guarantee") != NULL);
    for (uint32_t t = 0; t < 10; ++t) CHECK(!PowerBaudTest_Step(&reader, t, true));
    CHECK(sends == 0); /* Force mode is not automatic. */

    setup();
    g_power_baud_command = POWER_BAUD_COMMIT;
    CHECK(!PowerBaudTest_Step(&reader, 1, true));
    CHECK(g_power_baud_stage == POWER_BAUD_STOPPED && sends == 0);

    setup();
    CanFrame status = {.id=0x03AA0000, .extended=true, .dlc=8, .timestamp_ms=3};
    PowerBaudTest_OnFrame(&status);
    CHECK(strstr(output, "type03_candidate") == NULL);
    arm_and_commit();
    status.remote = true; PowerBaudTest_OnFrame(&status);
    CHECK(strstr(output, "type03_candidate") == NULL);
    status.remote = false; status.id = 0x03AB0000; PowerBaudTest_OnFrame(&status);
    CHECK(strstr(output, "type03_candidate") == NULL);
    status.id = 0x03AA0000; PowerBaudTest_OnFrame(&status);
    CHECK(strstr(output, "type03_candidate=1") != NULL);
    for (uint32_t t = 3; t < 20; ++t) CHECK(!PowerBaudTest_Step(&reader, t, true));
    CHECK(sends == 1); /* No duplicate write while awaiting completion. */
    PowerBaudTest_OnTxEvent("TX_TIMEOUT", &sent[0]);
    CHECK(!PowerBaudTest_Step(&reader, 20, true));
    CHECK(g_power_baud_stage == POWER_BAUD_STOPPED && sends == 1);

    setup();
    g_power_baud_command = POWER_BAUD_ARM;
    CHECK(!PowerBaudTest_Step(&reader, 1, true));
    g_power_baud_command = POWER_BAUD_CANCEL;
    CHECK(!PowerBaudTest_Step(&reader, 2, true));
    CHECK(g_power_baud_stage == POWER_BAUD_STOPPED && sends == 0);

    puts("power baud FORCE operator gate: simulated transport only; NOT a device PASS");
    printf("%u checks passed\n", checks);
    return 0;
}
