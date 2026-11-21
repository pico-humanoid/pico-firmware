/* Diagnostic only: TIM6 update -> DMA1 channel 1 -> GPIOA IDR samples.
 * No GPIO alternate-function, CAN clock, CAN timing or motor setting writes. */
#include "can_pin_trace.h"
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#define N 512U
static volatile uint32_t raw[N];
static DMA_HandleTypeDef dma;
static volatile bool done,failed;
static bool initialized,started,captured,dumped;
static uint32_t count,start,end,before,psr,ecr,txbto;
static void complete(DMA_HandleTypeDef *h) {
    (void)h; end=DWT->CYCCNT; TIM6->CR1=0; done=true;
}
static void error(DMA_HandleTypeDef *h) {
    (void)h; end=DWT->CYCCNT; TIM6->CR1=0; failed=true; done=true;
}
void DMA1_Channel1_IRQHandler(void) { HAL_DMA_IRQHandler(&dma); }
void CanPinTrace_Init(void) {
    initialized=started=captured=dumped=done=failed=false;count=0;
    if (HAL_RCC_GetHCLKFreq()!=16000000U || HAL_RCC_GetPCLK1Freq()!=16000000U) return;
    CoreDebug->DEMCR|=CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CTRL|=DWT_CTRL_CYCCNTENA_Msk;
    __HAL_RCC_TIM6_CLK_ENABLE();
    __HAL_RCC_DMAMUX1_CLK_ENABLE();
    __HAL_RCC_DMA1_CLK_ENABLE();
    TIM6->CR1=0; TIM6->DIER=0; TIM6->PSC=0; TIM6->ARR=7;
    TIM6->EGR=TIM_EGR_UG;TIM6->SR=0;TIM6->CNT=0;
    dma.Instance=DMA1_Channel1;
    dma.Init.Request=DMA_REQUEST_TIM6_UP;
    dma.Init.Direction=DMA_PERIPH_TO_MEMORY;
    dma.Init.PeriphInc=DMA_PINC_DISABLE;dma.Init.MemInc=DMA_MINC_ENABLE;
    dma.Init.PeriphDataAlignment=DMA_PDATAALIGN_WORD;
    dma.Init.MemDataAlignment=DMA_MDATAALIGN_WORD;
    dma.Init.Mode=DMA_NORMAL;dma.Init.Priority=DMA_PRIORITY_VERY_HIGH;
    if (HAL_DMA_Init(&dma)!=HAL_OK) return;
    dma.XferCpltCallback=complete;dma.XferErrorCallback=error;
    HAL_NVIC_SetPriority(DMA1_Channel1_IRQn,0,0);
    HAL_NVIC_EnableIRQ(DMA1_Channel1_IRQn);
    initialized=true;
}
void CanPinTrace_Begin(FDCAN_HandleTypeDef *bus) {
    if (started || bus->Instance!=FDCAN3) return;
    started=true;before=GPIOA->IDR;
    if (!initialized) { failed=true;return; }
    if (HAL_DMA_Start_IT(&dma,(uint32_t)&GPIOA->IDR,(uint32_t)raw,N)!=HAL_OK) { failed=true;return; }
    TIM6->CNT=0;TIM6->DIER=TIM_DIER_UDE;
    start=DWT->CYCCNT;TIM6->CR1=TIM_CR1_CEN;
}
void CanPinTrace_Capture(FDCAN_HandleTypeDef *bus) {
    if (captured || !started) return;
    const uint32_t wait=HAL_GetTick();
    while (!done && !failed && (uint32_t)(HAL_GetTick()-wait)<5U) { __NOP(); }
    if (!done) { failed=true;end=DWT->CYCCNT;TIM6->CR1=0; }
    TIM6->DIER=0;
    count=initialized?N-__HAL_DMA_GET_COUNTER(&dma):0;
    if (!done && initialized) (void)HAL_DMA_Abort(&dma);
    psr=bus->Instance->PSR;ecr=bus->Instance->ECR;txbto=bus->Instance->TXBTO;
    captured=true;
}
static bool emit(UART_HandleTypeDef *uart,const char *text) {
    return HAL_UART_Transmit(uart,(const uint8_t *)text,(uint16_t)strlen(text),100U)==HAL_OK;
}
void CanPinTrace_Dump(UART_HandleTypeDef *uart) {
    if (!captured || dumped) return;
    dumped=true;
    uint32_t tx_low=0,rx_low=0,mismatch=0;
    for (uint32_t i=0;i<count;++i) {
        bool tx=(raw[i]&GPIO_PIN_15)!=0U,rx=(raw[i]&GPIO_PIN_8)!=0U;
        tx_low+=!tx;rx_low+=!rx;mismatch+=!tx&&rx;
    }
    char text[512];
    (void)snprintf(text,sizeof(text),
        "# PIN_TRACE,sampler=TIM6_DMA,channel=FDCAN3,hclk=%lu,pclk1=%lu,timer_psc=%lu,timer_arr=%lu,period_cycles=8,nbtp=0x%08lX,ckdiv=0x%08lX,afrh=0x%08lX\r\n",
        (unsigned long)HAL_RCC_GetHCLKFreq(),(unsigned long)HAL_RCC_GetPCLK1Freq(),
        (unsigned long)TIM6->PSC,(unsigned long)TIM6->ARR,(unsigned long)FDCAN3->NBTP,
        (unsigned long)FDCAN_CONFIG->CKDIV,(unsigned long)GPIOA->AFR[1]);
    if (!emit(uart,text)) return;
    (void)snprintf(text,sizeof(text),
        "# PIN_TRACE_RESULT,samples=%lu,nominal_duration_cycles=%lu,completion_irq_cycles=%lu,dma_failed=%u,dma_error=0x%08lX,tx_low_samples=%lu,rx_low_samples=%lu,tx_low_rx_high_samples=%lu,psr=0x%08lX,lec=%lu,ecr=0x%08lX,txbto=0x%08lX,before_idr=0x%08lX\r\n",
        (unsigned long)count,(unsigned long)(count*8U),(unsigned long)(end-start),failed?1U:0U,
        (unsigned long)HAL_DMA_GetError(&dma),(unsigned long)tx_low,(unsigned long)rx_low,
        (unsigned long)mismatch,(unsigned long)psr,(unsigned long)(psr&7U),(unsigned long)ecr,
        (unsigned long)txbto,(unsigned long)before);
    if (!emit(uart,text)) return;
    uint32_t previous=~0UL,emitted=0;
    for (uint32_t i=0;i<count;++i) {
        uint32_t levels=raw[i]&(GPIO_PIN_15|GPIO_PIN_8);
        if (levels==previous && i+1U<count) continue;
        previous=levels;
        if (emitted++>=128U) { (void)emit(uart,"# PIN_TRACE,truncated=1\r\n");break; }
        (void)snprintf(text,sizeof(text),"# PIN_SAMPLE,index=%lu,nominal_cycles=%lu,tx=%u,rx=%u\r\n",
            (unsigned long)i,(unsigned long)((i+1U)*8U),(levels&GPIO_PIN_15)?1U:0U,(levels&GPIO_PIN_8)?1U:0U);
        if (!emit(uart,text)) return;
    }
}
