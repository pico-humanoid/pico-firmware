#include "board_fsm_app.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

USART_TypeDef test_uart;
static uint32_t now;
static char output[4096];
static size_t written;
static bool inject_reset;
static unsigned led;

void HAL_GPIO_WritePin(unsigned port, unsigned pin, unsigned value)
{
    if (port == GPIOA && pin == GPIO_PIN_5) led = value;
}

uint32_t HAL_GetTick(void)
{
    return now;
}

static void receive_byte(uint8_t byte, uint32_t uart_error)
{
    test_uart.ISR = UART_FLAG_RXNE | uart_error;
    test_uart.RDR = byte;
    BoardFsmApp_UartIrq();
}

static void receive_line(const char *str)
{
    while (*str != '\0') receive_byte((uint8_t)*str++, 0);
}

int HAL_UART_Transmit(UART_HandleTypeDef *uart, const uint8_t *bytes, uint16_t len, uint32_t timeout)
{
    (void)uart;
    (void)timeout;
    if (written + len >= sizeof output) return 1;
    char *line = output + written;
    memcpy(line, bytes, len);
    written += len;
    output[written] = '\0';
    if (inject_reset && strstr(line, "state=FAULT_LOCKED")) {
        // RESET arrives on the wire while the trailing ZERO status is still transmitting.
        receive_line("RESET\n");
        inject_reset = false;
    }
    return 0;
}

#define CHECK(expr) do { if (!(expr)) { fprintf(stderr, "Failed at line %d: %s\n%s", __LINE__, #expr, output); return 1; } } while (0)

static unsigned led_at(uint32_t tick)
{
    now = tick;
    BoardFsmApp_Step();
    return led;
}

int main(void)
{
    UART_HandleTypeDef uart = {LPUART1, {115200U, UART_WORDLENGTH_8B, UART_PARITY_NONE,
                                        UART_STOPBITS_1, UART_MODE_TX_RX}};
    BoardFsmApp_Init(&uart);
    CHECK(led_at(299) == GPIO_PIN_RESET); // Self-check.
    CHECK(led_at(300) == GPIO_PIN_SET);
    CHECK(led_at(499) == GPIO_PIN_SET && led_at(500) == GPIO_PIN_RESET);
    CHECK(led_at(700) == GPIO_PIN_RESET && led_at(1499) == GPIO_PIN_RESET);
    CHECK(led_at(1500) == GPIO_PIN_SET); // One flash per group.
    CHECK(strstr(output, "led_scheme=COUNTED"));
    receive_line("MISS2\nDAMP\n");
    BoardFsmApp_Step();
    BoardFsmApp_Step();
    CHECK(led == GPIO_PIN_RESET); // Waiting for a mode change.
    const uint32_t lock = now + 900;
    CHECK(led_at(lock) == GPIO_PIN_RESET);
    CHECK(strstr(output, "fault=MODE_TIMEOUT"));
    CHECK(led_at(lock + 550) == GPIO_PIN_RESET && led_at(lock + 1100) == GPIO_PIN_RESET);

    inject_reset = true;
    receive_line("ZERO\n");
    BoardFsmApp_Step();
    CHECK(!inject_reset);
    BoardFsmApp_Step();
    now += 300;
    BoardFsmApp_Step();
    const char *locked = strstr(output, "command=ZERO,result=FAULT_LOCKED");
    CHECK(locked);
    const char *accepted = strstr(locked, "command=RESET,result=ACCEPTED");
    CHECK(accepted);
    const char *started = strstr(accepted, "state=SELF_CHECK,target=ZERO_TORQUE,pending=1");
    CHECK(started);
    CHECK(strstr(started, "state=ZERO_TORQUE,target=ZERO_TORQUE,pending=0,ack1=1,ack2=1,fault=NONE"));

    // An overrun inside a command must not execute a truncated line.
    size_t before = written;
    receive_line("DA");
    receive_byte('M', UART_FLAG_ORE);
    receive_line("P\n");
    BoardFsmApp_Step();
    CHECK(strstr(output + before, "command=INVALID_LINE,result=DISCARDED"));
    CHECK(!strstr(output + before, "command=DAMP,result=ACCEPTED"));
    receive_line("DAMP\n");
    BoardFsmApp_Step();
    CHECK(strstr(output + before, "command=DAMP,result=ACCEPTED"));
    const uint32_t damping = now + 300;
    CHECK(led_at(damping) == GPIO_PIN_SET);
    CHECK(led_at(damping + 199) == GPIO_PIN_SET && led_at(damping + 200) == GPIO_PIN_RESET);
    CHECK(led_at(damping + 399) == GPIO_PIN_RESET && led_at(damping + 400) == GPIO_PIN_SET);
    CHECK(led_at(damping + 599) == GPIO_PIN_SET && led_at(damping + 600) == GPIO_PIN_RESET);
    CHECK(led_at(damping + 800) == GPIO_PIN_RESET && led_at(damping + 1600) == GPIO_PIN_SET);
    written = 0;
    output[0] = '\0';
    receive_line("DEBUG\n");
    BoardFsmApp_Step();
    CHECK(strstr(output, "command=DEBUG,result=ACCEPTED"));
    CHECK(strstr(output, "state=DAMPING,target=DEBUG_RESERVED,pending=1"));
    CHECK(led == GPIO_PIN_RESET);
    const uint32_t debug = now + 300;
    CHECK(led_at(debug - 1) == GPIO_PIN_RESET && led_at(debug) == GPIO_PIN_SET);
    CHECK(strstr(output, "state=DEBUG_RESERVED,target=DEBUG_RESERVED,pending=0,ack1=1,ack2=1"));
    CHECK(led_at(debug + 199) == GPIO_PIN_SET && led_at(debug + 200) == GPIO_PIN_RESET);
    CHECK(led_at(debug + 400) == GPIO_PIN_SET && led_at(debug + 600) == GPIO_PIN_RESET);
    CHECK(led_at(debug + 800) == GPIO_PIN_SET && led_at(debug + 1000) == GPIO_PIN_RESET);
    CHECK(led_at(debug + 1200) == GPIO_PIN_RESET && led_at(debug + 2000) == GPIO_PIN_SET);
    return 0;
}
