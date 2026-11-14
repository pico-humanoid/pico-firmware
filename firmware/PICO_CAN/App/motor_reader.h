#ifndef PICO_MOTOR_READER_H
#define PICO_MOTOR_READER_H
#include "protocol/motor_protocol.h"

typedef struct {
    uint8_t id, next_query, seen, valid;
    int32_t value_milli[MOTOR_QUERY_COUNT];
    uint32_t last_ok[MOTOR_QUERY_COUNT], submitted, replies, invalid, ignored;
    uint32_t timeouts, rejected, cycles;
} MotorNode;
typedef struct {
    MotorNode nodes[2];
    uint8_t count, host, next_node, pending_node, pending_query;
    bool pending;
    uint32_t pending_at, next_poll;
} MotorReader;
typedef bool (*MotorSend)(void *context, const CanFrame *frame, uint32_t now);
bool MotorReader_Init(MotorReader *reader, uint8_t count, uint8_t first_id,
                      uint8_t second_id, uint8_t host, uint32_t now);
void MotorReader_Age(MotorReader *reader, uint32_t now);
void MotorReader_Step(MotorReader *reader, uint32_t now, MotorSend send, void *context);
/* Returns matched node/query only for the current request, not unsolicited data. */
bool MotorReader_OnFrame(MotorReader *reader, const CanFrame *frame, uint8_t *node, MotorReading *reading);
#endif
