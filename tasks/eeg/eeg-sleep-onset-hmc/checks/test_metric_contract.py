#!/usr/bin/env python3
"""Synthetic checks for the pinned native sleep-onset BinnedMAE semantics."""
from pathlib import Path
import sys

TASK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK.parent / "_preparation"))
from sleep_special_contract import assign_bin, binned_mae

EDGES = [0.0, 40.0, 90.0, 300.0, 600.0]


def main() -> None:
    expected = [0, 1, 2, 3, 3, None, None]
    actual = [assign_bin(v, EDGES) for v in (0, 40, 90, 300, 600, -1, 601)]
    assert actual == expected, (actual, expected)
    result = binned_mae([10, 50, 70, 330, 550, 999, 999],
                        [0, 40, 90, 300, 600, -1, 601], EDGES)
    assert result["bin_counts"] == [1, 1, 1, 2], result
    assert result["out_of_range"] == 2 and result["value"] == 20.0, result
    assert result["value"] != (10 + 10 + 20 + 30 + 50) / 5
    empty = binned_mae([1], [601], EDGES)
    assert empty["value"] is None and empty["out_of_range"] == 1, empty
    print("native onset bin edges, cap, empty-bin and BinnedMAE checks passed")


if __name__ == "__main__":
    main()
