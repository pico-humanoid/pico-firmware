# PICO desktop workbench source

User guide: [docs/desktop-workbench.md](../../docs/desktop-workbench.md).

Build from the repository root with Python 3.12 and PyInstaller 6.22.3:

```bash
python -m pip install pyinstaller==6.22.3
python tools/pico_workbench/ui/packaging/build_distribution.py --repo . --output dist
```

On Ubuntu build hosts install python3-tk, xvfb, libpython3.12 and binutils. The release workflow builds and checks Windows x64 and Ubuntu 24.04 x86_64 independently. Public archives include app runtimes and source workspaces, and exclude proprietary editor/tool installations and user records.
