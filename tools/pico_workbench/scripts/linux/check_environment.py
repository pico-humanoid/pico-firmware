"""Read-only checks. A build PASS is independent from physical board validation."""
import json
import os
from pathlib import Path
import subprocess
from serial.tools import list_ports

ROOT = Path(__file__).resolve().parents[2]
BUNDLES = Path.home() / ".local/share/stm32cube/bundles"
items = {
    "GCC": [BUNDLES / "gnu-tools-for-stm32/14.3.1+st.2/bin/arm-none-eabi-gcc", "--version"],
    "GDB": [BUNDLES / "gnu-gdb-for-stm32/14.3.1+st.2/bin/arm-none-eabi-gdb", "--version"],
    "CMake": [BUNDLES / "cmake/4.4.0+st.1/bin/cmake", "--version"],
    "Ninja": [BUNDLES / "ninja/1.13.2+st.1/bin/ninja", "--version"],
    "CubeProgrammer": [BUNDLES / "programmer/2.23.0/bin/STM32_Programmer_CLI", "--version"],
    "ST-LINK GDB Server": [BUNDLES / "stlink-gdbserver/7.14.0+st.2/bin/ST-LINK_gdbserver", "-h"],
}
good = True
for name, argv in items.items():
    try:
        r = subprocess.run([str(v) for v in argv], capture_output=True, text=True, timeout=15)
        passed = r.returncode == 0
        print(f"{'OK' if passed else 'FAIL'}  {name}")
        good &= passed
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"FAIL  {name}: {exc}")
        good = False
for relative in ("build/Ubuntu-Loopback/PICO_CAN.elf", "build/Ubuntu-External/PICO_CAN.elf"):
    passed = (ROOT / relative).is_file()
    print(f"{'OK' if passed else 'FAIL'}  {relative}")
    good &= passed
rules = Path('/etc/udev/rules.d/70-pico-serial.rules').is_file()
print(f"{'OK' if rules else '待安装'}  USB/串口访问规则")
ports = [p for p in list_ports.comports() if p.vid is not None or not p.device.startswith('/dev/ttyS')]
print("当前串口：")
for p in ports:
    print(f"  {p.device}: {p.description}；可读写={os.access(p.device, os.R_OK | os.W_OK)}")
if not ports:
    print("  无设备连接。软件检查不会代替实物验证。")
print(f"软件运行检查：{'PASS' if good else 'FAIL'}；USB 权限规则：{'已安装' if rules else '尚未完成'}")
raise SystemExit(0 if good and rules else 1)
