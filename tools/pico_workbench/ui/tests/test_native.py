import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import platform_tools as tools
import workspace
from native import error_line


class WorkspaceAndLogTests(unittest.TestCase):
    def test_workspace_points_to_selected_project_and_source(self):
        path, entry = workspace.prepare("BMS-Read-500K")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(Path(data["folders"][0]["path"]), tools.project_dir("BMS-Read-500K"))
        self.assertEqual(entry.name, "device_read_app.c")
        self.assertIn("BMS-Read-500K", data["settings"]["cmake.buildDirectory"])
        self.assertEqual(data["settings"]["cmake.configureSettings"]["PICO_APP"], "BMS")
        self.assertIn("BMS-Read-500K", data["tasks"]["tasks"][0]["args"])
        if tools.WINDOWS:
            self.assertIn("UI-Windows-BMS-Read-500K", data["launch"]["configurations"][0]["imagesAndSymbols"][0]["imageFileName"])

    def test_dual_opens_dual_source_and_different_workspace(self):
        bms, _ = workspace.prepare("BMS-Read-500K")
        dual, entry = workspace.prepare("Dual-Read-500K")
        self.assertNotEqual(bms, dual)
        self.assertEqual(entry.name, "dual_device_reader.c")

    def test_launcher_opens_workspace_and_entry_not_just_welcome(self):
        with patch.object(tools, "desktop_tools", return_value={"vscode": "/tools/code"}), patch.object(tools.subprocess, "Popen") as proc:
            result = tools.launch_app("vscode", "Power-Read-500K")
        args = proc.call_args.args[0]
        self.assertIn("--goto", args)
        self.assertTrue(args[-1].endswith("device_read_app.c:1"))
        self.assertIn("Power-Read-500K", result["workspace"])

    def test_zero_health_counters_not_shown_as_errors(self):
        self.assertFalse(error_line("# HEALTH,bus_off=0,invalid=0,query_timeouts=0"))
        self.assertTrue(error_line("# HEALTH,bus_off=1"))
        self.assertTrue(error_line("# RESULT=FAIL"))
        self.assertTrue(error_line("1000,TX_TIMEOUT,FDCAN1"))

    def test_linux_workspace_uses_native_debug_tools(self):
        names={"gdb":"/opt/st/bin/arm-none-eabi-gdb","stlink-server":"/opt/st/bin/ST-LINK_gdbserver",
               "programmer":"/opt/st/bin/STM32_Programmer_CLI","cmake":"/opt/st/bin/cmake",
               "gcc":"/opt/st/bin/arm-none-eabi-gcc"}
        with patch.object(tools,"WINDOWS",False), patch.object(tools,"tool",side_effect=lambda n:names.get(n)):
            path,_=workspace.prepare("BMS-Read-500K")
        value=json.loads(path.read_text(encoding="utf-8"))
        debug=value["launch"]["configurations"][0]
        self.assertEqual(debug["gdb"],"/opt/st/bin/arm-none-eabi-gdb")
        self.assertIn("UI-Linux-BMS-Read-500K",value["settings"]["cmake.buildDirectory"])
        self.assertNotIn("AppData",debug["serverExe"])


if __name__ == "__main__":
    unittest.main()
