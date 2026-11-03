import unittest
from usb_can_power_probe import adapter_config, version_query, extract_frames


class CodecTests(unittest.TestCase):
    def test_config(self):
        p = adapter_config()
        self.assertEqual(len(p), 20)
        self.assertEqual(p[:5], bytes.fromhex('aa 55 12 01 02'))
        self.assertEqual(p[13:15], b'\0\1')
        self.assertEqual(p[-1], sum(p[2:19]) & 255)

    def test_query(self):
        self.assertEqual(version_query(0xAA), bytes.fromhex('aa e8 aa 00 00 05 00 00 00 00 00 00 00 00 55'))
        with self.assertRaises(ValueError):
            version_query(256)

    def test_official_examples(self):
        p = bytearray.fromhex('aa c8 23 01 11 22 33 44 55 66 77 88 55 aa e2 21 30 03 01 11 22 55')
        f = extract_frames(p)
        self.assertEqual(f[0], (0x123, False, False, 8, bytes.fromhex('11 22 33 44 55 66 77 88')))
        self.assertEqual(f[1], (0x1033021, True, False, 2, b'\x11\x22'))
        self.assertFalse(p)

    def test_fragment_noise_and_reply(self):
        raw = bytes.fromhex('aa e8 00 00 aa 05') + b'PBV1.00\0' + b'\x55'
        p = bytearray(b'noise' + raw[:8])
        self.assertEqual(extract_frames(p), [])
        p.extend(raw[8:])
        self.assertEqual(extract_frames(p)[0][0], 0x05AA0000)


if __name__ == '__main__':
    unittest.main()
