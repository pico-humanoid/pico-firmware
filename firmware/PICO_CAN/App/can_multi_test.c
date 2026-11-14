/* Independent three-controller bench. All RX is polled; no motor protocol.
 * A channel transmits only in response to its own valid bench request.
 * Shared clock and divider are configured before starting any controller. */
#include "can_multi_test.h"
#include "fdcan.h"
#include <stdio.h>
#include <string.h>

#define COUNT 100U
typedef struct {
    FDCAN_HandleTypeDef *can;
    GPIO_TypeDef *rx_port;
    uint16_t rx_pin;
    uint32_t rx_id,tx_id,ready,started,finished,start_ms;
    uint32_t rx_unique,rx_duplicate,rx_invalid,rx_other,rx_failed,rx_lost;
    uint32_t tx_submit,tx_done,tx_failed,tx_lost,tx_aborted,bus_off,edges,edge_test;
    uint8_t seen[COUNT],done[COUNT];
} Channel;
static FDCAN_HandleTypeDef can2;
static Channel channels[3];
static UART_HandleTypeDef *serial;
static uint32_t next_health,uart_failed;
static void line(const char *s) {
    if (HAL_UART_Transmit(serial,(const uint8_t *)s,(uint16_t)strlen(s),100U)!=HAL_OK) uart_failed=1;
}
static void frame_log(uint32_t i,const char *event,uint32_t id,const uint8_t data[8]) {
    char text[180];
    (void)snprintf(text,sizeof(text),"%lu,%s,CAN%lu,EXT,0x%08lX,8,%02X %02X %02X %02X %02X %02X %02X %02X\r\n",
        (unsigned long)HAL_GetTick(),event,(unsigned long)(i+1U),(unsigned long)id,
        data[0],data[1],data[2],data[3],data[4],data[5],data[6],data[7]);line(text);
}
static void edge_init(void) {
    __HAL_RCC_SYSCFG_CLK_ENABLE();
    HAL_NVIC_DisableIRQ(EXTI9_5_IRQn);HAL_NVIC_DisableIRQ(EXTI15_10_IRQn);
    MODIFY_REG(SYSCFG->EXTICR[2],SYSCFG_EXTICR3_EXTI8|SYSCFG_EXTICR3_EXTI11,
               SYSCFG_EXTICR3_EXTI8_PA|SYSCFG_EXTICR3_EXTI11_PA);
    MODIFY_REG(SYSCFG->EXTICR[3],SYSCFG_EXTICR4_EXTI12,SYSCFG_EXTICR4_EXTI12_PB);
    const uint32_t mask=GPIO_PIN_8|GPIO_PIN_11|GPIO_PIN_12;
    EXTI->EMR1&=~mask;EXTI->RTSR1|=mask;EXTI->FTSR1|=mask;
    EXTI->IMR1|=mask;EXTI->PR1=mask;
    for(uint32_t i=0;i<3U;++i) {
        EXTI->SWIER1|=channels[i].rx_pin;__DSB();
        channels[i].edge_test=(EXTI->PR1&channels[i].rx_pin)!=0U;
        EXTI->PR1=channels[i].rx_pin;
    }
}
void CanMultiTest_Init(UART_HandleTypeDef *uart) {
    serial=uart;
    line("# CAN_MULTI_TEST=1; version=1; CAN1 CAN2 CAN3 simultaneous; normal classic EXT; polling=1; bitrate=1000000; no motor\r\n");
    if(HAL_RCC_GetPCLK1Freq()!=16000000U) {line("# MULTI_INIT_ERROR clock\r\n");return;}
    channels[0]=(Channel){.can=&hfdcan1,.rx_port=GPIOA,.rx_pin=GPIO_PIN_11,.rx_id=0x321U,.tx_id=0x121U};
    channels[1]=(Channel){.can=&can2,.rx_port=GPIOB,.rx_pin=GPIO_PIN_12,.rx_id=0x322U,.tx_id=0x122U};
    channels[2]=(Channel){.can=&hfdcan3,.rx_port=GPIOA,.rx_pin=GPIO_PIN_8,.rx_id=0x323U,.tx_id=0x123U};
    FDCAN_GlobalTypeDef *instances[3]={FDCAN1,FDCAN2,FDCAN3};
    for(uint32_t i=0;i<3U;++i) {
        FDCAN_HandleTypeDef *can=channels[i].can;
        can->Instance=instances[i];
        can->Init.ClockDivider=FDCAN_CLOCK_DIV1;can->Init.FrameFormat=FDCAN_FRAME_CLASSIC;
        can->Init.Mode=FDCAN_MODE_NORMAL;can->Init.AutoRetransmission=DISABLE;
        can->Init.TransmitPause=DISABLE;can->Init.ProtocolException=DISABLE;
        can->Init.NominalPrescaler=1;can->Init.NominalSyncJumpWidth=2;
        can->Init.NominalTimeSeg1=13;can->Init.NominalTimeSeg2=2;
        can->Init.DataPrescaler=1;can->Init.DataSyncJumpWidth=1;can->Init.DataTimeSeg1=1;can->Init.DataTimeSeg2=1;
        can->Init.StdFiltersNbr=1;can->Init.ExtFiltersNbr=1;can->Init.TxFifoQueueMode=FDCAN_TX_FIFO_OPERATION;
        if(HAL_FDCAN_Init(can)!=HAL_OK) {line("# MULTI_INIT_ERROR HAL_Init\r\n");return;}
    }
    HAL_NVIC_DisableIRQ(FDCAN1_IT0_IRQn);HAL_NVIC_DisableIRQ(FDCAN2_IT0_IRQn);HAL_NVIC_DisableIRQ(FDCAN3_IT0_IRQn);
    for(uint32_t i=0;i<3U;++i) {
        Channel *c=&channels[i];FDCAN_FilterTypeDef f={0};
        f.FilterType=FDCAN_FILTER_MASK;f.FilterConfig=FDCAN_FILTER_TO_RXFIFO0;
        f.IdType=FDCAN_STANDARD_ID;
        HAL_StatusTypeDef ok=HAL_FDCAN_ConfigFilter(c->can,&f);
        f.IdType=FDCAN_EXTENDED_ID;
        if(ok!=HAL_OK || HAL_FDCAN_ConfigFilter(c->can,&f)!=HAL_OK ||
           HAL_FDCAN_ConfigGlobalFilter(c->can,FDCAN_ACCEPT_IN_RX_FIFO0,FDCAN_ACCEPT_IN_RX_FIFO0,
                                       FDCAN_REJECT_REMOTE,FDCAN_REJECT_REMOTE)!=HAL_OK ||
           HAL_FDCAN_Start(c->can)!=HAL_OK) {line("# MULTI_INIT_ERROR filter/start\r\n");return;}
        c->ready=1;
    }
    edge_init();next_health=HAL_GetTick()+1000U;
    line("# MULTI_READY=1; CAN1 TX=PA12 RX=PA11 PC=0x321 BOARD=0x121; CAN2 TX=PB13 RX=PB12 PC=0x322 BOARD=0x122; CAN3 TX=PA15 RX=PA8 PC=0x323 BOARD=0x123\r\n");
    line("t_ms,event,channel,format,id,dlc,data\r\n");
}
static void poll_channel(uint32_t i) {
    Channel *c=&channels[i];if(!c->ready)return;
    if(EXTI->PR1&c->rx_pin){++c->edges;EXTI->PR1=c->rx_pin;}
    FDCAN_HandleTypeDef *can=c->can;
    if(can->Instance->IR&FDCAN_IR_RF0L){++c->rx_lost;can->Instance->IR=FDCAN_IR_RF0L;}
    if(can->Instance->IR&FDCAN_IR_TEFL){++c->tx_lost;can->Instance->IR=FDCAN_IR_TEFL;}
    if(can->Instance->IR&FDCAN_IR_BO){++c->bus_off;can->Instance->IR=FDCAN_IR_BO;}
    for(uint32_t n=0;n<3U && HAL_FDCAN_GetRxFifoFillLevel(can,FDCAN_RX_FIFO0);++n) {
        FDCAN_RxHeaderTypeDef h={0};uint8_t data[64]={0};
        if(HAL_FDCAN_GetRxMessage(can,FDCAN_RX_FIFO0,&h,data)!=HAL_OK){++c->rx_failed;break;}
        if(h.IdType!=FDCAN_EXTENDED_ID || h.Identifier!=c->rx_id) {
            if(++c->rx_other<=5U){char s[150];(void)snprintf(s,sizeof(s),"# MULTI_OTHER channel=CAN%lu format=%s id=0x%08lX expected=0x%03lX\r\n",
                (unsigned long)(i+1U),h.IdType==FDCAN_EXTENDED_ID?"EXT":"STD",(unsigned long)h.Identifier,(unsigned long)c->rx_id);line(s);}continue;
        }
        const uint8_t tail[7]={0x88,0x77,0x66,0x55,0x44,0x33,0x22};
        if(h.RxFrameType!=FDCAN_DATA_FRAME || h.FDFormat!=FDCAN_CLASSIC_CAN || h.DataLength!=FDCAN_DLC_BYTES_8 ||
           data[0]>=COUNT || memcmp(data+1,tail,7)!=0){++c->rx_invalid;continue;}
        if(c->finished)continue;
        if(!c->started){c->started=1;c->start_ms=HAL_GetTick();}
        if(c->seen[data[0]]){++c->rx_duplicate;continue;}
        c->seen[data[0]]=1;++c->rx_unique;frame_log(i,"RX",c->rx_id,data);
        FDCAN_TxHeaderTypeDef tx={0};
        tx.Identifier=c->tx_id;tx.IdType=FDCAN_EXTENDED_ID;tx.TxFrameType=FDCAN_DATA_FRAME;
        tx.DataLength=FDCAN_DLC_BYTES_8;tx.ErrorStateIndicator=FDCAN_ESI_ACTIVE;
        tx.BitRateSwitch=FDCAN_BRS_OFF;tx.FDFormat=FDCAN_CLASSIC_CAN;
        tx.TxEventFifoControl=FDCAN_STORE_TX_EVENTS;tx.MessageMarker=data[0];
        uint8_t reply[8]={data[0],0x22,0x33,0x44,0x55,0x66,0x77,0x88};
        if(HAL_FDCAN_GetTxFifoFreeLevel(can) && HAL_FDCAN_AddMessageToTxFifoQ(can,&tx,reply)==HAL_OK)++c->tx_submit;
        else ++c->tx_failed;
    }
    while(can->Instance->TXEFS&FDCAN_TXEFS_EFFL){
        FDCAN_TxEventFifoTypeDef e={0};
        if(HAL_FDCAN_GetTxEvent(can,&e)!=HAL_OK){++c->tx_failed;break;}
        if(e.Identifier!=c->tx_id || e.MessageMarker>=COUNT || c->done[e.MessageMarker]){++c->tx_failed;continue;}
        c->done[e.MessageMarker]=1;++c->tx_done;
        uint8_t reply[8]={(uint8_t)e.MessageMarker,0x22,0x33,0x44,0x55,0x66,0x77,0x88};frame_log(i,"TX_DONE",c->tx_id,reply);
    }
    if(c->started && !c->finished && HAL_GetTick()-c->start_ms>=13000U){
        uint32_t ecr=can->Instance->ECR;
        uint32_t pass=c->rx_unique==COUNT && c->tx_submit==COUNT && c->tx_done==COUNT &&
            !(c->rx_duplicate||c->rx_invalid||c->rx_other||c->rx_failed||c->rx_lost||c->tx_failed||c->tx_lost||c->bus_off||uart_failed) &&
            (ecr&0x7FFFU)==0U && !(can->Instance->PSR&FDCAN_PSR_BO);
        char text[320];(void)snprintf(text,sizeof(text),"# MULTI_RESULT channel=CAN%lu result=%s rx_unique=%lu tx_submit=%lu tx_done=%lu rx_duplicate=%lu rx_invalid=%lu rx_other=%lu tx_failed=%lu bus_off=%lu tec=%lu rec=%lu\r\n",
            (unsigned long)(i+1U),pass?"PASS":"FAIL",(unsigned long)c->rx_unique,(unsigned long)c->tx_submit,(unsigned long)c->tx_done,
            (unsigned long)c->rx_duplicate,(unsigned long)c->rx_invalid,(unsigned long)c->rx_other,(unsigned long)c->tx_failed,
            (unsigned long)c->bus_off,(unsigned long)(ecr&255U),(unsigned long)((ecr>>8)&127U));line(text);c->finished=1;
    }
}
void CanMultiTest_Step(void){
    for(uint32_t i=0;i<3U;++i)poll_channel(i);
    uint32_t now=HAL_GetTick();if((int32_t)(now-next_health)<0)return;next_health=now+1000U;
    for(uint32_t i=0;i<3U;++i){
        Channel *c=&channels[i];if(!c->ready)continue;
        uint32_t psr=c->can->Instance->PSR,ecr=c->can->Instance->ECR;
        char s[400];(void)snprintf(s,sizeof(s),"# MULTI_HEALTH,channel=CAN%lu,t_ms=%lu,state=%s,rx_unique=%lu,tx_submit=%lu,tx_done=%lu,rx_other=%lu,rx_edge_observations=%lu,edge_latch_test=%lu,rx_pin=%u,lec=%lu,tec=%lu,rec=%lu,nbtp=0x%08lX\r\n",
            (unsigned long)(i+1U),(unsigned long)now,c->finished?"FINISHED":c->started?"ACTIVE":"WAIT",
            (unsigned long)c->rx_unique,(unsigned long)c->tx_submit,(unsigned long)c->tx_done,(unsigned long)c->rx_other,
            (unsigned long)c->edges,(unsigned long)c->edge_test,HAL_GPIO_ReadPin(c->rx_port,c->rx_pin)==GPIO_PIN_SET?1U:0U,
            (unsigned long)(psr&7U),(unsigned long)(ecr&255U),(unsigned long)((ecr>>8)&127U),(unsigned long)c->can->Instance->NBTP);line(s);
    }
}
