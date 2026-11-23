"""Desktop panel for the simulated, board-only state machine experiment."""
import os
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from engine import LOGS, ROOT, ports
from board_fsm_protocol import MODE_NAMES as MODE, VERIFY_STEPS
from board_fsm_report import LEGEND, led_text

PROFILE = "BoardFsm"
FAULT = {"NONE": "无", "LOCAL_CHECK_FAILED": "板端自检失败",
         "SELF_CHECK_TIMEOUT": "自检确认超时", "MODE_TIMEOUT": "模式切换确认超时"}
VERDICT = {"RUNNING": "正在验证", "PASS": "通过", "FAIL": "未通过"}


class BoardFsmPanel:
    def __init__(self, parent, manager, selected_port=""):
        self.manager = manager
        self.job = None
        self.cursor = 0
        self.timer = None
        self.window = tk.Toplevel(parent)
        self.window.title("PICO · 状态机单板验证")
        self.window.geometry("1100x860")
        self.window.minsize(920, 700)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.grab_set()

        body = ttk.Frame(self.window, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="状态机单板验证", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="只接 NUCLEO-G474RE 和 ST-LINK USB。电机反馈为模拟值，固件关闭 CAN。",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 10))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=4)
        self.build = ttk.Button(row, text="编译固件", command=lambda: self.start("build"))
        self.flash = ttk.Button(row, text="烧录固件", command=lambda: self.start("flash"))
        self.build.pack(side="left")
        self.flash.pack(side="left", padx=6)
        self.port = ttk.Combobox(row, state="readonly", width=36)
        self.port.pack(side="left", fill="x", expand=True, padx=6)
        self.refresh = ttk.Button(row, text="刷新串口", command=self.refresh_ports)
        self.refresh.pack(side="left")
        self.connect = ttk.Button(row, text="连接", command=lambda: self.start("fsm"))
        self.connect.pack(side="left", padx=6)
        self.disconnect = ttk.Button(row, text="断开", command=lambda: self.send("DISCONNECT"))
        self.disconnect.pack(side="left")
        self.refresh_ports(selected_port)

        row = ttk.Frame(body)
        row.pack(fill="x", pady=10)
        self.buttons = {}
        for key, label in (("ZERO", "请求零力矩"), ("DAMP", "请求阻尼"),
                           ("DEBUG", "进入调试预留"), ("RESET", "重新自检"), ("VERIFY", "一键验证")):
            button = ttk.Button(row, text=label, command=lambda k=key: self.send(k), state="disabled")
            button.pack(side="left", padx=(0, 6))
            self.buttons[key] = button
        ttk.Button(row, text="状态图与灯光", command=self.show_diagram).pack(side="left", padx=(8, 0))
        self.mode = tk.StringVar(value="状态：未连接")
        self.detail = tk.StringVar(value="选定 ST-LINK 虚拟串口后连接，开发板会周期上报状态。")
        self.result = tk.StringVar(value="一键验证：尚未运行")
        self.phase = tk.StringVar(value="可以先编译并烧录，或直接连接已烧录的开发板。")
        self.log_path = tk.StringVar()
        self.mode_label = ttk.Label(body, textvariable=self.mode, font=("", 15, "bold"))
        self.mode_label.pack(anchor="w", pady=3)
        ttk.Label(body, textvariable=self.detail, wraplength=1000).pack(anchor="w", pady=3)
        self.result_label = ttk.Label(body, textvariable=self.result, font=("", 12, "bold"))
        self.result_label.pack(anchor="w", pady=3)
        ttk.Label(body, textvariable=self.phase, wraplength=1000).pack(anchor="w", pady=3)
        ttk.Label(body, textvariable=self.log_path, wraplength=1000,
                  style="Muted.TLabel").pack(anchor="w", pady=3)

        panes = ttk.Panedwindow(body, orient="vertical")
        panes.pack(fill="both", expand=True, pady=(6, 0))
        progress = ttk.LabelFrame(panes, text="逐项验收 · 看到“步骤通过”才表示该项已满足", padding=6)
        panes.add(progress, weight=1)
        self.steps = ttk.Treeview(progress, columns=("name", "expected", "status"), show="headings", height=8)
        for key, title, width in (("name", "验证项目", 180), ("expected", "应该看到的现象", 540),
                                  ("status", "验收结果", 110)):
            self.steps.heading(key, text=title)
            self.steps.column(key, width=width, minwidth=90, stretch=key != "status")
        for index, (name, expected) in enumerate(VERIFY_STEPS, 1):
            self.steps.insert("", "end", iid=str(index), values=(f"{index}. {name}", expected, "尚未运行"))
        self.steps.tag_configure("PASS", foreground="#08745c")
        self.steps.tag_configure("FAIL", foreground="#be3030")
        self.steps.tag_configure("RUNNING", foreground="#155cb0")
        step_scroll = ttk.Scrollbar(progress, orient="vertical", command=self.steps.yview)
        self.steps.configure(yscrollcommand=step_scroll.set)
        step_scroll.pack(side="right", fill="y")
        self.steps.pack(side="left", fill="both", expand=True)

        self.tabs = ttk.Notebook(panes)
        panes.add(self.tabs, weight=2)
        self.output = self.make_log_tab("中文运行日志")
        self.raw_output = self.make_log_tab("原始报文")
        self.legend_output = self.make_log_tab("标志说明（点这里看含义）")
        self.append(LEGEND, self.legend_output)
        self.append("[阅读提示] 左侧中文日志解释每条消息；中间保留原始报文；右侧说明所有标志和字段。\n")
        self.poll()

    def show_diagram(self):
        dialog = tk.Toplevel(self.window)
        dialog.title("PICO · 状态转移与 LD2 灯光")
        dialog.transient(self.window)
        try:
            image = tk.PhotoImage(master=dialog, file=str(ROOT / "ui" / "data" / "board-fsm-led.png"))
        except tk.TclError as exc:
            dialog.destroy()
            messagebox.showerror("无法打开状态图", str(exc), parent=self.window)
            return
        dialog.geometry(f"{min(image.width() + 18, dialog.winfo_screenwidth() - 60)}x"
                        f"{min(image.height() + 18, dialog.winfo_screenheight() - 110)}")
        canvas = tk.Canvas(dialog, highlightthickness=0, background="#f7f9fc",
                           scrollregion=(0, 0, image.width(), image.height()))
        canvas.diagram_image = image
        canvas.create_image(0, 0, image=image, anchor="nw")
        for axis, row, col in (("y", 0, 1), ("x", 1, 0)):
            scroll = ttk.Scrollbar(dialog, orient="vertical" if axis == "y" else "horizontal",
                                   command=getattr(canvas, axis + "view"))
            canvas.configure(**{axis + "scrollcommand": scroll.set})
            scroll.grid(row=row, column=col, sticky="ns" if axis == "y" else "ew")
        canvas.grid(row=0, column=0, sticky="nsew")
        dialog.rowconfigure(0, weight=1)
        dialog.columnconfigure(0, weight=1)

        def close_diagram():
            dialog.destroy()
            self.window.grab_set()

        dialog.protocol("WM_DELETE_WINDOW", close_diagram)
        dialog.bind("<Escape>", lambda _event: close_diagram())
        dialog.wait_visibility()
        dialog.grab_set()

    def make_log_tab(self, title):
        frame = ttk.Frame(self.tabs)
        self.tabs.add(frame, text=title)
        font = "Microsoft YaHei UI" if os.name == "nt" else "Noto Sans CJK SC"
        widget = scrolledtext.ScrolledText(frame, wrap="word", state="disabled", height=10, font=(font, 11))
        widget.pack(fill="both", expand=True)
        for tag, color in (("pass", "#08745c"), ("fail", "#be3030"),
                           ("expected", "#985900"), ("send", "#155cb0")):
            widget.tag_configure(tag, foreground=color)
        return widget

    def refresh_ports(self, selected=""):
        previous = self.port.current()
        device = selected or (self.ports[previous]["device"] if previous >= 0 else "")
        self.ports = [port for port in ports() if port["kind"] == "board"]
        self.port["values"] = [p["device"] + " · " + p["name"] for p in self.ports]
        match = next((i for i, port in enumerate(self.ports) if port["device"] == device), -1)
        if match >= 0 or len(self.ports) == 1:
            self.port.current(max(0, match))
        else:
            self.port.set("")

    def append(self, lines, target=None):
        widget = target or self.output
        widget.configure(state="normal")
        for line in lines.splitlines(keepends=True):
            tag = ""
            if any(mark in line for mark in ("[步骤失败]", "[整体验证失败]", "[异常报警]")):
                tag = "fail"
            elif any(mark in line for mark in ("[步骤通过]", "[整体验证通过]")):
                tag = "pass"
            elif "[预期保护]" in line or "[故障注入]" in line:
                tag = "expected"
            elif "[电脑发送]" in line or "[步骤开始]" in line:
                tag = "send"
            widget.insert("end", line, tag)
        if int(widget.index("end-1c").split(".")[0]) > 2000:
            widget.delete("1.0", "201.0")
        widget.see("end")
        widget.configure(state="disabled")

    def start(self, kind):
        port = ""
        if kind == "fsm":
            index = self.port.current()
            if index < 0:
                self.phase.set("请选择 ST-LINK 虚拟串口。")
                return
            port = self.ports[index]["device"]
        try:
            self.job = self.manager.start(kind, PROFILE, port)
        except ValueError as exc:
            self.phase.set(str(exc))
            return
        self.cursor = 0
        self.append("\n")
        if kind == "fsm":
            self.result.set("一键验证：尚未运行")
            self.log_path.set("")
            for index, (name, expected) in enumerate(VERIFY_STEPS, 1):
                self.steps.item(str(index), values=(f"{index}. {name}", expected, "尚未运行"), tags=())
        self.render(self.job.snapshot())

    def send(self, command):
        if not self.job:
            return
        try:
            self.manager.fsm_command(self.job, command)
        except ValueError as exc:
            self.phase.set(str(exc))
        else:
            self.render(self.job.snapshot())

    def render(self, snapshot):
        active = snapshot["status"] == "running"
        connected = active and snapshot["kind"] == "fsm"
        telemetry = snapshot["telemetry"]
        state = telemetry.get("fsm") if snapshot["kind"] == "fsm" else None
        busy = telemetry.get("busy", False) if connected else False
        self.phase.set(snapshot["phase"])
        ready = connected and state and not busy and state["pending"] == "0"
        for key, button in self.buttons.items():
            allowed = ready and (key not in ("ZERO", "DAMP", "DEBUG") or state["state"] != "FAULT_LOCKED")
            button.configure(state="normal" if allowed else "disabled")
        for button in (self.build, self.flash, self.connect, self.refresh):
            button.configure(state="disabled" if active else "normal")
        self.port.configure(state="disabled" if active else "readonly")
        self.disconnect.configure(state="normal" if connected and not busy else "disabled")
        if state:
            self.mode.set(("当前状态：" if connected else "最后记录的状态（已断开）：") + MODE[state["state"]] +
                          (" → " + MODE[state["target"]] + "（等待确认）" if state["pending"] == "1" else ""))
            expected_fault = (telemetry.get("validation") == "RUNNING" and telemetry.get("fsm_step") in (6, 7, 8)
                              and state["fault"] == "MODE_TIMEOUT" and state["target"] == "DAMPING"
                              and state["ack1"] == "1" and state["ack2"] == "0")
            self.detail.set("模拟反馈 · 电机1 {} / 电机2 {} · {}{} · LD2：{}"
                            .format("已确认" if state["ack1"] == "1" else "未确认",
                                    "已确认" if state["ack2"] == "1" else "未确认",
                                    "预期保护测试 · " if expected_fault else "故障：",
                                    FAULT[state["fault"]], led_text(state)))
            self.mode_label.configure(foreground="#985900" if expected_fault else
                                      "#be3030" if state["state"] == "FAULT_LOCKED" else "#155cb0")
        else:
            self.mode.set("状态：" + ("等待固件识别" if connected else "未连接"))
            self.detail.set("无实时板端反馈。")
        if "validation" in telemetry:
            validation = telemetry["validation"]
            count = sum(step["status"] == "PASS" for step in telemetry.get("fsm_steps", []))
            self.result.set(f"一键验证：{VERDICT[validation]} · 已通过 {count}/8 项（单板模拟验收记录）")
            self.result_label.configure(foreground={"RUNNING": "#155cb0", "PASS": "#08745c", "FAIL": "#be3030"}[validation])
        for index, step in enumerate(telemetry.get("fsm_steps", []), 1):
            name, expected = VERIFY_STEPS[index - 1]
            status = step["status"]
            label = {"WAITING": "尚未执行", "RUNNING": "正在验证", "PASS": "通过", "FAIL": "未通过"}[status]
            values = (f"{index}. {name}", step.get("detail") or expected, label)
            if self.steps.item(str(index), "values") != values:
                self.steps.item(str(index), values=values, tags=(status,))
        if snapshot["kind"] == "fsm" and snapshot["files"]:
            readable = snapshot["files"][1] if len(snapshot["files"]) > 1 else snapshot["files"][0]
            self.log_path.set("中文日志：" + str(LOGS / readable) + "（原始报文保存在同目录）")

    def poll(self):
        if self.job:
            snapshot = self.job.snapshot(True, self.cursor)
            if snapshot["lines"]:
                for row in snapshot["lines"]:
                    line = row["text"]
                    if line.startswith(("[原始接收]", "[原始发送]", "[原始结果]")):
                        self.append(line + "\n", self.raw_output)
                    else:
                        self.append(line + "\n")
                self.cursor = snapshot["sequence"]
            self.render(snapshot)
        else:
            self.disconnect.configure(state="disabled")
        self.timer = self.window.after(120, self.poll)

    def close(self):
        if self.job and self.job.status == "running":
            if self.job.kind == "flash":
                messagebox.showinfo("正在烧录", "请等待写入和校验完成。", parent=self.window)
                return
            self.manager.stop(self.job.id)
        if self.timer is not None:
            self.window.after_cancel(self.timer)
        self.window.destroy()
