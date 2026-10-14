"""Small public-only cache and legacy-source tests; no network or official Test."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import prepare_public


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PublishedSplitCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="psych-public-cache-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        patcher = mock.patch.dict(os.environ, {"BPB_CACHE_ROOT": str(self.cache)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.experiment = "toy/exp1.csv"
        self.seed = "toy-public-seed"
        rows = [
            {"experiment": self.experiment, "participant": "p-one", "text": "Choose <<A>>"},
            {"experiment": self.experiment, "participant": "p-two", "text": "Choose <<B>>"},
        ]
        source_data = b"".join((json.dumps(row) + "\n").encode() for row in rows)
        self.source = self.root / "prompts_training.jsonl"
        self.source.write_bytes(source_data)
        valid_id = min((row["participant"] for row in rows), key=lambda participant:
                       hashlib.sha256(f"{self.experiment}:{self.seed}:{participant}".encode()).digest())
        self.splits = {}
        for split in ("train", "valid"):
            row = next(row for row in rows if (row["participant"] == valid_id) == (split == "valid"))
            self.splits[split] = (json.dumps(row, ensure_ascii=False) + "\n").encode()
        self.spec = {
            "schema": "bpb-psych101-public-contract/1", "experiment_id": self.experiment,
            "response_space_profile": "byte_next_v1", "split_seed": self.seed,
            "source_public_bytes": len(source_data), "source_public_sha256": digest(source_data),
            "splits": {split: {"bytes": len(body), "sha256": digest(body), "rows": 1,
                               "responses": 1} for split, body in self.splits.items()},
        }
        self.contract = self.root / "contract.json"
        self.contract.write_text(json.dumps(self.spec), encoding="utf-8")
        self.output = self.root / "workspace" / "public_data"

    def cache_split(self, split: str, body: bytes | None = None) -> Path:
        path = self.cache / self.spec["splits"][split]["sha256"] / "data"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.splits[split] if body is None else body)
        return path

    def assert_public_output(self) -> None:
        self.assertEqual({p.name for p in self.output.iterdir()},
                         {"train.jsonl", "valid.jsonl", "spec.json"})
        for split in ("train", "valid"):
            self.assertEqual((self.output / f"{split}.jsonl").read_bytes(), self.splits[split])
        self.assertFalse(any("private" in str(p).lower() or "test" in p.name.lower()
                             for p in self.output.rglob("*")))

    def test_two_cached_splits_work_when_old_source_is_absent(self) -> None:
        self.cache_split("train")
        self.cache_split("valid")
        prepare_public.prepare(self.contract, self.output, self.root / "missing-source", None)
        self.assert_public_output()

    def test_wrong_cached_hash_and_size_fail_closed(self) -> None:
        corrupted = bytearray(self.splits["train"])
        corrupted[0] ^= 1
        for body in (bytes(corrupted),
                     self.splits["train"] + b"\n"):
            with self.subTest(body_length=len(body)):
                self.cache_split("train", body)
                self.cache_split("valid")
                with self.assertRaisesRegex(ValueError, "train file differs"):
                    prepare_public.prepare(self.contract, self.output, self.source, None)
                self.assertFalse(self.output.exists())

    def test_half_cached_package_is_error_even_with_old_source(self) -> None:
        self.cache_split("train")
        with self.assertRaisesRegex(ValueError, "Incomplete cached public package: missing valid.jsonl"):
            prepare_public.prepare(self.contract, self.output, self.source, None)
        self.assertFalse(self.output.exists())

    def test_two_partial_downloads_do_not_fall_back_to_old_source(self) -> None:
        for split in ("train", "valid"):
            directory = self.cache / self.spec["splits"][split]["sha256"]
            directory.mkdir(parents=True)
            (directory / ".partial").write_bytes(b"unfinished-public-download")
        with self.assertRaisesRegex(ValueError, "Incomplete cached public package: missing train.jsonl, valid.jsonl"):
            prepare_public.prepare(self.contract, self.output, self.source, None)
        self.assertFalse(self.output.exists())

    def test_one_partial_download_does_not_fall_back_to_old_source(self) -> None:
        directory = self.cache / self.spec["splits"]["valid"]["sha256"]
        directory.mkdir(parents=True)
        (directory / ".partial").write_bytes(b"unfinished-public-download")
        with self.assertRaisesRegex(ValueError, "Incomplete cached public package"):
            prepare_public.prepare(self.contract, self.output, self.source, None)
        self.assertFalse(self.output.exists())

    def test_fetch_lock_without_data_does_not_fall_back_to_old_source(self) -> None:
        directory = self.cache / self.spec["splits"]["train"]["sha256"]
        directory.mkdir(parents=True)
        (directory / ".fetch.lock").write_text("12345", encoding="ascii")
        with self.assertRaisesRegex(ValueError, "Incomplete cached public package"):
            prepare_public.prepare(self.contract, self.output, self.source, None)
        self.assertFalse(self.output.exists())

    def test_explicit_published_directory_wins_over_incomplete_cache(self) -> None:
        self.cache_split("train", b"not a valid cached split")
        published = self.root / "published"
        published.mkdir()
        for split, body in self.splits.items():
            (published / f"{split}.jsonl").write_bytes(body)
        private = published / "private"
        private.mkdir()
        (private / "test.jsonl").write_text("held-out fixture must not be read", encoding="utf-8")
        prepare_public.prepare(self.contract, self.output, None, published)
        self.assert_public_output()

    def test_original_full_source_fallback_without_cached_splits(self) -> None:
        for split in ("train", "valid"):
            (self.cache / self.spec["splits"][split]["sha256"]).mkdir(parents=True)
        prepare_public.prepare(self.contract, self.output, self.source, None)
        self.assert_public_output()

    def test_no_source_and_no_cached_splits_preserves_old_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing or linked public source"):
            prepare_public.prepare(self.contract, self.output, self.root / "missing-source", None)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
