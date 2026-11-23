#ifndef BOARD_FSM_FAKE_HAL_H
#define BOARD_FSM_FAKE_HAL_H

#include <stdint.h>

typedef struct { uint32_t ISR, RDR; } USART_TypeDef;
extern USART_TypeDef test_uart;
typedef struct {
    USART_TypeDef *Instance;
    struct { uint32_t BaudRate, WordLength, Parity, StopBits, Mode; } Init;
} UART_HandleTypeDef;

#define LPUART1 (&test_uart)
#define LPUART1_IRQn 1
#define UART_WORDLENGTH_8B 8U
#define UART_PARITY_NONE 0U
#define UART_STOPBITS_1 1U
#define UART_MODE_TX_RX 3U
#define UART_FLAG_ORE 8U
#define UART_FLAG_FE 2U
#define UART_FLAG_NE 4U
#define UART_FLAG_RXNE 32U
#define UART_CLEAR_OREF UART_FLAG_ORE
#define UART_CLEAR_FEF UART_FLAG_FE
#define UART_CLEAR_NEF UART_FLAG_NE
#define UART_IT_ERR 1U
#define UART_IT_RXNE 2U
#define UART_RXDATA_FLUSH_REQUEST 1U
#define __HAL_UART_CLEAR_FLAG(uart, flags) ((uart)->Instance->ISR &= ~(flags))
#define __HAL_UART_SEND_REQ(uart, req) ((void)(uart), (void)(req))
#define __HAL_UART_ENABLE_IT(uart, irq) ((void)(uart), (void)(irq))
#define HAL_NVIC_SetPriority(irq, priority, sub) ((void)(irq), (void)(priority), (void)(sub))
#define HAL_NVIC_EnableIRQ(irq) ((void)(irq))
#define __get_PRIMASK() 0U
#define __disable_irq() ((void)0)
#define __set_PRIMASK(mask) ((void)(mask))
#define GPIOA 1U
#define GPIO_PIN_5 32U
#define GPIO_PIN_SET 1U
#define GPIO_PIN_RESET 0U
void HAL_GPIO_WritePin(unsigned port, unsigned pin, unsigned value);

uint32_t HAL_GetTick(void);
int HAL_UART_Transmit(UART_HandleTypeDef *uart, const uint8_t *bytes, uint16_t len, uint32_t timeout);

#endif
