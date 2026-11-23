#include "board_fsm.h"

static void start(BoardFsm *fsm, BoardFsmMode target, uint32_t now)
{
    fsm->target = target;
    fsm->started_ms = now;
    fsm->acks = 0;
    fsm->pending = true;
}

void BoardFsm_Begin(BoardFsm *fsm, uint32_t now, bool local_ok)
{
    *fsm = (BoardFsm){.state = BOARD_FSM_SELF_CHECK};
    start(fsm, BOARD_FSM_ZERO_TORQUE, now);
    if (!local_ok) {
        fsm->state = BOARD_FSM_FAULT;
        fsm->fault = BOARD_FSM_LOCAL_CHECK_FAILED;
        fsm->pending = false;
    }
}

BoardFsmReply BoardFsm_Request(BoardFsm *fsm, BoardFsmMode mode, uint32_t now)
{
    if (mode != BOARD_FSM_ZERO_TORQUE && mode != BOARD_FSM_DAMPING &&
        mode != BOARD_FSM_DEBUG_RESERVED) return BOARD_FSM_BAD_MODE;
    if (fsm->state == BOARD_FSM_FAULT) return BOARD_FSM_LOCKED;
    if (fsm->pending) return BOARD_FSM_BUSY;
    if (fsm->state == mode) return BOARD_FSM_ALREADY;
    start(fsm, mode, now);
    return BOARD_FSM_ACCEPTED;
}

void BoardFsm_Step(BoardFsm *fsm, uint32_t now, uint8_t confirmed)
{
    if (!fsm->pending) return;
    if (now - fsm->started_ms >= BOARD_FSM_TIMEOUT_MS) {
        fsm->fault = fsm->state == BOARD_FSM_SELF_CHECK
            ? BOARD_FSM_SELF_CHECK_TIMEOUT : BOARD_FSM_MODE_TIMEOUT;
        fsm->state = BOARD_FSM_FAULT;
        fsm->pending = false;
        return;
    }
    fsm->acks |= confirmed & BOARD_FSM_ALL_ACKS;
    if (fsm->acks == BOARD_FSM_ALL_ACKS) {
        fsm->state = fsm->target;
        fsm->pending = false;
    }
}

const char *BoardFsm_ModeName(BoardFsmMode mode)
{
    switch (mode) {
        case BOARD_FSM_SELF_CHECK: return "SELF_CHECK";
        case BOARD_FSM_ZERO_TORQUE: return "ZERO_TORQUE";
        case BOARD_FSM_DAMPING: return "DAMPING";
        case BOARD_FSM_DEBUG_RESERVED: return "DEBUG_RESERVED";
        case BOARD_FSM_FAULT: return "FAULT_LOCKED";
    }
    return "UNKNOWN";
}

const char *BoardFsm_FaultName(BoardFsmFault fault)
{
    switch (fault) {
        case BOARD_FSM_NO_FAULT: return "NONE";
        case BOARD_FSM_LOCAL_CHECK_FAILED: return "LOCAL_CHECK_FAILED";
        case BOARD_FSM_SELF_CHECK_TIMEOUT: return "SELF_CHECK_TIMEOUT";
        case BOARD_FSM_MODE_TIMEOUT: return "MODE_TIMEOUT";
    }
    return "UNKNOWN";
}
