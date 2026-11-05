"""Read-only interpretation of board CSV, device comments and USB-CAN JSONL."""
from collections import Counter
import csv
from dataclasses import dataclass, field
import json
import math
import re

EVENT_NAMES = {
    "TX_SUBMIT": "提交发送", "TX_DONE": "硬件发送完成", "RX": "接收报文",
    "TX_TIMEOUT": "发送完成超时", "RX_REMOTE": "接收远程帧",
    "HEALTH": "总线健康", "DEVICE_HEALTH": "设备健康", "BMS": "BMS 数据",
    "POWER": "电源板数据", "RESULT": "固件结果", "START": "启动 / 配置",
    "SERIAL_SUBMITTED": "串口已提交", "SERIAL_WRITE_INTENT": "准备串口写入",
    "RX_RAW": "串口原始片段", "READ_REPLY": "解析后的回复", "INFO": "说明",
}
FIELD_NAMES = {
    "seen": "曾收到的类别掩码", "valid": "新鲜数据掩码", "replies": "有效回复",
    "invalid": "校验失败累计", "ignored": "忽略帧累计", "query_timeouts": "查询超时累计",
    "query_failures": "查询失败累计", "tx_submit": "发送提交累计", "tx_done": "发送完成累计",
    "tx_rejected": "提交拒绝累计", "tx_timeout": "发送超时累计", "bus_off": "总线关闭累计",
    "tec": "发送错误计数 TEC", "rec": "接收错误计数 REC", "rx_fifo_lost": "硬件 FIFO 丢失累计",
    "rx_queue_drop": "软件队列丢失累计", "rx_read_fail": "接收读取错误累计",
    "tx_event_lost": "发送事件丢失累计", "tx_event_unknown": "未知发送事件累计",
    "counters_ok": "错误计数读取正常", "cycles": "充放电循环次数", "pending": "等待回复",
    "query_index": "当前查询索引", "voltage_mv": "电池电压", "current_ma": "电池电流",
    "remaining_mah": "剩余容量", "full_mah": "满充容量", "soc_percent": "SOC",
    "temperature_decic": "温度", "battery_mv": "电池侧电压", "motor_mv": "电机侧电压",
    "temp_c": "温度", "branch_current_ma": "支路电流", "version": "版本",
    "voltage_v": "电池电压", "current_a": "电池电流", "remaining_capacity_ah": "剩余容量",
    "full_capacity_ah": "满充容量", "temperature_c": "温度", "crc_ok": "CRC 校验",
    "Can_baud": "CAN 速率参数", "Com_baud": "通信速率参数", "POWER_ID": "电源板 ID",
    "t_ms": "板端时间 ms", "device": "设备", "data": "原始数据", "id": "CAN ID",
    "crc16": "CRC16 原值", "crc_endian": "CRC 字节序", "note": "备注",
    "balance_low": "低位均衡标志", "balance_high": "高位均衡标志", "protection": "保护标志",
    "charge_mos_on": "充电 MOS 开启", "discharge_mos_on": "放电 MOS 开启",
    "mos_status_raw": "MOS 状态原值", "production_date_raw": "生产日期原值",
    "software_version_raw": "软件版本原值", "status_byte_order": "状态字节序",
    "big_candidate": "大端候选值", "little_candidate": "小端候选值",
    "big_candidate_A_AL_AR_LL_LR": "大端支路电流候选", "little_candidate_A_AL_AR_LL_LR": "小端支路电流候选",
    "fault_switch_bytes_raw": "故障 / 开关字节原值", "remoteCtrl": "远程控制参数",
    "fanspeedCtrl": "风速控制参数", "soundEffect": "提示音参数",
}
WARNING_COUNTERS = {"invalid", "query_timeouts", "query_failures", "tx_rejected", "tx_timeout",
                    "rx_fifo_lost", "rx_queue_drop", "rx_read_fail", "rx_unsupported",
                    "tx_event_lost", "tx_event_unknown", "tec", "rec", "rx_invalid", "fatal"}


def number(value):
    try:
        result = int(str(value), 0) if str(value).lower().startswith("0x") else float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def fields_of(line):
    return dict(piece.strip().split("=", 1) for piece in line.strip().rstrip(",").split(",")[1:]
                if "=" in piece)


def severity(raw, event="", values=None):
    values = values or {}
    upper = raw.upper()
    if event == "RESULT" or "# RESULT=" in upper:
        if re.search(r"\bRESULT=FAIL\b", upper):
            return "error", "固件报告 FAIL；独立验收需结合完整日志"
        if re.search(r"\bRESULT=PASS\b", upper):
            return "pass", "固件报告 PASS；不代替独立日志复核"
    if event == "TX_TIMEOUT":
        return "warning", "未及时观察到发送完成；需结合回复、TEC/REC 和事件统计"
    if re.search(r",TX_TIMEOUT,", upper):
        return "warning", "发送完成超时"
    if re.search(r"\bERROR\b|\bCRC MISMATCH\b|\bFAIL(?:ED)?\b", upper):
        return "error", "日志包含明确错误或失败信息"
    if values.get("crc_ok") is False or str(values.get("crc_ok")).lower() == "false":
        return "error", "CRC 校验失败"
    if number(values.get("bus_off")) not in (None, 0):
        return "error", "总线关闭累计计数非零；不表示每行都发生了一次新故障"
    nonzero = [FIELD_NAMES.get(k, k) + "=" + str(v) for k, v in values.items()
               if k in WARNING_COUNTERS and number(v) not in (None, 0)]
    if nonzero:
        return "warning", "累计 / 当前计数非零：" + "，".join(nonzero)
    if "UNCONFIRMED" in upper:
        return "warning", "字段含未确认值，不能作为已确认物理量"
    return "normal", ""


@dataclass
class Record:
    line: int
    raw: str
    event: str = "INFO"
    time: str = ""
    channel: str = ""
    format: str = ""
    kind: str = ""
    identifier: str = ""
    dlc: str = ""
    data: str = ""
    values: dict = field(default_factory=dict)
    level: str = "normal"
    explanation: str = ""

    @property
    def label(self):
        return EVENT_NAMES.get(self.event, self.event)

    @property
    def display_time(self):
        val = number(self.time)
        return f"{val / 1000:.3f}" if val is not None else self.time or "—"

    @property
    def description(self):
        if self.data:
            return self.data
        if self.kind == "RTR":
            return "远程请求，无数据载荷"
        if self.values:
            parts = []
            for key, value in self.values.items():
                if key not in ("t_ms", "device"):
                    display, unit = format_value(key, value)
                    parts.append(FIELD_NAMES.get(key, key) + ": " + display + (" " + unit if unit else ""))
            return "  ·  ".join(parts)
        return self.raw.lstrip("# ")


def parse_record(line, index):
    if not line.strip() or line.startswith(("t_ms,event,", "elapsed_ms,event,")):
        return None
    rec = Record(index, line)
    if line.lstrip().startswith("{"):
        try:
            item = json.loads(line)
        except ValueError:
            rec.level, rec.explanation = "warning", "JSON 行不完整或格式不正确，原文已保留"
            return rec
        if not isinstance(item, dict):
            return rec
        original = str(item.get("event", "INFO"))
        rec.event = "RX" if original == "can" else original.upper()
        rec.time = str(float(item["elapsed_s"]) * 1000) if number(item.get("elapsed_s")) is not None else str(item.get("time", ""))
        rec.channel = "USB-CAN"
        rec.identifier = str(item.get("id", ""))
        if "extended" in item:
            rec.format = "EXT" if item["extended"] else "STD"
        rec.kind = "RTR" if item.get("remote") else "DATA"
        rec.dlc, rec.data = str(item.get("dlc", "")), str(item.get("data", "")).upper()
        rec.values = {k: v for k, v in item.items() if k not in
                      ("event", "time", "elapsed_s", "id", "dlc", "data", "raw", "extended", "remote")}
        if not rec.data and original in ("rx_raw", "serial_submitted", "serial_write_intent"):
            rec.data = str(item.get("raw", "")).upper()
    elif line.startswith("#"):
        body = line[1:].strip()
        rec.event = body.split(",", 1)[0]
        if body.startswith("RESULT="):
            rec.event = "RESULT"
            rec.values = dict(p.split("=", 1) for p in body.replace(",", " ").split() if "=" in p)
        elif rec.event in ("HEALTH", "DEVICE_HEALTH", "BMS", "POWER"):
            rec.values = fields_of(body)
        elif "PICO" in body or body.startswith("mode="):
            rec.event = "START"
        else:
            rec.event = "INFO"
        rec.time = str(rec.values.get("t_ms", ""))
        rec.channel = str(rec.values.get("device", ""))
    else:
        try:
            row = next(csv.reader([line]))
        except csv.Error:
            row = []
        if len(row) in (6, 8) and row[1] in ("TX_SUBMIT", "TX_DONE", "RX", "RX_REMOTE", "TX_TIMEOUT"):
            if len(row) == 8:
                rec.time, rec.event, rec.channel, rec.format, rec.kind, rec.identifier, rec.dlc, rec.data = row
            else:
                rec.time, rec.event, rec.format, rec.identifier, rec.dlc, rec.data = row
                rec.kind = "RTR" if rec.event == "RX_REMOTE" else "DATA"
            rec.data = rec.data.upper()
    rec.level, rec.explanation = severity(line, rec.event, rec.values)
    return rec


def parse(text):
    if text.lstrip().startswith(("{", "[")):
        try:
            doc = json.loads(text)
            if isinstance(doc, (dict, list)) and not (isinstance(doc, dict) and "event" in doc):
                return [Record(1, text, data="JSON 文档，完整内容见原始日志 / 复核摘要")]
        except ValueError:
            pass  # Multiple JSONL objects are parsed one line at a time.
    return [record for i, line in enumerate(text.splitlines(), 1) if (record := parse_record(line, i))]


def matches(rec, search="", category="全部", ident=""):
    if search.casefold() not in (rec.raw + " " + rec.label).casefold():
        return False
    if ident:
        requested = ident.strip().lower()
        if requested.startswith("0x"):
            requested = requested[2:]
        try:
            if int(rec.identifier, 16) != int(requested, 16):
                return False
        except ValueError:
            return False
    if category == "全部":
        return True
    if category == "报文":
        return rec.event in ("TX_SUBMIT", "TX_DONE", "RX", "RX_REMOTE", "TX_TIMEOUT")
    if category in ("异常 / 提示", "错误 / FAIL"):
        return rec.level in ("warning", "error")
    if category == "解析数据":
        return rec.event in ("BMS", "POWER", "READ_REPLY")
    if category in ("健康状态", "HEALTH"):
        return rec.event in ("HEALTH", "DEVICE_HEALTH")
    return rec.event == category


def summarize(records):
    count = Counter(rec.event for rec in records)
    result = next((rec for rec in reversed(records) if rec.event == "RESULT"), None)
    return {"tx": count["TX_SUBMIT"], "done": count["TX_DONE"], "rx": count["RX"] + count["RX_REMOTE"],
            "warnings": sum(r.level in ("warning", "error") for r in records),
            "result": "固件 PASS" if result and result.level == "pass" else
                      "固件 FAIL" if result and result.level == "error" else "未提供固件结论"}


def format_value(key, value):
    units = {"voltage_mv": ("V", 1000), "current_ma": ("A", 1000), "remaining_mah": ("Ah", 1000),
             "full_mah": ("Ah", 1000), "temperature_decic": ("°C", 10), "battery_mv": ("V", 1000),
             "motor_mv": ("V", 1000), "branch_current_ma": ("A", 1000), "temp_c": ("°C", 1),
             "voltage_v": ("V", 1), "current_a": ("A", 1), "temperature_c": ("°C", 1),
             "remaining_capacity_ah": ("Ah", 1), "full_capacity_ah": ("Ah", 1), "soc_percent": ("%", 1)}
    if key in units:
        unit, divisor = units[key]
        parts = value if isinstance(value, (list, tuple)) else str(value).split("/")
        if all(number(part) is not None for part in parts):
            return " / ".join(f"{number(part)/divisor:g}" for part in parts), unit
    if isinstance(value, bool):
        return "是" if value else "否", ""
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value), ""


def device_values(records):
    latest = {}
    for rec in records:
        if rec.event not in ("BMS", "POWER", "READ_REPLY"):
            continue
        device = rec.event if rec.event in ("BMS", "POWER") else "设备回复"
        values = rec.values
        if "name" in values and ("param" in values or "index" in values):
            key = str(values["name"])
            value = values.get("value_u8", values.get("value_milli_candidate", values.get("value_float32_le_candidate", values.get("raw", values.get("raw_value", "")))))
            note = "原始参数；完整标志见详情"
            if "value_milli_candidate" in values:
                note = "候选值，按固件原始缩放显示；单位与有效性见详情"
            if "value_float32_le_candidate" in values:
                note = "浮点候选值，单位未在此日志中确认"
            if str(values.get("numeric_valid")) == "0":
                note += "；数值未确认有效"
            if key == "Can_baud":
                note += "；" + {1: "1 Mbps", 2: "500 Kbps"}.get(number(value), "编码未解释")
            latest[(device, key)] = (rec, value, note)
        else:
            for key, value in values.items():
                if key not in ("cycle", "query", "host_elapsed_since_send_ms"):
                    latest[(device, key)] = (rec, value, "含未确认字段" if "UNCONFIRMED" in str(value) or "candidate" in key else "")
    priorities = ["voltage_mv", "voltage_v", "current_ma", "current_a", "soc_percent", "remaining_mah",
                  "remaining_capacity_ah", "full_mah", "full_capacity_ah", "temperature_decic", "temperature_c",
                  "battery_mv", "motor_mv", "temp_c", "branch_current_ma", "version", "Can_baud", "Com_baud"]
    order = {key: i for i, key in enumerate(priorities)}
    entries = sorted(latest.items(), key=lambda pair: (pair[0][0], order.get(pair[0][1], len(order))))
    return [(device, FIELD_NAMES.get(key, key), *format_value(key, value), str(value), rec.line, note, key)
            for (device, key), (rec, value, note) in entries]


def health_values(records):
    groups = {}
    for rec in records:
        if rec.event in ("HEALTH", "DEVICE_HEALTH"):
            groups[rec.channel or "总线"] = rec
    rows = []
    for group, rec in groups.items():
        for key, value in rec.values.items():
            if key not in ("device", "t_ms"):
                level = "error" if key == "bus_off" and number(value) not in (0, None) else (
                    "warning" if key in WARNING_COUNTERS and number(value) not in (0, None) else "normal")
                rows.append((group, "轮询周期累计" if key == "cycles" else FIELD_NAMES.get(key, key), str(value), rec.display_time, rec.line, level))
    return rows
