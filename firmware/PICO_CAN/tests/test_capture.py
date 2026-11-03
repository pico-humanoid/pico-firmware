"""Real pyserial + Linux PTY smoke tests; no physical serial port is used."""
import json
import os
from pathlib import Path
import pty
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "capture_device.py"


class CaptureTest(unittest.TestCase):
    def run_capture(self, payload=None, idle=False):
        with tempfile.TemporaryDirectory() as temp:
            master, slave = pty.openpty()
            path = Path(temp) / "board.csv"
            try:
                process = subprocess.Popen(
                    [sys.executable, str(SCRIPT), "--port", os.ttyname(slave),
                     "--output", str(path), "--duration", "2" if idle else "0.4",
                     "--idle-timeout", "0.2" if idle else "1"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self.assertIn("READY", process.stdout.readline())
                if payload is not None:
                    os.write(master, payload)
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 1 if idle else 0, stderr)
                self.assertEqual(path.read_bytes(), payload or b"")
                meta = json.loads(Path(str(path) + ".json").read_text())
                self.assertEqual(meta["reason"], "idle_timeout" if idle else "duration_complete")
                self.assertTrue(meta["capture_only_not_device_pass"])
                self.assertEqual(meta["bytes"], len(payload or b""))
                self.assertIn("NOT a device PASS", stdout)
            finally:
                os.close(master)
                os.close(slave)

    def test_preserves_bytes(self):
        self.run_capture(b"# PICO device-read\r\n1,RX,FDCAN1,STD,DATA,0x100,8,00\r\npartial")

    def test_idle_is_failure(self):
        self.run_capture(idle=True)

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "existing.csv"
            path.write_bytes(b"preserve")
            result = subprocess.run([sys.executable, str(SCRIPT), "--port", "/no/device",
                                     "--output", str(path)], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_bytes(), b"preserve")

    def test_open_failure_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "failed.csv"
            result = subprocess.run([sys.executable, str(SCRIPT), "--port", "/no/such/pico/device",
                                     "--output", str(path)], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(Path(str(path) + ".json").read_text())["reason"], "serial_or_io_error")


if __name__ == "__main__":
    unittest.main()
