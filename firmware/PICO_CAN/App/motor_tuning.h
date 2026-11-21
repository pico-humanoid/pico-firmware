#ifndef MOTOR_TUNING_H
#define MOTOR_TUNING_H
#include "protocol/robstride_spc.h"
typedef bool (*TuningSend)(void *,const CanFrame *,uint32_t);
typedef void (*TuningLog)(const char *);
typedef enum {TU_BOOT_STOP,TU_UID,TU_BASE,TU_READY,TU_ARM_STOP,TU_ORIGIN,TU_WRITE,TU_READ,TU_ENABLE,TU_POST,TU_ACTIVE,TU_CONTROL_WRITE,TU_CONTROL_READ,TU_STOP,TU_CLEAN_POS,TU_CLEAN_WRITE,TU_CLEAN_READ,TU_DONE} TuningStage;
typedef enum {TUNING_POSITION=5,TUNING_SPEED=2} TuningMode;
typedef struct {
 uint8_t id,uid[8];unsigned uid_count,stable_count,parameter,telemetry,control_parameter,attempts;
 TuningStage stage;TuningMode mode;
 bool sent,host_seen,uid_valid,enabled,stopped,target_cleared,error,cancel_pending;
 bool pos_valid,iq_valid,velocity_valid,telemetry_required,hold_enable,hold_control;
 uint32_t due,sent_at,last_host,last_feedback,last_position,last_iq,last_velocity,enable_at,next_refresh,samples,run_ms,stop_at,stall_since;
 uint32_t accepted_seq,applied_seq,transaction_seq;
 int32_t current_limit_ma;
 int32_t command_angle_mdeg,command_speed_mrad,command_velocity_mrad;
 int32_t transaction_angle_mdeg,transaction_speed_mrad,transaction_velocity_mrad;
 uint16_t pending_index;
 float expected,origin,actual,iq,velocity,target,limit,speed_target,stable_low,stable_high;
 const char *reason;TuningLog log;
} MotorTuning;
void MotorTuning_Init(MotorTuning *,uint8_t,uint32_t,TuningLog);
void MotorTuning_Heartbeat(MotorTuning *,uint32_t);
bool MotorTuning_CanArmTimed(const MotorTuning *,TuningMode,uint32_t,int32_t,int32_t,uint32_t,uint32_t);
bool MotorTuning_ArmTimed(MotorTuning *,TuningMode,uint32_t,int32_t,int32_t,uint32_t,uint32_t);
bool MotorTuning_CanSet(const MotorTuning *,uint32_t,int32_t,int32_t,uint32_t);
bool MotorTuning_Arm(MotorTuning *,TuningMode,uint32_t,int32_t,int32_t,uint32_t);
bool MotorTuning_Set(MotorTuning *,uint32_t,int32_t,int32_t,uint32_t);
void MotorTuning_Stop(MotorTuning *,uint32_t,const char *,bool);
void MotorTuning_OnFrame(MotorTuning *,const CanFrame *,uint32_t);
void MotorTuning_Step(MotorTuning *,uint32_t,TuningSend,void *);
const char *MotorTuning_Name(const MotorTuning *);
#endif
