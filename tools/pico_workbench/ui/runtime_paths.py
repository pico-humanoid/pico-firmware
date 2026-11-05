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
