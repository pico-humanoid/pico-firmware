"""Shared entry used by the three portable executables."""
from pathlib import Path
import sys
import os
for stream in (sys.stdout,sys.stderr):
    if stream is not None and hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')

# Prefer the shipped, writable source so an exported package can export its
# current project again without installing Python or PyInstaller.
project=Path(sys.executable).resolve().parent/'project'
if (project/'ui/native.py').is_file():
    os.environ['PICO_PROJECT_ROOT']=str(project)
    os.environ['PICO_TOOLS_ROOT']=str(project.parent/'tools')
    sys.path[:0]=[str(project/'ui'),str(project/'ui/vendor'),str(project/'scripts'),str(project/'scripts/linux')]

name = Path(sys.executable).stem.casefold()
if name == "picocli":
    from package_cli import main
    raise SystemExit(main())
if name == "picologviewer" and "--logs" not in sys.argv:
    sys.argv.insert(1, "--logs")
from native import main
main()
