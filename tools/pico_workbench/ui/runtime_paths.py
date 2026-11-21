"""Locate the writable project beside a portable executable or source checkout."""
import os
from pathlib import Path
import sys


def project_root():
    configured = os.environ.get("PICO_PROJECT_ROOT")
    if configured:
        return Path(configured).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "project"
    return Path(__file__).resolve().parents[1]


def firmware_root(workbench=None):
    """Support both the Git checkout and the exported standalone workspace."""
    workbench = Path(workbench) if workbench is not None else project_root()
    candidates = [workbench / "projects/pico-firmware/firmware/PICO_CAN",
                  workbench.parents[1] / "firmware/PICO_CAN"]
    return next((p for p in candidates if (p / "CMakeLists.txt").is_file()), candidates[0])
