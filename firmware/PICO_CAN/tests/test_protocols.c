#include "device_reader.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned checks;
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #x); exit(1); } } while (0)
static CanFrame bms_fixture(uint16_t id) {
    /* Golden total: 50 V, -1 A, 10 Ah; CRC generated independently via table algorithm. */
    CanFrame f = {.id = id, .dlc = 8U, .data = {0x13, 0x88, 0xFF, 0x9C, 0x03, 0xE8, 0, 0}};
    uint16_t crc = Bms_Crc16(f.data, 6);
    f.data[6] = (uint8_t)(crc >> 8); f.data[7] = (uint8_t)crc;
    return f;
}
static CanFrame power_fixture(uint8_t type) {
    CanFrame f = {.id = ((uint32_t)type << 24) | 0x00AA0000U, .extended = true, .dlc = 8U};
    return f;
}
static void test_bms(void) {
    CHECK(Bms_Crc16((const uint8_t *)"123456789", 9) == 0x4B37U);
    CanFrame f;
    CHECK(Bms_BuildQuery(0x100, 8, &f));
    CHECK(f.id == 0x100 && f.remote && !f.extended && f.dlc == 8);
    CHECK(Bms_BuildQuery(0x105, 0, &f) && f.dlc == 0);
    CHECK(!Bms_BuildQuery(0x12F, 8, &f));
    CHECK(!Bms_BuildQuery(0x100, 7, &f));
    CHECK(!Bms_BuildQuery(0x100, 8, NULL));
    BmsState state = {0}; uint8_t index = 255;
    f = bms_fixture(0x100);
    CHECK(Bms_Crc16(f.data, 6) == 0x2312U);
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_OK);
    CHECK(index == 0 && state.voltage_mv == 50000U && state.current_ma == -1000 && state.remaining_mah == 10000U);
    BmsState saved = state;
    f.data[7] ^= 1;
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_INVALID);
    CHECK(memcmp(&state, &saved, sizeof(state)) == 0);
    f = bms_fixture(0x100); uint8_t c = f.data[6]; f.data[6] = f.data[7]; f.data[7] = c;
    CHECK(Bms_Parse(&f, BYTE_ORDER_LITTLE, &state, &index) == PROTOCOL_OK);
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_INVALID);
    CHECK(Bms_Parse(&f, BYTE_ORDER_UNCONFIRMED, &state, &index) == PROTOCOL_INVALID);
    f = bms_fixture(0x100); f.remote = true;
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_INVALID);
    f.remote = false; f.dlc = 7;
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_INVALID);
    f.dlc = 9;
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_INVALID);
    f.dlc = 8; f.extended = true;
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_IGNORED);
    f.extended = false; f.id = 0x104;
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_IGNORED);
    CHECK(Bms_Parse(NULL, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_INVALID);
    f = (CanFrame){.id = 0x101, .dlc = 8, .data = {0x07,0xD0,0,0x2A,0,0x4B,0,0}};
    uint16_t crc = Bms_Crc16(f.data, 6); f.data[6] = (uint8_t)(crc >> 8); f.data[7] = (uint8_t)crc;
    CHECK(crc == 0x81A1U);
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_OK);
    CHECK(index == 1 && state.full_mah == 20000 && state.cycles == 42 && state.soc_percent == 75);
    f.data[5] = 101; crc = Bms_Crc16(f.data, 6); f.data[6] = (uint8_t)(crc >> 8); f.data[7] = (uint8_t)crc;
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_INVALID);
    f = (CanFrame){.id=0x105,.dlc=8,.data={0x0B,0xA5,0x0A,0x47,0x0B,0xA5,0,0}};
    crc = Bms_Crc16(f.data, 6); f.data[6] = (uint8_t)(crc >> 8); f.data[7] = (uint8_t)crc;
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_OK);
    CHECK(index == 4 && state.temperature_decic[0] == 250 && state.temperature_decic[1] == -100);
    f = bms_fixture(0x102);
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_OK && index == 2 && state.protection == 0x3E8);
    f = bms_fixture(0x103);
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_OK && index == 3 && state.mos_status == 0x1388);
    /* Full signed range, including minimum int16. */
    f = bms_fixture(0x100); f.data[2] = 0x80; f.data[3] = 0;
    crc = Bms_Crc16(f.data, 6); f.data[6] = (uint8_t)(crc >> 8); f.data[7] = (uint8_t)crc;
    CHECK(Bms_Parse(&f, BYTE_ORDER_BIG, &state, &index) == PROTOCOL_OK && state.current_ma == -327680);
}
static void test_power(void) {
    CanFrame f;
    CHECK(Power_BuildQuery(0xAA, 0, &f) && f.id == 0x050000AA && f.extended && !f.remote && f.dlc == 8);
    CHECK(Power_BuildQuery(0xAA, 1, &f) && f.id == 0x020000AA && f.data[0] == 0);
    CHECK(Power_BuildQuery(0xAA, 2, &f) && f.data[0] == 0xCA);
    CHECK(Power_BuildQuery(0xAA, 3, &f) && f.id == 0x070000AA && f.data[0] == 1 && f.data[1] == 0x60);
    CHECK(!Power_BuildQuery(0xAA, POWER_QUERY_COUNT, &f));
    CHECK(!Power_BuildQuery(0xAA, 0, NULL));
    PowerState state = {0}; uint8_t index;
    f = power_fixture(5); memcpy(f.data,"PBV1.00",7);
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_UNCONFIRMED,&state,&index) == PROTOCOL_OK && index == 0);
    CHECK(strcmp(state.version,"PBV1.00") == 0);
    f.data[0] = '\n';
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_UNCONFIRMED,&state,&index) == PROTOCOL_INVALID);
    f = power_fixture(7); f.data[0]=1; f.data[1]=0x60; f.data[4]=2;
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_UNCONFIRMED,&state,&index) == PROTOCOL_OK && index==3 && state.can_baud_code==2);
    f.data[5] = 1;
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_UNCONFIRMED,&state,&index) == PROTOCOL_OK);
    CHECK(state.parameters[0].upper_bytes_nonzero && state.can_baud_code == 2);
    f.data[5] = 0; f.data[4]=0;
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_UNCONFIRMED,&state,&index) == PROTOCOL_INVALID);
    f.data[4]=2; f.data[0]=3;
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_UNCONFIRMED,&state,&index) == PROTOCOL_IGNORED);
    f = power_fixture(3); f.id |= 0x1234U;
    const uint8_t data[] = {0x13,0x88,0x12,0xC0,25,0x01,0x02,0x03}; memcpy(f.data,data,8);
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_UNCONFIRMED,&state,&index) == PROTOCOL_OK && index == 1);
    CHECK(!state.numeric_status_confirmed && state.battery_mv==0 && state.temperature_c==25 && state.status03_id==f.id);
    CHECK(memcmp(state.status03_raw,data,8)==0);
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_BIG,&state,&index) == PROTOCOL_OK);
    CHECK(state.numeric_status_confirmed && state.battery_mv==50000 && state.motor_mv==48000 && state.fault_and_switch_bits==0x010203);
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_LITTLE,&state,&index) == PROTOCOL_OK);
    CHECK(state.battery_mv == 0x8813U*10 && state.fault_and_switch_bits==0x030201);
    f = power_fixture(4); f.data[1]=100;
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_BIG,&state,&index) == PROTOCOL_OK && index==2 && state.branch_current_ma[0]==1000);
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_LITTLE,&state,&index) == PROTOCOL_OK && state.branch_current_ma[0]==256000);
    PowerState saved = state; f.remote=true;
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_BIG,&state,&index) == PROTOCOL_INVALID);
    CHECK(memcmp(&saved,&state,sizeof(state))==0);
    f.remote=false; f.dlc=0;
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_BIG,&state,&index) == PROTOCOL_INVALID);
    f.dlc=8; f.id ^= 1U<<16;
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_BIG,&state,&index) == PROTOCOL_IGNORED);
    f = power_fixture(8);
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_BIG,&state,&index) == PROTOCOL_IGNORED);
    f = power_fixture(3); f.id |= 0x20000000U;
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_BIG,&state,&index) == PROTOCOL_INVALID);
    CHECK(!CanFrame_IsValid(&f));
    CHECK(!CanFrame_IsValid(NULL));
}

static void test_power_hardware_capture(void) {
    /* Exact USB-CAN capture, 2026-11-01 11:39; V1.08 board.
       State word order subsequently confirmed BIG by user. */
    static const CanFrame capture[] = {
        {.id=0x03AA0000U,.extended=true,.dlc=8,.data={0x12,0x6a,0x12,0x50,0x2d,0xd0,0x00,0x00}},
        {.id=0x04AA0000U,.extended=true,.dlc=8,.data={0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01}},
        {.id=0x07AA0000U,.extended=true,.dlc=8,.data={0x01,0x60,0x00,0x00,0x01,0x01,0x00,0x03}},
        {.id=0x07AA0000U,.extended=true,.dlc=8,.data={0x02,0x60,0x00,0x00,0x01,0x00,0x03,0x01}},
        {.id=0x07AA0000U,.extended=true,.dlc=8,.data={0x04,0x60,0x00,0x00,0x00,0x03,0x01,0x00}},
        {.id=0x07AA0000U,.extended=true,.dlc=8,.data={0x05,0x60,0x00,0x00,0x03,0x01,0x00,0x00}},
        {.id=0x07AA0000U,.extended=true,.dlc=8,.data={0x06,0x60,0x00,0x00,0x00,0x00,0x00,0x00}},
        {.id=0x07AA0000U,.extended=true,.dlc=8,.data={0x07,0x60,0x00,0x00,0x00,0x00,0x00,0x00}},
        {.id=0x07AA0000U,.extended=true,.dlc=8,.data={0x01,0x80,0x00,0x00,0x00,0x00,0xa0,0x42}},
        {.id=0x07AA0000U,.extended=true,.dlc=8,.data={0x03,0x80,0x00,0x00,0x00,0x00,0x5c,0x42}},
        {.id=0x07AA0000U,.extended=true,.dlc=8,.data={0x04,0x80,0x00,0x00,0x00,0x00,0xa0,0x40}},
    };
    PowerState state = {0}; uint8_t index = 255;
    for (uint8_t i=0; i<sizeof(capture)/sizeof(capture[0]); ++i) {
        CHECK(Power_Parse(&capture[i],0xAA,BYTE_ORDER_BIG,&state,&index)==PROTOCOL_OK);
        CHECK(index==i+1U);
    }
    CHECK(state.battery_mv==47140 && state.motor_mv==46880 && state.temperature_c==45);
    CHECK(state.fault_and_switch_bits==0xD00000U);
    CHECK(state.branch_current_ma[0]==0 && state.branch_current_ma[3]==10);
    CHECK(state.can_baud_code==1 && state.parameters[0].bits_le==0x03000101U);
    CHECK(state.parameters[0].upper_bytes_nonzero && state.parameters[0].numeric_valid);
    CHECK(state.parameters[1].value_u8==1 && state.parameters[2].value_u8==0);
    CHECK(state.parameters[3].value_u8==3 && state.parameters[5].value_u8==0);
    CHECK(state.parameters[4].value_u8==0 && state.reported_id_mismatch);
    CHECK(state.parameters[6].value_float==80.0f && state.parameters[7].value_float==55.0f);
    CHECK(state.parameters[8].value_float==5.0f);
    CanFrame f=power_fixture(5); memcpy(f.data,"V1.08",5);
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_BIG,&state,&index)==PROTOCOL_OK && index==0);
    CHECK(strcmp(state.version,"V1.08")==0);
    for (uint8_t i=0; i<POWER_QUERY_COUNT; ++i) {
        CHECK(Power_BuildQuery(0xAA,i,&f));
        CHECK((f.id>>24)==5U || (f.id>>24)==2U || (f.id>>24)==7U);
        CHECK(!f.remote && f.extended && f.dlc==8);
        if(i>=3U) {
            CHECK(((uint16_t)f.data[0] | ((uint16_t)f.data[1]<<8))==power_parameter_indices[i-3U]);
            CHECK(power_parameter_indices[i-3U]!=0x6003);
            for(uint8_t j=2; j<8; ++j) CHECK(f.data[j]==0);
        }
    }
    /* Nonfinite float replies remain visible as raw data, never a valid numeric value. */
    f=power_fixture(7); f.data[0]=1;f.data[1]=0x80;f.data[6]=0x80;f.data[7]=0x7F;
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_BIG,&state,&index)==PROTOCOL_OK);
    CHECK(index==9 && !state.parameters[6].numeric_valid);
    f.data[6]=0xC0;
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_BIG,&state,&index)==PROTOCOL_OK && !state.parameters[6].numeric_valid);
    f=power_fixture(7);f.data[0]=6;f.data[1]=0x60;f.data[4]=0xAA;
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_BIG,&state,&index)==PROTOCOL_OK && !state.reported_id_mismatch);
    /* Invalid known baud must not mutate state. */
    PowerState saved=state;
    f.data[0]=1; f.data[4]=5;
    CHECK(Power_Parse(&f,0xAA,BYTE_ORDER_BIG,&state,&index)==PROTOCOL_INVALID);
    CHECK(memcmp(&saved,&state,sizeof(state))==0);
}

static ReaderConfig config(ReaderKind kind) {
    return (ReaderConfig){.kind=kind,.power_id=0xAA,.bms_rtr_dlc=8,.max_attempts=3,
        .bms_crc_order=BYTE_ORDER_BIG,.power_status_order=BYTE_ORDER_UNCONFIRMED,
        .timeout_ms=500,.interval_ms=200,.stale_ms=10000};
}
static unsigned sent; static bool accept_send=true; static CanFrame last_request;
static bool send_fake(void *context, const CanFrame *frame, uint32_t now) {
    (void)context; (void)now; last_request=*frame; ++sent; return accept_send;
}
static void test_scheduler(void) {
    ReaderConfig c=config(READER_BMS); DeviceReader r;
    CHECK(DeviceReader_Init(&r,&c,0)); sent=0; accept_send=true;
    DeviceReader_Step(&r,999,send_fake,NULL); CHECK(sent==0);
    DeviceReader_Step(&r,1000,send_fake,NULL); CHECK(sent==1 && r.pending && last_request.remote);
    CanFrame f=bms_fixture(0x100); f.timestamp_ms=999;
    CHECK(DeviceReader_OnFrame(&r,&f)==0 && r.pending); /* old queued frame */
    f.timestamp_ms=1010;
    CHECK(DeviceReader_OnFrame(&r,&f)==0 && !r.pending && r.query_index==1 && r.valid_mask==1);
    DeviceReader_Step(&r,1209,send_fake,NULL); CHECK(sent==1);
    DeviceReader_Step(&r,1210,send_fake,NULL); CHECK(sent==2 && last_request.id==0x101);
    f=bms_fixture(0x100); f.timestamp_ms=1220;
    CHECK(DeviceReader_OnFrame(&r,&f)==0 && r.pending && r.query_index==1);
    f=bms_fixture(0x101); f.timestamp_ms=1221; f.data[7]^=1;
    CHECK(DeviceReader_OnFrame(&r,&f)==-1 && r.stats.invalid==1 && r.pending);
    DeviceReader_Step(&r,1710,send_fake,NULL); CHECK(r.stats.timeouts==1 && !r.pending);
    DeviceReader_Step(&r,1910,send_fake,NULL); CHECK(r.pending && r.attempts==2);
    DeviceReader_Step(&r,2410,send_fake,NULL); DeviceReader_Step(&r,2610,send_fake,NULL);
    CHECK(r.pending && r.attempts==3);
    DeviceReader_Step(&r,3110,send_fake,NULL); CHECK(r.query_index==2 && r.stats.query_failures==1 && r.stats.timeouts==3);
    DeviceReader_Step(&r,11221,send_fake,NULL); CHECK(r.valid_mask==0 && r.seen_mask==1);
    /* Immediate submit failure is bounded and never counted as a reply timeout. */
    CHECK(DeviceReader_Init(&r,&c,0)); accept_send=false;
    DeviceReader_Step(&r,1000,send_fake,NULL); DeviceReader_Step(&r,1200,send_fake,NULL); DeviceReader_Step(&r,1400,send_fake,NULL);
    CHECK(r.stats.tx_rejected==3 && r.stats.timeouts==0 && r.stats.query_failures==1 && r.query_index==1);
    /* Wraparound deadlines, one full power query cycle, fresh valid mask. */
    c=config(READER_POWER); uint32_t t=0xFFFFFF00U;
    CHECK(DeviceReader_Init(&r,&c,t)); accept_send=true;
    t+=1000; DeviceReader_Step(&r,t,send_fake,NULL); CHECK(r.pending);
    for (uint8_t job=0;job<POWER_QUERY_COUNT;++job) {
        uint8_t type=job==0 ? 5 : job==1 ? 3 : job==2 ? 4 : 7;
        f=power_fixture(type); f.timestamp_ms=t+10;
        if(job==0) memcpy(f.data,"PBV1.00",7);
        if(job>=3) {
            const uint16_t parameter=power_parameter_indices[job-3];
            f.data[0]=(uint8_t)parameter; f.data[1]=(uint8_t)(parameter>>8); f.data[4]=1;
        }
        CHECK(DeviceReader_OnFrame(&r,&f)==job);
        t+=210; if(job+1U<POWER_QUERY_COUNT) DeviceReader_Step(&r,t,send_fake,NULL);
    }
    CHECK(r.stats.cycles==1 && r.valid_mask==POWER_ALL_FRESH_MASK && r.stats.replies==POWER_QUERY_COUNT && !r.pending);
    CHECK(DeviceReader_OnFrame(&r,NULL)==-1);
    f=power_fixture(9); CHECK(DeviceReader_OnFrame(&r,&f)==-1 && r.stats.ignored==1);
    /* Response arriving at/after timeout cannot complete the outstanding attempt. */
    c=config(READER_BMS); CHECK(DeviceReader_Init(&r,&c,0)); DeviceReader_Step(&r,1000,send_fake,NULL);
    f=bms_fixture(0x100); f.timestamp_ms=1500; CHECK(DeviceReader_OnFrame(&r,&f)==0 && r.pending);
    c.max_attempts=0; CHECK(!DeviceReader_Init(&r,&c,0));
    c=config(READER_BMS); c.timeout_ms=0; CHECK(!DeviceReader_Init(&r,&c,0));
    c=config(READER_BMS); c.stale_ms=1; CHECK(!DeviceReader_Init(&r,&c,0));
    CHECK(!DeviceReader_Init(NULL,&c,0));
    CHECK(!DeviceReader_Init(&r,NULL,0));
}
int main(void) { test_bms(); test_power(); test_power_hardware_capture(); test_scheduler(); printf("protocol/scheduler: %u checks passed\n",checks); return 0; }
