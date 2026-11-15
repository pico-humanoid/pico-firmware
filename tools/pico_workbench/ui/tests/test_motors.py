"""Exercise motor selection, capture and display without opening hardware ports."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog
import engine
import log_model
import platform_tools as tools
import workspace
from test_desk import FakeSerial


def banner(mode="Motors-Read-1M", first=None):
    p = catalog.profile(mode)["cmake_options"]
    return (f"# PICO device-read v1; READ ONLY MOTOR; channel=FDCAN{p.get('PICO_MOTOR_CAN_CHANNEL',1)} device=MOTOR bitrate=1000000 "
            f"count={p['PICO_MOTOR_COUNT']} host_id={p['PICO_MOTOR_HOST_ID']} "
            f"motor1_id={first or p['PICO_MOTOR1_ID']} motor2_id={p['PICO_MOTOR2_ID']} "
            f"motor1_model={p['PICO_MOTOR1_MODEL']} motor2_model={p['PICO_MOTOR2_MODEL']}\n")


class MotorConsoleTests(unittest.TestCase):
    def test_selected_profile_build_and_workspace(self):
        for mode in ("RS10P-Read-1M", "RS00-Read-1M", "Motors-Read-1M"):
            with self.subTest(mode=mode):
                p = catalog.profile(mode)
                command = tools.build_commands(mode)[0]
                self.assertIn("-DPICO_APP=Motor", command)
                self.assertIn("-DPICO_MOTOR_CAN_CHANNEL=1", command)
                self.assertIn("-DPICO_MOTOR_COUNT=" + str(p["cmake_options"]["PICO_MOTOR_COUNT"]), command)
                path, entry = workspace.prepare(mode)
                self.assertEqual(entry.name, "motor_read_app.c")
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(value["settings"]["cmake.configureSettings"]["PICO_APP"], "Motor")

    def test_motor_stream_and_units_preserve_both_devices(self):
        job = engine.Job("board", "Motors-Read-1M", "TEST")
        job.profile["capture_seconds"] = 1
        text = (banner() + "1000,RX,FDCAN1,EXT,DATA,0x110001FD,8,19 70 00 00 00 00 C0 3F\n"
                "# MOTOR,device=MOTOR1,model=RS10P,id=0x01,position_millirad=1500\n"
                "# MOTOR,device=MOTOR2,model=RS00,id=0x02,position_millirad=-250\n"
                "# DEVICE_HEALTH,t_ms=5000,device=MOTOR1,seen=0x0F,valid=0x0F\n"
                "# HEALTH,t_ms=5000,device=MOTOR,tx_submit=20,tx_done=20,bus_off=0\n")
        with tempfile.TemporaryDirectory() as folder, patch.object(engine, "LOGS", Path(folder)):
            manager = engine.Manager()
            clock = iter(range(1000))
            with patch.object(manager, "_serial", return_value=FakeSerial(text.encode())), patch.object(engine.time, "monotonic", side_effect=lambda: next(clock)):
                result = manager._do_stream(job)
        self.assertTrue(result["capture_only"])
        self.assertFalse(result["pass"])
        self.assertEqual(job.telemetry["values"]["MOTOR1"]["position_millirad"], "1500")
        self.assertEqual(job.telemetry["values"]["MOTOR2"]["position_millirad"], "-250")
        rows = log_model.device_values(log_model.parse(text))
        positions = [r for r in rows if r[-1] == "position_millirad"]
        self.assertEqual([(r[0], r[2], r[3]) for r in positions], [("MOTOR1", "1.5", "rad"), ("MOTOR2", "-0.25", "rad")])

    def test_wrong_motor_id_rejected_before_capture_verdict(self):
        job = engine.Job("board", "RS10P-Read-1M", "TEST")
        with tempfile.TemporaryDirectory() as folder, patch.object(engine, "LOGS", Path(folder)):
            manager = engine.Manager()
            with patch.object(manager, "_serial", return_value=FakeSerial(banner("RS10P-Read-1M", first="127").encode())):
                with self.assertRaisesRegex(ValueError, "ID"):
                    manager._do_stream(job)

    def test_old_can3_motor_firmware_is_rejected(self):
        job = engine.Job("board", "RS00-Read-1M", "TEST")
        text = banner("RS00-Read-1M").replace("channel=FDCAN1", "channel=FDCAN3")
        with tempfile.TemporaryDirectory() as folder, patch.object(engine, "LOGS", Path(folder)):
            manager = engine.Manager()
            with patch.object(manager, "_serial", return_value=FakeSerial(text.encode())):
                with self.assertRaisesRegex(ValueError, "CAN1"):
                    manager._do_stream(job)
