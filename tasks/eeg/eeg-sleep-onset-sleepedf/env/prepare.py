#!/usr/bin/env python3
"""Thin entry for this task's pinned native data-only preparation recipe."""
from pathlib import Path
import subprocess
import sys

TASK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK.parent / "_preparation"))
from prepare import main

if __name__ == "__main__":
    try:
        raise SystemExit(main(TASK))
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"EEG data preparation stopped: {error}", file=sys.stderr)
        raise SystemExit(2) from error
