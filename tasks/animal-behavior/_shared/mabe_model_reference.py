"""Export frozen MABe reference models from public training inputs only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

from mabe_inference import PROBE_ID_RE, _expected_json, _packet_contract, _sha, freeze_model
from mabe_reference import fit as fit_supervised


SUPERVISED_SOURCE = '''"""Public-Train-only pose Ridge reference for MABe supervised clips."""
import numpy as np

def _features(pose):
    xy = pose[..., :2] / 448.0
    confidence = pose[..., 2:]
    raw = np.concatenate((xy, confidence), axis=-1).reshape(1800, 108)
    finite = np.isfinite(raw)
    cleaned = np.nan_to_num(raw, nan=0.0)
    delta = np.zeros_like(cleaned)
    delta[1:] = cleaned[1:] - cleaned[:-1]
    return np.concatenate((cleaned, finite.astype(np.float32), delta), axis=1).astype(np.float32)

class Model:
    def __init__(self, mean, scale, weights):
        self.mean, self.scale, self.weights = mean, scale, weights

    def predict_proba(self, keypoints, scores, context):
        if context["mode"] != "supervised" or context["class_count"] != 4:
            raise ValueError("supervised context mismatch")
        pose = np.concatenate((keypoints, scores[..., None]), axis=-1)
        x = _features(pose)
        x = np.concatenate((((x - self.mean) / self.scale), np.ones((len(x), 1))), axis=1)
        return np.clip(x @ self.weights, 0.0, 1.0)

def load_model(config, weights_path):
    if config != {"schema": "bpb-mabe-reference-config/1", "mode": "supervised"}:
        raise ValueError("reference config mismatch")
    with np.load(weights_path, allow_pickle=False) as data:
        if set(data.files) != {"mean", "scale", "weights"}:
            raise ValueError("reference weight schema")
        return Model(data["mean"], data["scale"], data["weights"])
'''


REPRESENTATION_SOURCE = '''"""Disjoint UserTrain pose PCA reference for MABe embeddings."""
import numpy as np

class Model:
    def __init__(self, mean, components):
        self.mean, self.components = mean, components

    def embed(self, keypoints, scores, context):
        if context["mode"] != "representation" or context["class_count"] != 6:
            raise ValueError("representation context mismatch")
        x = keypoints.reshape(1800, 72).astype(np.float64) / 224.0
        return ((x - self.mean) @ self.components).astype(np.float32)

def load_model(config, weights_path):
    if config != {"schema": "bpb-mabe-reference-config/1", "mode": "representation"}:
        raise ValueError("reference config mismatch")
    with np.load(weights_path, allow_pickle=False) as data:
        if set(data.files) != {"mean", "components"}:
            raise ValueError("reference weight schema")
        return Model(data["mean"], data["components"])
'''


def fit_representation(root: Path, manifest_sha: str | None,
                       packet_sha: str | None = None) -> tuple[np.ndarray, np.ndarray, int]:
    if packet_sha is not None:
        _packet_contract(root, packet_sha, "representation", "agent", None, None, None)
        manifest = _expected_json(root / "manifest.json", packet_sha)
        mapping = {}
        for row in manifest["files"]:
            path = row["path"]
            if path.startswith("public/probe_usertrain/") and path.endswith(".npz"):
                video_id = Path(path).stem
                if path != f"public/probe_usertrain/{video_id}.npz" or video_id in mapping:
                    raise ValueError("UserTrain packet path mismatch")
                mapping[video_id] = row["sha256"]
        if (len(mapping) != 784 or set(row["path"] for row in manifest["files"])
                != {f"public/probe_usertrain/{video_id}.npz" for video_id in mapping}
                   | {"public/probe_profile.json"}):
            raise ValueError("Agent UserTrain packet contains extra or missing files")
    else:
        if manifest_sha is None:
            raise ValueError("trusted UserTrain or packet SHA required")
        manifest = _expected_json(root / "usertrain_preparation_manifest.json", manifest_sha)
        mapping = manifest.get("files")
        if manifest.get("schema") != "bpb-mabe-usertrain-preparation/2" or not isinstance(mapping, dict):
            raise ValueError("disjoint UserTrain preparation contract mismatch")
    if len(mapping) != 784:
        raise ValueError("disjoint UserTrain sequence count mismatch")
    total, summation = 0, np.zeros(72, np.float64)
    gram = np.zeros((72, 72), np.float64)
    for video_id, digest in sorted(mapping.items()):
        if not isinstance(video_id, str) or not PROBE_ID_RE.fullmatch(video_id) or not isinstance(digest, str):
            raise ValueError("UserTrain manifest row mismatch")
        path = root / "public/probe_usertrain" / f"{video_id}.npz"
        if _sha(path)[1] != digest:
            raise ValueError("UserTrain pose SHA-256 mismatch")
        with np.load(path, allow_pickle=False) as source:
            if set(source.files) != {"keypoints"}:
                raise ValueError("UserTrain input contains labels or extra arrays")
            keypoints = source["keypoints"]
        if keypoints.shape != (1800, 3, 12, 2) or keypoints.dtype != np.int32:
            raise ValueError("UserTrain keypoint shape/dtype mismatch")
        x = keypoints.reshape(1800, 72).astype(np.float64) / 224.0
        summation += x.sum(axis=0)
        gram += x.T @ x
        total += len(x)
    mean = summation / total
    covariance = gram / total - np.outer(mean, mean)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    components = eigenvectors[:, np.argsort(eigenvalues)[::-1][:32]].copy()
    for index in range(components.shape[1]):
        anchor = np.argmax(np.abs(components[:, index]))
        if components[anchor, index] < 0:
            components[:, index] *= -1
    return mean, components, total


def export(root: Path, output: Path, mode: str, usertrain_sha: str | None = None,
           packet_sha: str | None = None) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError("fresh reference output required")
    staging = output.with_name(output.name + "-staging")
    if staging.exists() or staging.is_symlink():
        raise FileExistsError("reference staging path exists")
    staging.mkdir(mode=0o700, parents=True)
    if mode == "supervised":
        if packet_sha is not None:
            _packet_contract(root, packet_sha, "supervised", "val", None, None, None)
        mean, scale, weights, train = fit_supervised(root)
        source = SUPERVISED_SOURCE
        arrays = {"mean": mean, "scale": scale, "weights": weights}
        evidence = {"train": train, "source": "public supervised Train only"}
    elif mode == "representation":
        mean, components, frames = fit_representation(root, usertrain_sha, packet_sha)
        source = REPRESENTATION_SOURCE
        arrays = {"mean": mean, "components": components}
        evidence = {"train_videos": 784, "train_frames": frames,
                    "source": "disjoint public UserTrain pose only",
                    "usertrain_manifest_sha256": usertrain_sha,
                    "agent_packet_manifest_sha256": packet_sha}
    else:
        raise ValueError("unknown reference mode")
    (staging / "model.py").write_text(source, encoding="utf-8")
    (staging / "config.json").write_text(json.dumps({"schema": "bpb-mabe-reference-config/1", "mode": mode}), encoding="utf-8")
    with (staging / "weights.npz").open("xb") as stream:
        np.savez(stream, **arrays)
    for file in staging.iterdir():
        os.chmod(file, 0o600)
    evidence["frozen"] = freeze_model(staging, output)
    for file in staging.iterdir():
        file.unlink()
    staging.rmdir()
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=("supervised", "representation"), required=True)
    parser.add_argument("--expected-usertrain-manifest-sha256")
    parser.add_argument("--expected-packet-manifest-sha256")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.root, args.output, args.mode,
                            args.expected_usertrain_manifest_sha256,
                            args.expected_packet_manifest_sha256), sort_keys=True))


if __name__ == "__main__":
    main()
