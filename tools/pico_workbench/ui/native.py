"""Native Windows/Ubuntu launcher and standalone log viewer; no browser/server required."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import webbrowser

import catalog
from engine import LOGS, Manager, ports
from experiment_log import display_line, show_legend
import platform_tools as tools
from log_viewer import LogViewer, error_line

FONT = "Microsoft YaHei UI" if tools.WINDOWS else "Noto Sans CJK SC"
NAMES = {"build": "编译", "flash": "烧录", "board": "板端采集", "usbcan": "USB-CAN 测试", "manual": "人工记录",
         "fsm": "状态机单板验证"}
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
        self.export_events=queue.Queue();self.export_thread=None
        from appearance import apply_theme
        apply_theme(root)
        self.root.title("PICO 开发控制台 · 桌面版")
        self.root.geometry("1160x860")
        self.root.minsize(1000, 760)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="PICO  开发控制台", style='Title.TLabel').pack(anchor="w")
        ttk.Label(frame, text="G474 · CAN 实验工作台　/　工程、设备、轨迹与记录", style='Muted.TLabel').pack(anchor="w", pady=(4, 10))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text="当前工程 / 实验").pack(side="left", padx=(0, 12))
        self.mode = ttk.Combobox(row, state="readonly")
        self.mode.pack(side="left", fill="x", expand=True)
        self.mode.bind("<<ComboboxSelected>>", self.change_mode)
        ttk.Button(row, text="编辑 / 复制", command=lambda: self.edit_profile(self.profile())).pack(side="left", padx=8)
        more=ttk.Menubutton(row,text="更多")
        menu=tk.Menu(more,tearoff=False)
        menu.add_command(label="新增实验配置",command=lambda:self.edit_profile())
        menu.add_command(label="调试软件路径",command=self.debug_app_settings)
        more.configure(menu=menu);more.pack(side="left")
        self.path_label = tk.StringVar()
        ttk.Label(frame, textvariable=self.path_label, wraplength=1100, foreground="#5c7692").pack(anchor="w", pady=(6, 10))
        row=ttk.Frame(frame);row.pack(fill='x',pady=3)
        ttk.Label(row,text='开发板日志串口',width=17).pack(side='left')
        self.board_port=ttk.Combobox(row,state='readonly');self.board_port.pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='刷新设备',command=self.refresh_ports).pack(side='left',padx=(8,0))
        self.bench_button=ttk.Button(row,text='打开双向测试',command=lambda:self.start('usbcan'))
        self.navigation=ttk.Notebook(frame)
        self.navigation.pack(fill='x',pady=(12,10))
        work=ttk.Frame(self.navigation,padding=10)
        labs=ttk.Frame(self.navigation,padding=4)
        utilities=ttk.Frame(self.navigation,padding=10)
        self.navigation.add(work,text='工作台')
        self.navigation.add(labs,text='实验中心')
        self.navigation.add(utilities,text='工具与资料')
        self.action_buttons={}
        actions={
            'vscode':('VS Code 项目',lambda:self.open_app('vscode')),
            'cubemx':('CubeMX 配置',lambda:self.open_app('cubemx')),
            'project':('项目文件夹',lambda:open_folder(tools.project_dir(self.mode_id()))),
            'build':('编译固件',lambda:self.start('build')),
            'flash':('烧录固件',lambda:self.start('flash')),
            'board':('采集开发板日志',lambda:self.start('board')),
            'waveshare':('微雪 USB-CAN',lambda:self.open_debug_app('waveshare')),
            'robstride':('灵足电机调试',lambda:self.open_debug_app('robstride')),
            'logs':('日志查看器',lambda:LogViewer(root)),
            'records':('实验记录',self.records),
            'references':('接线与使用说明',self.references),
            'package':('一键打包',self.export_portable),
            'speed':('单机低速转动',lambda:self.open_motor_enable('speed')),
            'tuning':('交互跟踪示波器 · 位置 / 速度',lambda:self.open_motor_enable('tuning')),
            'position':('单机位置往返',lambda:self.open_motor_enable('position')),
            'dual_tuning':('双机交互跟踪示波器',lambda:self.open_motor_enable('dual_tuning')),
            'dual_speed':('双机低速联调',lambda:self.open_motor_enable('dual_speed')),
            'dual_position':('双机独立位置轨迹',lambda:self.open_motor_enable('dual_position')),
            'sync_position':('共同时间轴平滑轨迹',lambda:self.open_motor_enable('sync_position')),
            'fault':('反馈超时与联动停机',lambda:self.open_motor_enable('fault')),
            'board_fsm':('状态机单板验证',self.open_board_fsm),
            'motor_fsm7':('七电机实机状态机',self.open_motor_fsm7),
        }
        entry=ttk.Button(work,text='进入电机实验中心  →',style='Primary.TButton',command=lambda:self.navigation.select(labs))
        entry.grid(row=0,column=0,columnspan=3,sticky='ew',pady=(0,12))
        self.action_buttons['experiment_center']=entry
        for host,keys in [(work,('vscode','cubemx','project','build','flash')),
                          (utilities,('logs','records','references','waveshare','robstride','package','board'))]:
            for column in range(3):host.columnconfigure(column,weight=1,uniform='tools')
            for i,key in enumerate(keys):
                label,command=actions[key];button=ttk.Button(host,text=label,command=command)
                button.grid(row=i//3+(1 if host is work else 0),column=i%3,sticky='ew',padx=4,pady=5)
                self.action_buttons[key]=button
        groups=[('单机调试','先确认单台电机的通信与基本控制。',('tuning','speed','position')),
                ('双机联调','同一总线，独立目标、反馈和完成进度。',('dual_tuning','dual_speed','dual_position','sync_position')),
                ('保护验证','反馈超时、联动停机与状态机。',('fault','board_fsm','motor_fsm7'))]
        for column,(title,description,keys) in enumerate(groups):
            labs.columnconfigure(column,weight=1,uniform='experiments')
            card=ttk.Frame(labs,padding=12,style='Card.TFrame');card.grid(row=0,column=column,sticky='nsew',padx=4,pady=4)
            ttk.Label(card,text=title,style='CardTitle.TLabel').pack(anchor='w')
            ttk.Label(card,text=description,style='CardMuted.TLabel',wraplength=285).pack(anchor='w',pady=(5,10))
            for key in keys:
                label,command=actions[key];button=ttk.Button(card,text=label,command=command)
                button.pack(fill='x',pady=4);self.action_buttons[key]=button
        self.tip = tk.StringVar(value="采集串口打开后按开发板 RESET。新设备读取配置不会使用旧 100 帧验收规则。")
        ttk.Label(frame, textvariable=self.tip, wraplength=1100, foreground="#416a99").pack(anchor="w", pady=(0, 10))
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text="任务输出").pack(side="left")
        self.task_select = ttk.Combobox(row, state="readonly", width=35)
        self.task_select.pack(side="left", padx=10, fill="x", expand=True)
        self.task_select.bind("<<ComboboxSelected>>", self.select_task)
        self.stop_button = ttk.Button(row, text="停止当前任务", command=self.stop)
        self.stop_button.pack(side="right")
        ttk.Button(row, text="日志说明", command=lambda: show_legend(self.root)).pack(side="right", padx=7)
        self.console = scrolledtext.ScrolledText(frame, height=12, wrap="word",
                         font=("Consolas" if tools.WINDOWS else "DejaVu Sans Mono", 10),
                         background="#ffffff", foreground="#334660", insertbackground="#365fdf", relief="flat", borderwidth=0, padx=14, pady=12)
        self.console.pack(fill="both", expand=True)
        self.console.insert("end", "开发控制台已就绪。选择实验后点击相应按钮。\n")
        self.console.configure(state="disabled")
        self.status = tk.StringVar(value="尚无任务")
        ttk.Label(frame, textvariable=self.status).pack(side='bottom',anchor="w", pady=(6, 0),before=self.console)
        self.refresh_profiles('Motors-Read-1M')
        self.refresh_ports()
        root.after(300, self.poll)

    def mode_id(self):
        return self.profiles[max(self.mode.current(), 0)]["id"]

    def export_portable(self):
        if any(j.status=='running' for j in self.manager.jobs.values()) or self.exporting():
            messagebox.showinfo('任务运行中','请先完成当前任务后再打包。',parent=self.root);return
        from datetime import datetime
        extension='.zip' if tools.WINDOWS else '.tar.gz'
        path=filedialog.asksaveasfilename(parent=self.root,title='保存完整离线迁移包',defaultextension=extension,filetypes=[('ZIP压缩包','*.zip')] if tools.WINDOWS else [('Ubuntu压缩包','*.tar.gz')],initialfile=('PICO-Windows-x64-' if tools.WINDOWS else 'PICO-Ubuntu-x86_64-')+datetime.now().strftime('%Y%m%d_%H%M%S')+extension)
        if not path:return
        self.current='';self.cursor=0
        def work():
            try:
                from portable_export import export
                export(path,lambda value:self.export_events.put(('progress',value)))
                self.export_events.put(('done',path))
            except Exception as exc:self.export_events.put(('error',str(exc)))
        self.export_thread=threading.Thread(target=work,daemon=True);self.export_thread.start()
        self.status.set('正在打包，包含运行环境、当前工程与离线开发工具。')

    def exporting(self):
        thread=getattr(self,'export_thread',None)
        return bool(thread and thread.is_alive())

    def open_debug_app(self,key):
        try:
            import debug_apps
            debug_apps.launch(key)
            self.tip.set('已启动'+debug_apps.LABELS[key]+'。连接设备与收发设置在对应软件中操作。')
        except Exception as exc:
            messagebox.showerror('启动失败',str(exc),parent=self.root)

    def debug_app_settings(self):
        import debug_apps
        dialog=tk.Toplevel(self.root);dialog.title('调试软件路径')
        frame=ttk.Frame(dialog,padding=18);frame.pack(fill='both',expand=True)
        values={}
        for i,(key,label) in enumerate(debug_apps.LABELS.items()):
            ttk.Label(frame,text=label).grid(row=i,column=0,sticky='w',pady=6,padx=(0,10))
            value=tk.StringVar(value=debug_apps.paths()[key]);values[key]=value
            ttk.Entry(frame,textvariable=value,width=70).grid(row=i,column=1,pady=6,sticky='ew')
            def choose(v=value):
                path=filedialog.askopenfilename(parent=dialog,title='选择调试程序')
                if path:v.set(path)
            ttk.Button(frame,text='浏览',command=choose).grid(row=i,column=2,padx=(8,0))
        def save():
            try:debug_apps.save({key:v.get() for key,v in values.items()});dialog.destroy()
            except Exception as exc:messagebox.showerror('无法保存',str(exc),parent=dialog)
        ttk.Button(frame,text='保存',command=save).grid(row=2,column=2,pady=(12,0),sticky='e')

    def profile(self):
        return catalog.profile(self.mode_id())

    def open_motor_fsm7(self):
        if self.exporting() or any(job.status == "running" for job in self.manager.jobs.values()):
            messagebox.showinfo("任务运行中", "请先结束当前任务，再打开七电机实机状态机。", parent=self.root)
            return
        from motor_fsm7_panel import create_panel
        panel = getattr(self, "motor_fsm7_panel", None)
        if panel is not None and panel.window.winfo_exists():
            panel.window.lift()
            return panel
        index = self.board_port.current()
        selected_port = self.port_items[index]["device"] if index >= 0 else ""
        self.motor_fsm7_panel = create_panel(self.root, selected_port=selected_port, log_root=LOGS)
        self.motor_fsm7_panel.window.grab_set()
        return self.motor_fsm7_panel

    def open_board_fsm(self):
        if self.exporting():
            return
        if not any(profile["id"] == "BoardFsm" for profile in self.profiles):
            messagebox.showinfo("缺少固件源码", "此副本缺少 BoardFsm 固件源码，请使用更新后的 PICO 项目。", parent=self.root)
            return
        if any(job.status == "running" for job in self.manager.jobs.values()):
            messagebox.showinfo("任务运行中", "请先结束当前任务。", parent=self.root)
            return
        from board_fsm_panel import BoardFsmPanel
        index = self.board_port.current()
        selected_port = self.port_items[index]["device"] if index >= 0 else ""
        self.refresh_profiles("BoardFsm")
        self.board_fsm_panel = BoardFsmPanel(self.root, self.manager, selected_port)
        return self.board_fsm_panel

    def open_motor_enable(self,experiment=None):
        if self.exporting():return
        if any(j.status=='running' for j in self.manager.jobs.values()):
            messagebox.showinfo('任务运行中','请先结束当前编译、烧录或串口采集。',parent=self.root);return
        from motor_enable import EnablePanel,SpeedPanel,DualSpeedPanel,FaultPanel,PositionPanel,DualPositionPanel,SyncPositionPanel
        options=self.profile()['cmake_options'];app=options.get('PICO_APP')
        if experiment in ('tuning','dual_tuning') or (experiment is None and app=='MotorTuning'):
            from motor_tuning import TuningPanel
            model=options.get('PICO_TUNE_MODEL',options.get('PICO_ENABLE_MODEL',options.get('PICO_MOTOR1_MODEL','RS10P')))
            selected='Motors-Tuning' if experiment=='dual_tuning' or (experiment is None and int(options.get('PICO_TUNE_COUNT',1))==2) else model+'-Tuning'
            self.refresh_profiles(selected)
            self.motor_panel=TuningPanel(self.root,self.manager,selected);return self.motor_panel
        auto_open=experiment is None
        if experiment is None:experiment='sync_position' if app=='MotorSyncPosition' else 'dual_position' if app=='MotorDualPosition' else 'position' if app=='MotorPosition' else 'fault' if app=='MotorDualFault' else 'dual_speed' if app=='MotorDualSpeed' else 'speed' if app=='MotorSpeed' else 'enable'
        if experiment=='sync_position':panel,selected=SyncPositionPanel,'Motors-Sync-Position'
        elif experiment=='dual_position':panel,selected=DualPositionPanel,'Motors-Independent-Position'
        elif experiment=='fault':panel,selected=FaultPanel,'Motors-Fault-ID1'
        elif experiment=='dual_speed':panel,selected=DualSpeedPanel,'Motors-Speed-CAN1'
        else:
            model=options.get('PICO_ENABLE_MODEL',options.get('PICO_MOTOR1_MODEL','RS10P'))
            if model not in ('RS00','RS10P'):model='RS10P'
            panel=PositionPanel if experiment=='position' else SpeedPanel if experiment=='speed' else EnablePanel
            selected=model+('-Position-Cycles' if experiment=='position' else '-Speed-CAN1' if experiment=='speed' else '-Enable-CAN1')
        self.refresh_profiles(selected)
        self.motor_panel=panel(self.root,self.manager,selected)
        return self.motor_panel

    def refresh_profiles(self, selected=None):
        self.profiles = catalog.profiles()
        self.mode["values"] = [p["name"] for p in self.profiles]
        self.mode.current(next((i for i, p in enumerate(self.profiles) if p["id"] == (selected or 'Motors-Read-1M')), 0))
        self.change_mode()

    def change_mode(self, _event=None):
        profile=self.profile();options=profile['cmake_options']
        if options.get('PICO_APP')=='Motor':
            ids=' / '.join(str(int(str(options[k]),0)) for k in ('PICO_MOTOR1_ID','PICO_MOTOR2_ID')[:int(options.get('PICO_MOTOR_COUNT',1))])
            self.path_label.set(f"CAN{options.get('PICO_MOTOR_CAN_CHANNEL',1)}  ·  1 Mbps  ·  电机 ID：{ids}  ·  主机 ID：253")
        else:self.path_label.set('项目：'+str(tools.project_dir(self.mode_id()).resolve()))
        can3=self.profile()["cmake_options"].get("PICO_APP") == "Can3Bench"
        if can3:
            self.tip.set(self.profile()["description"])
        elif self.profile()["cmake_options"].get("PICO_APP") in ("BoardFsm", "Motor", "MotorEnable", "MotorSpeed", "MotorDualSpeed", "MotorDualFault", "MotorPosition", "MotorDualPosition", "MotorSyncPosition", "Can1Periodic", "Can2Periodic", "Can3Periodic"):
            self.tip.set(self.profile()["description"])
        else:
            self.tip.set("采集串口打开后按开发板 RESET。设备读取按完整日志验收。")
        if can3:self.bench_button.pack(side='left',padx=(8,0))
        else:self.bench_button.pack_forget()

    def refresh_ports(self):
        self.port_items = ports()
        for kind, combo in (("board", self.board_port),):
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
        if self.exporting():return
        try:
            if kind == "board" and self.profile()["cmake_options"].get("PICO_APP") == "BoardFsm":
                self.open_board_fsm()
                return
            if kind=='board' and self.profile()['cmake_options'].get('PICO_APP') in ('MotorTuning','MotorEnable','MotorSpeed','MotorDualSpeed','MotorDualFault','MotorPosition','MotorDualPosition','MotorSyncPosition'):
                self.open_motor_enable();return
            if kind == "usbcan" and self.profile()["cmake_options"].get("PICO_APP") == "Can3Bench":
                from can_pc_test import PCTest
                app=PCTest(self.root)
                app.profile=self.mode_id()
                self.tip.set("已打开 CAN3 双向测试窗口；由该窗口统一打开两侧串口，请先停止其他串口采集。")
                return
            if kind=='usbcan':raise ValueError('请使用微雪或灵足调试软件收发CAN报文。')
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
        while not self.export_events.empty():
            kind,value=self.export_events.get_nowait()
            self.status.set(value if kind=='progress' else '打包完成：'+value if kind=='done' else '打包失败：'+value)
            self.console.configure(state='normal');self.console.insert('end',self.status.get()+'\n');self.console.see('end');self.console.configure(state='disabled')
            if kind=='done':messagebox.showinfo('打包完成','已生成完整离线ZIP：\n'+value+('\n\n适用于Windows x64。新电脑可能需要安装包内USB驱动；历史日志未包含。' if tools.WINDOWS else '\n\n适用于Ubuntu24.04 x86_64；已包含运行环境和编译/烧录工具。首次USB权限需安装随包规则；历史日志未包含。'),parent=self.root)
            elif kind=='error':messagebox.showerror('打包失败',value,parent=self.root)
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
                texts = (x["text"] for x in snapshot["lines"])
                if job.kind in ('board', 'usbcan'):
                    texts = map(display_line, texts)
                self.console.insert("end", "\n".join(texts) + "\n")
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
        if self.exporting():active=[True]
        self.mode.configure(state="disabled" if active else "readonly")
        for key in ('build','flash','package','tuning','speed','dual_speed','fault','position','dual_position','board_fsm','motor_fsm7'):
            self.action_buttons[key].configure(state="disabled" if active else "normal")
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
        dialog.title("接线与使用说明")
        dialog.geometry("1000x760")
        book = ttk.Notebook(dialog)
        book.pack(fill="both", expand=True, padx=12, pady=12)
        for filename, title in [("Motor_CAN1.md", "当前电机接线"), ("RobStrideSPC_Adaptation.md", "官方控制库适配"), ("Motor_Tuning.md", "交互跟踪示波器"), ("Motor_Position_Diagnostic.md", "停机位置诊断"), ("wiring.json", "底板参考接线"),
                                ("firmware.json", "固件功能"), ("device-read-validation.md", "设备验收说明")]:
            path = tools.ROOT / ("docs" if filename.endswith('.md') and filename!='device-read-validation.md' else "ui/data") / filename
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
                lines = ["导入基线：" + data["updated"] + " / " + data["commit"], ""]
                if data.get("local_updated"):
                    lines += ["本地配置更新：" + data["local_updated"], data.get("local_change", ""), ""]
                for f in data["features"]:
                    lines += [f["name"], f["description"], f["status"], ""]
                lines += data["boundaries"]
                raw = "\n".join(lines)
            text.insert("1.0", raw)
            text.configure(state="disabled")
            book.add(text, text="  " + title + "  ")

    def close(self):
        if self.exporting():
            messagebox.showinfo('正在打包','请等待打包完成后再关闭，避免中断压缩包生成。',parent=self.root);return
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
    parser.add_argument("--tuning", action="store_true")
    args = parser.parse_args()
    if args.tuning:
        from motor_tuning import TuningPanel
        panel=TuningPanel();panel.window.mainloop();return
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
