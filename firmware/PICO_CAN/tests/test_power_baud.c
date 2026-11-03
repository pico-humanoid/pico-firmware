#include "power_baud_test.h"
#include "transport/can_transport.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned checks;
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); exit(1); } } while (0)
FDCAN_HandleTypeDef hfdcan1;
static CanTransportStats stats;
static uint32_t tec, rec;
static bool off, counters_ok, log_ok, accept;
static unsigned sends;
static CanFrame sent[8];
static char output[16384];
static DeviceReader r;
HAL_StatusTypeDef HAL_FDCAN_GetErrorCounters(const FDCAN_HandleTypeDef *h, FDCAN_ErrorCountersTypeDef *e) {
    (void)h; e->TxErrorCnt=tec; e->RxErrorCnt=rec; return counters_ok ? HAL_OK : HAL_ERROR;
}
CanTransportStats CanTransport_GetStats(void) { return stats; }
bool CanTransport_IsBusOff(void) { return off; }
bool CanTransport_Submit(const CanFrame *f, uint32_t now) {
    CHECK(sends<8); sent[sends]=*f; sent[sends++].timestamp_ms=now;
    if (accept) ++stats.tx_submitted;
    return accept;
}
static bool log_text(const char *s) {
    CHECK(strlen(output)+strlen(s)<sizeof(output)); strcat(output,s); return log_ok;
}
static void fresh(uint32_t now) {
    r.seen_mask=r.valid_mask=POWER_ALL_FRESH_MASK;
    for (unsigned i=0;i<POWER_QUERY_COUNT;++i) r.last_ok_ms[i]=now;
}
static void setup(void) {
    memset(&r,0,sizeof(r)); memset(&stats,0,sizeof(stats)); memset(sent,0,sizeof(sent));
    tec=rec=sends=0; off=false; counters_ok=log_ok=accept=true; output[0]=0;
    r.config.kind=READER_POWER; r.config.stale_ms=10000;
    r.stats.cycles=25; r.power.can_baud_code=PICO_DEVICE_BITRATE==1000000 ? 1 : 2;
    fresh(60000); PowerBaudTest_Init(0,log_text);
}
static void arm(void) {
    g_power_baud_command=POWER_BAUD_ARM;
    CHECK(!PowerBaudTest_Step(&r,60000,true));
    CHECK(g_power_baud_stage==POWER_BAUD_ARMED && sends==0);
}
static void commit(void) {
    g_power_baud_command=POWER_BAUD_COMMIT;
    CHECK(!PowerBaudTest_Step(&r,60001,true));
    CHECK(g_power_baud_stage==POWER_BAUD_WRITE_WAIT && sends==1);
    const uint8_t expected[8]={1,0x60,0,0,PICO_POWER_BAUD_TARGET==500000 ? 2 : 1,0,0,0};
    CHECK(sent[0].id==0x080000AA && sent[0].extended && !sent[0].remote && sent[0].dlc==8);
    CHECK(memcmp(sent[0].data,expected,8)==0);
}
static void write_done(void) {
    PowerBaudTest_OnTxEvent("TX_DONE",&sent[0]);
    CHECK(!PowerBaudTest_Step(&r,60002,true));
    CHECK(g_power_baud_stage==POWER_BAUD_READ_WAIT && sends==2);
    CHECK(sent[1].id==0x070000AA && sent[1].data[0]==1 && sent[1].data[1]==0x60);
    for(unsigned i=2;i<8;++i) CHECK(sent[1].data[i]==0);
}
static void rejected(void) {
    g_power_baud_command=POWER_BAUD_ARM;
    (void)PowerBaudTest_Step(&r,60000,true);
    CHECK(g_power_baud_stage==POWER_BAUD_IDLE && sends==0);
}
int main(void) {
    setup();
    /* Boot and repeated service never write, regardless of elapsed baseline. */
    for(uint32_t t=60000;t<80000;t+=100) { fresh(t); CHECK(PowerBaudTest_Step(&r,t,true)); }
    CHECK(sends==0 && g_power_baud_command==0);
    setup(); g_power_baud_command=POWER_BAUD_COMMIT; (void)PowerBaudTest_Step(&r,60000,true);
    CHECK(g_power_baud_stage==POWER_BAUD_STOPPED && sends==0);
    setup(); g_power_baud_command=123; (void)PowerBaudTest_Step(&r,60000,true); CHECK(sends==0 && g_power_baud_stage==POWER_BAUD_STOPPED);
    setup(); g_power_baud_command=POWER_BAUD_ARM; (void)PowerBaudTest_Step(&r,59999,true); CHECK(g_power_baud_stage==POWER_BAUD_IDLE);
    setup(); r.stats.cycles=1; rejected();
    setup(); r.valid_mask=0; rejected();
    setup(); r.seen_mask=0; rejected();
    setup(); r.config.kind=READER_BMS; rejected();
    setup(); r.last_ok_ms[7]=49999; rejected();
    setup(); r.power.can_baud_code=3; rejected();
    setup(); counters_ok=false; rejected();
    setup(); tec=1; rejected();
    setup(); rec=1; rejected();
    setup(); off=true; rejected();
#define READER_BAD(field) setup(); r.stats.field=1; rejected()
    READER_BAD(timeouts); READER_BAD(query_failures); READER_BAD(invalid); READER_BAD(tx_rejected);
#define TRANSPORT_BAD(field) setup(); stats.field=1; rejected()
    TRANSPORT_BAD(tx_rejected); TRANSPORT_BAD(tx_timed_out); TRANSPORT_BAD(rx_fifo_lost);
    TRANSPORT_BAD(rx_queue_dropped); TRANSPORT_BAD(rx_read_failed); TRANSPORT_BAD(rx_unsupported);
    TRANSPORT_BAD(tx_event_lost); TRANSPORT_BAD(tx_event_unknown); TRANSPORT_BAD(bus_off);
    setup(); r.pending=true; g_power_baud_command=POWER_BAUD_ARM;
    (void)PowerBaudTest_Step(&r,60000,true); CHECK(g_power_baud_stage==POWER_BAUD_DRAIN && sends==0);
    r.pending=false; (void)PowerBaudTest_Step(&r,60010,true); CHECK(g_power_baud_stage==POWER_BAUD_ARMED);
    setup(); stats.tx_submitted=1; g_power_baud_command=POWER_BAUD_ARM;
    (void)PowerBaudTest_Step(&r,60000,true); CHECK(g_power_baud_stage==POWER_BAUD_DRAIN);
    stats.tx_completed=1; (void)PowerBaudTest_Step(&r,60010,true); CHECK(g_power_baud_stage==POWER_BAUD_ARMED);
    setup(); r.pending=true; g_power_baud_command=POWER_BAUD_ARM;
    (void)PowerBaudTest_Step(&r,60000,true); (void)PowerBaudTest_Step(&r,61000,true);
    CHECK(g_power_baud_stage==POWER_BAUD_STOPPED && sends==0);
    setup(); arm(); g_power_baud_command=POWER_BAUD_COMMIT; (void)PowerBaudTest_Step(&r,65000,true);
    CHECK(g_power_baud_stage==POWER_BAUD_STOPPED && sends==0);
    setup(); arm(); tec=1; g_power_baud_command=POWER_BAUD_COMMIT; (void)PowerBaudTest_Step(&r,60001,true); CHECK(sends==0);
    setup(); arm(); g_power_baud_command=POWER_BAUD_COMMIT; (void)PowerBaudTest_Step(&r,60001,false); CHECK(sends==0);
    setup(); arm(); log_ok=false; g_power_baud_command=POWER_BAUD_COMMIT; (void)PowerBaudTest_Step(&r,60001,true); CHECK(sends==0);
    setup(); arm(); g_power_baud_command=POWER_BAUD_CANCEL; (void)PowerBaudTest_Step(&r,60001,true); CHECK(sends==0);
    setup(); arm(); accept=false; g_power_baud_command=POWER_BAUD_COMMIT; (void)PowerBaudTest_Step(&r,60001,true);
    CHECK(sends==1 && g_power_baud_stage==POWER_BAUD_STOPPED);
    (void)PowerBaudTest_Step(&r,62000,true); CHECK(sends==1);
    setup(); arm(); commit(); PowerBaudTest_OnTxEvent("TX_TIMEOUT",&sent[0]); (void)PowerBaudTest_Step(&r,60002,true);
    CHECK(sends==1 && g_power_baud_stage==POWER_BAUD_STOPPED);
    setup(); arm(); commit(); (void)PowerBaudTest_Step(&r,61001,true); CHECK(sends==1 && g_power_baud_stage==POWER_BAUD_STOPPED);
    setup(); arm(); commit(); CanFrame other=sent[0]; other.id=0x070000AA;
    PowerBaudTest_OnTxEvent("TX_DONE",&other); (void)PowerBaudTest_Step(&r,60002,true); CHECK(sends==1);
    write_done();
    CanFrame reply={.id=0x07AA0000,.extended=true,.dlc=8,.timestamp_ms=60003,.data={1,0x60,0,0,2,0,0,0}};
    other=reply; other.id=0x07AB0000; PowerBaudTest_OnFrame(&other);
    other=reply; other.timestamp_ms=60001; PowerBaudTest_OnFrame(&other);
    other=reply; other.timestamp_ms=61002; PowerBaudTest_OnFrame(&other);
    other=reply; other.data[0]=2; PowerBaudTest_OnFrame(&other);
    other=reply; other.remote=true; PowerBaudTest_OnFrame(&other);
    other=reply; other.extended=false; PowerBaudTest_OnFrame(&other);
    other=reply; other.dlc=7; PowerBaudTest_OnFrame(&other);
    (void)PowerBaudTest_Step(&r,60004,true); CHECK(g_power_baud_stage==POWER_BAUD_READ_WAIT);
    PowerBaudTest_OnFrame(&reply); (void)PowerBaudTest_Step(&r,60005,true);
    CHECK(g_power_baud_stage==POWER_BAUD_DONE && sends==2 && strstr(output,"NOT a migration PASS"));
    CHECK(strstr(output,"manual power cycle") && strstr(output,"ONE submission only"));
    for(unsigned i=0;i<10;++i) { g_power_baud_command=POWER_BAUD_COMMIT; (void)PowerBaudTest_Step(&r,60006+i,true); }
    CHECK(sends==2); g_power_baud_command=POWER_BAUD_ARM; (void)PowerBaudTest_Step(&r,60100,true); CHECK(sends==2);
    /* Reset explicitly destroys old authorization; no implicit repeated write. */
    PowerBaudTest_Init(0,log_text); CHECK(g_power_baud_command==0 && g_power_baud_stage==POWER_BAUD_IDLE);
    setup(); arm(); commit(); write_done(); (void)PowerBaudTest_Step(&r,61002,true);
    CHECK(sends==2 && g_power_baud_stage==POWER_BAUD_STOPPED);
    /* Unsigned time arithmetic survives MCU tick wrap. */
    setup(); PowerBaudTest_Init(UINT32_MAX-60000U,log_text); fresh(0); g_power_baud_command=POWER_BAUD_ARM;
    (void)PowerBaudTest_Step(&r,0,true); CHECK(g_power_baud_stage==POWER_BAUD_ARMED);
    puts("power baud gate: only a simulated transport; NOT a device PASS");
    printf("%u checks passed\n",checks); return 0;
}
