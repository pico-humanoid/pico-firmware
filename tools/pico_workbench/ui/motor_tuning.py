"""Operator-triggered position / independent Iq tuning. No motor starts on connect."""
from datetime import datetime
import json, math, queue, re, secrets, subprocess, threading, time
import tkinter as tk
from tkinter import ttk,messagebox,scrolledtext
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent/'vendor'))
import serial
from serial.tools.list_ports import comports
import catalog
import platform_tools as tools
from engine import Manager
from runtime_paths import project_root
from experiment_log import capture_notes, display_line, show_legend
from tuning_scope import TuningScope,fields

ACTIVE={'RUNNING','APPLY_WRITE','APPLY_READ'}
BACKEND='d8451a447d7265becf71271a008a71f7063b7ecc'
def validate_banner(line,profile):
    if not line.startswith('# PICO_MOTOR_TUNING=1;'):return False
    d=dict(re.findall(r'(\w+)=([^\s;]+)',line));o=profile['cmake_options']
    dual=int(o.get('PICO_TUNE_COUNT',1))==2
    expected={'channel':'FDCAN1','bitrate':'1000000','model':'RS10P,RS00' if dual else o['PICO_TUNE_MODEL'],'motor_id':'0' if dual else str(o['PICO_TUNE_MOTOR_ID']),'motor_count':'2' if dual else '1','host_id':'253','protocol':'6','position_limit_mdeg':'30000','current_limit_ma':'5300','speed_limit_mrad':'300','max_position_ms':'300000','max_speed_ms':'60000','host_timeout_ms':'500'}
    if any(d.get(k)!=v for k,v in expected.items()):raise ValueError('板内交互跟踪固件与所选电机或保护参数不匹配，请重新烧录。')
    return True

def encode_target(mode,angle,speed_limit,velocity):
    if mode=='POS':
        angle,speed_limit=float(angle),float(speed_limit)
        if not math.isfinite(angle) or not math.isfinite(speed_limit) or not -30<=angle<=30 or not .01<=speed_limit<=.3:raise ValueError('角度范围±30°，限速0.01–0.3rad/s。')
        return round(angle*1000),round(speed_limit*1000)
    if mode!='SPD':raise ValueError('请选择位置或速度模式。')
    velocity=float(velocity)
    if not math.isfinite(velocity) or not -.3<=velocity<=.3:raise ValueError('速度目标范围±0.3rad/s。')
    return round(velocity*1000),0

def duration_ms(mode,text):
    value=float(text);maximum=300 if mode=='POS' else 60
    if not math.isfinite(value) or not 1<=value<=maximum:raise ValueError(f'本模式实验时长范围1～{maximum}秒。')
    return round(value*1000)

class NumericSlider(ttk.Frame):
    """A bounded slider synchronized with an editable, validated numeric entry."""
    def __init__(self,parent,label,variable,lo,hi,step,digits,reset=0):
        super().__init__(parent);self.variable=variable;self.lo=lo;self.hi=hi;self.step=step;self.digits=digits
        ttk.Label(self,text=label,width=24).pack(side='left')
        ttk.Label(self,text=f'{lo:g}',width=5).pack(side='left')
        self.value=tk.DoubleVar(value=float(variable.get()))
        self.slider=ttk.Scale(self,from_=lo,to=hi,variable=self.value,command=self.slide);self.slider.pack(side='left',fill='x',expand=True,padx=6)
        ttk.Label(self,text=f'{hi:g}',width=5).pack(side='left')
        self.entry=ttk.Entry(self,textvariable=variable,width=9);self.entry.pack(side='left',padx=6)
        self.reset_button=ttk.Button(self,text='设为0' if reset==0 else '默认',width=6,command=lambda:variable.set(f'{reset:.{digits}f}'));self.reset_button.pack(side='left')
        self.trace=variable.trace_add('write',self.sync);self.bind('<Destroy>',self.cleanup)
    def slide(self,raw):
        value=max(self.lo,min(self.hi,round(float(raw)/self.step)*self.step))
        self.variable.set(f'{value:.{self.digits}f}')
    def sync(self,*_):
        try:value=float(self.variable.get())
        except ValueError:return
        if math.isfinite(value) and self.lo<=value<=self.hi and abs(value-self.value.get())>1e-8:self.value.set(value)
    def set_enabled(self,on):
        for widget in (self.slider,self.entry,self.reset_button):widget.configure(state='normal' if on else 'disabled')
    def cleanup(self,event):
        if event.widget is self:self.variable.trace_remove('write',self.trace)

class TuningPanel:
    def __init__(self,parent=None,manager=None,selected=None):
        from appearance import apply_theme
        self.window=tk.Toplevel(parent) if parent else tk.Tk();apply_theme(self.window)
        self.window.title('PICO · 交互跟踪示波器');self.window.geometry('1200x980');self.window.minsize(1000,780)
        if parent:self.window.transient(parent);self.window.grab_set()
        self.manager=manager or Manager();self.events=queue.Queue();self.commands=queue.Queue()
        self.connection_job=False;self.thread=None;self.disconnect=threading.Event();self.stop_requested=threading.Event();self.closed=False;self.closing=False
        self.connected=False;self.armed=False;self.last_state={};self.seq=0;self.last_line_at=0;self.live_timer=None
        self.profiles=[catalog.profile(p) for p in ('RS10P-Tuning','RS00-Tuning','Motors-Tuning')];self.uid_values={}
        f=ttk.Frame(self.window,padding=16);f.pack(fill='both',expand=True)
        ttk.Label(f,text='电机 · 交互跟踪示波器',font=('Microsoft YaHei UI',20,'bold')).pack(anchor='w')
        ttk.Label(f,text='CAN1 / 1Mbps · PA12 TX / PA11 RX · 空载并固定外壳；双机为10P ID1 + 00 ID2。连接不会使能。',wraplength=1120).pack(anchor='w',pady=6)
        bar=ttk.Frame(f);bar.pack(fill='x',pady=5)
        self.choice=ttk.Combobox(bar,state='readonly',values=[p['name'] for p in self.profiles],width=42);self.choice.pack(side='left');self.choice.current(next((i for i,p in enumerate(self.profiles) if p['id']==selected),0))
        self.port=ttk.Combobox(bar,state='readonly',width=44);self.port.pack(side='left',padx=8)
        self.refresh_button=ttk.Button(bar,text='刷新串口',command=self.refresh);self.refresh_button.pack(side='left')
        bar=ttk.Frame(f);bar.pack(fill='x',pady=8)
        self.prepare_button=ttk.Button(bar,text='1 编译并烧录',command=self.prepare);self.prepare_button.pack(side='left')
        self.connect_button=ttk.Button(bar,text='2 连接并复位',command=self.connect);self.connect_button.pack(side='left',padx=8)
        self.start_button=ttk.Button(bar,text='3 开始跟踪',command=self.arm,state='disabled');self.start_button.pack(side='left')
        self.stop_button=tk.Button(bar,text='立即停机',bg='#b42318',fg='white',command=self.stop,state='disabled');self.stop_button.pack(side='left',padx=10)
        ttk.Button(bar,text='VS Code 本实验项目',command=self.open_code).pack(side='right')
        self.disconnect_button=ttk.Button(bar,text='断开',command=self.disconnect_now,state='disabled');self.disconnect_button.pack(side='left')
        self.layout=ttk.Panedwindow(f,orient='vertical');self.layout.pack(fill='both',expand=True)
        controls=ttk.LabelFrame(self.layout,text='目标控制 · 切换模式须停机，再重新连接复位',padding=10);self.layout.add(controls,weight=1)
        self.mode=tk.StringVar(value='POS');self.mode_buttons=[]
        for value,label in [('POS','位置跟踪'),('SPD','独立速度目标')]:
            b=ttk.Radiobutton(controls,text=label,value=value,variable=self.mode,command=self.mode_changed);b.pack(anchor='w');self.mode_buttons.append(b)
        duration_row=ttk.Frame(controls);duration_row.pack(fill='x',pady=4)
        ttk.Label(duration_row,text='运行时长 / 秒').pack(side='left');self.duration=tk.StringVar(value='60')
        self.duration_entry=ttk.Spinbox(duration_row,from_=1,to=300,increment=1,textvariable=self.duration,width=9);self.duration_entry.pack(side='left',padx=8)
        ttk.Label(duration_row,text='开始前设置；开发板计时。双机共用时长。').pack(side='left')
        self.control_columns=ttk.Frame(controls);self.control_columns.pack(fill='x')
        self.primary_controls=ttk.LabelFrame(self.control_columns,text='电机1',padding=4);self.primary_controls.pack(side='left',fill='x',expand=True)
        self.angle=tk.StringVar(value='0');self.speed_limit=tk.StringVar(value='0.2');self.velocity=tk.StringVar(value='0')
        self.sliders=[]
        for label,var,lo,hi,step,digits,reset in [('相对起点角度 / °',self.angle,-30,30,.1,1,0),('位置模式限速 / rad/s',self.speed_limit,.01,.3,.01,2,.2),('独立速度目标 / rad/s',self.velocity,-.3,.3,.01,2,0)]:
            control=NumericSlider(self.primary_controls,label,var,lo,hi,step,digits,reset);control.pack(fill='x',pady=3);self.sliders.append(control)
        self.secondary_controls=ttk.LabelFrame(self.control_columns,text='RS00 · ID2',padding=4)
        self.angle2=tk.StringVar(value='0');self.speed_limit2=tk.StringVar(value='0.2');self.velocity2=tk.StringVar(value='0');self.sliders2=[]
        for label,var,lo,hi,step,digits,reset in [('相对起点角度 / °',self.angle2,-30,30,.1,1,0),('位置限速 / rad/s',self.speed_limit2,.01,.3,.01,2,.2),('速度目标 / rad/s',self.velocity2,-.3,.3,.01,2,0)]:
            control=NumericSlider(self.secondary_controls,label,var,lo,hi,step,digits,reset);control.pack(fill='x',pady=3);self.sliders2.append(control)
        self.inputs=[control.entry for control in self.sliders]
        self.current_limit=tk.StringVar(value='5.3');self.current_limit2=tk.StringVar(value='4.7')
        self.current_slider=NumericSlider(self.primary_controls,'限流 / A（开始前）',self.current_limit,.1,5.3,.01,2,5.3);self.current_slider.pack(fill='x',pady=3)
        self.current_slider2=NumericSlider(self.secondary_controls,'限流 / A（开始前）',self.current_limit2,.1,4.7,.01,2,4.7);self.current_slider2.pack(fill='x',pady=3)
        row=ttk.Frame(controls);row.pack(fill='x',pady=5)
        self.apply_button=ttk.Button(row,text='应用目标',command=self.apply,state='disabled');self.apply_button.pack(side='left')
        ttk.Label(row,text='限流在开始前设置；运行中查看实际Iq和已回读限流。').pack(side='left',padx=12)
        self.live=tk.BooleanVar(value=False);ttk.Checkbutton(controls,text='编辑后自动应用（200ms合并，须已手动开始）',variable=self.live).pack(anchor='w')
        self.note=ttk.Label(controls,wraplength=1100);self.note.pack(anchor='w',pady=4)
        self.current_readout=tk.StringVar(value='实际电流：等待反馈');ttk.Label(f,textvariable=self.current_readout,font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w')
        self.current_values={}
        self.alarm=tk.StringVar(value='');ttk.Label(f,textvariable=self.alarm,foreground='#b42318',font=('Microsoft YaHei UI',12,'bold'),wraplength=1100).pack(anchor='w')
        self.uid=tk.StringVar(value='UID：尚未读取');ttk.Label(f,textvariable=self.uid).pack(anchor='w')
        self.status=tk.StringVar(value='未连接；先烧录所选电机的交互跟踪固件。');ttk.Label(f,textvariable=self.status,font=('Microsoft YaHei UI',11,'bold'),wraplength=1100).pack(anchor='w',pady=7)
        self.folder=tk.StringVar(value='日志：尚未创建');ttk.Label(f,textvariable=self.folder).pack(anchor='w')
        tabs=ttk.Notebook(self.layout);self.layout.add(tabs,weight=2)
        self.scope_panes=ttk.Panedwindow(tabs,orient='horizontal');tabs.add(self.scope_panes,text='实时示波器')
        self.scope_frame=ttk.LabelFrame(self.scope_panes,text='电机1');self.scope_panes.add(self.scope_frame,weight=1)
        self.scope=TuningScope(self.scope_frame);self.scope.pack(fill='both',expand=True)
        self.scope_frame2=ttk.LabelFrame(self.scope_panes,text='RS00 · ID2');self.scope2=TuningScope(self.scope_frame2);self.scope2.pack(fill='both',expand=True)
        log=ttk.Frame(tabs);tabs.add(log,text='中文日志与原文')
        ttk.Button(log,text='日志说明',command=lambda:show_legend(self.window)).pack(anchor='e',padx=6,pady=3)
        self.output=scrolledtext.ScrolledText(log,height=8,font=('Consolas',9));self.output.pack(fill='both',expand=True)
        for var in (self.angle,self.speed_limit,self.velocity,self.angle2,self.speed_limit2,self.velocity2):var.trace_add('write',self.edited)
        self.choice.bind('<<ComboboxSelected>>',lambda _:self.profile_changed())
        self.profile_changed();self.mode_changed();self.refresh();self.window.protocol('WM_DELETE_WINDOW',self.close);self.timer=self.window.after(80,self.poll)
    def dual(self):return int(self.profile()['cmake_options'].get('PICO_TUNE_COUNT',1))==2
    def profile_changed(self):
        dual=self.dual();rated=4.7 if self.profile()['cmake_options'].get('PICO_TUNE_MODEL')=='RS00' and not dual else 5.3
        self.current_limit.set(str(rated));self.current_limit2.set('4.7');self.current_slider.hi=rated;self.current_slider.slider.configure(to=rated);self.current_slider.reset_button.configure(command=lambda:self.current_limit.set(str(rated)))
        self.scope.latest.configure(wraplength=450 if dual else 980);self.scope2.latest.configure(wraplength=450);self.primary_controls.configure(text='RS10P · ID1' if dual else self.profile()['name']);self.scope_frame.configure(text='RS10P · ID1' if dual else self.profile()['name'])
        if dual:
            self.secondary_controls.pack(side='left',fill='x',expand=True,padx=(8,0))
            if str(self.scope_frame2) not in self.scope_panes.panes():self.scope_panes.add(self.scope_frame2,weight=1)
        else:
            self.secondary_controls.pack_forget()
            if str(self.scope_frame2) in self.scope_panes.panes():self.scope_panes.forget(self.scope_frame2)
    def mode_changed(self):
        pos=self.mode.get()=='POS'
        for i,control in enumerate(self.sliders+self.sliders2):control.set_enabled((i%3<2)==pos)
        self.duration_entry.configure(to=300 if pos else 60)
        self.duration.set('60' if pos else '3')
        self.note.configure(text='POS：±30°，可调限速0.01–0.3rad/s，限流0.5A；实际位移超过32°请求停机。' if pos else 'SPD：速度目标±0.3rad/s，加速度0.5rad/s²，限流0.5A，时长1–60秒；不保持角度，位移保护随所设时长计算。')
    def refresh(self):
        self.ports=list(comports());self.port['values']=[p.device+' · '+p.description for p in self.ports]
        matches=[i for i,p in enumerate(self.ports) if p.vid==0x0483]
        if len(matches)==1:self.port.current(matches[0])
    def open_code(self):
        try:tools.launch_app('vscode',self.profile()['id'])
        except Exception as e:messagebox.showerror('无法打开',str(e),parent=self.window)
    def profile(self):return self.profiles[self.choice.current()]
    def edited(self,*_):
        if self.live_timer:self.window.after_cancel(self.live_timer)
        self.live_timer=self.window.after(200,self.live_apply)
    def live_apply(self):
        self.live_timer=None
        if self.live.get() and self.connected and self.last_state.get('state') in ACTIVE:self.apply()
    def target(self):return encode_target(self.mode.get(),self.angle.get(),self.speed_limit.get(),self.velocity.get())
    def enqueue(self,kind):
        try:
            targets=[self.target()]
            if self.dual():targets.append(encode_target(self.mode.get(),self.angle2.get(),self.speed_limit2.get(),self.velocity2.get()))
            limits=[float(self.current_limit.get())]+([float(self.current_limit2.get())] if self.dual() else [])
            maxima=[4.7 if self.profile()['cmake_options'].get('PICO_TUNE_MODEL')=='RS00' and not self.dual() else 5.3]+([4.7] if self.dual() else [])
            if any(not math.isfinite(v) or not .1<=v<=maxima[i] for i,v in enumerate(limits)):raise ValueError('限流不得超过对应型号额定值：RS10P 5.3A，RS00 4.7A。')
            targets=[(*pair,round(limits[i]*1000)) for i,pair in enumerate(targets)]
            duration=duration_ms(self.mode.get(),self.duration.get())
        except ValueError as e:return messagebox.showerror('目标无效',str(e),parent=self.window)
        if not self.connected or self.stop_requested.is_set():return
        if kind=='ARM' and self.last_state.get('state')!='READY':return
        if kind=='SET' and self.last_state.get('state') not in ACTIVE:return
        self.seq+=1;self.commands.put((kind,self.mode.get(),self.seq,targets,duration,time.monotonic()))
        if kind=='ARM':
            self.armed=True;self.current_slider.set_enabled(False);self.current_slider2.set_enabled(False);self.duration_entry.configure(state='disabled')
            self.last_state={'state':'PREPARING'};self.update_controls()
            for b in self.mode_buttons:b.configure(state='disabled')
    def arm(self):self.enqueue('ARM')
    def apply(self):self.enqueue('SET')
    def stop(self):self.stop_requested.set();self.start_button.configure(state='disabled');self.apply_button.configure(state='disabled');self.status.set('请求停机，等待电机反馈及目标清零确认。')
    def disconnect_now(self):self.stop();self.disconnect.set()
    def launch(self,fn):
        if self.thread and self.thread.is_alive():return
        self.busy(True)
        def run():
            try:fn()
            except Exception as e:self.events.put(('error',str(e)))
            finally:self.events.put(('finished',None))
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start()
    def busy(self,on):
        self.choice.configure(state='disabled' if on else 'readonly');self.port.configure(state='disabled' if on else 'readonly')
        for b in (self.prepare_button,self.connect_button,self.refresh_button):b.configure(state='disabled' if on else 'normal')
    def prepare(self):
        self.connection_job=False
        profile=self.profile()['id']
        def run():
            for kind in ('build','flash'):
                if self.closing:return
                job=self.manager.start(kind,profile);after=0
                while True:
                    snap=job.snapshot(True,after)
                    for ln in snap['lines']:self.events.put(('line',ln['text']))
                    after=snap['sequence']
                    if job.status!='running':break
                    time.sleep(.1)
                if job.status!='pass':raise RuntimeError(str(job.result))
            self.events.put(('line','烧录完成。点击连接并复位；READY后手动开始。'))
        self.launch(run)
    def connect(self):
        if self.port.current()<0:return messagebox.showerror('串口','请选择ST-LINK串口。',parent=self.window)
        p=self.ports[self.port.current()]
        if p.vid!=0x0483 or not p.serial_number:return messagebox.showerror('串口','需要带序列号的ST-LINK串口。',parent=self.window)
        self.connection_job=True
        profile=self.profile();self.seq=0;self.connected=False;self.last_state={};self.disconnect.clear();self.stop_requested.clear()
        while not self.commands.empty():self.commands.get_nowait()
        self.launch(lambda:self.worker(p,profile))
    def worker(self,port,profile):
        token=secrets.token_hex(4).upper();dual=int(profile['cmake_options'].get('PICO_TUNE_COUNT',1))==2;motor_id=0 if dual else profile['cmake_options']['PICO_TUNE_MOTOR_ID']
        out=project_root()/'logs'/('motor-tuning-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True)
        self.events.put(('folder',str(out)));last={};result=None
        (out/'settings.json').write_text(json.dumps({'profile':profile,'port':port.device,'baud':115200},ensure_ascii=False,indent=2),encoding='utf-8')
        with capture_notes(out, lambda text: self.events.put(('notes',text)), profile['name']), \
             (out/'board.log').open('wb') as raw,(out/'commands.jsonl').open('w',encoding='utf-8') as cmdlog,serial.Serial(port.device,115200,timeout=.02,write_timeout=.2) as dev:
            def write(text):
                data=(text+'\n').encode('ascii')
                if dev.write(data)!=len(data):raise RuntimeError('串口写入不完整')
                cmdlog.write(json.dumps({'at':datetime.now().isoformat(),'command':text})+'\n');cmdlog.flush()
            try:
                dev.reset_input_buffer()
                reset=subprocess.run(tools.reset_command(port.serial_number),env=tools.environment(),capture_output=True,timeout=15)
                (out/'reset.log').write_bytes(reset.stdout+reset.stderr)
                if reset.returncode:raise RuntimeError('复位失败，未发送使能。')
                buf=bytearray();start=time.monotonic();seen=False;backend=False;ready=False;session=False;handshake=keep=0.;stop_sent=False;closing=None;last_rx=start
                while True:
                    now=time.monotonic();data=dev.read(dev.in_waiting or 1)
                    if data:raw.write(data);raw.flush();buf.extend(data)
                    if len(buf)>65536:raise RuntimeError('串口数据格式异常')
                    while b'\n' in buf:
                        ln,_,rest=buf.partition(b'\n');buf=bytearray(rest);text=ln.decode('utf-8',errors='replace').strip();self.events.put(('line',text))
                        if text.startswith('# PICO_MOTOR_TUNING=1;'):
                            validate_banner(text,profile);seen=True;backend=ready=session=False;last={};result=None;start=now;token=secrets.token_hex(4).upper()
                            while not self.commands.empty():self.commands.get_nowait()
                            self.events.put(('reset',None))
                        if text.startswith('# CONTROL_BACKEND,') and seen:
                            if ('commit='+BACKEND) not in text:raise RuntimeError('官方库版本不匹配')
                            backend=True
                        if text=='# TUNE_COMMAND_READY=1; protocol=6' and seen and backend:ready=True
                        if text==f'# SESSION_OK token={token} id={motor_id}':session=True;self.events.put(('connected',None))
                        if text.startswith('# TUNE_STATE,'):
                            individual=fields(text)
                            if individual.get('id') not in (('1','2') if dual else (str(motor_id),)):raise RuntimeError('状态电机ID不匹配')
                            if not dual:last=individual;last_rx=now;self.events.put(('state',last))
                        if dual and text.startswith('# TUNE_GROUP_STATE,'):
                            last=fields(text);last_rx=now;self.events.put(('state',last))
                        if text.startswith('# TUNE_GROUP_RESULT,' if dual else '# TUNE_RESULT,'):result=fields(text);self.events.put(('result',result))
                    if not ready and now-start>5:raise RuntimeError('未收到匹配固件、官方库或就绪标识。请先烧录。')
                    if ready and not session and now>=handshake:
                        write(f'SESSION {token} {motor_id}');handshake=now+.5
                    if not session and now-start>8:raise RuntimeError('会话建立失败，未发送使能。')
                    if session and now>=keep:write('KEEP '+token);keep=now+.1
                    if session and now-last_rx>1.0 and last.get('state') not in ('DONE',None) and not stop_sent:
                        self.stop_requested.set();self.disconnect.set();self.events.put(('error','板端状态超时，已请求停机并等待确认。'))
                    if self.stop_requested.is_set() and ready and not stop_sent:write('STOP');stop_sent=True
                    pending=[]
                    while not self.commands.empty():pending.append(self.commands.get_nowait())
                    # ARM is never replaced by an edit; SET keeps only the latest pending target.
                    selected=[c for c in pending if c[0]=='ARM'];updates=[c for c in pending if c[0]=='SET']
                    if updates:selected.append(updates[-1])
                    for kind,mode,seq,targets,duration,at in selected:
                        if not session or self.stop_requested.is_set() or now-at>.5:continue
                        payload=' '.join(f'{target[0]} {target[1]}' for target in targets)
                        if kind=='ARM' and last.get('state')=='READY':
                            for i,target in enumerate(targets):write(f'LIMIT {token} {i+1 if dual else motor_id} {target[2] if len(target)>2 else 500}')
                            write(f'{"ARM2" if dual else "ARM"} {token} {mode} {seq} {payload} {duration}')
                            (out/'run-settings.json').write_text(json.dumps({'mode':mode,'duration_ms':duration,'targets':[{'id':i+1 if dual else motor_id,'value_mdeg_or_mrad_s':v,'speed_limit_mrad_s':limit} for i,(v,limit,*current) in enumerate(targets)]},ensure_ascii=False,indent=2),encoding='utf-8')
                        elif kind=='SET' and last.get('state') in ACTIVE:
                            if dual:write(f'SET2 {token} {seq} {payload}')
                            elif mode=='POS':write(f'SET {token} {seq} {payload}')
                            else:write(f'SETSPEED {token} {seq} {targets[0][0]}')
                    if self.disconnect.is_set():
                        if closing is None:closing=now
                        if last.get('state')=='DONE' and last.get('stop_confirmed')=='1':break
                        if now-closing>2.5:raise RuntimeError('停机未确认，请使用实物断电措施。')
            finally:
                try:write('STOP')
                except Exception:pass
                (out/'result.json').write_text(json.dumps({'last_state':last,'result':result,'stop_confirmed':last.get('stop_confirmed')=='1','target_cleared':last.get('target_cleared')=='1','automatic_hardware_pass':False},ensure_ascii=False,indent=2),encoding='utf-8')
    def update_controls(self):
        fresh=time.monotonic()-self.last_line_at<1
        active=self.connected and fresh and not self.stop_requested.is_set()
        self.start_button.configure(state='normal' if active and not self.armed and self.last_state.get('state')=='READY' else 'disabled')
        self.apply_button.configure(state='normal' if active and self.last_state.get('state') in ACTIVE else 'disabled')
    def poll(self):
        if self.closed:return
        log_lines=[];deadline=time.perf_counter()+.008
        for _ in range(250):
            if time.perf_counter()>=deadline:break
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='line':
                if value.startswith('# TUNE_SAMPLE,'):
                    sample=fields(value);self.current_values[sample.get('id','?')]=f"Iq {int(sample['iq_mA'])/1000:+.3f}A / 限流 {int(sample['limit_mA'])/1000:.2f}A";self.current_readout.set(' | '.join('ID'+k+' '+v for k,v in self.current_values.items()))
                if value.startswith('# TUNE_UID,'):
                    data=fields(value);self.uid_values[data.get('id','?')]=data.get('uid','未知');self.uid.set(' | '.join('ID'+k+' UID '+v for k,v in self.uid_values.items()))
                if value.startswith('# PICO_MOTOR_TUNING=1;'):
                    self.alarm.set('');self.uid_values.clear();self.uid.set('UID：等待重新读取');self.scope.feed(value);self.scope2.feed(value)
                else:
                    scope=self.scope2 if self.dual() and fields(value).get('id')=='2' else self.scope
                    scope.feed(value)
                log_lines.append(display_line(value))
            elif kind=='notes':log_lines.append(value)
            elif kind=='folder':self.folder.set(value)
            elif kind=='connected':self.connected=True;self.stop_button.configure(state='normal');self.disconnect_button.configure(state='normal')
            elif kind=='reset':
                self.connected=False;self.armed=False;self.last_state={};self.seq=0;self.stop_requested.clear();self.duration_entry.configure(state='normal');self.current_slider.set_enabled(True);self.current_slider2.set_enabled(True)
                for b in self.mode_buttons:b.configure(state='normal')
            elif kind=='state':
                if value.get('error')=='1':self.alarm.set('报警：'+('疑似受阻或堵转，已请求停机；请检查负载。' if value.get('reason')=='SUSPECTED_OBSTRUCTION' else value.get('reason','电机异常'))+' 请核对停机确认，未确认时使用实物断电。')
                self.last_state=value;self.last_line_at=time.monotonic();self.status.set(f"{value.get('state')} · {value.get('reason')} · 提交 #{value.get('accepted_seq')} / 回读 #{value.get('applied_seq')} · 停机确认 {value.get('stop_confirmed')} · 清理确认 {value.get('target_cleared')} · 时间 {int(value.get('elapsed_ms',0))/1000:.1f}/{int(value.get('duration_ms',0))/1000:g}s")
                if value.get('state')!='READY':
                    for b in self.mode_buttons:b.configure(state='disabled')
                elif not self.stop_requested.is_set() and not self.armed:
                    for b in self.mode_buttons:b.configure(state='normal')
            elif kind=='result':
                self.last_state=dict(value,state='DONE');self.stop_requested.set()
                self.start_button.configure(state='disabled');self.apply_button.configure(state='disabled')
                self.status.set(f"结束：{value.get('reason')} · 停机确认 {value.get('stop_confirmed')} · 目标清理 {value.get('target_cleared')}。再次运行请重新连接复位。")
                if value.get('stop_confirmed')!='1':self.status.set('停机未确认，请使用实物断电措施。原因：'+value.get('reason','UNKNOWN'))
            elif kind=='error':self.status.set('操作失败：'+value);log_lines.append('操作失败：'+value)
            elif kind=='finished':
                self.connected=False;self.busy(False);self.stop_button.configure(state='disabled');self.disconnect_button.configure(state='disabled')
                if self.closing:
                    if self.connection_job and self.last_state.get('stop_confirmed')!='1':
                        self.closing=False;messagebox.showwarning('停机未确认','无法确认电机已停机，请使用实物断电措施。',parent=self.window)
                    else:self.destroy();return
        if log_lines:
            follow=self.output.yview()[1]>=.98
            self.output.insert('end','\n'.join(log_lines)+'\n')
            excess=int(self.output.index('end-1c').split('.')[0])-1500
            if excess>0:self.output.delete('1.0',f'{excess+1}.0')
            if follow:self.output.see('end')
        self.update_controls()
        self.timer=self.window.after(20 if not self.events.empty() else 80,self.poll)
    def close(self):
        if self.thread and self.thread.is_alive():self.closing=True;self.disconnect_now()
        else:self.destroy()
    def destroy(self):
        self.closed=True
        if self.live_timer:self.window.after_cancel(self.live_timer)
        try:self.window.after_cancel(self.timer)
        except Exception:pass
        self.window.destroy()
