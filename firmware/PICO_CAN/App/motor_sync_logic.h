#ifndef MOTOR_SYNC_LOGIC_H
#define MOTOR_SYNC_LOGIC_H
#include "motor_position_logic.h"
#define MOTOR_SYNC_SEGMENT_MS 2000U
#define MOTOR_SYNC_DURATION_MS 40000U
#define MOTOR_SYNC_PERIOD_MS 50U
typedef struct {
 float peak,sum_square,minimum,maximum,last_error;
 uint32_t samples,bad_since;
 bool bad_tracking;
 float position[2];uint32_t at[2];unsigned history;
} MotorSyncMetrics;
typedef struct {
 MotorPosition motors[2];MotorSyncMetrics metrics[2];
 bool barrier_released,started,settling,complete,failure;
 uint32_t started_at,next_pair,elapsed,segments,pairs,max_lateness_ms;
 unsigned tx_budget;
 float progress_gap,max_progress_gap;bool progress_valid;uint32_t progress_at;
} MotorSync;
void MotorSync_Init(MotorSync *s,uint32_t now);
void MotorSync_Heartbeat(MotorSync *s,uint32_t now);
bool MotorSync_Request(MotorSync *s,uint32_t now);
void MotorSync_Stop(MotorSync *s,uint32_t now,const char *reason,bool error);
void MotorSync_OnFrame(MotorSync *s,const CanFrame *f,uint32_t now);
void MotorSync_Step(MotorSync *s,uint32_t now,unsigned tx_budget,MotorEnableSend send,void *context);
float MotorSync_UnitReference(uint32_t elapsed);
float MotorSync_Rms(const MotorSyncMetrics *m);
bool MotorSync_Passed(const MotorSync *s);
#endif
