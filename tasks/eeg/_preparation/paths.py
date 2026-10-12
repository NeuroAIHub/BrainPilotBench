"""Canonical, non-overwriting destinations for data-only export receipts/packages."""

from __future__ import annotations

import os
from pathlib import Path


def canonical_new_path(value: Path, label: str) -> Path:
    requested = value.expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    # resolve(strict=False) follows every existing symlink ancestor and normalizes
    # '..' even when the requested leaf has not been created yet.
    canonical = requested.resolve(strict=False)
    if os.path.lexists(requested) or os.path.lexists(canonical):
        raise ValueError(f"{label} already exists; never replace it: {requested}")
    return canonical


def disjoint(path: Path, protected: dict[str, Path], label: str) -> None:
    for name, root in protected.items():
        # The export output is deliberately nonexistent until launch. Resolve its
        # existing ancestors while still checking overlap with a new receipt.
        root = root.resolve(strict=False)
        if path == root or root in path.parents or path in root.parents:
            raise ValueError(f"{label} overlaps {name}: {path}")
