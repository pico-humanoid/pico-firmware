#include "board_fsm_app.h"
#include "board_fsm.h"
#include "board_fsm_checks.h"

#include <stdio.h>
#include <string.h>

static UART_HandleTypeDef *serial;
static BoardFsm fsm;
static uint8_t drop_next;
static uint8_t drop_active;
static bool built_in_checks_ok;
static uint32_t last_status_ms;
static char input[24];
static size_t input_used;
static bool discard_line;

static void update_led(uint32_t now);

// The IRQ only stores bytes. The main loop parses lines and sends replies.
enum { RX_CAPACITY = 128 };
static volatile uint8_t rx_bytes[RX_CAPACITY];
static volatile unsigned rx_head;
static volatile unsigned rx_tail;
static volatile bool rx_overflow;

void BoardFsmApp_UartIrq(void)
{
    const uint32_t flags = serial->Instance->ISR;
    const uint32_t errors = flags & (UART_FLAG_ORE | UART_FLAG_FE | UART_FLAG_NE);
    if (errors == 0U && (flags & UART_FLAG_RXNE) == 0U) return;

    uint8_t byte = 0; // NUL marks a receive error and invalidates the current line.
    if ((flags & UART_FLAG_RXNE) != 0U) {
        const uint8_t received = (uint8_t)serial->Instance->RDR;
        if (errors == 0U) byte = received;
    }
    if (errors != 0U) {
        __HAL_UART_CLEAR_FLAG(serial, UART_CLEAR_OREF | UART_CLEAR_FEF | UART_CLEAR_NEF);
    }

    const unsigned next = (rx_head + 1U) % RX_CAPACITY;
    if (next == rx_tail) {
        rx_overflow = true;
    } else {
        rx_bytes[rx_head] = byte;
        rx_head = next;
    }
}

static void send(const char *text)
{
    (void)HAL_UART_Transmit(serial, (const uint8_t *)text, (uint16_t)strlen(text), 40U);
}

static void status(void)
{
    char line[220];
    (void)snprintf(line, sizeof line,
        "# FSM_STATE,t_ms=%lu,source=SIMULATED,state=%s,target=%s,pending=%u,"
        "ack1=%u,ack2=%u,fault=%s,drop_next=%u,led_scheme=COUNTED\r\n",
        (unsigned long)HAL_GetTick(), BoardFsm_ModeName(fsm.state),
        BoardFsm_ModeName(fsm.target), (unsigned)fsm.pending,
        (unsigned)((fsm.acks & 1U) != 0U), (unsigned)((fsm.acks & 2U) != 0U),
        BoardFsm_FaultName(fsm.fault), (unsigned)drop_next);
    send(line);
}

static bool board_check(void)
{
    return built_in_checks_ok &&
        serial->Instance == LPUART1 &&
        serial->Init.BaudRate == 115200U &&
        serial->Init.WordLength == UART_WORDLENGTH_8B &&
        serial->Init.Parity == UART_PARITY_NONE &&
        serial->Init.StopBits == UART_STOPBITS_1 &&
        serial->Init.Mode == UART_MODE_TX_RX;
}

static void begin(uint32_t now)
{
    drop_active = drop_next;
    drop_next = 0;
    BoardFsm_Begin(&fsm, now, board_check());
    update_led(now);
    status();
}

static void result(const char *name, int passed)
{
    char line[110];
    (void)snprintf(line, sizeof line, "# FSM_CASE,%s,%s\r\n", name, passed ? "PASS" : "FAIL");
    send(line);
}

static bool run_checks(void)
{
    const unsigned failures = BoardFsm_RunChecks(result);
    send(failures == 0 ? "# FSM_TEST_RESULT=PASS,scope=BOARD_LOGIC_ONLY\r\n"
                       : "# FSM_TEST_RESULT=FAIL,scope=BOARD_LOGIC_ONLY\r\n");
    return failures == 0;
}

static const char *reply_name(BoardFsmReply reply)
{
    switch (reply) {
        case BOARD_FSM_ACCEPTED: return "ACCEPTED";
        case BOARD_FSM_ALREADY: return "ALREADY";
        case BOARD_FSM_BUSY: return "BUSY";
        case BOARD_FSM_LOCKED: return "FAULT_LOCKED";
        case BOARD_FSM_BAD_MODE: return "BAD_MODE";
    }
    return "UNKNOWN";
}

static void reply(const char *command, const char *reason)
{
    char line[100];
    (void)snprintf(line, sizeof line, "# FSM_REPLY,command=%s,result=%s\r\n", command, reason);
    send(line);
}

static void help(void)
{
    send("# FSM_COMMANDS: STATUS | ZERO | DAMP | DEBUG | MISS1 | MISS2 | RESET | TEST | HELP\r\n");
}

static void command(uint32_t now)
{
    if (strcmp(input, "STATUS") == 0) {
        status();
    } else if (strcmp(input, "HELP") == 0) {
        help();
    } else if (strcmp(input, "TEST") == 0) {
        if (fsm.pending) reply(input, "BUSY");
        else (void)run_checks();
    } else if (strcmp(input, "RESET") == 0) {
        if (fsm.pending) reply(input, "BUSY");
        else {
            reply(input, "ACCEPTED");
            begin(now);
        }
    } else if (strcmp(input, "MISS1") == 0 || strcmp(input, "MISS2") == 0) {
        if (fsm.pending || fsm.state == BOARD_FSM_FAULT) {
            reply(input, fsm.pending ? "BUSY" : "FAULT_LOCKED");
        } else {
            drop_next = input[4] == '1' ? 1U : 2U;
            reply(input, "ARMED_FOR_NEXT_TRANSITION");
        }
    } else {
        BoardFsmMode mode;
        if (strcmp(input, "ZERO") == 0) mode = BOARD_FSM_ZERO_TORQUE;
        else if (strcmp(input, "DAMP") == 0) mode = BOARD_FSM_DAMPING;
        else if (strcmp(input, "DEBUG") == 0) mode = BOARD_FSM_DEBUG_RESERVED;
        else {
            reply("UNKNOWN", "BAD_COMMAND");
            return;
        }
        const BoardFsmReply response = BoardFsm_Request(&fsm, mode, now);
        if (response == BOARD_FSM_ACCEPTED) {
            drop_active = drop_next;
            drop_next = 0;
            update_led(now);
        }
        reply(input, reply_name(response));
        status();
    }
}

static void receive(void)
{
    for (unsigned count = 0; count < sizeof input; ++count) {
        const uint32_t primask = __get_PRIMASK();
        __disable_irq();
        if (rx_overflow) {
            // A gap in the queue makes any incomplete command unsafe to interpret.
            rx_tail = rx_head;
            rx_overflow = false;
            input_used = 0;
            discard_line = true;
        }
        if (rx_tail == rx_head) {
            __set_PRIMASK(primask);
            return;
        }
        const uint8_t ch = rx_bytes[rx_tail];
        rx_tail = (rx_tail + 1U) % RX_CAPACITY;
        __set_PRIMASK(primask);
        if (ch == '\r' || ch == '\n') {
            if (discard_line) reply("INVALID_LINE", "DISCARDED");
            else if (input_used != 0) {
                input[input_used] = '\0';
                command(HAL_GetTick());
            }
            discard_line = false;
            input_used = 0;
            // Give the state update priority before handling another command.
            return;
        }
        if (discard_line) continue;
        if ((ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9')) {
            if (input_used < sizeof input - 1U) input[input_used++] = (char)ch;
            else discard_line = true;
        } else {
            discard_line = true;
        }
    }
}

static void update_led(uint32_t now)
{
    enum { ON_MS = 200, GAP_MS = 200, GROUP_PAUSE_MS = 1000 };
    static unsigned previous_count;
    static uint32_t group_start_ms;

    unsigned count = 0;
    if (!fsm.pending) {
        if (fsm.state == BOARD_FSM_ZERO_TORQUE) count = 1;
        else if (fsm.state == BOARD_FSM_DAMPING) count = 2;
        else if (fsm.state == BOARD_FSM_DEBUG_RESERVED) count = 3;
    }
    if (count != previous_count) {
        previous_count = count;
        group_start_ms = now;
    }

    bool on = false;
    if (count != 0U) {
        const uint32_t slot_ms = ON_MS + GAP_MS;
        const uint32_t end_of_flashes = (count - 1U) * slot_ms + ON_MS;
        const uint32_t phase = (now - group_start_ms) % (end_of_flashes + GROUP_PAUSE_MS);
        group_start_ms = now - phase;
        on = phase < end_of_flashes && phase % slot_ms < ON_MS;
    }
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_5, on ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

void BoardFsmApp_Init(UART_HandleTypeDef *uart)
{
    serial = uart;
    __HAL_UART_SEND_REQ(serial, UART_RXDATA_FLUSH_REQUEST);
    __HAL_UART_CLEAR_FLAG(serial, UART_CLEAR_OREF | UART_CLEAR_FEF | UART_CLEAR_NEF);
    HAL_NVIC_SetPriority(LPUART1_IRQn, 0, 0);
    __HAL_UART_ENABLE_IT(serial, UART_IT_ERR);
    __HAL_UART_ENABLE_IT(serial, UART_IT_RXNE);
    HAL_NVIC_EnableIRQ(LPUART1_IRQn);
    send("# PICO_BOARD_FSM=1,source=SIMULATED,can=OFF,motor_commands=OFF,uart_rx=IRQ,led_scheme=COUNTED\r\n");
    help();
    built_in_checks_ok = run_checks();
    last_status_ms = HAL_GetTick();
    begin(last_status_ms);
}

void BoardFsmApp_Step(void)
{
    const uint32_t now = HAL_GetTick();
    const BoardFsm before = fsm;
    const uint8_t simulated = BoardFsm_SimulatedAcks(now - fsm.started_ms, drop_active);
    BoardFsm_Step(&fsm, now, simulated);
    update_led(now);
    if (fsm.state != before.state || fsm.acks != before.acks || now - last_status_ms >= 1000U) {
        last_status_ms = now;
        status();
    }
    receive();
}
