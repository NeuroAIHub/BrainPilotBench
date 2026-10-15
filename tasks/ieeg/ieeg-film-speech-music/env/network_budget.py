#!/usr/bin/env python3
"""Record a conservative cumulative cap across resumable clinical downloads."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from fetch_full import SOURCE, LIMIT

RESERVE = 1_000_000_000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    args = parser.parse_args()
    source_root = args.data_root / "source"
    persisted = sum(path.stat().st_size for path in source_root.rglob("*") if path.is_file())
    planned = SOURCE["all_source_total_bytes"]
    if persisted > planned:
        raise ValueError("Persisted source bytes exceed the pinned inventory")
    # Every response body byte from earlier runs remains in a verified file or
    # resumable .part file. This reserve also charges unflushed/interrupted reads.
    conservative_total = planned + RESERVE
    if conservative_total > LIMIT:
        raise ValueError("Cumulative worst-case source transfer exceeds the 20 GB cap")
    report = {"schema": "bpb-ieeg-film-network-budget/1",
              "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
              "persisted_prior_source_bytes_including_reused_files": persisted,
              "remaining_pinned_source_bytes": planned - persisted,
              "interrupted_read_and_retry_reserve_bytes": RESERVE,
              "conservative_cumulative_network_bound_bytes": conservative_total,
              "network_limit_bytes": LIMIT,
              "note": "Persisted bytes include reused sub-02 and thus overstate prior network transfer. No partial or completed source bytes were discarded between runs."}
    path = args.data_root / "network_budget.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
