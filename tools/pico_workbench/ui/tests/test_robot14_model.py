import contextlib
import math
from pathlib import Path
import queue
import random
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import robot14_model as r


def info(core, token=123, signature=r.SIGNATURE):
    return (r.INFO, 0, token, r.INFO_DATA.pack(core.nonce, bytes(range(1,13)), 160000000, signature, 100, 200))


def node(mid=1, phase=0, command=r.ZERO, stamp=100):
    bus, model = r.topology(mid)
    return (r.NODE, stamp, 123, r.NODE_DATA.pack(mid,bus,0 if model=='RS00' else 1,phase,
             7|(8 if phase==11 else 0),2 if phase==11 else 0,0,0,
             0,0,0,250,*command,0,0,0,0,0))


def state(latched=0):
    return (r.STATE, 100, 123, r.STATE_DATA.pack(100,latched,0,*([0]*22)))


def accepted(core, kind, mid, now):
    seq = next(s for s,req in core.pending.items() if req[:2]==(kind,mid))
    core.receive((r.ACK,seq,123,bytes((kind,0,mid))),now)


class CodecTests(unittest.TestCase):
    def test_crc(self):
        self.assertEqual(r.crc(b'123456789'),0x29b1)

    def test_fragment_resync_and_crc(self):
        wire=r.packet(r.PING,3,10)
        p=r.Parser()
        self.assertEqual(p.feed(b'noise'+wire[:4],0),[])
        self.assertEqual(p.feed(wire[4:],.01),[(r.PING,3,10,b'')])
        broken=bytearray(wire);broken[-1]^=1
        self.assertEqual(p.feed(broken+wire,.02),[(r.PING,3,10,b'')])
        self.assertGreater(p.bad,0)

    def test_timeout_oversize_random(self):
        p=r.Parser();w=r.packet(r.PING)
        p.feed(w[:8],0)
        self.assertEqual(p.feed(w[8:],.06),[])
        oversize=bytearray(w);oversize[4:6]=b'\xff\xff'
        self.assertEqual(p.feed(bytes(oversize)+w,.07),[(r.PING,0,0,b'')])
        rng=random.Random(42)
        p.feed(bytes(rng.randrange(256) for _ in range(10000)),.08)
        self.assertLess(len(p.buffer),176)
        with self.assertRaises(ValueError): r.packet(r.SET,data=b'x'*161)

    def test_topology(self):
        self.assertEqual([r.topology(i) for i in (1,3,4,7,8,10,11,14)],
                         [(2,'RS00'),(2,'RS00'),(2,'RS10P'),(2,'RS10P'),(3,'RS00'),(3,'RS00'),(3,'RS10P'),(3,'RS10P')])
        for i in (0,15):
            with self.assertRaises(ValueError):r.topology(i)

    def test_target_and_batch(self):
        self.assertEqual(r.target([12.57,-1,1,5,1]),(12570,-1000,1000,5000,1000))
        for v in ([math.nan,0,0,0,0],[0,0,0,6,0],[0,2,0,0,0],[0,0,0,-1,0]):
            with self.assertRaises(ValueError):r.target(v)
        b=r.batch({i:r.ZERO for i in range(1,15)})
        self.assertEqual(len(b),142);self.assertEqual(b[:2],b'\xff\x3f')
        self.assertEqual(len(r.packet(r.SET,data=b)),158)

    def test_real_c_wire_compatibility(self):
        """Compile actual firmware codec, NOT a Python-only echo implementation."""
        root=Path(__file__).resolve().parents[4]
        app=root/'firmware/PICO_CAN/App'
        with tempfile.TemporaryDirectory() as d:
            exe=str(Path(d)/'wire')
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wpedantic',
                '-I'+str(app),'-I'+str(app/'robot'), str(root/'firmware/PICO_CAN/tests/test_robot_link.c'),
                str(app/'robot/Communicate/robot_link.c'),str(app/'robot/Modules/motor_network.c'),
                str(app/'robot/Peripheral/rs_motor.c'),'-lm','-o',exe],check=True,capture_output=True)
            lines=subprocess.check_output([exe,'--wire'],text=True).splitlines()
        core=r.Controller(0,nonce=777)
        for line in lines:
            frames=r.Parser().feed(bytes.fromhex(line),0)
            self.assertEqual(len(frames),1)
            core.receive(frames[0],0)
        self.assertEqual(core.nodes[1]['p'],1.25)
        self.assertAlmostEqual(core.nodes[1]['v'],-.1)
        self.assertEqual(core.nodes[1]['v_age'],0)
        self.assertEqual(core.info['uid'],'0102030405060708090a0b0c')
        self.assertEqual(core.events[-1][1]['bms_mv'],48000)
        self.assertEqual(core.events[-1][1]['power_mv'],47900)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.c=r.Controller(0,nonce=1234)
        self.c.receive(info(self.c),0)
        for mid in range(1,15): self.c.receive(node(mid),0)

    def arm(self, mid=1, duration=10):
        c=self.c;c.enable(mid,duration,0);accepted(c,r.ENABLE,mid,0);c.receive(node(mid,11),0)

    def kinds(self):
        return [wire[3] for wire in self.c.outbox]

    def test_connect_read_only(self):
        c=r.Controller(0,nonce=9);c.step(0)
        self.assertEqual(c.outbox,[r.packet(r.HELLO,token=9)])
        c.receive(info(c),.01);c.outbox.clear();c.step(.02)
        self.assertEqual([p[3] for p in c.outbox],[r.PING])
        self.assertFalse(c.owns)

    def test_wrong_info_and_old_firmware(self):
        with self.assertRaises(ValueError):self.c.receive(info(self.c,signature=0),0)
        with self.assertRaises(ValueError):r.Controller(0).step(3.01)
        c=r.Controller(0,nonce=20);c.receive(info(self.c),0);self.assertEqual(c.token,0)
        with self.assertRaises(ValueError): self.c.receive(info(self.c,token=456),0)

    def test_stale_and_finite_duration(self):
        with self.assertRaises(ValueError):self.c.enable(1,10,.31)
        for seconds in (0,61,math.nan,math.inf):
            with self.assertRaises(ValueError):self.c.enable(1,seconds,0)

    def test_enable_many_skips_unready(self):
        c=self.c
        c.receive(node(2, phase=11), 0)
        queued, skipped = c.enable_many([1, 2, 3], 10, 0)
        self.assertEqual(queued, [1, 3])
        self.assertEqual([m for m, _ in skipped], [2])
        self.assertEqual(sum(1 for w in c.outbox if w[3] == r.ENABLE), 2)
        self.assertEqual(sorted(c.deadlines), [1, 3])

    def test_no_set_before_enable_ack(self):
        c=self.c;c.enable(1,10,0);c.step(.01)
        self.assertNotIn(r.SET,self.kinds())
        accepted(c,r.ENABLE,1,.01);c.step(.02)
        self.assertIn(r.SET,self.kinds())
        wire=next(p for p in c.outbox if p[3]==r.SET)
        self.assertEqual(r.Parser().feed(wire,0)[0][3],b'\x01\x00'+bytes(10))
        with self.assertRaises(ValueError):c.apply(1,[0,0,0,0,0],.02)

    def test_apply_caps_and_error_effort(self):
        self.arm();c=self.c;c.apply(1,[.1,0,0,1,0],.01)
        self.assertEqual(c.targets[1],(100,0,0,1000,0))
        with self.assertRaises(ValueError):c.apply(1,[1,0,0,5,0],.02)
        self.assertEqual(c.targets[1],(100,0,0,1000,0))
        with self.assertRaises(ValueError):c.apply(1,[0,0,0,0,0],.101)

    def test_all_14_batch(self):
        for mid in range(1,15): self.arm(mid)
        self.c.step(.01)
        b=r.Parser().feed(self.c.outbox[-1],0)[0][3]
        self.assertEqual(len(b),142);self.assertEqual(b[:2],b'\xff\x3f')

    def test_normal_disable_and_reenable(self):
        self.arm();c=self.c;c.disable(1,.01)
        self.assertNotIn(1,c.targets)
        self.assertNotIn(r.STOP,self.kinds())
        accepted(c,r.DISABLE,1,.02);c.receive(node(1),.03)
        self.assertFalse(c.owns)
        c.enable(1,10,.03)
        self.assertFalse(c.latched)

    def test_stop_pending_enable_is_latched(self):
        self.c.enable(1,10,0);self.c.disable(1,.01)
        self.assertTrue(self.c.latched);self.assertEqual(self.kinds(),[r.STOP])

    def test_ui_freeze(self):
        self.arm();self.c.step(.201)
        self.assertTrue(self.c.latched);self.assertFalse(self.c.owns)
        self.assertIn(r.STOP,self.kinds());self.assertNotIn(r.SET,self.kinds())

    def test_ack_timeout(self):
        c=self.c;c.enable(1,10,0);c.ui_ms=.31;c.step(.31)
        self.assertTrue(c.latched)

    def test_telemetry_timeout(self):
        self.arm();self.c.ui_ms=.51;self.c.step(.51)
        self.assertTrue(self.c.latched)

    def test_readonly_telemetry_loss_closes_without_control(self):
        c = self.c
        c.outbox.clear()
        c.step(.99)
        self.assertFalse(c.owns)
        self.assertEqual(self.kinds(), [r.PING])
        with self.assertRaisesRegex(OSError, '遥测中断'):
            c.step(1.01)
        self.assertNotIn(r.ENABLE, self.kinds())
        self.assertNotIn(r.SET, self.kinds())
        self.assertNotIn(r.STOP, self.kinds())

    def test_duration_requests_disable_not_extend(self):
        self.arm(duration=1);c=self.c;c.ui_ms=1;c.last_rx=1;c.step(1)
        self.assertNotIn(1,c.targets);self.assertIn(r.DISABLE,self.kinds());self.assertFalse(c.latched)
        c.ui_ms=1.31;c.last_rx=1.31;c.step(1.31)
        self.assertTrue(c.latched) # Never pretend a missing stop ACK confirmed.

    def test_stop_clears_unsent(self):
        self.arm();self.c.step(.01);self.c.stop('test')
        self.assertEqual(self.kinds(),[r.STOP])
        self.c.step(.02);self.assertNotIn(r.SET,self.kinds())
        with self.assertRaises(ValueError):self.c.enable(2,10,.02)

    def test_board_latch_clears_all_targets(self):
        self.arm();self.c.receive(state(1),.01)
        self.assertTrue(self.c.latched);self.assertFalse(self.c.owns)

    def test_bad_node_and_wrong_token(self):
        frame=list(node());raw=bytearray(frame[3]);raw[1]=3;frame[3]=bytes(raw)
        with self.assertRaises(ValueError):self.c.receive(frame,0)
        frame=node();self.c.receive((frame[0],frame[1],124,frame[3]),1)
        self.assertEqual(self.c.nodes[1]['received'],0)


class FakeSerial:
    """In-memory UART only, never opens a device path. Provides continuous telemetry."""
    def __init__(self):
        self.parser=r.Parser();self.rx=bytearray();self.writes=[];self.latched=False
        self.phases={i:0 for i in range(1,15)};self.targets={i:r.ZERO for i in range(1,15)}
        self.closed=False;self.online=False;self.last=0;self.fail=False

    def reply(self, frame):self.rx.extend(r.packet(*frame))

    def write(self, wire):
        if self.fail:raise OSError('fake write failure')
        for kind,seq,token,data in self.parser.feed(wire):
            self.writes.append((kind,data))
            if kind==r.HELLO:
                self.online=True
                self.reply((r.INFO,seq,123,r.INFO_DATA.pack(token,bytes(range(12)),160000000,r.SIGNATURE,100,200)))
            elif kind==r.ENABLE:
                self.phases[data[0]]=11
                self.reply((r.ACK,seq,123,bytes((kind,0,data[0]))))
            elif kind==r.DISABLE:
                self.phases[data[0]]=0
                self.reply((r.ACK,seq,123,bytes((kind,0,data[0]))))
            elif kind==r.STOP:
                self.latched=True
                self.phases={i:12 for i in range(1,15)}
                self.reply((r.ACK,seq,123,bytes((kind,0,0))))
        return len(wire)

    def read(self, size):
        time.sleep(.003)
        now=time.monotonic()
        if self.online and now-self.last>.035:
            for mid in range(1,15):self.reply(node(mid,self.phases[mid],stamp=int(now*1000)&0xffffffff))
            self.reply(state(int(self.latched)));self.last=now
        data=bytes(self.rx[:size]);del self.rx[:size];return data

    def close(self):self.closed=True


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.fake=FakeSerial()
        self.w=r.Worker('NOT-A-REAL-PORT',self.temp.name,serial_factory=lambda:self.fake)
        self.events=[]
        self.w.start()
        self.wait_for(lambda:any(k=='node' for k,v in self.events))

    def tearDown(self):
        self.w.close();self.w.thread.join(2)
        self.assertFalse(self.w.thread.is_alive())
        self.temp.cleanup()

    def wait_for(self, pred, timeout=2, heartbeat=True):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if heartbeat:self.w.alive()
            while True:
                try:self.events.append(self.w.events.get_nowait())
                except queue.Empty:break
            if pred():return
            time.sleep(.01)
        self.fail('Timed out; events='+repr(self.events[-5:]))

    def enable(self):
        self.w.submit('enable',1,10)
        self.wait_for(lambda:any(k==r.SET for k,d in self.fake.writes))

    def test_readonly_and_log(self):
        self.assertFalse(any(k in (r.ENABLE,r.SET,r.STOP) for k,d in self.fake.writes))
        self.w.close();self.w.thread.join(2)
        folder=next(Path(self.temp.name).iterdir())
        self.assertTrue((folder/'nodes.csv').exists())
        self.assertTrue((folder/'commands.jsonl').exists())
        self.assertTrue((folder/'session.json').exists())
        self.assertTrue(self.fake.closed)
        self.assertFalse(any(k==r.STOP for k,d in self.fake.writes))

    def test_enable_disable_disconnect(self):
        self.enable();mark=len(self.events)
        self.w.submit('disable',1)
        self.wait_for(lambda:any(k==r.DISABLE for k,d in self.fake.writes))
        # Only an IDLE event after this disable confirms ownership release;
        # the connect-time IDLE frames must not satisfy this wait.
        self.wait_for(lambda:any(k=='node' and v['id']==1 and v['phase']=='IDLE'
                                 for k,v in self.events[mark:]))
        self.w.close();self.w.thread.join(2)
        self.assertFalse(any(k==r.STOP for k,d in self.fake.writes))

    def test_stop_priority_drops_queued_apply(self):
        self.enable();self.w.submit('apply',1,(.01,0,0,1,0));self.w.submit('stop')
        self.wait_for(lambda:any(k==r.STOP for k,d in self.fake.writes))
        index=next(i for i,(k,d) in enumerate(self.fake.writes) if k==r.STOP)
        time.sleep(.07)
        self.assertFalse(any(k in (r.ENABLE,r.SET) for k,d in self.fake.writes[index+1:]))

    def test_ui_freeze_sends_stop(self):
        self.enable()
        self.wait_for(lambda:any(k==r.STOP for k,d in self.fake.writes),heartbeat=False)

    def test_disconnect_with_active_stops(self):
        self.enable();self.w.close();self.w.thread.join(2)
        self.assertTrue(any(k==r.STOP for k,d in self.fake.writes))
        self.assertTrue(self.fake.closed)

    def test_write_failure_exits_and_reports(self):
        self.enable();self.fake.fail=True
        self.wait_for(lambda:any(k=='error' for k,v in self.events))
        self.w.thread.join(2);self.assertFalse(self.w.thread.is_alive())
        self.assertTrue(self.fake.closed)


if __name__=='__main__':unittest.main()
