"""Attach the original user's existing vendor tools to a local migration bundle.

This output is deliberately separate from the public GitHub application archives.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tarfile
import zipfile
from build_distribution import copy_tree, write_text, archive


def extract_vsix(path, destination):
    with zipfile.ZipFile(path) as z:
        info = json.loads(z.read("extension/package.json"))
        target = destination / (info["publisher"] + "." + info["name"] + "-" + info["version"])
        target.mkdir(parents=True, exist_ok=True)
        for name in z.namelist():
            if name.startswith("extension/") and not name.endswith("/"):
                part = Path(name[len("extension/"):])
                if part.is_absolute() or ".." in part.parts:
                    raise ValueError("Unsafe VSIX path")
                file = target / part
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(z.read(name))


def normalize_linux(root):
    for base, dirs, names in os.walk(root):
        Path(base).chmod(0o755)
        for name in names:
            path = Path(base) / name
            if path.is_symlink():
                continue
            with path.open("rb") as f:
                magic = f.read(4)
            path.chmod(0o755 if magic.startswith((b"\x7fELF", b"#!")) or path.suffix == ".sh" else 0o644)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--downloads", required=True, type=Path)
    parser.add_argument("--windows-home", type=Path)
    parser.add_argument("--serial-driver", type=Path)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    windows = os.name == "nt"
    d = Path("D:/") if windows else Path("/mnt/d")
    c = Path("C:/") if windows else Path("/mnt/c")
    windows_home = args.windows_home or (Path.home() if windows else None)
    source_tools = d / "STM32Tools/ubuntu"
    root = args.output / (args.app.name + "-FullOffline")
    copy_tree(args.app, root)
    tools = root / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    print("Attaching STM32 tool bundles...", flush=True)
    bundles = windows_home / "AppData/Local/stm32cube/bundles" if windows else source_tools / "stm32cube/bundles"
    copy_tree(bundles, tools / "stm32cube/bundles")
    packs = windows_home / "AppData/Local/stm32cube/packs/STMicroelectronics" if windows else source_tools / "stm32cube/packs/STMicroelectronics"
    copy_tree(packs, tools / "stm32cube/packs/STMicroelectronics")
    cube = d / "STM32Tools/STM32CubeMX-6.18.1/MX" if windows else source_tools / "STM32CubeMX-6.18.1/MX"
    print("Attaching CubeMX and firmware repository...", flush=True)
    copy_tree(cube, tools / "STM32CubeMX/MX")
    firmware = "STM32Cube_FW_G4_V1.6.3"
    copy_tree(d / "STM32Cube/Respsitory" / firmware, tools / "firmware" / firmware)
    (tools / "bin").mkdir(exist_ok=True)
    shutil.copy2(d / "STM32Tools/bin/cube.exe" if windows else source_tools / "bin/cube", tools / "bin" / ("cube.exe" if windows else "cube"))
    print("Attaching editor and offline extensions...", flush=True)
    editor = tools / "vscode"
    editor.mkdir(exist_ok=True)
    if windows:
        with zipfile.ZipFile(args.downloads / "vscode-windows.zip") as z:
            z.extractall(editor)
    else:
        tar_path = args.downloads / "vscode-linux-x64.tar.gz"
        with tarfile.open(tar_path) as tar:
            for member in tar.getmembers():
                if "/" not in member.name:
                    continue
                member.name = member.name.split("/", 1)[1]
                if member.name:
                    tar.extract(member, editor, filter="data")
    extensions = editor / "data/extensions"
    extensions.mkdir(parents=True, exist_ok=True)
    if windows:
        base = windows_home / ".vscode/extensions"
        for path in base.iterdir():
            if path.is_dir() and path.name.startswith(("stmicroelectronics.", "ms-vscode.cmake-tools-", "eclipse-cdt.", "ms-ceintl.vscode-language-pack-zh-hans-")):
                copy_tree(path, extensions / path.name)
    else:
        for path in (source_tools / "offline/vscode-extensions").glob("*.vsix"):
            extract_vsix(path, extensions)
        extract_vsix(source_tools / "offline/stm32-rtos-1.5.0.vsix", extensions)
        language = list((windows_home / ".vscode/extensions").glob("ms-ceintl.vscode-language-pack-zh-hans-*")) if windows_home else []
        if language:
            copy_tree(language[0], extensions / language[0].name)
    settings = {"stm32cube-ide-core.LocalOnly": True, "stm32cube-ide-core.networkInterfaceAutoDetection": False,
                "stm32cube-ide-core.enableTelemetry": False, "update.mode": "none", "extensions.autoUpdate": False,
                "extensions.autoCheckUpdates": False, "workbench.startupEditor": "none", "editor.fontSize": 15}
    config = editor / "data/user-data/User/settings.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    write_text(config, json.dumps(settings, ensure_ascii=False, indent=2))
    if windows:
        copy_tree(windows_home / "AppData/Local/stm32cube/bundles/stlink-usb-driver", tools / "drivers/ST-LINK")
        if args.serial_driver:
            shutil.copy2(args.serial_driver, tools / "drivers/CH341SER.EXE")
        write_text(root / "首次准备.cmd", '@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0首次准备.ps1"\r\npause\r\n')
        ps = r'''$ErrorActionPreference = 'Stop'
$bundleRoot = $PSScriptRoot
$repository = Join-Path $env:USERPROFILE 'STM32Cube\Repository'
New-Item -ItemType Directory -Force -Path $repository | Out-Null
$target = Join-Path $repository 'STM32Cube_FW_G4_V1.6.3'
if (-not (Test-Path -LiteralPath $target)) {
    New-Item -ItemType Junction -Path $target -Target (Join-Path $bundleRoot 'tools\firmware\STM32Cube_FW_G4_V1.6.3') | Out-Null
}
Write-Host 'PICO offline tools are ready. Run PICOConsole.exe or PICOLogViewer.exe.'
Write-Host 'If Windows has no device driver, run the signed installers in tools\drivers as administrator.'
& (Join-Path $bundleRoot 'PICOCLI.exe') check
'''
        write_text(root / "首次准备.ps1", ps)
    else:
        copy_tree(source_tools / "udev-rules", root / "usb-permissions")
        write_text(tools / "bin/STM32CubeMX", '#!/usr/bin/env bash\nset -e\nbase="$(cd -- "$(dirname -- "$0")/.." && pwd)"\ncd "$base/STM32CubeMX/MX"\nexec ./STM32CubeMX "$@"\n')
        write_text(tools / "bin/code", '#!/usr/bin/env bash\nset -e\nbase="$(cd -- "$(dirname -- "$0")/.." && pwd)"\nexec "$base/vscode/bin/code" --locale zh-cn "$@"\n')
        first = '''#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "$0")" && pwd)"
repo="$HOME/STM32Cube/Repository"
mkdir -p "$repo"
if [[ ! -e "$repo/STM32Cube_FW_G4_V1.6.3" ]]; then
  ln -s "$root/tools/firmware/STM32Cube_FW_G4_V1.6.3" "$repo/STM32Cube_FW_G4_V1.6.3"
fi
bash "$root/安装桌面入口.sh"
echo '下一步由 Ubuntu 请求管理员认证，安装 USB 规则并配置 VS Code 沙箱；不会烧录开发板。'
if command -v pkexec >/dev/null; then
  pkexec /bin/bash "$root/首次系统准备.sh"
else
  sudo /bin/bash "$root/首次系统准备.sh"
fi
"$root/PICOCLI" check
echo '准备完成。可从应用程序菜单打开 PICO。'
'''
        write_text(root / "首次准备.sh", first)
        admin = '''#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo '需要管理员权限。'; exit 2; }
root="$(cd -- "$(dirname -- "$0")" && pwd)"
bash "$root/安装USB权限.sh"
chown root:root "$root/tools/vscode/chrome-sandbox"
chmod 4755 "$root/tools/vscode/chrome-sandbox"
'''
        write_text(root / "首次系统准备.sh", admin)
        normalize_linux(root)
    manifest = json.loads((root / "bundle.json").read_text(encoding="utf-8"))
    manifest.update(development_tools_bundled=True, distribution="local_user_migration_only", third_party_editor="VS Code 1.145.0", firmware_library="STM32CubeG4 1.6.3")
    write_text(root / "bundle.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    print("Full offline directory:", root, flush=True)
    if not args.no_archive:
        print("Full offline archive:", archive(root), flush=True)


if __name__ == "__main__":
    main()
