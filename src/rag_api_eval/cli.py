"""Console entry points."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def dashboard() -> None:
    """Run the Streamlit dashboard using the installed package module file."""
    dashboard_file = Path(__file__).with_name("dashboard.py")
    raise SystemExit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(dashboard_file)]))
