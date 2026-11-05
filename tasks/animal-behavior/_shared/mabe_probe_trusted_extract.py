"""Isolated conversion of the original six classification labels and poses.

Run only in the documented no-network container. Test labels stay in owner/;
Agent-facing pose and train labels are numeric-only NPZ files.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

SOURCE_MD5 = {
    "mouse_submission_keypoints.npy": "68a9fe1fe71225787a4dae6369acc9dc",
    "mouse_submission_labels.npy": "7f10c2b676e7dd8b4348423f0ee0aa8a",
    "mouse_frame_number_map.npy": "ffc1dcae90176cdac4ff4fe123e18f25",
}
REPO_SHA256 = {
    "mouse_behaviors_labels.npy": "cae4936eee6213f7b5247dd14c021221c9ddbe12df69de7a150d906111ee207f",
    "mouse_behaviors_frame_map.npy": "7d4c6f891050ac5e6816a5d501c9bb6ea05b7d5f18bc5018a7981c61b4aee82a",
    "original_strain_split.json": "ef306e4f369f72b64a53df8f00b45747b50554678dd08b7300553c36feb22eaf",
    "original_lights_split.json": "ef306e4f369f72b64a53df8f00b45747b50554678dd08b7300553c36feb22eaf",
    "original_chase_split.json": "049f99e3ffb5b939962654265fda18f01088b6905d1a2f8f237c38df1fe41aa3",
    "original_three_huddle_split.json": "049f99e3ffb5b939962654265fda18f01088b6905d1a2f8f237c38df1fe41aa3",
    "original_face_sniff_split.json": "049f99e3ffb5b939962654265fda18f01088b6905d1a2f8f237c38df1fe41aa3",
    "original_anal_sniff_split.json": "049f99e3ffb5b939962654265fda18f01088b6905d1a2f8f237c38df1fe41aa3",
}
TASKS = {
    "strain": ("official", "strain"),
    "lights": ("official", "lights"),
    "huddle": ("manual", "three_huddle"),
    "chase": ("manual", "chase"),
    "face_sniff": ("manual", "face_sniff"),
    "anogenital_sniff": ("manual", "anal_sniff"),
}
SPLIT_SOURCE = {"huddle": "three_huddle", "anogenital_sniff": "anal_sniff"}
ROLE_KEYS = ("SubmissionTrain", "publicTest", "privateTest")
SEEDS = (0, 1, 2)


def digest(path: Path, kind: str) -> str:
    algo = hashlib.md5() if kind == "md5" else hashlib.sha256()  # noqa: S324: source MD5
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            algo.update(chunk)
    return algo.hexdigest()


def save_npz(path: Path, rows: dict[str, np.ndarray]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as output:
        np.savez_compressed(output, **rows)
    if "owner" in path.parts or "evaluator" in path.parts:
        path.parent.chmod(0o700)
        path.chmod(0o600)
    return digest(path, "sha256")


def frozen_subsets(task: str, ids: list[str]) -> list[list[str]]:
    """BPB v1 policy: sequence units; lowest SHA256 ranks; floor(0.8*N)."""
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate probe train sequence")
    count = (4 * len(ids)) // 5
    return [sorted(sorted(ids, key=lambda video_id: hashlib.sha256(
        f"bpb-mabe-probe-v1/{task}/{seed}/{video_id}".encode()).digest())[:count])
            for seed in SEEDS]


def main() -> None:
    if os.environ.get("MABE_ISOLATED_EXTRACTION") != "1":
        raise RuntimeError("Run only in the documented isolated container")
    root = Path("/data")
    for name, expected in SOURCE_MD5.items():
        if digest(root / name, "md5") != expected:
            raise ValueError(f"Caltech checksum mismatch: {name}")
    for name, expected in REPO_SHA256.items():
        if digest(root / name, "sha256") != expected:
            raise ValueError(f"pinned evaluator asset hash mismatch: {name}")

    # Object NPY unpickling is confined to this no-network container.
    official = np.load(root / "mouse_submission_labels.npy", allow_pickle=True).item()
    official_map = np.load(root / "mouse_frame_number_map.npy", allow_pickle=True).item()
    manual = np.load(root / "mouse_behaviors_labels.npy", allow_pickle=True).item()
    manual_map = np.load(root / "mouse_behaviors_frame_map.npy", allow_pickle=True).item()
    keypoints = np.load(root / "mouse_submission_keypoints.npy", allow_pickle=True).item()["sequences"]
    if official["frame_number_map"] != official_map or manual["frame_number_map"] != manual_map:
        raise ValueError("embedded and separate frame maps differ")
    if set(keypoints) != set(official_map) or len(keypoints) != 1830 or len(manual_map) != 400:
        raise ValueError("unexpected submission pose/label ID membership")
    if not set(manual_map) <= set(official_map):
        raise ValueError("manual behavior IDs are outside submission pose")
    if official["label_array"].shape != (13, 3294000) or manual["label_array"].shape != (4, 720000):
        raise ValueError("unexpected source label dimensions")
    if set(manual["vocabulary"]) != {"chase", "face_sniff", "anal_sniff", "three_huddle"}:
        raise ValueError("unexpected manual behavior vocabulary")

    input_dir = root / "public" / "probe_pose"
    input_dir.mkdir(parents=True, exist_ok=True)
    input_digests = {}
    for video_id in sorted(keypoints):
        pose = keypoints[video_id]["keypoints"]
        if pose.shape != (1800, 3, 12, 2) or pose.dtype.kind not in "iuf" or not np.isfinite(pose).all():
            raise ValueError(f"unexpected keypoints: {video_id}")
        input_digests[video_id] = save_npz(input_dir / f"{video_id}.npz", {"keypoints": pose.astype(np.int32)})

    task_profiles = {}
    label_files = {}
    for task, (source_name, source_label) in TASKS.items():
        split_name = SPLIT_SOURCE.get(task, task)
        split = json.loads((root / f"original_{split_name}_split.json").read_text())
        train = split["SubmissionTrain"]
        test1, test2 = split["publicTest"], split["privateTest"]
        expected_sizes = (1307, 261, 262) if source_name == "official" else (320, 40, 40)
        if tuple(map(len, (train, test1, test2))) != expected_sizes:
            raise ValueError(f"unexpected source split sizes: {task}")
        if len(set(train + test1 + test2)) != sum(expected_sizes):
            raise ValueError(f"source split roles overlap: {task}")
        label_source = official if source_name == "official" else manual
        frame_map = official_map if source_name == "official" else manual_map
        if not set(train + test1 + test2) <= set(frame_map):
            raise ValueError(f"split sequence not mapped: {task}")
        label_index = label_source["vocabulary"].index(source_label)
        for role, ids in zip(ROLE_KEYS, (train, test1, test2)):
            rows = {}
            for video_id in ids:
                start, end = frame_map[video_id]
                if end - start != 1800:
                    raise ValueError(f"unexpected label span: {video_id}")
                label = label_source["label_array"][label_index, start:end]
                if label.shape != (1800,) or not np.isfinite(label).all() or not np.isin(label, (0, 1)).all():
                    raise ValueError(f"nonbinary task label: {task}")
                rows[video_id] = label.astype(np.uint8)
            folder = root / ("evaluator" if role == "SubmissionTrain" else "owner") / "probe_labels"
            path = folder / f"{task}_{role}.npz"
            label_files[f"{task}/{role}"] = {"path": str(path.relative_to(root)),
                                             "sha256": save_npz(path, rows), "videos": len(rows)}
        task_profiles[task] = {
            "source_label_asset": "mouse_submission_labels.npy" if source_name == "official" else "mouse_behaviors_labels.npy",
            "source_label_name": source_label,
            "source_split": f"original_{split_name}_split.json",
            "train_ids": train, "test1_ids": test1, "test2_ids": test2,
            "three_probe_train_subsets": frozen_subsets(task, train),
        }

    profile = {
        "schema": "bpb-mabe-probe-profile/1",
        "name": "BrainPilotBench-MABe22-six-classification-sequence-probe-v1",
        "source_evaluator_sha": "234dae7098314d6035066e3028caedee3f3ee379",
        "sampling": {"unit": "sequence", "fraction": "floor(4*N/5)", "seeds": list(SEEDS),
                     "rank": "ascending SHA256 of bpb-mabe-probe-v1/{task}/{seed}/{video_id}"},
        "comparability": "Paper-aligned Bench adaptation; the paper does not publish these exact subsets, and released evaluator uses a different training/scoring recipe.",
        "tasks": task_profiles,
        "source_hashes": {**SOURCE_MD5, **REPO_SHA256},
        "agent_boundary": "Agent packet contains only numeric pose from public/probe_pose and public/probe_usertrain. evaluator/probe_labels contains probe-training labels and owner/probe_labels contains both Test roles; neither label directory is Agent-readable.",
    }
    profile_path = root / "public" / "probe_profile.json"
    profile_path.write_text(json.dumps(profile, indent=2) + "\n")
    manifest = {"schema": "bpb-mabe-probe-preparation/1", "profile_sha256": digest(profile_path, "sha256"),
                "pose_files": len(input_digests), "pose_sha256_by_video": input_digests,
                "label_files": label_files}
    (root / "probe_preparation_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"pose_files": len(input_digests), "tasks": list(task_profiles),
                      "train_sizes": {task: len(value["train_ids"]) for task, value in task_profiles.items()},
                      "test_labels_owner_only": True}))


if __name__ == "__main__":
    main()
