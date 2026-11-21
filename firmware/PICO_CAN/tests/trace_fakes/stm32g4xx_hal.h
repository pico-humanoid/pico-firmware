#ifndef TRACE_FAKE_HAL_H
#define TRACE_FAKE_HAL_H
#include <stdint.h>
typedef enum { HAL_OK, HAL_ERROR } HAL_StatusTypeDef;
typedef struct { unsigned unused; } UART_HandleTypeDef;
typedef struct { volatile uint32_t CTRL,CYCCNT; } DWT_Type;
typedef struct { volatile uint32_t DEMCR; } CoreDebug_Type;
typedef struct { volatile uint32_t IDR,AFR[2]; } GPIO_TypeDef;
typedef struct { volatile uint32_t PSR,ECR,TXBTO,TXBRP,NBTP,CCCR,TEST; } FDCAN_GlobalTypeDef;
typedef struct { FDCAN_GlobalTypeDef *Instance; } FDCAN_HandleTypeDef;
typedef struct { volatile uint32_t CKDIV; } FDCAN_Config_TypeDef;
extern DWT_Type fake_dwt;
extern CoreDebug_Type fake_debug;
extern GPIO_TypeDef fake_gpio;
extern FDCAN_GlobalTypeDef fake_bus;
extern FDCAN_Config_TypeDef fake_config;
#define DWT (&fake_dwt)
#define CoreDebug (&fake_debug)
#define GPIOA (&fake_gpio)
#define FDCAN3 (&fake_bus)
#define FDCAN_CONFIG (&fake_config)
#define GPIO_PIN_15 (1U<<15)
#define GPIO_PIN_8 (1U<<8)
#define CoreDebug_DEMCR_TRCENA_Msk (1U<<24)
#define DWT_CTRL_CYCCNTENA_Msk 1U
uint32_t __get_PRIMASK(void);
void __disable_irq(void);
void __set_PRIMASK(uint32_t irq);
uint32_t HAL_RCC_GetHCLKFreq(void);
uint32_t HAL_RCC_GetPCLK1Freq(void);
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *,const uint8_t *,uint16_t,uint32_t);
#endif
