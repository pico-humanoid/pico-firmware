"""Task execution, real serial captures, and persisted experiment records."""
from collections import deque
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from queue import Empty, Queue
import subprocess
import sys
import threading
import time
import uuid
from runtime_paths import project_root
from experiment_log import export_notes

HERE = project_root() / "ui"
sys.path.insert(0, str(HERE / "vendor"))
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE.parent / "scripts/linux"))
import serial
from serial.tools import list_ports
from check_log import check as check_board
from usbcan_test import Decoder, assess, data_packet, settings_packet
import platform_tools as tools
import catalog

ROOT = tools.ROOT
LOGS = ROOT / "logs"
RECORDS = LOGS / "ui_records"


def ports():
    return [{"device": p.device, "name": p.description, "vid": p.vid, "pid": p.pid,
             "kind": "board" if p.vid == 0x0483 else
                     "usbcan" if (p.vid, p.pid) == (0x1A86, 0x7523) else "other"}
            for p in sorted(list_ports.comports(), key=lambda p: p.device)]


class Cancelled(Exception):
    pass


class Job:
    def __init__(self, kind, mode, port=""):
        self.id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
        self.kind, self.mode, self.port = kind, mode, port
        self.profile = catalog.profile(mode)
        self.telemetry = {"health": {}, "devices": {}, "values": {}}
        self.status, self.phase = "running", "正在准备"
        self.started = datetime.now().isoformat(timespec="seconds")
        self.ended, self.result = None, None
        self.metrics = {"tx": 0, "rx": 0, "done": 0}
        self.lines, self.frames = deque(maxlen=2500), deque(maxlen=400)
        self.sequence = 0
        self.files = []
        self.board_job = None
        self.cancel = threading.Event()
        self.lock = threading.RLock()
        self.process = None
        if kind == "fsm":
            self.commands = Queue(maxsize=1)

    def log(self, message):
        with self.lock:
            self.sequence += 1
            self.lines.append({"n": self.sequence, "text": str(message)})

    def phase_set(self, phase):
        with self.lock:
            self.phase = phase
        self.log(phase)

    def frame(self, event, ident, data, ms, fmt="STD"):
        with self.lock:
            self.frames.append({"event": event, "id": ident, "data": data,
                                "ms": ms, "format": fmt})

    def snapshot(self, details=False, after=0):
        with self.lock:
            value = {"id": self.id, "kind": self.kind, "mode": self.mode, "port": self.port,
                     "status": self.status, "phase": self.phase, "started": self.started,
                     "ended": self.ended, "metrics": dict(self.metrics),
                     "result": self.result, "files": list(self.files)}
            value["board_job"] = self.board_job
            value["profile_name"] = self.profile["name"]
            value["base_mode"] = self.profile["base_mode"]
            value["profile"] = self.profile
            value["telemetry"] = json.loads(json.dumps(self.telemetry))
            if details:
                value.update(lines=[x for x in self.lines if x["n"] > after],
                             sequence=self.sequence, frames=list(self.frames))
            return value

    def checkpoint(self):
        if self.cancel.is_set():
            raise Cancelled()


class Manager:
    def __init__(self):
        LOGS.mkdir(exist_ok=True)
        RECORDS.mkdir(exist_ok=True)
        self.lock, self.jobs = threading.RLock(), {}

    def start(self, kind, mode, port=""):
        if kind not in ("build", "flash", "board", "usbcan", "fsm"):
            raise ValueError("不支持此操作。")
        tools.validate_mode(mode)
        if kind in ("board", "usbcan", "fsm"):
            if not port or port not in {p["device"] for p in ports()}:
                raise ValueError("请选择已连接的串口，然后重试。")
        if kind == "fsm" and mode != "BoardFsm":
            raise ValueError("状态机串口只用于单板验证配置。")
        if kind == "usbcan" and catalog.profile(mode)["base_mode"] != "External":
            raise ValueError("USB-CAN 测试适用于外部 CAN 配置。")
        with self.lock:
            active = [j for j in self.jobs.values() if j.status == "running"]
            if kind in ("build", "flash") and active:
                raise ValueError("请先结束当前任务，再编译或烧录。")
            if any(j.kind in ("build", "flash") for j in active):
                raise ValueError("正在编译或烧录，请等待完成。")
            if any(j.kind == kind or (port and j.port == port) for j in active):
                raise ValueError("该任务或串口正在使用中，请先停止已有任务。")
            if kind == "usbcan" and not any(j.kind == "board" and j.mode == mode
                                             and j.phase == "等待开发板 RESET / 测试数据" for j in active):
                raise ValueError("请先打开开发板日志，确认串口已打开，再按 RESET。")
            job = Job(kind, mode, port)
            if kind == "usbcan":
                job.board_job = next(j.id for j in active if j.kind == "board" and j.mode == mode)
            self.jobs[job.id] = job
            threading.Thread(target=self._run, args=(job,), daemon=True).start()
            return job

    def _run(self, job):
        try:
            result = getattr(self, "_do_" + job.kind)(job)
            job.checkpoint()
            with job.lock:
                job.result = result
                job.status = "recorded" if result.get("capture_only") else "pass" if result.get("pass") else "fail"
                job.phase = "已完成" if result.get("pass") else result.get("message", "检查未通过")
        except Cancelled:
            job.status, job.phase = "cancelled", "已停止；本次结果未验收"
            job.log(job.phase)
        except Exception as exc:
            job.status, job.phase = "error", str(exc)
            job.log("操作失败：" + str(exc))
            job.result = {"pass": False, "message": str(exc)}
        finally:
            if job.kind in ('board', 'usbcan'):
                source = next((LOGS / name for name in job.files if name.endswith('.csv')), None)
                if source is not None and source.is_file():
                    try:
                        readable = export_notes(source.with_name(source.stem + '_中文说明.log'), [source],
                                                status=job.phase, result=job.result, name=job.profile['name'])
                        with job.lock:
                            job.files.append(readable.name)
                        job.log('中文日志说明：' + str(readable))
                    except (ValueError, OSError) as exc:
                        job.log('中文说明保存失败，原始日志仍在：' + str(exc))
            with job.lock:
                job.ended = datetime.now().isoformat(timespec="seconds")
            (RECORDS / (job.id + ".json")).write_text(
                json.dumps(job.snapshot(True), ensure_ascii=False, indent=2), encoding="utf-8")

    def stop(self, ident):
        job = self.get(ident)
        if job.kind == "flash" and job.status == "running":
            raise ValueError("烧录期间请等待写入与校验完成。")
        job.cancel.set()
        if job.process and job.process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(job.process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                import signal
                try:
                    os.killpg(job.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def get(self, ident):
        with self.lock:
            if ident not in self.jobs:
                raise ValueError("找不到此任务。")
            return self.jobs[ident]

    def history(self, include_archived=False):
        records = []
        notes = catalog.annotations()
        for path in sorted(RECORDS.glob("*.json"), reverse=True)[:80]:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                item.pop("lines", None)
                item.pop("frames", None)
                item["annotation"] = notes.get(item["id"], {})
                if item["annotation"].get("archived") and not include_archived:
                    continue
                records.append(item)
            except (OSError, ValueError):
                continue
        return records

    def command(self, job, args, collect=False):
        job.checkpoint()
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        proc = tools.spawn(args, cwd=tools.project_dir(job.mode), env=tools.environment(), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, **flags)
        job.process = proc
        output = []
        try:
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip()
                job.log(line)
                if collect:
                    output.append(line)
            code = proc.wait()
            job.checkpoint()
            if code:
                raise RuntimeError("工具执行失败，退出码 " + str(code) + "，请查看控制台。")
            return "\n".join(output)
        finally:
            proc.stdout.close()
            job.process = None

    def _do_build(self, job):
        job.phase_set("正在编译：" + job.profile["name"])
        for command in tools.build_commands(job.mode):
            self.command(job, command)
        image = tools.image_for(job.mode)
        if not image.exists():
            raise RuntimeError("构建结束但没有找到 ELF 固件。")
        (tools.build_dir(job.mode) / "ui_build_profile.json").write_text(
            json.dumps({"profile": job.profile}, ensure_ascii=False, indent=2), encoding="utf-8")
        job.log("编译完成：" + str(image))
        return {"pass": True, "message": "编译成功；尚未烧录", "image": str(image),
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}

    def _do_flash(self, job):
        image = tools.image_for(job.mode)
        manifest = tools.build_dir(job.mode) / "ui_build_profile.json"
        if manifest.exists():
            built_profile = json.loads(manifest.read_text(encoding="utf-8")).get("profile")
            if built_profile != job.profile:
                raise ValueError("实验配置已修改，请重新编译后烧录，避免使用旧参数固件。")
        elif not job.profile.get("builtin") or job.profile["base_mode"] == "Device":
            raise ValueError("请先通过界面编译此配置，建立对应的固件版本记录。")
        if tools.source_newer(image, job.mode):
            raise ValueError("源文件已更新或固件不存在，请先编译当前配置。")
        programmer = tools.tool("programmer")
        job.phase_set("正在识别 ST-LINK")
        if programmer:
            output = self.command(job, [programmer, "-l", "st-link"], collect=True)
            probes = re.findall(r"ST-LINK SN\s*:\s*(\S+)", output)
        elif not tools.WINDOWS and tools.tool("openocd"):
            probes=tools.stlink_serials()
        else:raise ValueError("未找到STM32CubeProgrammer或OpenOCD。")
        if len(probes) != 1:
            raise ValueError("需要连接恰好一块可识别的ST-LINK开发板；当前识别到 " + str(len(probes)) + " 块。")
        job.phase_set("正在写入固件、校验并复位")
        self.command(job, tools.flash_command(probes[0],image))
        return {"pass": True, "message": "烧录和校验成功；测试结果以实际日志为准",
                "image": str(image), "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}

    def _serial(self, job, baud):
        kwargs = {"exclusive": True} if os.name != "nt" else {}
        return serial.Serial(job.port, baud, timeout=0.01 if job.kind == "usbcan" else 0.08,
                             write_timeout=1, **kwargs)

    def fsm_command(self, job, command):
        if command not in {"ZERO", "DAMP", "DEBUG", "RESET", "VERIFY", "DISCONNECT"}:
            raise ValueError("未知状态机命令。")
        with job.lock:
            if job.kind != "fsm" or job.status != "running" or job.cancel.is_set():
                raise ValueError("状态机串口未连接。")
            state = job.telemetry.get("fsm")
            if job.telemetry.get("busy"):
                raise ValueError("请等待当前操作结束。")
            if command != "DISCONNECT" and (not state or state["pending"] == "1"):
                raise ValueError("请等待开发板识别或状态切换完成。")
            if command in {"DAMP", "ZERO", "DEBUG"} and state["state"] == "FAULT_LOCKED":
                raise ValueError("故障已锁定，请先重新自检。")
            job.commands.put_nowait(command)
            job.telemetry["busy"] = True

    def _do_fsm(self, job):
        from board_fsm_protocol import Bench, MODE_NAMES, REPLY, VERIFY_STEPS, parse_state, verify
        from board_fsm_report import FsmReport, LEGEND, led_text

        path = LOGS / ("ui_fsm_" + job.id + ".log")
        readable_path = path.with_name(path.stem + "_readable.log")
        job.files.extend((path.name, readable_path.name))
        job.phase_set("正在识别单板状态机固件")
        last_feedback = None

        def progress(index, status, detail):
            with job.lock:
                if index == 1 and status == "RUNNING":
                    job.telemetry["fsm_steps"] = [{"status": "WAITING", "detail": ""} for _ in VERIFY_STEPS]
                job.telemetry["fsm_steps"][index - 1] = {"status": status, "detail": detail}
                job.telemetry["fsm_step"] = index
            job.phase_set(f"第{index}/8项 · {VERIFY_STEPS[index - 1][0]} · "
                          + {"RUNNING": "正在验证", "PASS": "通过", "FAIL": "未通过"}[status])

        def observe_led(state, seconds):
            text = f"{MODE_NAMES[state['state']]}：LD2 {led_text(state)}。留 {seconds} 秒观察。"
            job.phase_set("观察灯光 · " + text)
            report.emit("观察灯光", text)

        def line_received(line):
            nonlocal last_feedback
            state = parse_state(line)
            if state:
                last_feedback = time.monotonic()
                with job.lock:
                    job.telemetry["fsm"] = state
                if job.phase == "正在识别单板状态机固件":
                    job.phase_set("已识别 BoardFsm，电机反馈为模拟值")
            elif line.startswith(REPLY):
                with job.lock:
                    job.telemetry["reply"] = line[len(REPLY):]
            job.log("[原始接收] " + line)
            report.receive(line)

        def command_sent(command):
            job.log("[原始发送] > " + command)
            report.command(command)

        def checkpoint():
            if job.cancel.is_set():
                if report.running:
                    report.step(report.step_index, "FAIL", "验证被停止，未执行的项目不判定通过")
                    report.finish("FAIL", "验证被停止，本轮没有完成全部项目。")
                    with job.lock:
                        job.telemetry["validation"] = "FAIL"
                report.emit("连接结束", "操作者关闭了本次连接，日志已保存。")
            job.checkpoint()

        with self._serial(job, 115200) as dev, path.open("x", encoding="utf-8", buffering=1) as log, \
                readable_path.open("x", encoding="utf-8", buffering=1) as readable:
            readable.write("PICO 状态机单板验证 · 日志标志说明\n" + LEGEND + "\n--- 本次运行记录 ---\n")
            report = FsmReport(readable, output=job.log, on_progress=progress)
            report.start()
            bench = Bench(dev, log, output=job.log, on_line=line_received, checkpoint=checkpoint,
                          on_command=command_sent, on_step=report.step)
            start = time.monotonic()
            while True:
                checkpoint()
                try:
                    command = job.commands.get_nowait()
                except Empty:
                    command = None
                if command == "DISCONNECT":
                    report.emit("连接结束", "已断开串口，中文说明和原始报文均已保存。")
                    return {"capture_only": True, "message": "已断开串口，日志已保存",
                            "validation": job.telemetry.get("validation")}
                if command == "VERIFY":
                    with job.lock:
                        job.telemetry["validation"] = "RUNNING"
                    try:
                        verify(bench, on_observe=observe_led)
                    except (RuntimeError, OSError) as exc:
                        outcome = "FAIL"
                        if report.running:
                            report.step(report.step_index, "FAIL", str(exc))
                        report.finish(outcome, str(exc))
                    else:
                        outcome = "PASS"
                        report.finish(outcome)
                    with job.lock:
                        job.telemetry["validation"] = outcome
                        job.telemetry["busy"] = False
                    job.phase_set("一键验证：" + ("8/8项通过，已恢复零力矩" if outcome == "PASS" else "未通过，请查看失败步骤"))
                    job.log("[原始结果] BOARD_FSM_SERIAL_RESULT=" + outcome)
                    log.write("BOARD_FSM_SERIAL_RESULT=" + outcome + "\n")
                elif command:
                    # Await a fresh board response before releasing the command buttons.
                    job.phase_set("手动操作：" + {"ZERO": "请求零力矩", "DAMP": "请求阻尼",
                                                 "DEBUG": "进入调试预留", "RESET": "重新自检"}[command])
                    try:
                        if command == "RESET":
                            bench.reset()
                            job.phase_set("重新自检完成，两路确认已收到，已回到零力矩")
                        else:
                            bench.command(command)
                            reply = bench.wait(lambda line: line.startswith(REPLY + "command=" + command + ","),
                                               "指令 " + command + " 的回包").rsplit("=", 1)[-1]
                            bench.wait(parse_state, "指令后的状态")
                            if command == "DEBUG" and reply == "DEBUG_RESERVED":
                                job.phase_set("旧固件只返回预留标记。请编译并烧录新版 BoardFsm。")
                    except (RuntimeError, OSError) as exc:
                        report.emit("异常报警", str(exc))
                        raise
                    finally:
                        with job.lock:
                            job.telemetry["busy"] = False
                else:
                    bench.read_message()
                if time.monotonic() - (last_feedback if last_feedback is not None else start) >= 4:
                    report.emit("异常报警", "连续4秒没有有效状态，连接结束；检查串口、固件和USB连接。")
                    raise RuntimeError("未收到 BoardFsm 状态。请确认串口、固件和 USB 连接。")

    def _do_board(self, job):
        if job.profile["base_mode"] in ("Custom", "Device") or job.profile["cmake_options"].get("PICO_APP") == "Can3Bench":
            return self._do_stream(job)
        path = LOGS / ("ui_board_" + job.id + ".csv")
        job.files.append(path.name)
        lines, buffer, observed_mode, observed = [], bytearray(), None, False
        deadline = time.monotonic() + 300
        with self._serial(job, 115200) as dev, path.open("w", encoding="utf-8", newline="") as out:
            job.phase_set("等待开发板 RESET / 测试数据")
            job.log("串口已打开，115200 8N1。现在按开发板 RESET；最长等待 300 秒。")
            while time.monotonic() < deadline:
                job.checkpoint()
                buffer.extend(dev.read(dev.in_waiting or 1))
                while b"\n" in buffer:
                    raw, _, buffer = buffer.partition(b"\n")
                    text = raw.decode("utf-8", errors="replace").rstrip("\r")
                    lines.append(text)
                    out.write(text + "\n")
                    out.flush()
                    job.log(text)
                    if "# PICO G474" in text:
                        # A second reset starts a fresh log segment for independent checking.
                        lines = [text]
                        out.seek(0)
                        out.truncate()
                        out.write(text + "\n")
                        out.flush()
                        observed_mode, observed = None, False
                        deadline = time.monotonic() + 300
                        with job.lock:
                            job.frames.clear()
                            job.metrics = {"tx": 0, "rx": 0, "done": 0}
                    if "mode=" in text:
                        observed_mode = "External" if "EXTERNAL_NORMAL" in text else "Loopback"
                        if observed_mode != job.profile["base_mode"]:
                            raise ValueError("板上运行的固件与界面所选配置不一致，请选择匹配配置或重新烧录。")
                    row = text.split(",")
                    if len(row) == 6 and row[1] in ("RX", "TX_SUBMIT", "TX_DONE"):
                        if not observed:
                            deadline = time.monotonic() + 25
                            observed = True
                        job.frame(row[1], row[3], row[5], row[0], row[2])
                        with job.lock:
                            job.metrics[{"RX": "rx", "TX_SUBMIT": "tx", "TX_DONE": "done"}[row[1]]] += 1
                    if text.startswith("# RESULT="):
                        result = check_board("\n".join(lines), external=job.profile["base_mode"] == "External")
                        result["message"] = "开发板日志完整性复核" + ("通过" if result["pass"] else "未通过")
                        self._save_check(job, path, result)
                        return result
                if len(buffer) > 16384:
                    raise ValueError("串口持续输出无换行数据，请确认串口与波特率。")
        raise RuntimeError("采集超时，未得到完整结果。请确认已按 RESET；外部测试需启动 0x321 测试序列。原始日志已保留。")

    def _do_stream(self, job):
        """Device-reader 8-column logs have their own semantics; never use Bringup PASS."""
        path = LOGS / ("ui_device_" + job.id + ".csv")
        job.files.append(path.name)
        buffer = bytearray()
        seconds = job.profile.get("capture_seconds", 80)
        start = last_data = None
        waiting = time.monotonic() + 300
        with self._serial(job, job.profile.get("board_baud", 115200)) as dev, path.open("w", encoding="utf-8", newline="") as out:
            job.phase_set("等待开发板 RESET / 测试数据")
            job.log("串口已打开。现在按 RESET。首次数据后采集 " + str(seconds) + " 秒；完成采集不自动判定设备通过。")
            while True:
                job.checkpoint()
                now = time.monotonic()
                if start is not None and now - start >= seconds:
                    break
                if start is None and now > waiting:
                    raise ValueError("等待启动日志超时。请确认串口、波特率并按 RESET。")
                if last_data is not None and now - last_data > 10:
                    raise ValueError("连续 10 秒没有串口数据，原始日志已保存。")
                data = dev.read(dev.in_waiting or 1)
                if data:
                    start = now if start is None else start
                    last_data = now
                    buffer.extend(data)
                while b"\n" in buffer:
                    raw, _, buffer = buffer.partition(b"\n")
                    line = raw.decode("utf-8", errors="replace").rstrip("\r")
                    out.write(line + "\n")
                    out.flush()
                    job.log(line)
                    if "# PICO device-read" in line and job.profile["base_mode"] == "Device":
                        expected = str(job.profile["cmake_options"].get("PICO_APP", "")).upper()
                        device_match = re.search(r"device=([^\s;]+)", line)
                        actual = device_match[1].upper() if device_match else ""
                        if actual == "BMS+POWER":
                            actual = "DUAL"
                        if actual and expected and actual != expected:
                            raise ValueError("板端应用与所选读取配置不一致，请检查烧录镜像。")
                        rate_match = re.search(r"bitrate=(\d+)", line)
                        configured = str(job.profile["cmake_options"].get("PICO_DEVICE_BITRATE", ""))
                        if rate_match and configured and rate_match[1] != configured:
                            raise ValueError("板端 CAN 位速率与所选配置不一致。")
                        if expected == "MOTOR":
                            options = job.profile["cmake_options"]
                            pairs = [("count", "PICO_MOTOR_COUNT"), ("motor1_id", "PICO_MOTOR1_ID"), ("host_id", "PICO_MOTOR_HOST_ID")]
                            if int(options.get("PICO_MOTOR_COUNT", 1)) == 2:
                                pairs.append(("motor2_id", "PICO_MOTOR2_ID"))
                            for reported, configured_key in pairs:
                                found = re.search(r"\b" + reported + r"=([^\s;]+)", line)
                                if not found or int(found[1], 0) != int(str(options[configured_key]), 0):
                                    raise ValueError("板端电机数量或 ID 与所选配置不一致，请检查烧录镜像。")
                            for reported, key in [("motor1_model", "PICO_MOTOR1_MODEL"), ("motor2_model", "PICO_MOTOR2_MODEL")]:
                                found = re.search(r"\b" + reported + r"=([^\s;]+)", line)
                                if not found or found[1] != str(options[key]):
                                    raise ValueError("板端电机型号标签与所选配置不一致。")
                            channel=int(options.get("PICO_MOTOR_CAN_CHANNEL",1))
                            found=re.search(r"\bchannel=FDCAN(\d+)\b",line)
                            if not found or int(found[1])!=channel:
                                raise ValueError(f"电机实验需使用 CAN{channel}，请重新烧录当前镜像。")
                    if line.startswith("# "):
                        category, _, rest = line[2:].partition(",")
                        fields = dict(part.split("=", 1) for part in rest.split(",") if "=" in part)
                        with job.lock:
                            if category in ("HEALTH", "PC_CAN_HEALTH", "PERIODIC_HEALTH"):
                                job.telemetry["health"] = fields
                            elif category == "DEVICE_HEALTH":
                                job.telemetry["devices"][fields.get("device", "UNKNOWN")] = fields
                            elif category in ("BMS", "POWER", "MOTOR"):
                                group = job.telemetry["values"].setdefault(fields.get("device", "MOTOR") if category == "MOTOR" else category, {})
                                if "param" in fields:
                                    group[fields.get("name", fields["param"])] = fields
                                else:
                                    group.update(fields)
                    row = line.split(",")
                    is_bench=job.profile["cmake_options"].get("PICO_APP") in ("Can3Bench", "Can1Periodic", "Can2Periodic", "Can3Periodic")
                    if ((len(row) == 6 and is_bench) or len(row) == 8) and row[1] in ("RX", "TX_SUBMIT", "TX_DONE", "TX_TIMEOUT"):
                        if len(row)==6:
                            job.frame(row[1],row[3],row[5],row[0],row[2])
                        else:
                            job.frame(row[1] + (" / RTR" if row[4] == "RTR" else ""), row[5], row[7], row[0], row[3])
                        with job.lock:
                            metric = {"RX": "rx", "TX_SUBMIT": "tx", "TX_DONE": "done"}.get(row[1])
                            if metric:
                                job.metrics[metric] += 1
                if len(buffer) > 65536:
                    raise ValueError("串口数据缺少换行，请确认所选端口与波特率。")
            if buffer:
                out.write(buffer.decode("utf-8", errors="replace"))
        result = {"capture_only": True, "pass": False, "message": "采集完成；请依据健康统计与原始日志填写人工验收结论",
                  "seconds": seconds, "telemetry": job.telemetry, "metrics": job.metrics}
        self._save_check(job, path, result)
        return result

    def _save_check(self, job, path, result):
        report = path.with_suffix(".check.json")
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        job.files.append(report.name)
        job.log(result.get("message", "检查完成"))

    def _do_usbcan(self, job):
        if job.profile["cmake_options"].get("PICO_APP") == "Can3Bench":
            raise ValueError("此配置使用灵足AT协议，请使用开发控制台06按钮打开CAN3双向测试窗口。")
        path = LOGS / ("ui_usbcan_" + job.id + ".csv")
        job.files.append(path.name)
        frames, decoder, sent = [], Decoder(), 0
        with self._serial(job, 2000000) as dev, path.open("w", encoding="utf-8", newline="") as out:
            dev.reset_input_buffer()
            dev.write(settings_packet())
            dev.flush()
            job.phase_set("适配器已配置，5 秒后发送 100 帧")
            job.log("USB-CAN-A：串口 2000000，CAN 1 Mbps，正常模式；ID 固定 0x321，仅首字节自增。")
            for _ in range(50):
                job.checkpoint()
                time.sleep(0.1)
            dev.reset_input_buffer()
            writer = csv.writer(out)
            writer.writerow(["elapsed_ms", "event", "format", "id", "dlc", "data"])
            start = next_send = time.monotonic()
            job.phase_set("正在进行外部双向收发")
            while time.monotonic() - start < 16:
                job.checkpoint()
                now = time.monotonic()
                if sent < 100 and now >= next_send:
                    payload = bytes([sent]) + bytes.fromhex("88 77 66 55 44 33 22")
                    dev.write(data_packet(0x321, payload))
                    dev.flush()
                    ms = round((time.monotonic() - start) * 1000)
                    writer.writerow([ms, "TX_SUBMIT", "STD", "0x321", 8, payload.hex(" ").upper()])
                    job.frame("TX_SUBMIT", "0x321", payload.hex(" ").upper(), ms)
                    sent += 1
                    with job.lock:
                        job.metrics["tx"] = sent
                    next_send = time.monotonic() + 0.1
                for frame in decoder.feed(dev.read(dev.in_waiting or 1)):
                    frames.append(frame)
                    ms = round((time.monotonic() - start) * 1000)
                    fmt = "EXT" if frame.extended else "STD"
                    event = "RX_REMOTE" if frame.remote else "RX"
                    ident, data = f"0x{frame.identifier:03X}", frame.data.hex(" ").upper()
                    writer.writerow([ms, event, fmt, ident, len(frame.data), data])
                    job.frame(event, ident, data, ms, fmt)
                    with job.lock:
                        job.metrics["rx"] += 1
                    job.log(f"RX {ident}  {data}")
                out.flush()
        result = assess(frames, sent, decoder.malformed + bool(decoder.buffer))
        result["message"] = "电脑端检查" + ("通过" if result["pass"] else "未通过")
        self._save_check(job, path, result)
        return result
