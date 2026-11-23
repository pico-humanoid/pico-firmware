"""Shared serial protocol and acceptance sequence for the BoardFsm bench."""
import time

STATE = "# FSM_STATE,"
REPLY = "# FSM_REPLY,"
RESULT = "# FSM_TEST_RESULT=PASS,scope=BOARD_LOGIC_ONLY"


TARGETS = {"ZERO_TORQUE", "DAMPING", "DEBUG_RESERVED"}
MODES = TARGETS | {"SELF_CHECK", "FAULT_LOCKED"}
FAULTS = {"NONE", "LOCAL_CHECK_FAILED", "SELF_CHECK_TIMEOUT", "MODE_TIMEOUT"}
MODE_NAMES = {"SELF_CHECK": "自检", "ZERO_TORQUE": "零力矩", "DAMPING": "阻尼",
              "DEBUG_RESERVED": "调试预留", "FAULT_LOCKED": "故障锁定"}
FAULT_NAMES = {"NONE": "无故障", "LOCAL_CHECK_FAILED": "板端自检失败",
               "SELF_CHECK_TIMEOUT": "自检确认超时", "MODE_TIMEOUT": "模式切换确认超时"}
VERIFY_STEPS = (
    ("自检进入零力矩", "两路模拟确认都收到，进入零力矩"),
    ("板端内置逻辑检查", "五项逻辑用例全部通过"),
    ("切换到阻尼", "先等两路确认，再进入阻尼"),
    ("返回零力矩", "两路模拟确认都收到，返回零力矩"),
    ("切换到调试预留", "两路模拟确认后，当前状态变为调试预留"),
    ("模拟漏回确认", "故意丢失第2路确认，900毫秒后锁定故障"),
    ("检查故障锁定", "锁定时拒绝切换到零力矩和调试预留"),
    ("重新自检恢复", "故障清除，两路确认后回到零力矩"),
)


def parse_state(line):
    if not line.startswith(STATE):
        return None
    fields = dict(item.split("=", 1) for item in line[len(STATE):].split(",") if "=" in item)
    if (fields.get("source") != "SIMULATED" or fields.get("state") not in MODES
            or fields.get("target") not in TARGETS or fields.get("fault") not in FAULTS
            or not all(fields.get(key) in {"0", "1"} for key in ("pending", "ack1", "ack2"))
            or not fields.get("t_ms", "").isdigit()):
        return None
    return fields


class Bench:
    def __init__(self, port, log, *, output=print, on_line=None, checkpoint=None,
                 on_command=None, on_step=None):
        self.port = port
        self.log = log
        self.output = output
        self.on_line = on_line
        self.checkpoint = checkpoint
        self.on_command = on_command
        self.on_step = on_step
        self.buffer = bytearray()
        self.discard = False
        self.last_state = None

    def read_message(self):
        if self.checkpoint:
            self.checkpoint()
        raw = self.port.readline(512)
        if not raw:
            return ""
        if len(self.buffer) + len(raw) > 512:
            self.buffer.clear()
            self.discard = True
        if not self.discard:
            self.buffer.extend(raw)
        if not raw.endswith(b"\n"):
            return ""
        message = "" if self.discard else self.buffer.decode("ascii", errors="replace").strip()
        self.buffer.clear()
        self.discard = False
        if message:
            self.last_state = parse_state(message) or self.last_state
            self.log.write(message + "\n")
            if self.on_line:
                self.on_line(message)
        return message

    def wait(self, predicate, description):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            message = self.read_message()
            if message.startswith("# FSM_TEST_RESULT=FAIL"):
                raise RuntimeError("板端内置逻辑检查未通过，详见 FSM_CASE 原始记录。")
            if message == "# FSM_REPLY,command=INVALID_LINE,result=DISCARDED":
                raise RuntimeError("串口输入行被开发板丢弃（INVALID_LINE / DISCARDED），本条指令未执行；这不是预期的故障注入。")
            if predicate(message):
                return message
        raise RuntimeError(f"等待超时（4秒）：{description}")

    def command(self, command):
        if self.checkpoint:
            self.checkpoint()
        self.log.write(f"> {command}\n")
        self.port.write((command + "\n").encode("ascii"))
        if self.on_command:
            self.on_command(command)
        else:
            self.output(f"> {command}")

    def state(self, mode, acks, *, target=None, pending=0, fault="NONE"):
        expected = {
            "source": "SIMULATED", "state": mode, "target": target or mode,
            "pending": str(pending), "ack1": str(acks & 1),
            "ack2": str((acks >> 1) & 1), "fault": fault,
        }

        def matches(line):
            fields = parse_state(line)
            return bool(fields) and all(fields.get(key) == value for key, value in expected.items())

        description = (f"当前状态={MODE_NAMES[mode]}，目标={MODE_NAMES[target or mode]}，"
                       f"等待确认={'是' if pending else '否'}，"
                       f"模拟电机1确认={acks & 1}，模拟电机2确认={(acks >> 1) & 1}，"
                       f"故障={FAULT_NAMES[fault]}")
        self.wait(matches, description)

    def expect_reply(self, command, result):
        target = f"{REPLY}command={command},result={result}"
        def matches(line):
            if command == "DEBUG" and line == f"{REPLY}command=DEBUG,result=DEBUG_RESERVED":
                raise RuntimeError("开发板仍是旧固件，DEBUG 只返回标记。请编译并烧录新版 BoardFsm，再验证调试预留状态。")
            return line == target

        self.wait(matches, f"开发板对 {command} 的答复 {result}")

    def reset(self):
        self.command("RESET")
        accepted = False

        def started(line):
            nonlocal accepted
            if line == f"{REPLY}command=RESET,result=ACCEPTED":
                accepted = True
            elif line == f"{REPLY}command=RESET,result=BUSY":
                raise RuntimeError("开发板拒绝了 RESET，上一条状态切换仍在等待确认。")
            state = parse_state(line)
            if accepted and state and state["fault"] == "LOCAL_CHECK_FAILED":
                raise RuntimeError("重新自检失败，板端报告本地检查失败。")
            return (state and state["state"] == "SELF_CHECK" and state["target"] == "ZERO_TORQUE"
                    and state["pending"] == "1" and state["fault"] == "NONE")

        def complete(line):
            state = parse_state(line)
            if state and state["state"] == "FAULT_LOCKED":
                raise RuntimeError("重新自检失败，板端报告" + FAULT_NAMES[state["fault"]] + "。")
            return (state and state["state"] == state["target"] == "ZERO_TORQUE"
                    and state["pending"] == "0" and state["fault"] == "NONE"
                    and state["ack1"] == state["ack2"] == "1")

        # Current firmware also replies ACCEPTED. The state frames support older firmware.
        self.wait(started, "发送 RESET 后未观察到自检开始，请确认已烧录新版 BoardFsm 固件。")
        self.wait(complete, "自检已开始，等待两路确认并恢复零力矩。")

    def observe_led(self, mode, announce):
        scheme = (self.last_state or {}).get("led_scheme")
        seconds = {"COUNTED": 3, "SIMPLE": 2, "GROUPED": 3}.get(scheme, 0)
        if announce is None or not seconds:
            return
        announce(self.last_state, seconds)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            state = parse_state(self.read_message())
            if state and (state["state"] != mode or state["pending"] != "0"):
                raise RuntimeError(f"观察 LD2 期间离开了{MODE_NAMES[mode]}状态。")

    def step(self, index, status, detail=""):
        if self.on_step:
            self.on_step(index, status, detail)
        else:
            self.output(f"[步骤 {index}/8] {VERIFY_STEPS[index - 1][0]} · {status} {detail}")


def _verify_sequence(bench, on_observe):
    # Passive identification before sending any input to the selected port.
    bench.step(1, "RUNNING")
    bench.wait(parse_state,
               "识别 BoardFsm 状态。请检查串口、固件和115200波特率。")
    bench.reset()
    bench.step(1, "PASS")
    bench.step(2, "RUNNING")
    bench.command("TEST")
    bench.wait(lambda line: line == RESULT, "板端内置逻辑检查全部通过")
    bench.observe_led("ZERO_TORQUE", on_observe)
    bench.step(2, "PASS")
    bench.step(3, "RUNNING")
    bench.command("DAMP")
    bench.expect_reply("DAMP", "ACCEPTED")
    bench.state("ZERO_TORQUE", 1, target="DAMPING", pending=1)
    bench.state("DAMPING", 3)
    bench.observe_led("DAMPING", on_observe)
    bench.step(3, "PASS")
    bench.step(4, "RUNNING")
    bench.command("ZERO")
    bench.expect_reply("ZERO", "ACCEPTED")
    bench.state("ZERO_TORQUE", 3)
    bench.step(4, "PASS")
    bench.step(5, "RUNNING")
    bench.command("DEBUG")
    bench.expect_reply("DEBUG", "ACCEPTED")
    bench.state("ZERO_TORQUE", 1, target="DEBUG_RESERVED", pending=1)
    bench.state("DEBUG_RESERVED", 3)
    bench.observe_led("DEBUG_RESERVED", on_observe)
    bench.step(5, "PASS")
    bench.step(6, "RUNNING")
    bench.command("MISS2")
    bench.expect_reply("MISS2", "ARMED_FOR_NEXT_TRANSITION")
    bench.command("DAMP")
    bench.expect_reply("DAMP", "ACCEPTED")
    bench.state("FAULT_LOCKED", 1, target="DAMPING", fault="MODE_TIMEOUT")
    bench.step(6, "PASS")
    bench.step(7, "RUNNING")
    bench.command("ZERO")
    bench.expect_reply("ZERO", "FAULT_LOCKED")
    # Consume the accompanying state after each refused request.
    bench.state("FAULT_LOCKED", 1, target="DAMPING", fault="MODE_TIMEOUT")
    bench.command("DEBUG")
    bench.expect_reply("DEBUG", "FAULT_LOCKED")
    bench.state("FAULT_LOCKED", 1, target="DAMPING", fault="MODE_TIMEOUT")
    bench.observe_led("FAULT_LOCKED", on_observe)
    bench.step(7, "PASS")
    bench.step(8, "RUNNING")
    bench.reset()
    bench.step(8, "PASS")


def verify(bench, *, on_observe=None):
    """Run the acceptance sequence and mark the exact failed step."""
    current = 1
    original = bench.on_step

    def track(index, status, detail):
        nonlocal current
        current = index
        if original:
            original(index, status, detail)
        else:
            bench.output(f"[步骤 {index}/8] {VERIFY_STEPS[index - 1][0]} · {status} {detail}")

    bench.on_step = track
    try:
        _verify_sequence(bench, on_observe)
    except RuntimeError as exc:
        bench.step(current, "FAIL", str(exc))
        raise
    finally:
        bench.on_step = original
