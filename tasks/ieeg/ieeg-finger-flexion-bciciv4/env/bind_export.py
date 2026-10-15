"""Freeze actual derived metadata; this does not declare runtime acceptance."""
import argparse
import json
from pathlib import Path
from common import PROFILE, TASK, sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    bindings = {}
    datasets = []
    for role in ("train", "valid", "test"):
        folder = args.root / ("evaluator" if role == "test" else "public") / role
        path = folder / "manifest.json"
        manifest = json.loads(path.read_text())
        if manifest.get("profile") != PROFILE or manifest.get("role") != role:
            raise ValueError("unexpected derived profile/role")
        bindings[role] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        entries = [{"path": "manifest.json", **bindings[role]}]
        entries += [entry for record in manifest["subjects"] for entry in record["files"].values()]
        for entry in entries:
            actual = folder / entry["path"]
            if actual.stat().st_size != entry["bytes"] or sha256(actual) != entry["sha256"]:
                raise ValueError("array differs from export receipt")
            location = f"{'evaluator' if role == 'test' else 'public'}/{role}/{entry['path']}"
            datasets.append({"name": "bci-" + role + "-" + entry["path"].replace("/", "-"),
                             "uri": "local://" + location, "sha256": entry["sha256"],
                             "bytes": entry["bytes"], "format": "json" if entry["path"].endswith("json") else "npy",
                             "scope": "private" if role == "test" else "public"})
    contract = {"schema": "bpb-bci-contract/1", "task_id": TASK.name, "source_task_id": "BCI Competition IV Dataset 4",
                "task_version": "0.1-public-validation-offline", "profile": PROFILE,
                "protocol_sha256": sha256(TASK / "protocol.json"),
                "source_manifest_sha256": sha256(TASK / "source_manifest.json"),
                "public_cli_role": "valid", "manifests": bindings, "data_uploaded": False,
                "availability_status": "source_bound_reproducible_export", "official_competition": False,
                "source_isolation_note": "Original evaluation labels are public-origin; kept outside Agent workspace and model selection"}
    for path, value in ((TASK / "contract.json", contract), (TASK / "data.lock", {"datasets": datasets})):
        # JSON is a YAML subset; data.lock remains consumable by the standard CLI.
        path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"manifests": bindings, "public_paths": 14, "owner_paths": 7}))


if __name__ == "__main__":
    main()
