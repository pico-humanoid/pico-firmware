#ifndef MOTOR_POSITION_DIAG_H
#define MOTOR_POSITION_DIAG_H
#include "protocol/can_frame.h"
#define DIAG_PARAM_COUNT 8U
typedef bool (*DiagSend)(void *context,const CanFrame *frame,uint32_t now);
typedef void (*DiagLog)(const char *line);
typedef enum {DG_STOP,DG_UID,DG_VERSION,DG_SNAPSHOT,DG_MONITOR,DG_ECHO_STOP,DG_ECHO_MODE,DG_ECHO_POS,DG_ECHO_WRITE,DG_ECHO_READ,DG_ECHO_AFTER,DG_FAILURE_STOP,DG_HALTED} DiagStage;
typedef struct {
 uint8_t id,uid[8];unsigned uid_samples,uid_remaining,parameter,monitor_query,round,read_number,attempts;
 DiagStage stage;bool sent,stop_confirmed,uid_valid,uid_conflict,snapshot_done,echo_requested,echo_active,echo_finished,echo_mismatch,last_match,target_cleared,failed,cancel_pending,host_seen;
 uint32_t due,sent_at,write_at,last_stop,last_uid,last_host,echo_samples;
 uint16_t pending_index;
 float values[DIAG_PARAM_COUNT],expected,last_read,max_error;bool valid[DIAG_PARAM_COUNT];
 const char *reason;DiagLog log;
} MotorPositionDiag;
extern const uint16_t diag_indices[DIAG_PARAM_COUNT];
void MotorPositionDiag_Init(MotorPositionDiag *d,uint8_t id,uint32_t now,DiagLog log);
void MotorPositionDiag_Heartbeat(MotorPositionDiag *d,uint32_t now);
bool MotorPositionDiag_RequestEcho(MotorPositionDiag *d,uint32_t now);
bool MotorPositionDiag_EchoAllowed(const MotorPositionDiag *d,uint32_t now);
void MotorPositionDiag_Stop(MotorPositionDiag *d,uint32_t now,const char *reason,bool error);
void MotorPositionDiag_OnFrame(MotorPositionDiag *d,const CanFrame *f,uint32_t now);
void MotorPositionDiag_Step(MotorPositionDiag *d,uint32_t now,DiagSend send,void *context);
const char *MotorPositionDiag_Name(const MotorPositionDiag *d);
#endif
