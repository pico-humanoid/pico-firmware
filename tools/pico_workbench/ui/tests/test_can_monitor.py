import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile
import queue
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from can_monitor_model import ATDecoder,describe

def packet(identifier,data):
    return b'AT'+((identifier<<3)|4).to_bytes(4,'big')+bytes([len(data)])+data+b'\r\n'

class MonitorDecodeTests(unittest.TestCase):
    def test_observed_identity_is_not_parameter_response(self):
        frames=ATDecoder().feed(bytes.fromhex('41 54 00 03 FF F4 08 69 07 38 00 1C 44 39 16 0D 0A'))
        self.assertEqual(frames,[(0x7FFE,bytes.fromhex('69 07 38 00 1C 44 39 16'))])
        origin,meaning=describe(*frames[0])
        self.assertIn('身份回复',origin)
        self.assertIn('UID=69 07 38 00 1C 44 39 16',meaning)
    def test_fragmentation_and_two_directions(self):
        decoder=ATDecoder();raw=packet(0x1100FD7F,bytes.fromhex('19 70 00 00 00 00 00 00'))+packet(0x11007FFD,bytes.fromhex('19 70 00 00 00 00 C0 3F'))
        frames=[]
        for byte in raw:frames+=decoder.feed(bytes([byte]))
        self.assertEqual([f[0] for f in frames],[0x1100FD7F,0x11007FFD])
        self.assertIn('主机FD',describe(*frames[0])[0]);self.assertIn('电机7F',describe(*frames[1])[0])
        self.assertIn('1.5 rad',describe(*frames[1])[1])
    def test_payload_delimiters_are_not_line_breaks(self):
        payload=b'AT\r\n\0\1\2\3';decoder=ATDecoder()
        self.assertEqual(decoder.feed(b'junk'+packet(0x1234567,payload)),[(0x1234567,payload)])
        self.assertEqual(decoder.discarded,4)
    def test_invalid_dlc_and_bad_footer_resynchronize(self):
        decoder=ATDecoder();raw=b'AT\0\0\0\4\xff'+b'AT\0\0\0\4\0XX'+packet(0x1100FD7F,b'')
        self.assertEqual(decoder.feed(raw),[(0x1100FD7F,b'')]);self.assertGreater(decoder.discarded,0)
    def test_unsupported_flags_and_noise_are_preserved_as_counts(self):
        decoder=ATDecoder()
        self.assertEqual(decoder.feed(b'AT\0\0\0\0\0\r\n'),[])
        self.assertEqual(decoder.unsupported,1)
        decoder.feed(b'x'*100000+b'A');self.assertEqual(decoder.buffer,b'A')
    def test_nonfinite_and_short_payload_not_interpreted(self):
        self.assertNotIn(' = ',describe(0x11007FFD,bytes.fromhex('19 70 00 00 00 00 80 7F'))[1])
        self.assertEqual(describe(0x11007FFD,b'\x19')[1],'类型 17')

    def test_reader_never_writes_serial_and_preserves_logs(self):
        from can_monitor import CANMonitor
        monitor=CANMonitor.__new__(CANMonitor)
        monitor.events=queue.Queue();monitor.stop_event=threading.Event()
        expected=packet(0x1100FD7F,bytes.fromhex('19 70 00 00 00 00 00 00'))
        class ReadOnlySerial:
            in_waiting=100
            def __init__(self,**kwargs):pass
            def open(self):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def write(self,*args):raise AssertionError('Monitor must never write serial')
            def read(self,n):monitor.stop_event.set();return expected
        with tempfile.TemporaryDirectory() as directory:
            with patch('can_monitor.serial.Serial',ReadOnlySerial),patch('can_monitor.project_root',return_value=Path(directory)):
                monitor.read('FAKE',921600)
            csvs=list(Path(directory).rglob('frames.csv'));self.assertEqual(len(csvs),1)
            self.assertIn('0x1100FD7F',csvs[0].read_text(encoding='utf-8-sig'))
            self.assertIn(expected.hex(' '),next(Path(directory).rglob('raw.jsonl')).read_text())
            self.assertTrue(any(event[0]=='frame' for event in monitor.events.queue))

if __name__=='__main__':unittest.main()
