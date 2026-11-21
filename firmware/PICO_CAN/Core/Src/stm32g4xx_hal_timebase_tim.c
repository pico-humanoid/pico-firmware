/* Robot14 only: TIM6 owns HAL milliseconds; CMSIS-RTOS2 owns SysTick.
 * Minimal CMSIS-register backend: existing Cube HAL distribution omits TIM.
 * CubeMX metadata selects the same TIM6 timebase. No shared timer users
 * allowed.
 */
#include "main.h"
HAL_StatusTypeDef HAL_InitTick(uint32_t priority) {
  RCC_ClkInitTypeDef clk;
  uint32_t latency;
  HAL_RCC_GetClockConfig(&clk, &latency);
  uint32_t timer = HAL_RCC_GetPCLK1Freq();
  if (clk.APB1CLKDivider != RCC_HCLK_DIV1)
    timer *= 2U;
  if (priority >= (1UL << __NVIC_PRIO_BITS) || timer < 1000000U ||
      timer % 1000000U)
    return HAL_ERROR;
  __HAL_RCC_TIM6_CLK_ENABLE();
  TIM6->CR1 = 0;
  TIM6->DIER = 0;
  TIM6->PSC = timer / 1000000U - 1U;
  TIM6->ARR = 999;
  TIM6->EGR = TIM_EGR_UG;
  TIM6->SR = 0;
  TIM6->CNT = 0;
  uwTickPrio = priority;
  HAL_NVIC_SetPriority(TIM6_DAC_IRQn, priority, 0);
  HAL_NVIC_EnableIRQ(TIM6_DAC_IRQn);
  TIM6->DIER = TIM_DIER_UIE;
  TIM6->CR1 = TIM_CR1_URS | TIM_CR1_CEN;
  return HAL_OK;
}
void HAL_SuspendTick(void) { CLEAR_BIT(TIM6->DIER, TIM_DIER_UIE); }
void HAL_ResumeTick(void) { SET_BIT(TIM6->DIER, TIM_DIER_UIE); }
void TIM6_DAC_IRQHandler(void) {
  if ((TIM6->SR & TIM_SR_UIF) && (TIM6->DIER & TIM_DIER_UIE)) {
    TIM6->SR = ~TIM_SR_UIF;
    HAL_IncTick();
  }
}
