#include "board_fsm.h"
#include "board_fsm_checks.h"

uint8_t BoardFsm_SimulatedAcks(uint32_t elapsed_ms, uint8_t drop_mask)
{
    uint8_t acks = 0;
    if (elapsed_ms >= 150U) acks |= 1U;
    if (elapsed_ms >= 300U) acks |= 2U;
    return acks & (uint8_t)~drop_mask;
}

static int self_check(void)
{
    BoardFsm fsm;
    BoardFsm_Begin(&fsm, 10, true);
    int started = fsm.state == BOARD_FSM_SELF_CHECK &&
        BoardFsm_Request(&fsm, BOARD_FSM_DAMPING, 12) == BOARD_FSM_BUSY;
    BoardFsm_Step(&fsm, 160, BoardFsm_SimulatedAcks(150, 0));
    int waiting = fsm.state == BOARD_FSM_SELF_CHECK && fsm.acks == 1 && fsm.pending;
    BoardFsm_Step(&fsm, 310, BoardFsm_SimulatedAcks(300, 0));
    return started && waiting && fsm.state == BOARD_FSM_ZERO_TORQUE &&
        !fsm.pending && fsm.acks == BOARD_FSM_ALL_ACKS;
}

static int round_trip(void)
{
    BoardFsm fsm;
    BoardFsm_Begin(&fsm, 0, true);
    BoardFsm_Step(&fsm, 300, 3);
    if (BoardFsm_Request(&fsm, BOARD_FSM_DAMPING, 310) != BOARD_FSM_ACCEPTED ||
        fsm.acks != 0 || fsm.state != BOARD_FSM_ZERO_TORQUE ||
        BoardFsm_Request(&fsm, BOARD_FSM_ZERO_TORQUE, 311) != BOARD_FSM_BUSY) return 0;
    BoardFsm_Step(&fsm, 610, 3);
    if (fsm.state != BOARD_FSM_DAMPING ||
        BoardFsm_Request(&fsm, BOARD_FSM_DAMPING, 611) != BOARD_FSM_ALREADY ||
        BoardFsm_Request(&fsm, BOARD_FSM_ZERO_TORQUE, 620) != BOARD_FSM_ACCEPTED) return 0;
    BoardFsm_Step(&fsm, 920, 3);
    return fsm.state == BOARD_FSM_ZERO_TORQUE && !fsm.pending;
}

static int lost_feedback(void)
{
    BoardFsm fsm;
    BoardFsm_Begin(&fsm, 0, true);
    BoardFsm_Step(&fsm, 300, 3);
    if (BoardFsm_Request(&fsm, BOARD_FSM_DAMPING, 400) != BOARD_FSM_ACCEPTED) return 0;
    BoardFsm_Step(&fsm, 700, BoardFsm_SimulatedAcks(300, 2));
    BoardFsm_Step(&fsm, 1299, 1);
    if (!fsm.pending || fsm.acks != 1) return 0;
    BoardFsm_Step(&fsm, 1300, 3);
    BoardFsm_Step(&fsm, 1301, 3);
    return fsm.state == BOARD_FSM_FAULT && fsm.fault == BOARD_FSM_MODE_TIMEOUT &&
        fsm.acks == 1 && !fsm.pending &&
        BoardFsm_Request(&fsm, BOARD_FSM_ZERO_TORQUE, 1302) == BOARD_FSM_LOCKED &&
        BoardFsm_Request(&fsm, BOARD_FSM_DEBUG_RESERVED, 1303) == BOARD_FSM_LOCKED;
}

static int failed_check_and_recovery(void)
{
    BoardFsm fsm;
    BoardFsm_Begin(&fsm, 1, false);
    if (fsm.state != BOARD_FSM_FAULT || fsm.fault != BOARD_FSM_LOCAL_CHECK_FAILED) return 0;
    BoardFsm_Begin(&fsm, 10, true);
    BoardFsm_Step(&fsm, 310, BoardFsm_SimulatedAcks(300, 1));
    BoardFsm_Step(&fsm, 910, 2);
    if (fsm.state != BOARD_FSM_FAULT || fsm.fault != BOARD_FSM_SELF_CHECK_TIMEOUT ||
        fsm.acks != 2) return 0;
    BoardFsm_Begin(&fsm, 920, true);
    BoardFsm_Step(&fsm, 1220, 3);
    return fsm.state == BOARD_FSM_ZERO_TORQUE && fsm.fault == BOARD_FSM_NO_FAULT;
}

static int debug_round_trip_and_tick_wrap(void)
{
    BoardFsm fsm;
    BoardFsm_Begin(&fsm, UINT32_MAX - 600U, true);
    BoardFsm_Step(&fsm, UINT32_MAX - 300U, 3);
    if (fsm.state != BOARD_FSM_ZERO_TORQUE ||
        BoardFsm_Request(&fsm, BOARD_FSM_DEBUG_RESERVED, UINT32_MAX - 200U) != BOARD_FSM_ACCEPTED) return 0;
    BoardFsm_Step(&fsm, UINT32_MAX - 50U, 1);
    if (!fsm.pending || fsm.state != BOARD_FSM_ZERO_TORQUE || fsm.acks != 1U) return 0;
    BoardFsm_Step(&fsm, 99U, 2);
    if (fsm.pending || fsm.state != BOARD_FSM_DEBUG_RESERVED || fsm.acks != BOARD_FSM_ALL_ACKS ||
        BoardFsm_Request(&fsm, BOARD_FSM_DEBUG_RESERVED, 100U) != BOARD_FSM_ALREADY ||
        BoardFsm_Request(&fsm, BOARD_FSM_DAMPING, 101U) != BOARD_FSM_ACCEPTED) return 0;
    BoardFsm_Step(&fsm, 401U, 3);
    if (fsm.state != BOARD_FSM_DAMPING || fsm.pending ||
        BoardFsm_Request(&fsm, BOARD_FSM_DEBUG_RESERVED, 402U) != BOARD_FSM_ACCEPTED) return 0;
    BoardFsm_Step(&fsm, 702U, 3);
    if (fsm.state != BOARD_FSM_DEBUG_RESERVED || fsm.pending ||
        BoardFsm_Request(&fsm, BOARD_FSM_ZERO_TORQUE, 703U) != BOARD_FSM_ACCEPTED) return 0;
    BoardFsm_Step(&fsm, 1003U, 3);
    return fsm.state == BOARD_FSM_ZERO_TORQUE && !fsm.pending;
}

unsigned BoardFsm_RunChecks(BoardFsmCaseReport report)
{
    static const struct {
        const char *name;
        int (*run)(void);
    } cases[] = {
        {"self_check_requires_both_acks", self_check},
        {"zero_damping_zero_and_busy_guard", round_trip},
        {"missing_motor2_locks_and_rejects_late_ack", lost_feedback},
        {"failed_self_check_and_manual_recovery", failed_check_and_recovery},
        {"debug_round_trip_and_tick_wrap", debug_round_trip_and_tick_wrap},
    };
    unsigned failures = 0;
    for (unsigned i = 0; i < sizeof cases / sizeof cases[0]; ++i) {
        int passed = cases[i].run();
        if (!passed) ++failures;
        if (report) report(cases[i].name, passed);
    }
    return failures;
}
