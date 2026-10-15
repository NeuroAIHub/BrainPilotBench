#!/usr/bin/env python3
"""Owner-side deterministic export. Raw ZIPs must never enter Agent workspaces."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import zipfile

import numpy as np
from scipy.io import loadmat

from common import PROFILE, TASK, sha256, regular_unique
from prepare import ARCHIVE_BYTES, ARCHIVE_SHA256, CHANNELS, require_matrix


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def publish_export(output: Path, build):
    """Build outside the target, then publish only a complete export."""
    if output.exists() or output.is_symlink():
        raise FileExistsError("export target already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as scratch:
        staged = Path(scratch) / "complete"
        staged.mkdir()
        result = build(staged)
        if output.exists() or output.is_symlink():
            raise FileExistsError("export target appeared during preparation")
        os.rename(staged, output)
        return result


def export(archive, output, labels=None):
    regular_unique(archive)
    if archive.stat().st_size != ARCHIVE_BYTES or sha256(archive) != ARCHIVE_SHA256:
        raise ValueError("original BCI ZIP bytes/hash mismatch")
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError("export requires a new nonsymlink output directory")
    if output.resolve().is_relative_to(TASK.parents[2].resolve()):
        raise ValueError("export must be outside the repository")
    source = json.loads((TASK / "source_manifest.json").read_text())
    label_source = source.get("evaluation_labels")
    if labels:
        if not label_source:
            raise ValueError("official Test label binding has not been frozen")
        regular_unique(labels)
        if labels.stat().st_size != label_source["bytes"] or sha256(labels) != label_source["sha256"]:
            raise ValueError("original Test label ZIP bytes/hash mismatch")
    def build(staged):
        output = staged
        if labels:
            (output / "evaluator").mkdir(mode=0o700)
        roles = ("train", "valid", "test") if labels else ("train", "valid")
        manifests = {role: {"schema": "bpb-bci-data/1", "profile": PROFILE, "role": role,
                            "source_sha256": ARCHIVE_SHA256, "subjects": []} for role in roles}
        with zipfile.ZipFile(archive) as raw:
            if set(raw.namelist()) != {f"{subject}_comp.mat" for subject in CHANNELS}:
                raise ValueError("unexpected original ZIP entry set")
            for subject, channels in CHANNELS.items():
                variables = ("train_data", "train_dg", "test_data") if labels else ("train_data", "train_dg")
                with raw.open(f"{subject}_comp.mat") as stream:
                    matrices = loadmat(stream, variable_names=variables)
                x = require_matrix(matrices["train_data"], (400000, channels), "train ECoG")
                y = require_matrix(matrices["train_dg"], (400000, 5), "train labels")
                selected = {"train": (x[:319000], y[:319000]), "valid": (x[321000:], y[321000:])}
                if labels:
                    with zipfile.ZipFile(labels) as truth, truth.open(label_source["subjects"][subject]["member"]) as stream:
                        label = loadmat(stream, variable_names=(label_source["subjects"][subject]["variable"],))
                    test_y = require_matrix(label[label_source["subjects"][subject]["variable"]], (200000, 5), "Test labels")
                    selected["test"] = (require_matrix(matrices["test_data"], (200000, channels), "Test ECoG"), test_y)
                for role, pair in selected.items():
                    role_root = output / ("evaluator" if role == "test" else "public") / role
                    directory = role_root / subject
                    directory.mkdir(parents=True)
                    if role == "test":
                        role_root.chmod(0o700)
                        directory.chmod(0o700)
                    record = {"subject": subject, "native_input_dtype": str(pair[0].dtype), "files": {}}
                    for name, array, dtype in zip(("x.npy", "y.npy"), pair, (np.int32, np.float64)):
                        if name == "x.npy" and array.dtype in (np.dtype("int16"), np.dtype("int32")):
                            # Official MAT files mix int16 and int32 across subjects/roles.
                            # Widen int16 losslessly; record native dtype in the manifest.
                            array = array.astype(np.int32, copy=False)
                        elif array.dtype != np.dtype(dtype):
                            raise ValueError("unexpected native BCI dtype; do not silently convert")
                        path = directory / name
                        with path.open("xb") as stream:
                            np.save(stream, np.ascontiguousarray(array), allow_pickle=False)
                        if role == "test":
                            path.chmod(0o600)
                        record["files"][name] = {"path": f"{subject}/{name}", "bytes": path.stat().st_size,
                                                  "sha256": sha256(path), "dtype": str(array.dtype), "shape": list(array.shape)}
                    manifests[role]["subjects"].append(record)
        for role, manifest in manifests.items():
            if role == "test":
                manifest["labels_sha256"] = label_source["sha256"]
            manifest_path = output / ("evaluator" if role == "test" else "public") / role / "manifest.json"
            write_json(manifest_path, manifest)
            if role == "test":
                manifest_path.chmod(0o600)
        return roles

    roles = publish_export(output, build)
    print(json.dumps({"output": str(output), "roles": list(roles), "arrays": 6 * len(roles)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--labels", type=Path, help="owner only; never provided to public setup")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export(args.archive, args.output, args.labels)
