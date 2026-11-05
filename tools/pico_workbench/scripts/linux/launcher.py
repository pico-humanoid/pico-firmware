"""Local desktop launcher; actual board actions only start after a button click."""
from pathlib import Path
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

ROOT = Path(__file__).resolve().parents[2]


def launch(action):
    try:
        argv = ["bash", str(ROOT / "ubuntu.sh"), action]
        if action in {"open", "cubemx", "docs"}:
            subprocess.Popen(argv, cwd=ROOT)
        else:
            subprocess.Popen(["gnome-terminal", "--title=PICO CAN", "--", *argv, "--keep-open"], cwd=ROOT)
    except OSError as exc:
        messagebox.showerror("PICO", str(exc))


window = tk.Tk()
window.title("PICO · G474 CAN 开发环境")
window.geometry("700x750")
window.minsize(660, 720)
style = ttk.Style(window)
style.configure("TButton", font=("Noto Sans CJK SC", 13), padding=9)
frame = ttk.Frame(window, padding=22)
frame.pack(fill="both", expand=True)
ttk.Label(frame, text="NUCLEO-G474RE · Ubuntu", font=("Noto Sans CJK SC", 20, "bold")).pack(anchor="w", pady=(0, 8))
ttk.Label(frame, text="先编译，再选择需要的固件烧录。串口由设备自动识别。", font=("Noto Sans CJK SC", 11)).pack(anchor="w", pady=(0, 14))
for label, action in [
    ("01  打开 VS Code 工程", "open"),
    ("02  编译内部回环和外部 CAN", "build"),
    ("03  烧录内部回环", "loopback"),
    ("04  采集开发板日志（打开后按 RESET）", "capture"),
    ("05  烧录外部 CAN", "external"),
    ("06  USB-CAN 发送 100 帧并检查返回", "usbcan"),
    ("07  检查软件和已连接设备", "check"),
    ("08  打开 CubeMX 硬件配置", "cubemx"),
    ("09  查看 Ubuntu 操作说明", "docs"),
    ("10  安装 USB 权限（需要系统认证）", "permissions"),
]:
    ttk.Button(frame, text=label, command=lambda item=action: launch(item)).pack(fill="x", pady=3)
ttk.Label(frame, text="USB-CAN 入口适用于之前使用 USBCAN V2.12 的 CH340 串口协议适配器。", wraplength=610).pack(anchor="w", pady=(15, 0))
if not Path('/etc/udev/rules.d/70-pico-serial.rules').is_file():
    ttk.Label(frame, text="首次接板前，请点击 10 完成 USB 权限认证。", foreground="#B74222").pack(anchor="w", pady=(8, 0))
window.mainloop()
