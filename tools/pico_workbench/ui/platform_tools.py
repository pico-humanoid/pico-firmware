"""Local, cross-platform STM32 tools. No shell commands are supplied by the UI."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
import catalog
from runtime_paths import project_root

ROOT = project_root()
WINDOWS = os.name == "nt"
SPAWN_LOCK = threading.RLock()


def bundle_roots():
    candidates = [
        os.environ.get("CUBE_BUNDLE_PATH", ""),
        str(Path(os.environ["PICO_TOOLS_ROOT"]) / "stm32cube/bundles") if os.environ.get("PICO_TOOLS_ROOT") else "",
        str(ROOT.parent / "tools/stm32cube/bundles"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "stm32cube/bundles") if WINDOWS else "",
        str(Path.home() / ".local/share/stm32cube/bundles"),
        str(ROOT.parents[1] / "STM32Tools/ubuntu/stm32cube/bundles"),
    ]
    return [Path(p) for p in candidates if p and Path(p).is_dir()]


def tool(name):
    mapping = {
        "cmake": ("cmake", "cmake"),
        "ninja": ("ninja", "ninja"),
        "gcc": ("gnu-tools-for-stm32", "arm-none-eabi-gcc"),
        "programmer": ("programmer", "STM32_Programmer_CLI"),
        "gdb": ("gnu-gdb-for-stm32", "arm-none-eabi-gdb"),
        "stlink-server": ("stlink-gdbserver", "ST-LINK_gdbserver"),
    }
    folder, binary = mapping[name]
    executable = binary + (".exe" if WINDOWS else "")
    for root in bundle_roots():
        for path in sorted(root.glob(folder + "/*/bin/" + executable), reverse=True):
            if path.is_file():
                return str(path)
    return shutil.which(executable)


def environment():
    env = os.environ.copy()
    if getattr(sys, "frozen", False) and not WINDOWS:
        env["LD_LIBRARY_PATH"] = env.get("LD_LIBRARY_PATH_ORIG", "")
    bins = [str(Path(p).parent) for key in ("gcc", "ninja", "cmake", "programmer") if (p := tool(key))]
    env["PATH"] = os.pathsep.join(bins + [env.get("PATH", "")])
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if not WINDOWS:
        candidates = [Path(os.environ.get("PICO_TOOLS_ROOT", "/nonexistent")) / "lib",
                      ROOT.parents[1] / "STM32Tools/ubuntu/lib"]
        libs = [str(p) for p in candidates if p.is_dir()]
        env["LD_LIBRARY_PATH"] = ":".join(libs + [env.get("LD_LIBRARY_PATH", "")])
    return env


def spawn(args, **options):
    """External tools must not inherit the frozen GUI's private DLL directory."""
    if WINDOWS and getattr(sys, "frozen", False):
        import ctypes
        with SPAWN_LOCK:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
            try:
                return subprocess.Popen(args, **options)
            finally:
                ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))
    return subprocess.Popen(args, **options)


def build_dir(mode):
    validate_mode(mode)
    return project_dir(mode) / "build" / ("UI-" + ("Windows" if WINDOWS else "Linux") + "-" + mode)


def validate_mode(mode):
    catalog.profile(mode)


def project_dir(mode):
    if mode in ("Loopback", "External"):
        return ROOT
    value = catalog.profile(mode)["project_dir"]
    return Path(value) if Path(value).is_absolute() else ROOT / value


def image_for(mode):
    profile = catalog.profile(mode)
    own = build_dir(mode) / profile["elf_name"]
    if own.exists():
        return own
    if mode in ("Loopback", "External"):
        return ROOT / "build" / (mode if WINDOWS else "Ubuntu-" + mode) / "PICO_CAN.elf"
    return own


def build_commands(mode):
    validate_mode(mode)
    cmake, ninja, gcc = tool("cmake"), tool("ninja"), tool("gcc")
    if not all((cmake, ninja, gcc)):
        raise ValueError("未找到 CMake、Ninja 或 GCC，请在环境检查页查看工具路径。")
    dest = str(build_dir(mode))
    profile = catalog.profile(mode)
    source = project_dir(mode)
    config = [cmake, "--fresh", "-S", str(source), "-B", dest, "-G", "Ninja",
              "-DCMAKE_BUILD_TYPE=" + profile["build_type"], "-DCMAKE_MAKE_PROGRAM=" + ninja]
    if profile.get("toolchain"):
        config.append("-DCMAKE_TOOLCHAIN_FILE=" + str((source / profile["toolchain"]).resolve()))
    if profile["base_mode"] in ("Loopback", "External"):
        config.append("-DPICO_EXTERNAL_CAN=" + ("ON" if profile["base_mode"] == "External" else "OFF"))
    for key, value in profile["cmake_options"].items():
        config.append("-D" + key + "=" + ("ON" if value is True else "OFF" if value is False else str(value)))
    return [config, [cmake, "--build", dest, "--parallel", "4"]]


def source_newer(image, mode="Loopback"):
    if not image.exists():
        return True
    stamp = image.stat().st_mtime
    source = project_dir(mode)
    files = list(source.glob("CMakeLists.txt")) + list((source / "cmake").rglob("*.cmake"))
    files += list((source / "cmake").rglob("CMakeLists.txt"))
    for folder in ("App", "Core", "Drivers"):
        files.extend(p for p in (source / folder).rglob("*") if p.suffix in (".c", ".h", ".s", ".S"))
    files += list(source.glob("*.ld")) + list(source.glob("*.s"))
    return any(p.stat().st_mtime > stamp + 0.01 for p in files)


def desktop_tools():
    portable = Path(os.environ.get("PICO_TOOLS_ROOT", str(ROOT.parent / "tools")))
    if WINDOWS:
        cube = portable / "STM32CubeMX/MX/STM32CubeMX.exe"
        if not cube.is_file():
            cube = ROOT.parents[1] / "STM32Tools/STM32CubeMX-6.18.1/MX/STM32CubeMX.exe"
        code = portable / "vscode/Code.exe"
        if not code.is_file():
            code = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Microsoft VS Code/Code.exe"
    else:
        cube = portable / "bin/STM32CubeMX"
        if not cube.is_file():
            cube = ROOT.parents[1] / "STM32Tools/ubuntu/bin/STM32CubeMX"
        code = portable / "bin/code"
        if not code.is_file():
            code = Path(shutil.which("code") or "/nonexistent")
    return {"cubemx": str(cube) if cube.is_file() else shutil.which("STM32CubeMX"),
            "vscode": str(code) if code.is_file() else shutil.which("code")}


def launch_app(app, mode):
    if app not in ("cubemx", "vscode"):
        raise ValueError("不支持此应用。")
    executable = desktop_tools()[app]
    if not executable:
        raise ValueError("未找到 " + app + "，请在本机安装或检查路径。")
    directory = project_dir(mode)
    if app == "cubemx":
        matches = list(directory.glob("*.ioc"))
        if len(matches) != 1:
            raise ValueError("项目目录需有恰好一个 .ioc 文件。")
        args = [executable, str(matches[0])]
    else:
        from workspace import prepare
        workspace, entry = prepare(mode)
        args = [executable, "--reuse-window", str(workspace), "--goto", str(entry) + ":1"]
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {"start_new_session": True}
    spawn(args, cwd=directory, env=environment(), stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, **options)
    return {"ok": True, "application": app, "project": str(directory),
            **({"workspace": str(workspace), "entry_file": str(entry)} if app == "vscode" else {})}


def status():
    found = {name: tool(name) for name in ("cmake", "ninja", "gcc", "programmer")}
    return {"os": platform.system(), "project": str(ROOT), "tools": found, "applications": desktop_tools(),
            "ready": all(found.values()),
            "firmware": {m: {"path": str(image_for(m)), "exists": image_for(m).exists()}
                         for m in (p["id"] for p in catalog.profiles())}}
