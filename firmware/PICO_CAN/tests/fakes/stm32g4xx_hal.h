#ifndef PICO_TEST_FAKE_HAL_H
#define PICO_TEST_FAKE_HAL_H
#include <stdint.h>
#include <stddef.h>

typedef enum { HAL_OK, HAL_ERROR } HAL_StatusTypeDef;
typedef struct { uint32_t TXEFS, PSR, ECR, TXBRP, TXBTO, TXBCF, IR, CCCR, NBTP; } FDCAN_GlobalTypeDef;
extern FDCAN_GlobalTypeDef fake_fdcan1;
#define FDCAN1 (&fake_fdcan1)
typedef struct {
    uint32_t ClockDivider, FrameFormat, Mode, AutoRetransmission, TransmitPause, ProtocolException;
    uint32_t NominalPrescaler, NominalSyncJumpWidth, NominalTimeSeg1, NominalTimeSeg2;
    uint32_t StdFiltersNbr, ExtFiltersNbr, TxFifoQueueMode;
} FDCAN_InitTypeDef;
typedef struct { FDCAN_GlobalTypeDef *Instance; FDCAN_InitTypeDef Init; } FDCAN_HandleTypeDef;
typedef struct { uint32_t IdType, FilterIndex, FilterType, FilterConfig, FilterID1, FilterID2; } FDCAN_FilterTypeDef;
typedef struct {
    uint32_t Identifier, IdType, TxFrameType, DataLength, ErrorStateIndicator;
    uint32_t BitRateSwitch, FDFormat, TxEventFifoControl, MessageMarker;
} FDCAN_TxHeaderTypeDef;
typedef struct { uint32_t Identifier, IdType, RxFrameType, DataLength, FDFormat; } FDCAN_RxHeaderTypeDef;
typedef struct { uint32_t Identifier, MessageMarker; } FDCAN_TxEventFifoTypeDef;
typedef struct { uint32_t TxErrorCnt, RxErrorCnt; } FDCAN_ErrorCountersTypeDef;
typedef struct { int dummy; } UART_HandleTypeDef;
typedef enum { GPIO_PIN_RESET, GPIO_PIN_SET } GPIO_PinState;
#define GPIOA ((void *)1)
#define GPIO_PIN_5 32U
#define DISABLE 0U
#define FDCAN_CLOCK_DIV1 0U
#define FDCAN_FRAME_CLASSIC 0U
#define FDCAN_MODE_NORMAL 0U
#define FDCAN_TX_FIFO_OPERATION 0U
#define FDCAN_STANDARD_ID 0U
#define FDCAN_EXTENDED_ID 0x40000000U
#define FDCAN_FILTER_RANGE 0U
#define FDCAN_FILTER_MASK 2U
#define FDCAN_FILTER_TO_RXFIFO0 1U
#define FDCAN_REJECT 2U
#define FDCAN_REJECT_REMOTE 1U
#define FDCAN_IT_RX_FIFO0_NEW_MESSAGE 1U
#define FDCAN_IT_RX_FIFO0_MESSAGE_LOST 8U
#define FDCAN_IT_BUS_OFF 0x02000000U
#define FDCAN_IT_TX_EVT_FIFO_ELT_LOST 0x8000U
#define FDCAN_REMOTE_FRAME 0x20000000U
#define FDCAN_DATA_FRAME 0U
#define FDCAN_ESI_ACTIVE 0U
#define FDCAN_BRS_OFF 0U
#define FDCAN_CLASSIC_CAN 0U
#define FDCAN_STORE_TX_EVENTS 0x00800000U
#define FDCAN_RX_FIFO0 0U
#define FDCAN_TXEFS_EFFL 7U
static inline void __DMB(void) { __sync_synchronize(); }
static inline uint32_t __get_PRIMASK(void) { return 0; }
static inline void __disable_irq(void) { }
static inline void __set_PRIMASK(uint32_t irq) { (void)irq; }
uint32_t HAL_GetTick(void);
uint32_t HAL_RCC_GetPCLK1Freq(void);
HAL_StatusTypeDef HAL_FDCAN_DeInit(FDCAN_HandleTypeDef *);
HAL_StatusTypeDef HAL_FDCAN_Init(FDCAN_HandleTypeDef *);
HAL_StatusTypeDef HAL_FDCAN_ConfigFilter(FDCAN_HandleTypeDef *, FDCAN_FilterTypeDef *);
HAL_StatusTypeDef HAL_FDCAN_ConfigGlobalFilter(FDCAN_HandleTypeDef *, uint32_t, uint32_t, uint32_t, uint32_t);
HAL_StatusTypeDef HAL_FDCAN_ActivateNotification(FDCAN_HandleTypeDef *, uint32_t, uint32_t);
HAL_StatusTypeDef HAL_FDCAN_Start(FDCAN_HandleTypeDef *);
uint32_t HAL_FDCAN_GetTxFifoFreeLevel(const FDCAN_HandleTypeDef *);
HAL_StatusTypeDef HAL_FDCAN_AddMessageToTxFifoQ(FDCAN_HandleTypeDef *, const FDCAN_TxHeaderTypeDef *, const uint8_t *);
uint32_t HAL_FDCAN_GetLatestTxFifoQRequestBuffer(const FDCAN_HandleTypeDef *);
HAL_StatusTypeDef HAL_FDCAN_GetTxEvent(FDCAN_HandleTypeDef *, FDCAN_TxEventFifoTypeDef *);
uint32_t HAL_FDCAN_IsTxBufferMessagePending(const FDCAN_HandleTypeDef *, uint32_t);
HAL_StatusTypeDef HAL_FDCAN_AbortTxRequest(FDCAN_HandleTypeDef *, uint32_t);
uint32_t HAL_FDCAN_GetRxFifoFillLevel(const FDCAN_HandleTypeDef *, uint32_t);
HAL_StatusTypeDef HAL_FDCAN_GetRxMessage(FDCAN_HandleTypeDef *, uint32_t, FDCAN_RxHeaderTypeDef *, uint8_t *);
HAL_StatusTypeDef HAL_FDCAN_GetErrorCounters(const FDCAN_HandleTypeDef *, FDCAN_ErrorCountersTypeDef *);
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *, const uint8_t *, uint16_t, uint32_t);
void HAL_GPIO_WritePin(void *, uint16_t, GPIO_PinState);
void HAL_FDCAN_RxFifo0Callback(FDCAN_HandleTypeDef *, uint32_t);
void HAL_FDCAN_ErrorStatusCallback(FDCAN_HandleTypeDef *, uint32_t);
void HAL_FDCAN_TxEventFifoCallback(FDCAN_HandleTypeDef *, uint32_t);
#endif
