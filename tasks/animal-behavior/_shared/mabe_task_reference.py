"""Build a small frozen MABe reference using only the Agent's public packet."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from mabe_inference import MODEL_FILES, snapshot_model
from mabe_model_reference import export
from mabe_task_common import exact_packet, load_contract, stage_public_cache


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    packet = parser.add_mutually_exclusive_group(required=True)
    packet.add_argument("--public-dir", type=Path)
    packet.add_argument("--public-cache", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    contract = load_contract(args.task)
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("fresh submission directory required")
    mode = ("supervised" if contract["task_id"] == "mabe22-supervised-segmentation"
            else "representation")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bpb-mabe-public-reference-",
                                     dir=args.output.parent.resolve()) as temporary:
        public_dir = Path(temporary) / "packet" if args.public_cache else args.public_dir
        if args.public_cache:
            stage_public_cache(args.task, contract, public_dir)
        else:
            exact_packet(public_dir, contract, evaluator=False)
        frozen = Path(temporary) / "frozen"
        evidence = export(public_dir, frozen, mode,
                          packet_sha=contract["public_manifest_sha256"])
        before = snapshot_model(frozen)
        args.output.mkdir(mode=0o700, parents=True)
        for name in MODEL_FILES:
            with (frozen / name).open("rb") as reader, os.fdopen(os.open(args.output / name,
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as writer:
                shutil.copyfileobj(reader, writer)
        if snapshot_model(args.output, frozen=False) != before:
            raise ValueError("reference artifact copy mismatch")
    print(json.dumps({"mode": mode, "submission": str(args.output),
                      "source": evidence["source"],
                      "public_packet_sha256": contract["public_manifest_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
