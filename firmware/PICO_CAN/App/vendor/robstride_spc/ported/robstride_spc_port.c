#include "robstride_spc_port.h"
#include <string.h>
RobStrideSpcId txCanIdEx,rxCanIdEx,mittxCanIdEx;
RobStrideSpcHeader txMsg,rxMsg,MITtxMsg;
uint8_t tx_data[8],rx_data[8];
static uint8_t selected_motor,selected_host;
static bool active,model_10p,invalid;
static unsigned captured;
static CanFrame output;
uint8_t RobStrideSpc_SelectedMotor(void){return selected_motor;}
uint8_t RobStrideSpc_SelectedHost(void){return selected_host;}
float RobStrideSpc_VelocityMax(void){return model_10p?13.0f:33.0f;}
float RobStrideSpc_TorqueMax(void){return model_10p?42.0f:14.0f;}
bool RobStrideSpc_Begin(uint8_t motor,uint8_t host,bool rs10p){
 if(active||motor==0||motor>127||host==0||host>=254||motor==host)return false;
 active=true;selected_motor=motor;selected_host=host;model_10p=rs10p;captured=0;invalid=false;
 memset(&txCanIdEx,0,sizeof(txCanIdEx));memset(&rxCanIdEx,0,sizeof(rxCanIdEx));memset(&mittxCanIdEx,0,sizeof(mittxCanIdEx));
 memset(&txMsg,0,sizeof(txMsg));memset(&rxMsg,0,sizeof(rxMsg));memset(&MITtxMsg,0,sizeof(MITtxMsg));
 memset(tx_data,0,sizeof(tx_data));memset(rx_data,0,sizeof(rx_data));memset(&mf,0,sizeof(mf));
 /* Upstream parameter read/write assume DLC was set by an earlier command. */
 txMsg.DLC=MITtxMsg.DLC=8;memset(&output,0,sizeof(output));return true;
}
void can_txd(void){
 if(!active||txCanIdEx.res||txCanIdEx.mode>31||txCanIdEx.id>255||txCanIdEx.data>65535||txMsg.DLC!=8){invalid=true;return;}
 ++captured;
 output=(CanFrame){.id=(txCanIdEx.mode<<24)|(txCanIdEx.data<<8)|txCanIdEx.id,.extended=true,.dlc=8};
 memcpy(output.data,tx_data,8);
}
void can_MIT_txd(void){invalid=true;} /* Private Classic CAN only in this project. */
void RobStrideSpc_PacingHint(uint32_t milliseconds){
 /* No busy wait in a frame builder. Application state machines own >=1ms
    parameter pacing and readback deadlines, including the 50ms CSP scheduler. */
 if(milliseconds>1U)invalid=true;
}
bool RobStrideSpc_End(CanFrame *frame){
 bool ok=active&&!invalid&&captured==1&&frame!=NULL;
 if(ok)*frame=output;
 active=false;return ok;
}
void RobStrideSpc_FinishDecode(void){active=false;}
void RobStrideSpc_AnnounceDevice(void){
 /* UID request is absent upstream; official private-protocol type 0 extension. */
 txCanIdEx.mode=ANNOUNCE_DEVID;txCanIdEx.id=CAN_ID;txCanIdEx.data=MASTER_ID;can_txd();
}
