"""Generate an unambiguous VS Code workspace for the selected experiment."""
import copy
import json
import os
from pathlib import Path
import sys

import catalog
import platform_tools as tools


def prepare(mode):
    profile = catalog.profile(mode)
    project = tools.project_dir(mode).resolve()
    build = tools.build_dir(mode).resolve()
    app = profile["cmake_options"].get("PICO_APP", "Bringup")
    candidates = ["App/dual_device_reader.c", "App/device_read_app.c"] if app == "Dual" else (
        ["App/device_read_app.c", "App/device_reader.c"] if app in ("BMS", "Power", "PowerBaud") else
        ["App/can_bringup.c", "Core/Src/main.c"])
    entry = next((project / p for p in candidates if (project / p).is_file()), project / "CMakeLists.txt")
    folder = tools.ROOT / "ui/state/workspaces"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (mode + ("-Windows" if tools.WINDOWS else "-Ubuntu") + ".code-workspace")
    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe" and python.with_name("python.exe").is_file():
        python = python.with_name("python.exe")
    task_name = "PICO build selected experiment"
    frozen = getattr(sys, "frozen", False)
    cli = Path(sys.executable).with_name("PICOCLI.exe" if tools.WINDOWS else "PICOCLI")
    task = {"label": task_name, "type": "process", "command": str(cli if frozen else python),
            "args": ["build", mode] if frozen else [str(tools.ROOT / "ui/build_selected.py"), mode],
            "group": {"kind": "build", "isDefault": True}, "problemMatcher": ["$gcc"]}
    settings = {
        "window.title": profile["name"] + " · $" + "{activeEditorShort} · PICO",
        "workbench.startupEditor": "none",
        "cmake.cmakePath": tools.tool("cmake") or "cmake",
        "cmake.useCMakePresets": "never", "cmake.configureOnOpen": False,
        "cmake.sourceDirectory": str(project), "cmake.buildDirectory": str(build),
        "cmake.buildType": profile["build_type"],
        "cmake.configureSettings": dict(profile["cmake_options"]),
        "C_Cpp.default.compileCommands": str(build / "compile_commands.json"),
        "C_Cpp.default.compilerPath": tools.tool("gcc") or "arm-none-eabi-gcc",
    }
    if profile["toolchain"]:
        settings["cmake.configureSettings"]["CMAKE_TOOLCHAIN_FILE"] = str((project / profile["toolchain"]).resolve())
    if profile["base_mode"] in ("Loopback", "External"):
        settings["cmake.configureSettings"]["PICO_EXTERNAL_CAN"] = "ON" if profile["base_mode"] == "External" else "OFF"
    cube = tools.desktop_tools().get("cubemx")
    if cube:
        settings["stm32cube-ide-core.configuration.productSTM32CubeMX.executablePath"] = cube
    clangd_args = ["starm-clangd", "--compile-commands-dir=" + build.as_posix()]
    gcc = tools.tool("gcc")
    if gcc:
        clangd_args.append("--query-driver=" + Path(gcc).parent.as_posix() + "/arm-none-eabi-*")
    settings["stm32cube-ide-clangd.path"] = "cube"
    settings["stm32cube-ide-clangd.arguments"] = clangd_args
    value = {"folders": [{"name": profile["name"], "path": project.as_posix()}],
             "settings": settings, "tasks": {"version": "2.0.0", "tasks": [task]}}
    old_launch = project / ".vscode/launch.json"
    if old_launch.exists():
        candidates = json.loads(old_launch.read_text(encoding="utf-8-sig")).get("configurations", [])
        if candidates:
            debug = copy.deepcopy(candidates[0])
            debug.update(name=profile["name"] + " (ST-LINK)", cwd=str(project), preLaunchTask=task_name,
                         preBuild="", imagesAndSymbols=[{"imageFileName": str(tools.image_for(mode))}])
            gdb, stlink, programmer = tools.tool("gdb"), tools.tool("stlink-server"), tools.tool("programmer")
            if gdb and stlink and programmer:
                debug.update(gdb=gdb, serverExe=stlink, serverCubeProgPath=str(Path(programmer).parent))
                pack_root = Path(os.environ.get("CMSIS_PACK_ROOT") or
                    (str(Path(os.environ.get("LOCALAPPDATA", "")) / "stm32cube/packs") if tools.WINDOWS
                     else str(Path.home() / ".local/share/stm32cube/packs")))
                svds = list(pack_root.glob("STMicroelectronics/stm32g4xx_dfp/*/SVD/STM32G474.svd"))
                debug.pop("svdPath", None)
                if svds:
                    debug["svdPath"] = str(sorted(svds)[-1])
                value["launch"] = {"version": "0.2.0", "configurations": [debug]}
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, entry
