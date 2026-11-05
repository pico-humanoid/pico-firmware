"""Editable experiment definitions and record annotations, kept apart from raw evidence."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import threading
import uuid
from runtime_paths import project_root

ROOT = project_root()
STATE = ROOT / "ui/state"
LOCK = threading.RLock()


def load(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def builtins():
    items = [
        {"id": "Loopback", "name": "内部回环", "description": "当前 100 帧内部回环固件与完整性检查。",
         "base_mode": "Loopback", "project_dir": str(ROOT), "build_type": "Debug",
         "elf_name": "PICO_CAN.elf", "toolchain": "cmake/gcc-arm-none-eabi.cmake",
         "cmake_options": {}, "board_baud": 115200, "builtin": True},
        {"id": "External", "name": "外部双向收发", "description": "当前 CAN1 / 1 Mbps / 标准帧 100 帧验证。",
         "base_mode": "External", "project_dir": str(ROOT), "build_type": "Debug",
         "elf_name": "PICO_CAN.elf", "toolchain": "cmake/gcc-arm-none-eabi.cmake",
         "cmake_options": {}, "board_baud": 115200, "builtin": True},
    ]
    device_root = ROOT / "projects/pico-firmware/firmware/PICO_CAN"
    if (device_root / "CMakeLists.txt").is_file():
        for ident, name, app, rate, dlc in [
            ("BMS-Read-500K", "BMS 只读 · 500K", "BMS", 500000, 8),
            ("Power-Read-1M", "电源板只读 · 1M", "Power", 1000000, 8),
            ("Power-Read-500K", "电源板只读 · 500K", "Power", 500000, 8),
            ("Dual-Read-500K", "BMS + 电源板 · 同总线 500K", "Dual", 500000, 0),
        ]:
            items.append({"id": ident, "name": name, "description": "GitHub 新增只读固件；FDCAN1；完整采集后另行验收，不使用旧 100 帧判据。",
                          "base_mode": "Device", "project_dir": str(device_root), "build_type": "Debug",
                          "elf_name": "PICO_CAN.elf", "toolchain": "cmake/gcc-arm-none-eabi.cmake",
                          "cmake_options": {"PICO_APP": app, "PICO_DEVICE_BITRATE": rate,
                              "PICO_POWER_ID": "0xAA", "PICO_BMS_RTR_DLC": dlc,
                              "PICO_BMS_CRC_ENDIAN": "BIG", "PICO_POWER_STATUS_ENDIAN": "BIG"},
                          "board_baud": 115200, "capture_seconds": 80, "builtin": True})
    return items


def profiles():
    with LOCK:
        return builtins() + load(STATE / "profiles.json", [])


def profile(ident):
    for item in profiles():
        if item["id"] == ident:
            return dict(item)
    raise ValueError("找不到实验配置，请重新选择。")


def save_profile(value):
    with LOCK:
        ident = value.get("id") or "exp_" + uuid.uuid4().hex[:10]
        if ident in {p["id"] for p in builtins()}:
            raise ValueError("内置配置保留为基线。请复制后保存为自定义配置。")
        if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,47}", ident):
            raise ValueError("配置标识格式不正确。")
        name = str(value.get("name", "")).strip()
        if not name or len(name) > 80:
            raise ValueError("请填写 1–80 字的实验名称。")
        base = value.get("base_mode", "Custom")
        if base not in ("Loopback", "External", "Custom", "Device"):
            raise ValueError("未知验收方式。")
        directory = Path(value.get("project_dir") or ROOT).expanduser()
        directory = (ROOT / directory).resolve() if not directory.is_absolute() else directory.resolve()
        if not (directory / "CMakeLists.txt").is_file():
            raise ValueError("项目目录中没有 CMakeLists.txt。请先用 CubeMX 建立 CMake 工程。")
        build_type = value.get("build_type", "Debug")
        if build_type not in ("Debug", "Release", "RelWithDebInfo", "MinSizeRel"):
            raise ValueError("不支持的构建类型。")
        elf_name = value.get("elf_name", "PICO_CAN.elf")
        if not isinstance(elf_name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.elf", elf_name):
            raise ValueError("固件名称应是构建目录中的 .elf 文件名。")
        options = value.get("cmake_options", {})
        if not isinstance(options, dict) or len(options) > 40:
            raise ValueError("CMake 参数应为 JSON 对象，最多 40 项。")
        for key, val in options.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or not isinstance(val, (str, int, bool)):
                raise ValueError("CMake 参数名或值无效。")
            if key in ("CMAKE_HOME_DIRECTORY", "CMAKE_TOOLCHAIN_FILE", "CMAKE_MAKE_PROGRAM", "CMAKE_BUILD_TYPE"):
                raise ValueError("请用专门字段设置工程、工具链和构建类型。")
        baud = int(value.get("board_baud", 115200))
        if baud not in (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600, 2000000):
            raise ValueError("不支持的日志串口波特率。")
        chain = str(value.get("toolchain", "")).strip()
        if chain and not (directory / chain).resolve().is_file():
            raise ValueError("所填工具链文件不存在。")
        seconds = int(value.get("capture_seconds", 80))
        if not 10 <= seconds <= 3600:
            raise ValueError("采集时长应为 10–3600 秒。")
        try:
            saved_directory = str(directory.relative_to(ROOT.resolve())).replace("\\", "/") or "."
        except ValueError:
            saved_directory = str(directory)
        item = {"id": ident, "name": name, "description": str(value.get("description", ""))[:2000],
                "base_mode": base, "project_dir": saved_directory, "build_type": build_type,
                "elf_name": elf_name, "toolchain": chain, "cmake_options": options,
                "board_baud": baud, "capture_seconds": seconds, "builtin": False}
        entries = load(STATE / "profiles.json", [])
        entries = [p for p in entries if p["id"] != ident] + [item]
        write(STATE / "profiles.json", entries)
        return item


def delete_profile(ident):
    if profile(ident)["builtin"]:
        raise ValueError("内置配置不能删除，可创建自己的实验配置。")
    with LOCK:
        write(STATE / "profiles.json", [p for p in profiles() if not p["builtin"] and p["id"] != ident])


def record_file(ident):
    if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", ident):
        raise ValueError("记录标识无效。")
    file = ROOT / "logs/ui_records" / (ident + ".json")
    if not file.is_file():
        raise ValueError("找不到此实验记录。")
    return file


def annotations():
    return load(STATE / "record_notes.json", {})


def annotate(value):
    ident = value.get("id")
    record_file(ident)
    with LOCK:
        notes = annotations()
        old = notes.get(ident, {})
        entry = dict(old)
        for key, maximum in (("title", 160), ("participants", 200), ("purpose", 3000),
                             ("hardware", 2000), ("notes", 12000)):
            if key in value:
                if not isinstance(value[key], str):
                    raise ValueError("记录内容应为文字。")
                entry[key] = value[key][:maximum]
        if "conclusion" in value:
            if value["conclusion"] not in ("pending", "pass", "fail", "incomplete"):
                raise ValueError("请选择有效的人工结论。")
            entry["conclusion"] = value["conclusion"]
        if "archived" in value:
            if not isinstance(value["archived"], bool):
                raise ValueError("归档状态无效。")
            entry["archived"] = value["archived"]
        entry["updated"] = datetime.now().isoformat(timespec="seconds")
        notes[ident] = entry
        write(STATE / "record_notes.json", notes)
        return entry


def new_record(value):
    item = profile(value.get("mode", "Loopback"))
    ident = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    original = {"id": ident, "kind": "manual", "mode": item["id"], "profile_name": item["name"],
                "status": "recorded", "phase": "人工实验记录", "started": datetime.now().isoformat(timespec="seconds"),
                "ended": None, "metrics": {}, "result": None, "files": [], "board_job": None}
    with LOCK:
        write(ROOT / "logs/ui_records" / (ident + ".json"), original)
        return {"id": ident, "annotation": annotate(dict(value, id=ident))}
