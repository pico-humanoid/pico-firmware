import json
import math
from pathlib import Path
import queue
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import catalog
import platform_tools as tools
import workspace
import position_diagnostic as d

BANNER='# PICO_MOTOR_POSITION_DIAG=1; channel=FDCAN1 bitrate=1000000 motor_id=1 model=RS10P host_id=253 policy=STOPPED_ECHO_V1 no_enable=1 target_write=manual_current_position_only tx_policy=BOUNDED_RETRY_V1'

class DiagnosticTests(unittest.TestCase):
    def test_profile_and_protected_banner(self):
        p=catalog.profile('RS10P-Position-Diag')
        self.assertIn('-DPICO_APP=MotorPositionDiag',tools.build_commands(p['id'])[0])
        self.assertTrue(d.validate_banner(BANNER,p))
        for old,new in [('motor_id=1','motor_id=2'),('no_enable=1','no_enable=0'),('manual_current_position_only','automatic'),('BOUNDED_RETRY_V1','SINGLE_ATTEMPT_V1')]:
            with self.assertRaises(ValueError):d.validate_banner(BANNER.replace(old,new),p)
        with self.assertRaises(ValueError):d.validate_banner(BANNER,catalog.profile('RS00-Position-Diag'))
        with patch.object(tools,'tool',return_value=None):_,entry=workspace.prepare(p['id'])
        self.assertEqual(entry.name,'motor_position_diag_app.c')

    def test_missing_values_are_not_zero_and_function_codes_are_not_can_indices(self):
        model=d.DiagnosticData();self.assertIsNone(model.value(0x7016))
        model.feed('# DIAG_VALUE,t_ms=5,index=0x7016,status=UNAVAILABLE,value_micro=0')
        self.assertIsNone(model.value(0x7016))
        model.feed('# DIAG_VALUE,t_ms=5,index=0x7016,status=OK,value_micro=-1443445')
        self.assertAlmostEqual(model.value(0x7016),-1.443445)
        self.assertNotIn(0x3016,d.PARAMS)
        model.feed('# DIAG_VALUE,t_ms=6,index=0x7016,status=OK,value_micro=-1694788')
        low,high,count=model.ranges[0x7016]
        self.assertEqual(count,2);self.assertAlmostEqual(math.degrees(high-low),14.4009,places=3)

    def test_mismatch_is_preserved_after_state_and_reset_clears_it(self):
        model=d.DiagnosticData();model.feed('# DIAG_ECHO,round=2,nominal_ms=10,age_ms=30,expected_urad=-1694788,read_urad=-1443445,error_urad=251343,status=MISMATCH')
        self.assertAlmostEqual(math.degrees(int(model.echo[0]['error_urad'])/1e6),14.4009,places=3)
        model.feed('# DIAG_ECHO_RESULT,result=MISMATCH,stop_confirmed=1,target_cleared=0')
        model.feed('# DIAG_STATE,state=DONE,echo_allowed=0,error=0')
        self.assertEqual(model.result['result'],'MISMATCH');self.assertFalse(model.can_verify())
        model.feed(BANNER);self.assertIsNone(model.result);self.assertEqual(model.echo,[])

    def test_firmware_must_explicitly_allow_verification(self):
        model=d.DiagnosticData();self.assertFalse(model.can_verify())
        model.feed('# DIAG_STATE,state=MONITOR,echo_allowed=1,error=0');self.assertTrue(model.can_verify())
        model.feed('# DIAG_STATE,state=STOPPING,echo_allowed=1,error=1');self.assertFalse(model.can_verify())

    def test_failed_reply_overrides_legacy_ok_zero_and_success_clears_it(self):
        model=d.DiagnosticData();model.feed(BANNER)
        model.feed('1133,RX,FDCAN1,EXT,DATA,0x110101FD,8,05 20 00 00 00 00 00 00')
        model.feed('# DIAG_VALUE,t_ms=1133,index=0x2005,status=OK,value_micro=0')
        self.assertIsNone(model.value(0x2005));self.assertEqual(model.values[0x2005]['status'],'READ_FAILED')
        self.assertNotIn(0x2005,model.ranges)
        model.feed('1200,RX,FDCAN1,EXT,DATA,0x110001FD,8,05 20 00 00 00 00 00 00')
        model.feed('# DIAG_VALUE,t_ms=1200,index=0x2005,status=OK,value_micro=0')
        self.assertEqual(model.value(0x2005),0)
        model.feed('# DIAG_STATE,state=MONITOR,echo_allowed=1,error=0')
        model.feed('1201,RX,FDCAN1,EXT,DATA,0x110101FD,8,19 70 00 00 00 00 00 00')
        self.assertFalse(model.can_verify())

    def test_other_motor_read_error_does_not_invalidate_current_motor(self):
        model=d.DiagnosticData();model.feed(BANNER)
        model.feed('1201,RX,FDCAN1,EXT,DATA,0x110102FD,8,19 70 00 00 00 00 00 00')
        self.assertNotIn(0x7019,model.read_errors)

    def run_worker(self,request):
        panel=d.PositionDiagnosticPanel.__new__(d.PositionDiagnosticPanel)
        panel.events=queue.Queue();panel.commands=queue.Queue();panel.finish=threading.Event()
        writes=[]
        class FakeSerial:
            in_waiting=0
            def __init__(self,*args,**kwargs):self.pending=(BANNER+'\n# DIAG_COMMAND_READY=1; protocol=2\n').encode();self.count=0
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def reset_input_buffer(self):pass
            def flush(self):pass
            def read(self,n):
                self.count+=1
                if self.count>100:raise RuntimeError('fake serial loop did not terminate')
                time.sleep(.001);value=self.pending;self.pending=b'';return value
            def write(self,b):
                text=b.decode().strip();writes.append(text)
                if text.startswith('SESSION '):
                    token=text.split()[1];self.pending+=f'# SESSION_OK token={token} id=1\n# DIAG_STATE,state=MONITOR,echo_allowed=1,error=0,stop_confirmed=1\n'.encode()
                elif text.startswith('KEEP '):
                    if request:panel.commands.put('VERIFY')
                    else:panel.finish.set()
                elif text.startswith('VERIFY '):
                    self.pending+=b'# DIAG_ECHO_RESULT,result=CONSISTENT,stop_confirmed=1,target_cleared=1\n';panel.finish.set()
                elif text=='STOP':self.pending+=b'# DIAG_STATE,state=DONE,stop_confirmed=1,echo_allowed=0,error=0\n'
                return len(b)
        with tempfile.TemporaryDirectory() as folder,patch.object(d,'project_root',return_value=Path(folder)),patch.object(d.serial,'Serial',FakeSerial),patch.object(d.tools,'tool',return_value='mock-programmer'),patch.object(d.tools,'environment',return_value={}),patch.object(d.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'',stderr=b'')):
            panel.worker(SimpleNamespace(device='MOCK',serial_number='MOCK-SN'),catalog.profile('RS10P-Position-Diag'))
            result=json.loads(next(Path(folder).glob('logs/*/result.json')).read_text(encoding='utf-8'))
            self.assertEqual(result['last_state']['stop_confirmed'],'1')
        return writes

    def test_readonly_worker_never_sends_verify_or_run(self):
        writes=self.run_worker(False)
        self.assertTrue(any(s.startswith('SESSION ') for s in writes));self.assertIn('STOP',writes)
        self.assertFalse(any(s.startswith(('VERIFY','RUN','ENABLE')) for s in writes))

    def test_manual_worker_sends_verify_once_with_current_token(self):
        writes=self.run_worker(True);verify=[s for s in writes if s.startswith('VERIFY ')]
        self.assertEqual(len(verify),1)
        self.assertEqual(verify[0].split()[1],next(s for s in writes if s.startswith('SESSION ')).split()[1])
        self.assertFalse(any(s.startswith(('RUN','ENABLE')) for s in writes))

if __name__=='__main__':unittest.main()
