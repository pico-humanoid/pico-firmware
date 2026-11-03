import unittest
from usb_can_power_probe import adapter_config, extract_frames
from usb_can_power_baud import baud_write, matches


class BaudTests(unittest.TestCase):
    def test_adapter_500k_is_code3_not_board_code2(self):
        p = adapter_config(500000)
        self.assertEqual(p[:5], bytes.fromhex('aa 55 12 03 02'))
        self.assertEqual(p[13:15], b'\0\1')
        self.assertEqual(p[-1], sum(p[2:19]) & 255)
        with self.assertRaises(ValueError):
            adapter_config(250000)

    def test_exact_board_write(self):
        raw = baud_write(0xAA)
        self.assertEqual(raw.hex(), 'aae8aa000008016000000200000055')
        self.assertEqual(extract_frames(bytearray(raw)), [
            (0x080000AA, True, False, 8, bytes.fromhex('01 60 00 00 02 00 00 00'))])
        with self.assertRaises(ValueError):
            baud_write(256)

    def test_match_rejects_echo_other_source_and_index(self):
        data = bytes.fromhex('01 60 00 00 02 00 00 00')
        self.assertTrue(matches((0x07AA0000, True, False, 8, data), 0xAA, 7, 0x6001))
        for cid, ext, remote, dlc in [(0x070000AA, True, False, 8),
                                     (0x07AB0000, True, False, 8),
                                     (0x07AA0000, False, False, 8),
                                     (0x07AA0000, True, True, 8),
                                     (0x07AA0000, True, False, 7)]:
            self.assertFalse(matches((cid, ext, remote, dlc, data), 0xAA, 7, 0x6001))
        self.assertFalse(matches((0x07AA0000, True, False, 8, data), 0xAA, 7, 0x6002))


if __name__ == '__main__':
    unittest.main()
