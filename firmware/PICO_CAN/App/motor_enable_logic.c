/* Operator-triggered single-motor policies. No ID/baud/flash/zero-cal commands. */
#include "motor_enable_logic.h"
#include "protocol/robstride_spc.h"
#include <string.h>
#include <math.h>
static bool due(uint32_t now,uint32_t deadline){return (int32_t)(now-deadline)>=0;}
typedef struct {uint16_t index;float value;} SpeedParameter;
/* Clear a stale velocity target before changing mode; verify everything while stopped.
   Recheck after enable before allowing the first nonzero velocity command. */
static const SpeedParameter speed_setup[]={{0x700A,0},{0x7005,2},{0x7018,SPEED_CURRENT_LIMIT_A},{0x7022,0.5f},{0x700A,0}};
static const SpeedParameter speed_post[]={{0x7005,2},{0x7018,SPEED_CURRENT_LIMIT_A},{0x7022,0.5f},{0x700A,0}};
static CanFrame packet(const MotorEnable *e,uint8_t type,uint16_t index){
    return RsSpc_Frame(e->id,e->host,type,index,0);
}
static CanFrame write_parameter(const MotorEnable *e,uint16_t index,float value){return RsSpc_Frame(e->id,e->host,18,index,value);}
static void phase(MotorEnable *e,MotorEnablePhase p,uint32_t now){e->phase=p;e->sent=false;e->due=now;}
const char *MotorEnable_Name(MotorEnablePhase p){
    static const char *const names[]={"STOPPING","READ_BASELINE","READY","SET_CURRENT_MODE","VERIFY_MODE",
        "SET_ZERO","VERIFY_ZERO","WAIT_ENABLED","ENABLED","DONE",
        "SPEED_SETUP_WRITE","SPEED_SETUP_READ","READ_START_POSITION","SPEED_POSTCHECK",
        "SET_SPEED_TARGET","VERIFY_SPEED_TARGET","CLEAR_SPEED_TARGET","VERIFY_CLEARED_TARGET"};
    return (unsigned)p<sizeof(names)/sizeof(names[0])?names[p]:"ERROR";
}
void MotorEnable_InitSpeed(MotorEnable *e,uint8_t id,uint8_t host,uint32_t now){
    MotorEnable_Init(e,id,host,now);e->speed_test=true;
}
void MotorEnable_Init(MotorEnable *e,uint8_t id,uint8_t host,uint32_t now){
    memset(e,0,sizeof(*e));e->id=id;e->host=host;e->reason="BOOT_STOP";
    e->phase=ME_STOPPING;e->due=now+200U;e->stop_at=now;
    e->refresh_ms=100U;e->query_ms=40U;
}
void MotorEnable_Heartbeat(MotorEnable *e,uint32_t now){e->host_seen=true;e->last_heartbeat=now;}
bool MotorEnable_Request(MotorEnable *e,uint32_t now){
    if(e->phase!=ME_READY || !e->host_seen || now-e->last_heartbeat>500U || e->run_requested || e->error)return false;
    e->run_requested=true;e->stop_confirmed=false;e->reason="PREPARING";
    phase(e,e->speed_test?ME_SPEED_WRITE:ME_SET_MODE,now);return true;
}
void MotorEnable_Stop(MotorEnable *e,uint32_t now,const char *reason,bool error){
    if(e->phase==ME_DONE)return;
    if(e->finishing){if(error)e->error=true;return;}
    e->finishing=true;e->error|=error;e->reason=reason;e->abort_pending=true;
    e->stop_confirmed=false;e->stop_at=now;phase(e,ME_STOPPING,now);
}
static float scalar(const uint8_t *d){
    return RsSpc_Float(d);
}
static bool parameter_matches(const CanFrame *f,const SpeedParameter *p){
    if(p->index==0x7005U)return f->data[4]==(uint8_t)p->value;
    float value=scalar(f->data+4);return isfinite(value)&&fabsf(value-p->value)<0.00001f;
}
static void clear_failed(MotorEnable *e,uint32_t now){
    e->error=true;e->reason="STOPPED_TARGET_CLEAR_FAILED";phase(e,ME_DONE,now);
}
void MotorEnable_OnFrame(MotorEnable *e,const CanFrame *f,uint32_t now){
    if(!CanFrame_IsValid(f)||!f->extended||f->remote||f->dlc!=8U ||
       (f->id&255U)!=e->host || ((f->id>>8)&255U)!=e->id)return;
    uint8_t type=(uint8_t)((f->id>>24)&31U);
    if(type==2U){
        uint8_t mode,fault;
        if(!RsSpc_FeedbackStatus(f,&mode,&fault)){MotorEnable_Stop(e,now,"INVALID_FEEDBACK_MODE",true);return;}
        ++e->feedbacks;e->last_feedback=now;
        if(fault)MotorEnable_Stop(e,now,"MOTOR_FAULT",true);
        if(e->phase==ME_STOPPING && e->sent && mode==0U && (int32_t)(f->timestamp_ms-e->sent_at)>=0){
            e->stop_confirmed=true;e->stop_unconfirmed=false;
            phase(e,e->finishing?(e->speed_test?ME_SPEED_CLEAR:ME_DONE):ME_BASELINE,now+50U);
        }else if(e->phase==ME_WAIT_ENABLED && e->sent && mode==2U && !fault &&
                 (int32_t)(f->timestamp_ms-e->sent_at)>=0){
            e->enable_confirmed=true;e->reason=e->speed_test?"LOW_SPEED_TEST":"ZERO_CURRENT_TEST";
            e->parameter_step=0;
            phase(e,e->speed_test?ME_SPEED_POSTCHECK:ME_ACTIVE,now);
            e->active_at=e->last_iq=e->last_velocity=e->last_position=now;
            e->next_zero=now;e->next_iq=now;
        }else if(e->enable_confirmed && !e->finishing && mode!=2U)MotorEnable_Stop(e,now,"UNEXPECTED_MOTOR_MODE",true);
        else if(e->speed_test && (e->phase==ME_SPEED_CLEAR||e->phase==ME_SPEED_CLEAR_READ) && mode!=0U){
            e->finishing=false;MotorEnable_Stop(e,now,"UNEXPECTED_MOTOR_MODE",true);
        }
        return;
    }
    if(type==21U){
        if(f->data[0]||f->data[1]||f->data[2]||f->data[3])MotorEnable_Stop(e,now,"FAULT_REPORT",true);
        return;
    }
    if(type!=17U)return;
    if(((f->id>>16)&255U)!=0U){MotorEnable_Stop(e,now,"PARAMETER_READ_REJECTED",true);return;}
    uint16_t index=(uint16_t)((uint16_t)f->data[0]|((uint16_t)f->data[1]<<8));
    if(e->phase==ME_ACTIVE && index==0x701AU){
        float value=scalar(f->data+4);++e->iq_samples;e->last_iq=now;
        if(isfinite(value)&&fabsf(value)<=1000.0f)e->iq=value;
        if(!isfinite(value)||fabsf(value)>(e->speed_test?0.8f:0.2f))
            MotorEnable_Stop(e,now,e->speed_test?"MEASURED_IQ_OVER_0.8A":"MEASURED_IQ_OVER_0.2A",true);
        return;
    }
    if(e->speed_test && e->phase==ME_ACTIVE && (index==0x701BU||index==0x7019U)){
        float value=scalar(f->data+4);
        if(!isfinite(value)||fabsf(value)>100000.0f){MotorEnable_Stop(e,now,"INVALID_MOTION_TELEMETRY",true);return;}
        if(index==0x701BU){
            e->velocity=value;e->last_velocity=now;++e->velocity_samples;
            if(fabsf(value)>0.6f||value< -0.1f)MotorEnable_Stop(e,now,"UNEXPECTED_SPEED",true);
        }else{
#if PICO_SPEED_LIMIT_MA == 700
            /* Raw position jumps must not turn a startup diagnostic into PASS.
               Use the existing 0.6rad/s speed bound plus 0.01rad sample margin. */
            float step=value-(e->position_start+e->position_delta);
            float bound=0.6f*((float)(now-e->last_position)/1000.0f)+0.01f;
            if(fabsf(step)>bound){MotorEnable_Stop(e,now,"POSITION_SAMPLE_JUMP",true);return;}
#endif
            e->position_delta=value-e->position_start;e->last_position=now;++e->position_samples;
            if(fabsf(e->position_delta)>1.2f||e->position_delta< -0.1f)
                MotorEnable_Stop(e,now,"UNEXPECTED_DISPLACEMENT",true);
        }
        if(e->velocity>0.05f&&e->velocity<=0.6f&&e->position_delta>0.05f&&e->position_delta<=1.2f)
            e->motion_confirmed=true;
        return;
    }
    if(!e->sent || (int32_t)(f->timestamp_ms-e->sent_at)<0)return;
    if(e->speed_test && (e->phase==ME_SPEED_READ||e->phase==ME_SPEED_POSTCHECK)){
        const SpeedParameter *p=e->phase==ME_SPEED_READ?&speed_setup[e->parameter_step]:&speed_post[e->parameter_step];
        if(index!=p->index)return;
        if(!parameter_matches(f,p)){MotorEnable_Stop(e,now,"SPEED_PARAMETER_READBACK_MISMATCH",true);return;}
        ++e->parameter_step;
        if(e->phase==ME_SPEED_READ){
            phase(e,e->parameter_step<sizeof(speed_setup)/sizeof(speed_setup[0])?ME_SPEED_WRITE:ME_SPEED_POSITION,now+20U);
        }else phase(e,e->parameter_step<sizeof(speed_post)/sizeof(speed_post[0])?ME_SPEED_POSTCHECK:ME_SPEED_TARGET,now+20U);
    }else if(e->phase==ME_SPEED_POSITION && index==0x7019U){
        float value=scalar(f->data+4);
        if(!isfinite(value)||fabsf(value)>100000.0f){MotorEnable_Stop(e,now,"INVALID_START_POSITION",true);return;}
        e->position_start=value;phase(e,ME_WAIT_ENABLED,now+20U);
    }else if(e->phase==ME_SPEED_TARGET_READ && index==0x700AU){
        SpeedParameter p={0x700A,0.3f};
        if(!parameter_matches(f,&p)){MotorEnable_Stop(e,now,"SPEED_TARGET_READBACK_MISMATCH",true);return;}
        phase(e,ME_ACTIVE,now);e->active_at=e->last_iq=e->last_velocity=e->last_position=now;
        e->next_zero=e->next_iq=now;
    }else if(e->phase==ME_SPEED_CLEAR_READ && index==0x700AU){
        SpeedParameter p={0x700A,0};
        if(!parameter_matches(f,&p)){clear_failed(e,now);return;}
        e->target_cleared=true;phase(e,ME_DONE,now);
    }else if(e->phase==ME_BASELINE && index==0x7005U){
        e->original_mode=f->data[4];
        if(e->original_mode>5U || e->original_mode==4U){MotorEnable_Stop(e,now,"UNKNOWN_RUN_MODE",true);return;}
        phase(e,ME_READY,now);
    }else if(e->phase==ME_VERIFY_MODE && index==0x7005U){
        if(f->data[4]!=3U){MotorEnable_Stop(e,now,"MODE_READBACK_MISMATCH",true);return;}
        phase(e,ME_SET_ZERO,now);
    }else if(e->phase==ME_VERIFY_ZERO && index==0x7006U){
        float value=scalar(f->data+4);
        if(!isfinite(value)||value!=0.0f){MotorEnable_Stop(e,now,"ZERO_READBACK_MISMATCH",true);return;}
        phase(e,ME_WAIT_ENABLED,now+50U);
    }
}
void MotorEnable_CheckSafety(MotorEnable *e,uint32_t now){
    if(e->run_requested && !e->finishing){
        if(!e->host_seen || now-e->last_heartbeat>500U)MotorEnable_Stop(e,now,"HOST_TIMEOUT",true);
        else if(e->enable_confirmed && now-e->last_feedback>500U)MotorEnable_Stop(e,now,"FEEDBACK_TIMEOUT",true);
        else if(e->enable_confirmed && e->speed_test && e->phase==ME_ACTIVE &&
                (now-e->last_iq>500U||now-e->last_velocity>500U||now-e->last_position>500U))
            MotorEnable_Stop(e,now,"TELEMETRY_TIMEOUT",true);
        else if(((e->phase==ME_WAIT_ENABLED&&e->sent)||e->enable_confirmed) && now-e->enable_at>=3000U){
            bool no_motion=e->speed_test&&!e->motion_confirmed;
            MotorEnable_Stop(e,now,no_motion?"NO_MOTION":"AUTO_STOP",no_motion);
        }
    }
}
void MotorEnable_Step(MotorEnable *e,uint32_t now,MotorEnableSend send,void *context){
    if(e->phase==ME_DONE || !send)return;
    MotorEnable_CheckSafety(e,now);
    if(e->phase==ME_STOPPING){
        if(now-e->stop_at>=2000U)e->stop_unconfirmed=true;
        if(due(now,e->due)){
            CanFrame f=packet(e,4,0);
            if(send(context,&f,now)){e->sent=true;e->sent_at=now;}
            e->due=now+100U;
        }return;
    }
    if(e->phase==ME_READY)return;
    if(e->phase==ME_ACTIVE){
        if(due(now,e->next_zero)){
            CanFrame f=write_parameter(e,e->speed_test?0x700A:0x7006,e->speed_test?0.3f:0);
            if(send(context,&f,now))e->next_zero=now+e->refresh_ms;
        }else if(due(now,e->next_iq)){
            static const uint16_t indices[]={0x701A,0x701B,0x7019};
            CanFrame f=packet(e,17,e->speed_test?indices[e->telemetry_step]:0x701A);
            if(send(context,&f,now)){
                e->next_iq=now+(e->speed_test?e->query_ms:200U);
                if(e->speed_test)e->telemetry_step=(uint8_t)((e->telemetry_step+1U)%3U);
            }
        }return;
    }
    if(e->sent){
        if(now-e->sent_at>500U){
            if(e->phase==ME_SPEED_CLEAR_READ)clear_failed(e,now);
            else MotorEnable_Stop(e,now,"STAGE_RESPONSE_TIMEOUT",true);
        }
        return;
    }
    if(!due(now,e->due))return;
    CanFrame f;
    switch(e->phase){
        case ME_BASELINE:case ME_VERIFY_MODE:f=packet(e,17,0x7005);break;
        case ME_SET_MODE:f=write_parameter(e,0x7005,3);break;
        case ME_SET_ZERO:f=packet(e,18,0x7006);break;
        case ME_VERIFY_ZERO:f=packet(e,17,0x7006);break;
        case ME_WAIT_ENABLED:f=packet(e,3,0);break;
        case ME_SPEED_WRITE:{
            const SpeedParameter *p=&speed_setup[e->parameter_step];f=write_parameter(e,p->index,p->value);
            break;
        }
        case ME_SPEED_READ:f=packet(e,17,speed_setup[e->parameter_step].index);break;
        case ME_SPEED_POSTCHECK:f=packet(e,17,speed_post[e->parameter_step].index);break;
        case ME_SPEED_POSITION:f=packet(e,17,0x7019);break;
        case ME_SPEED_TARGET:f=write_parameter(e,0x700A,0.3f);break;
        case ME_SPEED_TARGET_READ:case ME_SPEED_CLEAR_READ:f=packet(e,17,0x700A);break;
        case ME_SPEED_CLEAR:f=packet(e,18,0x700A);break;
        default:return;
    }
    if(!send(context,&f,now)){
        if(e->phase==ME_SPEED_CLEAR||e->phase==ME_SPEED_CLEAR_READ)clear_failed(e,now);
        else MotorEnable_Stop(e,now,"CAN_SUBMIT_REJECTED",true);
        return;
    }
    e->sent=true;e->sent_at=now;
    if(e->phase==ME_SET_MODE)phase(e,ME_VERIFY_MODE,now+50U);
    else if(e->phase==ME_SET_ZERO)phase(e,ME_VERIFY_ZERO,now+50U);
    else if(e->phase==ME_WAIT_ENABLED)e->enable_at=now;
    else if(e->phase==ME_SPEED_WRITE)phase(e,ME_SPEED_READ,now+50U);
    else if(e->phase==ME_SPEED_TARGET)phase(e,ME_SPEED_TARGET_READ,now+50U);
    else if(e->phase==ME_SPEED_CLEAR)phase(e,ME_SPEED_CLEAR_READ,now+50U);
}
