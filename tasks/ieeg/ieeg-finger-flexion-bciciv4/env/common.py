"""Trusted BCI data and submission validation helpers. No submitted imports."""
import importlib.util
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
PROFILE = "bpb-bciciv4-offline-guarded-v1"
_path = TASK.parents[1] / "intracortical/falcon-h1-reach-grasp/checks/score.py"
_spec = importlib.util.spec_from_file_location("bpb_trusted_h1_validation", _path)
validation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validation)
sha256 = validation.sha256
bound_file = validation.bound_file
confined = validation.confined
regular_unique = validation.regular_unique


def read_role(root, role):
    import json
    import numpy as np
    contract = json.loads((TASK / "contract.json").read_text())
    if (contract.get("profile") != PROFILE or contract.get("task_id") != TASK.name or
            contract.get("schema") != "bpb-bci-contract/1" or
            contract.get("task_version") != "0.1-public-validation-offline" or
            contract.get("protocol_sha256") != sha256(TASK / "protocol.json") or
            contract.get("source_manifest_sha256") != sha256(TASK / "source_manifest.json")):
        raise ValueError("unsupported BCI contract")
    manifest_path = root / "manifest.json"
    bound_file(manifest_path, contract["manifests"][role], max_bytes=100_000)
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("profile") != PROFILE or manifest.get("role") != role or
            manifest.get("schema") != "bpb-bci-data/1" or
            [r.get("subject") for r in manifest.get("subjects", [])] != ["sub1", "sub2", "sub3"]):
        raise ValueError("BCI manifest identity, role, or subjects mismatch")
    size = {"train": 319000, "valid": 79000, "test": 200000}[role]
    loaded = []
    for record, channels in zip(manifest["subjects"], (62, 48, 64)):
        if set(record["files"]) != {"x.npy", "y.npy"}:
            raise ValueError("unexpected BCI file set")
        arrays = {}
        for name, width, dtype in (("x.npy", channels, "int32"), ("y.npy", 5, "float64")):
            entry = record["files"][name]
            path = confined(root, entry["path"])
            bound_file(path, entry, max_bytes=100_000_000)
            values = np.load(path, mmap_mode="r", allow_pickle=False)
            if (list(values.shape) != [size, width] or entry["shape"] != [size, width] or
                    str(values.dtype) != dtype or entry["dtype"] != dtype or not np.isfinite(values).all()):
                raise ValueError("BCI shape, dtype, or finite-value mismatch")
            arrays[name] = values
        loaded.append((record, arrays))
    return manifest, loaded
