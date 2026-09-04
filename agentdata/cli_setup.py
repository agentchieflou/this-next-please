# PYTHON_ARGCOMPLETE_OK
"""Entry points: ad-setup (guided wizard) and ad-doctor (offline health check)."""
from __future__ import annotations
import sys
from .setup.wizard import run_doctor, run_setup


def main_setup() -> None:
    sys.exit(run_setup())


def main_doctor() -> None:
    sys.exit(run_doctor())


if __name__ == "__main__":
    # `ad-setup` is the wizard; the doctor has its own console script and its own module-form row
    main_setup()
