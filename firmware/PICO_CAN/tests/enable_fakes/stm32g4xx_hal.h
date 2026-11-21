#ifndef ENABLE_FAKE_HAL_H
#define ENABLE_FAKE_HAL_H
#include <stdint.h>
#include <stdbool.h>
typedef struct {uint32_t TXBRP,TXBTO,TXBCF,PSR;} FDCAN_GlobalTypeDef;
typedef struct {FDCAN_GlobalTypeDef *Instance;} FDCAN_HandleTypeDef;
typedef struct {uint32_t ErrorCode;} UART_HandleTypeDef;
typedef struct {uint32_t TxErrorCnt,RxErrorCnt;} FDCAN_ErrorCountersTypeDef;
typedef enum {HAL_OK,HAL_ERROR} HAL_StatusTypeDef;
#define LPUART1_IRQn 0
#define UART_CLEAR_OREF 1U
#define UART_CLEAR_FEF 2U
#define UART_CLEAR_NEF 4U
#define UART_CLEAR_PEF 8U
#define UART_RXDATA_FLUSH_REQUEST 1U
#define __DMB() ((void)0)
#define __disable_irq() ((void)0)
#define __set_PRIMASK(x) ((void)(x))
#define __get_PRIMASK() 0U
#define __HAL_UART_CLEAR_FLAG(h,f) ((void)(h),(void)(f))
#define __HAL_UART_SEND_REQ(h,f) ((void)(h),(void)(f))
uint32_t HAL_GetTick(void);
void HAL_NVIC_SetPriority(int irq,int priority,int sub);
void HAL_NVIC_EnableIRQ(int irq);
HAL_StatusTypeDef HAL_UART_Receive_IT(UART_HandleTypeDef *h,uint8_t *p,uint16_t n);
HAL_StatusTypeDef HAL_UART_Transmit_IT(UART_HandleTypeDef *h,const uint8_t *p,uint16_t n);
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *h,const uint8_t *p,uint16_t n,uint32_t timeout);
HAL_StatusTypeDef HAL_FDCAN_AbortTxRequest(FDCAN_HandleTypeDef *h,uint32_t mask);
HAL_StatusTypeDef HAL_FDCAN_GetErrorCounters(const FDCAN_HandleTypeDef *h,FDCAN_ErrorCountersTypeDef *e);
#endif
