"""Create one low-information H2 reference from the first real Train file."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil

import numpy as np
from safetensors.numpy import save_file


TASK = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-data-dir", required=True, type=Path)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    args = parser.parse_args()
    root = args.public_data_dir.resolve()
    contract = json.loads((TASK / "contract.json").read_text())
    manifest_path = root / "train/manifest.json"
    from hashlib import sha256
    if sha256(manifest_path.read_bytes()).hexdigest() != contract["derived_manifests"]["train"]["sha256"]:
        raise ValueError("Train manifest differs from contract")
    manifest = json.loads(manifest_path.read_text())
    run = manifest["runs"][0]
    info = run["files"]["labels.json"]
    labels_path = manifest_path.parent / info["path"]
    if labels_path.stat().st_size != info["bytes"] or sha256(labels_path.read_bytes()).hexdigest() != info["sha256"]:
        raise ValueError("Train labels differ from contract")
    labels = json.loads(labels_path.read_text())
    if len(labels) != run["trials"] or not labels:
        raise ValueError("Train labels do not cover complete trials")
    # Frequency ties keep the first source-order sentence.
    counts = Counter(labels)
    sentence = max(labels, key=lambda text: counts[text])
    submission = args.artifacts_dir / "submission"
    submission.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(TASK / "solution/model.py", submission / "model.py")
    (submission / "config.json").write_text(json.dumps({"schema": "bpb-h2-train-text-reference/1",
                                                         "train_sentence": sentence}, ensure_ascii=False) + "\n")
    save_file({"anchor": np.zeros((1,), dtype=np.float32)}, str(submission / "weights.safetensors"))
    print(json.dumps({"submission": str(submission), "train_run": run["id"],
                      "train_trials_used": len(labels), "valid_labels_read": False,
                      "test_data_read": False, "model_executed_on_host": False}, sort_keys=True))


if __name__ == "__main__":
    main()
