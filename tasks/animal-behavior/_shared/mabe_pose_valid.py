"""Label-independent pose validity for the MABe22 supervised adaptation."""

from __future__ import annotations

import numpy as np


def pose_valid_frames(pose: np.ndarray, threshold: float = 0.2,
                      max_gap: int = 60) -> np.ndarray:
    """Union of source-style valid segments over three mice, length 1800.

    Confidence gaps up to max_gap are bridged, but a frame with a nonfinite
    keypoint or confidence is excluded. Behavior labels never enter this mask.
    """
    if pose.shape != (1800, 3, 12, 3):
        raise ValueError("expected 1800 x 3 x 12 x 3 pose")
    valid_video = np.zeros(1800, dtype=bool)
    for mouse in range(3):
        xy = pose[:, mouse, :, :2]
        conf = pose[:, mouse, :, 2]
        bad = ~np.isfinite(xy).all(axis=(1, 2)) | ~np.isfinite(conf).all(axis=1)
        clean_conf = np.nan_to_num(conf, nan=0.0, posinf=0.0, neginf=0.0)
        clean_conf[bad] = 0.0
        mean_conf = clean_conf.mean(axis=1)
        confident = mean_conf >= threshold
        segments = np.zeros(1800, dtype=bool)
        start = None
        gap = 0
        for frame, good in enumerate(confident):
            if good:
                if start is None:
                    start = frame
                gap = 0
            elif start is not None:
                gap += 1
                if gap > max_gap:
                    end = frame - gap
                    if end >= start:
                        segments[start:end + 1] = True
                    start = None
                    gap = 0
        if start is not None:
            end = 1799 - gap
            if end >= start:
                segments[start:end + 1] = True
        valid_video |= segments & ~bad
    return valid_video
