#!/usr/bin/env python3
"""Prepare the labeled portion of official BCI Competition IV Dataset 4."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import urllib.request
import zipfile

ARCHIVE_URL = "https://www.bbci.de/competition/download/competition_iv/BCICIV_4_mat.zip"
ARCHIVE_NAME = "BCICIV_4_mat.zip"
ARCHIVE_BYTES = 206_367_150
ARCHIVE_SHA256 = "cf734300ad415f81350b75d1606fea42d9e552543fb42b0a8c09754ea522cbc6"
CHANNELS = {"sub1": 62, "sub2": 48, "sub3": 64}
TRAIN_END = 319_000
VALID_START = 321_000
LABELED_END = 400_000
REPO_ROOT = Path(__file__).resolve().parents[4]
CACHE_ROOT = REPO_ROOT / ".cache"


def reject_symlinks(path: Path) -> None:
    current = CACHE_ROOT
    if current.is_symlink():
        raise ValueError(f"Cache root must not be a symlink: {current}")
    for component in path.relative_to(CACHE_ROOT).parts:
        current = current / component
        if current.is_symlink():
            raise ValueError(f"Cache path must not contain a symlink: {current}")


def validate_cache_dir(path: Path) -> Path:
    normalized = Path(os.path.abspath(path))
    if normalized == CACHE_ROOT or not normalized.is_relative_to(CACHE_ROOT):
        raise ValueError(f"Cache directory must be a named owner directory below {CACHE_ROOT}")
    reject_symlinks(normalized)
    return normalized


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


RANGE_RE = re.compile(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)\Z")


def write_transfer_receipt(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile("w", prefix=".bci-transfer-", dir=path.parent,
                                     delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_archive(path: Path, *, url: str = ARCHIVE_URL,
                  expected_bytes: int = ARCHIVE_BYTES,
                  expected_sha256: str = ARCHIVE_SHA256,
                  deadline_seconds: int = 3600,
                  chunk_bytes: int = 1024 * 1024) -> None:
    """Resume one receipted source transfer; preserve partial bytes on failure."""
    if expected_bytes <= 0 or deadline_seconds <= 0 or not 1 <= chunk_bytes <= 4 * 1024 * 1024:
        raise ValueError("Invalid bounded transfer configuration")
    partial = path.with_suffix(path.suffix + ".partial")
    receipt_path = path.with_suffix(path.suffix + ".partial.json")
    reject_symlinks(path)
    reject_symlinks(partial)
    reject_symlinks(receipt_path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Refusing to overwrite {path}")
    if partial.exists() != receipt_path.exists():
        raise ValueError("Partial source and transfer receipt must exist together")
    if partial.exists():
        for candidate in (partial, receipt_path):
            info = candidate.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Partial source or transfer receipt is not a unique regular file")
        receipt = json.loads(receipt_path.read_text())
        if (receipt.get("schema") != "bpb-bci-source-transfer/1" or
                receipt.get("url") != url or receipt.get("expected_bytes") != expected_bytes or
                receipt.get("expected_sha256") != expected_sha256 or
                receipt.get("received_bytes") != partial.stat().st_size or
                not 0 <= receipt["received_bytes"] <= expected_bytes or
                receipt.get("prefix_sha256") != sha256_file(partial)):
            raise ValueError("Partial source differs from its transfer receipt")
        offset = receipt["received_bytes"]
    else:
        offset = 0
        receipt = {"schema": "bpb-bci-source-transfer/1", "url": url,
                   "expected_bytes": expected_bytes, "expected_sha256": expected_sha256,
                   "received_bytes": 0, "prefix_sha256": hashlib.sha256(b"").hexdigest(),
                   "etag": None}
    if offset == expected_bytes:
        if receipt["prefix_sha256"] != expected_sha256:
            raise ValueError("Complete partial source SHA-256 differs from the pinned archive")
    else:
        headers = {"User-Agent": "BrainPilotBench-source-preparation/1"}
        if offset:
            headers["Range"] = f"bytes={offset}-{expected_bytes - 1}"
            if receipt.get("etag"):
                headers["If-Match"] = receipt["etag"]
        deadline = time.monotonic() + deadline_seconds
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
            if offset:
                match = RANGE_RE.fullmatch(response.headers.get("Content-Range", ""))
                if (response.status != 206 or match is None or
                        tuple(map(int, match.groups())) != (offset, expected_bytes - 1, expected_bytes)):
                    raise ValueError("Official source did not honor the exact resume range")
            elif response.status != 200 or response.headers.get("Content-Range"):
                raise ValueError("Official source did not return a complete initial response")
            reported_length = response.headers.get("Content-Length")
            if reported_length is not None and int(reported_length) != expected_bytes - offset:
                raise ValueError("Official source response length differs from the pinned size")
            etag = response.headers.get("ETag")
            if offset and receipt.get("etag") and etag != receipt["etag"]:
                raise ValueError("Official source ETag changed before resume")
            if not offset:
                receipt["etag"] = etag
                with partial.open("xb"):
                    pass
                write_transfer_receipt(receipt_path, receipt)
            digest = hashlib.sha256()
            if offset:
                with partial.open("rb") as previous:
                    for block in iter(lambda: previous.read(1024 * 1024), b""):
                        digest.update(block)
            total = offset
            with partial.open("ab") as target:
                while total < expected_bytes:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Official source transfer exceeded its one-hour deadline")
                    block = response.read(min(chunk_bytes, expected_bytes - total))
                    if not block:
                        raise ValueError("Official source response ended before the pinned size")
                    target.write(block)
                    target.flush()
                    digest.update(block)
                    total += len(block)
                    receipt["received_bytes"] = total
                    receipt["prefix_sha256"] = digest.hexdigest()
                    write_transfer_receipt(receipt_path, receipt)
            if response.read(1):
                raise ValueError("Official source response exceeds the pinned size")
    if partial.stat().st_size != expected_bytes or sha256_file(partial) != expected_sha256:
        raise ValueError("Official archive SHA-256 differs from the recorded source")
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Refusing to overwrite {path}")
    completed_receipt = path.with_suffix(path.suffix + ".fetch.json")
    if completed_receipt.exists() or completed_receipt.is_symlink():
        raise FileExistsError("Completed transfer receipt already exists")
    os.replace(partial, path)
    os.replace(receipt_path, completed_receipt)


def require_matrix(values: object, shape: tuple[int, int], name: str) -> np.ndarray:
    import numpy as np

    array = np.asarray(values)
    if array.shape != shape:
        raise ValueError(f"{name} has shape {array.shape}, expected {shape}")
    if not np.issubdtype(array.dtype, np.number) or not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite numeric values")
    return array


def save_array(path: Path, values: np.ndarray) -> dict[str, object]:
    import numpy as np

    reject_symlinks(path)
    with path.open("xb") as stream:
        np.save(stream, values, allow_pickle=False)
    return {
        "path": str(path),
        "shape": list(values.shape),
        "dtype": str(values.dtype),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def verified_archive(cache_dir: Path) -> tuple[Path, bool]:
    """Get the pinned ZIP without opening any MATLAB variables."""
    archive = cache_dir / ARCHIVE_NAME
    reject_symlinks(archive)
    cached = archive.exists()
    if not cached:
        fetch_archive(archive)
    if archive.stat().st_size != ARCHIVE_BYTES or sha256_file(archive) != ARCHIVE_SHA256:
        raise ValueError("The local ZIP does not match the recorded official archive")
    return archive, cached


def prepare(cache_dir: Path) -> None:
    from scipy.io import loadmat

    archive, _ = verified_archive(cache_dir)

    output = cache_dir / "prepared"
    reject_symlinks(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing to overwrite prepared data in {output}")
    output.mkdir()
    receipt: dict[str, object] = {
        "schema": "bpb-invasive-preparation-receipt/1",
        "task_id": "ieeg-finger-flexion-bciciv4",
        "source_url": ARCHIVE_URL,
        "source_sha256": ARCHIVE_SHA256,
        "source_terms_acknowledged": True,
        "source_citation": "Schalk et al., Decoding Two-Dimensional Movement Trajectories Using Electrocorticographic Signals in Humans, Journal of Neural Engineering 4:264-275 (2007)",
        "source_variables_read": ["train_data", "train_dg"],
        "guard_samples_each_side": 1000,
        "files": {},
    }
    with zipfile.ZipFile(archive) as source:
        actual = set(source.namelist())
        expected = {f"{subject}_comp.mat" for subject in CHANNELS}
        if actual != expected:
            raise ValueError(f"Unexpected official ZIP entry names: {sorted(actual)}")
        for subject, channels in CHANNELS.items():
            entry = f"{subject}_comp.mat"
            # loadmat skips test_data. The prepared output contains no original evaluation data.
            with source.open(entry) as member:
                matrices = loadmat(member, variable_names=("train_data", "train_dg"))
            ecog = require_matrix(matrices.get("train_data"), (LABELED_END, channels), f"{subject} train_data")
            flexion = require_matrix(matrices.get("train_dg"), (LABELED_END, 5), f"{subject} train_dg")
            subject_dir = output / subject
            reject_symlinks(subject_dir)
            subject_dir.mkdir()
            files = {
                "train_ecog": save_array(subject_dir / "train_ecog.npy", ecog[:TRAIN_END]),
                "train_flexion": save_array(subject_dir / "train_flexion.npy", flexion[:TRAIN_END]),
                "valid_ecog": save_array(subject_dir / "valid_ecog.npy", ecog[VALID_START:]),
                "valid_flexion": save_array(subject_dir / "valid_flexion.npy", flexion[VALID_START:]),
            }
            receipt["files"][subject] = files
            print(f"{subject}: train {TRAIN_END} samples, valid {LABELED_END - VALID_START} samples")
    receipt_path = output / "preparation_receipt.json"
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(f"Preparation receipt: {receipt_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True, help="Local ignored cache for the source and prepared data")
    parser.add_argument("--accept-source-terms", action="store_true", help="Acknowledge the citation and attribution terms on the official download page")
    parser.add_argument("--plan", action="store_true", help="Print source and split metadata without network or file writes")
    parser.add_argument("--download-only", action="store_true",
                        help="Fetch or verify the pinned ZIP without legacy array preparation")
    args = parser.parse_args()
    cache_dir = validate_cache_dir(args.cache_dir)
    if args.plan:
        print(json.dumps({
            "source_url": ARCHIVE_URL,
            "source_bytes": ARCHIVE_BYTES,
            "source_sha256": ARCHIVE_SHA256,
            "cache_dir": str(cache_dir),
            "subjects": CHANNELS,
            "source_variables_to_read": [] if args.download_only else ["train_data", "train_dg"],
            "train_samples_per_subject": TRAIN_END,
            "valid_samples_per_subject": LABELED_END - VALID_START,
            "guard_samples_each_side": 1000,
            "download_only": args.download_only,
            "legacy_preparation": not args.download_only,
            "download_requires_source_terms_acknowledgment": True,
        }, indent=2))
        return
    if not args.accept_source_terms:
        parser.error("Read the official download terms, then pass --accept-source-terms")
    cache_dir.mkdir(parents=True, exist_ok=True)
    if args.download_only:
        archive, cached = verified_archive(cache_dir)
        print(json.dumps({"status": "pinned_source_zip_verified", "archive": str(archive),
                          "bytes": ARCHIVE_BYTES, "sha256": ARCHIVE_SHA256,
                          "cache_reused": cached, "source_variables_read": [],
                          "legacy_prepared_created": False}, sort_keys=True))
        return
    prepare(cache_dir)


if __name__ == "__main__":
    main()
