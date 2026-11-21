import unittest,csv,tempfile,queue,threading
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import catalog,motor_tuning
from tuning_scope import ScopeData

SAMPLE='# TUNE_SAMPLE,t_ms=1234,mode=POS,accepted_seq=2,applied_seq=1,command_angle_mdeg=5000,target_angle_mdeg=3000,actual_angle_mdeg=2000,error_mdeg=1000,iq_mA=-123,command_iq_mA=NA,iq_target_mA=NA,limit_mA=500,velocity_mrad_s=200'
BANNER='# PICO_MOTOR_TUNING=1; channel=FDCAN1 bitrate=1000000 model=RS10P motor_id=1 motor_count=1 host_id=253 protocol=6 position_limit_mdeg=30000 current_limit_ma=5300 speed_limit_mrad=300 max_position_ms=300000 max_speed_ms=60000 host_timeout_ms=500'
class TuningTests(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(motor_tuning.encode_target('POS',30,.3,0),(30000,300))
        self.assertEqual(motor_tuning.encode_target('SPD',0,.2,-.3),(-300,0))
        for mode,a,l,i in [('POS',31,.2,0),('POS',0,.31,0),('SPD',0,.2,.301),('POS','nan',.2,0),('IQ',0,.2,0)]:
            with self.assertRaises(ValueError):motor_tuning.encode_target(mode,a,l,i)
    def test_firmware_identity(self):
        p=catalog.profile('RS10P-Tuning');self.assertTrue(motor_tuning.validate_banner(BANNER,p))
        with self.assertRaises(ValueError):motor_tuning.validate_banner(BANNER.replace('bitrate=1000000','bitrate=500000'),p)
    def test_retired(self):
        self.assertFalse(catalog.RETIRED.intersection(p['id'] for p in catalog.profiles()))
        self.assertEqual(catalog.profile('RS10P-Enable-CAN1')['cmake_options']['PICO_APP'],'MotorEnable')
    def test_scope_units_csv_missing_and_reset(self):
        d=ScopeData();self.assertTrue(d.feed(SAMPLE));r=d.rows[-1]
        self.assertEqual((r['requested_angle_deg'],r['applied_angle_deg'],r['actual_angle_deg']),(5,3,2))
        self.assertEqual(r['iq_A'],-.123);self.assertIsNone(r['iq_target_A'])
        self.assertFalse(d.feed(SAMPLE));self.assertFalse(d.feed(SAMPLE.replace('1234','bad')))
        with tempfile.TemporaryDirectory() as f:
            p=Path(f)/'scope.csv';d.export(p)
            with p.open(encoding='utf-8-sig',newline='') as file:rows=list(csv.DictReader(file))
            self.assertEqual(rows[0]['iq_target_A'],'');self.assertEqual(rows[0]['current_limit_A'],'0.5')
        d.feed('# TUNE_ORIGIN,id=1,position_urad=1000000');self.assertFalse(d.rows)
    def test_iq_scope_has_no_fake_angle_reference(self):
        d=ScopeData();d.feed(SAMPLE.replace('mode=POS','mode=IQ').replace('command_angle_mdeg=5000','command_angle_mdeg=NA').replace('target_angle_mdeg=3000','target_angle_mdeg=NA').replace('error_mdeg=1000','error_mdeg=NA').replace('iq_target_mA=NA','iq_target_mA=-100').replace('command_iq_mA=NA','command_iq_mA=-150').replace('limit_mA=500','limit_mA=NA'))
        r=d.rows[-1];self.assertIsNone(r['applied_angle_deg']);self.assertEqual(r['iq_target_A'],-.1);self.assertEqual(r['requested_iq_A'],-.15)
    def test_worker_no_auto_enable_and_explicit_modes(self):
        for mode in (None,'POS','SPD'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                panel=motor_tuning.TuningPanel.__new__(motor_tuning.TuningPanel)
                panel.events=queue.Queue();panel.commands=queue.Queue();panel.disconnect=threading.Event();panel.stop_requested=threading.Event()
                writes=[]
                class Device:
                    is_open=True;in_waiting=0
                    def __init__(self,*a,**kw):
                        self.buf=(BANNER+'\n# CONTROL_BACKEND,commit='+motor_tuning.BACKEND+'\n# TUNE_COMMAND_READY=1; protocol=6\n# TUNE_STATE,state=READY,id=1,mode=POS,stop_confirmed=1\n').encode()
                    def __enter__(self):return self
                    def __exit__(self,*a):pass
                    def reset_input_buffer(self):pass
                    def read(self,n):
                        data=self.buf;self.buf=b''
                        if b'SESSION_OK' in data and mode:panel.commands.put(('ARM',mode,1,[(0,200 if mode=='POS' else 0)],60000 if mode=='POS' else 3000,motor_tuning.time.monotonic()))
                        self.reads=getattr(self,'reads',0)+1
                        if self.reads>100:raise RuntimeError('fake serial stalled')
                        return data
                    def write(self,data):
                        text=data.decode().strip();writes.append(text)
                        if text.startswith('SESSION '):
                            self.buf+=b'# SESSION_OK token=AABBCCDD id=1\n'
                        elif text.startswith('ARM '):
                            self.buf+=f'# TUNE_STATE,state=RUNNING,id=1,mode={mode},stop_confirmed=0\n'.encode()
                            panel.commands.put(('SET',mode,2,[(100,100 if mode=='POS' else 0)],60000 if mode=='POS' else 3000,motor_tuning.time.monotonic()))
                        elif text.startswith(('SET ','SETSPEED ')) or (mode is None and text.startswith('KEEP ')):
                            panel.stop_requested.set();panel.disconnect.set()
                        elif text=='STOP':self.buf+=b'# TUNE_STATE,state=DONE,id=1,stop_confirmed=1,target_cleared=1\n'
                        return len(data)
                with patch.object(motor_tuning,'project_root',return_value=Path(folder)),patch.object(motor_tuning.serial,'Serial',Device),patch.object(motor_tuning.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'',stderr=b'')),patch.object(motor_tuning.tools,'tool',return_value='unused'),patch.object(motor_tuning.secrets,'token_hex',return_value='aabbccdd'):
                    panel.worker(SimpleNamespace(device='FAKE',serial_number='TEST'),catalog.profile('RS10P-Tuning'))
                arms=[w for w in writes if w.startswith('ARM ')]
                self.assertEqual(len(arms),0 if mode is None else 1)
                if mode:self.assertTrue(any(w.startswith('SET ' if mode=='POS' else 'SETSPEED ') for w in writes))
                self.assertIn('STOP',writes)

    def test_burst_draw_is_coalesced_without_dropping_samples(self):
        import tkinter as tk,time
        from tuning_scope import TuningScope
        root=tk.Tk();root.withdraw();scope=TuningScope(root);scope.pack()
        try:
            with patch.object(scope.canvas,'winfo_ismapped',return_value=True),patch.object(scope,'draw',wraps=scope.draw) as draw:
                begin=time.perf_counter()
                for i in range(850):scope.feed(SAMPLE.replace('t_ms=1234',f't_ms={i*30+1}'))
                elapsed=time.perf_counter()-begin
                self.assertEqual(draw.call_count,0)
                self.assertEqual(len(scope.data.rows),850)
                self.assertIsNotNone(scope._draw_timer)
                root.after(150,root.quit);root.mainloop()
                self.assertEqual(draw.call_count,1)
                self.assertLess(elapsed,.5)
                scope.freeze()
                scope.feed(SAMPLE.replace('t_ms=1234','t_ms=30000'))
                self.assertEqual(len(scope.data.rows),851)
                self.assertIsNone(scope._draw_timer)
                scope.freeze();self.assertIsNotNone(scope._draw_timer)
            scope.destroy()
        finally:root.destroy()

    def test_sliders_sync_entries_and_respect_mode(self):
        import tkinter as tk
        root=tk.Tk();root.withdraw()
        try:
            panel=motor_tuning.TuningPanel(root);panel.window.withdraw()
            panel.sliders[0].slider.set(25.1)
            self.assertAlmostEqual(float(panel.angle.get()),25.1)
            self.assertEqual(panel.target(),(25100,200))
            panel.angle.set('-30');self.assertEqual(panel.sliders[0].value.get(),-30)
            panel.speed_limit.set('0.15');self.assertEqual(panel.sliders[1].value.get(),.15)
            panel.mode.set('SPD');panel.mode_changed()
            self.assertEqual(str(panel.sliders[0].slider['state']),'disabled')
            self.assertEqual(str(panel.sliders[2].slider['state']),'normal')
            panel.sliders[2].slider.set(-.25);self.assertEqual(panel.target(),(-250,0))
            self.assertFalse(panel.armed);self.assertTrue(panel.commands.empty())
            panel.destroy()
        finally:root.destroy()
    def test_speed_scope_units_and_old_firmware_rejected(self):
        with self.assertRaises(ValueError):motor_tuning.validate_banner(BANNER.replace('protocol=6','protocol=3'),catalog.profile('RS10P-Tuning'))
        d=ScopeData();d.feed(SAMPLE.replace('mode=POS','mode=SPD')+',command_velocity_mrad_s=-300,target_velocity_mrad_s=-200,speed_limit_mrad_s=NA')
        self.assertEqual(d.rows[-1]['requested_velocity_rad_s'],-.3)
        self.assertEqual(d.rows[-1]['target_velocity_rad_s'],-.2)
        self.assertIsNone(d.rows[-1]['speed_limit_rad_s'])

    def test_duration_validation_and_dual_controls(self):
        import tkinter as tk
        self.assertEqual(motor_tuning.duration_ms('POS','300'),300000)
        self.assertEqual(motor_tuning.duration_ms('SPD','1.5'),1500)
        for mode,value in [('POS','301'),('SPD','61'),('SPD','0'),('POS','nan')]:
            with self.assertRaises(ValueError):motor_tuning.duration_ms(mode,value)
        root=tk.Tk();root.withdraw()
        try:
            panel=motor_tuning.TuningPanel(root,selected='Motors-Tuning');panel.window.withdraw()
            self.assertTrue(panel.dual());self.assertEqual(len(panel.scope_panes.panes()),2)
            panel.connected=True;panel.last_state={'state':'READY'};panel.duration.set('12')
            panel.angle.set('5');panel.angle2.set('-3');panel.arm()
            command=panel.commands.get_nowait();self.assertEqual(command[3],[(5000,200,5300),(-3000,200,4700)]);self.assertEqual(command[4],12000)
            self.assertEqual(str(panel.duration_entry['state']),'disabled')
            self.assertEqual(str(panel.start_button['state']),'disabled')
            panel.destroy()
        finally:root.destroy()
    def test_dual_worker_waits_for_group_stop_and_sends_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            panel=motor_tuning.TuningPanel.__new__(motor_tuning.TuningPanel)
            panel.events=queue.Queue();panel.commands=queue.Queue();panel.disconnect=threading.Event();panel.stop_requested=threading.Event()
            writes=[];group_done=[]
            class Device:
                is_open=True;in_waiting=0
                def __init__(self,*a,**kw):
                    self.buf=(BANNER.replace('model=RS10P motor_id=1 motor_count=1','model=RS10P,RS00 motor_id=0 motor_count=2')+'\n# CONTROL_BACKEND,commit='+motor_tuning.BACKEND+'\n# TUNE_COMMAND_READY=1; protocol=6\n').encode();self.stop_step=0;self.reads=0
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def reset_input_buffer(self):pass
                def read(self,n):
                    self.reads+=1
                    if self.reads>100:raise RuntimeError('fake serial stalled')
                    if not self.buf and self.stop_step==1:
                        self.stop_step=2;self.buf=b'# TUNE_GROUP_STATE,state=STOPPING,id=0,stop_confirmed=0\n'
                    elif not self.buf and self.stop_step==2:
                        self.stop_step=3;group_done.append(True);self.buf=b'# TUNE_GROUP_STATE,state=DONE,id=0,stop_confirmed=1,target_cleared=1\n# TUNE_GROUP_RESULT,result=STOPPED,id=0,stop_confirmed=1,target_cleared=1\n'
                    data=self.buf;self.buf=b''
                    if b'SESSION_OK' in data:panel.commands.put(('ARM','POS',1,[(5000,200),(-3000,150)],5000,motor_tuning.time.monotonic()))
                    return data
                def write(self,data):
                    text=data.decode().strip();writes.append(text)
                    if text.startswith('SESSION '):self.buf+=b'# SESSION_OK token=AABBCCDD id=0\n# TUNE_GROUP_STATE,state=READY,id=0,stop_confirmed=1\n'
                    elif text.startswith('ARM2 '):
                        self.buf+=b'# TUNE_STATE,state=RUNNING,id=1,stop_confirmed=0\n# TUNE_STATE,state=RUNNING,id=2,stop_confirmed=0\n# TUNE_GROUP_STATE,state=RUNNING,id=0,stop_confirmed=0\n'
                        panel.commands.put(('SET','POS',2,[(10000,100),(-10000,100)],5000,motor_tuning.time.monotonic()))
                    elif text.startswith('SET2 '):panel.stop_requested.set();panel.disconnect.set()
                    elif text=='STOP':self.buf+=b'# TUNE_STATE,state=DONE,id=1,stop_confirmed=1,target_cleared=1\n';self.stop_step=1
                    return len(data)
            with patch.object(motor_tuning,'project_root',return_value=Path(folder)),patch.object(motor_tuning.serial,'Serial',Device),patch.object(motor_tuning.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'',stderr=b'')),patch.object(motor_tuning.tools,'tool',return_value='unused'),patch.object(motor_tuning.secrets,'token_hex',return_value='aabbccdd'):
                panel.worker(SimpleNamespace(device='FAKE',serial_number='TEST'),catalog.profile('Motors-Tuning'))
            self.assertIn('ARM2 AABBCCDD POS 1 5000 200 -3000 150 5000',writes)
            self.assertIn('SET2 AABBCCDD 2 10000 100 -10000 100',writes);self.assertTrue(group_done)
