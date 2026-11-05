"""Build two native apps plus their CLI, with a relocatable firmware workspace.

CI layout: <repo>/tools/pico_workbench/{ui,scripts,legacy}.
Local layout: pass --project to use an existing prepared PICO_CAN checkout.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

SKIP = {".git", "__pycache__", "build", "state", "node_modules", ".pytest_cache"}


def copy_tree(source, destination):
    shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True,
                    ignore=lambda _path, names: [n for n in names if n in SKIP or n.endswith((".pyc", ".pyo"))])


def seed_project(destination, workbench, repo=None, local=None):
    if local:
        for name in ("App", "Core", "Drivers", "cmake", ".vscode", "ui", "scripts"):
            copy_tree(local / name, destination / name)
        for pattern in ("CMakeLists.txt", "*.ioc", "*.ld", "*.s"):
            for path in local.glob(pattern):
                shutil.copy2(path, destination / path.name)
        device = local / "projects/pico-firmware/firmware/PICO_CAN"
    else:
        device = repo / "firmware/PICO_CAN"
        copy_tree(device, destination)
        copy_tree(workbench / "legacy", destination)
        for name in ("ui", "scripts"):
            copy_tree(workbench / name, destination / name)
    copy_tree(device, destination / "projects/pico-firmware/firmware/PICO_CAN")
    # Examples come only from already-public repository evidence, never private UI records.
    if repo and (repo / "logs").is_dir():
        examples = list((repo / "logs/2026-10-27").glob("*.csv"))
        if examples:
            target = destination / "logs/examples"
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(examples[0], target / examples[0].name)
    (destination / "logs").mkdir(parents=True, exist_ok=True)


def write_text(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")
    if path.suffix == ".sh":
        path.chmod(0o755)


def assemble(output, workbench, seed, built):
    system = "Windows-x64" if os.name == "nt" else "Ubuntu-24.04-x86_64"
    result = output / ("PICO-Workbench-" + system)
    copy_tree(built, result)
    copy_tree(seed, result / "project")
    packaging = workbench / "ui/packaging"
    if (packaging / "README_PORTABLE.md").is_file():
        shutil.copy2(packaging / "README_PORTABLE.md", result / "README_使用说明.md")
    if (packaging / "THIRD_PARTY_NOTICES.md").is_file():
        shutil.copy2(packaging / "THIRD_PARTY_NOTICES.md", result / "THIRD_PARTY_NOTICES.md")
    license_source = Path(sys.base_prefix) / "LICENSE.txt"
    if not license_source.exists():
        license_source = Path(sys.base_prefix) / "share/doc/python3.12/copyright"
    if license_source.is_file():
        shutil.copy2(license_source, result / "PYTHON_LICENSE.txt")
    if os.name == "nt":
        for name, exe in (("打开开发控制台.cmd", "PICOConsole.exe"), ("打开日志查看器.cmd", "PICOLogViewer.exe")):
            write_text(result / name, '@echo off\r\nstart "" "%~dp0' + exe + '"\r\n')
        write_text(result / "检查环境.cmd", '@echo off\r\n"%~dp0PICOCLI.exe" check\r\npause\r\n')
    else:
        for name, exe in (("打开开发控制台.sh", "PICOConsole"), ("打开日志查看器.sh", "PICOLogViewer"), ("检查环境.sh", "PICOCLI")):
            args = ' check' if exe == 'PICOCLI' else ''
            text = '#!/usr/bin/env bash\nset -euo pipefail\nroot="$(cd -- "$(dirname -- "$0")" && pwd)"\n'
            text += 'export PICO_PROJECT_ROOT="$root/project"\n'
            text += 'if [[ -d "$root/tools" ]]; then\n export PICO_TOOLS_ROOT="$root/tools"\n export PATH="$root/tools/bin:$PATH"\n export CUBE_BUNDLE_PATH="$root/tools/stm32cube/bundles"\n export CMSIS_PACK_ROOT="$root/tools/stm32cube/packs"\nfi\n'
            text += f'exec "$root/{exe}"{args} "$@"\n'
            write_text(result / name, text)
        for name in ("安装桌面入口.sh", "安装USB权限.sh"):
            if (packaging / "ubuntu" / name).is_file():
                shutil.copy2(packaging / "ubuntu" / name, result / name)
                (result / name).chmod(0o755)
        rules = packaging / "udev-rules"
        if rules.is_dir():
            copy_tree(rules, result / "usb-permissions")
    manifest = {"version": "2026.11.05", "platform": system, "contains": ["PICOConsole", "PICOLogViewer", "PICOCLI", "Python/Tk runtime", "six firmware profiles", "source workspace"],
                "development_tools_bundled": False, "usb_hardware_validation": "not_run_in_package_test"}
    write_text(result / "bundle.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return result


def archive(path):
    if os.name == "nt":
        target = path.parent / (path.name + ".zip")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for item in path.rglob("*"):
                if item.is_file():
                    z.write(item, item.relative_to(path.parent).as_posix())
    else:
        target = path.parent / (path.name + ".tar.gz")
        with tarfile.open(target, "w:gz", compresslevel=6) as tar:
            tar.add(path, arcname=path.name)
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    target.with_name(target.name + ".sha256").write_text(digest + "  " + target.name + "\n", encoding="ascii")
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    workbench = args.project.resolve() if args.project else args.repo.resolve() / "tools/pico_workbench"
    seed = output / "work/project"
    seed.mkdir(parents=True, exist_ok=True)
    seed_project(seed, workbench, repo=args.repo, local=args.project)
    env = dict(os.environ, PICO_SOURCE_ROOT=str(seed))
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(output / "pyinstaller-dist"), "--workpath", str(output / "pyinstaller-work"), str(workbench / "ui/packaging/desktop.spec")]
    subprocess.run(command, env=env, check=True)
    result = assemble(output, workbench, seed, output / "pyinstaller-dist/PICO-Workbench")
    print("Distribution:", result, flush=True)
    if not args.no_archive:
        print("Archive:", archive(result), flush=True)


if __name__ == "__main__":
    main()
