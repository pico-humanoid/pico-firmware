"""Actual tuning samples only; angle in degrees, current in amperes."""
import csv
from collections import deque
from tkinter import ttk, filedialog
import tkinter as tk

COLUMNS=('motor_id','board_t_ms','mode','accepted_seq','applied_seq','requested_angle_deg','applied_angle_deg','actual_angle_deg','error_deg','iq_A','requested_iq_A','iq_target_A','current_limit_A','velocity_rad_s','requested_velocity_rad_s','target_velocity_rad_s','speed_limit_rad_s')
def fields(line):
    return dict(x.split('=',1) for x in line.strip().split(',')[1:] if '=' in x)

class ScopeData:
    def __init__(self):self.rows=deque(maxlen=12000)
    def feed(self,line):
        if line.startswith('# PICO_MOTOR_TUNING=1;') or line.startswith('# TUNE_ORIGIN,'):
            self.rows.clear();return False
        if not line.startswith('# TUNE_SAMPLE,'):return False
        d=fields(line)
        try:
            row={'motor_id':int(d['id']) if 'id' in d else None,'board_t_ms':int(d['t_ms']),'mode':d['mode'],'accepted_seq':int(d['accepted_seq']),'applied_seq':int(d['applied_seq'])}
            for key,source in [('requested_angle_deg','command_angle_mdeg'),('applied_angle_deg','target_angle_mdeg'),('actual_angle_deg','actual_angle_mdeg'),('error_deg','error_mdeg'),('iq_A','iq_mA'),('requested_iq_A','command_iq_mA'),('iq_target_A','iq_target_mA'),('current_limit_A','limit_mA'),('velocity_rad_s','velocity_mrad_s'),('requested_velocity_rad_s','command_velocity_mrad_s'),('target_velocity_rad_s','target_velocity_mrad_s'),('speed_limit_rad_s','speed_limit_mrad_s')]:
                raw=d.get(source,'NA');row[key]=None if raw=='NA' else int(raw)/1000
            if row['mode'] not in ('POS','IQ','SPD'):return False
        except (ValueError,KeyError):return False
        if self.rows and row['board_t_ms']<=self.rows[-1]['board_t_ms']:return False
        row['negative_speed_limit_rad_s']=-row['speed_limit_rad_s'] if row['speed_limit_rad_s'] is not None else None
        self.rows.append(row);return True
    def export(self,path):
        with open(path,'w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=COLUMNS,extrasaction='ignore');w.writeheader();w.writerows(self.rows)

class TuningScope(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent);self.data=ScopeData();self.paused=False;self._draw_timer=None;self.dirty=False
        bar=ttk.Frame(self);bar.pack(fill='x',pady=5)
        self.pause=ttk.Button(bar,text='冻结显示',command=self.freeze);self.pause.pack(side='left')
        ttk.Button(bar,text='导出波形 CSV',command=self.export).pack(side='left',padx=8)
        self.error=tk.BooleanVar(value=False);ttk.Checkbutton(bar,text='角度面板显示跟踪误差',variable=self.error,command=self.request_draw).pack(side='left')
        ttk.Label(bar,text='最近20秒 · 冻结显示不影响心跳或电机控制').pack(side='right')
        self.canvas=tk.Canvas(self,bg='#101d30',highlightthickness=0,height=380);self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda _:self.request_draw());self.canvas.bind('<Map>',lambda _:self.request_draw());self.bind('<Destroy>',self.on_destroy);self.latest=ttk.Label(self,text='等待真实采样；无反馈时不生成波形。',wraplength=980);self.latest.pack(fill='x',pady=5)
    def feed(self,line):
        changed=self.data.feed(line)
        if changed or line.startswith(('# PICO_MOTOR_TUNING=1;','# TUNE_ORIGIN,')):self.request_draw()
    def freeze(self):
        self.paused=not self.paused;self.pause.configure(text='恢复显示' if self.paused else '冻结显示')
        if not self.paused:self.request_draw()
    def request_draw(self):
        # Ingestion never renders. A burst schedules one frame, leaving the
        # event loop available for buttons; hidden plots do no drawing work.
        self.dirty=True
        if not self.paused and self._draw_timer is None:
            self._draw_timer=self.after(100,self.flush_draw)
    def flush_draw(self):
        self._draw_timer=None
        if self.dirty and not self.paused and self.canvas.winfo_ismapped():
            self.dirty=False;self.draw()
    def on_destroy(self,event):
        if event.widget is self and self._draw_timer is not None:
            self.after_cancel(self._draw_timer);self._draw_timer=None
    def export(self):
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.csv',filetypes=[('CSV','*.csv')])
        if path:self.data.export(path)
    def draw(self):
        if self.paused:return
        c=self.canvas;c.delete('all');w=max(c.winfo_width(),500);h=max(c.winfo_height(),300)
        rows=list(self.data.rows)
        if not rows:c.create_text(w/2,h/2,text='等待真实采样',fill='#90a8c4');return
        end=rows[-1]['board_t_ms'];start=max(rows[0]['board_t_ms'],end-20000);rows=[r for r in rows if r['board_t_ms']>=start]
        mode=rows[-1]['mode']
        angle=[('error_deg','误差','#fb7185')] if self.error.get() else [('requested_angle_deg','提交角度','#94a3b8'),('applied_angle_deg','回读目标','#fbbf24'),('actual_angle_deg','实际角度','#38bdf8')]
        if mode in ('IQ','SPD'):angle=[('actual_angle_deg','实际位移','#38bdf8')]
        if mode=='IQ':
            second=[('requested_iq_A','提交 Iq','#94a3b8'),('iq_A','实际 Iq','#34d399'),('iq_target_A','回读 Iq 目标','#fbbf24')];unit='电流 / A'
        elif mode=='SPD':
            second=[('requested_velocity_rad_s','提交速度','#94a3b8'),('target_velocity_rad_s','回读目标速度','#fbbf24'),('velocity_rad_s','实际速度','#34d399')];unit='速度 / rad/s'
        else:
            second=[('speed_limit_rad_s','正限速','#fbbf24'),('negative_speed_limit_rad_s','负限速','#a78bfa'),('velocity_rad_s','实际速度','#34d399')];unit='速度 / rad/s'
        for panel,(series,title) in enumerate([(angle,'角度 / °'),(second,unit)]):
            left,right,top,bottom=65,w-20,30+panel*h/2,(panel+1)*h/2-28
            vals=[r[key] for r in rows for key,_,_ in series if r[key] is not None];lo=min(vals+[0]);hi=max(vals+[0]);pad=max((hi-lo)*.15,.03 if panel else .3);lo-=pad;hi+=pad
            c.create_text(left,top-15,text=title,fill='#c4d6ec',anchor='w')
            for i in range(5):
                y=top+(bottom-top)*i/4;v=hi-(hi-lo)*i/4
                c.create_line(left,y,right,y,fill='#27384f');c.create_text(left-7,y,text=f'{v:.2f}',fill='#90a8c4',anchor='e')
            for si,(key,label,color) in enumerate(series):
                c.create_text(right-si*145,top-15,text=label,fill=color,anchor='e');points=[]
                for r in rows:
                    if r[key] is not None:points.extend((left+(right-left)*(r['board_t_ms']-start)/max(1,end-start),bottom-(bottom-top)*(r[key]-lo)/(hi-lo)))
                if len(points)>=4:c.create_line(*points,fill=color,width=2)
            c.create_text(left,bottom+13,text=f'{start/1000:.1f}s',fill='#90a8c4',anchor='w');c.create_text(right,bottom+13,text=f'{end/1000:.1f}s',fill='#90a8c4',anchor='e')
        r=rows[-1];self.latest.configure(text=f"{mode} · 提交 #{r['accepted_seq']} / 回读 #{r['applied_seq']} · 实际 {r['actual_angle_deg']:.3f}° · Iq {r['iq_A']:.3f}A · 速度 {r['velocity_rad_s']:.3f}rad/s")
