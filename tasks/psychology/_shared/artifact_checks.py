"""Trusted pre-execution checks for frozen Psych-101 artifacts."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def strict_json(path: Path):
    def bad_constant(value):
        raise ValueError("Non-finite JSON constant: " + value)
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=bad_constant,
                       object_pairs_hook=unique_pairs)
    def check(item):
        if type(item) is float and not math.isfinite(item):
            raise ValueError("Non-finite JSON number")
        if isinstance(item, dict):
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)
    check(value)
    return value


def numeric_elements(value) -> int:
    if type(value) in (int, float):
        return 1
    if isinstance(value, list):
        return sum(numeric_elements(item) for item in value)
    if isinstance(value, dict):
        return sum(numeric_elements(item) for item in value.values())
    return 0
