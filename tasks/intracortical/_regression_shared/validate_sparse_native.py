"""Compare selected M2 arrays with the pinned native loader on one real run.

The temporary sparse NWB has the original file layout and only the verified
HTTP ranges. It is a validation aid, not a raw source copy or cache entry.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

import numpy as np

from export import ARRAYS, frozen_sources, outside_git
from selective_m2 import verify_prepared
from validate_native import native_loader


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--derived-root", required=True, type=Path)
    args = parser.parse_args()
    derived = outside_git(args.derived_root)
    assets = frozen_sources("falcon-m2-finger-velocity")[2]
    matches = [asset for asset in assets if asset["asset_id"] == args.asset_id]
    if len(matches) != 1:
        parser.error("asset ID is not in frozen M2 inventory")
    asset = matches[0]
    access = "evaluator" if asset["role"] == "test" else "public"
    source_root = derived / access / "selected_sources" / asset["asset_id"]
    receipt = verify_prepared(source_root, asset)
    native_load, task_enum = native_loader()
    with tempfile.TemporaryDirectory(prefix="bpb-m2-native-layout-") as temporary:
        sparse = Path(temporary) / "source-layout-only.nwb"
        with sparse.open("wb") as output:
            output.truncate(asset["size_bytes"])
            for item in receipt["ranges"]:
                block = (source_root / "ranges" / f"{item['offset']:012d}.bin").read_bytes()
                output.seek(item["offset"])
                output.write(block)
        native_x, native_y, native_trial, native_mask = native_load(
            sparse, dataset=task_enum.m2)
    native_arrays = (native_x, native_y, native_mask, native_trial)
    for name, native in zip(ARRAYS, native_arrays):
        selected = np.load(source_root / name, allow_pickle=False)
        if not np.array_equal(np.asarray(native), selected):
            raise ValueError(f"selected range and pinned native loader differ: {name}")
    print(json.dumps({"asset_id": asset["asset_id"], "role": asset["role"],
                      "source_layout_bytes": asset["size_bytes"],
                      "selected_range_bytes": receipt["downloaded_bytes"],
                      "native_loader_exact_match": True,
                      "full_raw_sha256_verified": False,
                      "test_model_evaluated": False}, sort_keys=True))


if __name__ == "__main__":
    main()
