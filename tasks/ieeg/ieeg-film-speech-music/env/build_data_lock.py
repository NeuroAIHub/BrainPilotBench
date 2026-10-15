#!/usr/bin/env python3
"""Write a local derived-data lock after all source and export hashes are verified."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from fetch_full import SOURCE, verify

ROOT = Path(__file__).resolve().parents[1]


def entry(name: str, uri: str, sha256: str, size: int, scope: str, format_name: str) -> list[str]:
    return [f"  - name: {name}", f"    uri: {uri}", f"    sha256: {sha256}",
            f"    bytes: {size}", f"    format: {format_name}", f"    scope: {scope}"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "data.lock")
    args = parser.parse_args()
    receipt = json.loads((args.data_root / "source_receipt.json").read_text())
    derived = args.data_root / "derived-v2"
    common = json.loads((derived / "owner" / "common_contract.json").read_text())
    if common != json.loads((ROOT / "contract.json").read_text()):
        raise ValueError("The owner contract differs from the tracked contract")
    if len(receipt["files"]) != 306 or not common["test_exported"]:
        raise ValueError("The source or owner Test export is incomplete")
    lines = ["# Clinical ds003688 v1.0.7 sources and guarded-window derived files.",
             "# Raw files contain intervals from every split. Only the owner fetches raw sources.",
             "# Rebuild derived local:// files with env/fetch_full.py and env/prepare_full.py.",
             "# Source Git commit: " + SOURCE["source_git_commit"], "datasets:"]
    for record in SOURCE["records"]:
        for role, spec in record["files"].items():
            path = args.data_root / "source" / spec["path"]
            digest = verify(path, spec)
            if receipt["files"][spec["path"]] != {"bytes": spec["bytes"], "sha256": digest}:
                raise ValueError("The source receipt differs from actual bytes")
            name = spec["path"].replace("/", "__")
            lines.extend(entry(name, spec["url"], digest, spec["bytes"], "private",
                               spec["path"].rsplit(".", 1)[-1]))
    for role in ("train", "validation"):
        manifest_path = derived / common["roles"][role]["path"]
        manifest = json.loads(manifest_path.read_text())
        for record in manifest["subjects"]:
            subject_id = record["subject_id"]
            for kind in ("arrays", "labels"):
                spec = record["files"][kind]
                relative = f"{subject_id}/{spec['path']}"
                lines.extend(entry(relative.replace("/", "__"),
                                   f"local://derived-v2/public/{relative}",
                                   spec["sha256"], spec["bytes"], "public",
                                   spec["path"].rsplit(".", 1)[-1]))
            if role == "train":
                metadata = derived / "public" / subject_id / "metadata.json"
                digest = hashlib.sha256(metadata.read_bytes()).hexdigest()
                metadata_spec = record["files"]["metadata"]
                if digest != metadata_spec["sha256"] or metadata.stat().st_size != metadata_spec["bytes"]:
                    raise ValueError("Public metadata differs from the bound role manifest")
                relative = f"{subject_id}/metadata.json"
                lines.extend(entry(relative.replace("/", "__"),
                                   f"local://derived-v2/public/{relative}", digest,
                                   metadata_spec["bytes"], "public", "json"))
        spec = common["roles"][role]
        name = f"{role}_manifest.json"
        lines.extend(entry(name, f"local://derived-v2/public/{name}",
                           spec["sha256"], spec["bytes"], "public", "json"))
    args.output.write_text("\n".join(lines) + "\n")
    print(json.dumps({"source_files": len(receipt["files"]), "public_subjects": common["eligible_subjects"],
                      "lock": str(args.output)}))


if __name__ == "__main__":
    main()
