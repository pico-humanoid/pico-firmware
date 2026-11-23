#ifndef PICO_BOARD_FSM_CHECKS_H
#define PICO_BOARD_FSM_CHECKS_H

#include <stdint.h>

typedef void (*BoardFsmCaseReport)(const char *name, int passed);

uint8_t BoardFsm_SimulatedAcks(uint32_t elapsed_ms, uint8_t drop_mask);
unsigned BoardFsm_RunChecks(BoardFsmCaseReport report);

#endif
