"""Isolation fixtures and Train-only reference checks, separate from real-data acceptance."""

from __future__ import annotations

import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile

import numpy as np

from inference import digest_file, evaluate_sequences, freeze_model, load_features, load_truth, numeric_npz, predict_sequence, snapshot_model
from reference import fit_reference

IMAGE = os.environ.get("SAM2MICE_TEST_IMAGE")
CONSTANT = "return np.array([[i,7,.1,.1,.3,.3] for i in range(len(frames))],dtype=np.float64)"


class TrackingInferenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bpb-tracking-fixture-", dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.frames = np.full((6, 64, 64, 3), 200, dtype=np.uint8)
        for index in range(6):
            self.frames[index, 20:36, 4 + index * 6:20 + index * 6] = 20

    def model(self, body=CONSTANT):
        path = self.root / ("model-" + uuid.uuid4().hex)
        path.mkdir(mode=0o700)
        text = "import numpy as np\nclass Model:\n    def predict(self, frames, context):\n"
        text += "\n".join("        " + line for line in body.splitlines())
        text += "\ndef load_model(config, weights_path):\n    return Model()\n"
        (path / "model.py").write_text(text)
        (path / "config.json").write_text("{}\n")
        np.savez(path / "weights.npz", bias=np.zeros(1, dtype=np.float32))
        return path

    def frozen(self, body=CONSTANT):
        source = self.model(body)
        output = self.root / ("frozen-" + uuid.uuid4().hex)
        freeze_model(source, output)
        return output

    def sequence(self, stem="sequence-a", split="train"):
        feature = self.root / (stem + "-features.npz")
        truth = self.root / (stem + "-truth.npz")
        np.savez(feature, frames=self.frames)
        detections = np.array([[index, 0, (4 + index * 6) / 64, 20 / 64,
                                (20 + index * 6) / 64, 36 / 64]
                               for index in range(6)], dtype=np.float64)
        np.savez(truth, detections=detections)
        features, labels = digest_file(feature), digest_file(truth)
        return {"id": stem, "split": split, "feature_path": feature.name, "label_path": truth.name,
                "frames": len(self.frames), "feature_bytes": features["bytes"], "feature_sha256": features["sha256"],
                "label_bytes": labels["bytes"], "label_sha256": labels["sha256"]}

    def test_freeze_roundtrip_and_tamper(self):
        source = self.model()
        before = snapshot_model(source)
        frozen = self.root / "freeze"
        freeze_model(source, frozen)
        self.assertEqual(snapshot_model(frozen, frozen=True), before)
        (frozen / "model.py").write_text("# changed\n")
        with self.assertRaises(ValueError):
            snapshot_model(frozen, frozen=True)
        with self.assertRaises(FileExistsError):
            freeze_model(source, frozen)

    def test_extra_files_links_object_and_nonfinite_weights_rejected(self):
        source = self.model()
        (source / "extra").write_text("fixture")
        with self.assertRaises(ValueError):
            snapshot_model(source)
        (source / "extra").unlink()
        weights = source / "weights.npz"
        for invalid in [np.array([{"unsafe": True}], dtype=object), np.array([np.nan])]:
            np.savez(weights, forbidden=invalid)
            with self.assertRaises(ValueError):
                snapshot_model(source)
        weights.unlink()
        weights.symlink_to(self.root / "missing")
        with self.assertRaises(ValueError):
            snapshot_model(source)

    def test_numeric_header_bound_precedes_allocation(self):
        header = io.BytesIO()
        np.lib.format.write_array_header_1_0(header, {"descr": "|u1", "fortran_order": False, "shape": (10**12,)})
        archive = self.root / "bad.npz"
        with zipfile.ZipFile(archive, "w") as writer:
            writer.writestr("weights.npy", header.getvalue())
        with self.assertRaises(ValueError):
            numeric_npz(archive, max_bytes=1_000_000)

    def test_strict_feature_and_truth_schema(self):
        row = self.sequence()
        actual = load_features(self.root / row["feature_path"], expected_bytes=row["feature_bytes"],
                               expected_sha256=row["feature_sha256"], frames=row["frames"])
        np.testing.assert_array_equal(actual, self.frames)
        truth = load_truth(self.root / row["label_path"], expected_bytes=row["label_bytes"],
                           expected_sha256=row["label_sha256"], frames=row["frames"])
        self.assertEqual(truth.shape, (6, 6))
        with self.assertRaises(ValueError):
            load_features(self.root / row["feature_path"], expected_bytes=row["feature_bytes"], expected_sha256="0" * 64)
        leaking = self.root / "leaking.npz"
        np.savez(leaking, frames=self.frames, labels=truth)
        binding = digest_file(leaking)
        with self.assertRaises(ValueError):
            load_features(leaking, expected_bytes=binding["bytes"], expected_sha256=binding["sha256"])

    def test_train_only_reference_and_unique_sequences(self):
        row = self.sequence()
        output = self.root / "reference"
        report = fit_reference([row], output, root=self.root)
        self.assertEqual(report["train_sequences"], 1)
        self.assertIs(report["validation_or_test_read"], False)
        snapshot_model(output)
        with self.assertRaises(ValueError):
            fit_reference([{**row, "split": "test"}], self.root / "rejected", root=self.root)
        with self.assertRaises(ValueError):
            evaluate_sequences(self.root, [row, row], output, "not-immutable")

    @unittest.skipUnless(IMAGE, "set SAM2MICE_TEST_IMAGE to the pinned tracking image")
    def test_container_sees_only_rgb_and_isolated_model(self):
        secret = self.root / "private.txt"
        secret.write_text("fixture owner-only sentinel")
        body = f'''import os, socket
assert os.getuid() != 0
assert not os.path.exists({str(secret)!r})
assert set(os.listdir("/input")) == {{"features.npz"}}
with np.load("/input/features.npz", allow_pickle=False) as f:
    assert set(f.files) == {{"frames"}}
assert context == {{"task_id":"sam2mice-multi-animal-tracking","width":64,"height":64}}
for path in ["/input/forbidden", "/model/forbidden", "/forbidden", "/output/forbidden"]:
    try:
        open(path,"w").write("bad")
    except OSError:
        pass
    else:
        raise ValueError("writable forbidden mount")
try:
    socket.create_connection(("1.1.1.1",53),timeout=.3)
except OSError:
    pass
else:
    raise ValueError("network available")
{CONSTANT}'''
        result = predict_sequence(IMAGE, self.frozen(body), self.frames)
        self.assertEqual(result.shape, (6, 6))
        self.assertTrue(np.all(result[:, 1] == 7))

    @unittest.skipUnless(IMAGE, "set SAM2MICE_TEST_IMAGE to the pinned tracking image")
    def test_one_bounded_output_file_and_empty_detections(self):
        body = '''import os, resource, stat
assert set(os.listdir("/output")) == {"predictions.npy"}
assert stat.S_IMODE(os.stat("/output/predictions.npy").st_mode) == 0o600
assert resource.getrlimit(resource.RLIMIT_FSIZE) == (4194304,4194304)
assert os.statvfs("/output").f_flag & os.ST_RDONLY
for number in range(128):
    try:
        open(f"/output/extra-{number}","wb").write(b"fixture")
    except OSError:
        pass
    else:
        raise ValueError("writable output directory")
return np.empty((0,6),dtype=np.float64)'''
        self.assertEqual(predict_sequence(IMAGE, self.frozen(body), self.frames).shape, (0, 6))

    @unittest.skipUnless(IMAGE, "set SAM2MICE_TEST_IMAGE to the pinned tracking image")
    def test_bad_predictions_and_header_attack_rejected(self):
        cases = ["return np.full((1,6),np.nan)", "return np.ones((2,5))",
                 "return np.array([[0,0,0,0,1,1],[0,0,.1,.1,.5,.5]],dtype=float)",
                 "return np.array([[0,0,0,0,2,1]],dtype=float)",
                 'open("/output/extra","w").write("fixture")\n' + CONSTANT,
                 'import os\nwith open("/output/predictions.npy","wb") as f:\n    np.lib.format.write_array_header_1_0(f,{"descr":"<f8","fortran_order":False,"shape":(10**12,6)})\nos._exit(0)']
        for body in cases:
            with self.subTest(body=body), self.assertRaises((ValueError, RuntimeError)):
                predict_sequence(IMAGE, self.frozen(body), self.frames)

    @unittest.skipUnless(IMAGE, "set SAM2MICE_TEST_IMAGE to the pinned tracking image")
    def test_timeout_cleans_up_only_its_owned_container(self):
        value = uuid.uuid4()
        with patch("inference.uuid.uuid4", return_value=value), self.assertRaises(RuntimeError):
            predict_sequence(IMAGE, self.frozen("import time\ntime.sleep(30)\n" + CONSTANT), self.frames, timeout=1)
        result = subprocess.run(["docker", "container", "inspect", "bpb-tracking-" + value.hex],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        self.assertNotEqual(result.returncode, 0)

    @unittest.skipUnless(IMAGE, "set SAM2MICE_TEST_IMAGE to the pinned tracking image")
    def test_reference_runs_in_fresh_sequence_containers(self):
        row = self.sequence()
        other = self.sequence("sequence-b")
        model = self.root / "trained-reference"
        fit_reference([row], model, root=self.root)
        output = evaluate_sequences(self.root, [row, other], model, IMAGE)
        np.testing.assert_array_equal(output[row["id"]], output[other["id"]])
        self.assertGreater(len(output[row["id"]]), 0)


if __name__ == "__main__":
    unittest.main()
