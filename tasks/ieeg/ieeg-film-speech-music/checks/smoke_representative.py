#!/usr/bin/env python3
"""Score a real sub-02 Valid export through the isolated three-file model path."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import tempfile

import numpy as np

from run import Worker, resolve_image, stage_submission


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True, type=Path)
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--frozen-receipt", required=True, type=Path)
    parser.add_argument("--image")
    args = parser.parse_args()
    subjects = [path for path in (args.prepared / "public").iterdir() if path.is_dir()]
    if len(subjects) != 1:
        raise ValueError("The representative smoke needs exactly one participant")
    subject = subjects[0]
    with np.load(subject / "validation.npz", allow_pickle=False) as data:
        x, ids = data["x"], data["ids"].tolist()
    labels = json.loads((subject / "validation_labels.json").read_text())
    lineage = json.loads((args.prepared / "private" / "lineage.json").read_text())
    locations = lineage["splits"]["validation"]
    if set(ids) != set(labels) or set(ids) != set(locations):
        raise ValueError("Real representative IDs differ from hidden binding")
    groups = defaultdict(list)
    with tempfile.TemporaryDirectory(prefix="bpb-film-representative-") as temporary:
        stage_root = Path(temporary)
        stage_root.chmod(0o755)
        staged = stage_root / "submission"
        stage_submission(args.submission, staged, args.frozen_receipt)
        worker = Worker(resolve_image(args.image), staged, x.shape[1])
        try:
            for index, identifier in enumerate(ids):
                probability = worker.predict(x[index], subject.name)
                groups[locations[identifier]["block"]].append((probability, labels[identifier]))
        finally:
            worker.close()
    if set(groups) != {4, 11}:
        raise ValueError("Expected the two frozen Valid blocks")
    hits = []
    for values in groups.values():
        if len({label for _, label in values}) != 1:
            raise ValueError("Mixed condition labels within a Valid block")
        label = values[0][1]
        hits.append(int((sum(probability for probability, _ in values) / len(values) >= 0.5) == label))
    print(json.dumps({"status": "real_sub02_train_valid_container_reference_only",
                      "train_participants": 1, "valid_participants": 1,
                      "valid_windows": len(ids), "valid_block_balanced_accuracy": sum(hits) / 2,
                      "test_model_inference": False}, indent=2))


if __name__ == "__main__":
    main()
