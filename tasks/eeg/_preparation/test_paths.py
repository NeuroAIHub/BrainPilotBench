#!/usr/bin/env python3
"""Synthetic path-alias and no-overwrite checks for preparation destinations."""

from pathlib import Path
import json
import tempfile

from paths import canonical_new_path, disjoint
from prepare import load_recipe


def rejected(action, phrase: str) -> None:
    try:
        action()
    except ValueError as error:
        assert phrase in str(error), error
    else:
        raise AssertionError(f"unsafe path accepted: {phrase}")


def main() -> None:
    cache = Path.cwd() / ".cache" / "eeg-d-expansion"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="path-gates-", dir=cache) as directory:
        root = Path(directory)
        source = root / "source"; source.mkdir()
        raw = root / "raw"; raw.mkdir()
        task = root / "task"; task.mkdir()
        alias = root / "source-alias"; alias.symlink_to(source, target_is_directory=True)
        task_alias = root / "task-alias"; task_alias.symlink_to(task, target_is_directory=True)
        rejected(lambda: disjoint(canonical_new_path(alias / "new", "export"),
                                  {"source": source, "raw": raw}, "export"), "overlaps source")
        rejected(lambda: disjoint(canonical_new_path(alias / "nested" / ".." / "new", "export"),
                                  {"source": source, "raw": raw}, "export"), "overlaps source")
        rejected(lambda: disjoint(canonical_new_path(task_alias / "receipt.json", "receipt"),
                                  {"task": task}, "receipt"), "overlaps task")
        future = canonical_new_path(root / "future-export", "export")
        receipt = canonical_new_path(root / "receipt.json", "receipt")
        disjoint(receipt, {"future output": future}, "receipt")
        rejected(lambda: disjoint(canonical_new_path(future / "receipt.json", "receipt"),
                                  {"future output": future}, "receipt"),
                 "overlaps future output")
        rejected(lambda: disjoint(canonical_new_path(root / "future-export-alias" / ".." /
                                                      "future-export" / "receipt.json", "receipt"),
                                  {"future output": future}, "receipt"),
                 "overlaps future output")
        existing = root / "existing.json"; existing.write_text("preserved", encoding="utf-8")
        rejected(lambda: canonical_new_path(existing, "receipt"), "already exists")
        assert existing.read_text(encoding="utf-8") == "preserved"
        real = Path(__file__).resolve().parent.parent / "eeg-sleep-stage-hmc" / "preparation.json"
        recipe = json.loads(real.read_text(encoding="utf-8"))
        recipe["vendor_files"]["export_classification_native.py"] = "0" * 64
        fake_task = root / "eeg-sleep-stage-hmc"; fake_task.mkdir()
        (fake_task / "preparation.json").write_text(json.dumps(recipe), encoding="utf-8")
        rejected(lambda: load_recipe(fake_task), "vendored preparation file mismatch")
    print("canonical symlink/.. aliases, existing receipt and wrong exporter pin rejected")


if __name__ == "__main__":
    main()
