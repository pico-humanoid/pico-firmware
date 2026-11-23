#ifndef MF7_CONTROL_H
#define MF7_CONTROL_H
#include "Modules/motor_network.h"

#define MF7_COUNT 7U
#define MF7_BUS 2U
/* Fixed-point thousandths of N m / (rad/s), for supervised bench tuning. */
#define MF7_KD_DEFAULT_MILLI 600U
#define MF7_KD_MAX_MILLI 800U
#define MF7_KD_STEP_MILLI 50U
typedef enum { MF7_KD_ACCEPTED, MF7_KD_OUT_OF_RANGE, MF7_KD_NOT_READY } Mf7KdResult;
typedef enum {
    MF7_SELF_CHECK, MF7_READY, MF7_STARTING, MF7_ZERO_TORQUE, MF7_DAMPING,
    MF7_DEBUG_RESERVED, MF7_STOPPING, MF7_FAULT_LOCKED
} Mf7State;
typedef struct {
    MotorNetwork net;
    Mf7State state, target, after_stop;
    const char *reason;
    uint32_t heartbeat_ms, entered_ms, arm_ms, last_step_ms, next_arm_ms;
    uint32_t uid_ms;
    uint16_t kd_milli;
    uint32_t feedback_seq[MF7_COUNT], apply_feedback[MF7_COUNT];
    uint8_t uid[MF7_COUNT][8];
    uint8_t uid_count, uid_reads, arm_count, submitted;
    bool heartbeat_seen, uid_waiting, uid_complete, stop_confirmed, have_step;
} Mf7;

void Mf7_Init(Mf7 *f);
Mf7KdResult Mf7_SetKd(Mf7 *f, unsigned milli, uint32_t now);
void Mf7_Command(Mf7 *f, const char *command, uint32_t now);
void Mf7_OnFrame(Mf7 *f, const CanFrame *frame);
void Mf7_Halt(Mf7 *f, uint32_t now, const char *reason);
void Mf7_Step(Mf7 *f, uint32_t now, RobotMotorSend send, void *ctx);
unsigned Mf7_Ready(const Mf7 *f, uint32_t now);
unsigned Mf7_Active(const Mf7 *f);
unsigned Mf7_Stopped(const Mf7 *f);
const char *Mf7_Name(Mf7State state);
#endif
