#include "robstride_spc.h"
#include "vendor/robstride_spc/ported/robstride_spc_port.h"
#include <math.h>
#include <string.h>
static bool allowed_write(uint16_t index){
 switch(index){case 0x7005:case 0x7006:case 0x700A:case 0x7016:case 0x7017:case 0x7018:case 0x7022:return true;default:return false;}
}
CanFrame RsSpc_Frame(uint8_t motor,uint8_t host,unsigned type,uint16_t index,float value){
 CanFrame f={.dlc=9}; /* Invalid on failure, so a caller cannot send StdId=0. */
 if(type!=0&&type!=3&&type!=4&&type!=17&&type!=18)return f;
 if(type==18&&(!allowed_write(index)||!isfinite(value)))return f;
 if(type==18&&index==0x7005&&!(value==0||value==1||value==2||value==3||value==5))return f;
 if(!RobStrideSpc_Begin(motor,host,false))return f;
 switch(type){
 case 0:RobStrideSpc_AnnounceDevice();break;
 case 3:RobStride_motor_enable();break;
 case 4:RobStride_motor_reset();break;
 case 17:Get_RobStride_Motor_parameter(index);break;
 case 18:Set_RobStride_Motor_parameter(index,value,index==0x7005?Set_mode:Set_parameter);break;
 default:break;
 }
 if(!RobStrideSpc_End(&f))f=(CanFrame){.dlc=9};
 return f;
}
CanFrame RsSpc_VersionFrame(uint8_t motor,uint8_t host){
 /* Version query is another official-manual extension absent from SPC API. */
 CanFrame f=RsSpc_Frame(motor,host,4,0,0);if(CanFrame_IsValid(&f))f.data[1]=0xC4;return f;
}
float RsSpc_Float(const uint8_t *four_bytes){
 if(!four_bytes)return NAN;
 uint8_t payload[8]={0};memcpy(payload+4,four_bytes,4);return Byte_to_float(payload);
}
bool RsSpc_FeedbackStatus(const CanFrame *f,uint8_t *mode,uint8_t *fault){
 if(!f||!mode||!fault||!CanFrame_IsValid(f)||!f->extended||f->remote||f->dlc!=8||f->id>>24!=2U||((f->id>>22)&3U)>2U)return false;
 uint8_t motor=(uint8_t)(f->id>>8),host=(uint8_t)f->id;
 if(!RobStrideSpc_Begin(motor,host,false))return false;
 rxMsg.ExtId=f->id;rxCanIdEx.id=host;rxCanIdEx.data=(f->id>>8)&65535U;rxCanIdEx.mode=2;
 memcpy(rx_data,f->data,8);parse_motor_feedback();*mode=(uint8_t)mf.mms;
 *fault=(uint8_t)(mf.UnderVoltageFault|(mf.DriveFault<<1)|(mf.OverTemperatureFault<<2)|(mf.MagneticEncoderFault<<3)|(mf.StallOverloadFault<<4)|(mf.uncalibrated<<5));
 RobStrideSpc_FinishDecode();return true;
}
