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
set(PICO_APP "Bringup" CACHE STRING "Application: Bringup, BMS, Power, Dual, PowerBaud, PinLoop")
set_property(CACHE PICO_APP PROPERTY STRINGS Bringup BMS Power Dual PowerBaud PinLoop)
if(PICO_APP STREQUAL "PinLoop")
    # Test-only: PA12 output, PA11 input; FDCAN is deinitialized; no CAN traffic.
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/pin_loop_test.c)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_PIN_LOOP_TEST=1)
    message(STATUS "Pin loop test: PA12 out, PA11 in; FDCAN deinit; no CAN")
elseif(PICO_APP STREQUAL "Bringup")
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE App/can_bringup.c)
elseif(PICO_APP STREQUAL "BMS" OR PICO_APP STREQUAL "Power" OR PICO_APP STREQUAL "PowerBaud" OR PICO_APP STREQUAL "Dual")
    if(PICO_APP STREQUAL "BMS" OR PICO_APP STREQUAL "Dual")
        set(_device_kind 0)
        set(_default_bitrate 500000)
    else()
        set(_device_kind 1)
        set(_default_bitrate 1000000)
    endif()
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
        message(FATAL_ERROR "Dual requires both devices on the same FDCAN1 bus at 500000 bit/s")
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
        message(STATUS "Device reader: ${PICO_APP} ${PICO_DEVICE_BITRATE} bit/s; read-only")
    endif()
else()
    message(FATAL_ERROR "PICO_APP must be Bringup, BMS, Power, Dual, PowerBaud or PinLoop")
endif()
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE App)
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE PICO_EXTERNAL_CAN=$<BOOL:${PICO_EXTERNAL_CAN}>)
target_compile_options(${CMAKE_PROJECT_NAME} PRIVATE -Wall -Wextra -Werror)
add_custom_command(TARGET ${CMAKE_PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:${CMAKE_PROJECT_NAME}> ${CMAKE_CURRENT_BINARY_DIR}/PICO_CAN.bin
    COMMAND ${CMAKE_OBJCOPY} -O ihex $<TARGET_FILE:${CMAKE_PROJECT_NAME}> ${CMAKE_CURRENT_BINARY_DIR}/PICO_CAN.hex)
