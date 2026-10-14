#!/usr/bin/env python3
"""Package verified native public train/validation data without private Test."""
from pathlib import Path
import sys

TASK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK.parent / "_preparation"))
from package_public import main

if __name__ == "__main__":
    raise SystemExit(main(TASK))
