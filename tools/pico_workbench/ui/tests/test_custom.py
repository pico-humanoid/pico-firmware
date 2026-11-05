import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog
import engine
import platform_tools as tools
from test_desk import FakeSerial


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "CMakeLists.txt").write_text("project(Test)")
        self.state_patch = patch.object(catalog, "STATE", self.root / "ui/state")
        self.root_patch = patch.object(catalog, "ROOT", self.root)
        self.tool_root_patch = patch.object(tools, "ROOT", self.root)
        self.state_patch.start()
        self.root_patch.start()
        self.tool_root_patch.start()

    def tearDown(self):
        self.state_patch.stop()
        self.root_patch.stop()
        self.tool_root_patch.stop()
        self.folder.cleanup()

    def create(self, **kwargs):
        return catalog.save_profile(dict(name="My CAN experiment", project_dir=str(self.root),
                                         toolchain="", **kwargs))

    def test_add_update_delete_persists(self):
        item = self.create()
        self.assertEqual(catalog.profile(item["id"])["name"], "My CAN experiment")
        item["name"] = "Renamed"
        catalog.save_profile(item)
        self.assertEqual(catalog.profile(item["id"])["name"], "Renamed")
        catalog.delete_profile(item["id"])
        with self.assertRaises(ValueError):
            catalog.profile(item["id"])

    def test_inside_project_path_stored_portably(self):
        self.assertEqual(self.create()["project_dir"], ".")

    def test_builtin_not_overwritten_or_deleted(self):
        with self.assertRaises(ValueError):
            self.create(id="Loopback")
        with self.assertRaises(ValueError):
            catalog.delete_profile("External")

    def test_missing_project_rejected(self):
        with self.assertRaises(ValueError):
            catalog.save_profile({"name": "x", "project_dir": str(self.root / "missing")})

    def test_invalid_option_and_path_rejected(self):
        with self.assertRaises(ValueError):
            self.create(cmake_options={"--bad-option": "x"})
        with self.assertRaises(ValueError):
            self.create(elf_name="../escape.elf")

    def test_custom_build_uses_selected_project_and_parameters(self):
        item = self.create(cmake_options={"PICO_APP": "BMS", "PICO_DEVICE_BITRATE": 500000})
        with patch.object(tools, "tool", side_effect=lambda n: "/tools/" + n):
            commands = tools.build_commands(item["id"])
        self.assertEqual(commands[0][commands[0].index("-S") + 1], str(self.root))
        self.assertIn("-DPICO_APP=BMS", commands[0])
        self.assertIn("-DPICO_DEVICE_BITRATE=500000", commands[0])

    def test_notes_and_conclusion_do_not_replace_machine_result(self):
        path = self.root / "logs/ui_records/original.json"
        path.parent.mkdir(parents=True)
        raw = {"id": "original", "status": "fail", "result": {"pass": False}}
        path.write_text(json.dumps(raw))
        catalog.annotate({"id": "original", "title": "Retest", "notes": "Hardware replaced",
                          "conclusion": "pass"})
        self.assertEqual(json.loads(path.read_text())["status"], "fail")
        self.assertEqual(catalog.annotations()["original"]["conclusion"], "pass")

    def test_archive_and_restore_retains_raw_record(self):
        path = self.root / "logs/ui_records/original.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        catalog.annotate({"id": "original", "archived": True})
        self.assertTrue(path.exists())
        catalog.annotate({"id": "original", "archived": False})
        self.assertFalse(catalog.annotations()["original"]["archived"])

    def test_manual_record_is_recorded_not_automatic_pass(self):
        value = catalog.new_record({"mode": "Loopback", "title": "Power check", "conclusion": "pass"})
        raw = json.loads(catalog.record_file(value["id"]).read_text())
        self.assertEqual(raw["status"], "recorded")
        self.assertIsNone(raw["result"])


class DeviceTests(unittest.TestCase):
    def test_dual_boot_health_and_eight_column_frame(self):
        job = engine.Job("board", "Dual-Read-500K", "TEST")
        job.profile["capture_seconds"] = 1
        text = ("# PICO device-read v1; READ ONLY DUAL; device=BMS+POWER bitrate=500000\n"
                "t_ms,event,channel,format,kind,id,dlc,data\n"
                "1000,RX,FDCAN1,STD,DATA,0x00000100,8,01 02 03 04 05 06 07 08\n"
                "# BMS,voltage_mv=48000,current_ma=0\n"
                "# DEVICE_HEALTH,t_ms=5000,device=BMS,seen=0x01F,valid=0x01F\n"
                "# HEALTH,t_ms=5000,device=DUAL,bus_off=0,tec=0,rec=0\n")
        with tempfile.TemporaryDirectory() as folder, patch.object(engine, "LOGS", Path(folder)):
            manager = engine.Manager()
            clock = iter(range(1000))
            with patch.object(manager, "_serial", return_value=FakeSerial(text.encode())), patch.object(engine.time, "monotonic", side_effect=lambda: next(clock)):
                result = manager._do_stream(job)
            self.assertTrue(result["capture_only"])
            self.assertFalse(result["pass"])
            self.assertEqual(job.metrics["rx"], 1)
            self.assertEqual(job.telemetry["values"]["BMS"]["voltage_mv"], "48000")
            self.assertEqual(job.telemetry["devices"]["BMS"]["valid"], "0x01F")

    def test_device_rate_mismatch_rejected(self):
        job = engine.Job("board", "BMS-Read-500K", "TEST")
        text = "# PICO device-read v1; device=BMS bitrate=1000000\n"
        with tempfile.TemporaryDirectory() as folder, patch.object(engine, "LOGS", Path(folder)):
            manager = engine.Manager()
            with patch.object(manager, "_serial", return_value=FakeSerial(text.encode())):
                with self.assertRaisesRegex(ValueError, "位速率"):
                    manager._do_stream(job)

    def test_known_launch_arguments_follow_selected_profile(self):
        with patch.object(tools, "desktop_tools", return_value={"vscode": "/bin/code", "cubemx": "/bin/cubemx"}), patch.object(tools.subprocess, "Popen") as popen:
            tools.launch_app("vscode", "Dual-Read-500K")
            command = popen.call_args.args[0]
            self.assertIn("projects", str(command))
            self.assertIn("--reuse-window", command)


if __name__ == "__main__":
    unittest.main()
