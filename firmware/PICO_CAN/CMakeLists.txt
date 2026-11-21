cmake_minimum_required(VERSION 3.22)

#
# This file is generated only once,
# and is not re-generated if converter is called multiple times.
#
# User is free to modify the file as much as necessary
#

# Setup compiler settings
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)


# Define the build type
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Debug")
endif()

# Set the project name
set(CMAKE_PROJECT_NAME PICO_CAN)

# Enable compile command to ease indexing with e.g. clangd
set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)

# Core project settings
project(${CMAKE_PROJECT_NAME})
message("Build type: " ${CMAKE_BUILD_TYPE})

# Enable CMake support for ASM and C languages
enable_language(C ASM)

# Create an executable object type
add_executable(${CMAKE_PROJECT_NAME})

# Add STM32CubeMX generated sources
add_subdirectory(cmake/stm32cubemx)

# Link directories setup
target_link_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined library search paths
)

# Add sources to executable
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user sources here
)

# Add include paths
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined include paths
)

# Add project symbols (macros)
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined symbols
)

# Remove wrong libob.a library dependency when using cpp files
list(REMOVE_ITEM CMAKE_C_IMPLICIT_LINK_LIBRARIES ob)

# Add linked libraries
target_link_libraries(${CMAKE_PROJECT_NAME}
    stm32cubemx

    # Add user defined libraries
)

# PICO validation application: CubeMX preserves this top-level file.
option(PICO_EXTERNAL_CAN "Use normal CAN mode instead of internal loopback" OFF)
# Each image owns its HAL callbacks; never link bring-up and device transport together.
set(PICO_APP "Bringup" CACHE STRING "Application image (select from PICO_APP cache choices)")
set_property(CACHE PICO_APP PROPERTY STRINGS Robot14 Bringup BMS Power Dual PowerBaud PinLoop Motor MotorEnable MotorSpeed MotorDualSpeed MotorDualFault MotorPosition MotorDualPosition MotorSyncPosition MotorPositionDiag MotorTuning Listen Can3Bench CanMultiBench Can1Periodic Can2Periodic Can3Periodic)
set(PICO_CAN_CHANNEL "1" CACHE STRING "FDCAN instance: 1 (PA11/PA12), 2 (PB12/PB13), 3 (PA8/PA15)")
set_property(CACHE PICO_CAN_CHANNEL PROPERTY STRINGS 1 2 3)
# Diagnostic only: keep the logical topology (CAN1 devices, CAN2/3 motors) but
# move devices to FDCAN2 (500k) and motors to FDCAN1 (1M).
set(PICO_ROBOT_SWAP_CAN12 OFF CACHE BOOL "Robot14 diagnostic: physical CAN1/CAN2 instance swap")
if(NOT PICO_CAN_CHANNEL MATCHES "^(1|2|3)$")
    message(FATAL_ERROR "PICO_CAN_CHANNEL must be 1, 2, or 3")
endif()
if(PICO_APP MATCHES "^(Bringup|PinLoop|PowerBaud)$" AND NOT PICO_CAN_CHANNEL STREQUAL "1")
    message(FATAL_ERROR "Bringup/PinLoop/PowerBaud require PICO_CAN_CHANNEL=1")
endif()
if(PICO_APP STREQUAL "Robot14")
    set(PICO_EXTERNAL_CAN ON)
    include(App/robot/robot14.cmake)
elseif(PICO_APP STREQUAL "PinLoop")
    # Test-only: PA12 output, PA11 input; FDCAN is deinitialized; no CAN traffic.
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/pin_loop_test.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_PIN_LOOP_TEST=1)
    message(STATUS "Pin loop test: PA12 out, PA11 in; FDCAN deinit; no CAN")
elseif(PICO_APP STREQUAL "Bringup")
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/can_bringup.c)
elseif(PICO_APP STREQUAL "CanMultiBench")
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/can_multi_test.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_CAN_MULTI_TEST=1)
    message(STATUS "CAN1/2/3 PC bench: all active; 1M; independent counters; no motors")
elseif(PICO_APP MATCHES "^Can([123])Periodic$")
    set(PICO_PERIODIC_CHANNEL ${CMAKE_MATCH_1})
    set(PICO_PERIODIC_BITRATE "1000000" CACHE STRING "Periodic CAN bitrate: 500000 or 1000000")
    if(NOT PICO_PERIODIC_BITRATE MATCHES "^(500000|1000000)$")
        message(FATAL_ERROR "Periodic CAN bitrate must be 500000 or 1000000")
    endif()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/can_periodic_tx.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_CAN_PERIODIC_TX=1 PICO_PERIODIC_CHANNEL=${PICO_PERIODIC_CHANNEL} PICO_PERIODIC_BITRATE=${PICO_PERIODIC_BITRATE})
    message(STATUS "CAN${PICO_PERIODIC_CHANNEL} periodic TX: ${PICO_PERIODIC_BITRATE} bit/s EXT 0x123 every 1000ms; no request needed")
elseif(PICO_APP STREQUAL "Can3Bench")
    set(PICO_EXTERNAL_CAN ON)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/can_bringup.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_CAN3_PC_TEST=1)
    message(STATUS "CAN3 PC bench: 1M extended 0x321/0x123; disconnect motors")
elseif(PICO_APP STREQUAL "Listen")
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/can3_listen.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_CAN_LISTEN=1)
    message(STATUS "CAN3 passive listener: 1M, BUS_MONITORING, all IDs, no TX/ACK")
elseif(PICO_APP STREQUAL "MotorTuning")
    set(PICO_TUNE_COUNT "1" CACHE STRING "Tuning motor count")
    if(NOT PICO_TUNE_COUNT MATCHES "^[12]$")
        message(FATAL_ERROR "Tuning count must be 1 or 2")
    endif()
    set(PICO_TUNE_MOTOR_ID "1" CACHE STRING "Tuning motor ID")
    set(PICO_TUNE_MODEL "RS10P" CACHE STRING "Tuning model")
    if(NOT PICO_TUNE_MOTOR_ID MATCHES "^[1-9][0-9]*$" OR PICO_TUNE_MOTOR_ID GREATER 127 OR NOT PICO_TUNE_MODEL MATCHES "^(RS10P|RS00)$")
        message(FATAL_ERROR "Tuning target must be ID 1..127 and model RS10P or RS00")
    endif()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/motor_tuning.c App/motor_tuning_app.c App/transport/can_transport.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_MOTOR_ENABLE=1 PICO_MOTOR_CAN_CHANNEL=1 PICO_CAN_BOUNDED_TX_RETRY=1 PICO_TUNE_COUNT=${PICO_TUNE_COUNT} PICO_TUNE_MOTOR_ID=${PICO_TUNE_MOTOR_ID} PICO_TUNE_MODEL="${PICO_TUNE_MODEL}")
elseif(PICO_APP STREQUAL "MotorPositionDiag")
    set(PICO_DIAG_MOTOR_ID "1" CACHE STRING "Single stopped motor to diagnose")
    set(PICO_DIAG_MODEL "RS10P" CACHE STRING "Configured model label")
    if(NOT PICO_DIAG_MOTOR_ID MATCHES "^[1-9][0-9]*$" OR PICO_DIAG_MOTOR_ID GREATER 127 OR NOT PICO_DIAG_MODEL MATCHES "^(RS10P|RS00)$")
        message(FATAL_ERROR "Diagnostic target must be ID 1..127 and model RS10P or RS00")
    endif()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/motor_position_diag.c App/motor_position_diag_app.c App/transport/can_transport.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_MOTOR_ENABLE=1 PICO_MOTOR_CAN_CHANNEL=1 PICO_CAN_BOUNDED_TX_RETRY=1 PICO_DIAG_MOTOR_ID=${PICO_DIAG_MOTOR_ID} PICO_DIAG_MODEL="${PICO_DIAG_MODEL}")
    message(STATUS "Stopped diagnostic: no enable; reads + manually triggered echo of current measured position only")
elseif(PICO_APP STREQUAL "MotorSyncPosition")
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/motor_enable_logic.c App/motor_position_logic.c App/motor_sync_logic.c App/motor_sync_position_app.c App/transport/can_transport.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_MOTOR_ENABLE=1 PICO_MOTOR_CAN_CHANNEL=1 PICO_CAN_BOUNDED_TX_RETRY=1)
    message(STATUS "Shared-clock quintic position: RS10P ID1 +/-5deg, RS00 ID2 -/+3deg, 2s/segment, 5 cycles, 50ms target period; manual RUN")
elseif(PICO_APP STREQUAL "MotorDualPosition")
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/motor_enable_logic.c App/motor_position_logic.c App/motor_dual_position_app.c App/transport/can_transport.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_MOTOR_ENABLE=1 PICO_MOTOR_CAN_CHANNEL=1 PICO_CAN_BOUNDED_TX_RETRY=1)
    message(STATUS "Independent dual-position: RS10P ID1 +/-5deg dwell500ms; RS00 ID2 -/+3deg dwell800ms; 10 cycles; any error stops both")
elseif(PICO_APP STREQUAL "MotorDualSpeed" OR PICO_APP STREQUAL "MotorDualFault")
    if(PICO_APP STREQUAL "MotorDualFault")
        set(PICO_FAULT_TARGET "1" CACHE STRING "Motor feedback to suppress: 1 or 2")
        if(NOT PICO_FAULT_TARGET MATCHES "^[12]$")
            message(FATAL_ERROR "Fault target must be 1 or 2")
        endif()
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_FAULT_TARGET=${PICO_FAULT_TARGET})
    endif()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/motor_enable_logic.c App/motor_dual_speed_app.c App/transport/can_transport.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_MOTOR_ENABLE=1 PICO_MOTOR_SPEED=1 PICO_MOTOR_DUAL_SPEED=1 PICO_MOTOR_CAN_CHANNEL=1)
    message(STATUS "Dual motor CAN1 1M: RS10P ID1 + RS00 ID2; each 0.3rad/s, 0.5A, 0.5rad/s2; manual RUN; any error stops both")
elseif(PICO_APP STREQUAL "MotorEnable" OR PICO_APP STREQUAL "MotorSpeed" OR PICO_APP STREQUAL "MotorPosition")
    set(PICO_ENABLE_MOTOR_ID "2" CACHE STRING "Single motor enable experiment target ID")
    set(PICO_ENABLE_MODEL "RS00" CACHE STRING "Single motor model: RS00 or RS10P")
    if(NOT PICO_ENABLE_MOTOR_ID MATCHES "^[1-9][0-9]*$" OR PICO_ENABLE_MOTOR_ID GREATER 127)
        message(FATAL_ERROR "Enable experiment motor ID must be decimal 1..127")
    endif()
    if(NOT PICO_ENABLE_MODEL MATCHES "^(RS00|RS10P)$")
        message(FATAL_ERROR "Enable experiment model must be RS00 or RS10P")
    endif()
    if(PICO_APP STREQUAL "MotorPosition")
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/motor_enable_logic.c App/motor_position_logic.c App/motor_position_app.c App/transport/can_transport.c)
    else()
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/motor_enable_logic.c App/motor_enable_app.c App/transport/can_transport.c)
    endif()
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_MOTOR_ENABLE=1 PICO_MOTOR_CAN_CHANNEL=1
        PICO_ENABLE_MOTOR_ID=${PICO_ENABLE_MOTOR_ID} PICO_ENABLE_MODEL="${PICO_ENABLE_MODEL}")
    if(PICO_APP STREQUAL "MotorSpeed")
        set(PICO_SPEED_LIMIT_MA "500" CACHE STRING "Reviewed speed test current limit: 500 or 700mA")
        if(NOT PICO_SPEED_LIMIT_MA MATCHES "^(500|700)$")
            message(FATAL_ERROR "Speed test limit must be 500 or 700mA")
        endif()
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_MOTOR_SPEED=1 PICO_SPEED_LIMIT_MA=${PICO_SPEED_LIMIT_MA})
        message(STATUS "Single motor low-speed: target=0.3rad/s limit=${PICO_SPEED_LIMIT_MA}mA accel=0.5rad/s2; host trigger; 3s auto-stop")
    elseif(PICO_APP STREQUAL "MotorPosition")
        message(STATUS "Position CSP: ${PICO_ENABLE_MODEL} ID${PICO_ENABLE_MOTOR_ID}, +/-5deg x10, 0.2rad/s, 0.5A, 500ms dwell, 90s total timeout")
    else()
        message(STATUS "Single motor enable experiment: CAN1 1M ${PICO_ENABLE_MODEL} ID=${PICO_ENABLE_MOTOR_ID}; zero current, host trigger, 3s auto-stop")
    endif()
elseif(PICO_APP STREQUAL "Motor")
    set(PICO_MOTOR_CAN_CHANNEL "1" CACHE STRING "Motor CAN controller: 1 or 3")
    if(NOT PICO_MOTOR_CAN_CHANNEL MATCHES "^(1|3)$")
        message(FATAL_ERROR "Motor CAN controller must be 1 or 3")
    endif()
    option(PICO_CAN_PIN_TRACE "Observe the first CAN3 TX/RX at unchanged bit timing" OFF)
    option(PICO_CAN_DMA_TRACE "Use TIM6/DMA1 GPIO sampling for the diagnostic image" OFF)
    if(PICO_CAN_PIN_TRACE)
        if(NOT PICO_MOTOR_CAN_CHANNEL STREQUAL "3")
            message(FATAL_ERROR "Historical PA15/PA8 trace requires motor CAN channel 3")
        endif()
        if(PICO_CAN_DMA_TRACE)
            target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/can_dma_trace.c)
        else()
            target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/can_pin_trace.c)
        endif()
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_CAN_PIN_TRACE=1)
    endif()
    set(PICO_DEVICE_BITRATE "1000000" CACHE STRING "Motor Classic CAN bitrate")
    set(PICO_MOTOR_COUNT "1" CACHE STRING "Number of motors: 1 or 2")
    set(PICO_MOTOR1_ID "0x7F" CACHE STRING "Motor 1 actual ID (1..127); example only")
    set(PICO_MOTOR2_ID "2" CACHE STRING "Motor 2 actual ID (1..127)")
    set(PICO_MOTOR_HOST_ID "0xFD" CACHE STRING "Host ID (128..253)")
    set(PICO_MOTOR1_MODEL "RS10P" CACHE STRING "Configured model: RS10P or RS00")
    set(PICO_MOTOR2_MODEL "RS00" CACHE STRING "Configured model: RS10P or RS00")
    if(NOT PICO_DEVICE_BITRATE STREQUAL "1000000" OR NOT PICO_MOTOR_COUNT MATCHES "^[12]$")
        message(FATAL_ERROR "Motor requires 1000000 bit/s and count 1 or 2")
    endif()
    foreach(key IN ITEMS PICO_MOTOR1_ID PICO_MOTOR2_ID PICO_MOTOR_HOST_ID)
        if(NOT "${${key}}" MATCHES "^(0[xX][0-9a-fA-F]+|[1-9][0-9]*)$")
            message(FATAL_ERROR "${key} must be a decimal or hexadecimal ID")
        endif()
        math(EXPR _${key} "${${key}}")
    endforeach()
    if(_PICO_MOTOR1_ID LESS 1 OR _PICO_MOTOR1_ID GREATER 127 OR
       _PICO_MOTOR2_ID LESS 1 OR _PICO_MOTOR2_ID GREATER 127 OR
       _PICO_MOTOR_HOST_ID LESS 128 OR _PICO_MOTOR_HOST_ID GREATER 253)
        message(FATAL_ERROR "Motor IDs must be 1..127; host ID must be 128..253")
    endif()
    if(PICO_MOTOR_COUNT STREQUAL "2" AND _PICO_MOTOR1_ID EQUAL _PICO_MOTOR2_ID)
        message(FATAL_ERROR "Two motors on the same CAN bus must have different IDs")
    endif()
    foreach(key IN ITEMS PICO_MOTOR1_MODEL PICO_MOTOR2_MODEL)
        if(NOT "${${key}}" MATCHES "^(RS10P|RS00)$")
            message(FATAL_ERROR "${key} must be RS10P or RS00")
        endif()
    endforeach()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/protocol/motor_protocol.c
        App/motor_reader.c App/motor_read_app.c App/transport/can_transport.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_MOTOR_READ=1
        PICO_MOTOR_CAN_CHANNEL=${PICO_MOTOR_CAN_CHANNEL}
        PICO_MOTOR_COUNT=${PICO_MOTOR_COUNT} PICO_MOTOR1_ID=${_PICO_MOTOR1_ID}
        PICO_MOTOR2_ID=${_PICO_MOTOR2_ID} PICO_MOTOR_HOST_ID=${_PICO_MOTOR_HOST_ID}
        PICO_MOTOR1_MODEL="${PICO_MOTOR1_MODEL}" PICO_MOTOR2_MODEL="${PICO_MOTOR2_MODEL}")
    message(STATUS "Read-only Motor: CAN${PICO_MOTOR_CAN_CHANNEL} / 1M; type17 only; CAN1=PA12 TX/PA11 RX AF9")
elseif(PICO_APP STREQUAL "BMS" OR PICO_APP STREQUAL "Power" OR PICO_APP STREQUAL "PowerBaud" OR PICO_APP STREQUAL "Dual")
    if(PICO_APP STREQUAL "BMS" OR PICO_APP STREQUAL "Dual")
        set(_device_kind 0)
        set(_default_bitrate 500000)
    else()
        set(_device_kind 1)
        set(_default_bitrate 1000000)
    endif()
    message(STATUS "Device CAN: FDCAN${PICO_CAN_CHANNEL}; CAN1 PA11/RX PA12/TX; CAN2 PB12/RX PB13/TX; CAN3 PA8/RX PA15/TX")
    set(PICO_DEVICE_BITRATE "${_default_bitrate}" CACHE STRING "CAN bitrate: 500000 or 1000000")
    set(PICO_POWER_ID "0xAA" CACHE STRING "Actual power-board ID (0..255)")
    if(PICO_APP STREQUAL "Dual")
        set(_default_rtr_dlc 0)
    else()
        set(_default_rtr_dlc 8)
    endif()
    set(PICO_BMS_RTR_DLC "${_default_rtr_dlc}" CACHE STRING "BMS remote request DLC: 0 or 8 (no payload)")
    set(PICO_BMS_CRC_ENDIAN "BIG" CACHE STRING "BMS CRC wire order: BIG or LITTLE")
    set(PICO_POWER_STATUS_ENDIAN "BIG" CACHE STRING "Power status byte order: RAW, BIG, LITTLE")
    if(NOT PICO_DEVICE_BITRATE MATCHES "^(500000|1000000)$")
        message(FATAL_ERROR "PICO_DEVICE_BITRATE must be 500000 or 1000000")
    endif()
    if(PICO_APP STREQUAL "Dual" AND NOT PICO_DEVICE_BITRATE STREQUAL "500000")
        message(FATAL_ERROR "Dual requires both devices on the same selected FDCAN bus at 500000 bit/s")
    endif()
    if(NOT PICO_BMS_RTR_DLC MATCHES "^(0|8)$")
        message(FATAL_ERROR "PICO_BMS_RTR_DLC must be 0 or 8")
    endif()
    if(NOT PICO_POWER_ID MATCHES "^(0[xX][0-9a-fA-F]+|[0-9]+)$")
        message(FATAL_ERROR "PICO_POWER_ID must be a decimal or hexadecimal integer")
    endif()
    # Strip decimal leading zeroes so C does not interpret an ID as octal.
    if(PICO_POWER_ID MATCHES "^[0-9]+$")
        string(REGEX REPLACE "^0+" "" _power_id "${PICO_POWER_ID}")
        if(_power_id STREQUAL "")
            set(_power_id 0)
        endif()
    else()
        set(_power_id "${PICO_POWER_ID}")
    endif()
    math(EXPR _power_id "${_power_id}")
    if(_power_id LESS 0 OR _power_id GREATER 255)
        message(FATAL_ERROR "PICO_POWER_ID must be in 0..255")
    endif()
    if(PICO_BMS_CRC_ENDIAN STREQUAL "BIG")
        set(_crc_order 1)
    elseif(PICO_BMS_CRC_ENDIAN STREQUAL "LITTLE")
        set(_crc_order 2)
    else()
        message(FATAL_ERROR "PICO_BMS_CRC_ENDIAN must be BIG or LITTLE")
    endif()
    if(PICO_POWER_STATUS_ENDIAN STREQUAL "RAW")
        set(_status_order 0)
    elseif(PICO_POWER_STATUS_ENDIAN STREQUAL "BIG")
        set(_status_order 1)
    elseif(PICO_POWER_STATUS_ENDIAN STREQUAL "LITTLE")
        set(_status_order 2)
    else()
        message(FATAL_ERROR "PICO_POWER_STATUS_ENDIAN must be RAW, BIG or LITTLE")
    endif()
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE
        App/protocol/bms_protocol.c App/protocol/power_protocol.c
        App/device_reader.c App/device_read_app.c App/transport/can_transport.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
        PICO_DEVICE_READ=1 PICO_DEVICE_KIND=${_device_kind}
        PICO_DEVICE_BITRATE=${PICO_DEVICE_BITRATE} PICO_POWER_ID=${_power_id}
        PICO_BMS_RTR_DLC=${PICO_BMS_RTR_DLC} PICO_BMS_CRC_ORDER=${_crc_order}
        PICO_POWER_STATUS_ORDER=${_status_order})
    if(PICO_APP STREQUAL "Dual")
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/dual_device_reader.c)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_DEVICE_DUAL=1)
    endif()
    if(PICO_APP STREQUAL "PowerBaud")
        set(PICO_POWER_BAUD_TARGET "" CACHE STRING "Explicit target bitrate for gated test")
        if(NOT ((PICO_DEVICE_BITRATE STREQUAL "1000000" AND PICO_POWER_BAUD_TARGET STREQUAL "500000") OR
                (PICO_DEVICE_BITRATE STREQUAL "500000" AND PICO_POWER_BAUD_TARGET STREQUAL "1000000")))
            message(FATAL_ERROR "PowerBaud requires an explicit opposite 1M/500K target")
        endif()
        option(PICO_POWER_BAUD_ALLOW_QUERY_TIMEOUTS "Explicit operator override for one-shot baud write; preserves timeout logs" OFF)
        option(PICO_POWER_BAUD_FORCE_OPERATOR "Operator-authorized one-shot write without readiness gate; still requires SWD ARM+COMMIT" OFF)
        set(PICO_POWER_BAUD_BASELINE_MS "60000" CACHE STRING "Minimum read-only baseline before explicit ARM")
        if(NOT PICO_POWER_BAUD_BASELINE_MS MATCHES "^[1-9][0-9]*$")
            message(FATAL_ERROR "PICO_POWER_BAUD_BASELINE_MS must be a positive integer")
        endif()
        target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/power_baud_test.c)
        target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
            PICO_POWER_BAUD_TEST=1 PICO_POWER_BAUD_TARGET=${PICO_POWER_BAUD_TARGET}
            POWER_BAUD_BASELINE_MS=${PICO_POWER_BAUD_BASELINE_MS}UL
            PICO_POWER_BAUD_ALLOW_QUERY_TIMEOUTS=$<BOOL:${PICO_POWER_BAUD_ALLOW_QUERY_TIMEOUTS}>
            PICO_POWER_BAUD_FORCE_OPERATOR=$<BOOL:${PICO_POWER_BAUD_FORCE_OPERATOR}>)
        message(STATUS "GATED baud test: ${PICO_DEVICE_BITRATE} -> ${PICO_POWER_BAUD_TARGET}; SWD ARM+COMMIT required; timeout_override=${PICO_POWER_BAUD_ALLOW_QUERY_TIMEOUTS}; force_operator=${PICO_POWER_BAUD_FORCE_OPERATOR}; baseline_ms=${PICO_POWER_BAUD_BASELINE_MS}")
    else()
        message(STATUS "Device reader: ${PICO_APP} ${PICO_DEVICE_BITRATE} bit/s; channel=FDCAN${PICO_CAN_CHANNEL}; read-only")
    endif()
else()
    message(FATAL_ERROR "PICO_APP must be Robot14, Bringup, BMS, Power, Dual, PowerBaud, PinLoop or Motor")
endif()
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE App)
if(PICO_APP MATCHES "^Motor")
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/protocol/robstride_spc.c
        App/vendor/robstride_spc/ported/robstride_spc_port.c
        App/vendor/robstride_spc/ported/robstride_control.c)
    message(STATUS "Motor protocol backend: RobStrideSPC d8451a4, G474 nonblocking port V1")
endif()
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_EXTERNAL_CAN=$<BOOL:${PICO_EXTERNAL_CAN}> PICO_CAN_CHANNEL=${PICO_CAN_CHANNEL})
target_compile_options(${CMAKE_PROJECT_NAME} PRIVATE -Wall -Wextra -Werror)
add_custom_command(TARGET ${CMAKE_PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:${CMAKE_PROJECT_NAME}> ${CMAKE_CURRENT_BINARY_DIR}/PICO_CAN.bin
    COMMAND ${CMAKE_OBJCOPY} -O ihex $<TARGET_FILE:${CMAKE_PROJECT_NAME}> ${CMAKE_CURRENT_BINARY_DIR}/PICO_CAN.hex)
