#include "pin_loop_test.h"
#include "fdcan.h"
#include <stdio.h>
#include <string.h>

static UART_HandleTypeDef *serial;
static uint32_t next_toggle;
static GPIO_PinState state;

static void line(const char *text) {
    if (serial == NULL) return;
    (void)HAL_UART_Transmit(serial, (const uint8_t *)text, (uint16_t)strlen(text), 100U);
}

static void report(uint32_t now) {
    const GPIO_PinState pa12 = HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_12);
    const GPIO_PinState pa11 = HAL_GPIO_ReadPin(GPIOA, GPIO_PIN_11);
    char text[128];
    (void)snprintf(text, sizeof(text), "%lu,%u,%u,%u,%u\r\n",
        (unsigned long)now, state == GPIO_PIN_SET ? 1U : 0U,
        pa12 == GPIO_PIN_SET ? 1U : 0U, pa11 == GPIO_PIN_SET ? 1U : 0U,
        (pa12 == state && pa11 == state) ? 1U : 0U);
    line(text);
}

void PinLoopTest_Init(UART_HandleTypeDef *uart) {
    serial = uart;
    /* MX_FDCAN1_Init() already ran in the generated startup path. Release
       PA11/PA12 from AF9 and make sure the FDCAN peripheral is not driving. */
    (void)HAL_FDCAN_DeInit(&hfdcan1);
    __HAL_RCC_GPIOA_CLK_ENABLE();

    GPIO_InitTypeDef gpio = {0};
    gpio.Pin = GPIO_PIN_12;
    gpio.Mode = GPIO_MODE_OUTPUT_PP;
    gpio.Pull = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOA, &gpio);

    gpio.Pin = GPIO_PIN_11;
    gpio.Mode = GPIO_MODE_INPUT;
    gpio.Pull = GPIO_PULLDOWN;
    HAL_GPIO_Init(GPIOA, &gpio);

    state = GPIO_PIN_SET;
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_12, state);
    HAL_Delay(1);

    line("# PIN LOOP TEST v1; PA12=OUT(CN10-12), PA11=IN(CN10-14,pull-down); "
         "jumper PA12<->PA11; FDCAN deinit; NO CAN\r\n");
    line("t_ms,pa12_cmd,pa12_read,pa11,match\r\n");
    report(HAL_GetTick());
    next_toggle = HAL_GetTick() + 2000U;
}

void PinLoopTest_Step(void) {
    const uint32_t now = HAL_GetTick();
    if ((int32_t)(now - next_toggle) < 0) return;
    state = state == GPIO_PIN_SET ? GPIO_PIN_RESET : GPIO_PIN_SET;
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_12, state);
    HAL_Delay(1);
    report(now);
    next_toggle = now + 2000U;
}
