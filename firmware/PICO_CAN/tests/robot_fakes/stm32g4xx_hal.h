/* Reuse the legacy fake HAL, adding the no-events transport option only. */
#include "../fakes/stm32g4xx_hal.h"
#define FDCAN_NO_TX_EVENTS 0U
