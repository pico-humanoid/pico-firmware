"""Manual bench console for the seven-motor hardware FSM; no automatic arming."""

import csv
from datetime import datetime
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread
import sys
import time


BASE = Path(__file__).resolve().parent
KEEP_SECONDS = .1
STALE_SECONDS = 1.6
IDENTIFY_SECONDS = 4
STOP_SECONDS = 2.5
KD_MAX_MILLI = 800
KD_STEP_MILLI = 50
KD_DEFAULT_MILLI = 600

MODE = {
    "SELF_CHECK": "自检",
    "READY": "已就绪，等待手动启用",
    "STARTING": "正在进入零力矩",
    "ZERO_TORQUE": "零力矩",
    "DAMPING": "阻尼",
    "DEBUG_RESERVED": "调试预留",
    "STOPPING": "正在等待停机确认",
    "FAULT_LOCKED": "故障锁定",
}
COMMAND = {
    "ARM": "手动启用，先进入零力矩",
    "ZERO": "进入零力矩",
    "DAMP": "进入阻尼",
    "DEBUG": "停机后进入调试预留",
    "STOP": "请求七台电机停机",
}
REASON = {
    "NONE": "无异常",
    "OK": "无异常",
    "MAP_UNSET": "尚未配置并验证七电机映射，禁止启用",
    "READ_UID": "正在核对七台电机 UID",
    "PREFLIGHT_STOP": "正在确认启动前已停机",
    "WAIT_ARM": "等待手动启用",
    "ARMING": "正在启用并建立零力矩状态",
    "HOST_TIMEOUT": "上位机心跳超时",
    "MAX_RUN": "达到实机验证时限",
    "FEEDBACK_LOST": "电机反馈丢失",
    "MOTOR_FAULT": "电机报告异常",
    "EFFORT_LIMIT": "电机反馈力矩越限",
    "SPEED_LIMIT": "电机反馈速度越限",
    "CAN_FAULT": "CAN 通信故障",
    "UID_CONFLICT": "电机 UID 或通道/ID 映射冲突",
    "UID_TIMEOUT": "读取电机 UID 超时",
    "STOP_UNCONFIRMED": "停机尚未确认",
    "STOP_REQUEST": "操作者请求停机",
    "DEBUG_REQUEST": "请求停机并进入调试预留",
    "MODE_TIMEOUT": "等待切换状态超时",
    "NOT_READY": "当前条件不满足，状态未改变",
    "MODE_PENDING": "等待七台电机更新运行反馈",
    "MOTORS_MOVING": "电机仍在运动，等全部接近静止后再请求阻尼",
    "HANDSHAKE_FAILED": "使能或参数读回复核失败",
    "MOTOR_NETWORK_STOP": "电机网络触发保护",
    "UNEXPECTED_ENABLE": "未获授权时检测到电机运行，已请求全组停机",
    "UART_ERROR": "串口收包异常，已中止操作",
}


def fields(line):
    """Allow additional fields without mistaking a simulated status for hardware."""
    return dict(part.split("=", 1) for part in line.split(",")[1:] if "=" in part)


def hardware_banner(line):
    return (line.split(",", 1)[0] == "# PICO_MOTOR_FSM7=1"
            and fields(line).get("source") == "HARDWARE")


def parse_state(line):
    if not line.startswith("# MF7_STATE,"):
        return None
    values = fields(line)
    if (values.get("source") != "HARDWARE" or values.get("state") not in MODE
            or any(values.get(key) not in {"0", "1", "2", "3", "4", "5", "6", "7"}
                   for key in ("ready", "active", "stopped"))
            or not values.get("reason")):
        return None
    return values


def parse_motor(line):
    if not line.startswith("# MF7_MOTOR,"):
        return None
    values = fields(line)
    try:
        bus = int(values["bus"].removeprefix("FDCAN").removeprefix("CAN"))
        identifier = int(values["id"], 16 if values["id"].lower().startswith("0x") else 10)
        readings = tuple(int(values[name]) for name in ("vel_mrad_s", "torque_mNm", "estimate_mNm", "kd_milli"))
    except (KeyError, ValueError):
        return None
    if bus != 2 or not 1 <= identifier <= 7:
        return None
    return bus, identifier, *readings


def kd_request(command):
    digits = command[2:]
    if not command.startswith("KD") or len(digits) != 3 or not digits.isascii() or not digits.isdecimal():
        return None
    value = int(digits)
    return value if value <= KD_MAX_MILLI and value % KD_STEP_MILLI == 0 else None


def parse_kd_reply(line):
    if not line.startswith("# MF7_KD,"):
        return None
    data = fields(line)
    result = data.get("result")
    try:
        wanted, selected = (int(data[key]) for key in ("requested_milli", "set_milli"))
    except (ValueError, KeyError):
        return None
    if (not 0 <= selected <= KD_MAX_MILLI or selected % KD_STEP_MILLI
            or result not in {"ACCEPTED", "NOT_READY", "OUT_OF_RANGE", "INVALID_FORMAT"}
            or (result == "ACCEPTED" and wanted != selected)):
        return None
    return wanted, selected, result


def can_set_kd(state):
    if not state or state.get("target") != state["state"] or state["reason"] == "MAP_UNSET":
        return False
    board_setting = state.get("kd_set_milli", "")
    if not board_setting.isascii() or not board_setting.isdecimal() or len(board_setting) > 3:
        return False
    if kd_request(f"KD{int(board_setting):03}") is None:
        return False
    return ((state["state"] == "READY" and state["ready"] == state["stopped"] == "7" and state["active"] == "0")
            or (state["state"] == "ZERO_TORQUE" and state["active"] == "7"))


def kd_reply_description(reply):
    wanted, selected, result = reply
    if result == "ACCEPTED":
        return f"开发板已保存本次 Kd={selected/1000:.2f}，进入阻尼时使用。零力矩输出未改变。"
    reason = {"NOT_READY": "需先回到零力矩或等待就绪",
              "OUT_OF_RANGE": "超出固件允许的范围或步长",
              "INVALID_FORMAT": "命令格式错误"}[result]
    return f"Kd 设置未受理：{reason}，开发板保留 {selected/1000:.2f}。"


def can_command(state, command):
    if not state:
        return False
    mode = state["state"]
    if command == "STOP":
        return True
    if state["reason"] == "MAP_UNSET":
        return False
    if kd_request(command) is not None:
        return can_set_kd(state)
    if command == "ARM":
        return mode == "READY" and state["ready"] == state["stopped"] == "7" and state["active"] == "0"
    if command == "ZERO":
        return (mode == "DAMPING" and state["active"] == "7"
                or mode == "DEBUG_RESERVED" and state["stopped"] == "7" and state["active"] == "0")
    if command == "DAMP":
        return mode == "ZERO_TORQUE" and state["active"] == "7"
    if command == "DEBUG":
        return mode in ("ZERO_TORQUE", "DAMPING") and state["active"] == "7"
    return False


def command_description(command, state):
    kd = kd_request(command)
    if kd is not None:
        return f"设定阻尼 Kd={kd/1000:.2f} N·m/(rad/s)"
    if command == "ZERO" and state and state["state"] == "DEBUG_RESERVED":
        return "退出调试预留并回到就绪（仍需手动启用）"
    return COMMAND[command]


def stopped_state(state):
    return bool(state and state["stopped"] == "7" and state["active"] == "0"
                and state["state"] in ("READY", "DEBUG_RESERVED", "FAULT_LOCKED"))


def state_description(state):
    reason = REASON.get(state["reason"], state["reason"])
    return (f'{MODE[state["state"]]} ｜ 就绪 {state["ready"]}/7 · '
            f'运行 {state["active"]}/7 · 停机确认 {state["stopped"]}/7 ｜ {reason}')


class SerialSession:
    """State and command policy separated from the widgets and serial transport."""

    def __init__(self, send, publish, now):
        self.send = send
        self.publish = publish
        self.connected_at = now
        self.last_state_at = None
        self.identified_at = None
        self.next_keep = now
        self.identified = False
        self.state = None
        self.pending = None
        self.pending_until = None
        self.close_at = None
        self.done = False
        self.stop_confirmed = False

    def feed(self, line, now):
        if hardware_banner(line):
            self.identified_at = now
            self.identified = True
            self.state = None
            self.last_state_at = None
            self.pending = None
            self.pending_until = None
            self.stop_confirmed = False
            self.publish("identified", None)
            self.publish("state", None)
        state = parse_state(line)
        if state:
            if not self.identified:
                self.identified = True
                self.identified_at = now
                self.publish("identified", None)
            previous = self.state
            self.state = state
            self.last_state_at = now
            if not stopped_state(state):
                self.stop_confirmed = False
            relevant = ("state", "ready", "active", "stopped", "reason", "target", "kd_set_milli")
            if previous is None or any(previous.get(key) != state.get(key) for key in relevant):
                self.publish("state", state)
            if self.pending == "STOP" or self.close_at is not None:
                if stopped_state(state):
                    self.stop_confirmed = True
                    self.pending = None
                    self.pending_until = None
                    self.publish("stop", True)
                    if self.close_at is not None:
                        self.done = True
            elif self.pending and previous is not None and state["state"] != previous["state"]:
                self.pending = None
                self.pending_until = None
                self.publish("pending", None)
        if self.identified and self.close_at is None:
            kd = parse_kd_reply(line)
            if self.pending and kd is not None and kd_request(self.pending) == kd[0]:
                self.pending = None
                self.pending_until = None
                self.publish("pending", None)
                self.publish("kd", kd)
            sample = parse_motor(line)
            if sample:
                self.publish("motor", sample)

    def request(self, command, now):
        if self.done or self.close_at is not None or not self.identified:
            return False
        if command == "STOP":
            self.send("STOP")
            self.stop_confirmed = False
            self.pending = "STOP"
            self.pending_until = now + STOP_SECONDS
            self.publish("pending", "STOP")
            return True
        if self.pending or self.last_state_at is None or now - self.last_state_at >= STALE_SECONDS:
            return False
        if not can_command(self.state, command):
            return False
        self.send(command)
        self.stop_confirmed = False
        self.pending = command
        self.pending_until = now + STOP_SECONDS
        self.publish("pending", command)
        return True

    def close(self, now):
        if self.done or self.close_at is not None:
            return
        if not self.identified:
            self.done = True
            return
        self.request("STOP", now)
        self.close_at = now + STOP_SECONDS

    def tick(self, now):
        if self.done:
            return
        if self.close_at is not None:
            if now >= self.close_at:
                self.publish("stop", False)
                self.done = True
            return
        if not self.identified and now - self.connected_at >= IDENTIFY_SECONDS:
            self.publish("error", "未识别到七电机实机固件；此串口未发送任何命令。")
            self.done = True
            return
        last = self.last_state_at if self.last_state_at is not None else self.identified_at
        if last is not None and now - last >= STALE_SECONDS:
            self.publish("error", "板端状态失联，已停止发送心跳；不能确认停机，必要时立即从实物断电。")
            self.close(now)
            return
        if self.pending_until is not None and now >= self.pending_until:
            if self.pending == "STOP":
                self.publish("stop", False)
            else:
                if self.pending is not None and kd_request(self.pending) is not None:
                    self.publish("error", "未收到 Kd 设置答复，复核界面上的开发板设定值。")
                else:
                    self.publish("error", "未看到本次切换的状态变化，请复核板端状态和原始日志。")
            self.pending = None
            self.pending_until = None
            self.publish("pending", None)
        if self.identified and self.close_at is None and now >= self.next_keep:
            self.send("KEEP")
            self.next_keep = now + KEEP_SECONDS


def serial_api():
    """Use bundled pySerial when present, with no install required on PICO Workbench."""
    for candidate in (BASE/"vendor", BASE.parents[1]/"PICO_Workbench/project/ui/vendor"):
        if (candidate/"serial").is_dir():
            candidate = str(candidate)
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
            break
    import serial
    from serial.tools.list_ports import comports
    return serial, comports


def run_serial(port, controls, events, close_event, stop_event, log_root):
    session = None
    try:
        serial, _ = serial_api()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        directory = log_root/f"motor-fsm7-{stamp}"
        directory.mkdir(parents=True)
        events.put(("folder", directory))
        with ((directory/"board.raw.log").open("wb") as raw,
              (directory/"操作与中文说明.log").open("w", encoding="utf-8-sig", buffering=1) as report,
              (directory/"阻尼采样.csv").open("w", encoding="utf-8-sig", newline="", buffering=1) as capture):
            writer = csv.writer(capture)
            writer.writerow(("电脑接收时间_s", "板端反馈时间_ms", "最近上报状态", "CAN", "ID",
                             "速度_rad_s", "驱动反馈力矩_Nm", "阻尼估算_Nm", "固件指令Kd_Nm_per_rad_s"))
            started = time.monotonic()
            report.write("PICO 七电机实机状态机 · CAN2 ID1–3 RS00 / ID4–7 RS10P\n"
                         "就绪、运行、停机确认均为电机台数。写入串口只表示提交。\n"
                         "原始数据见 board.raw.log。vel_mrad_s 为速度（÷1000 后为 rad/s），"
                         "torque_mNm 为电机反馈力矩（÷1000 后为 N·m）；estimate_mNm 为由 −Kd × 实测速度得到的"
                         "阻尼估算（同样 ÷1000 后为 N·m），不是电机反馈。kd_milli 是板端指令 Kd 的千分值（非驱动器回读）。"
                         "逐台采样见 阻尼采样.csv。\n\n")
            def publish(kind, message):
                text = None
                if kind == "state" and message:
                    text = "[状态] " + state_description(message)
                elif kind == "kd":
                    text = "[Kd 设置] " + kd_reply_description(message)
                elif kind == "error":
                    text = "[异常] " + message
                elif kind == "stop":
                    text = "[停机确认] 收到七台停机状态。" if message else "[停机未确认] 不能据此判断电机已停机。"
                elif kind == "identified":
                    text = "[固件] 已识别七电机实机固件。"
                if text:
                    report.write(f"{datetime.now():%H:%M:%S} {text}\n")
                events.put((kind, message))

            device = serial.Serial(port=None, baudrate=115200, bytesize=serial.EIGHTBITS,
                                   parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                                   timeout=.02, write_timeout=.2, xonxoff=False,
                                   rtscts=False, dsrdtr=False)
            device.dtr = device.rts = False
            device.port = port
            with device:
                def send(command):
                    payload = (command + "\n").encode("ascii")
                    if device.write(payload) != len(payload):
                        raise OSError("串口写入不完整")
                    if command != "KEEP":
                        text = f"[电脑发送] {command}：{command_description(command, session.state)}；写入串口不等于已经执行。"
                        report.write(f"{datetime.now():%H:%M:%S} {text}\n")
                        events.put(("log", text))

                session = SerialSession(send, publish, time.monotonic())
                pending = bytearray()
                discard = False
                while not session.done:
                    now = time.monotonic()
                    if close_event.is_set():
                        session.close(now)
                    if session.done:
                        break
                    if stop_event.is_set():
                        stop_event.clear()
                        if session.close_at is None:
                            session.request("STOP", now)
                        while True:
                            try:
                                controls.get_nowait()
                            except Empty:
                                break
                    else:
                        try:
                            command = controls.get_nowait()
                        except Empty:
                            pass
                        else:
                            if not session.request(command, now):
                                publish("error", "当前状态不允许此操作，本条命令未发送。")
                    session.tick(now)
                    if session.done:
                        break
                    data = device.read(min(4096, device.in_waiting or 1))
                    if not data:
                        continue
                    raw.write(data)
                    raw.flush()
                    for part in data.splitlines(keepends=True):
                        if len(pending) + len(part) > 512:
                            discard = True
                            pending.clear()
                        if not discard:
                            pending.extend(part)
                        if not part.endswith(b"\n"):
                            continue
                        if not discard:
                            line = pending.decode("ascii", "replace").strip()
                            if line:
                                events.put(("raw", line))
                                stamp = time.monotonic()
                                session.feed(line, stamp)
                                sample = parse_motor(line)
                                if session.identified and sample:
                                    bus, ident, vel, torque, estimate, kd = sample
                                    board_time = fields(line).get("t_ms", "")
                                    if not board_time.isascii() or not board_time.isdecimal():
                                        board_time = ""
                                    writer.writerow((f"{stamp-started:.3f}", board_time,
                                        (session.state or {}).get("state", ""), bus, ident,
                                        *(f"{v/1000:.3f}" for v in (vel, torque, estimate, kd))))
                        pending.clear()
                        discard = False
                        if session.done:
                            break
    except (ImportError, OSError) as exc:
        events.put(("error", f"串口或日志操作失败：{exc}"))
    finally:
        events.put(("ended", (bool(session and session.identified), bool(session and session.done and session.close_at is not None and session.stop_confirmed))))


class MotorFsm7Panel:
    def __init__(self, parent=None, selected_port="", log_root=None):
        import tkinter as tk
        from tkinter import ttk, scrolledtext
        self.tk, self.ttk = tk, ttk
        self.window = tk.Toplevel(parent) if parent is not None else tk.Tk()
        self.window.title("PICO · 七电机实机状态机")
        self.window.geometry("1040x840")
        self.window.minsize(820, 635)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.log_root = Path(log_root) if log_root else BASE/"logs"
        self.thread = None
        self.closing = self.disconnecting = self.identified = False
        self.state = None
        self.pending = None
        self.status = tk.StringVar(value="未连接。先烧录七电机实机固件，再选择 ST-LINK 虚拟串口。")
        self.phase = tk.StringVar(value="当前状态：未连接")
        self.folder = tk.StringVar(value="原始报文和中文说明保存在本机。")
        body = ttk.Frame(self.window, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="七电机实机状态机", font=("", 18, "bold")).pack(anchor="w")
        ttk.Label(body, text="固定台架 · CAN2：ID1–3 RS00，ID4–7 RS10P。连接不会启用；此入口只适用于七电机实机固件。",
                  wraplength=960).pack(anchor="w", pady=(6, 12))

        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(0, 8))
        self.port = ttk.Combobox(bar, state="readonly", width=42)
        self.port.pack(side="left", fill="x", expand=True)
        self.refresh_button = ttk.Button(bar, text="刷新串口", command=self.refresh_ports)
        self.refresh_button.pack(side="left", padx=6)
        self.connect_button = ttk.Button(bar, text="连接", command=self.connect)
        self.connect_button.pack(side="left")
        self.disconnect_button = ttk.Button(bar, text="停机后断开", command=self.disconnect)
        self.disconnect_button.pack(side="left", padx=(6, 0))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(0, 8))
        self.buttons = {}
        for key, title in (("ARM", "手动启用"),
                           ("ZERO", "零力矩"), ("DAMP", "阻尼"),
                           ("DEBUG", "调试预留"), ("STOP", "请求停机")):
            button = ttk.Button(row, text=title, command=lambda value=key: self.command(value))
            button.pack(side="left", padx=(0, 6))
            self.buttons[key] = button
        ttk.Label(body, textvariable=self.phase, font=("", 13, "bold"), wraplength=960).pack(anchor="w", pady=(4, 2))
        ttk.Label(body, textvariable=self.status, wraplength=960).pack(anchor="w", pady=(0, 8))

        kd_box = ttk.LabelFrame(body, text="阻尼系数 Kd（七台共用，N·m/(rad/s)）", padding=6)
        kd_box.pack(fill="x", pady=(0, 8))
        self.kd_slider = tk.Scale(kd_box, orient="horizontal", from_=0, to=KD_MAX_MILLI/1000,
                                  resolution=KD_STEP_MILLI/1000, digits=3, showvalue=True, highlightthickness=0)
        self.kd_slider.set(KD_DEFAULT_MILLI/1000)
        self.kd_slider.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.kd_apply = ttk.Button(kd_box, text="应用 Kd", command=self.apply_kd)
        self.kd_apply.pack(side="left", padx=(0, 8))
        self.kd_status = tk.StringVar(value="连接新版固件后显示板端设定值。")
        ttk.Label(kd_box, textvariable=self.kd_status, width=46, wraplength=310).pack(side="left")

        table_box = ttk.LabelFrame(body, text="七电机最近反馈与阻尼估算", padding=6)
        table_box.pack(fill="x")
        self.table = ttk.Treeview(table_box, columns=("motor", "velocity", "torque", "estimate", "kd"),
                                  show="headings", height=7)
        for key, heading in zip(self.table["columns"], ("CAN2 · ID / 型号", "速度 / rad/s", "反馈力矩 / N·m",
                                                       "估算阻尼力矩 / N·m", "板端指令 Kd")):
            self.table.heading(key, text=heading)
            self.table.column(key, width=148, minwidth=85, anchor="center")
        self.table.pack(fill="x", expand=True)
        ttk.Label(table_box, text="反馈力矩来自电机；估算阻尼力矩 = −Kd × 实测速度，用来观察方向与大小，不是驱动反馈。",
                  wraplength=960).pack(anchor="w", pady=(4, 0))
        self.reset_rows()

        tabs = ttk.Notebook(body)
        tabs.pack(fill="both", expand=True, pady=8)
        self.logs = {}
        for key, label in (("log", "中文运行说明"), ("raw", "原始串口报文")):
            frame = ttk.Frame(tabs)
            tabs.add(frame, text=label)
            text = scrolledtext.ScrolledText(frame, wrap="word", height=9, state="disabled")
            text.pack(fill="both", expand=True)
            self.logs[key] = text
        ttk.Label(body, textvariable=self.folder, wraplength=960).pack(anchor="w")
        self.events = Queue()
        self.controls = Queue(maxsize=1)
        self.close_event = Event()
        self.stop_event = Event()
        self.ports = []
        self.refresh_ports(selected_port)
        self.render_controls()
        self.timer = self.window.after(75, self.poll)

    def reset_rows(self):
        self.table.delete(*self.table.get_children())
        for identifier in range(1, 8):
            label = f'{identifier} / {"RS00" if identifier <= 3 else "RS10P"}'
            self.table.insert("", "end", iid=f"2:{identifier}", values=(label, "—", "—", "—", "—"))

    def refresh_ports(self, selected_port=""):
        previous = selected_port or (self.ports[self.port.current()].device if self.port.current() >= 0 else "")
        try:
            _, comports = serial_api()
            self.ports = list(comports())
        except ImportError as exc:
            self.ports = []
            self.status.set(f"找不到 pySerial：{exc}。可用 PICO 随附的串口库。")
        self.port["values"] = [f"{port.device} · {port.description}" for port in self.ports]
        self.port.set("")
        match = next((i for i, port in enumerate(self.ports) if port.device == previous), -1)
        boards = [i for i, port in enumerate(self.ports) if port.vid == 0x0483]
        if match >= 0:
            self.port.current(match)
        elif len(boards) == 1:
            self.port.current(boards[0])

    def connect(self):
        index = self.port.current()
        if index < 0:
            self.status.set("请选择 ST-LINK 虚拟串口。")
            return
        self.events = Queue()
        self.controls = Queue(maxsize=1)
        self.close_event, self.stop_event = Event(), Event()
        self.pending = self.state = None
        self.disconnecting = self.identified = False
        self.reset_rows()
        self.status.set("正在识别七电机实机固件；此时不会发送任何指令。")
        self.phase.set("当前状态：等待板端")
        self.thread = Thread(target=run_serial, daemon=True,
                             args=(self.ports[index].device, self.controls, self.events,
                                   self.close_event, self.stop_event, self.log_root))
        self.thread.start()
        self.render_controls()

    def command(self, value):
        if self.thread is None or self.disconnecting:
            return
        if value == "STOP":
            self.stop_event.set()
            return
        if not can_command(self.state, value) or self.pending:
            return
        try:
            self.controls.put_nowait(value)
        except Full:
            return

    def apply_kd(self):
        milli = round(self.kd_slider.get() * 1000)
        self.command(f"KD{milli:03}")

    def disconnect(self):
        if self.thread is not None:
            self.disconnecting = True
            self.close_event.set()
            self.status.set("正在断开。识别过实机固件时先请求停机，等待七路确认。")
            self.render_controls()

    def close(self):
        if self.thread is not None:
            self.closing = True
            self.disconnect()
        else:
            self.window.after_cancel(self.timer)
            self.window.destroy()

    def render_controls(self):
        connected = self.thread is not None
        linked = connected and not self.disconnecting and self.identified
        for key, button in self.buttons.items():
            allowed = linked and (key == "STOP" or not self.pending and can_command(self.state, key))
            button.configure(state="normal" if allowed else "disabled")
        returning = bool(self.state and self.state["state"] == "DEBUG_RESERVED")
        self.buttons["ZERO"].configure(text="退出调试（回就绪）" if returning else "零力矩")
        can_set = linked and not self.pending and can_set_kd(self.state)
        self.kd_slider.configure(state="normal" if can_set else "disabled")
        self.kd_apply.configure(state="normal" if can_set else "disabled")
        kd = self.state.get("kd_set_milli") if linked and self.state else None
        if kd and kd.isascii() and kd.isdecimal() and len(kd) <= 3:
            text = f"板端设定 {int(kd)/1000:.2f}。"
            text += "拖动后点应用，再进入阻尼。" if can_set else "回到零力矩或等就绪后可调。"
        elif linked and self.state:
            text = "旧版固件不支持调节，请烧录新版。"
        else:
            text = "连接新版固件后显示板端设定值。"
        self.kd_status.set(text)
        self.connect_button.configure(state="disabled" if connected else "normal")
        self.disconnect_button.configure(state="normal" if connected and not self.disconnecting else "disabled")
        self.refresh_button.configure(state="disabled" if connected else "normal")
        self.port.configure(state="disabled" if connected else "readonly")

    def append(self, key, lines):
        if not lines:
            return
        widget = self.logs[key]
        follow = widget.yview()[1] >= .98
        widget.configure(state="normal")
        widget.insert("end", "\n".join(lines) + "\n")
        excess = int(widget.index("end-1c").split(".")[0]) - 1600
        if excess > 0:
            widget.delete("1.0", f"{excess+1}.0")
        widget.configure(state="disabled")
        if follow:
            widget.see("end")

    def poll(self):
        lines, raw, samples = [], [], {}
        for _ in range(300):
            try:
                kind, value = self.events.get_nowait()
            except Empty:
                break
            if kind == "raw":
                raw.append(value)
            elif kind == "log":
                lines.append(value)
            elif kind == "motor":
                samples[value[:2]] = value[2:]
            elif kind == "state":
                self.state = value
                if value:
                    text = state_description(value)
                    self.phase.set("当前状态：" + text)
                    lines.append("[状态] " + text)
            elif kind == "identified":
                self.identified = True
                self.pending = None
                self.phase.set("当前状态：已识别，等待完整状态报文")
                self.status.set("已识别实机固件。连接本身不会启用电机。")
            elif kind == "pending":
                self.pending = value
                if value:
                    self.status.set(command_description(value, self.state) + "：已发送，等待板端状态。")
            elif kind == "kd":
                text = kd_reply_description(value)
                self.status.set(text)
                lines.append("[Kd 设置] " + text)
            elif kind == "stop":
                self.pending = None
                self.status.set("收到 7/7 停机确认。" if value else "停机未确认，必要时立即从实物断电。")
                lines.append("[停机] " + self.status.get())
            elif kind == "folder":
                self.folder.set("日志：" + str(value))
            elif kind == "error":
                self.status.set(value)
                lines.append("[异常] " + value)
            elif kind == "ended":
                self.thread = None
                self.phase.set("当前状态：已断开")
                if value[0]:
                    self.status.set("已断开，收到 7/7 停机确认。" if value[1]
                                    else "已断开，停机未确认。必要时立即从实物断电。")
                if self.closing:
                    if value[0] and not value[1]:
                        from tkinter import messagebox
                        messagebox.showwarning("停机未确认", self.status.get(), parent=self.window)
                    self.window.destroy()
                    return
        for (bus, identifier), (velocity, torque, estimate, kd) in samples.items():
            row = f"{bus}:{identifier}"
            label = self.table.item(row, "values")[0]
            self.table.item(row, values=(label, f"{velocity/1000:.3f}", f"{torque/1000:.3f}",
                                         f"{estimate/1000:.3f}", f"{kd/1000:.3f}"))
        self.append("log", lines)
        self.append("raw", raw)
        self.render_controls()
        self.timer = self.window.after(75, self.poll)


def create_panel(parent=None, *, selected_port="", log_root=None):
    return MotorFsm7Panel(parent, selected_port=selected_port, log_root=log_root)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="PICO 七电机实机状态机（不会自动连接或启用）")
    parser.add_argument("--port", help="预选 ST-LINK 串口，例如 COM5 或 /dev/ttyACM0")
    parser.add_argument("--log-dir", type=Path, help="指定日志目录，默认为本程序旁的 logs")
    args = parser.parse_args(argv)
    panel = create_panel(selected_port=args.port or "", log_root=args.log_dir)
    panel.window.mainloop()


if __name__ == "__main__":
    main()
