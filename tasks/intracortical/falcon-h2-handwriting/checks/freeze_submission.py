"""Freeze a submitted H2 artifact for separate owner Test scoring."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_sequence_shared"))
from freeze_submission import main

if __name__ == "__main__":
    sys.argv[1:1] = ["--task", "h2"]
    main()
