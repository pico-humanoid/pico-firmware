#ifndef MOTOR_ENABLE_LOGIC_H
#define MOTOR_ENABLE_LOGIC_H
#ifndef PICO_SPEED_LIMIT_MA
#define PICO_SPEED_LIMIT_MA 500
#endif
#if PICO_SPEED_LIMIT_MA == 700
#define SPEED_CURRENT_LIMIT_A 0.7f
#define SPEED_CURRENT_LIMIT_TEXT "0.7"
#define SPEED_CURRENT_POLICY "STARTUP_0700_V1"
#elif PICO_SPEED_LIMIT_MA == 500
#define SPEED_CURRENT_LIMIT_A 0.5f
#define SPEED_CURRENT_LIMIT_TEXT "0.5"
#define SPEED_CURRENT_POLICY "BASE_0500_V1"
#else
#error "Only the reviewed 500mA and 700mA speed-test limits are allowed"
#endif
#include "protocol/can_frame.h"
typedef enum {ME_STOPPING,ME_BASELINE,ME_READY,ME_SET_MODE,ME_VERIFY_MODE,ME_SET_ZERO,
              ME_VERIFY_ZERO,ME_WAIT_ENABLED,ME_ACTIVE,ME_DONE,
              ME_SPEED_WRITE,ME_SPEED_READ,ME_SPEED_POSITION,ME_SPEED_POSTCHECK,
              ME_SPEED_TARGET,ME_SPEED_TARGET_READ,ME_SPEED_CLEAR,ME_SPEED_CLEAR_READ} MotorEnablePhase;
typedef bool (*MotorEnableSend)(void *context,const CanFrame *frame,uint32_t now);
typedef struct {
    uint8_t id,host,original_mode;
    MotorEnablePhase phase;
    uint32_t due,sent_at,last_heartbeat,last_feedback,enable_at,next_zero,next_iq,stop_at;
    uint32_t iq_samples,feedbacks;
    bool sent,host_seen,run_requested,finishing,enable_confirmed,stop_confirmed,error,abort_pending,stop_unconfirmed;
    float iq;
    const char *reason;
    bool speed_test,motion_confirmed,target_cleared;
    uint8_t parameter_step,telemetry_step;
    uint32_t active_at,last_iq,last_velocity,last_position,velocity_samples,position_samples;
    float velocity,position_start,position_delta;
    uint32_t refresh_ms,query_ms;
} MotorEnable;
void MotorEnable_Init(MotorEnable *e,uint8_t id,uint8_t host,uint32_t now);
void MotorEnable_InitSpeed(MotorEnable *e,uint8_t id,uint8_t host,uint32_t now);
void MotorEnable_Heartbeat(MotorEnable *e,uint32_t now);
bool MotorEnable_Request(MotorEnable *e,uint32_t now);
void MotorEnable_Stop(MotorEnable *e,uint32_t now,const char *reason,bool error);
void MotorEnable_OnFrame(MotorEnable *e,const CanFrame *f,uint32_t now);
void MotorEnable_Step(MotorEnable *e,uint32_t now,MotorEnableSend send,void *context);
void MotorEnable_CheckSafety(MotorEnable *e,uint32_t now);
const char *MotorEnable_Name(MotorEnablePhase phase);
#endif
