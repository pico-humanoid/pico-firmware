import unittest
from unittest.mock import patch

from usb_can_bms_read import (QUERY_IDS, Session, bms_adapter_config, crc16,
                              decode_reply, query_packet)
from usb_can_power_probe import extract_frames


def reply(cid, words=(4700, 0, 1000), order='big'):
    data = b''.join(x.to_bytes(2, 'big') for x in words)
    data += crc16(data).to_bytes(2, order)
    return (cid, False, False, 8, data)


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakePort:
    def __init__(self, clock, mode='ok'):
        self.clock, self.mode = clock, mode
        self.pending = bytearray()
        self.writes = []

    def reset_input_buffer(self):
        self.pending.clear()

    def write(self, raw):
        self.writes.append(raw)
        if raw != bms_adapter_config() and self.mode != 'timeout':
            cid = int.from_bytes(raw[2:4], 'little')
            words = (4700, 65526, 1000) if cid == 0x100 else (1, 2, 50)
            data = reply(cid, words)[4]
            if self.mode == 'crc':
                data = data[:-1] + bytes([data[-1] ^ 1])
            self.pending.extend(b'\xaa\xc8' + cid.to_bytes(2, 'little') + data + b'\x55')
        return len(raw)

    def flush(self):
        pass

    @property
    def in_waiting(self):
        return len(self.pending)

    def read(self, count):
        self.clock.now += 0.001
        # Deliberately split the response into one-byte chunks.
        value = bytes(self.pending[:1])
        del self.pending[:1]
        return value


class BmsTests(unittest.TestCase):
    def test_standard_configuration(self):
        p = bms_adapter_config()
        self.assertEqual(p.hex(' '), 'aa 55 12 03 01 00 00 00 00 00 00 00 00 00 01 00 00 00 00 17')
        self.assertEqual(p[-1], sum(p[2:19]) & 255)

    def test_only_allowlisted_remote_frames_no_payload(self):
        for cid in QUERY_IDS:
            for dlc in (0, 8):
                p = query_packet(cid, dlc)
                self.assertEqual(len(p), 5)
                self.assertEqual(extract_frames(bytearray(p)), [(cid, False, True, dlc, b'')])
        self.assertEqual(query_packet(0x100).hex(' '), 'aa d8 00 01 55')
        for cid, dlc in [(0x104, 8), (0x080000AA, 8), (0x100, 7)]:
            with self.assertRaises(ValueError):
                query_packet(cid, dlc)

    def test_crc_known_vector(self):
        self.assertEqual(crc16(b'123456789'), 0x4B37)

    def test_decoding_all_ids_and_negative_current(self):
        d = decode_reply(reply(0x100, (4700, 65526, 1000)), 0x100)
        self.assertEqual((d['voltage_v'], d['current_a'], d['remaining_capacity_ah']), (47, -0.1, 10))
        self.assertEqual(decode_reply(reply(0x101, (2000, 20, 50)), 0x101)['soc_percent'], 50)
        self.assertEqual(decode_reply(reply(0x102, (1, 2, 3)), 0x102)['protection'], '0x0003')
        self.assertTrue(decode_reply(reply(0x103, (3, 0, 1)), 0x103)['discharge_mos_on'])
        self.assertEqual(decode_reply(reply(0x105, (2981, 2731, 2631)), 0x105)['temperature_c'], [25, 0, -10])

    def test_reject_wrong_shape_soc_crc_and_no_auto_endian_switch(self):
        f = reply(0x100)
        bad = [(0x101, *f[1:]), (f[0], True, *f[2:]), (f[0], False, True, *f[3:]),
               (f[0], False, False, 7, f[4]), (f[0], False, False, 8, f[4][:-1])]
        for frame in bad:
            with self.assertRaises(ValueError):
                decode_reply(frame, 0x100)
        with self.assertRaises(ValueError):
            decode_reply(reply(0x101, (1, 2, 101)), 0x101)
        f = reply(0x100, order='little')
        with self.assertRaisesRegex(ValueError, 'opposite_byte_order_matches=True'):
            decode_reply(f, 0x100)
        self.assertTrue(decode_reply(f, 0x100, 'little')['crc_ok'])

    def session(self, mode, cycles):
        clock, events = Clock(), []
        port = FakePort(clock, mode)
        with patch('usb_can_bms_read.time', clock):
            session = Session(port, lambda event, **kw: events.append(dict(event=event, **kw)), 'big')
            result = session.run(cycles, 8, 0.2, 0.7)
            summary = session.summary(result)
        return port, events, summary

    def test_fragmented_65_cycles_60s_window(self):
        port, events, s = self.session('ok', 65)
        self.assertEqual(s['result'], 'READ_WINDOW_OK')
        self.assertEqual((s['submitted'], s['matched']), (325, 325))
        self.assertTrue(s['stable_60s_window_pass'])
        self.assertEqual(set(s['replies_by_id'].values()), {65})
        self.assertEqual(len(port.writes), 326)
        self.assertTrue(all(raw[1] == 0xD8 for raw in port.writes[1:]))
        self.assertEqual(sum(x['event'] == 'can' for x in events), 325)

    def test_short_window_not_stability_pass(self):
        _, _, s = self.session('ok', 3)
        self.assertEqual(s['result'], 'READ_WINDOW_OK')
        self.assertFalse(s['stable_60s_window_pass'])

    def test_timeout_stops_no_retry(self):
        port, _, s = self.session('timeout', 65)
        self.assertEqual(s['result'], 'READ_TIMEOUT')
        self.assertEqual((s['submitted'], s['matched']), (1, 0))
        self.assertEqual(len(port.writes), 2)
        self.assertFalse(s['stable_60s_window_pass'])

    def test_bad_crc_stops_no_retry(self):
        port, _, s = self.session('crc', 65)
        self.assertEqual(s['result'], 'INVALID_REPLY')
        self.assertEqual(s['invalid_replies'], 1)
        self.assertEqual((s['submitted'], s['matched']), (1, 0))
        self.assertEqual(len(port.writes), 2)


if __name__ == '__main__':
    unittest.main()
