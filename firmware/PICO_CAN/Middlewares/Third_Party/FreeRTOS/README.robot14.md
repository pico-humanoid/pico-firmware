# Robot14 vendor provenance

Offline copy from the user-specified reference project:
`/home/zjy/27RCfour/EmbeddedProgramming/new_dog2.4_6014/Middlewares/Third_Party/FreeRTOS/Source`.

- Kernel: FreeRTOS V10.3.1 (see `include/task.h`), MIT license in `Source/LICENSE`.
- ARM_CM4F GCC port and heap_4, not the reference H7 port.
- CMSIS-RTOS2 adapter: original Arm/ST files, with Apache-2.0 notices retained;
  full license in `Source/CMSIS_RTOS_V2/LICENSE.Apache-2.0`.
- Source files copied unchanged; no remote dependency installation is required.
- Robot14-specific configuration lives in `Core/Inc/FreeRTOSConfig.h`, not here.
- This is the reference project's pinned version, not a claim to use the latest
  FreeRTOS release. Upgrading requires separate adapter/port regression testing.
