"""Single native app to prepare firmware and test PC <-> CAN3 via official AT adapter."""
from datetime import datetime
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk,scrolledtext,messagebox
from contextlib import ExitStack

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE/'vendor')]
import serial
from serial.tools.list_ports import comports
from engine import Manager
import platform_tools as tools
from can_monitor_model import ATDecoder
from can_pc_test_model import request,assess,multi_request,assess_multi,channel_ids,multi_health
from runtime_paths import project_root

PROFILE='CAN3-PC-Test-1M'
class PCTest:
    def __init__(self,parent=None,multi=False):
        self.multi=multi;self.profile='CAN123-PC-Test-1M' if multi else PROFILE
        self.window=tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title('电脑 ↔ 开发板 CAN1/2/3 三路诊断（灵足 USB-CAN）' if multi else '电脑 ↔ 开发板 CAN3 双向测试（灵足 USB-CAN）')
        self.window.geometry('1020x900' if multi else '980x720');self.stop_event=threading.Event();self.events=queue.Queue();self.thread=None;self.closed=False
        self.manager=Manager();frame=ttk.Frame(self.window,padding=18);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='NUCLEO CAN1 / CAN2 / CAN3 三路诊断' if multi else '电脑 ↔ NUCLEO CAN3 双向测试',font=('Microsoft YaHei UI',19,'bold')).pack(anchor='w')
        ttk.Label(frame,text=('三路同时启用；一个收发模块可断电后分别移接TXD/RXD。测试时断开电机及底板CAN连接。' if multi else '专用台架：电脑→灵足USB-CAN→独立收发器→PA15/PA8。测试时断开电机及底板CAN连接。'),wraplength=960).pack(anchor='w',pady=6)
        ttk.Label(frame,text=('CAN=1M、扩展帧；选择当前接线通道，每路独立100帧请求/回复、独立验收。未接通道显示WAIT。' if multi else 'CAN=1M、扩展帧；PC发0x321，开发板回0x123；100帧，每100ms。串口与板端日志共同验证。'),wraplength=960).pack(anchor='w')
        if multi:
            self.channel=ttk.Combobox(frame,state='readonly',values=[
                'CAN1：TX=PA12 / CN10-12，RX=PA11 / CN10-14',
                'CAN2：TX=PB13 / CN10-30，RX=PB12 / CN10-16',
                'CAN3：TX=PA15 / CN7-17，RX=PA8 / CN10-23'])
            self.channel.pack(fill='x',pady=6);self.channel.current(0)
            cols=('channel','state','rx_unique','tx_done','rx_edge_observations','lec','tec','rec')
            self.health_table=ttk.Treeview(frame,columns=cols,show='headings',height=3)
            for key,label in zip(cols,('通道','状态','收到有效帧','发送完成','边沿观测','LEC','TEC','REC')):
                self.health_table.heading(key,text=label);self.health_table.column(key,width=100,anchor='center')
            for i in range(1,4):self.health_table.insert('','end',iid='CAN'+str(i),values=('CAN'+str(i),'尚未采集','—','—','—','—','—','—'))
            self.health_table.pack(fill='x',pady=5)
        self.combos={}
        for key,label in [('adapter','灵足 USB-CAN 串口'),('board','ST-LINK 日志串口')]:
            row=ttk.Frame(frame);row.pack(fill='x',pady=5)
            ttk.Label(row,text=label,width=23).pack(side='left')
            combo=ttk.Combobox(row,state='readonly');combo.pack(side='left',fill='x',expand=True);self.combos[key]=combo
        row=ttk.Frame(frame);row.pack(fill='x',pady=5)
        ttk.Button(row,text='刷新串口',command=self.refresh).pack(side='left')
        ttk.Label(row,text='USB-CAN串口波特率').pack(side='left',padx=12)
        self.baud=ttk.Combobox(row,values=['921600','115200','2000000'],width=12);self.baud.set('921600');self.baud.pack(side='left')
        row=ttk.Frame(frame);row.pack(fill='x',pady=12)
        self.prepare_button=ttk.Button(row,text='1 编译并烧录专用固件',command=lambda:self.launch(self.prepare));self.prepare_button.pack(side='left')
        self.test_button=ttk.Button(row,text='2 开始双向100帧测试',command=self.start_test);self.test_button.pack(side='left',padx=12)
        ttk.Button(row,text='停止测试',command=self.stop_event.set).pack(side='left')
        self.status=tk.StringVar(value='未测试。关闭占用这两个串口的官方软件、旁路监控和板端采集后再开始。')
        ttk.Label(frame,textvariable=self.status,wraplength=920).pack(anchor='w',pady=5)
        self.output=scrolledtext.ScrolledText(frame,font=('Consolas',10),wrap='word');self.output.pack(fill='both',expand=True)
        self.output.insert('end','本测试程序会主动发送专用测试帧，不能作为只读旁路监听使用。\n适配器CAN速率需事先设为1M。不会修改电机参数；但本测试不应连接电机。\n')
        self.refresh();self.window.protocol('WM_DELETE_WINDOW',self.close);self.window.after(100,self.poll)
    def refresh(self):
        self.ports=list(comports())
        for key,combo in self.combos.items():
            combo['values']=[p.device+' · '+p.description for p in self.ports]
            wanted=0x0483 if key=='board' else 0x1A86
            matches=[i for i,p in enumerate(self.ports) if p.vid==wanted]
            if len(matches)==1:combo.current(matches[0])
    def launch(self,operation):
        if self.thread and self.thread.is_alive():return
        self.stop_event.clear();self.prepare_button.configure(state='disabled');self.test_button.configure(state='disabled')
        if self.multi:self.channel.configure(state='disabled')
        def worker():
            try:operation()
            except Exception as exc:self.events.put(('text','操作停止：'+str(exc)))
            finally:self.events.put(('done',''))
        self.thread=threading.Thread(target=worker,daemon=True);self.thread.start()
    def prepare(self):
        for kind in ['build','flash']:
            job=self.manager.start(kind,self.profile);after=0
            while job.status=='running':
                snap=job.snapshot(True,after)
                for line in snap['lines']:self.events.put(('text',line['text']))
                after=snap['sequence'];time.sleep(.1)
            snap=job.snapshot(True,after)
            for line in snap['lines']:self.events.put(('text',line['text']))
            if job.status!='pass':raise RuntimeError(str(job.result))
        self.events.put(('text','专用固件已烧录。接线就绪后点击“开始双向100帧测试”。'))
    def start_test(self):
        try:
            chosen={k:self.ports[c.current()] if c.current()>=0 else None for k,c in self.combos.items()}
            if not all(chosen.values()):raise ValueError('请选择两个串口。')
            if chosen['adapter'].device==chosen['board'].device:raise ValueError('两个串口不能相同。')
            if chosen['board'].vid!=0x0483:raise ValueError('板端串口必须是ST-LINK。')
            if chosen['adapter'].vid==0x0483:raise ValueError('USB-CAN串口不能选ST-LINK。')
            baud=int(self.baud.get())
            if baud not in (115200,921600,2000000):raise ValueError('请核对USB-CAN串口波特率。')
        except ValueError as exc:messagebox.showerror('无法开始',str(exc),parent=self.window);return
        channel=self.channel.current()+1 if self.multi else 3
        self.launch(lambda:self.test(chosen['adapter'].device,chosen['board'].device,chosen['board'].serial_number,baud,channel))
    def test(self,adapter,board,sn,baud,channel=3):
        if not sn:raise RuntimeError('未识别ST-LINK序列号，不自动复位其他开发板。')
        multi=getattr(self,'multi',False)
        request_id=channel_ids(channel)[0] if multi else 0x321
        out=project_root()/'logs'/(('pc-can123-CAN'+str(channel)+'-' if multi else 'pc-can3-')+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True)
        decoder=ATDecoder();received=[];sent=0;board_raw=b'';next_send=0.;send_started=None
        board_lines=bytearray()
        (out/'settings.json').write_text(json.dumps({'adapter_port':adapter,'adapter_serial_baud':baud,
            'board_port':board,'board_serial_baud':115200,'stlink_serial':sn,'can_bitrate':1000000,'channel':channel,'multi':multi,
            'protocol':'RobStride AT extended classic data','ports':[{'device':p.device,'description':p.description,
            'hwid':p.hwid,'serial_number':p.serial_number} for p in comports()]},ensure_ascii=False,indent=2),encoding='utf-8')
        self.events.put(('text','日志：'+str(out)))
        with ExitStack() as stack:
            pc=stack.enter_context(serial.Serial(adapter,baud,timeout=0,write_timeout=1))
            mcu=stack.enter_context(serial.Serial(board,115200,timeout=0))
            board_file=stack.enter_context((out/'board.log').open('wb'))
            raw_file=stack.enter_context((out/'usb-raw.jsonl').open('w',encoding='utf-8'))
            frames_file=stack.enter_context((out/'pc-frames.jsonl').open('w',encoding='utf-8'))
            pc.reset_input_buffer();mcu.reset_input_buffer()
            result=subprocess.run(tools.reset_command(sn),env=tools.environment(),capture_output=True,timeout=20)
            (out/'reset.log').write_bytes(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError('开发板复位失败。')
            start=time.monotonic()
            while time.monotonic()-start<23 and not self.stop_event.is_set():
                now=time.monotonic();data=mcu.read(mcu.in_waiting or 1)
                if data:
                    board_raw+=data;board_file.write(data);board_file.flush();board_lines.extend(data)
                    while b'\n' in board_lines:
                        line,_,remaining=board_lines.partition(b'\n');board_lines=bytearray(remaining)
                        text=line.decode('utf-8',errors='replace').rstrip()
                        self.events.put(('text','开发板：'+text))
                        health=multi_health(text)
                        if multi and health:self.events.put(('health',health))
                if send_started is None and now-start>=1:
                    expected=[b'# CAN_MULTI_TEST=1;',b'# MULTI_READY=1;'] if multi else [b'# CAN3_PC_TEST=1;']
                    if not all(marker in board_raw for marker in expected):
                        raise RuntimeError('板内不是当前测试所需的固件，或初始化未完成；请编译烧录。未发送任何测试帧。')
                    send_started=now;next_send=now
                if send_started is not None and sent<100 and now>=next_send:
                    packet=multi_request(sent,channel) if multi else request(sent)
                    if pc.write(packet)!=len(packet):raise RuntimeError('串口写入不完整。')
                    frames_file.write(json.dumps({'event':'SERIAL_SUBMITTED','id':hex(request_id),'channel':channel,'sequence':sent,'packet_hex':packet.hex(' ')})+'\n')
                    sent+=1;next_send=now+.1
                    if sent%10==0:self.events.put(('text',f'电脑串口已提交 {sent}/100 帧（不等于硬件已发送完成）'))
                data=pc.read(pc.in_waiting or 1)
                if data:
                    raw_file.write(json.dumps({'pc_time':datetime.now().isoformat(),'bytes':data.hex(' ')})+'\n')
                    for identifier,payload in decoder.feed(data):
                        received.append((identifier,payload))
                        frames_file.write(json.dumps({'event':'RX','id':hex(identifier),'data':payload.hex(' ')})+'\n')
                        self.events.put(('text',f'电脑收到：ID=0x{identifier:X} DATA={payload.hex(" ").upper()}'))
                time.sleep(.002)
        board_log=board_raw.decode('utf-8',errors='replace')
        result=assess_multi(sent,received,board_log,channel,self.stop_event.is_set()) if multi else assess(sent,received,board_log,self.stop_event.is_set())
        result['decoder_discarded_bytes']=decoder.discarded
        result['decoder_unsupported_frames']=decoder.unsupported
        result['decoder_pending_bytes']=len(decoder.buffer)
        if decoder.discarded or decoder.unsupported or decoder.buffer:result['pass']=False
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        self.events.put(('text',json.dumps(result,ensure_ascii=False,indent=2)))
        self.events.put(('text','双向测试通过' if result['pass'] else '未通过。已保留电脑与开发板两侧原始记录。'))
    def poll(self):
        if self.closed:return
        for _ in range(300):
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='done':
                self.prepare_button.configure(state='normal');self.test_button.configure(state='normal')
                if self.multi:self.channel.configure(state='readonly')
            elif kind=='health':
                self.health_table.item(value['channel'],values=[value.get(k,'—') for k in ('channel','state','rx_unique','tx_done','rx_edge_observations','lec','tec','rec')])
            else:self.output.insert('end',value+'\n');self.output.see('end');self.status.set(value[-250:])
        self.window.after(100,self.poll)
    def close(self):self.stop_event.set();self.closed=True;self.window.destroy()

if __name__=='__main__':
    app=PCTest();app.window.mainloop()
