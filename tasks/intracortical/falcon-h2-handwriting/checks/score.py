"""H2 public Valid and separate owner Test scorer."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_sequence_shared"))
from score import main

if __name__ == "__main__":
    sys.argv[1:1] = ["--sequence-task", "h2"]
    main()
