"""Robot14 overview and explicit MIT-impedance tuning; no automatic hardware actions."""
from collections import deque
import queue
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext

from engine import LOGS, Manager, ports
from robot14_model import Worker, topology, fresh, target, CAPS


class Robot14Panel:
    def __init__(self, parent=None, manager=None):
        from appearance import apply_theme
        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        apply_theme(self.window)
        self.window.title('PICO · Robot14 整机可视化调参')
        self.window.geometry('1280x960')
        self.window.minsize(1120, 830)
        if parent:
            self.window.transient(parent)
            self.window.grab_set()
        self.manager = manager or Manager()
        self.worker = None
        self.connected = False
        self.closing = False
        self.closed = False
        self.latched = False
        self.nodes = {}
        self.health = None
        self.health_received = 0
        self.last_error = None
        self.folder = None
        self.history = {i: deque(maxlen=800) for i in range(1, 15)}
        self.events = queue.Queue()
        self.build_thread = None
        self.building = False
        self.resetting = False
        f = ttk.Frame(self.window, padding=12)
        f.pack(fill='both', expand=True)
        ttk.Label(f, text='Robot14 · 整机监视 / MIT 阻抗调参', style='Title.TLabel').pack(anchor='w')
        ttk.Label(f, text='CAN2：RS00 1–3 / RS10P 4–7　 CAN3：RS00 8–10 / RS10P 11–14　'
                  'CAN1：BMS + 电源板（双设备共享总线）', wraplength=1200).pack(anchor='w', pady=4)
        bar = ttk.Frame(f)
        bar.pack(fill='x', pady=4)
        self.port = ttk.Combobox(bar, state='readonly', width=48)
        self.port.pack(side='left')
        self.refresh_button = ttk.Button(bar, text='刷新串口', command=self.refresh)
        self.refresh_button.pack(side='left', padx=6)
        self.connect_button = ttk.Button(bar, text='连接（只读 / 不复位）', command=self.connect)
        self.connect_button.pack(side='left')
        self.disconnect_button = ttk.Button(bar, text='断开', command=self.disconnect, state='disabled')
        self.disconnect_button.pack(side='left', padx=6)
        self.build_button = ttk.Button(bar, text='仅编译 Robot14', command=self.build)
        self.build_button.pack(side='right')
        self.reset_button = ttk.Button(bar, text='复位开发板（清锁存）', command=self.reset_mcu)
        self.reset_button.pack(side='right', padx=6)
        self.status = tk.StringVar(value='未连接；请先手动烧录本次 Robot14 固件。连接不使能、不复位、不烧录。')
        ttk.Label(f, textvariable=self.status, wraplength=1200).pack(anchor='w', pady=5)
        columns = ('id', 'bus', 'model', 'phase', 'p', 'v', 't', 'temp', 'age', 'target', 'fault')
        ttk.Style(self.window).configure('Robot14.Treeview', rowheight=23, font=('Noto Sans CJK SC',9))
        self.table = ttk.Treeview(f, columns=columns, show='headings', height=14, selectmode='browse', style='Robot14.Treeview')
        for key, label, width in zip(columns,
                ('ID', '总线', '型号', '状态', '位置 rad', '速度 rad/s', '转矩 Nm', '温度 °C',
                 '反馈/位置/速度龄 ms', '板端目标 p/v/τ/Kp/Kd', '故障/警告'),
                (36, 55, 65, 105, 80, 85, 80, 65, 140, 230, 100)):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=30, stretch=key in ('target', 'fault'))
        for tag, color in [('offline', '#8993a1'), ('idle', '#334660'), ('active', '#107246'), ('fault', '#b42318')]:
            self.table.tag_configure(tag, foreground=color)
        self.table.pack(fill='x', pady=3)
        for i in range(1, 15):
            bus, model = topology(i)
            self.table.insert('', 'end', iid=str(i), values=(i, f'CAN{bus}', model, '未收到', *(['—']*7)), tags=('offline',))
        self.table.bind('<<TreeviewSelect>>', self.selected)
        control = ttk.LabelFrame(f, text='逐台操作 · 编辑不会发送；选择另一台也不会复制 / 应用目标', padding=8)
        control.pack(fill='x', pady=5)
        bar = ttk.Frame(control)
        bar.pack(fill='x')
        self.motor = tk.StringVar(value='1')
        self.motor_combo = ttk.Combobox(bar, textvariable=self.motor, values=[str(i) for i in range(1, 15)],
                                      state='readonly', width=5)
        self.motor_combo.pack(side='left')
        self.motor_combo.bind('<<ComboboxSelected>>', self.selected)
        self.duration = tk.StringVar(value='10')
        ttk.Label(bar, text='本次使能时长（1–60秒）').pack(side='left', padx=(10, 3))
        ttk.Spinbox(bar, from_=1, to=60, textvariable=self.duration, width=5).pack(side='left')
        self.operator = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text='已确认固定 / 支撑、空载与硬件急停；零力矩不保持重力负载',
                        variable=self.operator).pack(side='left', padx=10)
        fields = ttk.Frame(control)
        fields.pack(fill='x', pady=4)
        self.values = []
        for index, (label, bounds) in enumerate(zip(('p / rad（绝对）', 'v / rad/s', 'τ前馈 / Nm', 'Kp', 'Kd'), CAPS)):
            cell = ttk.Frame(fields)
            cell.grid(row=0, column=index, sticky='ew', padx=6)
            fields.columnconfigure(index, weight=1)
            var = tk.StringVar(value='0')
            self.values.append(var)
            ttk.Label(cell, text=label).pack(anchor='w')
            ttk.Entry(cell, textvariable=var, width=10).pack(side='left')
            # A scale edits only the draft; no trace/write callback sends a command.
            ttk.Scale(cell, from_=bounds[0], to=bounds[1],
                      command=lambda value, v=var: v.set(f'{float(value):.3f}')).pack(side='left', fill='x', expand=True)
        bar = ttk.Frame(control)
        bar.pack(fill='x')
        self.enable_button = ttk.Button(bar, text='使能选中（零力矩）', command=self.enable, state='disabled')
        self.enable_button.pack(side='left')
        self.enable_all_button = ttk.Button(bar, text='全部使能（零力矩）', command=self.enable_all,
                                            state='disabled')
        self.enable_all_button.pack(side='left', padx=6)
        self.apply_button = ttk.Button(bar, text='应用目标到选中', command=self.apply, state='disabled')
        self.apply_button.pack(side='left', padx=6)
        ttk.Button(bar, text='草稿清零（不发送）', command=self.zero).pack(side='left')
        self.disable_button = ttk.Button(bar, text='停止选中（可再次使能）', command=self.disable, state='disabled')
        self.disable_button.pack(side='left', padx=6)
        self.stop_button = tk.Button(bar, text='全部锁存停机 · 需复位', bg='#b42318', fg='white',
                                     command=self.stop, state='disabled')
        self.stop_button.pack(side='right')
        tabs = ttk.Notebook(f)
        tabs.pack(fill='both', expand=True, pady=4)
        self.scope = tk.Canvas(tabs, bg='#fafcff', highlightthickness=0, height=200)
        tabs.add(self.scope, text='选中电机曲线（实线反馈 / 虚线板端目标）')
        health_tab = ttk.Frame(tabs, padding=8)
        tabs.add(health_tab, text='CAN / BMS / 电源板')
        self.health_text = tk.StringVar(value='等待板端健康状态；CAN1 电压仅显示有效字段，不作为自动电源互锁。')
        ttk.Label(health_tab, textvariable=self.health_text, justify='left', wraplength=1150).pack(anchor='nw')
        log_tab = ttk.Frame(tabs)
        tabs.add(log_tab, text='事件与记录')
        self.output = scrolledtext.ScrolledText(log_tab, height=6, state='disabled', font=('DejaVu Sans Mono', 9))
        self.output.pack(fill='both', expand=True)
        foot = ttk.Frame(f)
        foot.pack(fill='x')
        self.log_path = tk.StringVar(value='连接后自动保存 nodes.csv 与串口 / 命令记录。')
        ttk.Label(foot, textvariable=self.log_path, wraplength=1050).pack(side='left')
        ttk.Button(foot, text='导出本次 CSV', command=self.export_csv).pack(side='right')
        self.refresh()
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.timer = self.window.after(40, self.poll)

    def refresh(self):
        self.ports = ports()
        old = self.port.get()
        labels = [f"{p['device']} · {p['name']}" for p in self.ports]
        self.port.configure(values=labels)
        if labels:
            self.port.current(labels.index(old) if old in labels else next(
                (i for i, p in enumerate(self.ports) if p['kind']=='board'), 0))

    def busy(self):
        return bool(self.worker and self.worker.thread.is_alive())

    def log(self, text):
        self.output.configure(state='normal')
        self.output.insert('end', text+'\n')
        if int(self.output.index('end-1c').split('.')[0]) > 1000:
            self.output.delete('1.0', '200.0')
        self.output.see('end')
        self.output.configure(state='disabled')

    def connect(self):
        if self.busy() or self.building: return
        if any(j.status=='running' for j in self.manager.jobs.values()):
            messagebox.showerror('任务运行中', '先结束其他编译、烧录或串口采集任务。', parent=self.window)
            return
        if self.port.current()<0: return
        self.nodes.clear()
        for history in self.history.values(): history.clear()
        self.health = None
        self.health_received = 0
        self.last_error = None
        self.latched = False
        self.operator.set(False)
        self.connected = False
        self.folder = None
        self.worker = Worker(self.ports[self.port.current()]['device'], LOGS)
        self.worker.start()
        self.status.set('连接中：验证 Robot14 版本与保护签名；未发使能命令。')

    def disconnect(self):
        if self.worker:
            self.worker.close()
            self.status.set('正在关闭；若存在受控电机，先请求全部锁存停机并等待确认。')

    def zero(self):
        for value in self.values: value.set('0')

    def selected(self, event=None):
        if event and event.widget is self.table and self.table.selection():
            self.motor.set(self.table.selection()[0])
        else:
            self.table.selection_set(self.motor.get())
        self.zero()
        if self.worker and self.connected: self.worker.submit('select', int(self.motor.get()))

    def enable(self):
        if not self.operator.get():
            messagebox.showwarning('先确认硬件安全', '确认固定 / 支撑、空载与独立急停后勾选安全确认。', parent=self.window)
            return
        mid = int(self.motor.get())
        bus, model = topology(mid)
        try:
            seconds = float(self.duration.get())
            if not 1 <= seconds <= 60: raise ValueError()
        except ValueError:
            messagebox.showerror('时长', '使能时长须为 1–60 秒。', parent=self.window)
            return
        if messagebox.askyesno('逐台使能确认', f'CAN{bus} / {model} / ID{mid}\n'
                f'以零力矩进行 MIT 握手并使能，{seconds:g} 秒后自动停机。\n'
                '零力矩不等于机械锁止；会失去重力支撑。确认继续？', parent=self.window):
            # A modal dialog stops regular Tk polling; explicitly refresh heartbeat,
            # but existing controlled motors have already stopped on a >200ms pause.
            if self.worker:
                self.worker.alive()
                self.worker.submit('enable', mid, seconds)

    def enable_all(self):
        """逐台发零力矩 ENABLE；只处理当前有新鲜、静止 IDLE 读数的电机。"""
        if not self.operator.get():
            messagebox.showwarning('先确认硬件安全', '确认固定 / 支撑、空载与独立急停后勾选安全确认。', parent=self.window)
            return
        try:
            seconds = float(self.duration.get())
            if not 1 <= seconds <= 60: raise ValueError()
        except ValueError:
            messagebox.showerror('时长', '使能时长须为 1–60 秒。', parent=self.window)
            return
        now = time.monotonic()
        ready = [i for i in range(1, 15)
                 if fresh(self.nodes.get(i), now) and self.nodes[i]['phase'] == 'IDLE'
                 and abs(self.nodes[i]['v']) <= .1]
        if not ready:
            messagebox.showinfo('没有可安全使能的电机',
                                '当前没有电机同时满足：有新鲜读数、IDLE、静止（|v|≤0.1）。',
                                parent=self.window)
            return
        text = '、'.join(f'ID{i}' for i in ready)
        if messagebox.askyesno('全部使能确认',
                f'将逐台发送零力矩使能：\n{text}\n\n'
                f'每台 {seconds:g} 秒后自动停机；没有新鲜/静止读数的电机会被跳过。\n'
                '这不是固件“一键全使能”，板端仍逐台校验 IDLE、静止与握手。\n'
                '零力矩不保持重力负载。确认继续？', parent=self.window):
            # The modal dialog pauses Tk polling; keep the host lease alive.
            if self.worker:
                self.worker.alive()
                self.worker.submit('enable_all', ready, seconds)
                self.status.set(f'已提交全部使能：{text}；以表格 ACTIVE 为准，未确认前不要离开窗口。')

    def apply(self):
        if not self.operator.get(): return
        try:
            values = tuple(float(v.get()) for v in self.values)
            target(values)
        except (ValueError, OverflowError) as exc:
            messagebox.showerror('目标无效', str(exc), parent=self.window)
            return
        if self.worker: self.worker.submit('apply', int(self.motor.get()), values)

    def disable(self):
        if self.worker: self.worker.submit('disable', int(self.motor.get()))

    def stop(self):
        if self.worker:
            self.worker.submit('stop')
            self.status.set('已请求全部锁存停机；以板端 stop_pending 与实际停稳为准。')

    def reset_mcu(self):
        """Explicit SWD reset; clears the latched stop. Never reflashes."""
        if self.building or self.resetting:
            return
        if not messagebox.askyesno('复位开发板',
                '复位会立即停止 MCU。\n'
                '若电机正在使能/出力，扭矩会立即消失，电机在自身 200 ms 通信看门狗后停止。\n'
                '请先支撑机构、确认急停可用，再复位。\n\n'
                '复位只清除锁存并重新启动固件，不烧录、不改参数。确认复位？', parent=self.window):
            return
        if self.worker and self.busy():
            self.worker.close()
        self.resetting = True
        self.status.set('正在复位开发板；完成后请重新点击“连接”。')

        def run():
            try:
                # Let the serial worker release the session/port first.
                end = time.monotonic() + 2.0
                while self.worker and self.worker.thread.is_alive() and time.monotonic() < end:
                    time.sleep(.05)
                import platform_tools as tools
                serials = tools.stlink_serials()
                if not serials:
                    raise RuntimeError('未找到 ST-LINK（检查 USB 连接与 udev 权限）。')
                if len(serials) > 1:
                    raise RuntimeError('检测到多个 ST-LINK；只保留一个后重试。')
                proc = subprocess.run(tools.reset_command(serials[0]), env=tools.environment(),
                                      capture_output=True, text=True, timeout=30)
                if proc.returncode != 0:
                    detail = (proc.stderr or proc.stdout or '').strip().splitlines()
                    raise RuntimeError(detail[-1] if detail else f'返回码 {proc.returncode}')
                self.events.put(('reset_done', '开发板已复位；锁存已清除，请重新点击“连接”。'))
            except Exception as exc:
                self.events.put(('reset_failed', f'复位失败：{exc}'))

        threading.Thread(target=run, daemon=True, name='Robot14Reset').start()

    def build(self):
        if self.busy() or self.building: return
        import threading
        self.building = True
        def run():
            try:
                job = self.manager.start('build', 'Robot14')
                after = 0
                while True:
                    snapshot = job.snapshot(True, after)
                    for line in snapshot['lines']: self.events.put(('message', line['text']))
                    after = snapshot['sequence']
                    if job.status != 'running': break
                    time.sleep(.1)
                self.events.put(('message', f'Robot14 编译：{job.status}；本窗口不会自动烧录。'))
            except Exception as exc:
                self.events.put(('error', str(exc)))
            finally:
                self.events.put(('build_done', None))
        self.build_thread = threading.Thread(target=run, daemon=True)
        self.build_thread.start()

    def export_csv(self):
        if not self.folder or not (self.folder/'nodes.csv').exists(): return
        if self.busy():
            messagebox.showinfo('先断开', '请先断开连接，让本次 CSV 完整落盘后导出。', parent=self.window)
            return
        path = filedialog.asksaveasfilename(parent=self.window, defaultextension='.csv', initialfile='robot14-nodes.csv')
        if path: shutil.copyfile(self.folder/'nodes.csv', path)

    def update_table(self, now):
        for mid in range(1, 15):
            n = self.nodes.get(mid)
            if not n: continue
            online = self.connected and now-n['received'] <= .3
            active = n['phase'] == 'ACTIVE'
            p_ok = online and (fresh(n, now, True) if active else bool(n['flags']&1 and n['p_age']<=300))
            v_ok = online and (fresh(n, now, True) if active else bool(n['flags']&2 and n['v_age']<=300))
            fb_ok = online and n['flags']&4 and n['fb_age']<=100
            values = (mid, f"CAN{n['bus']}", n['model'], n['phase']+f" / M{n['mode']}" if online else n['phase']+' / 过期',
                      f"{n['p']:.3f}" if p_ok else '—', f"{n['v']:.3f}" if v_ok else '—',
                      f"{n['t']:.3f}" if fb_ok else '—', f"{n['temp']:.1f}" if fb_ok else '—',
                      '/'.join(str(n[k]) if n[k]!=65535 else '—' for k in ('fb_age','p_age','v_age')),
                      '/'.join(f'{v/1000:g}' for v in n['target']),
                      f"{n['faults']:02x}/{n['fault_word']:08x}/{n['warning_word']:08x}")
            tag = 'offline' if not online else 'fault' if n['phase']=='FAULT' or n['faults'] or n['fault_word'] else 'active' if active else 'idle'
            self.table.item(str(mid), values=values, tags=(tag,))

    def draw(self, now):
        c = self.scope
        c.delete('all')
        width, height = max(c.winfo_width(), 200), max(c.winfo_height(), 150)
        rows = list(self.history[int(self.motor.get())])
        rows = [n for n in rows if now-n['received']<=20]
        for index, (key, label) in enumerate((('p', 'p / rad'), ('v', 'v / rad/s'), ('t', 'τ / Nm'))):
            top, bottom = index*height/3+18, (index+1)*height/3-8
            c.create_text(6, top, text=label, anchor='w', fill='#476176')
            c.create_line(70, bottom, width-10, bottom, fill='#d6dfea')
            def valid(n):
                if key=='t' or n['flags']&8: return bool(n['flags']&4 and n['fb_age']<=100)
                return bool(n['flags']&(1 if key=='p' else 2) and n[key+'_age']<=300)
            measured = [n[key] for n in rows if valid(n)]
            targets = [n['target'][index]/1000 for n in rows if n['phase']=='ACTIVE']
            low = min(measured+targets+[0])
            high = max(measured+targets+[0])
            if high-low < .02: low -= .01; high += .01
            margin = (high-low)*.08
            low -= margin; high += margin
            def xy(n, value):
                return (70+(n['received']-(now-20))/20*(width-80), bottom-(value-low)/(high-low)*(bottom-top))
            previous = None
            for n in rows:
                # Never bridge idle cumulative reads, limited type2 feedback,
                # stale intervals or a 2π-range/wrap jump as continuous position.
                if previous and valid(n) and valid(previous) and n['received']-previous['received']<.4 and (n['flags']&8)==(previous['flags']&8):
                    if key!='p' or abs(n[key]-previous[key]) < 6.28:
                        c.create_line(*xy(previous, previous[key]), *xy(n, n[key]), fill='#2962ca', width=2)
                    if n['phase']==previous['phase']=='ACTIVE':
                        c.create_line(*xy(previous, previous['target'][index]/1000), *xy(n, n['target'][index]/1000), fill='#d68b19', dash=(4,3))
                previous = n
            c.create_text(width-12, top, text=f'{high:.3f} / {low:.3f}', anchor='e', fill='#789')
        c.create_text(72, height-2, text='最近20秒 · 无效区间断线；IDLE累计位置 ≠ ACTIVE有限范围反馈；不是连续多圈角度', anchor='sw', fill='#789')

    def event(self, kind, value):
        if kind=='info':
            self.connected = True
            self.status.set(f"Robot14 验证通过 · UID {value['uid']} · 160MHz · 默认只读；请逐台操作。")
        elif kind=='node':
            self.nodes[value['id']] = value
            self.history[value['id']].append(value)
        elif kind=='state':
            self.health = value
            self.health_received = time.monotonic()
            self.latched = value['latched']
            if self.latched:
                self.status.set(f"全部锁存停机；待停机确认掩码 0x{value['stop_pending']:04X}（0=已收到停机反馈）；人工确认安全后复位才可再使能。")
            bms = f"{value['bms_mv']/1000:.2f} V" if value['bms_valid']&1 else '无有效电压'
            power = f"{value['power_mv']/1000:.2f} V" if value['power_valid']&2 else '无有效电压'
            lines = [f'BMS：{bms}，有效掩码 0x{value["bms_valid"]:X}', f'电源板电池侧：{power}，有效掩码 0x{value["power_valid"]:X}',
                     f'拒绝={value["rejected"]} 任务逾期={value["overruns"]} 串口坏帧={value["bad_frames"]}',
                     'CAN统计：接收 / 提交发送（非物理ACK） / bus-off / 接收丢帧 / 发送过期']
            lines += [f'CAN{i+1}: '+ ' / '.join(map(str, bus)) for i,bus in enumerate(value['can'])]
            lines += ['电压不是自动使能条件；未实现电源安全互锁。']
            self.health_text.set('\n'.join(lines))
        elif kind=='folder':
            from pathlib import Path
            self.folder = Path(value)
            self.log_path.set(value)
        elif kind=='closed':
            self.connected = False
            self.status.set(('连接已关闭；错误：'+self.last_error) if self.last_error else value)
            self.log(value)
        elif kind=='build_done': self.building = False
        elif kind=='reset_done':
            self.resetting = False
            self.latched = False
            self.connected = False
            self.health = None
            self.log(str(value)); self.status.set(str(value))
        elif kind=='reset_failed':
            self.resetting = False
            self.log(str(value)); self.status.set(str(value))
        else:
            if kind=='error': self.last_error = str(value)
            self.log(str(value))
            self.status.set(('错误：' if kind=='error' else '')+str(value))

    def poll(self):
        if self.closed: return
        now = time.monotonic()
        if self.worker:
            self.worker.alive()
            for _ in range(150):
                try: kind, value = self.worker.events.get_nowait()
                except queue.Empty: break
                self.event(kind, value)
        for _ in range(100):
            try: kind, value = self.events.get_nowait()
            except queue.Empty: break
            self.event(kind, value)
        busy = self.busy()
        for button in (self.connect_button, self.refresh_button, self.build_button):
            button.configure(state='disabled' if busy or self.building else 'normal')
        self.reset_button.configure(state='disabled' if self.building or self.resetting else 'normal')
        self.port.configure(state='disabled' if busy else 'readonly')
        self.disconnect_button.configure(state='normal' if busy else 'disabled')
        self.stop_button.configure(state='normal' if busy else 'disabled')
        n = self.nodes.get(int(self.motor.get()))
        can_control = self.connected and busy and not self.latched and self.health is not None and now-self.health_received<.5
        self.enable_button.configure(state='normal' if can_control and fresh(n, now) and n['phase']=='IDLE' else 'disabled')
        ready = [i for i in range(1, 15)
                 if fresh(self.nodes.get(i), now) and self.nodes[i]['phase'] == 'IDLE'
                 and abs(self.nodes[i]['v']) <= .1]
        self.enable_all_button.configure(state='normal' if can_control and ready else 'disabled')
        self.apply_button.configure(state='normal' if can_control and fresh(n, now, True) else 'disabled')
        self.disable_button.configure(state='normal' if can_control and n and n['phase'] not in ('IDLE', 'FAULT') else 'disabled')
        self.update_table(now)
        if int(now*5)!=getattr(self, '_last_draw', -1):
            self.draw(now)
            self._last_draw = int(now*5)
        if self.closing and not busy and not self.building:
            self.destroy()
            return
        self.timer = self.window.after(40, self.poll)

    def close(self):
        self.closing = True
        if self.busy(): self.disconnect()
        elif not self.building: self.destroy()

    def destroy(self):
        self.closed = True
        try: self.window.after_cancel(self.timer)
        except tk.TclError: pass
        parent = self.window.master
        self.window.destroy()
        if parent:
            try: parent.grab_set()
            except tk.TclError: pass


if __name__ == '__main__':
    panel = Robot14Panel()
    panel.window.mainloop()
