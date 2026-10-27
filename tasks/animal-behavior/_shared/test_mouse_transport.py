"""Transport-only fixtures; no research arrays or network access."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from mouse_transport import encoded, transport_metadata


def hosted_task_metadata(task: Path, *, public=True, private=True) -> dict:
    """Build synthetic publication metadata for a temporary task fixture."""
    contract = json.loads((task / "contract.json").read_text())
    source = {name: json.loads((task / name).read_text()) for name in ("data.lock", "evaluator.lock")}
    hosted = copy.deepcopy(source)
    card = {"schema": "bpb-mouse-hf-delivery/1", "task_id": contract["task_id"],
            "content_revision": contract["revision"], "transport_only": True,
            "public": {"repo_id": "BrainPilot-Bench/Tasks-Data-Public", "revision": "a" * 40} if public else None,
            "private": {"repo_id": "BrainPilot-Bench/Tasks-Data-Private", "revision": "b" * 40} if private else None,
            "source_bindings": {name: hashlib.sha256((task / name).read_bytes()).hexdigest()
                                for name in ("data.lock", "evaluator.lock", "contract.json", "task.yaml")}}
    for entry in hosted["data.lock"]["datasets"]:
        role = entry["scope"]
        if not card[role]:
            continue
        packet_role = "public" if role == "public" else "evaluator"
        native = entry["uri"].split(f"/{contract['revision']}/{packet_role}/", 1)[1]
        remote = native.removeprefix("public/") if public and role == "public" else native
        entry["uri"] = (f"hf://datasets/{card[role]['repo_id']}@{card[role]['revision']}/"
                        f"tasks/animal-behavior/{contract['task_id']}/{packet_role}/{remote}")
    if private:
        hosted["evaluator.lock"].update(schema="bpb-evaluator-data/1",
                                       repo_id=card["private"]["repo_id"], revision="b" * 40)
    card["hosted_bindings"] = {name: hashlib.sha256(encoded(value)).hexdigest() for name, value in hosted.items()}
    for name, value in hosted.items():
        (task / name).write_bytes(encoded(value))
    (task / "hf-delivery.json").write_bytes(encoded(card))
    return {"source": source, "hosted": hosted, "card": card}


class MouseTransportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bpb-mouse-transport-")
        self.addCleanup(self.tmp.cleanup)
        self.task = Path(self.tmp.name).resolve()
        self.contract = {"task_id": "mabe22-supervised-segmentation", "revision": "d" * 64}
        self.data = {"datasets": [{"scope": role, "uri": f"local://tasks/animal-behavior/{self.contract['task_id']}/{self.contract['revision']}/{packet}/{native}"}
                                  for role, packet, native in (("public", "public", "public/pose/train/a.npz"),
                                                               ("private", "evaluator", "owner/test_labels.npz"))]}
        self.evaluator = {"schema": "bpb-evaluator-source/1", "task_id": self.contract["task_id"],
                          "repo_id": "local-prepared", "revision": self.contract["revision"], "files": []}
        for name, value in (("contract.json", self.contract), ("data.lock", self.data), ("evaluator.lock", self.evaluator)):
            (self.task / name).write_bytes(encoded(value))
        (self.task / "task.yaml").write_text("# fixture only\n")

    def test_source_metadata_is_unchanged_without_sidecar(self):
        self.assertEqual(transport_metadata(self.task, self.contract, self.data, self.evaluator), (self.data, self.evaluator))

    def test_hosted_metadata_normalizes_remote_public_only(self):
        result = hosted_task_metadata(self.task)
        actual = transport_metadata(self.task, self.contract, self.data, self.evaluator)
        self.assertEqual(actual, (result["hosted"]["data.lock"], result["hosted"]["evaluator.lock"]))
        self.assertIn("/public/pose/train/", actual[0]["datasets"][0]["uri"])
        self.assertIn("/evaluator/owner/test_labels", actual[0]["datasets"][1]["uri"])

    def test_public_only_retains_local_owner_binding(self):
        hosted_task_metadata(self.task, private=False)
        data, evaluator = transport_metadata(self.task, self.contract, self.data, self.evaluator)
        self.assertEqual(data["datasets"][1], self.data["datasets"][1])
        self.assertEqual(evaluator, self.evaluator)

    def test_wrong_destination_or_bindings_are_rejected(self):
        base = hosted_task_metadata(self.task)["card"]
        for change in (lambda c: c["public"].update(repo_id="other/repo"),
                       lambda c: c["private"].update(revision="main"),
                       lambda c: c["source_bindings"].update({"data.lock": "0" * 64}),
                       lambda c: c["hosted_bindings"].update({"evaluator.lock": "0" * 64})):
            card = copy.deepcopy(base)
            change(card)
            (self.task / "hf-delivery.json").write_bytes(encoded(card))
            with self.assertRaises(ValueError):
                transport_metadata(self.task, self.contract, self.data, self.evaluator)


if __name__ == "__main__":
    unittest.main()
