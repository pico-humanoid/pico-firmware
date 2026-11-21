# PICO desktop workbench source

User guide: [docs/desktop-workbench.md](../../docs/desktop-workbench.md).

Source use on Ubuntu 22.04 (Python 3.10): see [the Ubuntu 22.04 guide](../../docs/Ubuntu_22.04.md). Run `bash tools/pico_workbench/ui/start.sh` from the repository root. No PyInstaller is required for source use.

Build a portable distribution from the repository root with Python 3.10 or later and PyInstaller 6.22.3:

```bash
python -m pip install pyinstaller==6.22.3
python tools/pico_workbench/ui/packaging/build_distribution.py --repo . --output dist
```

On Ubuntu build hosts install python3-tk, xvfb, xauth, binutils and the matching Python runtime library. The workflow defines independent Windows x64, Ubuntu 22.04 / Python 3.10 and Ubuntu 24.04 / Python 3.12 builds. The new 22.04 job has not been executed or published in this local integration; a complete frozen/offline package has not been validated locally. Historical 24.04 binaries are not claimed to work on 22.04. Public archives include app runtimes and source workspaces, and exclude proprietary editor/tool installations and user records.
