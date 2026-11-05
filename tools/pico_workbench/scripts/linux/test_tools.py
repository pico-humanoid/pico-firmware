"""Software-only protocol and pseudo-terminal checks; never a hardware PASS."""
import os
from pathlib import Path
import pty
import subprocess
import sys
import tempfile
import threading
import unittest
from usbcan_test import Decoder, Frame, assess, data_packet, settings_packet


class ProtocolTests(unittest.TestCase):
    def test_official_configuration_vector(self):
        self.assertEqual(settings_packet().hex(), 'aa55120101000000000000000000010000000015')
        self.assertEqual(len(settings_packet()), 20)

    def test_exact_transmit_frame(self):
        self.assertEqual(data_packet(0x321, bytes.fromhex('00 88 77 66 55 44 33 22')).hex(), 'aac82103008877665544332255')

    def test_split_stream_with_delimiters_in_payload(self):
        payload = bytes.fromhex('AA 55 00 11 22 33 44 55')
        raw = data_packet(0x123, payload) + data_packet(0x321, b'\x55')
        decoder = Decoder()
        frames = []
        for value in raw:
            frames.extend(decoder.feed(bytes([value])))
        self.assertEqual([(x.identifier, x.data) for x in frames], [(0x123, payload), (0x321, b'\x55')])
        self.assertEqual(decoder.malformed, 0)

    def test_commands_are_not_data(self):
        decoder = Decoder()
        self.assertEqual(decoder.feed(settings_packet()), [])
        self.assertEqual(decoder.malformed, 0)

    def test_bad_serial_frame_is_rejected(self):
        decoder = Decoder()
        self.assertEqual(decoder.feed(b'\xAA\xC8\x23\x01' + bytes(8) + b'\x00'), [])
        self.assertGreater(decoder.malformed, 0)

    def test_full_return_sequence_and_negative_cases(self):
        valid = [Frame(0x123, bytes([n]) + bytes.fromhex('22 33 44 55 66 77 88')) for n in range(100)]
        self.assertTrue(assess(valid, 100)['pass'])
        for bad, sent, malformed in [(valid[:-1], 100, 0), (valid + valid[:1], 100, 0), (valid, 99, 0), (valid, 100, 1), (valid + [Frame(0x123, b'bad')], 100, 0), (valid + [Frame(0x321, b'')], 100, 0)]:
            with self.subTest(sent=sent, count=len(bad), malformed=malformed):
                self.assertFalse(assess(bad, sent, malformed)['pass'])

    def test_capture_pty_and_independent_log_check(self):
        master, slave = pty.openpty()
        try:
            with tempfile.TemporaryDirectory(prefix='pico-synthetic-') as out:
                process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('capture.py')), '--port', os.ttyname(slave), '--seconds', '3', '--output-dir', out], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                ready = process.stdout.readline()
                self.assertIn('115200', ready)
                lines = ['# mode=INTERNAL_LOOPBACK', 't_ms,event,format,id,dlc,data']
                for n in range(100):
                    for event in ('TX_SUBMIT', 'TX_DONE', 'RX'):
                        lines.append(f'{2000+n*100},{event},STD,0x123,8,{n:02X} 22 33 44 55 66 77 88')
                summary = {'tx_submit':100,'tx_done':100,'rx_unique':100,'rx_missing':0,'rx_duplicate':0,'rx_invalid':0,'tx_submit_failed':0,'rx_fifo_lost_events':0,'rx_queue_dropped':0,'rx_read_failed':0,'tx_event_lost_events':0,'bus_off_events':0,'fatal':0,'tec':0,'rec':0}
                lines.append('# RESULT=PASS ' + ' '.join(f'{k}={v}' for k,v in summary.items()))
                def feed():
                    remaining = ('\n'.join(lines)+'\n').encode()
                    while remaining:
                        remaining = remaining[os.write(master, remaining):]
                sender = threading.Thread(target=feed, daemon=True)
                sender.start()
                stdout, _ = process.communicate(timeout=10)
                sender.join(timeout=1)
                self.assertEqual(process.returncode, 0, stdout)
                self.assertIn('日志完整性复核：通过', stdout)
                self.assertEqual(len(list(Path(out).glob('*.check.json'))), 1)
        finally:
            os.close(master)
            os.close(slave)


if __name__ == '__main__':
    unittest.main(verbosity=2)
