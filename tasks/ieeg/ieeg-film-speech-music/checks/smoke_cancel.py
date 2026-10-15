#!/usr/bin/env python3
"""Check normal SIGTERM cleanup after one real Train-window prediction."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess

import numpy as np

from run import Worker, install_termination_handler, resolve_image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-subject", required=True, type=Path)
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--image")
    args = parser.parse_args()
    with np.load(args.public_subject / "train.npz", allow_pickle=False) as data:
        window = data["x"][0]
    install_termination_handler()
    worker = Worker(resolve_image(args.image), args.submission, window.shape[0])
    interrupted = False
    try:
        try:
            worker.predict(window, args.public_subject.name)
            os.kill(os.getpid(), signal.SIGTERM)
        finally:
            worker.close()
    except KeyboardInterrupt:
        interrupted = True
    remaining = subprocess.check_output(
        ["docker", "ps", "-a", "--filter", f"name=^{worker.name}$", "--format", "{{.Names}}"],
        text=True).strip()
    if not interrupted or remaining:
        raise ValueError("Normal SIGTERM left an owned film container")
    print(json.dumps({"status": "normal_sigterm_container_cleanup_passed",
                      "real_train_window": True, "test_inference": False}))


if __name__ == "__main__":
    main()
