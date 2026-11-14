import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog
import motor_enable as m
import platform_tools as tools
import workspace

class MotorSpeedTests(unittest.TestCase):
    def test_startup_700_profile_and_strict_current_policy(self):
        p=catalog.profile('RS10P-Speed-0700mA')
        self.assertEqual(p['cmake_options']['PICO_SPEED_LIMIT_MA'],700)
        self.assertIn('-DPICO_SPEED_LIMIT_MA=700',tools.build_commands(p['id'])[0])
        banner='# PICO_MOTOR_SPEED=1; channel=FDCAN1 bitrate=1000000 model=RS10P motor_id=1 host_id=253 max_enable_ms=3000 host_timeout_ms=500 target_rad_s=0.3 current_limit_A=0.7 accel_rad_s2=0.5 iq_trip_A=0.8 current_policy=STARTUP_0700_V1'
        self.assertTrue(m.validate_banner(banner,p))
        for old,new in [('current_limit_A=0.7','current_limit_A=0.5'),('iq_trip_A=0.8','iq_trip_A=1.8'),('STARTUP_0700_V1','BASE_0500_V1'),('max_enable_ms=3000','max_enable_ms=30000')]:
            with self.assertRaises(ValueError):m.validate_banner(banner.replace(old,new),p)
        with self.assertRaises(ValueError):m.validate_banner(banner,catalog.profile('RS10P-Speed-CAN1'))
        self.assertEqual(m.StartupSpeedPanel.profile_ids,('RS10P-Speed-0700mA',))

    def test_profiles_banner_and_experiment_separation(self):
        for model,ident in [('RS10P',1),('RS00',2)]:
            p=catalog.profile(model+'-Speed-CAN1')
            self.assertEqual(p['cmake_options']['PICO_ENABLE_MOTOR_ID'],ident)
            self.assertIn('-DPICO_APP=MotorSpeed',tools.build_commands(p['id'])[0])
            _,entry=workspace.prepare(p['id']);self.assertEqual(entry.name,'motor_enable_app.c')
            line=f'# PICO_MOTOR_SPEED=1; channel=FDCAN1 bitrate=1000000 model={model} motor_id={ident} max_enable_ms=3000 host_timeout_ms=500 target_rad_s=0.3 current_limit_A=0.5 accel_rad_s2=0.5'
            self.assertTrue(m.validate_banner(line,p))
            for bad in [line.replace('0.3','3.0'),line.replace('current_limit_A=0.5','current_limit_A=5'),line.replace('max_enable_ms=3000','max_enable_ms=30000'),line.replace('FDCAN1','FDCAN3'),line.replace('PICO_MOTOR_SPEED','PICO_MOTOR_ENABLE')]:
                with self.assertRaises(ValueError):m.validate_banner(bad,p)
            with self.assertRaises(ValueError):m.validate_banner(line,catalog.profile(model+'-Enable-CAN1'))

    def test_speed_worker_waits_for_ready_never_runs_without_operator(self):
        app=m.SpeedPanel.__new__(m.SpeedPanel)
        app.events=queue.Queue();app.commands=queue.Queue();app.disconnect=threading.Event();app.stop_requested=threading.Event()
        class Device:
            def __init__(self):self.reads=0;self.pending=b'';self.writes=[];self.is_open=True
            @property
            def in_waiting(self):return len(self.pending)
            def __enter__(self):return self
            def __exit__(self,*args):self.is_open=False
            def reset_input_buffer(self):pass
            def flush(self):pass
            def read(self,n):
                self.reads+=1
                if self.reads==1:return b'# PICO_MOTOR_SPEED=1; channel=FDCAN1 bitrate=1000000 model=RS10P motor_id=1 max_enable_ms=3000 host_timeout_ms=500 target_rad_s=0.3 current_limit_A=0.5 accel_rad_s2=0.5\n'
                if self.reads==2:
                    assert not self.writes
                    return b'# SPEED_COMMAND_READY=1; protocol=2\n# SPEED_STATE,state=READY,id=1,stop_confirmed=1\n'
                if self.pending:data=self.pending;self.pending=b'';return data
                app.stop_requested.set();app.disconnect.set();return b''
            def write(self,data):
                self.writes.append(data);command=data.decode().strip()
                assert not command.startswith(('RUN ','ENABLE '))
                if command.startswith('SESSION '):self.pending+=f'# SESSION_OK token={command.split()[1]} id=1\n'.encode()
                if command=='STOP':self.pending+=b'# SPEED_STATE,state=DONE,id=1,stop_confirmed=1\n# SPEED_RESULT,result=STOPPED,id=1\n'
                return len(data)
        dev=Device()
        with tempfile.TemporaryDirectory() as folder,patch.object(m,'project_root',return_value=Path(folder)),patch.object(m.serial,'Serial',return_value=dev),patch.object(m.tools,'tool',return_value='fake'),patch.object(m.tools,'environment',return_value={}),patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'',stderr=b'')):
            app.worker(SimpleNamespace(device='FAKE',serial_number='FAKE'),catalog.profile('RS10P-Speed-CAN1'))
            result=json.loads(next(Path(folder).glob('logs/motor-speed-*/result.json')).read_text(encoding='utf-8'))
            self.assertFalse(result['pass'])
        self.assertTrue(any(v.startswith(b'KEEP ') for v in dev.writes))
        self.assertIn(b'STOP\n',dev.writes)

if __name__=='__main__':unittest.main()
