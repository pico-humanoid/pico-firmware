"""Stopped-motor diagnostic UI. No enable, motor ID or calibration command."""
from datetime import datetime
import json,math,queue,re,secrets,subprocess,threading,time
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox,scrolledtext,filedialog
import catalog
import platform_tools as tools
from engine import Manager
from runtime_paths import project_root
from motor_enable import serial,comports

PARAMS={0x7005:('控制模式',''),0x7016:('位置目标 loc_ref','rad'),0x7019:('实际位置 mechPos','rad'),0x7029:('零位标志 zero_sta',''),0x702B:('零位偏置 add_offset','rad'),0x2005:('MechOffset（兼容读取）','rad'),0x7017:('限速','rad/s'),0x7018:('限流','A')}
def fields(line):return dict(v.split('=',1) for v in line.strip().split(',')[1:] if '=' in v)
def validate_banner(line,profile):
    if not line.startswith('# PICO_MOTOR_POSITION_DIAG=1;'):raise ValueError('不是停机位置诊断固件，请编译并烧录所选配置。')
    d=dict(re.findall(r'(\w+)=([^\s;]+)',line));opts=profile['cmake_options']
    expected={'channel':'FDCAN1','bitrate':'1000000','motor_id':str(opts['PICO_DIAG_MOTOR_ID']),'model':opts['PICO_DIAG_MODEL'],'host_id':'253','policy':'STOPPED_ECHO_V1','no_enable':'1','target_write':'manual_current_position_only','tx_policy':'BOUNDED_RETRY_V1'}
    if any(d.get(k)!=v for k,v in expected.items()):raise ValueError('诊断固件的对象或保护策略与界面不匹配。')
    return d
class DiagnosticData:
    def __init__(self):self.state={};self.values={};self.uid='未读取';self.version='未读取';self.echo=[];self.result=None;self.ranges={};self.read_errors={};self.motor_id=None
    def feed(self,line):
        if line.startswith('# PICO_MOTOR_POSITION_DIAG=1;'):
            self.__init__();match=re.search(r'\bmotor_id=(\d+)',line)
            if match:self.motor_id=int(match.group(1))
        elif line.startswith('# DIAG_STATE,'):self.state=fields(line)
        elif line.startswith('# DIAG_VALUE,'):
            d=fields(line);index=int(d['index'],16)
            if index in PARAMS:
                if index in self.read_errors:d=dict(d,status='READ_FAILED',reply_status=str(self.read_errors[index]))
                self.values[index]=d;value=self.value(index)
                if value is not None:
                    low,high,count=self.ranges.get(index,(value,value,0));self.ranges[index]=(min(low,value),max(high,value),count+1)
        elif line.startswith('# DIAG_UID,'):self.uid=fields(line).get('uid','无有效回复')
        elif line.startswith('# DIAG_VERSION,'):self.version=fields(line).get('value','无有效回复')
        elif line.startswith('# DIAG_ECHO,'):self.echo.append(fields(line))
        elif line.startswith(('# DIAG_ECHO_RESULT,','# DIAG_RESULT,')):self.result=fields(line)
        elif not line.startswith('#'):
            # Correct historical logs too: old firmware printed OK for type-17
            # failure replies. Preserve raw log text, but never display fake 0.
            row=line.split(',')
            if len(row)==8 and row[1:5]==['RX','FDCAN1','EXT','DATA'] and row[6]=='8':
                try:identifier=int(row[5],0);payload=bytes.fromhex(row[7])
                except ValueError:return
                if len(payload)!=8 or (identifier>>24)&31!=17 or (identifier&255)!=253:return
                if self.motor_id is not None and ((identifier>>8)&255)!=self.motor_id:return
                index=int.from_bytes(payload[:2],'little');status=(identifier>>16)&255
                if status:
                    self.read_errors[index]=status
                    if index in self.values:self.values[index]=dict(self.values[index],status='READ_FAILED',reply_status=str(status))
                else:self.read_errors.pop(index,None)
    def value(self,index):
        d=self.values.get(index,{})
        if d.get('status')!='OK':return None
        value=int(d['value_micro'])/1000000
        return value if math.isfinite(value) else None
    def can_verify(self):return self.state.get('echo_allowed')=='1' and self.state.get('error')=='0' and not any(i in self.read_errors for i in (0x7005,0x7016,0x7019))

class PositionDiagnosticPanel:
    profile_ids=('RS10P-Position-Diag','RS00-Position-Diag')
    def __init__(self,parent=None,manager=None,selected=None):
        self.window=tk.Toplevel(parent) if parent else tk.Tk()
        from appearance import apply_theme
        apply_theme(self.window);self.window.title('PICO · 停机位置诊断');self.window.geometry('1120x860');self.window.minsize(980,760)
        if parent:self.window.transient(parent);self.window.grab_set()
        self.manager=manager or Manager();self.events=queue.Queue();self.commands=queue.Queue();self.finish=threading.Event();self.thread=None;self.closed=self.closing=self.session_ok=False;self.data=DiagnosticData();self._timer=None
        f=ttk.Frame(self.window,padding=16);f.pack(fill='both',expand=True)
        ttk.Label(f,text='停机位置诊断',style='Title.TLabel').pack(anchor='w')
        ttk.Label(f,text='CAN1 · 1Mbps · 只接待测电机。连接后自动停机并读取；整个程序不发送使能命令。',wraplength=1060).pack(anchor='w',pady=6)
        row=ttk.Frame(f);row.pack(fill='x');self.profiles=[catalog.profile(p) for p in self.profile_ids]
        self.choice=ttk.Combobox(row,state='readonly',values=[p['name'] for p in self.profiles]);self.choice.current(self.profile_ids.index(selected) if selected in self.profile_ids else 0);self.choice.pack(side='left',fill='x',expand=True)
        self.port=ttk.Combobox(row,state='readonly',width=45);self.port.pack(side='left',padx=8);self.refresh_button=ttk.Button(row,text='刷新串口',command=self.refresh);self.refresh_button.pack(side='left')
        row=ttk.Frame(f);row.pack(fill='x',pady=10)
        self.prepare_button=ttk.Button(row,text='1 编译并烧录',command=self.prepare);self.prepare_button.pack(side='left')
        self.connect_button=ttk.Button(row,text='2 连接并只读诊断',command=self.connect);self.connect_button.pack(side='left',padx=8)
        self.verify_button=ttk.Button(row,text='3 停机写回验证（不使能）',command=self.verify,state='disabled');self.verify_button.pack(side='left')
        self.load_button=ttk.Button(row,text='查看已有诊断日志',command=self.load_log);self.load_button.pack(side='left',padx=8)
        self.stop_button=ttk.Button(row,text='停止诊断 / 请求停机',command=self.stop,state='disabled');self.stop_button.pack(side='right')
        ttk.Label(f,text='第3步会把刚读取的实测位置写回loc_ref，分3轮在不同延时回读。不修改模式、限流、增益、零位、ID或保存参数。',wraplength=1060,foreground='#52657c').pack(anchor='w')
        self.status=tk.StringVar(value='先编译烧录，再连接。默认只读取；写回验证需要停机确认、稳定UID和CSP模式5。');ttk.Label(f,textvariable=self.status,wraplength=1060,font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w',pady=8)
        self.identity=tk.StringVar(value='UID：未读取　固件版本：未读取');ttk.Label(f,textvariable=self.identity,wraplength=1060).pack(anchor='w')
        self.summary=tk.StringVar(value='等待真实回复；无回复的参数显示“未读取”，不代填0。');ttk.Label(f,textvariable=self.summary,wraplength=1060).pack(anchor='w',pady=5)
        self.tabs=ttk.Notebook(f);self.tabs.pack(fill='both',expand=True)
        values=ttk.Frame(self.tabs,padding=8);echo=ttk.Frame(self.tabs,padding=8);raw=ttk.Frame(self.tabs);self.tabs.add(values,text='参数实时值');self.tabs.add(echo,text='写回对照');self.tabs.add(raw,text='原始CAN日志')
        columns=('name','index','value','degree','status');self.table=ttk.Treeview(values,columns=columns,show='headings',height=10)
        for key,label,width in zip(columns,('项目','CAN索引','读回值','角度 / °','状态'),(250,100,200,140,180)):
            self.table.heading(key,text=label);self.table.column(key,width=width,anchor='w')
        self.table.pack(fill='both',expand=True)
        for i,(name,unit) in PARAMS.items():self.table.insert('', 'end',iid=str(i),values=(name,f'0x{i:04X}','未读取','—','等待回复'))
        ttk.Label(values,text='loc_ref和mechPos在停机时可能不同。判定写回异常，要看写入同一值后的回读结果。',wraplength=1000,foreground='#52657c').pack(anchor='w',pady=8)
        self.echo_table=ttk.Treeview(echo,columns=('round','delay','age','expected','read','error','status'),show='headings')
        for key,label in zip(self.echo_table['columns'],('轮次','设定延时/ms','实际间隔/ms','写入/rad','回读/rad','差值/°','结果')):self.echo_table.heading(key,text=label);self.echo_table.column(key,width=130,anchor='w')
        self.echo_table.pack(fill='both',expand=True)
        self.output=scrolledtext.ScrolledText(raw,font=('Consolas',10),wrap='word');self.output.pack(fill='both',expand=True)
        self.folder=tk.StringVar(value='日志将在连接时保存到本机。');ttk.Label(f,textvariable=self.folder,wraplength=1060).pack(anchor='w',pady=6)
        self.refresh();self.window.protocol('WM_DELETE_WINDOW',self.close);self._timer=self.window.after(100,self.poll)
    def profile(self):return self.profiles[self.choice.current()]
    def refresh(self):
        self.ports=list(comports());self.port['values']=[p.device+' · '+p.description for p in self.ports]
        candidates=[i for i,p in enumerate(self.ports) if p.vid==0x0483]
        if len(candidates)==1:self.port.current(candidates[0])
    def busy(self,value):
        for b in (self.prepare_button,self.connect_button,self.refresh_button,self.load_button):b.configure(state='disabled' if value else 'normal')
        self.choice.configure(state='disabled' if value else 'readonly');self.port.configure(state='disabled' if value else 'readonly')
    def launch(self,fn):
        if self.thread and self.thread.is_alive():return
        self.busy(True)
        def run():
            try:fn()
            except Exception as exc:self.events.put(('text','操作失败：'+str(exc)))
            finally:self.events.put(('finished',''))
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start()
    def prepare(self):
        ident=self.profile()['id'];self.tabs.select(2)
        def run():
            for kind in ('build','flash'):
                job=self.manager.start(kind,ident);after=0
                while True:
                    snap=job.snapshot(True,after)
                    for line in snap['lines']:self.events.put(('text',line['text']))
                    after=snap['sequence']
                    if job.status!='running':break
                    time.sleep(.1)
                if job.status!='pass':raise RuntimeError(str(job.result))
            self.events.put(('text','固件已烧录；点击“2 连接并只读诊断”。'))
        self.launch(run)
    def connect(self):
        if self.port.current()<0:return messagebox.showerror('串口未选择','请选择ST-LINK日志串口。',parent=self.window)
        port=self.ports[self.port.current()]
        if port.vid!=0x0483 or not port.serial_number:return messagebox.showerror('串口不匹配','需要可识别序列号的ST-LINK日志串口。',parent=self.window)
        self.finish.clear();self.session_ok=False;self.data=DiagnosticData();self.echo_table.delete(*self.echo_table.get_children());self.update_values();self.tabs.select(0)
        profile=self.profile();self.launch(lambda:self.worker(port,profile))
    def verify(self):
        if self.session_ok and self.data.can_verify():self.verify_button.configure(state='disabled');self.tabs.select(1);self.commands.put('VERIFY')
    def load_log(self,path=None):
        if self.thread and self.thread.is_alive():return
        if path is None:path=filedialog.askopenfilename(parent=self.window,title='选择停机位置诊断的board.log',initialdir=project_root()/'logs',filetypes=[('诊断日志','*.log *.txt'),('所有文件','*.*')])
        if not path:return
        try:
            text=Path(path).read_text(encoding='utf-8',errors='replace');start=text.rfind('# PICO_MOTOR_POSITION_DIAG=1;')
            if start<0:raise ValueError('文件中没有停机位置诊断固件标识。')
            text=text[start:]
        except Exception as exc:return messagebox.showerror('无法查看日志',str(exc),parent=self.window)
        self.session_ok=False;self.data=DiagnosticData();self.echo_table.delete(*self.echo_table.get_children());self.output.delete('1.0','end');self.tabs.select(0);self.folder.set('离线查看：'+str(Path(path).resolve()))
        for line in text.splitlines():self.events.put(('text',line))
        self.events.put(('offline',''))
    def stop(self):self.finish.set();self.verify_button.configure(state='disabled');self.status.set('正在停止诊断并请求停机。')
    def worker(self,port,profile):
        folder=project_root()/'logs'/('position-diag-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));folder.mkdir(parents=True);self.events.put(('folder',str(folder)))
        token=secrets.token_hex(4).upper();model=DiagnosticData();verified=ready=session=False;state={};result=None
        while not self.commands.empty():self.commands.get_nowait()
        (folder/'settings.json').write_text(json.dumps({'profile':profile,'port':port.device},ensure_ascii=False,indent=2),encoding='utf-8')
        with serial.Serial(port.device,115200,timeout=.02,write_timeout=.3) as dev,(folder/'board.log').open('wb') as raw,(folder/'commands.jsonl').open('w',encoding='utf-8') as commands:
            def write(text):
                b=(text+'\n').encode('ascii')
                if dev.write(b)!=len(b):raise RuntimeError('串口命令未完整写入。')
                commands.write(json.dumps({'time':datetime.now().isoformat(),'command':text})+'\n');commands.flush()
            try:
                dev.reset_input_buffer();r=subprocess.run(tools.reset_command(port.serial_number),env=tools.environment(),capture_output=True,timeout=15,**({'creationflags':subprocess.CREATE_NO_WINDOW} if tools.WINDOWS else {}));(folder/'reset.log').write_bytes(r.stdout+r.stderr)
                if r.returncode:raise RuntimeError('开发板复位失败。')
                buffer=bytearray();start=time.monotonic();handshake_due=keep_due=0.;closing=None
                while True:
                    now=time.monotonic();data=dev.read(dev.in_waiting or 1)
                    if data:raw.write(data);raw.flush();buffer.extend(data)
                    while b'\n' in buffer:
                        line,_,rest=buffer.partition(b'\n');buffer=bytearray(rest);text=line.decode('utf-8',errors='replace').strip();self.events.put(('text',text))
                        if text.startswith('# PICO_MOTOR_'):
                            validate_banner(text,profile);verified=True;ready=session=False;state={};result=None;token=secrets.token_hex(4).upper();start=now;handshake_due=keep_due=0.;self.events.put(('session',False))
                        model.feed(text)
                        if text.startswith('# DIAG_COMMAND_READY=1;') and verified:ready=True
                        if text==f"# SESSION_OK token={token} id={profile['cmake_options']['PICO_DIAG_MOTOR_ID']}":session=True;self.events.put(('session',True))
                        if text.startswith('# DIAG_STATE,'):state=fields(text)
                        if text.startswith(('# DIAG_ECHO_RESULT,','# DIAG_RESULT,')):result=fields(text)
                    if not verified and now-start>3:raise RuntimeError('未收到停机诊断固件标识，请先编译并烧录。')
                    if verified and not ready and now-start>3:raise RuntimeError('固件接收未就绪。')
                    if ready and not session and now>=handshake_due:write(f"SESSION {token} {profile['cmake_options']['PICO_DIAG_MOTOR_ID']}");handshake_due=now+.5
                    if ready and not session and now-start>5:raise RuntimeError('诊断会话未建立。')
                    if session and now>=keep_due:write('KEEP '+token);keep_due=now+.1
                    while not self.commands.empty():
                        command=self.commands.get_nowait()
                        if command=='VERIFY' and session and model.can_verify() and not self.finish.is_set():write('VERIFY '+token)
                    if self.finish.is_set():
                        if closing is None:write('STOP');closing=now
                        if (state.get('state')=='DONE' and state.get('stop_confirmed')=='1') or now-closing>1.5:break
            finally:
                try:write('STOP');dev.flush()
                except serial.SerialException:pass
                (folder/'result.json').write_text(json.dumps({'last_state':state,'result':result,'values':model.values,'uid':model.uid,'version':model.version,'echo':model.echo},ensure_ascii=False,indent=2),encoding='utf-8')
    def update_values(self):
        self.identity.set(f'UID：{self.data.uid}　固件版本：{self.data.version}')
        for index,(name,unit) in PARAMS.items():
            value=self.data.value(index);d=self.data.values.get(index,{})
            text='未读取' if value is None else (str(int(value)) if index in (0x7005,0x7029) else f'{value:.6f} {unit}')
            degree=f'{math.degrees(value):.6f}' if value is not None and unit=='rad' else '—'
            self.table.item(str(index),values=(name,f'0x{index:04X}',text,degree,d.get('status','等待回复')))
        target=self.data.value(0x7016);actual=self.data.value(0x7019)
        span=self.data.ranges.get(0x7019)
        range_text=f"；本次实测位置读值跨度{math.degrees(span[1]-span[0]):.6f}° / {span[2]}次" if span else ''
        if self.data.result:
            d=self.data.result
            if d.get('result')=='STOPPED' and not self.data.echo:self.summary.set(f"只读采集结束 · 停机确认{d.get('stop_confirmed')} · 未完成写回对照 · 未发送使能")
            else:self.summary.set(f"诊断结果：{d.get('result')} · 停机确认{d.get('stop_confirmed')} · 目标写回确认{d.get('target_cleared')} · 未发送使能")
        elif target is not None and actual is not None:self.summary.set(f'位置目标 − 实际位置：{math.degrees(target-actual):+.6f}°（只作对照，不能单凭该差值判故障）')
        else:self.summary.set('等待目标和实际位置的有效回复；无回复项不代填0。')
        self.summary.set(self.summary.get()+range_text)
    def poll(self):
        self._timer=None
        if self.closed:return
        for _ in range(200):
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='text':
                self.output.insert('end',value+'\n');self.output.see('end');self.data.feed(value);self.update_values()
                if value.startswith('# DIAG_STATE,'):
                    s=self.data.state;self.status.set(f"{s.get('state','')} · {s.get('reason','')} · 停机确认{s.get('stop_confirmed','0')} · UID一致{s.get('uid_stable','0')} · TEC/REC {s.get('tec','—')}/{s.get('rec','—')}")
                    if s.get('stop_confirmed')=='0' and s.get('state') in ('STOPPING','DONE'):self.status.set('停机未确认，需使用实物断电措施处理。')
                    if s.get('state')=='MONITOR' and self.data.value(0x7005)!=5:self.status.set(self.status.get()+' · 当前不是CSP模式5，只读取，未修改模式。')
                    self.verify_button.configure(state='normal' if self.session_ok and self.data.can_verify() and not self.finish.is_set() else 'disabled')
                if value.startswith('# DIAG_ECHO,'):
                    d=fields(value);self.echo_table.insert('', 'end',values=(d['round'],d['nominal_ms'],d['age_ms'],f"{int(d['expected_urad'])/1e6:.6f}",f"{int(d['read_urad'])/1e6:.6f}",f"{math.degrees(int(d['error_urad'])/1e6):+.6f}",d['status']))
                if value.startswith(('# DIAG_ECHO_RESULT,','# DIAG_RESULT,')):
                    self.verify_button.configure(state='disabled')
                if value.startswith(('操作失败：','# DIAG_REJECTED')):self.status.set(value)
            elif kind=='session':self.session_ok=value;self.stop_button.configure(state='normal' if value else 'disabled')
            elif kind=='folder':self.folder.set(value)
            elif kind=='offline':self.status.set('离线日志 · '+self.status.get());self.verify_button.configure(state='disabled');self.stop_button.configure(state='disabled')
            elif kind=='finished':
                self.session_ok=False;self.busy(False);self.verify_button.configure(state='disabled');self.stop_button.configure(state='disabled')
                if self.closing:self.destroy();return
        self._timer=self.window.after(100,self.poll)
    def close(self):
        if self.thread and self.thread.is_alive():
            if any(j.kind=='flash' and j.status=='running' for j in self.manager.jobs.values()):messagebox.showinfo('正在烧录','请等待写入校验完成。',parent=self.window);return
            self.closing=True;self.stop()
        else:self.destroy()
    def destroy(self):
        self.closed=True
        if self._timer:self.window.after_cancel(self._timer);self._timer=None
        try:self.window.grab_release()
        except tk.TclError:pass
        self.window.destroy()
