#include "can_pin_trace.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); exit(1); } } while(0)
DWT_Type fake_dwt;
CoreDebug_Type fake_debug;
GPIO_TypeDef fake_gpio;
FDCAN_GlobalTypeDef fake_bus;
FDCAN_Config_TypeDef fake_config;
static uint32_t irq=1;
static char output[8000];
static size_t used;
uint32_t __get_PRIMASK(void) { return irq; }
void __disable_irq(void) { irq=1; }
void __set_PRIMASK(uint32_t value) { irq=value; }
uint32_t HAL_RCC_GetHCLKFreq(void) { return 16000000; }
uint32_t HAL_RCC_GetPCLK1Freq(void) { return 16000000; }
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *h,const uint8_t *data,uint16_t n,uint32_t timeout) {
    (void)h; (void)timeout;
    CHECK(used+n<sizeof(output)); memcpy(output+used,data,n);used+=n;output[used]=0;return HAL_OK;
}
int main(void) {
    FDCAN_HandleTypeDef bus={FDCAN3}; UART_HandleTypeDef uart={0};
    fake_gpio.IDR=GPIO_PIN_15|GPIO_PIN_8;fake_gpio.AFR[1]=0xB000000B;
    fake_bus.NBTP=0x02000C01;fake_bus.CCCR=0x1040;
    CanPinTrace_Init();CanPinTrace_Dump(&uart);CHECK(!used);
    CanPinTrace_Begin(&bus);CanPinTrace_Capture(&bus);CHECK(irq==1);
    CanPinTrace_Dump(&uart);
    CHECK(strstr(output,"samples=1024,duration_cycles=0")); /* stopped DWT is finite, explicitly visible */
    CHECK(strstr(output,"tx_low_samples=0,rx_low_samples=0,tx_low_rx_high_samples=0"));
    CHECK(strstr(output,"nbtp=0x02000C01"));
    size_t prior=used;
    fake_gpio.IDR=GPIO_PIN_8;CanPinTrace_Capture(&bus);CanPinTrace_Dump(&uart);CHECK(used==prior);
    used=0;output[0]=0;irq=0;
    CanPinTrace_Init();CanPinTrace_Begin(&bus);fake_bus.PSR=5;fake_bus.ECR=8;
    CanPinTrace_Capture(&bus);CHECK(irq==0);
    fake_bus.PSR=7; /* preserve earlier hardware error across subsequent PSR reads */
    CanPinTrace_Dump(&uart);
    CHECK(strstr(output,"tx_low_samples=1024,rx_low_samples=0,tx_low_rx_high_samples=1024"));
    CHECK(strstr(output,"psr=0x00000005,lec=5,ecr=0x00000008"));
    CHECK(fake_bus.NBTP==0x02000C01 && fake_bus.CCCR==0x1040 && fake_gpio.AFR[1]==0xB000000B);
    puts("PASS: trace one-shot, stopped-counter bound, pin levels, first PSR preservation, IRQ restoration and unchanged CAN/GPIO configuration");
    return 0;
}
