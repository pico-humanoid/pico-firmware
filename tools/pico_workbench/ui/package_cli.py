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
    assert len(desktop.navigation.tabs())==3
    root.withdraw()
    for button,app in [('speed','MotorSpeed'),('dual_speed','MotorDualSpeed'),('fault','MotorDualFault'),('position','MotorPosition'),('dual_position','MotorDualPosition'),('sync_position','MotorSyncPosition')]:
        desktop.action_buttons[button].invoke()
        experiment=desktop.motor_panel
        experiment.window.withdraw()
        assert str(experiment.enable_button['state'])=='disabled'
        assert experiment.profile()['cmake_options']['PICO_APP']==app
        assert desktop.profile()['cmake_options']['PICO_APP']==app
        assert hasattr(experiment,'plot') and len(experiment.details.tabs())==2
        experiment.destroy()
    assert 'enable' not in desktop.action_buttons and 'startup_speed' not in desktop.action_buttons
    desktop.action_buttons['tuning'].invoke()
    tuning=desktop.motor_panel;tuning.window.withdraw()
    assert str(tuning.start_button['state'])=='disabled'
    assert str(tuning.apply_button['state'])=='disabled'
    assert tuning.profile()['cmake_options']['PICO_APP']=='MotorTuning'
    assert desktop.profile()['cmake_options']['PICO_APP']=='MotorTuning'
    tuning.mode.set('SPD');tuning.mode_changed()
    assert str(tuning.inputs[0]['state'])=='disabled'
    assert str(tuning.inputs[2]['state'])=='normal'
    tuning.destroy()
    desktop.action_buttons['dual_tuning'].invoke()
    dual=desktop.motor_panel;dual.window.withdraw()
    assert dual.dual() and len(dual.scope_panes.panes())==2
    assert str(dual.start_button['state'])=='disabled'
    dual.destroy()
    desktop.action_buttons['position_diag'].invoke()
    diagnostic=desktop.motor_panel
    diagnostic.window.withdraw()
    assert str(diagnostic.verify_button['state'])=='disabled'
    assert not hasattr(diagnostic,'enable_button')
    assert diagnostic.profile()['cmake_options']['PICO_APP']=='MotorPositionDiag'
    assert desktop.profile()['cmake_options']['PICO_APP']=='MotorPositionDiag'
    assert len(diagnostic.tabs.tabs())==3
    with tempfile.TemporaryDirectory() as folder:
        log=Path(folder)/'board.log'
        log.write_text('# PICO_MOTOR_POSITION_DIAG=1; channel=FDCAN1\n# DIAG_VALUE,t_ms=1,index=0x7019,status=OK,value_micro=-1695000\n# DIAG_VALUE,t_ms=2,index=0x7019,status=OK,value_micro=-1443650\n# DIAG_RESULT,result=STOPPED,reason=USER_STOP,stop_confirmed=1,target_cleared=0\n# DIAG_STATE,state=DONE,id=1,error=0,stop_confirmed=1,echo_allowed=0\n',encoding='utf-8')
        diagnostic.load_log(log)
        root.update()
        if diagnostic._timer:diagnostic.window.after_cancel(diagnostic._timer);diagnostic._timer=None
        diagnostic.poll()
        assert '跨度14.40' in diagnostic.summary.get()
        assert diagnostic.data.result['result']=='STOPPED'
        assert str(diagnostic.verify_button['state'])=='disabled'
        assert '离线日志' in diagnostic.status.get()
    diagnostic.destroy()
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
            "checks": ["native_console", "native_log_viewer", "grouped_experiment_center", "live_trajectory_and_log_tabs", "stopped_diagnostic_entry_and_offline_values", "main_buttons_open_tuning_single_and_dual_speed", "CSV_and_comment_parsing", "units", "zero_error_counters", "portable_project", "VS_Code_build_command"]}


def main():
    parser = argparse.ArgumentParser(description="PICO portable build and environment check")
    parser.add_argument("action", choices=("check", "self-test", "build", "export"))
    parser.add_argument("profile", nargs="?")
    args = parser.parse_args()
    if args.action == "export":
        if not args.profile:parser.error("export requires a destination path")
        from portable_export import export
        export(args.profile,print);return 0
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
