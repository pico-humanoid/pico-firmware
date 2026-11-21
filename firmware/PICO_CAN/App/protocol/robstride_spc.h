#ifndef PICO_ROBSTRIDE_SPC_H
#define PICO_ROBSTRIDE_SPC_H
#include "can_frame.h"
#define ROBSTRIDE_SPC_COMMIT "d8451a447d7265becf71271a008a71f7063b7ecc"
#define ROBSTRIDE_SPC_BACKEND "ROBSTRIDE_SPC_D8451A4_PORT_V1"
#define ROBSTRIDE_SPC_BANNER "# CONTROL_BACKEND,library=RobStrideSPC,commit=" ROBSTRIDE_SPC_COMMIT ",port=G474_CAPTURE_V1,safety=READBACK_STATE_MACHINE\r\n"
/* Pure, synchronous frame builders; all actual transmission remains in
   CanTransport. Call from the main loop only, never from an ISR. */
CanFrame RsSpc_Frame(uint8_t motor,uint8_t host,unsigned type,uint16_t index,float value);
CanFrame RsSpc_VersionFrame(uint8_t motor,uint8_t host);
float RsSpc_Float(const uint8_t *four_bytes);
bool RsSpc_FeedbackStatus(const CanFrame *frame,uint8_t *mode,uint8_t *fault);
#endif
