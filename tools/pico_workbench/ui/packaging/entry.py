"""Shared entry used by the three portable executables."""
from pathlib import Path
import sys

name = Path(sys.executable).stem.casefold()
if name == "picocli":
    from package_cli import main
    raise SystemExit(main())
if name == "picologviewer" and "--logs" not in sys.argv:
    sys.argv.insert(1, "--logs")
from native import main
main()
