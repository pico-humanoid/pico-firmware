# Added at top-level (CubeMX does not own this file).
set(RTOS ${CMAKE_CURRENT_SOURCE_DIR}/Middlewares/Third_Party/FreeRTOS/Source)
add_library(robot14_rtos STATIC
    ${RTOS}/tasks.c ${RTOS}/queue.c ${RTOS}/list.c ${RTOS}/timers.c
    ${RTOS}/event_groups.c ${RTOS}/stream_buffer.c
    ${RTOS}/portable/GCC/ARM_CM4F/port.c ${RTOS}/portable/MemMang/heap_4.c
    ${RTOS}/CMSIS_RTOS_V2/cmsis_os2.c)
target_link_libraries(robot14_rtos PUBLIC stm32cubemx)
target_include_directories(robot14_rtos PUBLIC ${RTOS}/include ${RTOS}/portable/GCC/ARM_CM4F ${RTOS}/CMSIS_RTOS_V2)
# Pass to HAL objects as well as the executable (same timebase/clock configuration).
target_compile_definitions(stm32cubemx INTERFACE PICO_ROBOT14=1 PICO_ROBOT_SWAP_CAN12=$<BOOL:${PICO_ROBOT_SWAP_CAN12}>)
target_link_libraries(${CMAKE_PROJECT_NAME} robot14_rtos)
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE App/robot App)
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    App/robot/Peripheral/rs_motor.c App/robot/Modules/motor_network.c
    App/robot/Communicate/robot_link.c App/robot/Communicate/robot_uart.c
    App/robot/Communicate/robot_can.c App/robot/Application/robot_app.c
    App/dual_device_reader.c App/device_reader.c App/protocol/bms_protocol.c App/protocol/power_protocol.c
    Core/Src/freertos.c Core/Src/stm32g4xx_hal_timebase_tim.c)
