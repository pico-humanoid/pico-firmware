"""Chinese explanations of real BoardFsm messages, shared by GUI and CLI."""
from datetime import datetime
import time

from board_fsm_protocol import FAULT_NAMES, MODE_NAMES, REPLY, VERIFY_STEPS, parse_state

COMMANDS = {
    "RESET": "重新执行自检，检查后回到零力矩",
    "TEST": "运行板端五项内置逻辑检查",
    "DAMP": "请求切换到阻尼",
    "ZERO": "请求切换到零力矩",
    "DEBUG": "请求切换到调试预留；本版只验证切换",
    "MISS1": "让模拟电机1在下一次切换时故意不回确认",
    "MISS2": "让模拟电机2在下一次切换时故意不回确认",
    "STATUS": "读取当前状态", "HELP": "读取支持的指令",
}
REPLIES = {
    "ACCEPTED": "已受理，仍需等待两路模拟确认才能完成切换",
    "ALREADY": "已经处于请求的模式，无需切换",
    "BUSY": "当前仍在等待确认，本条请求被拒绝",
    "FAULT_LOCKED": "故障已锁定，本条请求被拒绝；需要重新自检",
    "DEBUG_RESERVED": "旧版只返回预留标记，状态未切换；请更新固件",
    "ARMED_FOR_NEXT_TRANSITION": "已设置一次漏回确认；仅影响下一次切换或自检",
    "BAD_MODE": "不支持此目标模式，请求被拒绝",
    "BAD_COMMAND": "无法识别指令，请求被拒绝",
    "DISCARDED": "串口输入行无效或接收溢出，该行已丢弃",
}
CASES = {
    "self_check_requires_both_acks": "自检必须等两路确认都收到才能结束",
    "zero_damping_zero_and_busy_guard": "零力矩与阻尼往返切换，切换中拒绝新请求",
    "missing_motor2_locks_and_rejects_late_ack": "第2路漏回确认后锁定故障，迟到确认不能解锁",
    "failed_self_check_and_manual_recovery": "自检失败进入故障，重新自检后可恢复",
    "debug_round_trip_and_tick_wrap": "调试预留可进入和退出，计时器回绕时切换仍正常",
    "debug_reserved_and_tick_wrap": "旧版用例仅检查预留标记和计时器回绕",
}

def led_text(state):
    mode = state["state"]
    waiting = state["pending"] == "1"
    if state.get("led_scheme") == "COUNTED":
        flashes = {"ZERO_TORQUE": 1, "DAMPING": 2, "DEBUG_RESERVED": 3}.get(mode, 0)
        return f"每组闪 {flashes} 下" if not waiting and flashes else "熄灭"
    if state.get("led_scheme") == "SIMPLE":
        return "闪烁" if not waiting and mode in ("ZERO_TORQUE", "DAMPING", "DEBUG_RESERVED") else "熄灭"
    if state.get("led_scheme") == "GROUPED":
        if mode == "FAULT_LOCKED":
            return "三短一长，循环"
        if mode == "SELF_CHECK":
            return "自检期间点亮"
        if waiting:
            return "切换等待期间熄灭"
        return {"ZERO_TORQUE": "一短一长，循环", "DAMPING": "两短一长，循环"}.get(mode, "规则未知")
    if mode == "FAULT_LOCKED":
        return "快闪"
    if waiting:
        return "按0.25秒亮灭"
    return "常亮" if mode == "ZERO_TORQUE" else "慢闪"


LEGEND = """这里验证的是开发板上的状态机逻辑。电机1、2都是固件模拟的对象，CAN关闭。

中文日志的标记
[电脑发送] 电脑通过USB串口发出了什么请求。
[板端答复] 开发板是否受理请求。ACCEPTED只表示受理，尚未完成切换。
[等待确认] 当前模式还没切换成功，需要两路模拟反馈全部确认。
[状态到达] 板端已经上报指定状态。本条记录本身不代表整套实验通过。
[状态心跳] 状态未变，板端仍在周期上报。中文日志约10秒记录一次，原始报文保留每条。
[逻辑用例] 固件内部的单项程序检查。PASS只表示这一项通过。
[内置检查] 五项板端逻辑检查的汇总，不代表整套串口验证通过。
[故障注入] 一键验证主动安排漏回确认，用来检查保护功能。
[观察灯光] 一键验证短暂停留，方便观察 LD2 是否闪烁。状态以串口记录为准。
[预期保护] 在指定故障测试中看到的超时锁定或拒绝请求；需完成本步骤才算通过。
[异常报警] 测试预期之外的故障、报文异常或拒绝请求，需要检查。
[步骤开始 / 步骤通过 / 步骤失败] 对应上方8项验收表。
[整体验证通过] 8项验收全部通过，最终重新自检回到零力矩。
[整体验证失败] 至少一项未满足；查看失败步骤，后续步骤没有执行。

原始报文的开头
# 是开发板输出的日志前缀，不表示错误；> 是电脑发送的指令。
PICO_BOARD_FSM  固件身份。source=SIMULATED表示模拟反馈，can=OFF表示CAN关闭，uart_rx=IRQ表示新版串口中断接收。
FSM_COMMANDS  支持的串口指令列表。
FSM_STATE  开发板当前状态和确认情况，每秒周期上报，也会在变化时立即上报。
FSM_REPLY  开发板对某条指令的答复，command为指令，result为答复代码。
FSM_CASE  固件内部单项逻辑用例，最后的PASS/FAIL为该项结果。
FSM_TEST_RESULT  板端内置检查汇总。scope=BOARD_LOGIC_ONLY表示仅检查程序逻辑。
BOARD_FSM_SERIAL_RESULT  电脑执行完整串口验收后的最终结果。

FSM_STATE字段逐项解释
t_ms  开发板上电后的毫秒数。1000毫秒=1秒；这是板端计时，不是电脑时间。
source=SIMULATED  两路电机确认由固件模拟，不是实体电机反馈。
state  当前状态。SELF_CHECK自检，ZERO_TORQUE零力矩，DAMPING阻尼，DEBUG_RESERVED调试预留，FAULT_LOCKED故障锁定。
target  本次请求要到达的状态。与state不同，表示尚未到达或因故障未能到达。
pending=1  正在等确认。pending=0表示当前不再等待，可能已完成，也可能已故障锁定。
ack1 / ack2  模拟电机1 / 2对此次请求的确认，1=已收到，0=尚未收到。
fault=NONE  无故障。MODE_TIMEOUT为模式切换确认超时（900毫秒），
SELF_CHECK_TIMEOUT为自检确认超时，LOCAL_CHECK_FAILED为板端本地检查失败。
drop_next  下一次故意漏回哪路确认，0=不丢，1=电机1，2=电机2。开始切换后清零，
所以drop_next=0不代表本次故障注入已经结束。

板载用户灯 LD2（PA5）
led_scheme=COUNTED：零力矩每组闪 1 下，阻尼 2 下，调试预留 3 下。
每下亮 0.2 秒，组内间隔 0.2 秒；每组闪完停 1 秒，再重复。
自检、等待切换确认和故障锁定期间熄灭；界面会显示具体状态。
旧日志可能带 led_scheme=SIMPLE、GROUPED 或不含该字段，仍按对应固件解释。
"""


class FsmReport:
    def __init__(self, log, output=print, on_progress=None):
        self.log, self.output, self.on_progress = log, output, on_progress
        self.previous = None
        self.last_heartbeat = 0
        self.step_index = 0
        self.running = False
        self.completed = set()

    def emit(self, label, text):
        line = f"{datetime.now():%H:%M:%S.%f}"[:-3] + f" [{label}] {text}"
        self.log.write(line + "\n")
        self.output(line)

    def start(self):
        self.emit("实验说明", "仅验证开发板状态机；两路电机确认均为模拟，CAN关闭。")
        self.emit("阅读提示", "先看标记，再看内容。电脑时间在行首；板端运行时间写在状态记录中。")

    @property
    def expecting_fault(self):
        return self.running and self.step_index in (6, 7, 8)

    def command(self, command):
        self.emit("故障注入" if command in ("MISS1", "MISS2") else "电脑发送",
                  f"{command} → {COMMANDS.get(command, '未知指令')}。")

    def step(self, index, status, detail=""):
        if index == 1 and status == "RUNNING":
            self.completed.clear()
            self.running = True
        self.step_index = index
        if status == "PASS":
            self.completed.add(index)
        elif status == "FAIL":
            self.running = False
        name, expected = VERIFY_STEPS[index - 1]
        label = {"RUNNING": "步骤开始", "PASS": "步骤通过", "FAIL": "步骤失败"}[status]
        self.emit(label, f"{index}/8 {name}。" + (detail or expected) + "。")
        if self.on_progress:
            self.on_progress(index, status, detail)

    def finish(self, outcome, detail=""):
        self.running = False
        passed = outcome == "PASS" and len(self.completed) == len(VERIFY_STEPS)
        if passed:
            self.emit("整体验证通过", "8/8项通过；最终回到零力矩，两路模拟确认均收到。仅证明单板状态机逻辑通过。")
        else:
            self.emit("整体验证失败", detail or f"本轮已通过{len(self.completed)}/8项，请检查未通过的步骤。")

    def receive(self, line):
        state = parse_state(line)
        if state:
            self._state(state)
            return
        if line.startswith("# FSM_STATE,"):
            self.emit("异常报警", "状态报文缺少必要字段或字段值无效，未更新状态，详见原始报文。")
        elif line.startswith(REPLY):
            values = dict(p.split("=", 1) for p in line[len(REPLY):].split(",") if "=" in p)
            command, result = values.get("command", "?"), values.get("result", "?")
            label = "板端答复"
            if result == "FAULT_LOCKED" and self.expecting_fault:
                label = "预期保护"
            elif result in ("FAULT_LOCKED", "BAD_MODE", "BAD_COMMAND", "DISCARDED", "BUSY"):
                label = "异常报警"
            explanation = ("已收到重新自检指令，接下来检查自检状态和两路模拟确认"
                           if (command, result) == ("RESET", "ACCEPTED")
                           else REPLIES.get(result, "未知答复代码，请查看原始报文"))
            self.emit(label, f"{command} → {result}：{explanation}。")
        elif line.startswith("# FSM_CASE,"):
            parts = line.split(",")
            if len(parts) == 3:
                self.emit("逻辑用例" if parts[2] == "PASS" else "异常报警",
                          f"{'通过' if parts[2] == 'PASS' else '未通过'} · {CASES.get(parts[1], parts[1])}。")
            else:
                self.emit("异常报警", "逻辑用例报文格式异常，详见原始报文。")
        elif line.startswith("# FSM_TEST_RESULT="):
            passed = line.startswith("# FSM_TEST_RESULT=PASS,")
            self.emit("内置检查" if passed else "异常报警",
                      ("五项内置逻辑用例通过" if passed else "板端内置逻辑检查未通过")
                      + "；这不是整套串口验证的最终结果。")
        elif line.startswith("# PICO_BOARD_FSM="):
            description = "收到BoardFsm启动标记，反馈为模拟，CAN关闭，电机命令关闭。"
            if "uart_rx=IRQ" in line.split(","):
                description += "新版串口中断接收已启用。"
            self.emit("固件身份", description)
        elif line.startswith("# FSM_COMMANDS:"):
            self.emit("指令说明", "开发板已列出支持的指令；每条含义可查看“标志说明”页。")
        else:
            self.emit("未识别报文", "收到尚未翻译的内容，已保留原始记录：" + line)

    def _state(self, state):
        key = tuple(state.get(k) for k in ("state", "target", "pending", "ack1", "ack2", "fault", "drop_next", "led_scheme"))
        now = time.monotonic()
        unchanged = key == self.previous
        if unchanged and now - self.last_heartbeat < 10:
            return
        self.previous, self.last_heartbeat = key, now
        current, target = MODE_NAMES[state["state"]], MODE_NAMES[state["target"]]
        acks = f"模拟电机1={'已确认' if state['ack1'] == '1' else '未确认'}，模拟电机2={'已确认' if state['ack2'] == '1' else '未确认'}"
        prefix = f"板端{int(state['t_ms']) / 1000:.3f}秒 · "
        if state["state"] == "FAULT_LOCKED":
            expected = (self.expecting_fault and state["fault"] == "MODE_TIMEOUT"
                        and state["ack1"] == "1" and state["ack2"] == "0"
                        and state["target"] == "DAMPING")
            label = "预期保护" if expected else "异常报警"
            text = f"故障锁定，{FAULT_NAMES[state['fault']]}；目标{target}未到达。{acks}。用户灯{led_text(state)}。"
            if expected:
                text += "这是漏回确认测试的预期现象；后续还需验证锁定和恢复。"
        elif state["pending"] == "1":
            label = "等待确认"
            text = f"当前{current} → 目标{target}，切换尚未完成。{acks}。用户灯{led_text(state)}。"
        else:
            label = "状态心跳" if unchanged else "状态到达"
            text = f"当前{current}，不再等待确认，{acks}，{FAULT_NAMES[state['fault']]}。用户灯{led_text(state)}。"
        self.emit(label, prefix + text)
