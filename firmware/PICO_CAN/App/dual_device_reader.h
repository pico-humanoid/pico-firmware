#ifndef PICO_DUAL_DEVICE_READER_H
#define PICO_DUAL_DEVICE_READER_H
#include "device_reader.h"

/* Two devices on ONE shared CAN bus, not FDCAN1/FDCAN2. Only one request
   may await a reply across both readers. A missing device cannot starve the other. */
typedef struct {
    DeviceReader bms, power;
    uint32_t next_due;
    uint8_t next_reader;
} DualDeviceReader;
bool DualDeviceReader_Init(DualDeviceReader *pair, const ReaderConfig *bms,
                           const ReaderConfig *power, uint32_t now);
void DualDeviceReader_Age(DualDeviceReader *pair, uint32_t now);
void DualDeviceReader_Step(DualDeviceReader *pair, uint32_t now,
                           ReaderSend send, void *context);
#endif
