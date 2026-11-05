"""Local-only CalMS21 Task 2/3 delivery locks and row iteration.

The public package contains a verified public manifest and a local:// data
lock. Owner Test has a separate, explicit package. Neither copies NPZ files
into an Agent workspace or publishes the source data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from calms_family_prepare import _assert_no_symlink_ancestors, _file_digest, _read_json, _write_json, verify_prepared


def iter_rows(manifest: dict[str, object], role: str, *, group: str | None = None) -> list[dict[str, object]]:
    """Return deterministic rows from a verified family manifest."""
    schema = manifest.get("schema")
    if schema == "bpb-calms21-family-public/1" and role in ("train", "valid"):
        rows = manifest["splits"][role]
    elif schema == "bpb-calms21-family-owner-test/1" and role == "test":
        rows = manifest["sequences"]
    else:
        raise ValueError("manifest schema or requested role mismatch")
    if not isinstance(rows, list):
        raise ValueError("invalid manifest rows")
    if group is not None and group not in manifest["vocab_by_group"]:
        raise ValueError("unknown group")
    selected = [row for row in rows if group is None or row["group"] == group]
    return sorted(selected, key=lambda row: (row["group"], row["id"]))


def create_delivery(prepared_root: Path, output: Path, *, owner: bool = False) -> dict[str, object]:
    """Create a lightweight, local pointer package from an already verified tree."""
    verify_prepared(prepared_root, include_owner=owner)
    source = prepared_root / ("owner/test-manifest.json" if owner else "public/manifest.json")
    manifest = _read_json(source)
    _assert_no_symlink_ancestors(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("delivery output must be fresh")
    output.mkdir(mode=0o700, parents=True)
    name = "owner-test-manifest.json" if owner else "public-manifest.json"
    _write_json(output / name, manifest)
    subtree = (prepared_root / ("owner/test" if owner else "public")).absolute()
    lock = {"schema": "bpb-calms21-family-local-delivery/1",
            "role": "owner-test" if owner else "public",
            "task": manifest["task"], "source_sha256": manifest["source_sha256"],
            "data_url": "local://" + str(subtree),
            "manifest_file": name, "manifest_sha256": _file_digest(output / name)[1],
            "owner_test_included": bool(owner), "copied_npz": False}
    _write_json(output / "data.lock", lock)
    return lock


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--public", action="store_true", help="verified public-only package")
    scope.add_argument("--owner", action="store_true", help="explicit owner Test package")
    args = parser.parse_args()
    result = create_delivery(args.prepared, args.output, owner=args.owner)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
