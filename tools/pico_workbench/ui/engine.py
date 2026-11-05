"""Task execution, real serial captures, and persisted experiment records."""
from collections import deque
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid
from runtime_paths import project_root

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
        if kind not in ("build", "flash", "board", "usbcan"):
            raise ValueError("不支持此操作。")
        tools.validate_mode(mode)
        if kind in ("board", "usbcan"):
            if not port or port not in {p["device"] for p in ports()}:
                raise ValueError("请选择已连接的串口，然后重试。")
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
        if not programmer:
            raise ValueError("未找到 STM32CubeProgrammer。")
        job.phase_set("正在识别 ST-LINK")
        output = self.command(job, [programmer, "-l", "st-link"], collect=True)
        probes = re.findall(r"ST-LINK SN\s*:\s*(\S+)", output)
        if len(probes) != 1:
            raise ValueError("需要连接恰好一块 ST-LINK 开发板；当前识别到 " + str(len(probes)) + " 块。")
        job.phase_set("正在写入固件、校验并复位")
        self.command(job, [programmer, "-c", "port=SWD", "freq=1000", "sn=" + probes[0],
                           "-w", str(image), "-v", "-rst"])
        return {"pass": True, "message": "烧录和校验成功；测试结果以实际日志为准",
                "image": str(image), "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}

    def _serial(self, job, baud):
        kwargs = {"exclusive": True} if os.name != "nt" else {}
        return serial.Serial(job.port, baud, timeout=0.01 if job.kind == "usbcan" else 0.08,
                             write_timeout=1, **kwargs)

    def _do_board(self, job):
        if job.profile["base_mode"] in ("Custom", "Device"):
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
                    if line.startswith("# "):
                        category, _, rest = line[2:].partition(",")
                        fields = dict(part.split("=", 1) for part in rest.split(",") if "=" in part)
                        with job.lock:
                            if category == "HEALTH":
                                job.telemetry["health"] = fields
                            elif category == "DEVICE_HEALTH":
                                job.telemetry["devices"][fields.get("device", "UNKNOWN")] = fields
                            elif category in ("BMS", "POWER"):
                                group = job.telemetry["values"].setdefault(category, {})
                                if "param" in fields:
                                    group[fields.get("name", fields["param"])] = fields
                                else:
                                    group.update(fields)
                    row = line.split(",")
                    if len(row) == 8 and row[1] in ("RX", "TX_SUBMIT", "TX_DONE", "TX_TIMEOUT"):
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
