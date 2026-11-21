import math
from pathlib import Path
import struct
import tempfile
import unittest
from trajectory_plot import TrajectoryData

def frame(stamp,event,ident,index,value):
    data=index.to_bytes(2,'little')+b'\0\0'+struct.pack('<f',value)
    return f'{stamp},{event},FDCAN1,EXT,DATA,0x{ident:08X},8,'+data.hex(' ').upper()

class TrajectoryPlotTests(unittest.TestCase):
    def test_separate_nonzero_origins_and_submitted_targets(self):
        data=TrajectoryData()
        data.feed(frame(100,'RX',0x110001FD,0x7019,5))
        data.feed(frame(100,'RX',0x110002FD,0x7019,-2))
        data.feed(frame(200,'TX_SUBMIT',0x1200FD01,0x7016,5+math.radians(5)))
        data.feed(frame(200,'TX_SUBMIT',0x1200FD02,0x7016,-2-math.radians(3)))
        data.feed(frame(300,'RX',0x110001FD,0x7019,5+math.radians(4)))
        self.assertAlmostEqual(data.points[1,'target'][-1][1],5,places=3)
        self.assertAlmostEqual(data.points[2,'target'][-1][1],-3,places=3)
        self.assertAlmostEqual(data.points[1,'actual'][-1][1],4,places=3)
        self.assertEqual(data.points[2,'actual'][-1][1],0)
    def test_no_invented_data_invalid_frames_and_reset(self):
        data=TrajectoryData()
        self.assertFalse(data.feed(frame(1,'RX',0x110001FD,0x7019,float('nan'))))
        self.assertEqual(data.rows(),[])
        data.feed(frame(10,'RX',0x110001FD,0x7019,1))
        data.feed('# DUAL_POSITION_PHASE,id=1,state=STOPPING,reason=HOST_TIMEOUT')
        self.assertEqual(data.events[-1][1],'ID1 HOST_TIMEOUT')
        data.feed('# PICO_MOTOR_DUAL_POSITION=1;')
        self.assertEqual(data.rows(),[]);self.assertFalse(data.origin)
    def test_csv_contains_received_samples_only(self):
        data=TrajectoryData();data.feed(frame(10,'RX',0x110001FD,0x7019,1))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'curve.csv';data.save(path)
            lines=path.read_text(encoding='utf-8-sig').splitlines()
            self.assertEqual(len(lines),2);self.assertIn('10,1,actual,0.0',lines[1])
