"""Validate the BoardFsm firmware over the ST-LINK virtual COM port."""
import argparse
from datetime import datetime
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
for vendor in (HERE / "vendor", *(parent / "ui/vendor" for parent in HERE.parents),
               *(parent / "tools/pico_workbench/ui/vendor" for parent in HERE.parents)):
    if (vendor / "serial").is_dir():
        sys.path.insert(0, str(vendor))
        break

for folder in (HERE, next((parent / "scripts" for parent in HERE.parents
                          if (parent / "scripts/board_fsm_protocol.py").is_file()), HERE)):
    if (folder / "board_fsm_protocol.py").is_file():
        sys.path.insert(0, str(folder))
        break

from board_fsm_protocol import Bench, verify
from board_fsm_report import FsmReport, LEGEND


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", help="For example COM5 or /dev/ttyACM0")
    parser.add_argument("--list", action="store_true", help="List ports without opening them")
    args = parser.parse_args()
    try:
        import serial
        from serial.tools.list_ports import comports
    except ImportError:
        parser.error("pySerial is missing. Use the scripts in the supplied delivery folder.")
    if args.list:
        for port in comports():
            print(f"{port.device}  {port.description}")
        return 0
    if not args.port:
        parser.error("specify the ST-LINK virtual COM port or use --list")
    log_path = Path.cwd() / f"board-fsm-{datetime.now():%Y%m%d-%H%M%S-%f}.log"
    readable_path = log_path.with_name(log_path.stem + "_readable.log")
    try:
        with log_path.open("x", encoding="utf-8", buffering=1) as log, \
                readable_path.open("x", encoding="utf-8", buffering=1) as readable:
            readable.write("PICO 状态机单板验证 · 日志标志说明\n" + LEGEND + "\n--- 本次运行记录 ---\n")
            report = FsmReport(readable)
            report.start()
            try:
                with serial.Serial(args.port, 115200, timeout=0.2, write_timeout=1) as port:
                    verify(Bench(port, log, on_line=report.receive, on_command=report.command, on_step=report.step))
            except (OSError, RuntimeError) as exc:
                report.finish("FAIL", str(exc))
                log.write("BOARD_FSM_SERIAL_RESULT=FAIL\n")
                raise
            else:
                report.finish("PASS")
                log.write("BOARD_FSM_SERIAL_RESULT=PASS\n")
    except (OSError, RuntimeError) as exc:
        print(f"BOARD_FSM_SERIAL_RESULT=FAIL: {exc}", file=sys.stderr)
        print(log_path)
        print("中文说明日志：" + str(readable_path))
        return 1
    print("BOARD_FSM_SERIAL_RESULT=PASS (simulated motors)")
    print(log_path)
    print("中文说明日志：" + str(readable_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
