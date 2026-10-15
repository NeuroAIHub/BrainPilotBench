#!/usr/bin/env python3
"""Copy the verified owner contract into the task for candidate acceptance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    args = parser.parse_args()
    source = args.data_root / "derived-v2" / "owner" / "common_contract.json"
    value = json.loads(source.read_text())
    if value.get("schema") != "bpb-ieeg-film-common-contract/2" or not value.get("test_exported"):
        raise ValueError("The full owner contract is incomplete")
    target = ROOT / "contract.json"
    if target.exists() and target.read_bytes() != source.read_bytes():
        raise ValueError("The tracked contract already binds a different export")
    if not target.exists():
        shutil.copyfile(source, target)
    print(json.dumps({"status": "single_common_contract_frozen", "path": str(target)}))


if __name__ == "__main__":
    main()
