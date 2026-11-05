"""Protect interpretation and live-reading behavior, without touching hardware."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest

import log_model as model
from log_viewer import LogViewer, PAGE_SIZE, error_line


class InterpretationTests(unittest.TestCase):
    def test_legacy_csv_and_eight_columns_keep_source_lines(self):
        rows = model.parse("# mode=INTERNAL_LOOPBACK\nt_ms,event,format,id,dlc,data\n2013,RX,STD,0x123,8,00 22 33 44 55 66 77 88\n1000,TX_SUBMIT,FDCAN1,EXT,RTR,0x00000100,8,\n")
        self.assertEqual(rows[1].line, 3)
        self.assertEqual(rows[1].display_time, "2.013")
        self.assertEqual(rows[2].kind, "RTR")
        self.assertIn("无数据", rows[2].description)
        self.assertEqual(model.summarize(rows)["rx"], 1)

    def test_zero_counters_do_not_match_failure_substring(self):
        line = "# HEALTH,query_failures=0,tx_rejected=0,invalid=0,bus_off=0,tec=0,rec=0"
        self.assertFalse(error_line(line))
        self.assertTrue(error_line(line.replace("query_failures=0", "query_failures=2")))

    def test_nonzero_cumulative_count_does_not_invent_fail_verdict(self):
        stats = model.summarize(model.parse("# HEALTH,query_failures=42,bus_off=0\n"))
        self.assertEqual(stats["warnings"], 1)
        self.assertEqual(stats["result"], "未提供固件结论")

    def test_usb_submission_and_decoded_reply_not_double_counted(self):
        data = [{"event": "serial_submitted", "elapsed_s": .1, "raw": "aa d0 00 01 55"},
                {"event": "can", "elapsed_s": .2, "id": "0x100", "extended": False, "dlc": 8, "data": "11 ea 00 00 01 e4 56 1b"},
                {"event": "read_reply", "elapsed_s": .2, "id": "0x100", "crc_ok": True, "voltage_v": 45.86}]
        rows = model.parse("\n".join(json.dumps(d) for d in data))
        stats = model.summarize(rows)
        self.assertEqual((stats["tx"], stats["done"], stats["rx"]), (0, 0, 1))
        self.assertEqual(stats["warnings"], 0)

    def test_units_arrays_and_unconfirmed_values(self):
        self.assertEqual(model.format_value("voltage_mv", "45860"), ("45.86", "V"))
        self.assertEqual(model.format_value("current_ma", "-1234"), ("-1.234", "A"))
        self.assertEqual(model.format_value("temperature_decic", "220/212/214"), ("22 / 21.2 / 21.4", "°C"))
        self.assertEqual(model.format_value("temperature_c", [22, 21.2]), ("22 / 21.2", "°C"))
        rec = model.parse_record("# POWER,status03_numeric=UNCONFIRMED_ENDIAN", 5)
        self.assertEqual(rec.level, "warning")
        self.assertIn("UNCONFIRMED", model.device_values([rec])[0][2])

    def test_parameter_values_are_kept_separately_in_jsonl(self):
        rows = model.parse("\n".join(json.dumps(d) for d in [
            {"event": "read_reply", "index": "0x6001", "name": "Can_baud", "value_u8": 2},
            {"event": "read_reply", "index": "0x6002", "name": "Com_baud", "value_u8": 1}]))
        values = model.device_values(rows)
        self.assertEqual([v[2] for v in values], ["2", "1"])
        self.assertIn("500 Kbps", values[0][6])

    def test_exact_id_search_accepts_zero_padding_and_chinese_names(self):
        row = model.parse_record("1234,RX,FDCAN1,EXT,DATA,0x00000100,8,00 00", 2)
        self.assertTrue(model.matches(row, "接收", "RX", "100"))
        self.assertFalse(model.matches(row, "", "全部", "10"))

    def test_pretty_json_report_not_misidentified_as_bad_jsonl(self):
        rows = model.parse(json.dumps({"result": "PASS", "matched": 325}, indent=2))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].level, "normal")


class NativeReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk display unavailable: {exc}")
        ttk.Style(cls.root).theme_use("clam")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "capture.log"
        self.path.write_text("t_ms,event,channel,format,kind,id,dlc,data\n" + "\n".join(
            f"{i},RX,FDCAN1,STD,DATA,0x123,1,01" for i in range(PAGE_SIZE * 3)), encoding="utf-8")
        self.viewer = LogViewer(self.root, self.path)
        self.viewer.window.withdraw()
        self.root.update()

    def tearDown(self):
        self.viewer.close()
        self.tmp.cleanup()

    def test_all_rows_reachable_by_paging_and_filters_work(self):
        v = self.viewer
        self.assertIn("t_ms,event,channel", v.text.get("1.0", "end"))
        self.assertEqual(len(v.filtered), PAGE_SIZE * 3)
        self.assertEqual(len(v.table.get_children()), PAGE_SIZE)
        v.latest()
        self.assertEqual(v.page, 2)
        self.assertEqual(v.table.item(v.table.get_children()[-1], "values")[0], str(PAGE_SIZE * 3 + 1))
        v.ident.set("0x124")
        v.apply_filter()
        self.assertEqual(len(v.table.get_children()), 0)

    def test_live_refresh_keeps_page_scroll_and_selected_source(self):
        v = self.viewer
        v.turn(1)
        v.table.selection_set("event-620")
        v.table.yview_moveto(.3)
        self.root.update()
        before = v.table.yview()[0]
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write("\n9999,RX,FDCAN1,STD,DATA,0x123,1,02")
        v.load(self.path, automatic=True)
        self.root.update()
        self.assertFalse(v.follow.get())
        self.assertEqual(v.page, 1)
        self.assertEqual(v.table.selection(), ("event-620",))
        self.assertAlmostEqual(v.table.yview()[0], before, places=2)
        self.assertEqual(v.summary["rx"].get(), str(PAGE_SIZE * 3 + 1))
        v.follow.set(True)
        v.render()
        self.assertEqual(v.page, 3)
        self.assertEqual(v.table.item(v.table.get_children()[-1], "values")[0], str(PAGE_SIZE * 3 + 2))

    def test_analysis_report_discovery_and_detail_keeps_raw_line(self):
        report = self.path.with_suffix(".analysis.json")
        report.write_text(json.dumps({"result": "READ_WINDOW_OK", "matched": 1500}), encoding="utf-8")
        self.viewer.load(self.path)
        self.assertEqual(self.viewer.report_path, report)
        self.assertIn("READ_WINDOW_OK", self.viewer.report.get("1.0", "end"))
        self.viewer.table.selection_set("event-2")
        self.viewer.show_detail(self.viewer.table)
        self.assertIn("0,RX,FDCAN1,STD,DATA,0x123,1,01", self.viewer.detail.get("1.0", "end"))

    def test_live_device_selection_stays_on_same_field_when_new_field_arrives(self):
        self.path.write_text("# BMS,soc_percent=40\n", encoding="utf-8")
        v = self.viewer
        v.load(self.path)
        selected = v.devices.get_children()[0]
        v.devices.selection_set(selected)
        self.path.write_text("# BMS,soc_percent=40\n# BMS,voltage_mv=45860\n", encoding="utf-8")
        v.load(self.path, automatic=True)
        self.root.update()
        self.assertEqual(v.devices.selection(), (selected,))
        self.assertEqual(v.devices.item(selected, "values")[1], "SOC")


if __name__ == "__main__":
    unittest.main()
