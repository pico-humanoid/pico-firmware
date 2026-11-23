#include "mf7_app.h"
#include "mf7_control.h"
#include "mf7_can.h"
#include <stdio.h>
#include <string.h>

enum { RX_CAP = 128, TX_CAP = 1536 };
static Mf7 control;
static UART_HandleTypeDef *serial;
static FDCAN_HandleTypeDef can2;
static uint32_t cancel_generation, last_state, last_motor;
static unsigned motor_cursor;
static bool can_ready;
static volatile uint8_t rx[RX_CAP];
static volatile unsigned rx_write, rx_read;
static volatile bool rx_error;
static char command[16], tx[TX_CAP];
static unsigned command_used, tx_write, tx_read;
static bool discard;

void Mf7App_UartIrq(void) {
    const uint32_t status = serial->Instance->ISR;
    const uint32_t error = status & (UART_FLAG_ORE | UART_FLAG_FE | UART_FLAG_NE);
    uint8_t byte = 0;
    if (status & UART_FLAG_RXNE) byte = (uint8_t)serial->Instance->RDR;
    if (error) {
        __HAL_UART_CLEAR_FLAG(serial, UART_CLEAR_OREF | UART_CLEAR_FEF | UART_CLEAR_NEF);
        rx_error = true;
        return;
    }
    if (!(status & UART_FLAG_RXNE)) return;
    const unsigned next = (rx_write + 1U) % RX_CAP;
    if (next == rx_read) {
        rx_error = true;
        return;
    }
    rx[rx_write] = byte;
    rx_write = next;
}

static void queue_text(const char *text);

static void dispatch(uint32_t now) {
    if (strncmp(command, "KD", 2) != 0) {
        Mf7_Command(&control, command, now);
        return;
    }
    unsigned milli = 0;
    const char *result = "INVALID_FORMAT";
    if (command_used == 5U && command[2] >= '0' && command[2] <= '9' &&
        command[3] >= '0' && command[3] <= '9' && command[4] >= '0' && command[4] <= '9') {
        milli = (unsigned)(command[2]-'0') * 100U + (unsigned)(command[3]-'0') * 10U +
                (unsigned)(command[4]-'0');
        const Mf7KdResult reply = Mf7_SetKd(&control, milli, now);
        result = reply == MF7_KD_ACCEPTED ? "ACCEPTED" :
                 reply == MF7_KD_OUT_OF_RANGE ? "OUT_OF_RANGE" : "NOT_READY";
    }
    char line[100];
    (void)snprintf(line, sizeof line,
        "# MF7_KD,requested_milli=%u,set_milli=%u,result=%s\r\n",
        milli, (unsigned)control.kd_milli, result);
    queue_text(line);
}

static void uart_input(uint32_t now) {
    for (unsigned i = 0; i < 20U; ++i) {
        const uint32_t mask = __get_PRIMASK();
        __disable_irq();
        const bool error = rx_error;
        unsigned head = rx_write;
        if (error) {
            rx_error = false;
            rx_read = head;
        }
        const bool has_byte = rx_read != head;
        const uint8_t c = has_byte ? rx[rx_read] : 0;
        if (has_byte) rx_read = (rx_read + 1U) % RX_CAP;
        __set_PRIMASK(mask);
        if (error) {
            discard = true;
            command_used = 0;
            Mf7_Halt(&control, now, "UART_ERROR");
        }
        if (!has_byte) return;
        if (c == '\r' || c == '\n') {
            if (command_used && !discard) {
                command[command_used] = '\0';
                dispatch(now);
            }
            command_used = 0;
            discard = false;
        } else if (((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) &&
                   command_used + 1U < sizeof command) {
            command[command_used++] = (char)c;
        } else {
            discard = true;
        }
    }
}

static void queue_text(const char *text) {
    const size_t n = strlen(text);
    const unsigned used = (tx_write + TX_CAP - tx_read) % TX_CAP;
    if (n >= TX_CAP - used) return; // Never block CAN safety on diagnostics.
    for (size_t i = 0; i < n; ++i) {
        tx[tx_write] = text[i];
        tx_write = (tx_write + 1U) % TX_CAP;
    }
}

static void uart_output(void) {
    if (tx_read != tx_write && (serial->Instance->ISR & UART_FLAG_TXE)) {
        serial->Instance->TDR = (uint8_t)tx[tx_read];
        tx_read = (tx_read + 1U) % TX_CAP;
    }
}

static void cancel_if_changed(void) {
    if (cancel_generation != control.net.stop_generation) {
        cancel_generation = control.net.stop_generation;
        Mf7Can_Cancel(MF7_BUS);
    }
}

static bool send(void *ctx, uint8_t bus, const CanFrame *frame, uint32_t now) {
    (void)ctx;
    (void)now;
    if (bus != MF7_BUS || !can_ready) return false;
    cancel_if_changed(); // Also covers a protect-stop raised inside MotorNetwork_Step.
    return Mf7Can_Send(bus, frame);
}

static void emit_state(uint32_t now) {
    char buf[256];
    (void)snprintf(buf, sizeof buf,
        "# MF7_STATE,state=%s,source=HARDWARE,ready=%u,active=%u,stopped=%u,"
        "reason=%s,target=%s,uid_count=%u,can_fault=0x%lX,t_ms=%lu,kd_set_milli=%u\r\n",
        Mf7_Name(control.state), Mf7_Ready(&control, now), Mf7_Active(&control),
        Mf7_Stopped(&control), control.reason, Mf7_Name(control.target), control.uid_count,
        (unsigned long)Mf7Can_Faults(MF7_BUS), (unsigned long)now, (unsigned)control.kd_milli);
    queue_text(buf);
}

static void emit_motor(uint32_t now) {
    const unsigned idx = motor_cursor++ % MF7_COUNT;
    const RobotMotor *m = &control.net.motors[idx];
    if (m->phase != MOTOR_ACTIVE || !m->feedback_seen ||
        now - m->feedback_ms > ROBOT_FEEDBACK_TIMEOUT_MS) return;
    char buf[160];
    const float estimated = -m->command.kd * m->feedback.velocity;
    (void)snprintf(buf, sizeof buf,
        "# MF7_MOTOR,bus=2,id=%u,vel_mrad_s=%ld,torque_mNm=%ld,estimate_mNm=%ld,kd_milli=%ld,t_ms=%lu\r\n",
        idx + 1U, (long)(m->feedback.velocity * 1000.0f), (long)(m->feedback.torque * 1000.0f),
        (long)(estimated * 1000.0f), (long)(m->command.kd * 1000.0f), (unsigned long)m->feedback_ms);
    queue_text(buf);
}

void Mf7App_Init(UART_HandleTypeDef *uart) {
    serial = uart;
    Mf7_Init(&control);
    can_ready = Mf7Can_Init(MF7_BUS, &can2, ROBOT_HOST_ID);
    if (!can_ready) Mf7_Halt(&control, HAL_GetTick(), "CAN_FAULT");
    __HAL_UART_SEND_REQ(serial, UART_RXDATA_FLUSH_REQUEST);
    __HAL_UART_CLEAR_FLAG(serial, UART_CLEAR_OREF | UART_CLEAR_FEF | UART_CLEAR_NEF);
    HAL_NVIC_SetPriority(LPUART1_IRQn, 1, 0);
    __HAL_UART_ENABLE_IT(serial, UART_IT_ERR);
    __HAL_UART_ENABLE_IT(serial, UART_IT_RXNE);
    HAL_NVIC_EnableIRQ(LPUART1_IRQn);
    queue_text("# PICO_MOTOR_FSM7=1,source=HARDWARE,bus=2,bitrate=1000000,count=7\r\n");
    emit_state(HAL_GetTick());
}

static void led(uint32_t now) {
    static unsigned previous;
    static uint32_t start;
    unsigned flashes = 0;
    if (control.target == control.state) {
        if (control.state == MF7_ZERO_TORQUE) flashes = 1;
        else if (control.state == MF7_DAMPING) flashes = 2;
        else if (control.state == MF7_DEBUG_RESERVED) flashes = 3;
    }
    if (flashes != previous) {
        previous = flashes;
        start = now;
    }
    bool on = false;
    if (flashes) {
        const uint32_t end = 400U * (flashes - 1U) + 200U;
        const uint32_t phase = (now - start) % (end + 1000U);
        start = now - phase;
        on = phase < end && phase % 400U < 200U;
    }
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_5, on ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

void Mf7App_Step(void) {
    const uint32_t now = HAL_GetTick();
    const Mf7State before = control.state;
    uart_input(now);
    cancel_if_changed();
    if (can_ready) {
        CanFrame f;
        for (unsigned i = 0; i < 12U && Mf7Can_Poll(MF7_BUS, &f); ++i) Mf7_OnFrame(&control, &f);
        if (!Mf7Can_Healthy(MF7_BUS))
            Mf7_Halt(&control, now, "CAN_FAULT");
        cancel_if_changed();
        Mf7_Step(&control, now, send, NULL);
    }
    led(now);
    if (before != control.state || now - last_state >= 200U) {
        last_state = now;
        emit_state(now);
    }
    if (now - last_motor >= 35U) {
        last_motor = now;
        emit_motor(now);
    }
    uart_output();
}
