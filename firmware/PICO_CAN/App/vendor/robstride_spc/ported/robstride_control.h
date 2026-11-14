#ifndef __ROBSTRIDE_CONYROL_H__
#define __ROBSTRIDE_CONYROL_H__

#include <string.h>
#include <stdint.h>
#define CAN_ID RobStrideSpc_SelectedMotor()
#define MASTER_ID RobStrideSpc_SelectedHost()
#define ANNOUNCE_DEVID  			0					//通告设备ID
#define MOTOR_CTRL      			0x01      //MOTOR-电机运控控制
#define MOTOR_FEEDBACK				0x02  		//MOTOR-电机反馈
#define MOTOR_IN							0x03      //MOTOR-进入电机模式
#define MOTOR_RESET						0x04      //MOTOR-电机复位模式
#define MOTOR_CALI						0x05      //MOTOR-高速编码器标定
#define MOTOR_ZERO						0x06      //MOTOR-设置机械零位	
#define MOTOR_ID							0x07      //MOTOR-设置ID	
#define MOTOR_PARAREAD				0x11     	//参数-读取
#define MOTOR_PARAWRITE 			0x12    	//参数-写入
#define MOTOR_ErrorFeedback 	0x15 			//MOTOR-故障帧反馈
#define MOTOR_DataSave				0x16 			//参数-保存
#define MOTOR_BAUD						0x17 			//修改波特率
#define MOTOR_Proactive				0x18 			//主动上报
#define MOTOR_MODESTE					0X19			//修改协议

/* Port: ranges are per selected motor, never the upstream MOTOR_TYPE=5 default. */
uint8_t RobStrideSpc_SelectedMotor(void);
uint8_t RobStrideSpc_SelectedHost(void);
float RobStrideSpc_VelocityMax(void);
float RobStrideSpc_TorqueMax(void);
#define P_MIN -12.57f
#define P_MAX 12.57f
#define V_MIN (-RobStrideSpc_VelocityMax())
#define V_MAX RobStrideSpc_VelocityMax()
#define T_MIN (-RobStrideSpc_TorqueMax())
#define T_MAX RobStrideSpc_TorqueMax()
#define KP_MIN 0.0f
#define KP_MAX 500.0f
#define KD_MIN 0.0f
#define KD_MAX 5.0f

#define Set_mode 		  'j'				//设置控制模式
#define Set_parameter 'p'				//设置参数
//各种控制模式
#define move_control_mode  			0	//运控模式
#define Pos_PP_control_mode  		1	//PP位置模式
#define Speed_control_mode 			2 //速度模式
#define Elect_control_mode 			3 //电流模式
#define Set_Zero_mode     			4 //零点模式
#define Pos_CSP_control_mode		5	//CSP位置模式
enum ModeStatus{   //定义id中24-28位
    rest=0,
    Cali,
		running,
};
typedef struct
{
	uint8_t uncalibrated;
	uint8_t StallOverloadFault;
	uint8_t MagneticEncoderFault;
	uint8_t OverTemperatureFault;
	uint8_t DriveFault;
	uint8_t UnderVoltageFault;
	enum ModeStatus mms;
	float angle;         // rad
	float speed;         // rad/s
	float torque;        // Nm
	float temperature;   // ℃
	uint8_t  motorMode;
	
} motor_feedback_t;

void RobStride_motor_enable(void);
void RobStride_motor_reset(void);
void Set_RobStride_Motor_parameter(uint16_t Index, float Value, char Value_mode);
void Get_RobStride_Motor_parameter(uint16_t Index);
void RobStrideMotor_move_control(float torque, float MechPosition,float speed, float kp, float kd);
void RobStride_Motor_Speed_control(float limit_cur,float Speed_acc,float Speed);
void RobStride_Motor_Pos_PP_control(float Speed, float Speed_acc, float Angle);
void RobStride_Motor_Pos_CSP_control(float Speed, float Angle);
void RobStride_Motor_current_control(float cuttent);
void RobStride_Set_ZreoPos(void);
void RobStride_Set_CAN_ID(uint8_t Set_CAN_ID);
void RobStride_Motor_MotorDataSave(void);
void RobStride_Motor_BaudRateChange(uint8_t F_CMD);
void RobStride_Motor_ProtactiveEscalationSet(uint8_t F_CMD);
void RobStride_Motor_MIT_ModeSet(uint8_t F_CMD);
void RobStride_Motor_MIT_enable(void);
void RobStride_Motor_MIT_reset(void);
void RobStride_Motor_MIT_ClearOrCheckError(uint8_t F_CMD);
void RobStride_Motor_MIT_SetMotorType(uint8_t F_CMD);
void RobStride_Motor_MIT_SetMotorId(uint8_t F_CMD);
void RobStride_Motor_MIT_Control(float Angle, float Speed, float Kp, float Kd, float Torque);
void RobStride_Motor_MIT_PositionControl(float position_rad, float speed_rad_per_s);
void RobStride_Motor_MIT_SpeedControl(float speed_rad_per_s, float current_limit);
void RobStride_Motor_MIT_SetZeroPos(void);
void RobStride_Motor_MIT_MotorDataSave(void);
void RobStride_Motor_MIT_ProtactiveEscalationSet(uint8_t F_CMD);
void Get_RobStride_Motor_MIT_parameter(uint16_t Index);
void Set_RobStride_Motor_MIT_parameter(uint16_t Index, float Value);
#endif


