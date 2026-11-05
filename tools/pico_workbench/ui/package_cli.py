"""Console companion for portable builds and checks, never flashes implicitly."""
import argparse
import json
from pathlib import Path
import sys
import tempfile


def self_test():
    import tkinter as tk
    from tkinter import ttk
    import catalog
    import platform_tools as tools
    import workspace
    from native import Desktop
    from log_viewer import LogViewer
    root = tk.Tk()
    root.withdraw()
    ttk.Style(root).theme_use("clam")
    desktop = Desktop(root)
    root.withdraw()
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "smoke.csv"
        path.write_text("t_ms,event,format,id,dlc,data\n1000,RX,STD,0x123,1,01\n# BMS,voltage_mv=45860\n# HEALTH,query_failures=0,bus_off=0\n", encoding="utf-8")
        viewer = LogViewer(root, path)
        viewer.window.withdraw()
        root.update()
        assert viewer.summary["rx"].get() == "1"
        assert viewer.summary["warnings"].get() == "0"
        assert any(viewer.devices.item(row, "values")[2:4] == ("45.86", "V") for row in viewer.devices.get_children())
        assert (tools.ROOT / "CMakeLists.txt").is_file()
        profiles = catalog.profiles()
        assert len(profiles) >= 6
        path, entry = workspace.prepare("BMS-Read-500K")
        config = json.loads(path.read_text(encoding="utf-8"))
        if getattr(sys, "frozen", False):
            assert Path(config["tasks"]["tasks"][0]["command"]).name.startswith("PICOCLI")
        viewer.close()
    root.destroy()
    return {"result": "PASS", "project": str(tools.ROOT), "profiles": len(profiles),
            "checks": ["native_console", "native_log_viewer", "CSV_and_comment_parsing", "units", "zero_error_counters", "portable_project", "VS_Code_build_command"]}


def main():
    parser = argparse.ArgumentParser(description="PICO portable build and environment check")
    parser.add_argument("action", choices=("check", "self-test", "build"))
    parser.add_argument("profile", nargs="?")
    args = parser.parse_args()
    if args.action == "build":
        if not args.profile:
            parser.error("build requires a profile ID")
        from build_selected import main as build
        return build(args.profile)
    if args.action == "self-test":
        value = self_test()
    else:
        import platform_tools as tools
        value = tools.status()
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
