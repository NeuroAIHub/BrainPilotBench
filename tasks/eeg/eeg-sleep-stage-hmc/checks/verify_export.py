#!/usr/bin/env python3
"""Check a frozen native export before deriving public and evaluator packages."""
from pathlib import Path
import sys

TASK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK.parent / "_preparation"))
from verify_export import main

if __name__ == "__main__":
    raise SystemExit(main(TASK))
