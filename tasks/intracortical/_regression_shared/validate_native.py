"""Compare one real NWB conversion with the pinned FALCON native loader.

This maintainer check fetches only the pinned source file into memory. It
compares arrays without writing labels or reporting a model score.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import urlopen

import numpy as np

from export import SPECS, convert


SOURCE_URL = (
    "https://raw.githubusercontent.com/snel-repo/falcon-challenge/"
    "770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f/falcon_challenge/dataloaders.py"
)


def native_loader():
    with urlopen(SOURCE_URL, timeout=30) as response:
        source = response.read(100_000).decode("utf-8")
    line = "from falcon_challenge.config import FalconTask"
    if source.count(line) != 1 or "def load_nwb(" not in source or "def bin_units(" not in source:
        raise ValueError("pinned source loader structure changed")
    enum = "from enum import Enum\nclass FalconTask(Enum):\n    h1='h1'\n    h2='h2'\n    m1='m1'\n    m2='m2'\n    b1='b1'"
    namespace = {}
    exec(compile(source.replace(line, enum), SOURCE_URL, "exec"), namespace)
    return namespace["load_nwb"], namespace["FalconTask"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", choices=tuple(SPECS), required=True)
    parser.add_argument("--nwb", type=Path, required=True)
    parser.add_argument("--derived-run", type=Path,
                        help="Optional derived arrays to compare against full native loading")
    args = parser.parse_args()
    spec = SPECS[args.task_id]
    official_load, task_enum = native_loader()
    native_x, native_y, native_trial_start, native_mask = official_load(
        args.nwb, dataset=getattr(task_enum, spec["native"]))
    expected = (native_x, native_y, native_mask, native_trial_start)
    actual = convert(args.nwb, spec)
    comparisons = [np.array_equal(np.asarray(left), right) for left, right in zip(expected, actual)]
    if not all(comparisons):
        raise ValueError(f"native array mismatch: {comparisons}")
    if args.derived_run is not None:
        for name, native in zip(("x.npy", "y.npy", "mask.npy", "trial_start.npy"), expected):
            derived = np.load(args.derived_run / name, allow_pickle=False)
            if not np.array_equal(np.asarray(native), derived):
                raise ValueError(f"derived array differs from full native source: {name}")
    print(json.dumps({"task_id": args.task_id, "source_commit": SOURCE_URL.split("/")[5],
                      "shapes": [list(array.shape) for array in actual],
                      "exact_match": True, "derived_export_match": args.derived_run is not None,
                      "test_model_evaluated": False}, sort_keys=True))


if __name__ == "__main__":
    main()
