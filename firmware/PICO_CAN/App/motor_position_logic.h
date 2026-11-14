#ifndef MOTOR_POSITION_LOGIC_H
#define MOTOR_POSITION_LOGIC_H
#include "motor_enable_logic.h"
/* Target readback agreement, distinct from the 0.5-degree arrival test. */
#define MOTOR_POSITION_READBACK_TOLERANCE_RAD 0.0005f
#define MOTOR_POSITION_STABLE_SPAN_RAD 0.0017453293f /* 0.1 degree, sampled range */
typedef enum {MP_START,MP_WRITE,MP_READ,MP_CHECK_START,MP_ENABLE,MP_POSTCHECK,
 MP_TARGET,MP_TARGET_READ,MP_MOVE,MP_CLEAN_POSITION,MP_CLEAN_WRITE,MP_CLEAN_READ} MotorPositionStage;
typedef struct {
 MotorEnable core;
 MotorPositionStage stage;
 unsigned parameter,waypoints;
 uint32_t leg_at,settle_at;
 bool settled,neutralize_failed;
 float origin,target,actual,max_arrival_error,max_return_error,peak_iq;
 float last_arrival_error,last_target;
 float amplitude_rad;
 uint32_t dwell_ms;
 float stable_min,stable_max,stable_span;
 uint32_t stable_last_at,stable_samples;
 float velocity_history[5],stable_velocity;
 unsigned velocity_cursor,velocity_count;
 float stable_last_position,sampled_position_speed,stable_position_travel,mean_position_speed;
 /* Opt-in streaming coordinator; legacy point-to-point behavior is default. */
 bool stream_control,stream_settling,stream_settled;
} MotorPosition;
void MotorPosition_Init(MotorPosition *p,uint8_t id,uint8_t host,uint32_t now);
void MotorPosition_Heartbeat(MotorPosition *p,uint32_t now);
bool MotorPosition_Request(MotorPosition *p,uint32_t now);
void MotorPosition_Stop(MotorPosition *p,uint32_t now,const char *reason,bool error);
void MotorPosition_OnFrame(MotorPosition *p,const CanFrame *f,uint32_t now);
void MotorPosition_Step(MotorPosition *p,uint32_t now,MotorEnableSend send,void *context);
void MotorPosition_CheckSafety(MotorPosition *p,uint32_t now);
const char *MotorPosition_Name(const MotorPosition *p);
bool MotorPosition_Passed(const MotorPosition *p);
#endif
