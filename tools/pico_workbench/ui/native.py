"""Native Windows/Ubuntu launcher and standalone log viewer; no browser/server required."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
import webbrowser

import catalog
from engine import LOGS, Manager, ports
import platform_tools as tools
from log_viewer import LogViewer, error_line

FONT = "Microsoft YaHei UI" if tools.WINDOWS else "Noto Sans CJK SC"
NAMES = {"build": "编译", "flash": "烧录", "board": "板端采集", "usbcan": "USB-CAN 测试", "manual": "人工记录"}
STATUS = {"running": "进行中", "pass": "通过", "fail": "未通过", "error": "操作异常",
          "cancelled": "已停止", "recorded": "已记录 / 待验收"}


def open_folder(path):
    if tools.WINDOWS:
        os.startfile(str(path))
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Desktop:
    def __init__(self, root):
        self.root, self.manager, self.cursor, self.current = root, Manager(), 0, ""
        self.root.title("PICO 开发控制台 · 桌面版")
        self.root.geometry("860x880")
        self.root.minsize(740, 730)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="PICO · G474 开发控制台", font=(FONT, 20, "bold")).pack(anchor="w")
        ttk.Label(frame, text="选择实验 → 打开软件或执行任务。所有操作在本机完成。", foreground="#65788e").pack(anchor="w", pady=(6, 14))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text="实验配置").pack(side="left", padx=(0, 12))
        self.mode = ttk.Combobox(row, state="readonly")
        self.mode.pack(side="left", fill="x", expand=True)
        self.mode.bind("<<ComboboxSelected>>", self.change_mode)
        ttk.Button(row, text="新增配置", command=lambda: self.edit_profile()).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="复制 / 编辑", command=lambda: self.edit_profile(self.profile())).pack(side="left", padx=6)
        self.path_label = tk.StringVar()
        ttk.Label(frame, textvariable=self.path_label, wraplength=780, foreground="#5c7692").pack(anchor="w", pady=(8, 12))
        for kind, label in (("board", "开发板日志串口"), ("usbcan", "USB-CAN 串口")):
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=17).pack(side="left")
            combo = ttk.Combobox(row, state="readonly")
            combo.pack(side="left", fill="x", expand=True)
            setattr(self, kind + "_port", combo)
            if kind == "board":
                ttk.Button(row, text="刷新设备", command=self.refresh_ports).pack(side="left", padx=(8, 0))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=15)
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        self.action_buttons = {}
        for i, (name, command) in enumerate([
            ("01  打开 VS Code 对应项目", lambda: self.open_app("vscode")),
            ("02  打开 CubeMX 配置", lambda: self.open_app("cubemx")),
            ("03  编译当前实验", lambda: self.start("build")),
            ("04  烧录当前实验", lambda: self.start("flash")),
            ("05  采集开发板日志", lambda: self.start("board")),
            ("06  USB-CAN 100 帧测试", lambda: self.start("usbcan")),
            ("07  打开日志查看器", lambda: LogViewer(root)),
            ("08  实验记录 / 备注", self.records),
            ("09  底板接线 / 固件新功能", self.references),
            ("10  打开当前项目文件夹", lambda: open_folder(tools.project_dir(self.mode_id()))),
        ]):
            button = ttk.Button(buttons, text=name, command=command)
            button.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 8) if i % 2 == 0 else (0, 0), pady=4)
            self.action_buttons[i] = button
        self.tip = tk.StringVar(value="采集串口打开后按开发板 RESET。新设备读取配置不会使用旧 100 帧验收规则。")
        ttk.Label(frame, textvariable=self.tip, wraplength=780, foreground="#416a99").pack(anchor="w", pady=(0, 10))
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text="任务输出").pack(side="left")
        self.task_select = ttk.Combobox(row, state="readonly", width=35)
        self.task_select.pack(side="left", padx=10, fill="x", expand=True)
        self.task_select.bind("<<ComboboxSelected>>", self.select_task)
        self.stop_button = ttk.Button(row, text="停止当前任务", command=self.stop)
        self.stop_button.pack(side="right")
        self.console = scrolledtext.ScrolledText(frame, height=12, wrap="word",
                         font=("Consolas" if tools.WINDOWS else "DejaVu Sans Mono", 10),
                         background="#192b40", foreground="#d2e0ef", insertbackground="white")
        self.console.pack(fill="both", expand=True)
        self.console.insert("end", "开发控制台已就绪。选择实验后点击相应按钮。\n")
        self.console.configure(state="disabled")
        self.status = tk.StringVar(value="尚无任务")
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=(10, 0))
        self.refresh_profiles()
        self.refresh_ports()
        root.after(300, self.poll)

    def mode_id(self):
        return self.profiles[max(self.mode.current(), 0)]["id"]

    def profile(self):
        return catalog.profile(self.mode_id())

    def refresh_profiles(self, selected=None):
        self.profiles = catalog.profiles()
        self.mode["values"] = [p["name"] for p in self.profiles]
        self.mode.current(next((i for i, p in enumerate(self.profiles) if p["id"] == selected), 0))
        self.change_mode()

    def change_mode(self, _event=None):
        self.path_label.set(str(tools.project_dir(self.mode_id()).resolve()))
        self.action_buttons[5].configure(state="normal" if self.profile()["base_mode"] == "External" else "disabled")

    def refresh_ports(self):
        self.port_items = ports()
        for kind, combo in (("board", self.board_port), ("usbcan", self.usbcan_port)):
            previous = combo.get()
            values = [p["device"] + " · " + p["name"] for p in self.port_items]
            combo["values"] = values
            if previous in values:
                combo.set(previous)
            else:
                matching = [i for i, p in enumerate(self.port_items) if p["kind"] == kind]
                combo.set("")
                if len(matching) == 1:
                    combo.current(matching[0])

    def open_app(self, app):
        try:
            result = tools.launch_app(app, self.mode_id())
            self.tip.set("已打开 " + self.profile()["name"] + "：" + (Path(result["entry_file"]).name if app == "vscode" else "CubeMX .ioc"))
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc), parent=self.root)

    def start(self, kind):
        try:
            port = ""
            if kind in ("board", "usbcan"):
                combo = self.board_port if kind == "board" else self.usbcan_port
                if combo.current() < 0:
                    raise ValueError("请先选择正确的串口。")
                port = self.port_items[combo.current()]["device"]
            job = self.manager.start(kind, self.mode_id(), port)
            self.current, self.cursor = job.id, 0
            self.console.configure(state="normal")
            self.console.delete("1.0", "end")
            self.console.configure(state="disabled")
        except Exception as exc:
            messagebox.showerror("无法开始", str(exc), parent=self.root)

    def select_task(self, _event=None):
        index = self.task_select.current()
        if index >= 0:
            self.current, self.cursor = self.task_ids[index], 0
            self.console.configure(state="normal")
            self.console.delete("1.0", "end")
            self.console.configure(state="disabled")

    def poll(self):
        with self.manager.lock:
            jobs = list(self.manager.jobs.values())
        self.task_ids = [j.id for j in jobs]
        self.task_select["values"] = [NAMES[j.kind] + " · " + j.profile["name"] + " · " + j.started[11:] for j in jobs]
        if self.current in self.task_ids:
            self.task_select.current(self.task_ids.index(self.current))
            job = self.manager.get(self.current)
            snapshot = job.snapshot(True, self.cursor)
            if snapshot["lines"]:
                self.console.configure(state="normal")
                self.console.insert("end", "\n".join(x["text"] for x in snapshot["lines"]) + "\n")
                self.console.see("end")
                self.console.configure(state="disabled")
            self.cursor = snapshot["sequence"]
            m = snapshot["metrics"]
            self.status.set(STATUS[job.status] + " · " + snapshot["phase"] +
                            f"  |  提交 {m['tx']} / 完成 {m['done']} / 接收 {m['rx']}")
            self.stop_button.configure(state="normal" if job.status == "running" and job.kind != "flash" else "disabled")
        else:
            self.stop_button.configure(state="disabled")
        active = [j for j in jobs if j.status == "running"]
        self.mode.configure(state="disabled" if active else "readonly")
        for i in (2, 3):
            self.action_buttons[i].configure(state="disabled" if active else "normal")
        self.root.after(500, self.poll)

    def stop(self):
        if self.current:
            try:
                self.manager.stop(self.current)
            except Exception as exc:
                messagebox.showerror("无法停止", str(exc), parent=self.root)

    def edit_profile(self, profile=None):
        if any(j.status == "running" for j in self.manager.jobs.values()):
            messagebox.showinfo("任务运行中", "请先结束当前任务。", parent=self.root)
            return
        p = dict(profile or {"id": "", "name": "", "base_mode": "Custom", "project_dir": str(tools.ROOT),
             "build_type": "Debug", "elf_name": "PICO_CAN.elf", "toolchain": "cmake/gcc-arm-none-eabi.cmake",
             "board_baud": 115200, "capture_seconds": 80, "description": "", "cmake_options": {}})
        if p.get("builtin"):
            p.update(id="", name=p["name"] + " · 副本")
        dialog = tk.Toplevel(self.root)
        dialog.title("新增 / 编辑实验配置")
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        variables = {}
        fields = [("name", "实验名称"), ("project_dir", "CMake 项目目录"), ("base_mode", "日志方式：Custom / Device / Loopback / External"),
                  ("build_type", "构建类型：Debug / Release"), ("elf_name", "固件文件名"), ("toolchain", "工具链文件"),
                  ("board_baud", "日志波特率"), ("capture_seconds", "设备日志采集秒数"), ("description", "说明")]
        for i, (key, label) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", pady=5, padx=(0, 12))
            variables[key] = tk.StringVar(value=str(p.get(key, "")))
            ttk.Entry(frame, textvariable=variables[key], width=65).grid(row=i, column=1, sticky="ew", pady=5)
        ttk.Label(frame, text="CMake 参数（JSON）").grid(row=9, column=0, sticky="nw", pady=8)
        options = scrolledtext.ScrolledText(frame, width=62, height=7)
        options.grid(row=9, column=1, sticky="nsew", pady=8)
        options.insert("1.0", json.dumps(p.get("cmake_options", {}), ensure_ascii=False, indent=2))
        def save():
            try:
                value = {key: var.get() for key, var in variables.items()}
                value.update(id=p.get("id", ""), cmake_options=json.loads(options.get("1.0", "end")))
                result = catalog.save_profile(value)
                self.refresh_profiles(result["id"])
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("无法保存", str(exc), parent=dialog)
        actions = ttk.Frame(frame)
        actions.grid(row=10, column=1, sticky="e", pady=10)
        ttk.Button(actions, text="保存配置", command=save).pack(side="left", padx=6)
        if p.get("id") and not p.get("builtin"):
            def remove():
                if messagebox.askyesno("删除配置", "删除此配置？日志和实验记录保留。", parent=dialog):
                    catalog.delete_profile(p["id"])
                    self.refresh_profiles()
                    dialog.destroy()
            ttk.Button(actions, text="删除配置", command=remove).pack(side="left")

    def records(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("PICO 实验记录")
        dialog.geometry("1100x650")
        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill="both", expand=True)
        include = tk.BooleanVar()
        listing = ttk.Treeview(frame, columns=("title", "time", "status", "note"), show="headings")
        for name, title, width in [("title", "标题 / 实验", 330), ("time", "时间", 170), ("status", "自动结果", 150), ("note", "人工结论", 130)]:
            listing.heading(name, text=title)
            listing.column(name, width=width)
        listing.pack(fill="both", expand=True, pady=10)
        data = {}
        def refresh():
            listing.delete(*listing.get_children())
            data.clear()
            for record in self.manager.history(include.get()):
                a = record.get("annotation", {})
                ident = listing.insert("", "end", values=(a.get("title") or record.get("profile_name") or record["mode"],
                        record["started"].replace("T", " "), STATUS.get(record["status"], record["status"]),
                        {"pass": "通过", "fail": "未通过", "pending": "待评估", "incomplete": "条件不足"}.get(a.get("conclusion"), "未填写")))
                data[ident] = record
        def selected():
            return data.get(next(iter(listing.selection()), ""))
        def annotate():
            record = selected()
            if record:
                self.edit_record(record, refresh)
        def archive():
            record = selected()
            if record:
                catalog.annotate({"id": record["id"], "archived": not record.get("annotation", {}).get("archived", False)})
                refresh()
        def logs():
            record = selected()
            initial = next((LOGS / name for name in (record or {}).get("files", []) if name.endswith(".csv")), None)
            LogViewer(dialog, initial)
        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        for name, command in [("新建记录", lambda: self.edit_record(None, refresh)), ("编辑备注 / 结论", annotate),
                               ("归档 / 恢复", archive), ("查看关联日志", logs), ("刷新", refresh)]:
            ttk.Button(controls, text=name, command=command).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(controls, text="包含已归档", variable=include, command=refresh).pack(side="left")
        listing.bind("<Double-1>", lambda _e: annotate())
        refresh()

    def edit_record(self, record, callback):
        dialog = tk.Toplevel(self.root)
        dialog.title("编辑实验记录")
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ann = record.get("annotation", {}) if record else {}
        values = {}
        for i, (key, label) in enumerate([("title", "标题"), ("purpose", "目的"), ("participants", "人员"),
                      ("hardware", "实板 / 固件版本"), ("conclusion", "人工结论：pending / pass / fail / incomplete")]):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", padx=(0, 10), pady=6)
            default = ann.get(key, "pending" if key == "conclusion" else
                              (record.get("profile_name", record.get("mode", "")) if record and key == "title" else ""))
            values[key] = tk.StringVar(value=default)
            ttk.Entry(frame, textvariable=values[key], width=62).grid(row=i, column=1, pady=6)
        ttk.Label(frame, text="备注 / 异常 / 后续动作").grid(row=5, column=0, sticky="nw")
        text = scrolledtext.ScrolledText(frame, width=62, height=10)
        text.grid(row=5, column=1, pady=10)
        text.insert("1.0", ann.get("notes", ""))
        def save():
            try:
                value = {key: var.get() for key, var in values.items()}
                value["notes"] = text.get("1.0", "end").rstrip()
                if record:
                    catalog.annotate(dict(value, id=record["id"]))
                else:
                    catalog.new_record(dict(value, mode=self.mode_id()))
                callback()
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("保存失败", str(exc), parent=dialog)
        ttk.Button(frame, text="保存记录（原始自动结果保留）", command=save).grid(row=6, column=1, sticky="e")

    def references(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("底板接线与最新固件")
        dialog.geometry("1000x760")
        book = ttk.Notebook(dialog)
        book.pack(fill="both", expand=True, padx=12, pady=12)
        for filename, title in [("wiring.json", "底板接线"), ("firmware.json", "固件新功能"),
                                ("board-design.md", "底板原文"), ("device-read-validation.md", "设备验收说明")]:
            path = tools.ROOT / "ui/data" / filename
            text = scrolledtext.ScrolledText(book, wrap="word", font=(FONT, 11))
            raw = path.read_text(encoding="utf-8")
            if filename == "wiring.json":
                data = json.loads(raw)
                lines = ["NUCLEO-G474RE + 三路 TJA1051T/3", data["note"], ""]
                for c in data["channels"]:
                    lines += [c["name"] + "　" + c["ports"], "TX: " + c["tx"], "RX: " + c["rx"],
                              c["ic"] + "　" + c["termination"], c["purpose"], ""]
                for d in data["details"]:
                    lines += [d["title"]] + [a + "： " + b for a, b in d["rows"]] + [""]
                raw = "\n".join(lines)
            elif filename == "firmware.json":
                data = json.loads(raw)
                lines = ["固件快照：" + data["updated"] + " / " + data["commit"], ""]
                for f in data["features"]:
                    lines += [f["name"], f["description"], f["status"], ""]
                lines += data["boundaries"]
                raw = "\n".join(lines)
            text.insert("1.0", raw)
            text.configure(state="disabled")
            book.add(text, text="  " + title + "  ")

    def close(self):
        active = [j for j in self.manager.jobs.values() if j.status == "running"]
        if any(j.kind == "flash" for j in active):
            messagebox.showinfo("正在烧录", "请等待写入和校验完成后再关闭。", parent=self.root)
            return
        if active and not messagebox.askyesno("关闭控制台", "停止正在运行的任务并关闭？已有日志会保留。", parent=self.root):
            return
        for job in active:
            self.manager.stop(job.id)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", action="store_true")
    parser.add_argument("--log-file", type=Path)
    args = parser.parse_args()
    root = tk.Tk()
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=(FONT, 10))
    style.configure("TButton", padding=(10, 9))
    style.configure("Treeview", rowheight=28)
    if args.logs or args.log_file:
        root.withdraw()
        LogViewer(root, initial=args.log_file, standalone=True)
    else:
        Desktop(root)
    root.mainloop()


if __name__ == "__main__":
    main()
