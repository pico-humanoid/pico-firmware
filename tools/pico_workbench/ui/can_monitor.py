"""Native RobStride USB-CAN monitor: reads serial only; never writes commands."""
import csv
from datetime import datetime,timezone
import json
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk,messagebox
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'vendor'))
import serial
from serial.tools.list_ports import comports
from can_monitor_model import ATDecoder,describe
from runtime_paths import project_root
from experiment_log import capture_notes, show_legend

class CANMonitor:
    def __init__(self,parent=None):
        self.window=tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title('CAN3 总线监控 · 灵足官方 USB-CAN / AT')
        self.window.geometry('1180x720');self.window.minsize(880,560)
        self.events=queue.Queue(maxsize=5000);self.stop_event=threading.Event();self.thread=None
        self.closed=False;self.count=0;self.rows=0;self.request=0;self.reply=0;self.identity=0
        frame=ttk.Frame(self.window,padding=15);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='CAN3 总线旁路监控',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
        ttk.Label(frame,text='先确认适配器 CAN=1M、AT 模式，并关闭占用它的官方上位机。串口波特率与 CAN 速率不同。').pack(anchor='w',pady=(6,3))
        ttk.Label(frame,text='本程序不发送串口数据或 CAN 请求；适配器是否自动 ACK 由其硬件工作模式决定。只解析经典扩展数据帧，其他字节另存原始日志。',wraplength=1100).pack(anchor='w')
        row=ttk.Frame(frame);row.pack(fill='x',pady=12)
        ttk.Label(row,text='USB-CAN 串口').pack(side='left')
        self.port=ttk.Combobox(row,state='readonly',width=43);self.port.pack(side='left',padx=6)
        ttk.Button(row,text='刷新',command=self.refresh).pack(side='left')
        ttk.Label(row,text='串口波特率').pack(side='left',padx=(16,4))
        self.baud=ttk.Combobox(row,values=['921600','115200','2000000'],width=10);self.baud.set('921600');self.baud.pack(side='left')
        self.start_button=ttk.Button(row,text='开始监听',command=self.start);self.start_button.pack(side='left',padx=10)
        ttk.Button(row,text='停止',command=self.stop).pack(side='left')
        self.status=tk.StringVar(value='未连接。仅支持灵足官方 AT 协议适配器；不选择 ST-LINK 串口。')
        ttk.Label(frame,textvariable=self.status,wraplength=1100).pack(anchor='w',pady=(0,8))
        self.summary=tk.StringVar(value='接收 0 帧');ttk.Label(frame,textvariable=self.summary).pack(anchor='w')
        columns=('time','origin','id','dlc','data','meaning')
        area=ttk.Frame(frame);area.pack(fill='both',expand=True,pady=8)
        self.table=ttk.Treeview(area,columns=columns,show='headings')
        for key,label,width in [('time','电脑接收时间',135),('origin','方向推断',225),('id','CAN ID',115),('dlc','DLC',40),('data','原始数据 HEX',220),('meaning','协议解释',280)]:
            self.table.heading(key,text=label);self.table.column(key,width=width,minwidth=40)
        sy=ttk.Scrollbar(area,orient='vertical',command=self.table.yview);sx=ttk.Scrollbar(area,orient='horizontal',command=self.table.xview)
        self.table.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.table.grid(row=0,column=0,sticky='nsew');sy.grid(row=0,column=1,sticky='ns');sx.grid(row=1,column=0,sticky='ew')
        area.rowconfigure(0,weight=1);area.columnconfigure(0,weight=1)
        self.follow=tk.BooleanVar(value=True);ttk.Checkbutton(frame,text='跟随最新报文（列表保留最近2000帧，文件保存全部帧）',variable=self.follow).pack(anchor='w')
        ttk.Label(frame,text='请求预期：0x1100FD7F；回复预期：0x11007FFD。方向按ID字段推断，CAN帧本身不携带物理发送节点标识。',wraplength=1100).pack(anchor='w',pady=6)
        self.refresh();self.window.protocol('WM_DELETE_WINDOW',self.close)
        ttk.Button(frame,text='日志说明',command=lambda:show_legend(self.window)).pack(anchor='e')
        self.window.after(100,self.poll)
    def refresh(self):
        self.port_items=list(comports())
        self.port['values']=[p.device+' · '+p.description for p in self.port_items]
        candidates=[i for i,p in enumerate(self.port_items) if p.vid==0x1A86]
        if len(candidates)==1:self.port.current(candidates[0])
    def start(self):
        if self.thread and self.thread.is_alive():return
        try:
            i=self.port.current()
            if i<0:raise ValueError('请选择 USB-CAN 串口。')
            p=self.port_items[i]
            if p.vid==0x0483:raise ValueError('这是 ST-LINK 串口；请选择 USB-CAN 适配器串口。')
            baud=int(self.baud.get())
            if baud not in (9600,19200,38400,57600,115200,230400,460800,921600,1000000,2000000):raise ValueError('请核对适配器的串口波特率。')
        except ValueError as exc:messagebox.showerror('无法开始',str(exc),parent=self.window);return
        self.stop_event.clear();self.start_button.configure(state='disabled')
        self.count=self.request=self.reply=self.identity=0
        self.thread=threading.Thread(target=self.read,args=(p.device,baud),daemon=True);self.thread.start()
    def read(self,port,baud):
        try:
            folder=project_root()/'logs'/('can3-monitor-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            folder.mkdir(parents=True,exist_ok=True)
            decoder=ATDecoder();total=0;started=time.monotonic();last=started
            device=serial.Serial(port=None,baudrate=baud,timeout=.2)
            device.dtr=False;device.rts=False;device.port=port
            device.open()
            with capture_notes(folder, lambda text: self.events.put_nowait(('status',text))
                               if not self.events.full() else None, 'CAN 旁路监听', final={'capture_only':True}), \
                 device, (folder/'frames.csv').open('w',encoding='utf-8-sig',newline='') as output, (folder/'raw.jsonl').open('w',encoding='utf-8') as raw:
                writer=csv.writer(output);writer.writerow(['pc_utc','elapsed_ms','origin_inferred','format','id','dlc','data','meaning'])
                self.events.put(('status','已打开 '+port+'，串口 '+str(baud)+'；只读监听。日志：'+str(folder)))
                skipped=0
                while not self.stop_event.is_set():
                    data=device.read(min(65536,max(device.in_waiting,1)))
                    now=time.monotonic()
                    if data:
                        utc=datetime.now(timezone.utc);total+=len(data)
                        raw.write(json.dumps({'pc_utc':utc.isoformat(),'serial_hex':data.hex(' ')})+'\n')
                        for identifier,payload in decoder.feed(data):
                            origin,meaning=describe(identifier,payload)
                            row=(utc.strftime('%H:%M:%S.%f')[:-3],origin,'0x%08X'%identifier,len(payload),payload.hex(' ').upper(),meaning)
                            writer.writerow([utc.isoformat(),round((now-started)*1000,3),origin,'EXT',row[2],row[3],row[4],meaning])
                            try:self.events.put_nowait(('frame',row))
                            except queue.Full:skipped+=1
                    if now-last>=1:
                        output.flush();raw.flush();last=now
                        note=f'{port}：收到 {total} 串口字节；无法识别字节 {decoder.discarded}；非扩展数据帧 {decoder.unsupported}；界面略过 {skipped} 帧（完整记录仍写入文件）。日志：{folder}'
                        try:self.events.put_nowait(('status',note))
                        except queue.Full:pass
        except Exception as exc:
            try:self.events.put(('status','监听失败：'+str(exc)),timeout=.5)
            except queue.Full:pass
        finally:
            try:self.events.put(('ended',None),timeout=.5)
            except queue.Full:pass
    def stop(self):self.stop_event.set()
    def poll(self):
        if self.closed:return
        for _ in range(500):
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='status':self.status.set(value)
            elif kind=='ended':self.start_button.configure(state='normal')
            elif kind=='frame':
                self.count+=1
                if value[2]=='0x1100FD7F':self.request+=1
                if value[2]=='0x11007FFD':self.reply+=1
                if value[2]=='0x00007FFE':self.identity+=1
                self.table.insert('','end',values=value)
                children=self.table.get_children()
                if len(children)>2000:self.table.delete(*children[:len(children)-2000])
                if self.follow.get():self.table.yview_moveto(1)
                self.summary.set(f'接收 {self.count} 帧；主机FD参数请求 {self.request}；电机7F参数回复 {self.reply}；电机7F身份报文 {self.identity}')
        self.window.after(100,self.poll)
    def close(self):
        self.stop_event.set();self.closed=True;self.window.destroy()

if __name__=='__main__':
    app=CANMonitor();app.window.mainloop()
