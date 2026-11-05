"""Regression checks use temporary logs and mock serial devices only."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine
import platform_tools as tools
import server


def board_log(external=False, duplicate=False):
    lines = ["# PICO G474 CAN bring-up; timestamps are board uptime milliseconds",
             "# mode=" + ("EXTERNAL_NORMAL" if external else "INTERNAL_LOOPBACK"),
             "t_ms,event,format,id,dlc,data"]
    for seq in range(100):
        tx = f"{seq:02X} 22 33 44 55 66 77 88"
        rx = f"{seq:02X} 88 77 66 55 44 33 22" if external else tx
        lines += [f"{2000+100*seq},TX_SUBMIT,STD,0x123,8,{tx}",
                  f"{2001+100*seq},TX_DONE,STD,0x123,8,{tx}",
                  f"{2002+100*seq},RX,STD,{'0x321' if external else '0x123'},8,{rx}"]
    if duplicate:
        lines.append(lines[-1])
    lines.append("# RESULT=PASS tx_submit=100 tx_done=100 rx_unique=100 rx_missing=0 "
                 "rx_duplicate=0 rx_invalid=0 tx_submit_failed=0 rx_fifo_lost_events=0 "
                 "rx_queue_dropped=0 rx_read_failed=0 tx_event_lost_events=0 bus_off_events=0 fatal=0 tec=0 rec=0")
    return "\n".join(lines) + "\n"


class FakeSerial:
    def __init__(self, data):
        self.data = bytearray(data)
        self.closed = False
        self.writes = []

    @property
    def in_waiting(self):
        return len(self.data)

    def read(self, count):
        data = bytes(self.data[:count])
        del self.data[:count]
        return data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def reset_input_buffer(self):
        pass

    def write(self, value):
        self.writes.append(value)

    def flush(self):
        pass


class CaptureTests(unittest.TestCase):
    def capture(self, text, mode="Loopback"):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(engine, "LOGS", Path(folder)), patch.object(engine, "RECORDS", Path(folder)):
                manager = engine.Manager()
                job = engine.Job("board", mode, "test")
                device = FakeSerial(text.encode())
                with patch.object(manager, "_serial", return_value=device):
                    result = manager._do_board(job)
                self.assertTrue(device.closed)
                return result, (Path(folder) / job.files[0]).read_text(encoding="utf-8")

    def test_complete_loopback(self):
        result, raw = self.capture(board_log())
        self.assertTrue(result["pass"])
        self.assertIn("# RESULT=PASS", raw)

    def test_complete_external(self):
        result, _ = self.capture(board_log(True), "External")
        self.assertTrue(result["pass"])

    def test_duplicate_rejected_even_if_board_claims_pass(self):
        result, _ = self.capture(board_log(duplicate=True))
        self.assertFalse(result["pass"])

    def test_missing_frame_rejected(self):
        text = board_log().replace("2002,RX,STD,0x123,8,00 22 33 44 55 66 77 88\n", "")
        result, _ = self.capture(text)
        self.assertFalse(result["pass"])

    def test_mode_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "固件"):
            self.capture(board_log(True), "Loopback")

    def test_reset_keeps_only_latest_capture_segment(self):
        prefix = board_log().split("# RESULT=")[0]
        result, raw = self.capture(prefix + board_log())
        self.assertTrue(result["pass"])
        self.assertEqual(raw.count("t_ms,event"), 1)

    def test_cancel_releases_serial_and_never_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(engine, "LOGS", Path(folder)), patch.object(engine, "RECORDS", Path(folder)):
                manager = engine.Manager()
                job = engine.Job("board", "Loopback", "test")
                job.cancel.set()
                device = FakeSerial(b"")
                with patch.object(manager, "_serial", return_value=device), self.assertRaises(engine.Cancelled):
                    manager._do_board(job)
                self.assertTrue(device.closed)
                self.assertIsNone(job.result)

    def test_usbcan_packets_and_independent_check(self):
        frames = [engine.data_packet(0x123, bytes([seq]) + bytes.fromhex("22 33 44 55 66 77 88"))
                  for seq in range(100)]
        device = FakeSerial(b"".join(frames))
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(engine, "LOGS", Path(folder)), patch.object(engine, "RECORDS", Path(folder)):
                manager = engine.Manager()
                job = engine.Job("usbcan", "External", "test")
                ticks = iter(i * .01 for i in range(10000))
                with patch.object(manager, "_serial", return_value=device), patch.object(engine.time, "sleep"), patch.object(engine.time, "monotonic", side_effect=lambda: next(ticks)):
                    result = manager._do_usbcan(job)
                self.assertTrue(result["pass"])
                self.assertEqual(len(device.writes), 101)
                decoder = engine.Decoder()
                actual = [frame for raw in device.writes[1:] for frame in decoder.feed(raw)]
                self.assertEqual([f.identifier for f in actual], [0x321] * 100)
                self.assertEqual([f.data[0] for f in actual], list(range(100)))

    def test_usbcan_no_returns_is_not_pass(self):
        self.assertFalse(engine.assess([], 100)["pass"])

    def test_usbcan_read_timeout_does_not_block_100ms_send_schedule(self):
        manager = engine.Manager()
        job = engine.Job("usbcan", "External", "test")
        with patch.object(engine.serial, "Serial") as constructor:
            manager._serial(job, 2000000)
            self.assertLessEqual(constructor.call_args.kwargs["timeout"], 0.01)


class PlatformAndTaskTests(unittest.TestCase):
    def test_platform_build_dirs_are_separate(self):
        with patch.object(tools, "WINDOWS", True):
            windows = tools.build_dir("External")
        with patch.object(tools, "WINDOWS", False):
            linux = tools.build_dir("External")
        self.assertNotEqual(windows, linux)
        self.assertIn("UI-Linux-External", str(linux))

    def test_linux_commands_use_native_paths_no_windows_preset(self):
        with patch.object(tools, "WINDOWS", False), patch.object(tools, "tool", side_effect=lambda n: "/opt/tools/" + n):
            commands = tools.build_commands("External")
        self.assertEqual(commands[0][0], "/opt/tools/cmake")
        self.assertIn("-DPICO_EXTERNAL_CAN=ON", commands[0])
        self.assertFalse(any("--preset" in value for cmd in commands for value in cmd))

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            tools.build_dir("External; command")

    def test_operations_cannot_share_a_serial_port(self):
        manager = engine.Manager()
        job = engine.Job("board", "External", "TEST")
        manager.jobs[job.id] = job
        with patch.object(engine, "ports", return_value=[{"device": "TEST"}]):
            with self.assertRaisesRegex(ValueError, "使用"):
                manager.start("usbcan", "External", "TEST")

    def test_flash_cannot_interrupt_running_capture(self):
        manager = engine.Manager()
        job = engine.Job("board", "Loopback")
        manager.jobs[job.id] = job
        with self.assertRaises(ValueError):
            manager.start("flash", "Loopback")


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server(0)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:" + str(cls.httpd.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def fetch(self, path, body=None, extra=None):
        headers = extra or {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.url + path,
                  data=None if body is None else json.dumps(body).encode(), headers=headers)
        return urllib.request.urlopen(request, timeout=3)

    def test_dashboard_served(self):
        with self.fetch("/") as response:
            self.assertIn("开发控制台", response.read().decode())
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_csrf_required_for_mutations(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.fetch("/api/start", {"kind": "build", "mode": "Loopback"})
        self.assertEqual(context.exception.code, 403)

    def test_cross_site_origin_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.fetch("/api/state", extra={"Origin": "https://untrusted.invalid"})
        self.assertEqual(context.exception.code, 403)

    def test_invalid_action_cannot_start_arbitrary_process(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.fetch("/api/start", {"kind": "anything", "mode": "Loopback"}, {"X-Pico-Token": server.TOKEN})
        self.assertEqual(context.exception.code, 400)

    def test_log_path_traversal_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.fetch("/download/../CMakeLists.txt")
        self.assertEqual(context.exception.code, 400)

    def test_only_allowed_sources_readable(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.fetch("/api/source?name=../../outside")

    def test_generated_sources_cannot_be_written(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.fetch("/api/source", {"name": "Core/Src/main.c", "text": "changed"},
                       {"X-Pico-Token": server.TOKEN})

    def test_revision_conflict_prevents_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "App/can_bringup.c"
            source.parent.mkdir()
            source.write_text("original", encoding="utf-8")
            with patch.object(tools, "ROOT", Path(folder)):
                with self.assertRaises(urllib.error.HTTPError):
                    self.fetch("/api/source", {"name": "App/can_bringup.c", "text": "new", "revision": "stale"},
                               {"X-Pico-Token": server.TOKEN})
            self.assertEqual(source.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
