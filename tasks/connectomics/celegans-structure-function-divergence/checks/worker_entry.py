#!/usr/bin/env python3
"""Run only the submitted analyzer on one input reconstruction.

This file is baked into the worker image. The trusted evaluator and its truth
implementation are deliberately absent from that image and its mounts.
"""

import importlib.util
import json
import sys

import numpy as np


def plain(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported result type: {type(value).__name__}")


def main():
    sys.dont_write_bytecode = True
    path = "/candidate/divergence/divergence_analysis.py"
    spec = importlib.util.spec_from_file_location("candidate_analysis", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("candidate module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    analyzer = module.DivergenceAnalysis()
    with np.load("/input.npz", allow_pickle=False) as data:
        signaling = data["signaling"].astype(np.float64)
        alpha = data["alpha"].astype(np.float64)
        adjacency = data["adjacency"].astype(np.uint8)
        neuron_ids = [str(item) for item in data["neuron_ids"]]
    result = analyzer.analyze(signaling, alpha, adjacency, neuron_ids)
    sys.stdout.write(json.dumps(plain(result), allow_nan=True, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
