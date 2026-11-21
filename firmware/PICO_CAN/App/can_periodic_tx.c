/* Standalone selected CAN source for an independent USB-CAN monitor.
 * No RX trigger, no motor commands, no synthetic PASS verdict. */
#include "can_periodic_tx.h"
#include <stdio.h>
#include <string.h>
#if PICO_PERIODIC_BITRATE == 500000
#define PERIODIC_PRESCALER 2U
#define PERIODIC_RATE_TEXT "500000"
#define PERIODIC_PRESCALER_TEXT "2"
#elif PICO_PERIODIC_BITRATE == 1000000
#define PERIODIC_PRESCALER 1U
#define PERIODIC_RATE_TEXT "1000000"
#define PERIODIC_PRESCALER_TEXT "1"
#else
#error Unsupported periodic CAN bitrate
#endif
#if PICO_PERIODIC_CHANNEL == 1
#define PERIODIC_INSTANCE FDCAN1
#define PERIODIC_HEADER "# CAN1_PERIODIC_TX=1; channel=FDCAN1 TX=PA12 RX=PA11 AF9"
#elif PICO_PERIODIC_CHANNEL == 2
#define PERIODIC_INSTANCE FDCAN2
#define PERIODIC_HEADER "# CAN2_PERIODIC_TX=1; channel=FDCAN2 TX=PB13 RX=PB12 AF9"
#elif PICO_PERIODIC_CHANNEL == 3
#define PERIODIC_INSTANCE FDCAN3
#define PERIODIC_HEADER "# CAN3_PERIODIC_TX=1; channel=FDCAN3 TX=PA15 RX=PA8 AF11"
#else
#error Invalid periodic CAN channel
#endif
static FDCAN_HandleTypeDef *bus;
static UART_HandleTypeDef *serial;
static uint32_t ready,next_tx,next_health,submitted,completed,failed,waiting,submit_ms,pending_mask;
static uint8_t sequence,pending_data[8];
static void line(const char *s){
    (void)HAL_UART_Transmit(serial,(const uint8_t *)s,(uint16_t)strlen(s),100U);
}
static void frame(const char *event){
    char s[160];(void)snprintf(s,sizeof(s),"%lu,%s,EXT,0x123,8,%02X %02X %02X %02X %02X %02X %02X %02X\r\n",
        (unsigned long)HAL_GetTick(),event,pending_data[0],pending_data[1],pending_data[2],pending_data[3],
        pending_data[4],pending_data[5],pending_data[6],pending_data[7]);line(s);
}
void CanPeriodicTx_Init(FDCAN_HandleTypeDef *can,UART_HandleTypeDef *uart){
    bus=can;serial=uart;
    if(can->Instance!=PERIODIC_INSTANCE || HAL_RCC_GetPCLK1Freq()!=16000000U){
        line("# PERIODIC_INIT_ERROR peripheral/clock/deinit\r\n");return;
    }
    if(can->State!=HAL_FDCAN_STATE_RESET && HAL_FDCAN_DeInit(can)!=HAL_OK){
        line("# PERIODIC_INIT_ERROR deinit\r\n");return;
    }
    can->Init.ClockDivider=FDCAN_CLOCK_DIV1;can->Init.FrameFormat=FDCAN_FRAME_CLASSIC;
    can->Init.Mode=FDCAN_MODE_NORMAL;can->Init.AutoRetransmission=DISABLE;
    can->Init.TransmitPause=DISABLE;can->Init.ProtocolException=DISABLE;
    can->Init.NominalPrescaler=PERIODIC_PRESCALER;can->Init.NominalSyncJumpWidth=2;
    can->Init.NominalTimeSeg1=13;can->Init.NominalTimeSeg2=2;
    can->Init.DataPrescaler=1;can->Init.DataSyncJumpWidth=1;
    can->Init.DataTimeSeg1=1;can->Init.DataTimeSeg2=1;
    can->Init.StdFiltersNbr=0;can->Init.ExtFiltersNbr=0;
    can->Init.TxFifoQueueMode=FDCAN_TX_FIFO_OPERATION;
    if(HAL_FDCAN_Init(can)!=HAL_OK ||
       HAL_FDCAN_ConfigGlobalFilter(can,FDCAN_REJECT,FDCAN_REJECT,FDCAN_REJECT_REMOTE,FDCAN_REJECT_REMOTE)!=HAL_OK ||
       HAL_FDCAN_Start(can)!=HAL_OK){line("# PERIODIC_INIT_ERROR init/filter/start\r\n");return;}
    line(PERIODIC_HEADER " bitrate=" PERIODIC_RATE_TEXT " format=EXT id=0x123 dlc=8 period_ms=1000 auto_start=1 no_rx_trigger=1 auto_retransmission=0\r\n");
    line("# FDCAN=PCLK1=16MHz divider=1 prescaler=" PERIODIC_PRESCALER_TEXT " BS1=13 BS2=2 SJW=2; first byte wraps 00..FF; no motor\r\n");
    line("t_ms,event,format,id,dlc,data\r\n");
    next_tx=HAL_GetTick()+2000U;next_health=HAL_GetTick()+1000U;ready=1;
}
void CanPeriodicTx_Step(void){
    if(!ready)return;
    uint32_t now=HAL_GetTick();
    while(bus->Instance->TXEFS&FDCAN_TXEFS_EFFL){
        FDCAN_TxEventFifoTypeDef e={0};
        if(HAL_FDCAN_GetTxEvent(bus,&e)!=HAL_OK){++failed;break;}
        if(waiting && e.Identifier==0x123U && e.IdType==FDCAN_EXTENDED_ID && e.MessageMarker==pending_data[0]){
            ++completed;frame("TX_DONE");waiting=0;
        }else{++failed;line("# TX_EVENT_MISMATCH\r\n");}
    }
    if(waiting && now-submit_ms>=300U){
        if(HAL_FDCAN_IsTxBufferMessagePending(bus,pending_mask))
            (void)HAL_FDCAN_AbortTxRequest(bus,pending_mask);
        ++failed;frame("TX_TIMEOUT");waiting=0;
    }
    if((int32_t)(now-next_tx)>=0){
        next_tx=now+1000U;
        if(!waiting && !(bus->Instance->PSR&FDCAN_PSR_BO) && HAL_FDCAN_GetTxFifoFreeLevel(bus)){
            FDCAN_TxHeaderTypeDef h={0};
            h.Identifier=0x123U;h.IdType=FDCAN_EXTENDED_ID;h.TxFrameType=FDCAN_DATA_FRAME;
            h.DataLength=FDCAN_DLC_BYTES_8;h.ErrorStateIndicator=FDCAN_ESI_ACTIVE;
            h.BitRateSwitch=FDCAN_BRS_OFF;h.FDFormat=FDCAN_CLASSIC_CAN;
            h.TxEventFifoControl=FDCAN_STORE_TX_EVENTS;h.MessageMarker=sequence;
            const uint8_t data[8]={sequence,0x22,0x33,0x44,0x55,0x66,0x77,0x88};
            if(HAL_FDCAN_AddMessageToTxFifoQ(bus,&h,data)==HAL_OK){
                memcpy(pending_data,data,8);pending_mask=HAL_FDCAN_GetLatestTxFifoQRequestBuffer(bus);
                waiting=1;submit_ms=now;++submitted;++sequence;frame("TX_SUBMIT");
            }else{++failed;line("# TX_SUBMIT_FAILED\r\n");}
        }else line("# TX_SKIPPED pending/fifo_full/bus_off; if bus_off reset after receiver is ready\r\n");
    }
    if((int32_t)(now-next_health)>=0){
        next_health=now+1000U;uint32_t psr=bus->Instance->PSR,ecr=bus->Instance->ECR;
        char s[320];(void)snprintf(s,sizeof(s),"# PERIODIC_HEALTH,channel=CAN%u,t_ms=%lu,tx_submit=%lu,tx_done=%lu,tx_failed=%lu,waiting=%lu,lec=%lu,tec=%lu,rec=%lu,bus_off=%lu,nbtp=0x%08lX\r\n",
            (unsigned)PICO_PERIODIC_CHANNEL,(unsigned long)now,(unsigned long)submitted,(unsigned long)completed,(unsigned long)failed,(unsigned long)waiting,
            (unsigned long)(psr&7U),(unsigned long)(ecr&255U),(unsigned long)((ecr>>8)&127U),
            (unsigned long)((psr&FDCAN_PSR_BO)!=0U),(unsigned long)bus->Instance->NBTP);line(s);
    }
}
