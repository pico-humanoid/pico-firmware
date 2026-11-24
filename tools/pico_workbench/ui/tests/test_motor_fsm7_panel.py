from collections import deque
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import csv
import unittest
from unittest.mock import patch
from motor_fsm7_panel import SerialSession, can_command, command_description, hardware_banner, parse_motor, parse_state, run_serial


def status(state, *, ready=7, active=0, stopped=7, reason="NONE", source="HARDWARE"):
    return f"# MF7_STATE,state={state},source={source},ready={ready},active={active},stopped={stopped},reason={reason}"


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.commands, self.events = [], []
        self.session = SerialSession(self.commands.append, lambda *event: self.events.append(event), 0)

    def test_simulated_or_malformed_state_never_triggers_output(self):
        self.session.feed("# PICO_BOARD_FSM=1,source=SIMULATED", .1)
        self.session.feed(status("READY", source="SIMULATED"), .15)
        self.session.feed(status("READY", ready=8), .2)
        self.assertFalse(self.session.request("ARM", .25))
        self.session.tick(.5)
        self.session.tick(4.1)
        self.assertTrue(self.session.done)
        self.assertEqual(self.commands, [])

    def test_identification_does_not_arm_and_requires_seven_stopped(self):
        self.session.feed(status("READY", stopped=6), .1)
        self.session.tick(.1)
        self.assertEqual(self.commands, ["KEEP"])
        self.assertFalse(self.session.request("ARM", .1))
        self.session.feed(status("READY"), .2)
        self.assertTrue(self.session.request("ARM", .2))
        self.assertFalse(self.session.request("ARM", .21))
        self.assertEqual(self.commands, ["KEEP", "ARM"])

    def test_debug_returns_to_ready_via_zero_only_and_map_blocks_commands(self):
        debug = parse_state(status("DEBUG_RESERVED"))
        self.assertTrue(can_command(debug, "ZERO"))
        self.assertIn("仍需手动启用", command_description("ZERO", debug))
        self.assertFalse(can_command(debug, "ARM"))
        self.assertFalse(can_command(debug, "DAMP"))
        fault = parse_state(status("FAULT_LOCKED", reason="MAP_UNSET"))
        self.assertFalse(can_command(fault, "ARM"))
        self.assertTrue(can_command(fault, "STOP"))

    def test_debug_resume_waits_for_actual_destination(self):
        debug = status("DEBUG_RESERVED") + ",debug_resume=1"
        self.session.feed(debug, .1)
        self.assertTrue(can_command(parse_state(debug), "ZERO"))
        self.assertTrue(self.session.request("DAMP", .2))
        for timestamp, name in ((.3,"SELF_CHECK"), (.5,"READY"), (1.0,"STARTING"), (1.8,"ZERO_TORQUE")):
            self.session.feed(status(name), timestamp)
            self.assertEqual(self.session.pending, "DAMP")
        self.session.feed(status("DAMPING", active=7, stopped=0), 2.1)
        self.assertIsNone(self.session.pending)

    def test_kd_only_on_new_firmware_in_stable_ready_or_zero(self):
        ready = status("READY")
        zero = status("ZERO_TORQUE", ready=0, active=7, stopped=0)
        damp = status("DAMPING", ready=0, active=7, stopped=0)
        self.session.feed(ready, .1)
        self.assertFalse(self.session.request("KD400", .1))
        self.session.feed(zero + ",target=DAMPING,kd_set_milli=600", .2)
        self.assertFalse(self.session.request("KD400", .2))
        self.session.feed(damp + ",target=DAMPING,kd_set_milli=600", .3)
        self.assertFalse(self.session.request("KD400", .3))
        self.session.feed(ready + ",target=READY,kd_set_milli=600", .4)
        self.assertFalse(self.session.request("KD275", .4))
        self.assertFalse(self.session.request("KD850", .4))
        self.assertTrue(self.session.request("KD400", .4))
        self.session.feed("# MF7_KD,requested_milli=450,set_milli=450,result=ACCEPTED", .5)
        self.assertEqual(self.session.pending, "KD400")
        self.session.feed("# MF7_KD,requested_milli=400,set_milli=400,result=ACCEPTED", .6)
        self.assertIsNone(self.session.pending)
        self.assertIn(("kd", (400, 400, "ACCEPTED")), self.events)
        self.assertEqual(self.commands, ["KD400"])

    def test_disconnect_sends_stop_and_requires_fresh_seven_confirmations(self):
        self.session.feed(status("DAMPING", active=7, stopped=0), .2)
        self.session.tick(.2)
        self.session.close(.3)
        self.session.feed(status("STOPPING", stopped=7), .35)
        self.session.feed(status("FAULT_LOCKED", active=0, stopped=6), .4)
        self.session.tick(.5)
        self.assertEqual(self.commands, ["KEEP", "STOP"])
        self.assertFalse(self.session.done)
        self.assertFalse(self.session.stop_confirmed)
        self.session.feed(status("FAULT_LOCKED"), .6)
        self.assertTrue(self.session.done)
        self.assertTrue(self.session.stop_confirmed)

    def test_disconnect_timeout_cannot_claim_stopped(self):
        self.session.feed(status("READY"), .1)
        self.session.close(.2)
        self.assertFalse(self.session.stop_confirmed)
        self.session.tick(2.8)
        self.assertTrue(self.session.done)
        self.assertIn(("stop", False), self.events)
        self.assertEqual(self.commands, ["STOP"])

    def test_stale_state_requests_stop_and_stops_heartbeat(self):
        self.session.feed(status("DAMPING", active=7, stopped=0), .2)
        self.session.tick(.2)
        self.session.tick(2)
        self.session.tick(2.5)
        self.assertEqual(self.commands, ["KEEP", "STOP"])

    def test_fake_serial_fragmentation_and_log_preservation_on_disconnect(self):
        hello = b"# PICO_MOTOR_FSM7=1,source=HARDWARE\r\n"
        ready = (status("READY") + "\r\n").encode("ascii")
        sample = b"# MF7_MOTOR,bus=2,id=3,vel_mrad_s=-250,torque_mNm=180,estimate_mNm=200,kd_milli=800,t_ms=50\r\n"
        confirmed = (status("FAULT_LOCKED", reason="STOP_REQUEST") + "\r\n").encode("ascii")
        closer = Event()

        class FakeSerial:
            def __init__(self, **_):
                self.parts = deque((hello[:15], hello[15:] + sample + ready))
                self.writes = []

            @property
            def in_waiting(self):
                return len(self.parts[0]) if self.parts else 0

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def write(self, data):
                self.writes.append(data)
                if data == b"STOP\n":
                    self.parts.append(confirmed)
                return len(data)

            def read(self, _):
                if self.parts:
                    data = self.parts.popleft()
                    if data.endswith(ready):
                        closer.set()
                    return data
                raise AssertionError("No more data expected in this scripted session")

        fake = FakeSerial()
        library = SimpleNamespace(Serial=lambda **_: fake, EIGHTBITS=8, PARITY_NONE="N", STOPBITS_ONE=1)
        events = Queue()
        with TemporaryDirectory() as folder, patch("motor_fsm7_panel.serial_api", return_value=(library, None)):
            run_serial("virtual", Queue(), events, closer, Event(), Path(folder))
            directory = next(Path(folder).iterdir())
            self.assertEqual((directory/"board.raw.log").read_bytes(), hello + sample + ready + confirmed)
            self.assertIn("停机确认", (directory/"操作与中文说明.log").read_text(encoding="utf-8-sig"))
            with (directory/"阻尼采样.csv").open(encoding="utf-8-sig", newline="") as file:
                rows = list(csv.reader(file))
            self.assertEqual(rows[1][1:],
                             ["50", "", "2", "3", "-0.250", "0.180", "0.200", "0.800"])
        self.assertEqual(fake.writes, [b"STOP\n"])
        self.assertEqual(list(events.queue)[-1], ("ended", (True, True)))

    def test_banner_and_motor_telemetry(self):
        self.assertTrue(hardware_banner("# PICO_MOTOR_FSM7=1,source=HARDWARE,mode=bench"))
        self.assertFalse(hardware_banner("# PICO_MOTOR_FSM7=1,source=SIMULATED"))
        self.assertEqual(parse_motor("# MF7_MOTOR,bus=2,id=3,vel_mrad_s=-250,torque_mNm=40,estimate_mNm=188,kd_milli=750"),
                         (2, 3, -250, 40, 188, 750))
        self.assertIsNone(parse_motor("# MF7_MOTOR,bus=CAN1,id=3,vel_mrad_s=-250,torque_mNm=40,estimate_mNm=188,kd_milli=750"))
        self.assertIsNone(parse_motor("# MF7_MOTOR,bus=2,id=8,vel_mrad_s=-250,torque_mNm=40,estimate_mNm=188,kd_milli=750"))
        self.assertIsNone(parse_motor("# MF7_MOTOR,bus=2,id=3,iq_mA=150,vel_mrad_s=-25,cmd_mA=2"))


if __name__ == "__main__":
    unittest.main()
