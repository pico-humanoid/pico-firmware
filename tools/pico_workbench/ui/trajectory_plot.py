"""Dependency-free Tk position waveform; consumes the same immutable board log."""
from collections import defaultdict,deque
import csv
import math
from pathlib import Path
import re
import struct
import tkinter as tk
from tkinter import filedialog,ttk

FRAME=re.compile(r'^(\d+),(RX|TX_SUBMIT),FDCAN\d+,EXT,DATA,0x([0-9a-fA-F]+),8,([0-9a-fA-F ]+)$')
COLORS={1:('#0d9488','#6ccfc3'),2:('#e58026','#edb77b')}

class TrajectoryData:
    def __init__(self):self.reset()
    def reset(self):
        self.origin={};self.points=defaultdict(lambda:deque(maxlen=3600));self.events=deque(maxlen=60);self.last_t=0;self.last_reason={}
    def feed(self,line):
        if line.startswith('# PICO_MOTOR_'):self.reset();return True
        if line.startswith(('# SYNC_POSITION_ORIGIN,','# SYNC_POSITION_SAMPLE,')):
            try:
                fields=dict(v.split('=',1) for v in line.strip().split(',')[1:] if '=' in v)
                motor=int(fields['id'])
                if motor not in (1,2):return False
                if line.startswith('# SYNC_POSITION_ORIGIN,'):
                    origin=int(fields['position_urad'])/1000000
                    if not math.isfinite(origin) or abs(origin)>1000:return False
                    self.origin[motor]=origin
                    for key in list(self.points):
                        if key[0]==motor:del self.points[key]
                else:
                    stamp=int(fields['t_ms']);ref=int(fields['reference_urad'])/1000000;error=int(fields['error_urad'])/1000000
                    if stamp<0 or not all(math.isfinite(v) and abs(v)<=1000 for v in (ref,error)):return False
                    self.points[motor,'reference'].append((stamp,math.degrees(ref)))
                    self.points[motor,'error'].append((stamp,math.degrees(error)));self.last_t=max(self.last_t,stamp)
                return True
            except (ValueError,KeyError,OverflowError):return False
        match=FRAME.match(line.strip())
        if match:
            stamp,event,ident,hexdata=match.groups();stamp=int(stamp);ident=int(ident,16)
            try:data=bytes.fromhex(hexdata)
            except ValueError:return False
            if len(data)!=8:return False
            self.last_t=max(self.last_t,stamp)
            index=int.from_bytes(data[:2],'little');value=struct.unpack('<f',data[4:])[0]
            if not math.isfinite(value) or abs(value)>1000:return False
            kind=None
            if event=='RX' and (ident>>24)&31==17 and index==0x7019 and ident&255==253:
                motor=(ident>>8)&255;kind='actual'
            elif event=='TX_SUBMIT' and (ident>>24)&31==18 and index==0x7016:
                motor=ident&255;kind='target'
            if kind and motor in (1,2):
                self.origin.setdefault(motor,value)
                self.points[motor,kind].append((stamp,math.degrees(value-self.origin[motor])))
                self.last_t=max(self.last_t,stamp);return True
        if line.startswith('# ') and ('_PHASE,' in line or '_STATE,' in line):
            fields=dict(v.split('=',1) for v in line.split(',')[1:] if '=' in v)
            ident=fields.get('id');reason=fields.get('reason','');state=fields.get('state','')
            if ident in ('1','2') and (fields.get('error')=='1' or state in ('STOPPING','DONE')):
                if reason not in ('BOOT_STOP','PREPARING_POSITION') and self.last_reason.get(ident)!=reason:
                    self.events.append((self.last_t,f'ID{ident} {reason}'));self.last_reason[ident]=reason;return True
        return False
    def rows(self):
        return sorted((t,m,k,v) for (m,k),points in self.points.items() for t,v in points)
    def save(self,path):
        with Path(path).open('w',newline='',encoding='utf-8-sig') as stream:
            out=csv.writer(stream);out.writerow(('board_t_ms','motor_id','series','angle_deg'));out.writerows(self.rows())

class TrajectoryPlot(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent,padding=8);self.data=TrajectoryData();self.frozen=False;self.dirty=True;self.folder=None;self._timer=None
        bar=ttk.Frame(self);bar.pack(fill='x',pady=(0,8))
        ttk.Label(bar,text='实时位置轨迹',font=('Microsoft YaHei UI',12,'bold')).pack(side='left')
        self.window=ttk.Combobox(bar,state='readonly',values=('最近20秒','最近60秒','全部轨迹'),width=12);self.window.current(0);self.window.pack(side='left',padx=12);self.window.bind('<<ComboboxSelected>>',lambda _:self.invalidate())
        self.view=ttk.Combobox(bar,state='readonly',values=('位置轨迹','跟踪误差'),width=11);self.view.current(0);self.view.pack(side='left');self.view.bind('<<ComboboxSelected>>',lambda _:self.invalidate())
        self.pause=ttk.Button(bar,text='暂停显示',command=self.toggle);self.pause.pack(side='right',padx=(8,0))
        ttk.Button(bar,text='导出曲线CSV',command=self.export).pack(side='right')
        self.canvas=tk.Canvas(self,background='#ffffff',highlightthickness=1,highlightbackground='#dce5ef',height=285)
        self.canvas.bind('<Configure>',lambda _:self.invalidate())
        footer=ttk.Frame(self);footer.pack(side='bottom',fill='x',pady=(6,0))
        self.legend=ttk.Label(footer,text='青色：10P ID1　橙色：00 ID2　实线：实测位置　虚线：目标（已提交）　角度均相对本次起点',foreground='#52657c');self.legend.pack(anchor='w',pady=(0,2))
        ttk.Label(footer,text='暂停显示只冻结画面，串口接收和电机控制仍继续。未收到位置报文时不绘制模拟轨迹。',foreground='#7b899b').pack(anchor='w')
        self.canvas.pack(fill='both',expand=True)
        self.bind('<Destroy>',self.on_destroy);self.tick()
    def invalidate(self):self.dirty=True
    def feed(self,line):
        if self.data.feed(line):self.dirty=True
    def toggle(self):
        self.frozen=not self.frozen;self.pause.configure(text='继续显示' if self.frozen else '暂停显示');self.dirty=True
    def tick(self):
        if self.dirty and not self.frozen:self.draw();self.dirty=False
        self._timer=self.after(120,self.tick)
    def on_destroy(self,event):
        if event.widget is self and self._timer:
            self.after_cancel(self._timer);self._timer=None
    def export(self):
        path=filedialog.asksaveasfilename(parent=self.winfo_toplevel(),title='导出当前接收的位置曲线',initialdir=str(self.folder) if self.folder else None,initialfile='trajectory.csv',defaultextension='.csv',filetypes=[('CSV','*.csv')])
        if path:self.data.save(path)
    def draw(self):
        c=self.canvas;c.delete('all');w=c.winfo_width();h=c.winfo_height()
        if w<200 or h<120:return
        left,top,right,bottom=64,28,w-24,h-42
        end=max(self.data.last_t,1000);span=(20000,60000,end)[self.window.current()];start=max(0,end-span);end=max(end,start+1000)
        error_view=self.view.current()==1
        allowed=('error',) if error_view else ('target','actual')
        visible=[v for (_,kind),points in self.data.points.items() if kind in allowed for t,v in points if start<=t<=end]
        extent=max([0.2 if error_view else 6.0]+[abs(v)*1.15 for v in visible]);extent=math.ceil(extent*10)/10 if error_view else math.ceil(extent)
        self.legend.configure(text='青色：10P ID1　橙色：00 ID2　误差＝实际位置－采样时刻的参考轨迹；基于MCU接收时间估算' if error_view else '青色：10P ID1　橙色：00 ID2　实线：实测位置　虚线：目标（已提交）　角度均相对本次起点')
        def x(t):return left+(t-start)/(end-start)*(right-left)
        def y(v):return top+(extent-v)/(2*extent)*(bottom-top)
        for i in range(5):
            value=extent-i*extent/2;py=y(value)
            c.create_line(left,py,right,py,fill='#e8eef5' if i!=2 else '#c6d5e4')
            c.create_text(left-10,py,text=f'{value:g}°',anchor='e',fill='#6d7f94',font=('Segoe UI',9))
        for i in range(6):
            stamp=start+(end-start)*i/5;px=x(stamp);c.create_line(px,top,px,bottom,fill='#f0f4f8')
            c.create_text(px,bottom+18,text=f'{stamp/1000:.1f}s',fill='#6d7f94',font=('Segoe UI',9))
        for (motor,kind),samples in sorted(self.data.points.items(),key=lambda item:item[0][1]=='actual'):
            if kind not in allowed:continue
            points=sorted(samples);inside=[(t,v) for t,v in points if start<=t<=end]
            prior=[p for p in points if p[0]<start]
            if prior:inside.insert(0,(start,prior[-1][1]))
            if not inside:continue
            coords=[]
            if kind=='target':
                for i,(t,v) in enumerate(inside):
                    if i:coords.extend((x(t),y(inside[i-1][1])))
                    coords.extend((x(t),y(v)))
                coords.extend((x(end),y(inside[-1][1])))
            else:
                for t,v in inside:coords.extend((x(t),y(v)))
            color=COLORS[motor][0 if kind in ('actual','error') else 1]
            if len(coords)>=4:c.create_line(*coords,fill=color,width=2.5 if kind in ('actual','error') else 1.8,dash=(6,4) if kind=='target' else ())
            elif coords:c.create_oval(coords[0]-2,coords[1]-2,coords[0]+2,coords[1]+2,fill=color,outline=color)
        for i,(stamp,label) in enumerate(e for e in self.data.events if start<=e[0]<=end):
            px=x(stamp);c.create_line(px,top,px,bottom,fill='#d95656',dash=(2,4))
            near_edge=px>right-190
            c.create_text(px-4 if near_edge else px+4,top+12+(i%3)*15,text=label,anchor='e' if near_edge else 'w',fill='#ad3a3a',font=('Segoe UI',8))
        c.create_text(left,12,text='跟踪误差 / °' if error_view else '相对位置 / °',anchor='w',fill='#52657c',font=('Microsoft YaHei UI',9))
        if not visible:c.create_text((left+right)/2,(top+bottom)/2,text='等待共同时间轴实验的误差采样…' if error_view else '等待电机位置数据…\n连接并开始实验后显示真实目标与反馈',fill='#8798ac',font=('Microsoft YaHei UI',12),justify='center')
