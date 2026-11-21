#ifndef ROBOT_CAN_H
#define ROBOT_CAN_H
#include "fdcan.h"
#include "protocol/can_frame.h"
typedef struct {
  uint32_t tx_submitted, tx_done, tx_expired, rx_received, rx_dropped,
      rx_invalid, fifo_lost, bus_off;
} RobotCanStats;
bool RobotCan_Start(void);
bool RobotCan_Send(void *unused, uint8_t bus, const CanFrame *f, uint32_t now);
bool RobotCan_Receive(uint8_t bus, CanFrame *f);
void RobotCan_Service(uint32_t now);
void RobotCan_AbortMotors(void);
RobotCanStats RobotCan_GetStats(uint8_t bus);
/* A bus counts as connected only after at least one frame was acknowledged
   (tx_done) or received. An unpopulated bus keeps probing; its timeouts must
   not stop the other motor bus. */
bool RobotCan_BusActive(uint8_t bus);
/* True only when a bus that had been connected before has a real fault now:
   bus-off, a new TX timeout after activation, or RX ring/FIFO loss. Faults on
   a bus that never carried traffic (e.g. CAN3 with nothing wired) are isolated
   and stay visible in GetStats instead of latching a global stop. */
bool RobotCan_BusFatal(uint8_t bus);
#endif
