#!/usr/bin/env python3
"""Make a disjoint public-only train/eval fixture with hard-linked MRI files."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def stage(root: Path, dest: Path, train_count: int, eval_count: int) -> None:
    root = root.resolve(strict=True)
    dest = dest.resolve()
    if dest.exists():
        raise ValueError(f"fixture destination exists: {dest}")
    subjects = read_csv(root / "subjects.csv")
    ages = {row["subject_id"]: row["age"] for row in read_csv(root / "ages.csv")}
    if len(subjects) < train_count + eval_count or train_count < 6 or eval_count < 3:
        raise ValueError("need at least six training and three evaluation subjects")
    for split, selected in (("public", subjects[:train_count]),
                            ("evaluation", subjects[train_count:train_count + eval_count])):
        target = dest / split
        (target / "images").mkdir(parents=True)
        for row in selected:
            image = root / row["image_path"]
            if image.resolve().parent != (root / "images").resolve():
                raise ValueError("image outside public source")
            (target / "images" / image.name).hardlink_to(image)
        write_csv(target / "subjects.csv", ["subject_id", "image_path"], selected)
        age_rows = [{"subject_id": row["subject_id"], "age": ages[row["subject_id"]]}
                    for row in selected]
        if split == "public":
            write_csv(target / "ages.csv", ["subject_id", "age"], age_rows)
        else:
            write_csv(target / "labels" / "true_ages.csv", ["subject_id", "age"], age_rows)
    print(f"public-only fixture: train={train_count}, evaluation={eval_count}, destination={dest}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-data", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--train-count", type=int, default=12)
    parser.add_argument("--eval-count", type=int, default=3)
    args = parser.parse_args()
    stage(args.public_data, args.destination, args.train_count, args.eval_count)


if __name__ == "__main__":
    main()
