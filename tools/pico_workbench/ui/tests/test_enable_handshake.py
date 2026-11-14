"""Reproduce a host receiving the banner before MCU RX is ready."""
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog
import motor_enable as m

class HandshakeRegressionTests(unittest.TestCase):
    def test_no_session_until_command_ready_and_no_automatic_enable(self):
        app=m.EnablePanel.__new__(m.EnablePanel)
        app.events=queue.Queue();app.commands=queue.Queue();app.disconnect=threading.Event();app.stop_requested=threading.Event()
        class Fake:
            def __init__(self):self.reads=0;self.writes=[];self.pending=b'';self.ready=False;self.is_open=True
            @property
            def in_waiting(self):return len(self.pending)
            def __enter__(self):return self
            def __exit__(self,*args):self.is_open=False
            def reset_input_buffer(self):pass
            def flush(self):pass
            def read(self,count):
                self.reads+=1
                if self.reads==1:return b'# PICO_MOTOR_ENABLE=1; channel=FDCAN1 bitrate=1000000 model=RS10P motor_id=1\n'
                if self.reads==2:
                    self.assert_no_early_send();return b''
                if self.reads==3:
                    self.ready=True;return b'# ENABLE_COMMAND_READY=1; protocol=2\n# ENABLE_STATE,state=READY,id=1,stop_confirmed=1\n'
                if self.pending:data=self.pending;self.pending=b'';return data
                app.stop_requested.set();app.disconnect.set();return b''
            def assert_no_early_send(self):assert not self.writes,'SESSION sent before MCU RX ready'
            def write(self,data):
                self.writes.append(data);command=data.decode().strip()
                assert not command.startswith('ENABLE '),'No operator command was issued'
                if command.startswith('SESSION '):
                    assert self.ready
                    self.pending+=f'# SESSION_OK token={command.split()[1]} id=1\n'.encode()
                if command=='STOP':self.pending+=b'# ENABLE_STATE,state=DONE,id=1,stop_confirmed=1\n'
                return len(data)
        dev=Fake()
        with tempfile.TemporaryDirectory() as folder,patch.object(m,'project_root',return_value=Path(folder)),patch.object(m.serial,'Serial',return_value=dev),patch.object(m.tools,'tool',return_value='programmer'),patch.object(m.tools,'environment',return_value={}),patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'',stderr=b'')):
            app.worker(SimpleNamespace(device='TEST',serial_number='TEST'),catalog.profile('RS10P-Enable-CAN1'))
        self.assertTrue(any(v.startswith(b'SESSION ') for v in dev.writes))
        self.assertTrue(any(v.startswith(b'KEEP ') for v in dev.writes))
        self.assertIn(b'STOP\n',dev.writes)

if __name__=='__main__':unittest.main()
