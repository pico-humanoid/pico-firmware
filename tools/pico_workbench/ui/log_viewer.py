"""Portable, read-only Tk log viewer. No server or extra GUI dependency."""
from datetime import datetime
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import log_model as model
import platform_tools as tools

FONT = "Microsoft YaHei UI" if tools.WINDOWS else "Noto Sans CJK SC"
MONO = "Consolas" if tools.WINDOWS else "DejaVu Sans Mono"
PAGE_SIZE = 500
COLORS = {"ink": "#20334b", "muted": "#60738a", "blue": "#1b64a4",
          "green": "#20734c", "amber": "#875411", "red": "#a32e3b"}


def error_line(line):
    rec = model.parse_record(line, 1)
    return bool(rec and rec.level in ("warning", "error"))


class LogViewer:
    def __init__(self, parent, initial=None, standalone=False):
        self.window = tk.Toplevel(parent)
        self.window.title("PICO 日志查看器 · 清晰阅读")
        width = min(1400, int(parent.winfo_screenwidth() * .94))
        height = min(910, int(parent.winfo_screenheight() * .88))
        self.window.geometry(f"{width}x{height}")
        self.window.minsize(min(1060, width), min(680, height))
        self.parent, self.path, self.stamp, self.raw = parent, None, None, ""
        self.records, self.filtered, self.paths, self.row_records, self.raw_lines = [], [], {}, {}, []
        self.page, self.pending, self.timer = 0, None, None
        self.report_path, self.json_document = None, None
        self.window.protocol("WM_DELETE_WINDOW", lambda: (self.close(), parent.destroy()) if standalone else self.close())
        self.search = tk.StringVar()
        self.ident = tk.StringVar()
        self.direction = tk.StringVar(value="全部")
        self.auto_refresh = tk.BooleanVar(value=True)
        self.follow = tk.BooleanVar(value=False)
        self.font_size = tk.IntVar(value=11)
        self.file_search = tk.StringVar()
        self.file_kind = tk.StringVar(value="采集日志")
        self.info = tk.StringVar(value="打开一个日志文件，或从左侧选择历史记录。")
        self.paging = tk.StringVar(value="尚未打开日志")
        self.summary = {key: tk.StringVar(value="—") for key in ("tx", "done", "rx", "warnings", "result")}

        body = ttk.Frame(self.window, padding=(16, 12, 16, 10))
        body.pack(fill="both", expand=True)
        heading = ttk.Frame(body)
        heading.pack(fill="x")
        ttk.Label(heading, text="PICO  /  日志查看器", font=(FONT, 19, "bold"), foreground=COLORS["ink"]).pack(side="left")
        ttk.Label(heading, text="读取本机文件 · 支持实时更新", foreground=COLORS["muted"]).pack(side="right")
        bar = ttk.Frame(body, padding=(0, 10, 0, 10))
        bar.pack(fill="x")
        for text, command in (("打开文件…", self.choose), ("刷新列表", self.scan), ("另存原始副本…", self.export)):
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=(0, 7))
        ttk.Checkbutton(bar, text="自动刷新", variable=self.auto_refresh).pack(side="left", padx=(12, 4))
        ttk.Checkbutton(bar, text="跟随最新", variable=self.follow, command=self.render).pack(side="left", padx=4)
        ttk.Label(bar, text="字号").pack(side="left", padx=(18, 4))
        size = ttk.Combobox(bar, textvariable=self.font_size, values=(10, 11, 12, 14, 16), width=3, state="readonly")
        size.pack(side="left")
        size.bind("<<ComboboxSelected>>", lambda _: self.apply_font())
        self.path_label = ttk.Label(body, textvariable=self.info, foreground=COLORS["muted"], wraplength=1280)
        self.path_label.pack(fill="x", pady=(0, 8))
        ttk.Label(body, text="文件概览 · 以下统计针对整个文件，不受筛选影响", foreground=COLORS["muted"], font=(FONT, 9)).pack(anchor="w", pady=(0, 5))

        cards = ttk.Frame(body)
        cards.pack(fill="x", pady=(0, 10))
        for col, (key, label, color) in enumerate((
                ("tx", "提交发送 · TX_SUBMIT", "blue"), ("done", "硬件完成 · TX_DONE", "blue"),
                ("rx", "接收 · RX", "green"), ("warnings", "异常 / 提示行", "amber"),
                ("result", "文件内固件结论", "ink"))):
            card = ttk.Frame(cards, padding=(12, 7), relief="solid", borderwidth=1)
            card.grid(row=0, column=col, sticky="nsew", padx=(0, 7 if col < 4 else 0))
            cards.columnconfigure(col, weight=1)
            ttk.Label(card, text=label, foreground=COLORS["muted"], font=(FONT, 9)).pack(anchor="w")
            ttk.Label(card, textvariable=self.summary[key], foreground=COLORS[color], font=(FONT, 15, "bold")).pack(anchor="w", pady=(3, 0))

        split = ttk.Panedwindow(body, orient="horizontal")
        split.pack(fill="both", expand=True)
        left = ttk.Frame(split)
        split.add(left, weight=0)
        ttk.Label(left, text="最近文件", font=(FONT, 11, "bold")).pack(anchor="w", pady=(0, 6))
        ttk.Combobox(left, textvariable=self.file_kind, values=("采集日志", "全部文件（含报告 / 任务）"), state="readonly", width=27).pack(fill="x", pady=(0, 6))
        ttk.Entry(left, textvariable=self.file_search, width=27).pack(fill="x", pady=(0, 7))
        self.files = self.tree(left, (("file", "文件名", 185), ("date", "修改时间", 100)))
        self.files.bind("<<TreeviewSelect>>", self.selected)
        ttk.Label(left, text="输入上方关键词筛选文件\n支持 CSV / LOG / JSONL / JSON", foreground=COLORS["muted"], font=(FONT, 9)).pack(anchor="w", pady=(6, 0))
        right = ttk.Frame(split)
        split.add(right, weight=1)
        filters = ttk.Frame(right)
        filters.pack(fill="x", pady=(0, 7))
        ttk.Label(filters, text="内容").pack(side="left")
        ttk.Entry(filters, textvariable=self.search, width=21).pack(side="left", fill="x", expand=True, padx=(5, 10))
        ttk.Label(filters, text="ID (十六进制)").pack(side="left")
        ttk.Entry(filters, textvariable=self.ident, width=11).pack(side="left", padx=(5, 10))
        categories = ("全部", "报文", "RX", "TX_SUBMIT", "TX_DONE", "异常 / 提示", "解析数据", "健康状态")
        ttk.Combobox(filters, textvariable=self.direction, values=categories, state="readonly", width=12).pack(side="left")
        ttk.Button(filters, text="清空", command=self.clear_filters).pack(side="left", padx=(7, 0))
        reading = ttk.Panedwindow(right, orient="vertical")
        reading.pack(fill="both", expand=True)
        table_area = ttk.Frame(reading)
        reading.add(table_area, weight=4)
        self.book = ttk.Notebook(table_area)
        self.book.pack(fill="both", expand=True)
        events = ttk.Frame(self.book, padding=6)
        self.book.add(events, text=" 报文与事件 ")
        ttk.Label(events, text="蓝色：发送   绿色：接收   黄色：提示   红色：错误   ·   点击任意行查看完整原文", foreground=COLORS["muted"], font=(FONT, 9)).pack(anchor="w", pady=(0, 6))
        self.table = self.tree(events, (("line", "行", 52), ("time", "时间 / s", 94), ("event", "事件", 155),
                    ("channel", "通道", 82), ("id", "CAN ID", 108), ("frame", "帧类型", 105),
                    ("dlc", "DLC", 47), ("data", "数据 / 说明", 330)))
        self.table.bind("<<TreeviewSelect>>", lambda _: self.show_detail(self.table))

        devices = ttk.Frame(self.book, padding=6)
        self.book.add(devices, text=" 设备数据 ")
        ttk.Label(devices, text="显示筛选范围内字段的最后记录值；新鲜度请结合健康页 valid 掩码。点击一行追溯原文。", foreground=COLORS["muted"], wraplength=820).pack(anchor="w", pady=(0, 6))
        self.devices = self.tree(devices, (("device", "来源", 88), ("name", "字段", 170), ("value", "最新值", 135),
                    ("unit", "单位", 55), ("raw", "原始值", 130), ("line", "行", 55), ("note", "说明", 295)))
        self.devices.bind("<<TreeviewSelect>>", lambda _: self.show_detail(self.devices))
        health = ttk.Frame(self.book, padding=6)
        self.book.add(health, text=" 健康状态 ")
        ttk.Label(health, text="显示各组最后一次健康快照。累计计数非零可能来自较早阶段，不等于当前窗口新增故障。", foreground=COLORS["muted"], wraplength=820).pack(anchor="w", pady=(0, 6))
        self.health = self.tree(health, (("device", "分组", 100), ("name", "指标", 245), ("value", "最新值", 130),
                    ("time", "时间 / s", 110), ("line", "行", 55)))
        self.health.bind("<<TreeviewSelect>>", lambda _: self.show_detail(self.health))
        rawtab = ttk.Frame(self.book, padding=6)
        self.book.add(rawtab, text=" 原始日志 ")
        ttk.Label(rawtab, text="与报文页共用分页；筛选时仅显示匹配原始行。左侧行号为查看器标注，另存副本保留原始字节。", foreground=COLORS["muted"], wraplength=820).pack(anchor="w", pady=(0, 6))
        self.text = scrolledtext.ScrolledText(rawtab, wrap="none", height=8, background="#f8fafc", foreground=COLORS["ink"], relief="flat", padx=10, pady=8)
        self.text.pack(fill="both", expand=True)
        rawbar = ttk.Scrollbar(rawtab, orient="horizontal", command=self.text.xview)
        rawbar.pack(fill="x")
        self.text.configure(xscrollcommand=rawbar.set)
        for tag, bg in (("warning", "#fff1d6"), ("error", "#fde7eb"), ("pass", "#e0f3e8")):
            self.text.tag_configure(tag, background=bg)
        reporttab = ttk.Frame(self.book, padding=6)
        self.book.add(reporttab, text=" 复核摘要 ")
        self.report = scrolledtext.ScrolledText(reporttab, wrap="word", height=8, relief="flat", padx=12, pady=10, background="#f8fafc", foreground=COLORS["ink"])
        self.report.pack(fill="both", expand=True)
        self.fill(self.report, "打开日志后，将自动寻找同名 .analysis.json、.check.json 等复核报告。")

        pager = ttk.Frame(table_area, padding=(0, 7, 0, 7))
        pager.pack(fill="x")
        self.prev_button = ttk.Button(pager, text="← 上一页", command=lambda: self.turn(-1))
        self.prev_button.pack(side="left")
        self.next_button = ttk.Button(pager, text="下一页 →", command=lambda: self.turn(1))
        self.next_button.pack(side="left", padx=6)
        self.latest_button = ttk.Button(pager, text="到最新", command=self.latest)
        self.latest_button.pack(side="left")
        ttk.Label(pager, textvariable=self.paging, foreground=COLORS["muted"]).pack(side="right")
        detail_area = ttk.Frame(reading)
        reading.add(detail_area, weight=1)
        detailbar = ttk.Frame(detail_area)
        detailbar.pack(fill="x")
        ttk.Label(detailbar, text="选中行详情", font=(FONT, 10, "bold")).pack(side="left")
        ttk.Button(detailbar, text="复制原始行", command=self.copy_line).pack(side="right")
        self.detail = scrolledtext.ScrolledText(detail_area, height=4, wrap="word", relief="solid", borderwidth=1, background="#f5f8fc", foreground=COLORS["ink"], padx=9, pady=7)
        self.detail.pack(fill="both", expand=True, pady=(5, 0))
        self.fill(self.detail, "选择一行后，这里显示中文解释、完整字段和原始内容。")
        self.selected_record = None
        self.apply_palette(body)
        self.apply_font()
        self.book.bind("<<NotebookTabChanged>>", lambda _: self.update_pager())
        self.search.trace_add("write", self.filter_changed)
        self.ident.trace_add("write", self.filter_changed)
        self.direction.trace_add("write", self.filter_changed)
        self.file_search.trace_add("write", lambda *_: self.scan())
        self.file_kind.trace_add("write", lambda *_: self.scan())
        self.scan()
        if initial:
            self.load(Path(initial))
        self.timer = self.window.after(1200, self.watch)

    def tree(self, parent, columns):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=7, selectmode="browse", style="PicoLog.Treeview")
        for name, title, width in columns:
            tree.heading(name, text=title)
            tree.column(name, width=width, minwidth=40, stretch=name in ("data", "note", "file", "value", "name"), anchor="w")
        v = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        h = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=v.set, xscrollcommand=h.set)
        tree.grid(row=0, column=0, sticky="nsew")
        v.grid(row=0, column=1, sticky="ns")
        h.grid(row=1, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree.tag_configure("even", background="#ffffff")
        tree.tag_configure("odd", background="#f2f6fb")
        tree.tag_configure("tx", foreground=COLORS["blue"])
        tree.tag_configure("rx", foreground=COLORS["green"])
        tree.tag_configure("warning", foreground=COLORS["amber"], background="#fff3dc")
        tree.tag_configure("error", foreground=COLORS["red"], background="#fde9ed")
        tree.tag_configure("pass", foreground=COLORS["green"], background="#e4f4e9")
        return tree

    def apply_font(self):
        n = self.font_size.get()
        style = ttk.Style(self.window)
        style.configure("PicoLog.Treeview", font=(FONT, n), rowheight=int(n * 2.8), foreground=COLORS["ink"])
        style.configure("PicoLog.Treeview.Heading", font=(FONT, n, "bold"), padding=(5, 6))
        self.text.configure(font=(MONO, n))
        self.detail.configure(font=(FONT, n))
        self.report.configure(font=(FONT, n))

    def apply_palette(self, widget):
        style = ttk.Style(self.window)
        bg, border = "#f4f7fb", "#d7e1ed"
        style.configure("PicoLog.TFrame", background=bg)
        style.configure("PicoLog.TLabel", background=bg)
        style.configure("PicoLog.TCheckbutton", background=bg)
        style.map("PicoLog.TCheckbutton", background=[("active", bg)])
        style.configure("PicoLog.TButton", background="#ffffff", foreground=COLORS["ink"], bordercolor=border, padding=(10, 8))
        style.map("PicoLog.TButton", background=[("active", "#e8f0fb")])
        style.configure("PicoLog.TNotebook", background=bg, bordercolor=border)
        style.configure("PicoLog.TNotebook.Tab", background="#e6edf6", foreground=COLORS["ink"], padding=(9, 7))
        style.map("PicoLog.TNotebook.Tab", background=[("selected", "#ffffff")])
        style.configure("PicoLog.Treeview", background="#ffffff", fieldbackground="#ffffff", bordercolor=border)
        style.configure("PicoLog.Treeview.Heading", background="#e6edf5", foreground=COLORS["ink"], bordercolor=border)
        style.map("PicoLog.Treeview", background=[("selected", "#205b93")], foreground=[("selected", "#ffffff")])
        classes = {"TFrame": "PicoLog.TFrame", "TLabel": "PicoLog.TLabel", "TButton": "PicoLog.TButton",
                   "TCheckbutton": "PicoLog.TCheckbutton", "TNotebook": "PicoLog.TNotebook"}
        def walk(item):
            if item.winfo_class() in classes:
                item.configure(style=classes[item.winfo_class()])
            for child in item.winfo_children():
                walk(child)
        walk(widget)

    def scan(self):
        current = self.path
        self.paths = {}
        self.files.delete(*self.files.get_children())
        roots = [tools.ROOT / "logs", tools.ROOT / "projects/pico-firmware/logs"]
        candidates = []
        for root in roots:
            if root.is_dir():
                for path in root.rglob("*"):
                    if path.suffix.lower() in (".csv", ".log", ".txt", ".json", ".jsonl") and "ui_source_backups" not in path.parts:
                        if self.file_kind.get() == "采集日志" and (path.suffix.lower() == ".json" or "ui_records" in path.parts or any(word in path.name for word in ("service", "ui_stage", "ui_desktop"))):
                            continue
                        try:
                            stat = path.stat()
                            if path.is_file() and self.file_search.get().casefold() in path.name.casefold():
                                candidates.append((stat.st_mtime, path))
                        except OSError:
                            continue
        selected = None
        for i, (mtime, path) in enumerate(sorted(candidates, key=lambda v: v[0], reverse=True)[:400]):
            row = self.files.insert("", "end", values=(path.name, datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")), tags=("even" if i % 2 == 0 else "odd",))
            self.paths[row] = path
            if path == current:
                selected = row
        if selected:
            # Focus is enough; changing selection would reload the current file.
            self.files.focus(selected)

    def selected(self, _event=None):
        selection = self.files.selection()
        if selection and selection[0] in self.paths:
            self.load(self.paths[selection[0]])

    def choose(self):
        path = filedialog.askopenfilename(parent=self.window, initialdir=tools.ROOT / "logs", filetypes=[("实验日志", "*.csv *.log *.json *.jsonl *.txt"), ("所有文件", "*.*")])
        if path:
            self.load(Path(path))

    def load(self, path, automatic=False):
        path = Path(path)
        try:
            stat = path.stat()
            if stat.st_size > 25 * 1024 * 1024:
                raise ValueError("文件超过 25 MB，请先按实验分段后查看。")
            data = path.read_bytes()
            try:
                raw = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                raw = data.decode("gb18030", errors="replace")
            changed = self.path != path
            self.path, self.stamp, self.raw = path, stat.st_mtime_ns, raw
            self.raw_lines = raw.splitlines()
            self.records = model.parse(raw)
            self.json_document = None
            if path.suffix.lower() == ".json":
                try:
                    self.json_document = json.loads(raw)
                except ValueError:
                    pass
            if changed:
                self.page = 0
                self.selected_record = None
                self.fill(self.detail, "选择一行查看完整原文。概览统计始终针对整个文件；下方列表使用当前筛选。")
            self.info.set(str(path))
            self.window.title("PICO 日志查看器 · " + path.name)
            summary = model.summarize(self.records)
            for key, var in self.summary.items():
                var.set(str(summary[key]))
            self.render(preserve=not changed)
            self.load_report()
        except (OSError, ValueError) as exc:
            if automatic:
                self.info.set(f"暂时无法更新：{exc}；当前已读取内容仍可查看。")
            else:
                messagebox.showerror("无法读取日志", str(exc), parent=self.window)

    def filter_changed(self, *_):
        if self.pending:
            self.window.after_cancel(self.pending)
        self.pending = self.window.after(180, self.apply_filter)

    def apply_filter(self):
        self.pending = None
        self.page = 0
        self.render()

    def clear_filters(self):
        self.search.set("")
        self.ident.set("")
        self.direction.set("全部")

    @staticmethod
    def fill(widget, text, preserve=False):
        view = widget.yview()
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")
        if preserve:
            widget.yview_moveto(view[0])

    @staticmethod
    def tags(rec, i):
        shade = "even" if i % 2 == 0 else "odd"
        state = rec.level if rec.level != "normal" else "rx" if rec.event in ("RX", "RX_REMOTE") else "tx" if rec.event.startswith("TX_") else "normal"
        return shade, state

    def render(self, preserve=False):
        if not self.path:
            return
        self.filtered = [r for r in self.records if model.matches(r, self.search.get(), self.direction.get(), self.ident.get().strip())]
        pages = max(1, (len(self.filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = pages - 1 if self.follow.get() else min(self.page, pages - 1)
        start = self.page * PAGE_SIZE
        shown = self.filtered[start:start + PAGE_SIZE]
        old = {tree: (tree.selection(), tree.yview()) for tree in (self.table, self.devices, self.health)}
        self.row_records.clear()
        for tree in old:
            tree.delete(*tree.get_children())
        for i, rec in enumerate(shown):
            row = "event-" + str(rec.line)
            self.table.insert("", "end", iid=row, values=(rec.line, rec.display_time, rec.label,
                    rec.channel or "—", rec.identifier or "—", " / ".join(x for x in (rec.format, rec.kind) if x) or "—",
                    rec.dlc or "—", rec.description), tags=self.tags(rec, i))
            self.row_records[(self.table, row)] = rec
        index = {r.line: r for r in self.filtered}
        for i, values in enumerate(model.device_values(self.filtered)):
            rec = index[values[5]]
            row = "device-" + json.dumps([values[0], values[7]], ensure_ascii=True)
            self.devices.insert("", "end", iid=row, values=values[:7], tags=self.tags(rec, i))
            self.row_records[(self.devices, row)] = rec
        for i, values in enumerate(model.health_values(self.filtered)):
            rec = index[values[4]]
            row = "health-" + json.dumps([values[0], values[1]], ensure_ascii=True)
            self.health.insert("", "end", iid=row, values=values[:5], tags=("even" if i % 2 == 0 else "odd", values[5]))
            self.row_records[(self.health, row)] = rec
        rawview = self.text.yview()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if self.json_document is not None:
            self.text.insert("end", self.raw)
        elif not (self.search.get() or self.ident.get().strip() or self.direction.get() != "全部"):
            lo = 1 if self.page == 0 else self.filtered[start - 1].line + 1 if shown else 1
            hi = len(self.raw_lines) if self.page == pages - 1 else shown[-1].line if shown else len(self.raw_lines)
            levels = {r.line: r.level for r in shown}
            for line in range(lo, hi + 1):
                self.text.insert("end", f"{line:>7}  {self.raw_lines[line - 1]}\n", levels.get(line, "normal"))
        else:
            for rec in shown:
                self.text.insert("end", f"{rec.line:>7}  {rec.raw}\n", rec.level)
        self.text.configure(state="disabled")
        if preserve and not self.follow.get():
            self.text.yview_moveto(rawview[0])
        if self.follow.get():
            children = self.table.get_children()
            if children:
                self.table.see(children[-1])
            self.text.see("end")
        elif preserve:
            for tree, (selected, position) in old.items():
                if selected and tree.exists(selected[0]):
                    tree.selection_set(selected[0])
                tree.yview_moveto(position[0])
        self.update_pager()

    def update_pager(self):
        count = len(self.filtered)
        pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
        current = self.book.index("current")
        paged = current in (0, 3) and self.json_document is None
        self.prev_button.configure(state="normal" if paged and self.page > 0 else "disabled")
        self.next_button.configure(state="normal" if paged and self.page < pages - 1 else "disabled")
        self.latest_button.configure(state="normal" if paged else "disabled")
        if current == 1:
            text = f"当前筛选内的最新设备字段：{len(self.devices.get_children())} 项"
        elif current == 2:
            text = f"当前筛选内的最新健康指标：{len(self.health.get_children())} 项"
        elif current == 4:
            text = "复核报告与文件概览"
        elif self.json_document is not None:
            text = "JSON 文档 · 原始日志页显示完整文件"
        else:
            start = self.page * PAGE_SIZE
            text = f"{start + 1 if count else 0}–{min(start + PAGE_SIZE, count)} / {count:,} 条 · 第 {self.page + 1}/{pages} 页"
        self.paging.set(text)

    def turn(self, step):
        self.follow.set(False)
        self.page = max(0, self.page + step)
        self.render()
        self.table.yview_moveto(0)
        self.text.yview_moveto(0)

    def latest(self):
        self.page = max(0, (len(self.filtered) - 1) // PAGE_SIZE)
        self.render()
        children = self.table.get_children()
        if children:
            self.table.see(children[-1])
        self.text.see("end")

    def show_detail(self, tree):
        selected = tree.selection()
        rec = self.row_records.get((tree, selected[0])) if selected else None
        if not rec:
            return
        self.selected_record = rec
        text = f"第 {rec.line} 行  ·  {rec.label} ({rec.event})"
        if rec.time:
            text += f"  ·  相对时间 {rec.display_time} s" if model.number(rec.time) is not None else f"  ·  时间 {rec.time}"
        if rec.explanation:
            text += "\n" + rec.explanation
        if rec.event == "SERIAL_SUBMITTED":
            text += "\n此事件表示串口写入已提交，不等于 CAN 控制器发送完成。"
        if rec.values:
            fields = []
            for key, value in rec.values.items():
                display, unit = model.format_value(key, value)
                fields.append(f"{model.FIELD_NAMES.get(key, key)} [{key}] = {display}{' ' + unit if unit else ''}")
            text += "\n" + "   |   ".join(fields)
        text += "\n原始行：\n" + rec.raw
        self.fill(self.detail, text)

    def copy_line(self):
        if self.selected_record:
            self.window.clipboard_clear()
            self.window.clipboard_append(self.selected_record.raw)

    def load_report(self):
        candidates = [self.path.with_suffix(suffix) for suffix in (".analysis.json", ".check.json")]
        candidates += [Path(str(self.path) + ".json"), Path(str(self.path) + ".analysis.json")]
        if self.path.name.endswith(".verified.log"):
            candidates.append(self.path.with_name(self.path.name.replace(".verified.log", ".analysis.json")))
        self.report_path = next((p for p in candidates if p != self.path and p.is_file()), None)
        text = "概览统计范围：当前打开文件的全部已读取内容（不受筛选影响）。\n"
        text += "采集完成与固件 PASS 是不同结论；USB 串口提交次数也不等于 CAN 发送完成次数。\n\n"
        if self.report_path or self.json_document is not None:
            try:
                report = json.loads(self.report_path.read_text(encoding="utf-8-sig")) if self.report_path else self.json_document
                text += "复核文件：" + str(self.report_path or self.path) + "\n\n"
                if isinstance(report, dict):
                    names = {"result": "报告结论", "status": "报告状态", "requests": "请求数", "matched": "匹配回复数", "reply_span_s": "回复覆盖时间 / s", "reason": "原因", "errors": "错误明细"}
                    for key, title in names.items():
                        if key in report:
                            text += title + "：" + str(report[key]) + "\n"
                text += "\n完整报告：\n" + json.dumps(report, ensure_ascii=False, indent=2)
            except (OSError, ValueError) as exc:
                text += "报告暂时无法解析：" + str(exc)
        else:
            text += "未找到同名独立复核报告。\n\n"
            text += "健康页的计数通常从启动累积；若文件跨越多次启动或包含旧缓存，需按目标窗口判断，不能把累计值当作当前窗口新增故障。\n"
            text += "异常 / 提示行数只是已标记行的数量，不是独立故障次数。\n"
        self.fill(self.report, text, preserve=True)

    def watch(self):
        try:
            if self.auto_refresh.get() and self.path and self.path.exists() and self.path.stat().st_mtime_ns != self.stamp:
                self.load(self.path, automatic=True)
            self.timer = self.window.after(1200, self.watch)
        except tk.TclError:
            pass
        except OSError:
            self.timer = self.window.after(1200, self.watch)

    def export(self):
        if not self.path:
            return
        dest = filedialog.asksaveasfilename(parent=self.window, initialfile=self.path.stem + "_副本" + self.path.suffix, defaultextension=self.path.suffix)
        if dest:
            try:
                if Path(dest).resolve() == self.path.resolve():
                    messagebox.showinfo("请选择副本位置", "请使用不同的文件名，保留当前原始日志。", parent=self.window)
                    return
                Path(dest).write_bytes(self.path.read_bytes())
            except OSError as exc:
                messagebox.showerror("保存失败", str(exc), parent=self.window)

    def close(self):
        for callback in (self.timer, self.pending):
            if callback:
                self.window.after_cancel(callback)
        self.window.destroy()
