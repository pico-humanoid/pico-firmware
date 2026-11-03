#include "dual_test_frames.h"
#include <stdio.h>
#include <stdlib.h>

static unsigned checks, sends;
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr,"%s:%d: %s\n",__FILE__,__LINE__,#x); exit(1); } } while(0)
static DualDeviceReader pair;
static bool reject, last_extended;
static uint32_t last_send;
static ReaderConfig cfg(ReaderKind kind) {
    return (ReaderConfig){.kind=kind,.power_id=0xAA,.bms_rtr_dlc=0,.max_attempts=1,
        .bms_crc_order=BYTE_ORDER_BIG,.power_status_order=BYTE_ORDER_BIG,
        .timeout_ms=700,.interval_ms=200,.stale_ms=10000};
}
static void init(uint32_t now) {
    ReaderConfig b=cfg(READER_BMS), p=cfg(READER_POWER);
    CHECK(DualDeviceReader_Init(&pair,&b,&p,now));
    sends=0; reject=false;
}
static bool send_fake(void *context, const CanFrame *f, uint32_t now) {
    CHECK(context == &pair);
    CHECK(!pair.bms.pending && !pair.power.pending);
    if (sends) CHECK((uint32_t)(now-last_send)>=200U);
    CHECK(f->extended ? (!f->remote && (f->id>>24==5 || f->id>>24==2 || f->id>>24==7)) :
          (f->remote && f->dlc==0 && f->id>=0x100 && f->id<=0x105 && f->id!=0x104));
    last_extended=f->extended; last_send=now; ++sends;
    return !reject;
}
static void reply(DeviceReader *r, uint32_t now) {
    CanFrame f=dual_test_reply(r->config.kind,r->query_index,now);
    CHECK(DeviceReader_OnFrame(r,&f)>=0);
}
static void run(uint32_t start, uint32_t duration, int missing) {
    for (uint32_t d=0; d<=duration; d+=10U) {
        uint32_t now=start+d;
        DualDeviceReader_Step(&pair,now,send_fake,&pair);
        CHECK(!(pair.bms.pending && pair.power.pending));
        if (pair.bms.pending && missing!=0) reply(&pair.bms,now+1U);
        if (pair.power.pending && missing!=1) reply(&pair.power,now+1U);
    }
}
int main(void) {
    ReaderConfig b=cfg(READER_BMS), p=cfg(READER_POWER);
    CHECK(!DualDeviceReader_Init(NULL,&b,&p,0));
    CHECK(!DualDeviceReader_Init(&pair,NULL,&p,0));
    CHECK(!DualDeviceReader_Init(&pair,&p,&b,0));
    p.timeout_ms=0; CHECK(!DualDeviceReader_Init(&pair,&b,&p,0));
    init(0); run(0,65000,-1);
    CHECK(pair.bms.stats.replies>=150 && pair.power.stats.replies>=150);
    CHECK(pair.bms.stats.tx_submitted==pair.power.stats.tx_submitted+1U);
    CHECK(pair.bms.stats.cycles>=30 && pair.power.stats.cycles>=12);
    CHECK(pair.bms.valid_mask==0x1F && pair.power.valid_mask==POWER_ALL_FRESH_MASK);
    CHECK(pair.bms.stats.timeouts==0 && pair.power.stats.timeouts==0);
    CHECK(pair.power.power.can_baud_code==2);
    DualDeviceReader_Age(&pair,80000);
    CHECK(pair.bms.valid_mask==0 && pair.power.valid_mask==0);
    /* Silent BMS / silent power: never starve the healthy device. */
    init(0); run(0,65000,0);
    CHECK(pair.bms.stats.timeouts>50 && pair.bms.stats.replies==0);
    CHECK(pair.power.stats.replies>50 && pair.power.stats.timeouts==0);
    CHECK(pair.power.seen_mask==POWER_ALL_FRESH_MASK && pair.power.valid_mask!=0);
    /* With 700ms timeouts on every BMS query, a full power sweep can exceed
       10s. Old samples must expire rather than be reported as all-fresh. */
    CHECK(pair.power.valid_mask!=POWER_ALL_FRESH_MASK);
    init(0); run(0,65000,1);
    CHECK(pair.power.stats.timeouts>50 && pair.power.stats.replies==0);
    CHECK(pair.bms.stats.replies>50 && pair.bms.stats.timeouts==0);
    CHECK(pair.bms.valid_mask==0x1F);
    /* Invalid CRC cannot complete a pending query; power still runs after timeout. */
    init(0); DualDeviceReader_Step(&pair,1000,send_fake,&pair);
    CanFrame f=dual_test_reply(READER_BMS,0,1001); f.data[7]^=1;
    CHECK(DeviceReader_OnFrame(&pair.bms,&f)==-1 && pair.bms.pending);
    f=dual_test_reply(READER_BMS,1,1002);
    CHECK(DeviceReader_OnFrame(&pair.bms,&f)==1 && pair.bms.pending);
    DualDeviceReader_Step(&pair,1699,send_fake,&pair); CHECK(sends==1);
    DualDeviceReader_Step(&pair,1700,send_fake,&pair);
    CHECK(pair.bms.stats.query_failures==1 && !pair.bms.pending);
    DualDeviceReader_Step(&pair,1701,send_fake,&pair); CHECK(sends==2 && last_extended);
    /* Rejected submissions alternate too, without tight-loop retries. */
    init(0); reject=true;
    DualDeviceReader_Step(&pair,1000,send_fake,&pair);
    DualDeviceReader_Step(&pair,1001,send_fake,&pair); CHECK(sends==1);
    DualDeviceReader_Step(&pair,1200,send_fake,&pair); CHECK(sends==2 && last_extended);
    CHECK(pair.bms.stats.tx_rejected==1 && pair.power.stats.tx_rejected==1);
    /* Startup deadlines, spacing, freshness and both readers survive tick wrap. */
    init(UINT32_MAX-500U); run(UINT32_MAX-500U,7000,-1);
    CHECK(pair.bms.stats.cycles>=3 && pair.power.stats.cycles>=1);
    CHECK(pair.bms.stats.timeouts==0 && pair.power.stats.timeouts==0);
    printf("dual reader: %u checks passed\n",checks);
    return 0;
}
