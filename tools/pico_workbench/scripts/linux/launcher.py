"""Compatibility entry for the native workbench (no device actions on launch)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ui"))
from native import main

if __name__ == "__main__":
    main()
