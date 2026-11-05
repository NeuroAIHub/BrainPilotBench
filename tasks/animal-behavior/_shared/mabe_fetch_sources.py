"""Download and verify only the public MABe22 assets used by these candidates.

No videos or unpublished files are fetched. Object NPY files are downloaded as
opaque bytes and must be decoded only by the isolated extraction scripts.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen

CALTECH = "https://data.caltech.edu/api/records/rdsa8-rde65/files"
EVALUATOR = "https://raw.githubusercontent.com/damaggu/MABe2022/234dae7098314d6035066e3028caedee3f3ee379/round2/metadata"
RESIFUSE = "https://raw.githubusercontent.com/BRAINML-GT/ResiFuse/ae4acf51962b1611656da00d3da92a6b02a56ef4/splits/mabe_finetune_split.json"

# name: (source URL, exact bytes, checksum algorithm, published or SHA256 hash)
ASSETS = {
    "mouse_submission_labels.npy": (f"{CALTECH}/mouse_submission_labels.npy/content", 171372184, "md5", "7f10c2b676e7dd8b4348423f0ee0aa8a"),
    "mouse_frame_number_map.npy": (f"{CALTECH}/mouse_frame_number_map.npy/content", 83594, "md5", "ffc1dcae90176cdac4ff4fe123e18f25"),
    "mouse_submission_keypoints.npy": (f"{CALTECH}/mouse_submission_keypoints.npy/content", 948861986, "md5", "68a9fe1fe71225787a4dae6369acc9dc"),
    "mouse_user_train.npy": (f"{CALTECH}/mouse_user_train.npy/content", 417845925, "md5", "389bc12c9ad49b7cb50b531707b448a5"),
    "mabe_finetune_split.json": (RESIFUSE, 3660, "sha256", "ebb486c7351eff8c9ae0fcfd2a21423083d06d0795e2febd2677d000ad4bffc9"),
    "mouse_behaviors_labels.npy": (f"{EVALUATOR}/mouse_new_splits/labels.npy", 23058156, "sha256", "cae4936eee6213f7b5247dd14c021221c9ddbe12df69de7a150d906111ee207f"),
    "mouse_behaviors_frame_map.npy": (f"{EVALUATOR}/mouse_new_splits/frame_number_map.npy", 17812, "sha256", "7d4c6f891050ac5e6816a5d501c9bb6ea05b7d5f18bc5018a7981c61b4aee82a"),
}

_CONDITION_HASH = "ef306e4f369f72b64a53df8f00b45747b50554678dd08b7300553c36feb22eaf"
_MANUAL_HASH = "049f99e3ffb5b939962654265fda18f01088b6905d1a2f8f237c38df1fe41aa3"
for name in ("strain", "lights"):
    ASSETS[f"original_{name}_split.json"] = (f"{EVALUATOR}/mouse_round2_splits/{name}.json", 62805, "sha256", _CONDITION_HASH)
for name in ("chase", "three_huddle", "face_sniff", "anal_sniff"):
    ASSETS[f"original_{name}_split.json"] = (f"{EVALUATOR}/mouse_new_splits/split_files/{name}.json", 17349, "sha256", _MANUAL_HASH)


def checksum(path: Path, kind: str) -> str:
    digest = hashlib.new(kind)  # MD5 matches the published Caltech checksums.
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(root: Path, name: str) -> str:
    url, size, algorithm, expected = ASSETS[name]
    target = root / name
    if target.exists() and target.stat().st_size == size and checksum(target, algorithm) == expected:
        return "cached"
    with tempfile.NamedTemporaryFile(dir=root, prefix=f".{name}.", delete=False) as temporary:
        temp_path = Path(temporary.name)
        try:
            with urlopen(Request(url, headers={"User-Agent": "BrainPilotBench-source-prep/1"}), timeout=180) as response:
                while chunk := response.read(1024 * 1024):
                    temporary.write(chunk)
                    if temporary.tell() > size:
                        raise ValueError(f"source larger than pinned size: {name}")
            temporary.flush()
            if temporary.tell() != size or checksum(temp_path, algorithm) != expected:
                raise ValueError(f"source size/checksum mismatch: {name}")
            os.replace(temp_path, target)
            return "downloaded"
        finally:
            temp_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--asset", choices=("all", *ASSETS), default="all")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    names = ASSETS if args.asset == "all" else (args.asset,)
    result = {name: fetch(args.root, name) for name in names}
    print({"verified": len(result), "downloaded": sum(value == "downloaded" for value in result.values()),
           "cached": sum(value == "cached" for value in result.values())})


if __name__ == "__main__":
    main()
