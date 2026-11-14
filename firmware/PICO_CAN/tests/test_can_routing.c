/* Exercise the production pin initialization and vector handlers, including
   both instances sharing one peripheral clock. No physical CAN is simulated. */
#include "fdcan.h"
#include "stm32g4xx_it.h"
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #x); exit(1); } } while (0)
FDCAN_GlobalTypeDef fake_fdcan1, fake_fdcan3;
static GPIO_InitTypeDef gpio;
static uint32_t deinit_pins, clock_enables;
static bool clock_on, gpio_clock_on, irq_enabled[4];
static FDCAN_HandleTypeDef *last_irq;
void HAL_FDCAN_MspInit(FDCAN_HandleTypeDef *);
void HAL_FDCAN_MspDeInit(FDCAN_HandleTypeDef *);

void Error_Handler(void) { CHECK(false); }
void fake_fdcan_clock_enable(void) { clock_on = true; ++clock_enables; }
void fake_fdcan_clock_disable(void) { clock_on = false; }
void fake_gpioa_clock_enable(void) { gpio_clock_on = true; }
HAL_StatusTypeDef HAL_RCCEx_PeriphCLKConfig(const RCC_PeriphCLKInitTypeDef *config) {
    CHECK(config->PeriphClockSelection == RCC_PERIPHCLK_FDCAN);
    CHECK(config->FdcanClockSelection == RCC_FDCANCLKSOURCE_PCLK1);
    return HAL_OK;
}
HAL_StatusTypeDef HAL_FDCAN_Init(FDCAN_HandleTypeDef *handle) {
    HAL_FDCAN_MspInit(handle);
    return HAL_OK;
}
void HAL_GPIO_Init(void *port, const GPIO_InitTypeDef *config) {
    CHECK(port == GPIOA && clock_on && gpio_clock_on);
    gpio = *config;
}
void HAL_GPIO_DeInit(void *port, uint32_t pins) { CHECK(port == GPIOA); deinit_pins = pins; }
void HAL_NVIC_SetPriority(IRQn_Type irq, uint32_t priority, uint32_t subpriority) {
    CHECK((irq == FDCAN1_IT0_IRQn || irq == FDCAN3_IT0_IRQn) && priority == 1U && subpriority == 0U);
}
void HAL_NVIC_EnableIRQ(IRQn_Type irq) { irq_enabled[irq] = true; }
void HAL_NVIC_DisableIRQ(IRQn_Type irq) { irq_enabled[irq] = false; }
void HAL_FDCAN_IRQHandler(FDCAN_HandleTypeDef *handle) { last_irq = handle; }
void HAL_IncTick(void) { }

int main(void) {
    MX_FDCAN1_Init();
    CHECK(hfdcan1.Instance == FDCAN1 && hfdcan1.Init.Mode == FDCAN_MODE_INTERNAL_LOOPBACK);
    CHECK(gpio.Pin == (GPIO_PIN_11 | GPIO_PIN_12) && gpio.Alternate == GPIO_AF9_FDCAN1);
    CHECK(irq_enabled[FDCAN1_IT0_IRQn]);
    FDCAN1_IT0_IRQHandler();
    CHECK(last_irq == &hfdcan1);

    MX_FDCAN3_Init();
    CHECK(hfdcan3.Instance == FDCAN3 && hfdcan3.Init.Mode == FDCAN_MODE_NORMAL);
    CHECK(gpio.Pin == (GPIO_PIN_8 | GPIO_PIN_15) && gpio.Alternate == GPIO_AF11_FDCAN3);
    CHECK(gpio.Mode == GPIO_MODE_AF_PP && gpio.Pull == GPIO_NOPULL);
    CHECK(hfdcan3.Init.NominalPrescaler == 2U && hfdcan3.Init.NominalTimeSeg1 == 13U && hfdcan3.Init.NominalTimeSeg2 == 2U);
    CHECK(irq_enabled[FDCAN3_IT0_IRQn] && clock_enables == 1U);
    FDCAN3_IT0_IRQHandler();
    CHECK(last_irq == &hfdcan3);

    HAL_FDCAN_MspDeInit(&hfdcan1);
    CHECK(clock_on && !irq_enabled[FDCAN1_IT0_IRQn] && irq_enabled[FDCAN3_IT0_IRQn]);
    HAL_FDCAN_MspDeInit(&hfdcan3);
    CHECK(!clock_on && !irq_enabled[FDCAN3_IT0_IRQn]);
    CHECK(deinit_pins == (GPIO_PIN_8 | GPIO_PIN_15));
    /* Device transport reinitializes its instance after the generated init. */
    MX_FDCAN3_Init();
    CHECK(clock_on && clock_enables == 2U && irq_enabled[FDCAN3_IT0_IRQn]);
    puts("CAN3 pins, clocks and interrupt routing passed; CAN1 bring-up retained");
    return 0;
}
