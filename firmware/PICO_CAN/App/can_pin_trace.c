/* Diagnostic only: observe the first real read request, never drive GPIO or
 * modify CAN timing/mode. DWT timestamps describe MCU GPIO observations, not
 * an oscilloscope measurement of CANH/CANL or transceiver pins. */
#include "can_pin_trace.h"
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#define SAMPLE_COUNT 1024U
typedef struct { uint32_t cycles, idr; } PinSample;
static PinSample samples[SAMPLE_COUNT];
static uint32_t count, before_idr, psr, ecr, txbto, txbrp;
static bool started, captured, dumped;

void CanPinTrace_Init(void) {
    started=captured=dumped=false; count=0;
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}
void CanPinTrace_Begin(FDCAN_HandleTypeDef *bus) {
    if (started || bus->Instance != FDCAN3) return;
    before_idr=GPIOA->IDR;
}
#if defined(__arm__) || defined(__thumb__)
__attribute__((section(".RamFunc"), noinline, optimize("O2")))
#else
__attribute__((optimize("O2")))
#endif
void CanPinTrace_Capture(FDCAN_HandleTypeDef *bus) {
    if (started || bus->Instance != FDCAN3) return;
    started=true;
    uint32_t irq=__get_PRIMASK();
    __disable_irq();
    const uint32_t start=DWT->CYCCNT;
    /* Fixed count bounds execution even with a stopped DWT. The ARM hot loop
       runs from SRAM and stores absolute timestamps to avoid per-sample C
       bookkeeping. Duration/gaps are measured, not assumed to be uniform.
       Hardware CAN continues; ISR service is deferred during the sample burst. */
#if defined(__arm__) || defined(__thumb__)
    uint32_t *cursor=(uint32_t *)samples;
    uint32_t remaining=SAMPLE_COUNT;
    __asm volatile (
        "1:\n"
        "ldr r2, [%[counter]]\n"
        "ldr r3, [%[gpio]]\n"
        "stmia %[cursor]!, {r2, r3}\n"
        "subs %[remaining], %[remaining], #1\n"
        "bne 1b\n"
        : [cursor] "+&r" (cursor), [remaining] "+&r" (remaining)
        : [counter] "r" (&DWT->CYCCNT), [gpio] "r" (&GPIOA->IDR)
        : "r2", "r3", "cc", "memory");
    count=SAMPLE_COUNT;
#else
    for (count=0; count<SAMPLE_COUNT; ++count) {
        samples[count]=(PinSample){DWT->CYCCNT,GPIOA->IDR};
    }
#endif
    /* PSR reads clear sticky LEC. Preserve this earlier observation explicitly. */
    psr=bus->Instance->PSR; ecr=bus->Instance->ECR;
    txbto=bus->Instance->TXBTO; txbrp=bus->Instance->TXBRP;
    __set_PRIMASK(irq);
    for (uint32_t i=0;i<count;++i) samples[i].cycles-=start;
    captured=true;
}
static bool emit(UART_HandleTypeDef *uart,const char *text) {
    return HAL_UART_Transmit(uart,(const uint8_t *)text,(uint16_t)strlen(text),100U)==HAL_OK;
}
void CanPinTrace_Dump(UART_HandleTypeDef *uart) {
    if (!captured || dumped) return;
    dumped=true;
    uint32_t tx_low=0, rx_low=0, mismatch=0, max_gap=0;
    for (uint32_t i=0;i<count;++i) {
        bool tx=(samples[i].idr&GPIO_PIN_15)!=0U;
        bool rx=(samples[i].idr&GPIO_PIN_8)!=0U;
        tx_low+=!tx; rx_low+=!rx; mismatch+=!tx && rx;
        if (i && samples[i].cycles-samples[i-1].cycles>max_gap)
            max_gap=samples[i].cycles-samples[i-1].cycles;
    }
    char text[512];
    (void)snprintf(text,sizeof(text),
        "# PIN_TRACE,sampler=RAM_TIGHT,channel=FDCAN3,hclk=%lu,pclk1=%lu,nbtp=0x%08lX,ckdiv=0x%08lX,afrh=0x%08lX,cccr=0x%08lX,test=0x%08lX\r\n",
        (unsigned long)HAL_RCC_GetHCLKFreq(),(unsigned long)HAL_RCC_GetPCLK1Freq(),
        (unsigned long)FDCAN3->NBTP,(unsigned long)FDCAN_CONFIG->CKDIV,
        (unsigned long)GPIOA->AFR[1],(unsigned long)FDCAN3->CCCR,(unsigned long)FDCAN3->TEST);
    if (!emit(uart,text)) return;
    (void)snprintf(text,sizeof(text),
        "# PIN_TRACE_RESULT,samples=%lu,duration_cycles=%lu,max_gap_cycles=%lu,tx_low_samples=%lu,rx_low_samples=%lu,tx_low_rx_high_samples=%lu,psr=0x%08lX,lec=%lu,ecr=0x%08lX,txbto=0x%08lX,txbrp=0x%08lX,before_idr=0x%08lX\r\n",
        (unsigned long)count,(unsigned long)samples[count-1U].cycles,(unsigned long)max_gap,
        (unsigned long)tx_low,(unsigned long)rx_low,(unsigned long)mismatch,
        (unsigned long)psr,(unsigned long)(psr&7U),(unsigned long)ecr,
        (unsigned long)txbto,(unsigned long)txbrp,(unsigned long)before_idr);
    if (!emit(uart,text)) return;
    uint32_t previous=~0UL, emitted=0;
    for (uint32_t i=0;i<count;++i) {
        uint32_t levels=samples[i].idr&(GPIO_PIN_15|GPIO_PIN_8);
        if (levels==previous && i+1U<count) continue;
        previous=levels;
        if (emitted++>=128U) { (void)emit(uart,"# PIN_TRACE,truncated=1; raw buffer available in debugger; no full-waveform claim\r\n"); break; }
        (void)snprintf(text,sizeof(text),"# PIN_SAMPLE,cycles=%lu,tx=%u,rx=%u\r\n",
            (unsigned long)samples[i].cycles,(levels&GPIO_PIN_15)?1U:0U,(levels&GPIO_PIN_8)?1U:0U);
        if (!emit(uart,text)) return;
    }
}
