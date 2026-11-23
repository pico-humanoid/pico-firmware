"""Single-motor zero-current enable experiment; operator-triggered only."""
from datetime import datetime
import json
from pathlib import Path
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox,scrolledtext,ttk
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE/'vendor')]
import serial
from serial.tools.list_ports import comports
import catalog
import platform_tools as tools
from engine import Manager
from runtime_paths import project_root
from experiment_log import capture_notes, display_line, show_legend

PROFILES=('RS00-Enable-CAN1','RS10P-Enable-CAN1')
PHASES={'STOPPING':'请求停机','READ_BASELINE':'读取原模式','READY':'已停机，等待手动使能',
    'SET_CURRENT_MODE':'设置电流模式','VERIFY_MODE':'核对电流模式','SET_ZERO':'设置0A目标',
    'VERIFY_ZERO':'核对0A目标','WAIT_ENABLED':'等待运行反馈','ENABLED':'零电流使能中',
    'DONE':'实验结束'}

def parse_banner(line):
    if not line.startswith(('# PICO_MOTOR_SYNC_POSITION=1;','# PICO_MOTOR_DUAL_POSITION=1;','# PICO_MOTOR_POSITION=1;','# PICO_MOTOR_ENABLE=1;','# PICO_MOTOR_SPEED=1;','# PICO_MOTOR_DUAL_SPEED=1;','# PICO_MOTOR_DUAL_FAULT=1;')):return None
    return dict(re.findall(r'(\w+)=([^\s;]+)',line))

def parse_state(line):
    if not line.startswith(('# SYNC_POSITION_STATE,','# DUAL_POSITION_STATE,','# POSITION_STATE,','# ENABLE_STATE,','# SPEED_STATE,','# DUAL_SPEED_STATE,','# DUAL_FAULT_STATE,')):return None
    return dict(v.split('=',1) for v in line.strip().split(',')[1:] if '=' in v)

def validate_banner(line,profile):
    data=parse_banner(line)
    if not data:return False
    options=profile['cmake_options']
    dual_position=options.get('PICO_APP')=='MotorDualPosition'
    sync=options.get('PICO_APP')=='MotorSyncPosition'
    position=options.get('PICO_APP')=='MotorPosition'
    fault=options.get('PICO_APP')=='MotorDualFault'
    dual=sync or dual_position or fault or options.get('PICO_APP')=='MotorDualSpeed'
    speed=(dual and not dual_position and not sync) or options.get('PICO_APP')=='MotorSpeed'
    expected='SYNC_POSITION' if sync else 'DUAL_POSITION' if dual_position else 'POSITION' if position else 'DUAL_FAULT' if fault else 'DUAL_SPEED' if dual else 'SPEED' if speed else 'ENABLE'
    if not line.startswith(f'# PICO_MOTOR_{expected}=1;'):
        raise ValueError('固件实验类型不匹配；低速转动与零电流使能固件不能混用。')
    target_ok=(data.get('motor_ids')=='1,2' and data.get('models')=='RS10P,RS00') if dual else (data.get('motor_id')==str(options['PICO_ENABLE_MOTOR_ID']) and data.get('model')==options['PICO_ENABLE_MODEL'])
    if data.get('channel')!='FDCAN1' or data.get('bitrate')!='1000000' or not target_ok:
        raise ValueError('板内固件与所选电机不一致；未发送使能命令，请先烧录所选固件。')
    current_ma=int(options.get('PICO_SPEED_LIMIT_MA',500)) if not dual else 500
    if speed and current_ma not in (500,700):raise ValueError('电流限制只能为经过审核的0.5A或0.7A测试档位。')
    if speed and any(data.get(k)!=v for k,v in {'target_rad_s':'0.3','current_limit_A':f'{current_ma/1000:g}','accel_rad_s2':'0.5','max_enable_ms':'3000','host_timeout_ms':'500'}.items()):
        raise ValueError('低速固件参数不符合本次实验设置，未发送运行命令。')
    if speed and current_ma==700 and (data.get('current_policy')!='STARTUP_0700_V1' or data.get('iq_trip_A')!='0.8'):
        raise ValueError('0.7A测试固件的策略或实测电流保护不匹配，请重新编译烧录。')
    if position and any(data.get(k)!=v for k,v in {'cycles':'10','angle_deg':'5','speed_limit_rad_s':'0.2','current_limit_A':'0.5','dwell_ms':'500','max_enable_ms':'90000','host_timeout_ms':'500'}.items()):raise ValueError('位置实验参数不匹配，未发送运行命令。')
    if dual_position and any(data.get(k)!=v for k,v in {'angle1_deg':'5','angle2_deg':'-3','dwell1_ms':'500','dwell2_ms':'800','cycles':'10','speed_limit_rad_s':'0.2','current_limit_A':'0.5','max_enable_ms':'90000','host_timeout_ms':'500'}.items()):raise ValueError('双机独立位置轨迹参数不匹配。')
    if sync and any(data.get(k)!=v for k,v in {'host_id':'253','trajectory':'QUINTIC_V1','angle1_deg':'5','angle2_deg':'-3','cycles':'5','segment_ms':'2000','duration_ms':'40000','target_period_ms':'50','max_enable_ms':'90000','host_timeout_ms':'500','speed_limit_rad_s':'0.2','current_limit_A':'0.5','tracking_peak_deg':'2','tracking_rms_deg':'1'}.items()):raise ValueError('共同时间轴轨迹固件参数不匹配，未发送运行命令。')
    if (position or dual_position or sync) and data.get('arrival_policy')!='POSITION_WINDOW_V3':raise ValueError('位置固件为旧版到位判定，请重新编译烧录。')
    if (dual_position or sync) and (data.get('tx_policy')!='BOUNDED_RETRY_V1' or data.get('tx_deadline_ms')!='300'):raise ValueError('双机位置固件缺少有界CAN自动重发，请重新编译烧录。')
    return True

def group_state(states):
    """An incomplete pair must never look READY or fully stopped."""
    complete=set(states)=={'1','2'}
    entries=list(states.values())
    names={v.get('state') for v in entries}
    state=next(iter(names)) if complete and len(names)==1 else 'WAIT_BOTH'
    if 'STOPPING' in names or any(v.get('stop_unconfirmed')=='1' for v in entries):state='STOPPING'
    value={'state':state,'motors':{k:dict(v) for k,v in states.items()},'reason':' / '.join(dict.fromkeys(v.get('reason','') for v in entries))}
    for flag in ('enable_confirmed','stop_confirmed','motion_confirmed','target_cleared'):
        value[flag]='1' if complete and all(v.get(flag)=='1' for v in entries) else '0'
    for flag in ('error','stop_unconfirmed'):
        value[flag]='1' if any(v.get(flag)=='1' for v in entries) else '0'
    return value

class EnablePanel:
    tag='ENABLE'
    command='ENABLE'
    profile_ids=PROFILES
    headline='单台电机 · 零电流使能'
    start_label='3 零电流使能 · 最长3秒'
    explanation='实验会写run_mode=3和iq_ref=0，再发送使能；不发送保存、改ID、改波特率或机械零位命令。'
    phase_labels=PHASES
    stop_notice='3秒后自动停机；电脑心跳或运行反馈中断500ms会请求停机。'
    connection_hint='CAN1：PA12 TX / PA11 RX · 1Mbps。只接待测电机，固定电机外壳并空载测试，手离开输出轴。软件停机不能替代实物断电。'
    def __init__(self,parent=None,manager=None,selected=None):
        self.window=tk.Toplevel(parent) if parent else tk.Tk()
        from appearance import apply_theme
        apply_theme(self.window)
        self.window.title('PICO · '+self.headline);self.window.geometry('1160x900')
        self.window.minsize(1020,780)
        if parent:self.window.transient(parent);self.window.grab_set()
        self.manager=manager or Manager();self.events=queue.Queue();self.commands=queue.Queue()
        self.thread=None;self.disconnect=threading.Event();self.stop_requested=threading.Event()
        self.pause_heartbeat=threading.Event()
        self.connected=False;self.running=False;self.closed=False;self.closing=False;self.session_ok=False
        frame=ttk.Frame(self.window,padding=14);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text=self.headline,font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
        ttk.Label(frame,text=self.connection_hint,wraplength=1100).pack(anchor='w',pady=(6,12))
        row=ttk.Frame(frame);row.pack(fill='x',pady=4)
        ttk.Label(row,text='测试电机',width=15).pack(side='left')
        self.profiles=[catalog.profile(p) for p in self.profile_ids]
        self.choice=ttk.Combobox(row,state='readonly',values=[p['name'] for p in self.profiles]);self.choice.pack(side='left',fill='x',expand=True)
        self.choice.current(self.profile_ids.index(selected) if selected in self.profile_ids else 0)
        row=ttk.Frame(frame);row.pack(fill='x',pady=4)
        ttk.Label(row,text='ST-LINK日志串口',width=15).pack(side='left')
        self.port=ttk.Combobox(row,state='readonly');self.port.pack(side='left',fill='x',expand=True)
        self.refresh_button=ttk.Button(row,text='刷新',command=self.refresh);self.refresh_button.pack(side='left',padx=8)
        row=ttk.Frame(frame);row.pack(fill='x',pady=10)
        self.prepare_button=ttk.Button(row,text='1 编译并烧录',command=self.prepare);self.prepare_button.pack(side='left')
        self.connect_button=ttk.Button(row,text='2 连接并复位',command=self.connect);self.connect_button.pack(side='left',padx=8)
        self.enable_button=ttk.Button(row,text=self.start_label,command=self.enable,state='disabled');self.enable_button.pack(side='left',padx=8)
        self.stop_button=tk.Button(row,text='立即停机',command=self.stop,bg='#b42318',fg='white',font=('Microsoft YaHei UI',11,'bold'),state='disabled');self.stop_button.pack(side='left',padx=8)
        self.disconnect_button=ttk.Button(row,text='断开',command=self.disconnect_now,state='disabled');self.disconnect_button.pack(side='left')
        row=ttk.Frame(frame);row.pack(fill='x')
        self.heartbeat_button=ttk.Button(row,text='暂停电脑心跳（测试保护）',command=self.pause_host_heartbeat,state='disabled');self.heartbeat_button.pack(side='left')
        ttk.Label(row,text='保留串口接收；约500ms后应出现HOST_TIMEOUT。重连复位后恢复。').pack(side='left',padx=8)
        self.state=tk.StringVar(value='未连接。先烧录所选固件；连接后先确认停机，READY后才允许手动开始实验。')
        ttk.Label(frame,textvariable=self.state,wraplength=1100,font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',pady=8)
        self.metrics=tk.StringVar(value='使能反馈：—　停机反馈：—　实际Iq：—　CAN错误：—')
        ttk.Label(frame,textvariable=self.metrics,wraplength=1100).pack(anchor='w',pady=(0,8))
        self.log_folder=tk.StringVar(value='日志将在连接时自动创建。')
        ttk.Label(frame,textvariable=self.log_folder,wraplength=1100,foreground='#5c7692').pack(anchor='w')
        self.details=ttk.Notebook(frame);self.details.pack(fill='both',expand=True,pady=10)
        from trajectory_plot import TrajectoryPlot
        self.plot=TrajectoryPlot(self.details);self.details.add(self.plot,text='实时波形')
        self.log_tab=ttk.Frame(self.details);self.details.add(self.log_tab,text='中文日志与原文')
        ttk.Button(self.log_tab,text='日志说明',command=lambda:show_legend(self.window)).pack(anchor='e',padx=6,pady=3)
        self.output=scrolledtext.ScrolledText(self.log_tab,font=('Consolas',10),wrap='word',background='#ffffff',foreground='#334660',relief='flat',padx=12,pady=10);self.output.pack(fill='both',expand=True)
        if self.tag not in ('POSITION','DUAL_POSITION','SYNC_POSITION'):self.details.select(self.log_tab)
        self.output.insert('end',self.explanation+'\n'+self.stop_notice+'\n若显示“停机未确认”，应使用实物断电措施处理，不能把软件请求当作停机已经完成。\n')
        self.refresh();self.window.protocol('WM_DELETE_WINDOW',self.close);self._poll_timer=self.window.after(100,self.poll)
    def refresh(self):
        self.ports=list(comports());self.port['values']=[p.device+' · '+p.description for p in self.ports]
        matches=[i for i,p in enumerate(self.ports) if p.vid==0x0483]
        if len(matches)==1:self.port.current(matches[0])
    def profile(self):return self.profiles[self.choice.current()]
    def heartbeat_paused(self):
        event=getattr(self,'pause_heartbeat',None)
        return bool(event and event.is_set())
    def pause_host_heartbeat(self):
        self.pause_heartbeat.set();self.heartbeat_button.configure(state='disabled',text='心跳已暂停（重连恢复）')
        self.events.put(('text','已暂停KEEP心跳，继续接收日志；等待HOST_TIMEOUT和停机确认。'))
    def busy(self,value):
        self.choice.configure(state='disabled' if value else 'readonly')
        self.port.configure(state='disabled' if value else 'readonly')
        for button in (self.prepare_button,self.connect_button,self.refresh_button):button.configure(state='disabled' if value else 'normal')
    def launch(self,operation):
        if self.thread and self.thread.is_alive():return
        self.busy(True)
        def work():
            try:operation()
            except Exception as exc:self.events.put(('text','操作失败：'+str(exc)))
            finally:self.events.put(('disconnected',''))
        self.thread=threading.Thread(target=work,daemon=True);self.thread.start()
    def prepare(self):
        self.details.select(self.log_tab)
        ident=self.profile()['id']
        def work():
            for kind in ('build','flash'):
                if self.closing:return
                job=self.manager.start(kind,ident);after=0
                while True:
                    snap=job.snapshot(True,after)
                    for line in snap['lines']:self.events.put(('text',line['text']))
                    after=snap['sequence']
                    if job.status!='running':break
                    time.sleep(.1)
                if job.status!='pass':raise RuntimeError(str(job.result))
            self.events.put(('text','固件已烧录。电机接线准备好后，点击“连接并复位”。'))
        self.launch(work)
    def connect(self):
        if self.port.current()<0:return messagebox.showerror('无法连接','请选择ST-LINK日志串口。',parent=self.window)
        port=self.ports[self.port.current()]
        if port.vid!=0x0483 or not port.serial_number:return messagebox.showerror('无法连接','需要可识别序列号的ST-LINK串口。',parent=self.window)
        profile=self.profile();self.disconnect.clear();self.stop_requested.clear();self.pause_heartbeat.clear();self.heartbeat_button.configure(text='暂停电脑心跳（测试保护）');self.session_ok=False;self.running=False
        self.launch(lambda:self.worker(port,profile))
    def enable(self):
        if self.connected and self.session_ok and not self.stop_requested.is_set():
            self.enable_button.configure(state='disabled');self.commands.put(self.command)
    def stop(self):
        self.stop_requested.set();self.enable_button.configure(state='disabled');self.state.set('正在请求停机，等待电机反馈。')
    def disconnect_now(self):self.stop();self.disconnect.set()
    def worker(self,port,profile):
        token=secrets.token_hex(4).upper();motor_id=0 if self.tag in ('DUAL_SPEED','DUAL_FAULT','DUAL_POSITION','SYNC_POSITION') else profile['cmake_options']['PICO_ENABLE_MOTOR_ID']
        out=project_root()/'logs'/('motor-'+self.tag.lower()+'-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True)
        self.events.put(('folder',str(out)));last_state={};motor_states={};result_line=None
        (out/'settings.json').write_text(json.dumps({'profile':profile,'port':port.device,'baud':115200,'stlink_serial':port.serial_number},ensure_ascii=False,indent=2),encoding='utf-8')
        for _ in range(self.commands.qsize()):
            try:self.commands.get_nowait()
            except queue.Empty:break
        with capture_notes(out, lambda text: self.events.put(('text',text)), profile['name']), \
             (out/'board.log').open('wb') as raw,(out/'commands.jsonl').open('w',encoding='utf-8') as commands,serial.Serial(port.device,115200,timeout=.02,write_timeout=.3) as dev:
            def write(command):
                packet=(command+'\n').encode('ascii')
                if dev.write(packet)!=len(packet):raise RuntimeError('串口命令写入不完整。')
                commands.write(json.dumps({'time':datetime.now().isoformat(),'command':command})+'\n');commands.flush()
            try:
                dev.reset_input_buffer()
                reset=subprocess.run(tools.reset_command(port.serial_number),env=tools.environment(),capture_output=True,timeout=15)
                (out/'reset.log').write_bytes(reset.stdout+reset.stderr)
                if reset.returncode:raise RuntimeError('开发板复位失败。')
                buffer=bytearray();start=time.monotonic();verified=False;fault_verified=self.tag!='DUAL_FAULT';command_ready=False;handshake=False;handshake_due=0.;session=False;keep_due=0.;stop_sent=False;closing_at=None
                while True:
                    now=time.monotonic()
                    data=dev.read(dev.in_waiting or 1)
                    if data:
                        raw.write(data);raw.flush();buffer.extend(data)
                    while b'\n' in buffer:
                        line,_,rest=buffer.partition(b'\n');buffer=bytearray(rest);text=line.decode('utf-8',errors='replace').strip()
                        self.events.put(('text',text))
                        if parse_banner(text):
                            validate_banner(text,profile);verified=True;fault_verified=self.tag!='DUAL_FAULT';command_ready=False;handshake=False;session=False
                            start=now;handshake_due=now;last_state={};motor_states={};result_line=None;token=secrets.token_hex(4).upper()
                            while not self.commands.empty():self.commands.get_nowait()
                            self.events.put(('session_reset',''))
                        if text.startswith('# FAULT_CONFIG,') and self.tag=='DUAL_FAULT':
                            expected=profile['cmake_options']['PICO_FAULT_TARGET']
                            if not text.startswith(f'# FAULT_CONFIG,target_id={expected},method=DROP_VALID_RUNNING_FEEDBACK,timeout_ms=500'):raise ValueError('故障注入配置不匹配，未发送运行命令。')
                            fault_verified=True
                        if text.startswith(f'# {self.tag}_COMMAND_READY=1;') and fault_verified:command_ready=True
                        if text==f'# SESSION_OK token={token} id={motor_id}':session=True;self.events.put(('connected',''))
                        value=parse_state(text) if text.startswith(f'# {self.tag}_STATE,') else None
                        if value:
                            if self.tag in ('DUAL_SPEED','DUAL_FAULT','DUAL_POSITION','SYNC_POSITION'):
                                if value.get('id') not in ('1','2'):raise ValueError('双机固件返回了非预期电机ID。')
                                motor_states[value['id']]=value;value=group_state(motor_states)
                            last_state=value;self.events.put(('state',value))
                        if text.startswith(f'# {self.tag}_RESULT,'):result_line=text
                    if not verified and now-start>3:raise RuntimeError('没有收到匹配的实验固件标识，请先烧录；未发送运行命令。')
                    if verified and not command_ready and now-start>3:raise RuntimeError('固件缺少接收就绪标识，请重新编译烧录新版固件；未发送运行命令。')
                    if verified and command_ready and not session and now>=handshake_due:
                        write(f'SESSION {token} {motor_id}');handshake=True;handshake_due=now+.5
                    if verified and handshake and not session and now-start>5:raise RuntimeError('实验会话未建立，不能使能。')
                    if session and now>=keep_due and not self.heartbeat_paused():write('KEEP '+token);keep_due=now+.1
                    if self.stop_requested.is_set() and verified and not stop_sent:
                        write('STOP');stop_sent=True
                    while not self.commands.empty():
                        command=self.commands.get_nowait()
                        if command==self.command and session and not self.stop_requested.is_set() and last_state.get('state')=='READY':write(self.command+' '+token)
                    if self.disconnect.is_set():
                        if closing_at is None:closing_at=now
                        if (last_state.get('state')=='DONE' and last_state.get('stop_confirmed')=='1') or now-closing_at>1.2:break
            finally:
                if dev.is_open:
                    try:write('STOP');dev.flush()
                    except serial.SerialException:pass
                (out/'result.json').write_text(json.dumps({'last_state':last_state,'result_line':result_line,
                    'pass':bool(result_line and result_line.startswith(f'# {self.tag}_RESULT,result=PASS,'))},ensure_ascii=False,indent=2),encoding='utf-8')
    def poll(self):
        self._poll_timer=None
        if self.closed:return
        for _ in range(300):
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='text':
                self.plot.feed(value)
                self.output.insert('end',display_line(value)+'\n');self.output.see('end')
                if value.startswith('操作失败：'):self.state.set(value)
            elif kind=='folder':self.log_folder.set(value);self.plot.folder=Path(value)
            elif kind=='connected':
                if self.tag in ('POSITION','DUAL_POSITION','SYNC_POSITION'):self.details.select(self.plot)
                self.connected=True;self.session_ok=True;self.stop_button.configure(state='normal');self.disconnect_button.configure(state='normal')
            elif kind=='session_reset':
                self.session_ok=False;self.enable_button.configure(state='disabled')
            elif kind=='state':
                self.heartbeat_button.configure(state='normal' if value.get('enable_confirmed')=='1' and value.get('error')=='0' and value.get('stop_confirmed')=='0' and self.session_ok and not self.heartbeat_paused() else 'disabled')
                name=value.get('state','');self.state.set(self.phase_labels.get(name,name)+' · '+value.get('reason',''))
                if value.get('stop_unconfirmed')=='1':self.state.set('停机尚未确认，请使用实物断电措施处理。')
                self.metrics.set(f"使能反馈：{value.get('enable_confirmed','—')}　停机反馈：{value.get('stop_confirmed','—')}　实际Iq：{value.get('iq_mA','—')} mA　TEC/REC：{value.get('tec','—')}/{value.get('rec','—')}")
                if self.tag=='POSITION':
                    actual=int(value.get('delta_mrad','0'))/1000*180/3.141592654
                    target=int(value.get('target_delta_mrad','0'))/1000*180/3.141592654
                    error=int(value.get('max_return_error_mrad','0'))/1000*180/3.141592654
                    self.metrics.set(self.metrics.get()+f"\n循环：{value.get('cycles_completed','0')}/10 · 目标{target:.2f}° / 实际{actual:.2f}° · 最大回零误差{error:.2f}° · 停机目标中和{value.get('target_cleared','0')}")
                if self.tag=='SPEED':
                    velocity=int(value.get('velocity_mrad_s','0'))/1000
                    angle=int(value.get('delta_mrad','0'))/1000*180/3.141592654
                    self.metrics.set(self.metrics.get()+f"\n实际速度：{velocity:.3f} rad/s　位移：{angle:.1f}°　转动确认：{value.get('motion_confirmed','0')}　速度目标清零：{value.get('target_cleared','0')}")
                elif self.tag in ('DUAL_SPEED','DUAL_FAULT','DUAL_POSITION','SYNC_POSITION'):
                    rows=[]
                    for ident,model in [('1','10P'),('2','00')]:
                        motor=value.get('motors',{}).get(ident,{})
                        velocity=int(motor.get('velocity_mrad_s','0'))/1000
                        angle=int(motor.get('delta_mrad','0'))/1000*180/3.141592654
                        if self.tag=='SYNC_POSITION':
                            deg=lambda key:int(motor.get(key,'0'))/1000000*180/3.141592654
                            rows.append(f"{model} ID{ident}：{int(motor.get('elapsed_ms','0'))/1000:.1f}s · {motor.get('cycles_completed','0')}/5轮 · 目标{deg('target_delta_urad'):.2f}°/实际{deg('delta_urad'):.2f}° · 误差 RMS {deg('tracking_rms_urad'):.3f}°/峰值{deg('tracking_peak_urad'):.3f}° · 停机{motor.get('stop_confirmed','0')}")
                            continue
                        if self.tag=='DUAL_POSITION':
                            target=int(motor.get('target_delta_mrad','0'))/1000*180/3.141592654
                            error=int(motor.get('max_return_error_mrad','0'))/1000*180/3.141592654
                            rows.append(f"{model} ID{ident}：轮{motor.get('cycles_completed','0')}/10 · 目标{target:.2f}°/实际{angle:.2f}° · 回起点最大误差{error:.2f}° · 稳定{motor.get('stable_elapsed_ms','0')}ms/{motor.get('stable_samples','0')}点 · Iq {motor.get('iq_mA','—')}mA · 停机{motor.get('stop_confirmed','0')}")
                            continue
                        rows.append(f"{model} ID{ident}：{velocity:.3f}rad/s · {angle:.1f}° · Iq {motor.get('iq_mA','—')}mA · 转动{motor.get('motion_confirmed','0')} / 停机{motor.get('stop_confirmed','0')} / 清零{motor.get('target_cleared','0')}")
                    self.metrics.set('\n'.join(rows))
                    if self.tag=='SYNC_POSITION':
                        shared=value.get('motors',{}).get('1',{})
                        gap=f"{int(shared.get('progress_gap_ppm','0'))/10000:.2f}%" if shared.get('progress_valid')=='1' else '等待可对齐采样'
                        self.metrics.set(self.metrics.get()+f"\n同采样时刻估算的进度差：{gap} · 最大目标调度迟到{shared.get('max_lateness_ms','0')}ms · 最大成对提交间隔{shared.get('max_pair_skew_ms','0')}ms")
                self.enable_button.configure(state='normal' if name=='READY' and self.session_ok and not self.stop_requested.is_set() else 'disabled')
            elif kind=='disconnected':
                self.heartbeat_button.configure(state='disabled')
                self.connected=False;self.session_ok=False;self.enable_button.configure(state='disabled')
                self.stop_button.configure(state='disabled');self.disconnect_button.configure(state='disabled');self.busy(False)
                if self.closing:self.destroy();return
        self._poll_timer=self.window.after(100,self.poll)
    def destroy(self):
        self.closed=True
        timer=getattr(self,'_poll_timer',None)
        if timer:
            self.window.after_cancel(timer);self._poll_timer=None
        try:self.window.grab_release()
        except tk.TclError:pass
        self.window.destroy()
    def close(self):
        if self.thread and self.thread.is_alive():
            if any(j.kind=='flash' and j.status=='running' for j in self.manager.jobs.values()):
                messagebox.showinfo('正在烧录','请等待写入和校验完成。',parent=self.window);return
            self.closing=True;self.disconnect_now();self.state.set('正在请求停机并保存日志…')
        else:self.destroy()

class SpeedPanel(EnablePanel):
    tag='SPEED'
    command='RUN'
    profile_ids=('RS10P-Speed-CAN1','RS00-Speed-CAN1')
    headline='单台电机 · 低速转动'
    start_label='3 开始低速转动 · 最长3秒'
    explanation='本次将实际转动：run_mode=2，目标0.3rad/s（约2.9rpm），限流0.5A，加速度0.5rad/s²。先核对零速度和限制参数，再使能并手动开始；停止后核对速度目标清零。不保存、不改ID/波特率/机械零位。'
    phase_labels={**PHASES,'READY':'已停机，等待手动开始转动','ENABLED':'低速转动中',
        'SPEED_SETUP_WRITE':'写入速度实验参数','SPEED_SETUP_READ':'核对速度实验参数',
        'READ_START_POSITION':'读取起始位置','SPEED_POSTCHECK':'使能后复核零速度和限制',
        'SET_SPEED_TARGET':'设置低速目标','VERIFY_SPEED_TARGET':'核对低速目标',
        'CLEAR_SPEED_TARGET':'已停机，清零速度目标','VERIFY_CLEARED_TARGET':'核对速度目标清零'}

class StartupSpeedPanel(SpeedPanel):
    profile_ids=('RS10P-Speed-0700mA',)
    headline='单台RS10P · 起转电流测试 · 0.7A'
    start_label='3 开始0.7A起转测试 · 最长3秒'
    explanation='将实际转动：ID1，速度模式2、目标0.3rad/s、限流0.7A、加速度0.5rad/s²。实测Iq超过0.8A、速度/位移异常或位置反馈突跳请求停机。先停机核对零速度与限制，再使能复核后放行；结束确认停机并清零速度目标。不保存、不改ID/波特率/零位/增益。0.7A是本次诊断设定，不是厂家规定的起转电流。'

class DualSpeedPanel(SpeedPanel):
    tag='DUAL_SPEED'
    profile_ids=('Motors-Speed-CAN1',)
    headline='双电机 · CAN1低速联调'
    connection_hint='CAN1 · 1Mbps · 10P ID1 / 00 ID2。CANH、CANL同名并接；两台固定外壳、空载测试，准备好同时断电。'
    start_label='3 两台开始低速转动 · 最长3秒'
    explanation='两台都会实际转动：10P ID1、00 ID2，每台0.3rad/s（约2.9rpm）、限流0.5A、加速度0.5rad/s²。两台复核通过才发转动目标，任一台异常请求两台停机；不验证机械同步。不保存、不改ID/波特率/机械零位。'
    phase_labels={**SpeedPanel.phase_labels,'WAIT_BOTH':'等待两台状态一致','READY':'两台已停机，等待手动开始','ENABLED':'两台低速转动中'}

class FaultPanel(DualSpeedPanel):
    tag='DUAL_FAULT'
    profile_ids=('Motors-Fault-ID1','Motors-Fault-ID2')
    headline='双电机 · 运行反馈超时与联动停机'
    start_label='3 开始低速与反馈超时验证'
    explanation='两台空载低速转动，确认动作后自动屏蔽所选电机正常运行反馈；故障报文和停机反馈不屏蔽。预期500ms反馈超时，请求两台停机并核对速度目标清零。这是软件注入，不代表真实CAN断线保护已验证。'

class PositionPanel(EnablePanel):
    tag='POSITION'
    command='RUN'
    profile_ids=('RS10P-Position-Cycles','RS00-Position-Cycles')
    headline='单台电机 · 连续小角度位置往返'
    start_label='3 开始±5°位置往返 · 10轮'
    explanation='读取当前实际位置为起点，执行+5°→起点→-5°→起点，共10轮。CSP位置模式5，限速0.2rad/s、限流0.5A，到位保持0.5秒；位置采样范围≤0.1°、至少4点。不保存、不改ID/波特率/机械零位。位置模式会主动保持位置，请空载固定。'
    stop_notice='完成40个目标点后停机，单点超时5秒、总超时90秒；心跳/反馈/采样中断500ms请求停机。停机后将位置目标设为停止时实测位置并回读确认，不是机械清零。'
    phase_labels={**PHASES,'READ_ORIGIN':'读取实测起点','POSITION_WRITE':'设置位置参数','POSITION_READ':'核对位置参数','CHECK_START_POSITION':'确认起点未移动','POSITION_POSTCHECK':'使能后复核位置参数','SET_POSITION_TARGET':'设置本轮目标','VERIFY_POSITION_TARGET':'核对位置目标','POSITION_MOVING':'位置往返与到位保持','READ_STOP_POSITION':'读取停机实际位置','HOLD_STOP_POSITION':'将目标中和到停机位置','VERIFY_STOP_TARGET':'核对停机位置目标'}

class DualPositionPanel(DualSpeedPanel):
    tag='DUAL_POSITION'
    profile_ids=('Motors-Independent-Position',)
    headline='双电机 · 独立位置轨迹联调'
    start_label='3 开始两台独立位置轨迹'
    explanation='10P ID1：+5°→起点→-5°→起点，停留500ms；00 ID2：-3°→起点→+3°→起点，停留800ms。各10轮，限速0.2rad/s、每台限流0.5A。两台复核通过才放行目标，任一异常请求两台停机；正常完成的一台停机等待另一台。'
    stop_notice='这是双轴独立目标与进度测试，不验证机械同步。CAN允许自动重发，单帧300ms未完成请求停机；各轴90秒总超时，心跳/反馈/采样500ms超时停机。暂停电脑心跳按钮仅停止KEEP，保留日志接收。'
    phase_labels={**PositionPanel.phase_labels,'WAIT_BOTH':'两台独立运行或等待另一台完成','READY':'两台已停机，等待手动开始'}

class SyncPositionPanel(DualPositionPanel):
    tag='SYNC_POSITION'
    profile_ids=('Motors-Sync-Position',)
    headline='双电机 · 共同时间轴平滑轨迹'
    start_label='3 开始平滑轨迹 · 5轮'
    explanation='10P ID1：起点→+5°→起点→-5°→起点；00 ID2：起点→-3°→起点→+3°→起点。每段2秒、每轮8秒，共5轮。MCU每50ms生成共同时间轴上的五次平滑位置目标；限速0.2rad/s、限流0.5A。两台复核且收到实际量后才开始。'
    stop_notice='轨迹40秒，末尾最多3秒确认回到起点并稳定，再停机和目标中和。误差>2°持续500ms、失联500ms、过流或过速请求两台停机；CAN保留300ms截止。采样峰值≤2°、RMS≤1°且两台完整完成才通过。进度差为异步采样插值估计，不代表硬件同步。'
    phase_labels={**DualPositionPanel.phase_labels,'SYNC_TRACKING':'两台跟踪共同时间轴','SYNC_SETTLING':'轨迹结束，确认两台回到起点','WAIT_BOTH':'等待两台复核或状态更新'}

if __name__=='__main__':
    app=(DualSpeedPanel if '--dual-speed' in sys.argv else SpeedPanel if '--speed' in sys.argv else EnablePanel)();app.window.mainloop()
