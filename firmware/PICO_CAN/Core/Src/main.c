/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "fdcan.h"
#include "usart.h"
#include "gpio.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#if defined(PICO_ROBOT14)
#include "cmsis_os2.h"
#include "freertos.h"
#elif defined(PICO_MOTOR_ENABLE)
#include "motor_enable_app.h"
#elif defined(PICO_CAN_PERIODIC_TX)
#include "can_periodic_tx.h"
#elif defined(PICO_CAN_MULTI_TEST)
#include "can_multi_test.h"
#elif defined(PICO_PIN_LOOP_TEST)
#include "pin_loop_test.h"
#elif defined(PICO_CAN_LISTEN)
#include "can3_listen.h"
#elif defined(PICO_MOTOR_READ)
#include "motor_read_app.h"
#elif defined(PICO_DEVICE_READ)
#include "device_read_app.h"
#else
#include "can_bringup.h"
#endif

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#ifndef PICO_CAN_CHANNEL
#define PICO_CAN_CHANNEL 1
#endif

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_LPUART1_UART_Init();
#if defined(PICO_ROBOT14)
  MX_FDCAN1_Init();
  MX_FDCAN2_Init();
  MX_FDCAN3_Init();
#elif defined(PICO_CAN_PERIODIC_TX)
  /* The periodic app configures only the selected CAN instance. */
#elif defined(PICO_CAN_MULTI_TEST)
  /* The diagnostic initializes all three instances before starting any bus. */
#elif defined(PICO_MOTOR_ENABLE) || (defined(PICO_MOTOR_READ) && PICO_MOTOR_CAN_CHANNEL == 1)
  MX_FDCAN1_Init();
#elif defined(PICO_DEVICE_READ)
#if PICO_CAN_CHANNEL == 1
  MX_FDCAN1_Init();
#elif PICO_CAN_CHANNEL == 2
  MX_FDCAN2_Init();
#elif PICO_CAN_CHANNEL == 3
  MX_FDCAN3_Init();
#else
#error "PICO_CAN_CHANNEL must be 1, 2, or 3"
#endif
#elif defined(PICO_MOTOR_READ) || defined(PICO_CAN_LISTEN) || defined(PICO_CAN3_PC_TEST)
  MX_FDCAN3_Init();
#else
  MX_FDCAN1_Init();
#endif
  /* USER CODE BEGIN 2 */
#if defined(PICO_ROBOT14)
  if (osKernelInitialize() != osOK) Error_Handler();
  MX_FREERTOS_Init();
  if (osKernelStart() != osOK) Error_Handler();
  Error_Handler();
#elif defined(PICO_MOTOR_ENABLE)
  MotorEnableApp_Init(&hfdcan1,&hlpuart1);
#elif defined(PICO_CAN_PERIODIC_TX)
#if PICO_PERIODIC_CHANNEL == 1
  hfdcan1.Instance=FDCAN1;
  CanPeriodicTx_Init(&hfdcan1, &hlpuart1);
#elif PICO_PERIODIC_CHANNEL == 2
  hfdcan2.Instance=FDCAN2;
  CanPeriodicTx_Init(&hfdcan2, &hlpuart1);
#elif PICO_PERIODIC_CHANNEL == 3
  hfdcan3.Instance=FDCAN3;
  CanPeriodicTx_Init(&hfdcan3, &hlpuart1);
#else
#error Invalid periodic CAN channel
#endif
#elif defined(PICO_CAN_MULTI_TEST)
  CanMultiTest_Init(&hlpuart1);
#elif defined(PICO_PIN_LOOP_TEST)
  PinLoopTest_Init(&hlpuart1);
#elif defined(PICO_CAN_LISTEN)
  Can3Listen_Init(&hfdcan3, &hlpuart1);
#elif defined(PICO_CAN3_PC_TEST)
  CanTest_Init(&hfdcan3, &hlpuart1);
#elif defined(PICO_MOTOR_READ)
#if PICO_MOTOR_CAN_CHANNEL == 1
  MotorRead_Init(&hfdcan1, &hlpuart1);
#else
  MotorRead_Init(&hfdcan3, &hlpuart1);
#endif
#elif defined(PICO_DEVICE_READ)
#if PICO_CAN_CHANNEL == 1
  DeviceRead_Init(&hfdcan1, &hlpuart1);
#elif PICO_CAN_CHANNEL == 2
  DeviceRead_Init(&hfdcan2, &hlpuart1);
#elif PICO_CAN_CHANNEL == 3
  DeviceRead_Init(&hfdcan3, &hlpuart1);
#endif
#else
  CanTest_Init(&hfdcan1, &hlpuart1);
#endif

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
#if defined(PICO_ROBOT14)
    Error_Handler();
#elif defined(PICO_MOTOR_ENABLE)
    MotorEnableApp_Step();
#elif defined(PICO_CAN_PERIODIC_TX)
    CanPeriodicTx_Step();
#elif defined(PICO_CAN_MULTI_TEST)
    CanMultiTest_Step();
#elif defined(PICO_PIN_LOOP_TEST)
    PinLoopTest_Step();
#elif defined(PICO_CAN_LISTEN)
    Can3Listen_Step();
#elif defined(PICO_MOTOR_READ)
    MotorRead_Step();
#elif defined(PICO_DEVICE_READ)
    DeviceRead_Step();
#else
    CanTest_Step();
#endif
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
#if defined(PICO_ROBOT14)
  /* HSI16 / 4 * 80 / 2 = 160 MHz. APB1 / 2 = FDCAN kernel 80 MHz. */
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = RCC_PLLM_DIV4;
  RCC_OscInitStruct.PLL.PLLN = 80;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = RCC_PLLQ_DIV4;
  RCC_OscInitStruct.PLL.PLLR = RCC_PLLR_DIV2;
  /* 160 MHz requires Range1 boost, not the normal <=150 MHz setting. */
  if (HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1_BOOST) != HAL_OK) Error_Handler();
#else
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
#endif
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
#if defined(PICO_ROBOT14)
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
#else
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
#endif
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
#if defined(PICO_ROBOT14)
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
#else
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
#endif
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

#if defined(PICO_ROBOT14)
  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_4) != HAL_OK)
#else
  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_0) != HAL_OK)
#endif
  {
    Error_Handler();
  }
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
