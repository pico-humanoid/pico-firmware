#ifndef ROBSTRIDE_SPC_PORT_H
#define ROBSTRIDE_SPC_PORT_H
#include "robstride_control.h"
#include <stdbool.h>
#include "protocol/can_frame.h"
/* Explicit fields replace the F105 aliasing/bitfield overlay. No HAL globals. */
typedef struct {uint32_t id,data,mode,res;} RobStrideSpcId;
typedef struct {uint32_t DLC,ExtId,StdId;} RobStrideSpcHeader;
extern RobStrideSpcId txCanIdEx,rxCanIdEx,mittxCanIdEx;
extern RobStrideSpcHeader txMsg,rxMsg,MITtxMsg;
extern uint8_t tx_data[8],rx_data[8];
extern motor_feedback_t mf;
void can_txd(void);
void can_MIT_txd(void);
void parse_motor_feedback(void);
float Byte_to_float(uint8_t *bytes);
void RobStrideSpc_PacingHint(uint32_t milliseconds);
#define HAL_Delay RobStrideSpc_PacingHint
/* Synchronous capture only: no transport or implicit motor operation. */
bool RobStrideSpc_Begin(uint8_t motor,uint8_t host,bool rs10p);
bool RobStrideSpc_End(CanFrame *frame);
void RobStrideSpc_FinishDecode(void);
void RobStrideSpc_AnnounceDevice(void);
#endif
