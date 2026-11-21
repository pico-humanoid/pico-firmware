/* Independent receive-only diagnostic. No transmit API calls; hardware MON
 * inhibits ACK/error-frame transmission. Polling removes the IRQ route and
 * host-ID filter from the reception experiment. CAN bit timing is unchanged. */
#include "can3_listen.h"
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
static FDCAN_HandleTypeDef *bus;
static UART_HandleTypeDef *serial;
static bool ready,uart_failed;
static uint32_t received,printed,unsupported,read_failed,lost_observations,next_health;
static uint32_t rx_edge_observations;
static bool edge_latch_test;
static void line(const char *text) {
    if (!uart_failed && HAL_UART_Transmit(serial,(const uint8_t *)text,(uint16_t)strlen(text),100U)!=HAL_OK)
        uart_failed=true;
}
void Can3Listen_Init(FDCAN_HandleTypeDef *can,UART_HandleTypeDef *uart) {
    bus=can;serial=uart;ready=false;uart_failed=false;
    received=printed=unsupported=read_failed=lost_observations=0;
    rx_edge_observations=0;edge_latch_test=false;
    if (!can || !uart || can->Instance!=FDCAN3 || HAL_RCC_GetPCLK1Freq()!=16000000U) return;
    if (HAL_FDCAN_DeInit(can)!=HAL_OK) return;
    can->Init.ClockDivider=FDCAN_CLOCK_DIV1;
    can->Init.FrameFormat=FDCAN_FRAME_CLASSIC;
    can->Init.Mode=FDCAN_MODE_BUS_MONITORING;
    can->Init.AutoRetransmission=DISABLE;
    can->Init.TransmitPause=DISABLE;can->Init.ProtocolException=DISABLE;
    can->Init.NominalPrescaler=1;can->Init.NominalSyncJumpWidth=2;
    can->Init.NominalTimeSeg1=13;can->Init.NominalTimeSeg2=2;
    can->Init.StdFiltersNbr=1;can->Init.ExtFiltersNbr=1;
    can->Init.TxFifoQueueMode=FDCAN_TX_FIFO_OPERATION;
    if (HAL_FDCAN_Init(can)!=HAL_OK) return;
    FDCAN_FilterTypeDef filter={0};
    filter.FilterIndex=0;filter.FilterType=FDCAN_FILTER_MASK;
    filter.FilterConfig=FDCAN_FILTER_TO_RXFIFO0;
    filter.IdType=FDCAN_STANDARD_ID;
    if (HAL_FDCAN_ConfigFilter(can,&filter)!=HAL_OK) return;
    filter.IdType=FDCAN_EXTENDED_ID;
    if (HAL_FDCAN_ConfigFilter(can,&filter)!=HAL_OK ||
        HAL_FDCAN_ConfigGlobalFilter(can,FDCAN_ACCEPT_IN_RX_FIFO0,FDCAN_ACCEPT_IN_RX_FIFO0,
            FDCAN_FILTER_REMOTE,FDCAN_FILTER_REMOTE)!=HAL_OK ||
        HAL_FDCAN_Start(can)!=HAL_OK) return;
    if ((can->Instance->CCCR&FDCAN_CCCR_MON)==0U || (can->Instance->TEST&FDCAN_TEST_LBCK)!=0U) return;
    /* Observe EXTI8 pending in polling only. GPIOA MODER/AFR/PUPDR are left
       untouched, so PA8 remains the AF11 CAN RX input. Enabling the line's
       pending path while masking its NVIC IRQ avoids an interrupt per CAN edge.
       The count is observations of a latch, NOT the number of physical edges. */
    __HAL_RCC_SYSCFG_CLK_ENABLE();
    HAL_NVIC_DisableIRQ(EXTI9_5_IRQn);
    MODIFY_REG(SYSCFG->EXTICR[2],SYSCFG_EXTICR3_EXTI8,SYSCFG_EXTICR3_EXTI8_PA);
    EXTI->EMR1&=~GPIO_PIN_8;
    EXTI->RTSR1|=GPIO_PIN_8;EXTI->FTSR1|=GPIO_PIN_8;
    EXTI->IMR1|=GPIO_PIN_8;EXTI->PR1=GPIO_PIN_8;
    EXTI->SWIER1|=GPIO_PIN_8;
    __DSB();
    edge_latch_test=(EXTI->PR1&GPIO_PIN_8)!=0U;
    EXTI->PR1=GPIO_PIN_8;
    char text[384];
    (void)snprintf(text,sizeof(text),
        "# PICO CAN3 LISTEN v2; channel=FDCAN3 bitrate=1000000 mode=BUS_MONITORING no_tx=1 no_ack=1 all_ids=1 polling=1 cccr=0x%08lX nbtp=0x%08lX\r\n",
        (unsigned long)can->Instance->CCCR,(unsigned long)can->Instance->NBTP);
    line(text);
    (void)snprintf(text,sizeof(text),"# RX_EDGE_LATCH,pin=PA8,nvic_disabled=1,self_test=%u,afrh=0x%08lX,moder=0x%08lX,observations_not_exact_edge_count=1\r\n",
        edge_latch_test?1U:0U,(unsigned long)GPIOA->AFR[1],(unsigned long)GPIOA->MODER);
    line(text);
    line("# Use official USB-CAN software to READ motor parameters; first 40 frames printed; counters continue. No motor commands originate here.\r\n");
    line("t_ms,event,channel,format,kind,id,dlc,data\r\n");
    next_health=HAL_GetTick()+1000U;ready=true;
}
void Can3Listen_Step(void) {
    if (!ready || uart_failed) return;
    if (EXTI->PR1&GPIO_PIN_8) { ++rx_edge_observations;EXTI->PR1=GPIO_PIN_8; }
    for (uint32_t n=0;n<32U && HAL_FDCAN_GetRxFifoFillLevel(bus,FDCAN_RX_FIFO0);++n) {
        FDCAN_RxHeaderTypeDef header={0};uint8_t data[64]={0};
        if (HAL_FDCAN_GetRxMessage(bus,FDCAN_RX_FIFO0,&header,data)!=HAL_OK) { ++read_failed;break; }
        ++received;
        if (header.FDFormat!=FDCAN_CLASSIC_CAN || header.DataLength>8U) { ++unsupported;continue; }
        if (printed<40U) {
            char text[192];
            int used=snprintf(text,sizeof(text),"%lu,RX,FDCAN3,%s,%s,0x%08lX,%lu,",
                (unsigned long)HAL_GetTick(),header.IdType==FDCAN_EXTENDED_ID?"EXT":"STD",
                header.RxFrameType==FDCAN_REMOTE_FRAME?"RTR":"DATA",
                (unsigned long)header.Identifier,(unsigned long)header.DataLength);
            if (header.RxFrameType!=FDCAN_REMOTE_FRAME)
                for (uint32_t i=0;i<header.DataLength;++i)
                    used+=snprintf(text+used,sizeof(text)-(size_t)used,"%s%02X",i?" ":"",data[i]);
            (void)snprintf(text+used,sizeof(text)-(size_t)used,"\r\n");line(text);++printed;
        }
    }
    if (bus->Instance->IR&FDCAN_IR_RF0L) { ++lost_observations;bus->Instance->IR=FDCAN_IR_RF0L; }
    const uint32_t now=HAL_GetTick();
    if ((int32_t)(now-next_health)>=0) {
        const uint32_t psr=bus->Instance->PSR,ecr=bus->Instance->ECR;
        char text[384];
        (void)snprintf(text,sizeof(text),
            "# LISTEN_HEALTH,t_ms=%lu,rx=%lu,printed=%lu,unsupported=%lu,read_failed=%lu,fifo_lost_observations=%lu,psr=0x%08lX,lec=%lu,tec=%lu,rec=%lu,rx_pin=%u,rx_edge_observations=%lu,edge_latch_test=%u\r\n",
            (unsigned long)now,(unsigned long)received,(unsigned long)printed,
            (unsigned long)unsupported,(unsigned long)read_failed,(unsigned long)lost_observations,
            (unsigned long)psr,(unsigned long)(psr&7U),(unsigned long)(ecr&255U),
            (unsigned long)((ecr>>8)&127U),HAL_GPIO_ReadPin(GPIOA,GPIO_PIN_8)==GPIO_PIN_SET?1U:0U,
            (unsigned long)rx_edge_observations,edge_latch_test?1U:0U);
        line(text);next_health=now+1000U;
    }
}
