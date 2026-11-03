import unittest
import struct
from usb_can_power_read import requests, packet, decode
from usb_can_power_probe import extract_frames


class ReadTests(unittest.TestCase):
    def test_allowlist(self):
        plan = requests(0xAA)
        self.assertEqual(len(plan), 11)
        self.assertNotIn(0x6003, [p[4] for p in plan])
        for _, kind, data, _, _ in plan:
            frames = extract_frames(bytearray(packet(0xAA, kind, data)))
            self.assertEqual(len(frames), 1)
            self.assertIn(frames[0][0] >> 24, (2, 7))
        for kind, data in [(8, bytes(8)), (1, bytes(8)), (7, bytes.fromhex('03 60') + bytes(6)), (2, b'\x01' + bytes(7))]:
            with self.assertRaises(ValueError):
                packet(0xAA, kind, data)

    def test_parameter_decode(self):
        self.assertEqual(decode(7, bytes.fromhex('01 60 00 00 01 00 00 00'))['value_u8'], 1)
        self.assertEqual(decode(7, bytes.fromhex('01 80 00 00') + struct.pack('<f', 80))['value_float32_le_candidate'], 80)

    def test_status_uncertainty(self):
        d = decode(3, bytes.fromhex('c0 12 00 00 19 00 00 00'))
        self.assertEqual(d['temperature_c'], 25)
        self.assertEqual(d['status_byte_order'], 'UNCONFIRMED')
        self.assertEqual(d['little_candidate']['battery_v'], 48)


if __name__ == '__main__':
    unittest.main()
