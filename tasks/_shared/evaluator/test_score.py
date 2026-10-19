"""Private dispatcher contract tests; no private data or Docker is used."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("score.py")
SPEC = importlib.util.spec_from_file_location("bpb_private_dispatch", MODULE_PATH)
DISPATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DISPATCH)
IMAGE = "sha256:" + "a" * 64


class DispatchTests(unittest.TestCase):
    def setUp(self):
        materialization = patch.object(DISPATCH, "verify_materialization_data", return_value={})
        materialization.start()
        self.addCleanup(materialization.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root / "bundle/artifacts"
        submission = self.artifacts / "submission"
        submission.mkdir(parents=True)
        for name in DISPATCH.MODEL_FILES:
            (submission / name).write_bytes(name.encode())
        self.data = self.root / "evaluator"
        (self.data / "test").mkdir(parents=True)
        self.freeze = self.root / "freeze.json"
        self.task_id = "ieeg-finger-flexion-bciciv4"
        self.task = DISPATCH.ROOT / "tasks/ieeg/ieeg-finger-flexion-bciciv4"
        self.refreeze()

    def refreeze(self):
        self.freeze.write_text(json.dumps({"schema": "bpb-private-submission-freeze/1",
                                           "task_id": self.task_id,
                                           "task_version": DISPATCH.task_version(self.task),
                                           "files": DISPATCH.artifact_snapshot(self.artifacts)}))

    def test_freeze_rejects_mutation_extra_file_and_symlink(self):
        self.assertEqual(DISPATCH.verify_freeze(self.task_id, self.artifacts, self.freeze),
                         DISPATCH.artifact_snapshot(self.artifacts))
        new = self.artifacts / "extra.txt"
        new.write_text("extra")
        with self.assertRaisesRegex(ValueError, "differ"):
            DISPATCH.verify_freeze(self.task_id, self.artifacts, self.freeze)
        new.unlink()
        (self.artifacts / "submission/model.py").write_text("mutated")
        with self.assertRaisesRegex(ValueError, "differ"):
            DISPATCH.verify_freeze(self.task_id, self.artifacts, self.freeze)
        (self.artifacts / "submission/model.py").unlink()
        (self.artifacts / "submission/model.py").symlink_to("config.json")
        with self.assertRaisesRegex(ValueError, "link"):
            DISPATCH.verify_freeze(self.task_id, self.artifacts, self.freeze)

    def test_task_id_and_source_only_rejection(self):
        self.assertEqual(DISPATCH.task_identity(self.task), self.task_id)
        for source_only in (
                DISPATCH.ROOT / "tasks/psychology/psych101-steingroever2015data-exp2",
                DISPATCH.ROOT / "tasks/mri/tops-fmri",
                DISPATCH.ROOT / "tasks/intracortical/falcon-h1-reach-grasp"):
            with self.assertRaisesRegex(ValueError, "unsupported"):
                DISPATCH.task_identity(source_only)

    def test_bci_uses_test_role_docker_and_legacy_receipt(self):
        def scorer(command, **_):
            self.assertEqual(command[command.index("--role") + 1], "test")
            self.assertIn("--owner-test", command)
            self.assertEqual(command[command.index("--data") + 1], str((self.data / "test").resolve()))
            self.assertEqual(command[command.index("--image") + 1], IMAGE)
            receipt = json.loads(Path(command[command.index("--frozen") + 1]).read_text())
            self.assertEqual(receipt["schema"], "bpb-bci-frozen-artifact/1")
            expected = hashlib.sha256(b"model.py").hexdigest()
            self.assertEqual(receipt["files"]["model.py"]["sha256"], expected)
            return json.dumps({"pearson_r": 0.25})

        with patch.dict("os.environ", {"BPB_INFERENCE_IMAGE": IMAGE}), patch.object(
                DISPATCH, "run_scorer", side_effect=scorer):
            self.assertEqual(DISPATCH.score(self.task, self.artifacts, self.data, self.freeze),
                             {"pearson_r": 0.25})

    def test_film_owner_files_are_new_and_removed(self):
        self.task_id = "ieeg-film-speech-music"
        self.task = DISPATCH.ROOT / "tasks/ieeg/ieeg-film-speech-music"
        owner = self.data / "derived-v2/owner"
        owner.mkdir(parents=True)
        self.refreeze()

        def scorer(command, **_):
            receipt = Path(command[command.index("--frozen-submission-receipt") + 1])
            report = Path(command[command.index("--report-out") + 1])
            self.assertEqual(receipt.parent, owner.resolve())
            self.assertEqual(report.parent, owner.resolve())
            self.assertEqual(json.loads(receipt.read_text())["schema"],
                             "bpb-ieeg-film-frozen-submission/1")
            report.write_text(json.dumps({"value": 0.75}))
            return ""

        with patch.dict("os.environ", {"BPB_INFERENCE_IMAGE": IMAGE}), patch.object(
                DISPATCH, "run_scorer", side_effect=scorer):
            self.assertEqual(DISPATCH.score(self.task, self.artifacts, self.data, self.freeze),
                             {"balanced_accuracy": 0.75})
        self.assertEqual(list(owner.glob(".dispatch-*")), [])

    def test_falcon_sequence_report_uses_owner_test(self):
        self.task_id = "falcon-h2-handwriting"
        self.task = DISPATCH.ROOT / "tasks/intracortical/falcon-h2-handwriting"
        self.refreeze()

        def scorer(command, **_):
            self.assertEqual(command[command.index("--sequence-task") + 1], "h2")
            self.assertIn("--owner-test", command)
            self.assertEqual(command[command.index("--data-manifest") + 1],
                             str((self.data / "test/manifest.json").resolve()))
            report = Path(command[command.index("--report-output") + 1])
            report.write_text(json.dumps({"metrics": {"WER": {"mean": 0.5},
                                                      "CER": {"mean": 0.25}}}))
            return ""

        with patch.dict("os.environ", {"BPB_INFERENCE_IMAGE": IMAGE}), patch.object(
                DISPATCH, "run_scorer", side_effect=scorer):
            self.assertEqual(DISPATCH.score(self.task, self.artifacts, self.data, self.freeze),
                             {"WER": 0.5, "CER": 0.25})

    def test_prepared_data_is_verified_before_and_after_scoring(self):
        self.task_id = "brain-age-mri"
        self.task = DISPATCH.ROOT / "tasks/mri/brain-age-mri"
        self.refreeze()
        prepared = self.data / "prepared"
        prepared.mkdir()
        receipt = {"schema": "bpb-private-prepared/1"}
        calls = []

        def verify(_task, _data):
            calls.append("verify")
            if calls.count("verify") == 2:
                raise ValueError("prepared private data differs from source-bound receipt")
            return prepared, receipt

        def scorer(_command, **_):
            calls.append("score")
            return f"{DISPATCH.START}\n{{\"test_mae\": 1.0}}\n{DISPATCH.END}\n"

        with patch.dict("os.environ", {"BPB_INFERENCE_IMAGE": IMAGE}), patch.object(
                DISPATCH, "verify_prepared_data", side_effect=verify), patch.object(
                DISPATCH, "run_scorer", side_effect=scorer):
            with self.assertRaisesRegex(ValueError, "prepared private data differs"):
                DISPATCH.score(self.task, self.artifacts, self.data, self.freeze)
        self.assertEqual(calls, ["verify", "score", "verify"])


if __name__ == "__main__":
    unittest.main()
