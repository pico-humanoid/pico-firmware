# RobStrideSPC pinned G474 port

Upstream: https://github.com/RobStride/RobStrideSPC
Commit: d8451a447d7265becf71271a008a71f7063b7ecc

The upstream directory retains byte-verified originals and the upstream README's license/disclaimer statement. This project does not claim to relicense the vendor source. SOURCE.json records Git blob SHA-1 and SHA-256; PORTING.patch describes changes in the two ported library files.

The production port calls RobStride_motor_enable/reset and Set/Get_RobStride_Motor_parameter under a bounded, synchronous, one-frame capture context. Existing application state machines retain all operator gates and safety deadlines. can_txd captures a frame only; it never sends to hardware. MIT and compound multi-frame captures are rejected. UID and version queries are documented protocol extensions, not upstream SPC functions.

No original F105 HAL, startup, main loop, pin configuration or example motor constants are imported into the G474 hardware setup. Type2 numeric feedback scaling is not used for physical telemetry; the application uses checked type17 parameter reads. See the workspace docs/RobStrideSPC_Adaptation.md for the complete scope, safety boundaries and validation limits.
