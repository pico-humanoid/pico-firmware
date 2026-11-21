"""Capture actual board logs and verify them with the existing independent checker."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time
import serial
from ports import choose_port

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from check_log import check


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port")
    parser.add_argument("--seconds", type=float, default=300)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "logs")
    args = parser.parse_args()
    port = choose_port("board", args.port)
    logs = args.output_dir
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / ("linux_board_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".csv")
    lines, external, observed = [], False, False
    with serial.Serial(port, 115200, timeout=0.3, exclusive=True) as dev, path.open("w", encoding="utf-8") as output:
        print(f"串口 {port} 已打开，115200 8N1。现在按开发板 RESET。", flush=True)
        print(f"日志：{path}\n最长等待 {args.seconds:g} 秒；外部测试需先启动 USB-CAN 发送。", flush=True)
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            raw = dev.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            lines.append(line)
            output.write(line + "\n")
            output.flush()
            print(line, flush=True)
            if "mode=EXTERNAL_NORMAL" in line:
                external = True
            if any(event in line for event in (",RX,", ",TX_SUBMIT,", ",TX_DONE,")):
                if not observed:
                    deadline = time.monotonic() + 25
                observed = True
            if line.startswith("# RESULT="):
                result = check("\n".join(lines), external=external)
                path.with_suffix(".check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print("日志完整性复核：" + ("通过" if result["pass"] else "未通过"), flush=True)
                if not result["pass"]:
                    print("\n".join(result["errors"]), flush=True)
                return 0 if result["pass"] else 1
    if external and not observed:
        print("等待超时：尚无有效 CAN 测试数据。检查 USB-CAN 是否发送标准数据帧 0x321，数据为 序号 88 77 66 55 44 33 22。")
    else:
        print("未得到完整测试结果。确认已按 RESET，检查保存的原始日志。")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, serial.SerialException) as exc:
        print(f"无法采集：{exc}", file=sys.stderr)
        raise SystemExit(2)
