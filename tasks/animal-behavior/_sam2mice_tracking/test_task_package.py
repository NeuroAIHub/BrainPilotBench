"""Software-only fixtures for review gates, exact packets and owner isolation."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from fetch_sources import ARTICLE, EXPECTED_BYTES, EXPECTED_MD5, FILE_ID, FILE_NAME, SOURCE_URL
from package_task import bind_and_materialize, build_packets
from score_task import _evaluate, build_reference, node_freeze_path, score_private
from sam2mice_transport import HOSTED_AVAILABILITY, REPOS, SOURCE_AVAILABILITY
from task_common import (PROFILE, TASK_ID, digest, encoded, exact_packet, load_contract,
                         stage_evaluator, stage_public_cache, stage_public_workspace, verify_locks)


def private_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o600)


def fixture_source(root: Path) -> None:
    """Construct schema fixtures only. These files are never benchmark data."""
    root.mkdir(mode=0o700)
    pairs = []
    for index in range(9):
        image_name, truth_name = f"raw_frames/{index:05d}.jpg", f"ground_truth/{index:05d}.txt"
        image_path = root / image_name
        image_path.parent.mkdir(mode=0o700, exist_ok=True)
        rgb = np.full((16, 20, 3), 20 + index * 20, dtype=np.uint8)
        Image.fromarray(rgb).save(image_path, format="JPEG")
        image_path.chmod(0o600)
        truth = b"" if index == 0 else b"0 0.5 0.5 0.25 0.25\n"
        private_bytes(root / truth_name, truth)
        pairs.append({"frame_index": index, "image": image_name, "truth": truth_name,
                      "image_sha256": digest(image_path)["sha256"], "truth_sha256": digest(root / truth_name)["sha256"],
                      "width": 20, "height": 16,
                      "image_source_member": f"SAM2_Mice/benchmark_data/openfield_five_mouse/{index:05d}.jpg",
                      "truth_source_member": f"SAM2_Mice/benchmark_data/ground_truth_bb_labels/{index:05d}.txt"})
    provenance = {"schema": "bpb-sam2mice-source/1", "status": "verified", "file": FILE_NAME,
                  "file_id": FILE_ID, "bytes": EXPECTED_BYTES, "md5": EXPECTED_MD5,
                  "sha256": "0" * 64, "source_url": SOURCE_URL, "source_article": ARTICLE,
                  "license": "CC-BY-4.0", "note": "software schema fixture; no source archive was downloaded"}
    private_bytes(root / "paired-frames.json", encoded({"schema": "bpb-sam2mice-source-pairs/1",
                  "source_sequence": "openfield_five_mouse", "source": provenance, "pairs": pairs}))
    private_bytes(root / "audit.json", encoded({"schema": "bpb-sam2mice-source-audit/1", "source": provenance,
                  "upstream_commit": "80a01ecd8aafe7bb2eb2c0a74f76088c650fbf98",
                  "note": "software fixture, never empirical acceptance"}))
    bindings = {str(path.relative_to(root)): digest(path) for path in root.rglob("*") if path.is_file()}
    private_bytes(root / "complete.json", encoded({"schema": "bpb-sam2mice-tracking-prepared/1",
                  "source_verified": True, "fixture": False, "source": provenance,
                  "note": "schema fixture only; does not represent an actual source-verification claim",
                  "paired_manifest_sha256": bindings["paired-frames.json"]["sha256"], "files": bindings}))


class PackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bpb-tracking-packet-test-", dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        fixture_source(self.source)
        self.review = self.root / "source-review.json"
        self.split = self.root / "split-review.json"
        self.packets = self.root / "packets"
        self.task = self.root / "tasks/animal-behavior" / TASK_ID
        self.local = self.root / "local"
        review = {
            "schema": "bpb-sam2mice-tracking-source-review/1", "status": "passed",
            "source_complete_sha256": digest(self.source / "complete.json")["sha256"],
            "paired_manifest_sha256": digest(self.source / "paired-frames.json")["sha256"],
            "author_gt_verified": True, "image_label_alignment_verified": True,
            "identity_continuity_verified": True, "clean_input_verified": True,
            "basis": "software fixture only; no real source has been accepted",
        }
        private_bytes(self.review, encoded(review))
        split = {
            "schema": "bpb-sam2mice-tracking-split-review/1", "status": "frozen",
            "task_id": TASK_ID, "task_version": "0.1", "profile": PROFILE,
            "source_complete_sha256": review["source_complete_sha256"],
            "paired_manifest_sha256": review["paired_manifest_sha256"],
            "source_review_sha256": digest(self.review)["sha256"], "no_model_scores_used": True,
            "rule": {"description": "software fixture with explicit gaps and role boundaries"},
            "sequences": [
                {"id": "sequence-" + "1" * 16, "split": "train", "frame_indices": [0, 1, 2]},
                {"id": "sequence-" + "2" * 16, "split": "valid", "frame_indices": [4, 5]},
                {"id": "sequence-" + "3" * 16, "split": "test", "frame_indices": [7, 8]},
            ],
        }
        private_bytes(self.split, encoded(split))

    def build(self, output=None):
        return build_packets(self.source, self.review, self.split, output or self.packets)

    def ready(self):
        contract = self.build()
        bind_and_materialize(self.packets, self.task, self.local)
        return contract, self.local / "tasks/animal-behavior" / TASK_ID / contract["revision"]

    def rewrite_split(self, transform):
        value = json.loads(self.split.read_text())
        transform(value)
        private_bytes(self.split, encoded(value))

    def bind_hosted_fixture(self, contract):
        """Transport fixture with invented commit IDs, never a publication receipt."""
        private_bytes(self.task / "task.yaml", b"id: " + TASK_ID.encode() + b"\n" + SOURCE_AVAILABILITY)
        bindings = {name: digest(self.task / name)["sha256"]
                    for name in ("contract.json", "task.yaml", "data.lock", "evaluator.lock")}
        data = json.loads((self.task / "data.lock").read_text())
        evaluator = json.loads((self.task / "evaluator.lock").read_text())
        destinations = {role: {"repo_id": REPOS[role], "revision": ("a" if role == "public" else "b") * 40}
                        for role in ("public", "private")}
        for entry in data["datasets"]:
            role = entry["scope"]
            packet_role = "public" if role == "public" else "evaluator"
            prefix = f"local://tasks/animal-behavior/{TASK_ID}/{contract['revision']}/{packet_role}/"
            self.assertTrue(entry["uri"].startswith(prefix))
            entry["uri"] = (f"hf://datasets/{destinations[role]['repo_id']}@{destinations[role]['revision']}/"
                            f"tasks/animal-behavior/{TASK_ID}/{packet_role}/" + entry["uri"][len(prefix):])
        evaluator.update(schema="bpb-evaluator-data/1", **destinations["private"])
        private_bytes(self.task / "data.lock", encoded(data))
        private_bytes(self.task / "evaluator.lock", encoded(evaluator))
        private_bytes(self.task / "task.yaml", (self.task / "task.yaml").read_bytes().replace(SOURCE_AVAILABILITY, HOSTED_AVAILABILITY))
        card = {"schema": "bpb-mouse-hf-delivery/1", "task_id": TASK_ID,
                "content_revision": contract["revision"], "transport_only": True,
                "source_bindings": bindings, **destinations,
                "hosted_bindings": {name: digest(self.task / name)["sha256"]
                                    for name in ("data.lock", "evaluator.lock", "task.yaml")}}
        private_bytes(self.task / "hf-delivery.json", encoded(card))
        return card

    def test_hosted_locks_preserve_source_content_and_reconstruction(self):
        contract, _ = self.ready()
        self.bind_hosted_fixture(contract)
        verify_locks(self.task, contract)
        names = ("contract.json", "data.lock", "evaluator.lock", "task.yaml", "hf-delivery.json")
        before = {name: (self.task / name).read_bytes() for name in names}
        result = bind_and_materialize(self.packets, self.task, self.root / "hosted-rebuild", materialize_only=True)
        self.assertEqual(result["mode"], "created")
        self.assertEqual(before, {name: (self.task / name).read_bytes() for name in names})

    def test_hosted_evaluator_marker_uses_pinned_revision(self):
        contract, delivered = self.ready()
        card = self.bind_hosted_fixture(contract)
        owner = self.root / "owner/evaluator"
        shutil.copytree(delivered / "evaluator", owner)
        marker = {"schema": "bpb-prepared-evaluator/1", "task_id": TASK_ID,
                  "revision": card["private"]["revision"], "files": len(contract["owner_files"]),
                  "evaluator_lock_sha256": digest(self.task / "evaluator.lock")["sha256"]}
        private_bytes(owner / ".bpb-evaluator.json", encoded(marker))
        stage_evaluator(self.task, contract, owner, self.root / "verified-hosted-owner")
        marker["revision"] = contract["revision"]
        private_bytes(owner / ".bpb-evaluator.json", encoded(marker))
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            stage_evaluator(self.task, contract, owner, self.root / "wrong-content-revision")

    def test_hosted_transport_cannot_redirect_private_or_change_task(self):
        contract, _ = self.ready()
        card = self.bind_hosted_fixture(contract)
        card["private"]["repo_id"] = REPOS["public"]
        private_bytes(self.task / "hf-delivery.json", encoded(card))
        with self.assertRaisesRegex(ValueError, "destinations"):
            verify_locks(self.task, contract)
        card["private"]["repo_id"] = REPOS["private"]
        private_bytes(self.task / "hf-delivery.json", encoded(card))
        private_bytes(self.task / "task.yaml", (self.task / "task.yaml").read_bytes() + b"# unreviewed change\n")
        with self.assertRaisesRegex(ValueError, "beyond the availability"):
            verify_locks(self.task, contract)

    def test_hosted_binding_hashes_cannot_hide_changed_scientific_bytes(self):
        contract, _ = self.ready()
        card = self.bind_hosted_fixture(contract)
        data = json.loads((self.task / "data.lock").read_text())
        data["datasets"][0]["bytes"] += 1
        private_bytes(self.task / "data.lock", encoded(data))
        card["hosted_bindings"]["data.lock"] = digest(self.task / "data.lock")["sha256"]
        private_bytes(self.task / "hf-delivery.json", encoded(card))
        with self.assertRaisesRegex(ValueError, "expected transport"):
            verify_locks(self.task, contract)

    def test_review_and_preanalysis_split_are_mandatory(self):
        review = json.loads(self.review.read_text())
        review["status"] = "pending"
        private_bytes(self.review, encoded(review))
        with self.assertRaisesRegex(ValueError, "explicit source review"):
            self.build()
        self.assertFalse(self.packets.exists())
        review["status"] = "passed"
        private_bytes(self.review, encoded(review))
        self.rewrite_split(lambda value: value.update(no_model_scores_used=False))
        with self.assertRaisesRegex(ValueError, "pre-analysis split"):
            self.build()
        self.assertFalse(self.packets.exists())

    def test_stale_source_is_rejected_before_any_packet_write(self):
        private_bytes(self.source / "audit.json", b"{\"changed\":true}\n")
        with self.assertRaisesRegex(ValueError, "prepared source changed"):
            self.build()
        self.assertFalse(self.packets.exists())

    def test_source_verified_flag_cannot_replace_pinned_author_identity(self):
        complete = json.loads((self.source / "complete.json").read_text())
        complete["source"]["file_id"] = FILE_ID + 1
        private_bytes(self.source / "complete.json", encoded(complete))
        with self.assertRaisesRegex(ValueError, "source provenance differs"):
            self.build()
        self.assertFalse(self.packets.exists())

    def test_empty_gt_sequence_is_rejected_before_packet_write(self):
        self.rewrite_split(lambda value: value["sequences"][0].update(frame_indices=[0]))
        with self.assertRaisesRegex(ValueError, "at least one author GT object"):
            self.build()
        self.assertFalse(self.packets.exists())

    def test_unobserved_gaps_and_reused_frames_are_rejected(self):
        self.rewrite_split(lambda value: value["sequences"][0].update(frame_indices=[0, 2]))
        with self.assertRaisesRegex(ValueError, "unique contiguous"):
            self.build()
        self.rewrite_split(lambda value: value["sequences"][0].update(frame_indices=[4, 5]))
        with self.assertRaisesRegex(ValueError, "unique contiguous"):
            self.build()
        self.assertFalse(self.packets.exists())

    def test_real_packet_shape_and_explicit_empty_gt_frame(self):
        contract, delivered = self.ready()
        self.assertEqual(contract, load_contract(self.task))
        verify_locks(self.task, contract)
        public = exact_packet(delivered / "public", contract, evaluator=False)
        private = exact_packet(delivered / "evaluator", contract, evaluator=True)
        self.assertEqual({row["split"] for row in public["sequences"]}, {"train", "valid"})
        self.assertEqual({row["split"] for row in private["sequences"]}, {"test"})
        train = next(row for row in public["sequences"] if row["split"] == "train")
        with np.load(delivered / "public" / train["feature_path"], allow_pickle=False) as data:
            self.assertEqual(set(data.files), {"frames"})
            self.assertEqual(data["frames"].shape, (3, 16, 20, 3))
        with np.load(delivered / "public" / train["label_path"], allow_pickle=False) as data:
            self.assertEqual(set(data.files), {"detections"})
            self.assertEqual(set(data["detections"][:, 0]), {1, 2})
        manifest_text = (delivered / "public/manifest.json").read_text()
        for forbidden in ("frame_indices", "image_source_member", "ground_truth", "raw_frames", "test/"):
            self.assertNotIn(forbidden, manifest_text)
        locks = json.loads((self.task / "data.lock").read_text())["datasets"]
        self.assertTrue(all(row["uri"].startswith("local://tasks/animal-behavior/" + TASK_ID + "/") for row in locks))

    def test_regeneration_and_materialization_are_byte_identical(self):
        contract, _ = self.ready()
        second = self.root / "packets-second"
        self.assertEqual(self.build(second), contract)
        before = {name: (self.task / name).read_bytes() for name in ("contract.json", "data.lock", "evaluator.lock")}
        result = bind_and_materialize(second, self.task, self.local, materialize_only=True)
        self.assertEqual(result["mode"], "verified-existing")
        self.assertEqual(before, {name: (self.task / name).read_bytes() for name in before})

    def test_changed_review_cannot_silently_rebind(self):
        self.ready()
        original = (self.task / "contract.json").read_bytes()
        self.rewrite_split(lambda value: value["rule"].update(description="changed frozen scientific protocol"))
        changed = self.root / "packets-changed"
        self.build(changed)
        with self.assertRaisesRegex(ValueError, "checked-in binding differs"):
            bind_and_materialize(changed, self.task, self.local, materialize_only=True)
        self.assertEqual(original, (self.task / "contract.json").read_bytes())

    def test_partial_metadata_is_preserved(self):
        self.ready()
        (self.task / "evaluator.lock").unlink()
        before = (self.task / "contract.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "partial task bindings"):
            bind_and_materialize(self.packets, self.task, self.local)
        self.assertEqual(before, (self.task / "contract.json").read_bytes())

    def test_extra_files_links_and_owner_permissions_are_rejected(self):
        contract, delivered = self.ready()
        extra = delivered / "public/extra.json"
        private_bytes(extra, b"{}")
        with self.assertRaisesRegex(ValueError, "missing or extra paths"):
            exact_packet(delivered / "public", contract, evaluator=False)
        extra.unlink()
        (delivered / "evaluator/manifest.json").chmod(0o644)
        with self.assertRaisesRegex(ValueError, "owner-only"):
            exact_packet(delivered / "evaluator", contract, evaluator=True)
        manifest = delivered / "public/manifest.json"
        backup = self.root / "manifest-copy.json"
        shutil.copyfile(manifest, backup)
        manifest.unlink()
        manifest.symlink_to(backup)
        with self.assertRaises(ValueError):
            exact_packet(delivered / "public", contract, evaluator=False)

    def test_public_staging_and_private_receipt_are_separate(self):
        contract, delivered = self.ready()
        cache = self.root / "public-cache"
        cache.mkdir(mode=0o700)
        for row in contract["public_files"]:
            target = cache / row["sha256"] / "data"
            if not target.exists():
                private_bytes(target, (delivered / "public" / row["path"]).read_bytes())
        with patch.dict(os.environ, {"BPB_CACHE_ROOT": str(cache)}):
            stage_public_cache(self.task, contract, self.root / "cache-packet")
        with patch.dict(os.environ, {"BPB_PUBLIC_DATA_ROOT": str(delivered / "public")}):
            stage_public_workspace(self.task, contract, self.root / "workspace")
            stage_public_workspace(self.task, contract, self.root / "workspace")
        owner = self.root / "owner/evaluator"
        shutil.copytree(delivered / "evaluator", owner)
        marker = {"schema": "bpb-prepared-evaluator/1", "task_id": TASK_ID, "revision": contract["revision"],
                  "files": len(contract["owner_files"]), "evaluator_lock_sha256": digest(self.task / "evaluator.lock")["sha256"]}
        private_bytes(owner / ".bpb-evaluator.json", encoded(marker))
        stage_evaluator(self.task, contract, owner, self.root / "trusted-packet")
        marker["revision"] = "0" * 64
        private_bytes(owner / ".bpb-evaluator.json", encoded(marker))
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            stage_evaluator(self.task, contract, owner, self.root / "bad-packet")
        with patch.dict(os.environ, {"BPB_PUBLIC_DATA_ROOT": str(owner)}):
            with self.assertRaisesRegex(ValueError, "evaluator storage"):
                stage_public_workspace(self.task, contract, self.root / "bad-workspace")

    def test_reference_receives_train_only(self):
        _, delivered = self.ready()
        def fit(rows, output, *, root):
            self.assertEqual({row["split"] for row in rows}, {"train"})
            self.assertEqual(len(rows), 1)
            self.assertEqual(root, delivered / "public")
            return {"train_only": True}
        with patch("reference.fit_reference", side_effect=fit):
            self.assertEqual(build_reference(self.task, self.root / "model", public_dir=delivered / "public"),
                             {"train_only": True})

    def test_private_freeze_link_and_public_directory_rejected(self):
        path = self.root / "submission-freeze.json"
        private_bytes(path, b"{}")
        linked = self.root / "linked.json"
        linked.symlink_to(path)
        with self.assertRaisesRegex(ValueError, "linked private freeze"):
            node_freeze_path(linked)
        parent = self.root / "bpb-owner-score-test"
        parent.mkdir(mode=0o755)
        parent.chmod(0o755)
        with patch("tempfile.gettempdir", return_value=str(self.root)):
            with self.assertRaisesRegex(ValueError, "owner-only"):
                node_freeze_path(parent / "submission-freeze.json")

    def test_private_bridge_binds_the_model_and_returns_both_metrics(self):
        contract, delivered = self.ready()
        artifacts = self.root / "artifacts"
        model = artifacts / "submission"
        model.mkdir(parents=True, mode=0o700)
        private_bytes(model / "model.py", b"# Software fixture, never executed.\n")
        private_bytes(model / "config.json", b"{}\n")
        with (model / "weights.npz").open("xb") as writer:
            np.savez(writer, fixture=np.zeros(1))
        (model / "weights.npz").chmod(0o600)
        freeze = {"schema": "bpb-private-submission-freeze/1", "task_id": TASK_ID, "task_version": "0.1",
                  "files": {"submission/" + name: digest(model / name)["sha256"]
                            for name in ("model.py", "config.json", "weights.npz")}}
        frozen_path = self.root / "freeze.json"
        private_bytes(frozen_path, encoded(freeze))
        owner = self.root / "owner/evaluator"
        shutil.copytree(delivered / "evaluator", owner)
        private_bytes(owner / ".bpb-evaluator.json", encoded({
            "schema": "bpb-prepared-evaluator/1", "task_id": TASK_ID, "revision": contract["revision"],
            "files": len(contract["owner_files"]), "evaluator_lock_sha256": digest(self.task / "evaluator.lock")["sha256"],
        }))
        expected = {"mota": -0.5, "idf1": 0.2, "note": "software fixture"}
        environment = {"BPB_SUBMISSION_ISOLATION": "docker", "BPB_INFERENCE_IMAGE": "sha256:" + "a" * 64}
        with patch.dict(os.environ, environment), patch("score_task._evaluate", return_value=expected) as evaluate:
            self.assertEqual(score_private(self.task, artifacts, owner, frozen_path), expected)
            self.assertEqual({row["split"] for row in evaluate.call_args.args[1]}, {"test"})
        freeze["task_version"] = "wrong"
        private_bytes(frozen_path, encoded(freeze))
        with patch.dict(os.environ, environment):
            with self.assertRaisesRegex(ValueError, "Node model freeze identity"):
                score_private(self.task, artifacts, owner, frozen_path)

    def test_partial_prediction_sequence_set_cannot_score(self):
        contract, delivered = self.ready()
        packet = delivered / "public"
        manifest = exact_packet(packet, contract, evaluator=False)
        rows = [row for row in manifest["sequences"] if row["split"] == "valid"]
        with patch("inference.evaluate_sequences", return_value={}):
            with self.assertRaisesRegex(ValueError, "prediction sequence IDs differ"):
                _evaluate(packet, rows, self.root / "unused-model", "unused-image")


if __name__ == "__main__":
    unittest.main()
