#ifndef PICO_BOARD_FSM_H
#define PICO_BOARD_FSM_H

#include <stdbool.h>
#include <stdint.h>

#define BOARD_FSM_ALL_ACKS 3U
#define BOARD_FSM_TIMEOUT_MS 900U

typedef enum {
    BOARD_FSM_SELF_CHECK, BOARD_FSM_ZERO_TORQUE, BOARD_FSM_DAMPING,
    BOARD_FSM_DEBUG_RESERVED, BOARD_FSM_FAULT
} BoardFsmMode;

typedef enum {
    BOARD_FSM_NO_FAULT, BOARD_FSM_LOCAL_CHECK_FAILED,
    BOARD_FSM_SELF_CHECK_TIMEOUT, BOARD_FSM_MODE_TIMEOUT
} BoardFsmFault;

typedef enum {
    BOARD_FSM_ACCEPTED, BOARD_FSM_ALREADY, BOARD_FSM_BUSY,
    BOARD_FSM_LOCKED, BOARD_FSM_BAD_MODE
} BoardFsmReply;

typedef struct {
    BoardFsmMode state;
    BoardFsmMode target;
    BoardFsmFault fault;
    uint32_t started_ms;
    uint8_t acks;
    bool pending;
} BoardFsm;

void BoardFsm_Begin(BoardFsm *fsm, uint32_t now, bool local_ok);
BoardFsmReply BoardFsm_Request(BoardFsm *fsm, BoardFsmMode mode, uint32_t now);
void BoardFsm_Step(BoardFsm *fsm, uint32_t now, uint8_t confirmed);
const char *BoardFsm_ModeName(BoardFsmMode mode);
const char *BoardFsm_FaultName(BoardFsmFault fault);

#endif
