import json
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import catalog
import motor_enable as m
import platform_tools as tools
import workspace

class DualPositionTests(unittest.TestCase):
    def test_independent_profile_and_parameters(self):
        p=catalog.profile('Motors-Independent-Position')
        self.assertIn('-DPICO_APP=MotorDualPosition',tools.build_commands(p['id'])[0])
        _,entry=workspace.prepare(p['id']);self.assertEqual(entry.name,'motor_dual_position_app.c')
        banner='# PICO_MOTOR_DUAL_POSITION=1; channel=FDCAN1 bitrate=1000000 models=RS10P,RS00 motor_ids=1,2 max_enable_ms=90000 host_timeout_ms=500 angle1_deg=5 angle2_deg=-3 dwell1_ms=500 dwell2_ms=800 cycles=10 speed_limit_rad_s=0.2 current_limit_A=0.5 arrival_policy=POSITION_WINDOW_V3 tx_policy=BOUNDED_RETRY_V1 tx_deadline_ms=300'
        self.assertTrue(m.validate_banner(banner,p))
        for bad in [banner.replace('angle2_deg=-3','angle2_deg=3'),banner.replace('dwell2_ms=800','dwell2_ms=500'),banner.replace('DUAL_POSITION','DUAL_SPEED'),banner.replace('POSITION_WINDOW_V3','POSITION_WINDOW_V2'),banner.replace(' tx_policy=BOUNDED_RETRY_V1',''),banner.replace('BOUNDED_RETRY_V1','SINGLE_ATTEMPT_V1'),banner.replace('tx_deadline_ms=300','tx_deadline_ms=3000')]:
            with self.assertRaises(ValueError):m.validate_banner(bad,p)
        with self.assertRaises(ValueError):m.validate_banner(banner,catalog.profile('RS10P-Position-Cycles'))
    def test_pause_heartbeat_keeps_receiving_until_timeout_without_proactive_stop(self):
        app=m.SpeedPanel.__new__(m.SpeedPanel)
        app.events=queue.Queue();app.commands=queue.Queue();app.disconnect=threading.Event();app.stop_requested=threading.Event();app.pause_heartbeat=threading.Event()
        class Device:
            def __init__(self):self.reads=0;self.pending=b'';self.writes=[];self.is_open=True;self.timeout_seen=False
            @property
            def in_waiting(self):return len(self.pending)
            def __enter__(self):return self
            def __exit__(self,*args):self.is_open=False
            def reset_input_buffer(self):pass
            def flush(self):pass
            def read(self,n):
                self.reads+=1
                if self.reads==1:return b'# PICO_MOTOR_SPEED=1; channel=FDCAN1 bitrate=1000000 model=RS10P motor_id=1 max_enable_ms=3000 host_timeout_ms=500 target_rad_s=0.3 current_limit_A=0.5 accel_rad_s2=0.5\n# SPEED_COMMAND_READY=1; protocol=2\n'
                if self.pending:data=self.pending;self.pending=b'';return data
                assert app.heartbeat_paused()
                self.timeout_seen=True;app.disconnect.set()
                return b'# SPEED_STATE,state=DONE,id=1,reason=HOST_TIMEOUT,error=1,stop_confirmed=1\n# SPEED_RESULT,result=FAIL,id=1,reason=HOST_TIMEOUT\n'
            def write(self,data):
                self.writes.append(data);text=data.decode().strip()
                if text.startswith('SESSION '):self.pending+=f'# SESSION_OK token={text.split()[1]} id=1\n'.encode()
                elif text.startswith('KEEP '):app.pause_heartbeat.set()
                elif text=='STOP':assert self.timeout_seen,'Pause must not send STOP before the MCU timeout'
                return len(data)
        dev=Device()
        with tempfile.TemporaryDirectory() as folder,patch.object(m,'project_root',return_value=Path(folder)),patch.object(m.serial,'Serial',return_value=dev),patch.object(m.tools,'tool',return_value='fake'),patch.object(m.tools,'environment',return_value={}),patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'',stderr=b'')):
            app.worker(SimpleNamespace(device='FAKE',serial_number='FAKE'),catalog.profile('RS10P-Speed-CAN1'))
            result=json.loads(next(Path(folder).glob('logs/motor-speed-*/result.json')).read_text(encoding='utf-8'))
            self.assertEqual(result['last_state']['reason'],'HOST_TIMEOUT');self.assertFalse(result['pass'])
        self.assertEqual(sum(v.startswith(b'KEEP ') for v in dev.writes),1)
