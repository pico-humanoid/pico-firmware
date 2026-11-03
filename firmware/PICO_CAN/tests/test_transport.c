#include "transport/can_transport.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned checks;
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr,"%s:%d: %s\n",__FILE__,__LINE__,#x); exit(1); } } while(0)
FDCAN_GlobalTypeDef fake_fdcan1;
static FDCAN_HandleTypeDef handle = {.Instance=FDCAN1}, other;
static uint32_t clock_hz=16000000U, tick, pending_mask, latest_mask, aborts;
static uint32_t free_level=3;
static HAL_StatusTypeDef status=HAL_OK, rx_status=HAL_OK, submit_status=HAL_OK;
static FDCAN_FilterTypeDef configured_filter, standard_filter, extended_filter;
static FDCAN_TxHeaderTypeDef submitted;
static uint8_t submitted_data[8];
static FDCAN_RxHeaderTypeDef rx_header;
static uint8_t rx_data[64]; static uint32_t rx_count;
static FDCAN_TxEventFifoTypeDef events[8]; static uint8_t events_in, events_out;
static unsigned logged_submit, logged_done, logged_timeout;
static CanFrame last_log;
uint32_t HAL_GetTick(void) { return tick; }
uint32_t HAL_RCC_GetPCLK1Freq(void) { return clock_hz; }
HAL_StatusTypeDef HAL_FDCAN_DeInit(FDCAN_HandleTypeDef *h) { (void)h; return status; }
HAL_StatusTypeDef HAL_FDCAN_Init(FDCAN_HandleTypeDef *h) { (void)h; return status; }
HAL_StatusTypeDef HAL_FDCAN_ConfigFilter(FDCAN_HandleTypeDef *h,FDCAN_FilterTypeDef *f) { (void)h; configured_filter=*f; if(f->IdType==FDCAN_STANDARD_ID)standard_filter=*f; else extended_filter=*f; return status; }
HAL_StatusTypeDef HAL_FDCAN_ConfigGlobalFilter(FDCAN_HandleTypeDef *h,uint32_t a,uint32_t b,uint32_t c,uint32_t d) {
    (void)h; CHECK(a==FDCAN_REJECT && b==FDCAN_REJECT && c==FDCAN_REJECT_REMOTE && d==FDCAN_REJECT_REMOTE); return status;
}
HAL_StatusTypeDef HAL_FDCAN_ActivateNotification(FDCAN_HandleTypeDef *h,uint32_t flags,uint32_t buffers) {
    (void)h; (void)buffers; CHECK((flags & FDCAN_IT_BUS_OFF)!=0U); return status;
}
HAL_StatusTypeDef HAL_FDCAN_Start(FDCAN_HandleTypeDef *h) { (void)h; return status; }
uint32_t HAL_FDCAN_GetTxFifoFreeLevel(const FDCAN_HandleTypeDef *h) { (void)h; return free_level; }
HAL_StatusTypeDef HAL_FDCAN_AddMessageToTxFifoQ(FDCAN_HandleTypeDef *h,const FDCAN_TxHeaderTypeDef *header,const uint8_t *data) {
    (void)h; submitted=*header; memcpy(submitted_data,data,8);
    if(submit_status!=HAL_OK) return submit_status;
    for(unsigned i=0;i<3;++i) if(!(pending_mask & (1U<<i))) { latest_mask=1U<<i; pending_mask|=latest_mask; return HAL_OK; }
    return HAL_ERROR;
}
uint32_t HAL_FDCAN_GetLatestTxFifoQRequestBuffer(const FDCAN_HandleTypeDef *h) { (void)h; return latest_mask; }
HAL_StatusTypeDef HAL_FDCAN_GetTxEvent(FDCAN_HandleTypeDef *h,FDCAN_TxEventFifoTypeDef *event) {
    (void)h; if(events_out==events_in)return HAL_ERROR;
    *event=events[events_out++]; fake_fdcan1.TXEFS=events_in-events_out; return HAL_OK;
}
uint32_t HAL_FDCAN_IsTxBufferMessagePending(const FDCAN_HandleTypeDef *h,uint32_t mask) { (void)h; return (pending_mask & mask)!=0; }
HAL_StatusTypeDef HAL_FDCAN_AbortTxRequest(FDCAN_HandleTypeDef *h,uint32_t mask) { (void)h; ++aborts; pending_mask &= ~mask; return HAL_OK; }
uint32_t HAL_FDCAN_GetRxFifoFillLevel(const FDCAN_HandleTypeDef *h,uint32_t fifo) { (void)h; (void)fifo; return rx_count; }
HAL_StatusTypeDef HAL_FDCAN_GetRxMessage(FDCAN_HandleTypeDef *h,uint32_t fifo,FDCAN_RxHeaderTypeDef *header,uint8_t *data) {
    (void)h; (void)fifo; if(rx_status!=HAL_OK)return rx_status;
    --rx_count; *header=rx_header; memcpy(data,rx_data,64); return HAL_OK;
}
static void log_fake(const char *event,const CanFrame *frame) {
    last_log=*frame;
    if(!strcmp(event,"TX_SUBMIT"))++logged_submit;
    if(!strcmp(event,"TX_DONE"))++logged_done;
    if(!strcmp(event,"TX_TIMEOUT"))++logged_timeout;
}
/* These are HAL input checks, not a measurement of the physical CAN clock. */
static void check_profile(uint32_t bitrate) {
    CHECK(handle.Init.ClockDivider==FDCAN_CLOCK_DIV1);
    CHECK(handle.Init.FrameFormat==FDCAN_FRAME_CLASSIC);
    CHECK(handle.Init.Mode==FDCAN_MODE_NORMAL);
    CHECK(handle.Init.AutoRetransmission==DISABLE);
    CHECK(handle.Init.NominalPrescaler==(bitrate==500000U ? 2U : 1U));
    CHECK(handle.Init.NominalSyncJumpWidth==2U);
    CHECK(handle.Init.NominalTimeSeg1==13U && handle.Init.NominalTimeSeg2==2U);
    const uint32_t total_tq=1U+handle.Init.NominalTimeSeg1+handle.Init.NominalTimeSeg2;
    /* ClockDivider was checked as DIV1 above; its HAL enum is not a divisor. */
    CHECK(clock_hz/(handle.Init.NominalPrescaler*total_tq)==bitrate);
    CHECK((1U+handle.Init.NominalTimeSeg1)*1000U/total_tq==875U);
    CHECK(handle.Init.NominalSyncJumpWidth<=handle.Init.NominalTimeSeg2);
}
static void reset(void) {
    status=rx_status=submit_status=HAL_OK; clock_hz=16000000;
    fake_fdcan1.TXEFS=0; pending_mask=0; latest_mask=0; aborts=0; free_level=3;
    events_in=events_out=0; rx_count=0; logged_submit=logged_done=logged_timeout=0;
    memset(&handle.Init,0xFF,sizeof(handle.Init)); /* Do not inherit zero-valued defaults. */
    CHECK(CanTransport_Init(&handle,500000,CAN_FILTER_BMS,0xAA,log_fake));
    check_profile(500000U);
}
static void complete(uint32_t marker,uint32_t id,uint32_t mask) {
    events[events_in++]=(FDCAN_TxEventFifoTypeDef){.MessageMarker=marker,.Identifier=id};
    fake_fdcan1.TXEFS=events_in-events_out; pending_mask &= ~mask;
}
int main(void) {
    CHECK(!CanTransport_Init(NULL,500000,CAN_FILTER_BMS,0xAA,log_fake));
    CHECK(!CanTransport_Init(&other,500000,CAN_FILTER_BMS,0xAA,log_fake));
    CHECK(!CanTransport_Init(&handle,250000,CAN_FILTER_BMS,0xAA,log_fake));
    clock_hz=8000000; CHECK(!CanTransport_Init(&handle,500000,CAN_FILTER_BMS,0xAA,log_fake));
    clock_hz=16000000; status=HAL_ERROR; CHECK(!CanTransport_Init(&handle,500000,CAN_FILTER_BMS,0xAA,log_fake));
    reset();
    CHECK(handle.Init.NominalPrescaler==2 && handle.Init.NominalTimeSeg1==13 && handle.Init.NominalTimeSeg2==2);
    CHECK(handle.Init.Mode==FDCAN_MODE_NORMAL && handle.Init.AutoRetransmission==DISABLE);
    CHECK(configured_filter.IdType==FDCAN_STANDARD_ID && configured_filter.FilterID1==0x100 && configured_filter.FilterID2==0x105);
    memset(&handle.Init,0xFF,sizeof(handle.Init));
    CHECK(CanTransport_Init(&handle,1000000,CAN_FILTER_POWER,0x12,log_fake));
    check_profile(1000000U);
    CHECK(handle.Init.NominalPrescaler==1 && handle.Init.ExtFiltersNbr==1 && handle.Init.StdFiltersNbr==0);
    CHECK(configured_filter.IdType==FDCAN_EXTENDED_ID && configured_filter.FilterID1==0x00120000 && configured_filter.FilterID2==0x00FF0000);
    CHECK(CanTransport_Init(&handle,500000,CAN_FILTER_DUAL,0xAA,log_fake));
    check_profile(500000U);
    CHECK(handle.Init.StdFiltersNbr==1 && handle.Init.ExtFiltersNbr==1);
    CHECK(standard_filter.FilterIndex==0 && standard_filter.FilterType==FDCAN_FILTER_RANGE &&
          standard_filter.FilterID1==0x100 && standard_filter.FilterID2==0x105);
    CHECK(extended_filter.FilterIndex==0 && extended_filter.FilterType==FDCAN_FILTER_MASK &&
          extended_filter.FilterID1==0x00AA0000 && extended_filter.FilterID2==0x00FF0000);
    CanFrame f={.id=0x100,.remote=true,.dlc=8,.data={1,2,3,4,5,6,7,8}};
    CHECK(CanTransport_Submit(&f,1000));
    CHECK(submitted.FDFormat==FDCAN_CLASSIC_CAN && submitted.BitRateSwitch==FDCAN_BRS_OFF);
    CHECK(submitted.TxEventFifoControl==FDCAN_STORE_TX_EVENTS);
    CHECK(submitted.TxFrameType==FDCAN_REMOTE_FRAME && submitted.IdType==FDCAN_STANDARD_ID && submitted.DataLength==8);
    CHECK(submitted_data[0]==0 && submitted_data[7]==0 && logged_submit==1 && logged_done==0);
    uint32_t marker=submitted.MessageMarker, mask=latest_mask;
    complete(marker,f.id,mask); CanTransport_Service(1010);
    CHECK(logged_done==1 && last_log.timestamp_ms==1010 && CanTransport_GetStats().tx_completed==1);
    f.remote=false; f.extended=true; f.id=0x070000AA; f.dlc=2;
    CHECK(CanTransport_Submit(&f,1020));
    CHECK(submitted.FDFormat==FDCAN_CLASSIC_CAN && submitted.BitRateSwitch==FDCAN_BRS_OFF);
    CHECK(submitted.TxEventFifoControl==FDCAN_STORE_TX_EVENTS);
    CHECK(submitted.TxFrameType==FDCAN_DATA_FRAME && submitted.IdType==FDCAN_EXTENDED_ID && submitted.DataLength==2 && submitted_data[0]==1 && submitted_data[2]==0);
    CanTransport_Service(1320); CHECK(logged_timeout==1 && aborts==1);
    CanTransport_Service(1321); CHECK(logged_timeout==1);
    CHECK(CanTransport_GetStats().tx_timed_out==1);
    CHECK(!CanTransport_Submit(NULL,1400));
    f.dlc=9; CHECK(!CanTransport_Submit(&f,1400));
    f.dlc=8; f.id=0x20000000; CHECK(!CanTransport_Submit(&f,1400));
    f.id=0x100; f.extended=false; free_level=0; CHECK(!CanTransport_Submit(&f,1400));
    free_level=3; submit_status=HAL_ERROR; CHECK(!CanTransport_Submit(&f,1400)); submit_status=HAL_OK;
    /* Fill all tracked hardware slots and reject the fourth request. */
    reset();
    for(unsigned i=0;i<3;++i)CHECK(CanTransport_Submit(&f,0));
    CHECK(!CanTransport_Submit(&f,0));
    CanTransport_Service(300); CanTransport_Service(301); CHECK(aborts==3);
    CHECK(CanTransport_Submit(&f,400));
    /* A completion with an unknown marker is not falsely attributed. */
    complete(255,0x777,0); CanTransport_Service(401); CHECK(CanTransport_GetStats().tx_event_unknown==1);
    reset();
    rx_header=(FDCAN_RxHeaderTypeDef){.Identifier=0x100,.DataLength=8,.IdType=FDCAN_STANDARD_ID,.FDFormat=FDCAN_CLASSIC_CAN};
    memset(rx_data,0xAB,sizeof(rx_data)); tick=123; rx_count=1;
    HAL_FDCAN_RxFifo0Callback(&other,FDCAN_IT_RX_FIFO0_NEW_MESSAGE); CHECK(rx_count==1);
    HAL_FDCAN_RxFifo0Callback(&handle,FDCAN_IT_RX_FIFO0_NEW_MESSAGE);
    CHECK(CanTransport_Receive(&f) && f.timestamp_ms==123 && f.dlc==8 && f.data[7]==0xAB && !f.extended);
    CHECK(!CanTransport_Receive(&f)); CHECK(!CanTransport_Receive(NULL));
    rx_header.IdType=FDCAN_EXTENDED_ID; rx_header.Identifier=0x03001234; rx_header.DataLength=0; rx_header.RxFrameType=FDCAN_REMOTE_FRAME; rx_count=1;
    HAL_FDCAN_RxFifo0Callback(&handle,FDCAN_IT_RX_FIFO0_NEW_MESSAGE);
    CHECK(CanTransport_Receive(&f) && f.extended && f.remote && f.dlc==0 && f.data[0]==0);
    rx_header.RxFrameType=FDCAN_DATA_FRAME; rx_header.DataLength=15; rx_count=1;
    HAL_FDCAN_RxFifo0Callback(&handle,FDCAN_IT_RX_FIFO0_NEW_MESSAGE);
    CHECK(CanTransport_GetStats().rx_unsupported==1);
    rx_header.DataLength=8; rx_header.FDFormat=1; rx_count=1;
    HAL_FDCAN_RxFifo0Callback(&handle,FDCAN_IT_RX_FIFO0_NEW_MESSAGE);
    CHECK(CanTransport_GetStats().rx_unsupported==2);
    rx_header.FDFormat=FDCAN_CLASSIC_CAN; rx_count=1; rx_status=HAL_ERROR;
    HAL_FDCAN_RxFifo0Callback(&handle,FDCAN_IT_RX_FIFO0_NEW_MESSAGE);
    CHECK(CanTransport_GetStats().rx_read_failed==1);
    rx_status=HAL_OK; rx_count=40;
    HAL_FDCAN_RxFifo0Callback(&handle,FDCAN_IT_RX_FIFO0_NEW_MESSAGE|FDCAN_IT_RX_FIFO0_MESSAGE_LOST);
    CHECK(CanTransport_GetStats().rx_queue_dropped==9 && CanTransport_GetStats().rx_fifo_lost==1);
    unsigned received=0; while(CanTransport_Receive(&f))++received; CHECK(received==31);
    HAL_FDCAN_TxEventFifoCallback(&handle,FDCAN_IT_TX_EVT_FIFO_ELT_LOST);
    CHECK(CanTransport_GetStats().tx_event_lost==1);
    HAL_FDCAN_ErrorStatusCallback(&other,FDCAN_IT_BUS_OFF); CHECK(!CanTransport_IsBusOff());
    HAL_FDCAN_ErrorStatusCallback(&handle,FDCAN_IT_BUS_OFF); CHECK(CanTransport_IsBusOff());
    f=(CanFrame){.id=0x100,.dlc=8}; CHECK(!CanTransport_Submit(&f,500));
    reset(); CHECK(!CanTransport_IsBusOff());
    /* Lost completion + buffer reuse at the same millisecond: cancelling an
       old slot must not abort the newer owner of that hardware buffer. */
    CHECK(CanTransport_Submit(&f,0)); pending_mask=0;
    CHECK(CanTransport_Submit(&f,0));
    CanTransport_Service(300);
    CHECK(aborts==1 && CanTransport_GetStats().tx_timed_out==2);
    reset();
    /* Deadline works across HAL_GetTick wraparound. */
    CHECK(CanTransport_Submit(&f,0xFFFFFFF0U)); CanTransport_Service(0x11BU); CHECK(logged_timeout==0);
    CanTransport_Service(0x11CU); CHECK(logged_timeout==1);
    printf("transport: %u checks passed\n",checks);
    return 0;
}
