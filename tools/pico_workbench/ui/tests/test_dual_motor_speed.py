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

BANNER='# PICO_MOTOR_DUAL_SPEED=1; channel=FDCAN1 bitrate=1000000 models=RS10P,RS00 motor_ids=1,2 host_id=253 max_enable_ms=3000 host_timeout_ms=500 target_rad_s=0.3 current_limit_A=0.5 accel_rad_s2=0.5'

class DualMotorSpeedTests(unittest.TestCase):
    def test_group_target_and_firmware_are_unambiguous(self):
        p=catalog.profile('Motors-Speed-CAN1')
        self.assertTrue(m.validate_banner(BANNER,p))
        for wrong in [BANNER.replace('motor_ids=1,2','motor_ids=1,1'),BANNER.replace('RS10P,RS00','RS00,RS10P'),BANNER.replace('FDCAN1','FDCAN3'),BANNER.replace('0.3','3.0')]:
            with self.assertRaises(ValueError):m.validate_banner(wrong,p)
        with self.assertRaises(ValueError):m.validate_banner(BANNER,catalog.profile('RS10P-Speed-CAN1'))
        self.assertIn('-DPICO_APP=MotorDualSpeed',tools.build_commands(p['id'])[0])
        _,entry=workspace.prepare(p['id']);self.assertEqual(entry.name,'motor_dual_speed_app.c')

    def test_one_ready_or_one_stopped_cannot_confirm_the_pair(self):
        states={'1':{'state':'READY','stop_confirmed':'1','enable_confirmed':'0'}}
        value=m.group_state(states)
        self.assertNotEqual(value['state'],'READY');self.assertEqual(value['stop_confirmed'],'0')
        states['2']={'state':'READY','stop_confirmed':'1','enable_confirmed':'0'}
        self.assertEqual(m.group_state(states)['state'],'READY')
        states['1']={'state':'DONE','stop_confirmed':'1','motion_confirmed':'1'}
        states['2']={'state':'STOPPING','stop_confirmed':'0','stop_unconfirmed':'1'}
        value=m.group_state(states)
        self.assertEqual(value['state'],'STOPPING');self.assertEqual(value['stop_confirmed'],'0')
        self.assertEqual(value['motion_confirmed'],'0');self.assertEqual(value['stop_unconfirmed'],'1')

    def test_group_session_does_not_start_either_motor(self):
        app=m.DualSpeedPanel.__new__(m.DualSpeedPanel)
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
                if self.reads==1:return (BANNER+'\n').encode()
                if self.reads==2:
                    assert not self.writes
                    return b'# DUAL_SPEED_COMMAND_READY=1; protocol=2\n# DUAL_SPEED_STATE,state=READY,id=1,stop_confirmed=1\n# DUAL_SPEED_STATE,state=READY,id=2,stop_confirmed=1\n'
                if self.pending:data=self.pending;self.pending=b'';return data
                app.stop_requested.set();app.disconnect.set();return b''
            def write(self,data):
                self.writes.append(data);command=data.decode().strip()
                assert not command.startswith(('RUN ','ENABLE '))
                if command.startswith('SESSION '):
                    assert command.split()[-1]=='0'
                    self.pending+=f'# SESSION_OK token={command.split()[1]} id=0\n'.encode()
                if command=='STOP':self.pending+=b'# DUAL_SPEED_STATE,state=DONE,id=1,stop_confirmed=1\n# DUAL_SPEED_STATE,state=DONE,id=2,stop_confirmed=1\n# DUAL_SPEED_RESULT,result=STOPPED\n'
                return len(data)
        dev=Device()
        with tempfile.TemporaryDirectory() as folder,patch.object(m,'project_root',return_value=Path(folder)),patch.object(m.serial,'Serial',return_value=dev),patch.object(m.tools,'tool',return_value='fake'),patch.object(m.tools,'environment',return_value={}),patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'',stderr=b'')):
            app.worker(SimpleNamespace(device='FAKE',serial_number='FAKE'),catalog.profile('Motors-Speed-CAN1'))
            result=json.loads(next(Path(folder).glob('logs/motor-dual_speed-*/result.json')).read_text(encoding='utf-8'))
            self.assertFalse(result['pass']);self.assertEqual(set(result['last_state']['motors']),{'1','2'})
        self.assertIn(b'STOP\n',dev.writes)

if __name__=='__main__':unittest.main()
