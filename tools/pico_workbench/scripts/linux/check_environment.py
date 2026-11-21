"""Read-only portable/system tool detection; never builds, flashes or opens a port."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "ui"), str(ROOT / "ui/vendor")]
import platform_tools as tools
from serial.tools import list_ports


def main():
    value = tools.status()
    value["serial_ports"] = [{"device": p.device, "description": p.description}
                             for p in list_ports.comports()]
    value["hardware_validation"] = "NOT_RUN"
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if value["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
