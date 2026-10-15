#!/usr/bin/env python3
"""Measure exact BrainVision byte ranges for all complete guarded windows."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from fetch_full import SOURCE, verify
from prepare_full import PROTOCOL, events, good_channels

FIELDS = {"NumberOfChannels", "SamplingInterval", "BinaryFormat", "DataOrientation"}


def fields(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.startswith(";"):
            key, value = line.split("=", 1)
            if key in FIELDS:
                result[key] = value.strip()
    if set(result) != FIELDS:
        raise ValueError(f"Missing BrainVision format fields: {path}")
    return result


def header_channel_names(path: Path) -> list[str]:
    names = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if re.match(r"Ch\d+=", line):
            names.append(line.split("=", 1)[1].split(",", 1)[0].replace("\\1", ","))
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = []
    for record in SOURCE["records"]:
        files = record["files"]
        paths = {name: args.data_root / "source" / files[name]["path"]
                 for name in ("events", "channels", "sidecar", "header", "markers")}
        for name, path in paths.items():
            verify(path, files[name])
        header = fields(paths["header"])
        if header["DataOrientation"] != "MULTIPLEXED" or header["BinaryFormat"] != "IEEE_FLOAT_32":
            raise ValueError(f"Unhandled BrainVision data layout: {record['subject']}")
        channels = int(header["NumberOfChannels"])
        sample_hz = round(1_000_000 / float(header["SamplingInterval"]))
        sidecar = json.loads(paths["sidecar"].read_text())
        if sample_hz != sidecar["SamplingFrequency"] or sample_hz not in (256, 512, 1024, 2048):
            raise ValueError(f"Sampling rates differ or are unreviewed: {record['subject']}")
        frame_bytes = channels * 4
        signal_bytes = files["signal"]["bytes"]
        if signal_bytes % frame_bytes:
            raise ValueError(f"Signal size is not a whole frame count: {record['subject']}")
        n_times = signal_bytes // frame_bytes
        blocks = events(paths["events"])
        good, _ = good_channels(paths["channels"])
        header_names = header_channel_names(paths["header"])
        if len(header_names) != channels or len(set(header_names)) != channels or any(
                name not in header_names for name in good):
            raise ValueError(f"Good BIDS channel names differ from BrainVision header: {record['subject']}")
        ranges = []
        for block_number, (onset, duration, _) in enumerate(blocks, start=1):
            starts = [value for value in PROTOCOL["window"]["local_start_seconds"]
                      if value >= 2 and value + 4 <= duration]
            if len(starts) < 12:
                raise ValueError(f"Too few complete windows: {record['subject']} block {block_number}")
            first = round((onset + starts[0]) * sample_hz)
            last = round((onset + starts[-1]) * sample_hz) + 2 * sample_hz
            if last > n_times:
                raise ValueError(f"Signal ends before block {block_number}: {record['subject']}")
            ranges.append({"block": block_number, "first_sample": first, "last_sample": last,
                           "byte_start": first * frame_bytes, "byte_end_exclusive": last * frame_bytes,
                           "windows": len(starts)})
        required = sum(item["byte_end_exclusive"] - item["byte_start"] for item in ranges)
        records.append({"subject": record["subject"], "sample_hz": sample_hz,
                        "source_channels": channels, "good_channels": len(good),
                        "source_samples": n_times, "source_bytes": signal_bytes,
                        "required_range_bytes": required, "fraction": required / signal_bytes,
                        "ranges": ranges})
    source_total = sum(row["source_bytes"] for row in records)
    required_total = sum(row["required_range_bytes"] for row in records)
    plan = {"schema": "bpb-ieeg-film-range-plan/1", "source_git_commit": SOURCE["source_git_commit"],
                      "source_signal_bytes": source_total, "required_range_bytes": required_total,
                      "fraction": required_total / source_total, "saved_bytes": source_total - required_total,
                      "maximum_good_channels": max(row["good_channels"] for row in records),
                      "records": records}
    if args.output is not None:
        args.output.write_text(json.dumps(plan, indent=2) + "\n")
    print(json.dumps({key: value for key, value in plan.items() if key != "records"}, indent=2))


if __name__ == "__main__":
    main()
