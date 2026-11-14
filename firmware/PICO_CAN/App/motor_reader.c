#include "motor_reader.h"
#include <string.h>

bool MotorReader_Init(MotorReader *r, uint8_t count, uint8_t first, uint8_t second,
                      uint8_t host, uint32_t now) {
    CanFrame probe;
    if (!r || (count != 1U && count != 2U) ||
        !Motor_MakeRead(first, host, 0, &probe) ||
        (count == 2U && (first == second || !Motor_MakeRead(second, host, 0, &probe)))) return false;
    memset(r, 0, sizeof(*r));
    r->count=count; r->host=host; r->nodes[0].id=first; r->nodes[1].id=second;
    r->next_poll=now+1000U;
    return true;
}
void MotorReader_Age(MotorReader *r, uint32_t now) {
    for (uint8_t n=0; n<r->count; ++n)
        for (uint8_t q=0; q<MOTOR_QUERY_COUNT; ++q)
            if ((r->nodes[n].valid & (1U<<q)) && (uint32_t)(now-r->nodes[n].last_ok[q])>10000U)
                r->nodes[n].valid &= (uint8_t)~(1U<<q);
}
void MotorReader_Step(MotorReader *r, uint32_t now, MotorSend send, void *context) {
    MotorReader_Age(r,now);
    if (r->pending && (uint32_t)(now-r->pending_at)>=700U) {
        ++r->nodes[r->pending_node].timeouts;
        r->pending=false;
    }
    if (r->pending || (int32_t)(now-r->next_poll)<0) return;
    const uint8_t n=r->next_node;
    MotorNode *node=&r->nodes[n];
    CanFrame frame;
    const uint8_t query=node->next_query;
    if (Motor_MakeRead(node->id,r->host,query,&frame) && send && send(context,&frame,now)) {
        ++node->submitted;
        r->pending=true; r->pending_node=n; r->pending_query=query; r->pending_at=now;
    } else ++node->rejected;
    node->next_query=(uint8_t)((query+1U)%MOTOR_QUERY_COUNT);
    if (node->next_query==0U) ++node->cycles;
    r->next_node=(uint8_t)((n+1U)%r->count);
    r->next_poll=now+200U;
}
bool MotorReader_OnFrame(MotorReader *r, const CanFrame *f, uint8_t *node_index, MotorReading *reading) {
    if (!f || !reading || !node_index) return false;
    for (uint8_t n=0; n<r->count; ++n) {
        MotorReading value;
        ProtocolResult result=Motor_ParseRead(f,r->nodes[n].id,r->host,&value);
        if (result==PROTOCOL_IGNORED) continue;
        MotorNode *node=&r->nodes[n];
        if (result==PROTOCOL_INVALID) { ++node->invalid; return false; }
        if (!r->pending || r->pending_node!=n || value.query!=r->pending_query ||
            (int32_t)(f->timestamp_ms-r->pending_at)<0 || (uint32_t)(f->timestamp_ms-r->pending_at)>700U) {
            ++node->ignored; return false;
        }
        node->value_milli[value.query]=value.value_milli;
        node->last_ok[value.query]=f->timestamp_ms;
        node->seen |= (uint8_t)(1U<<value.query);
        node->valid |= (uint8_t)(1U<<value.query);
        ++node->replies; r->pending=false;
        *node_index=n; *reading=value;
        return true;
    }
    return false;
}
