#!/usr/bin/env python3
"""RSC place-cell benchmark.

Metrics
-------
1. Cross-session place-cell ratio stability.
2. Bayesian position-decoding significance against trial-wise circular shuffles.
3. Five-fold trial-grouped cross-validation stability.

The official decoding benchmark uses all recorded cells by default to avoid
circular feature selection. ``--decoder-cells place`` is available only for
legacy compatibility with analyses that decode from detected place cells.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy import io, ndimage
from sklearn.model_selection import KFold


SCHEMA_VERSION = "1.0"
EPS = 1e-12


@dataclass
class SessionData:
    session_index: int
    session_name: str
    neural_activity: np.ndarray  # cells x frames
    position_norm: np.ndarray  # frames
    position_cm: np.ndarray  # frames
    trial_id: np.ndarray  # frames
    timestamps_s: np.ndarray  # frames
    speed_cm_s: np.ndarray  # frames
    running_mask: np.ndarray  # frames
    alignment_method: str
    original_position_min: float
    original_position_max: float


@dataclass
class PlaceCellResult:
    n_total_cells: int
    n_place_cells: int
    place_cell_ratio: float
    place_cell_indices: np.ndarray
    spatial_information: np.ndarray
    p_values: np.ndarray
    null_thresholds: np.ndarray


@dataclass
class DecodingResult:
    real_median_decoding_error_cm: float
    shuffle_median_decoding_error_cm: float
    decoding_error_reduction: float
    decoding_improvement_ratio: float
    decoding_p_value: float
    decoding_significant: bool
    fold_decoding_errors_cm: list[float]
    mean_cv_error_cm: float
    std_cv_error_cm: float
    cv_decoding_error: float
    depends_on_trial_split: bool
    shuffle_errors_cm: list[float]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark RSC place-cell ratios and Bayesian position decoding."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="MAT file, one standardized NPZ file, or a directory of session NPZ files.",
    )
    parser.add_argument("--output", default="benchmark_results", help="Output directory.")
    parser.add_argument(
        "--sessions",
        default="all",
        help="MAT session indices, zero-based, e.g. '0,2,7'; default: all.",
    )
    parser.add_argument("--track-length-cm", type=float, default=90.0)
    parser.add_argument("--n-bins", type=int, default=50)
    parser.add_argument("--speed-threshold-cm-s", type=float, default=1.0)
    parser.add_argument("--speed-smooth-sigma-frames", type=float, default=2.0)
    parser.add_argument("--tuning-smooth-sigma-bins", type=float, default=1.0)
    parser.add_argument(
        "--sampling-rate-hz",
        type=float,
        default=19.02,
        help="Fallback sampling rate when timestamps are unavailable.",
    )
    parser.add_argument("--place-shuffles", type=int, default=500)
    parser.add_argument(
        "--place-alpha",
        type=float,
        default=0.025,
        help="Place-cell threshold: observed SI above the (1-alpha) null quantile.",
    )
    parser.add_argument("--decoding-shuffles", type=int, default=500)
    parser.add_argument("--decoding-alpha", type=float, default=0.05)
    parser.add_argument("--cv-folds", type=int, default=5)
    parser.add_argument(
        "--cv-threshold",
        type=float,
        default=0.20,
        help="Flag split dependence when std(fold errors)/mean(fold errors) exceeds this value.",
    )
    parser.add_argument(
        "--decoder-cells",
        choices=("all", "place"),
        default="all",
        help="Use all cells (official, avoids circular selection) or detected place cells.",
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--n-jobs", type=int, default=1, help="Parallel shuffle workers.")
    return parser


def _unwrap_scalar(value: Any) -> Any:
    while isinstance(value, np.ndarray) and value.size == 1:
        value = value.reshape(-1)[0]
    return value


def _extract_field(value: Any, field_names: Sequence[str], required: bool = True) -> Any:
    value = _unwrap_scalar(value)
    for name in field_names:
        if isinstance(value, dict) and name in value:
            return _unwrap_scalar(value[name])
        if isinstance(value, np.void) and value.dtype.names and name in value.dtype.names:
            return _unwrap_scalar(value[name])
        if hasattr(value, name):
            return _unwrap_scalar(getattr(value, name))
    if required:
        raise KeyError(f"None of the fields {field_names!r} was found.")
    return None


def _as_vector(value: Any, dtype: Any = float) -> np.ndarray:
    value = _unwrap_scalar(value)
    array = np.asarray(value, dtype=dtype).reshape(-1)
    return array


def _as_neural_matrix(value: Any) -> np.ndarray:
    value = _unwrap_scalar(value)
    array = np.asarray(value, dtype=float)
    if array.ndim != 2:
        raise ValueError(f"Neural activity must be 2-D, got shape {array.shape}.")
    # Expected orientation is cells x frames. A conservative heuristic flips a
    # clearly frame-major matrix while leaving ambiguous cases unchanged.
    if array.shape[0] > 5000 and array.shape[1] < 5000:
        array = array.T
    return array


def _flatten_mat_sessions(value: Any) -> list[Any]:
    array = np.asarray(value, dtype=object)
    return [_unwrap_scalar(item) for item in array.reshape(-1)]


def parse_session_indices(spec: str, n_sessions: int) -> list[int]:
    if spec.strip().lower() == "all":
        return list(range(n_sessions))
    indices: list[int] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        index = int(token)
        if index < 0 or index >= n_sessions:
            raise IndexError(f"Session index {index} is outside [0, {n_sessions - 1}].")
        indices.append(index)
    if not indices:
        raise ValueError("No valid session indices were provided.")
    return sorted(set(indices))


def _interpolate_rows(
    neural: np.ndarray, source_time: np.ndarray, target_time: np.ndarray
) -> np.ndarray:
    if source_time.size != neural.shape[1]:
        raise ValueError("Imaging timestamp count does not match neural frame count.")
    order = np.argsort(source_time)
    source_time = source_time[order]
    neural = neural[:, order]
    unique_time, unique_indices = np.unique(source_time, return_index=True)
    neural = neural[:, unique_indices]
    output = np.empty((neural.shape[0], target_time.size), dtype=float)
    for cell_index, trace in enumerate(neural):
        output[cell_index] = np.interp(
            target_time, unique_time, trace, left=np.nan, right=np.nan
        )
    return output


def _align_arrays(
    neural: np.ndarray,
    position: np.ndarray,
    trial_id: np.ndarray,
    sampling_rate_hz: float,
    imaging_time: np.ndarray | None = None,
    behavior_time: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, str]:
    n_neural = neural.shape[1]
    n_behavior = position.size
    if trial_id.size != n_behavior:
        raise ValueError("position and trial arrays must have the same length.")

    if n_neural == n_behavior:
        if behavior_time is not None and behavior_time.size == n_behavior:
            timestamps = behavior_time
            method = "direct_behavior_time"
        elif imaging_time is not None and imaging_time.size == n_neural:
            timestamps = imaging_time
            method = "direct_imaging_time"
        else:
            timestamps = np.arange(n_neural, dtype=float) / sampling_rate_hz
            method = "direct_fallback_sampling_rate"
        return neural, position, trial_id, timestamps, method

    if (
        imaging_time is not None
        and behavior_time is not None
        and imaging_time.size == n_neural
        and behavior_time.size == n_behavior
    ):
        neural_aligned = _interpolate_rows(neural, imaging_time, behavior_time)
        return neural_aligned, position, trial_id, behavior_time, "neural_to_behavior_timestamps"

    # Legacy fallback: align behavior to neural frames using normalized time.
    source_grid = np.linspace(0.0, 1.0, n_behavior)
    target_grid = np.linspace(0.0, 1.0, n_neural)
    position_aligned = np.interp(target_grid, source_grid, position)
    trial_aligned = np.rint(np.interp(target_grid, source_grid, trial_id)).astype(int)
    if imaging_time is not None and imaging_time.size == n_neural:
        timestamps = imaging_time
        method = "behavior_to_imaging_normalized_time"
    else:
        timestamps = np.arange(n_neural, dtype=float) / sampling_rate_hz
        method = "behavior_to_neural_fallback_sampling_rate"
    return neural, position_aligned, trial_aligned, timestamps, method


def _prepare_session(
    session_index: int,
    session_name: str,
    neural: np.ndarray,
    position: np.ndarray,
    trial_id: np.ndarray,
    timestamps_s: np.ndarray,
    alignment_method: str,
    track_length_cm: float,
    speed_threshold_cm_s: float,
    speed_smooth_sigma_frames: float,
    sampling_rate_hz: float,
) -> SessionData:
    neural = np.asarray(neural, dtype=float)
    position = np.asarray(position, dtype=float).reshape(-1)
    trial_id_float = np.asarray(trial_id, dtype=float).reshape(-1)
    timestamps_s = np.asarray(timestamps_s, dtype=float).reshape(-1)

    if neural.shape[1] != position.size or position.size != trial_id_float.size:
        raise ValueError("Aligned neural, position, and trial arrays have inconsistent lengths.")
    if timestamps_s.size != position.size:
        timestamps_s = np.arange(position.size, dtype=float) / sampling_rate_hz
        alignment_method += "+timestamp_fallback"

    valid_position = np.isfinite(position)
    if valid_position.sum() < 2:
        raise ValueError("Session contains fewer than two finite position samples.")
    p_min = float(np.nanmin(position))
    p_max = float(np.nanmax(position))
    if not p_max > p_min:
        raise ValueError("Position has zero range.")
    position_norm = (position - p_min) / (p_max - p_min)
    position_norm = np.clip(position_norm, 0.0, 1.0)
    position_cm = position_norm * track_length_cm

    trial_id_clean = np.zeros_like(trial_id_float, dtype=int)
    finite_trials = np.isfinite(trial_id_float)
    trial_id_clean[finite_trials] = np.rint(trial_id_float[finite_trials]).astype(int)

    # Non-finite and negative deconvolved values are not valid Poisson rates.
    neural = np.nan_to_num(neural, nan=0.0, posinf=0.0, neginf=0.0)
    neural = np.clip(neural, 0.0, None)

    dt = np.diff(timestamps_s)
    positive_dt = dt[np.isfinite(dt) & (dt > 0)]
    fallback_dt = 1.0 / sampling_rate_hz
    median_dt = float(np.median(positive_dt)) if positive_dt.size else fallback_dt
    dt = np.where(np.isfinite(dt) & (dt > 0), dt, median_dt)

    speed = np.zeros(position_cm.size, dtype=float)
    delta_position = np.diff(position_cm)
    same_trial = trial_id_clean[1:] == trial_id_clean[:-1]
    speed[1:] = np.where(same_trial, np.abs(delta_position) / dt, 0.0)
    if speed_smooth_sigma_frames > 0:
        speed = ndimage.gaussian_filter1d(
            speed, sigma=speed_smooth_sigma_frames, mode="nearest"
        )
    transition = np.r_[True, ~same_trial]
    speed[transition] = 0.0

    valid_frame = (
        np.isfinite(position_norm)
        & np.isfinite(timestamps_s)
        & (trial_id_clean > 0)
    )
    running_mask = valid_frame & (speed >= speed_threshold_cm_s)

    return SessionData(
        session_index=session_index,
        session_name=session_name,
        neural_activity=neural,
        position_norm=position_norm,
        position_cm=position_cm,
        trial_id=trial_id_clean,
        timestamps_s=timestamps_s,
        speed_cm_s=speed,
        running_mask=running_mask,
        alignment_method=alignment_method,
        original_position_min=p_min,
        original_position_max=p_max,
    )


def load_mat_sessions(path: Path, args: argparse.Namespace) -> list[SessionData]:
    try:
        mat = io.loadmat(path, squeeze_me=False, struct_as_record=False)
    except NotImplementedError as exc:
        raise RuntimeError(
            "MATLAB v7.3 files are not supported by scipy.io.loadmat. "
            "Export the sessions to the standardized NPZ format described in README.md."
        ) from exc

    required_keys = {"deconv_all", "behavior_vr_all"}
    missing = required_keys - set(mat)
    if missing:
        raise KeyError(f"MAT input is missing required keys: {sorted(missing)}")

    neural_sessions = _flatten_mat_sessions(mat["deconv_all"])
    behavior_sessions = _flatten_mat_sessions(mat["behavior_vr_all"])
    if len(neural_sessions) != len(behavior_sessions):
        raise ValueError("deconv_all and behavior_vr_all contain different session counts.")
    tcs_sessions = (
        _flatten_mat_sessions(mat["tcs_all"]) if "tcs_all" in mat else [None] * len(neural_sessions)
    )
    selected = parse_session_indices(args.sessions, len(neural_sessions))

    sessions: list[SessionData] = []
    for index in selected:
        neural = _as_neural_matrix(neural_sessions[index])
        behavior = behavior_sessions[index]
        position = _as_vector(_extract_field(behavior, ("pos_norm", "position", "pos")))
        trial_id = _as_vector(_extract_field(behavior, ("trial", "trial_id", "trials")))
        behavior_time_raw = _extract_field(
            behavior,
            ("ts", "time", "timestamps", "timestamp", "t", "tt"),
            required=False,
        )
        behavior_time = (
            _as_vector(behavior_time_raw) if behavior_time_raw is not None else None
        )

        imaging_time = None
        if index < len(tcs_sessions) and tcs_sessions[index] is not None:
            imaging_raw = _extract_field(
                tcs_sessions[index], ("tt", "time", "timestamps", "t"), required=False
            )
            if imaging_raw is not None:
                imaging_time = _as_vector(imaging_raw)

        # MATLAB file stores deconvolved activity as frames x cells in this
        # dataset. Resolve orientation from the imaging timestamps (preferred)
        # or behavior length before temporal alignment.
        expected_frames = imaging_time.size if imaging_time is not None else position.size
        if neural.shape[0] == expected_frames and neural.shape[1] != expected_frames:
            neural = neural.T
        elif neural.shape[1] != expected_frames:
            # Fallback: the dimension closer to the observed time-vector length
            # is interpreted as frames.
            if abs(neural.shape[0] - expected_frames) < abs(neural.shape[1] - expected_frames):
                neural = neural.T

        neural, position, trial_id, timestamps, alignment = _align_arrays(
            neural=neural,
            position=position,
            trial_id=trial_id,
            sampling_rate_hz=args.sampling_rate_hz,
            imaging_time=imaging_time,
            behavior_time=behavior_time,
        )
        sessions.append(
            _prepare_session(
                session_index=index,
                session_name=f"session_{index:03d}",
                neural=neural,
                position=position,
                trial_id=trial_id,
                timestamps_s=timestamps,
                alignment_method=alignment,
                track_length_cm=args.track_length_cm,
                speed_threshold_cm_s=args.speed_threshold_cm_s,
                speed_smooth_sigma_frames=args.speed_smooth_sigma_frames,
                sampling_rate_hz=args.sampling_rate_hz,
            )
        )
    return sessions


def load_npz_session(path: Path, session_index: int, args: argparse.Namespace) -> SessionData:
    with np.load(path, allow_pickle=False) as data:
        required = {"neural_activity", "position_norm", "trial_id"}
        missing = required - set(data.files)
        if missing:
            raise KeyError(f"{path.name} is missing NPZ keys: {sorted(missing)}")
        neural = _as_neural_matrix(data["neural_activity"])
        position = _as_vector(data["position_norm"])
        trial_id = _as_vector(data["trial_id"])
        timestamps = (
            _as_vector(data["timestamps_s"])
            if "timestamps_s" in data.files
            else np.arange(position.size, dtype=float) / args.sampling_rate_hz
        )

    neural, position, trial_id, timestamps, alignment = _align_arrays(
        neural=neural,
        position=position,
        trial_id=trial_id,
        sampling_rate_hz=args.sampling_rate_hz,
        imaging_time=timestamps if timestamps.size == neural.shape[1] else None,
        behavior_time=timestamps if timestamps.size == position.size else None,
    )
    return _prepare_session(
        session_index=session_index,
        session_name=path.stem,
        neural=neural,
        position=position,
        trial_id=trial_id,
        timestamps_s=timestamps,
        alignment_method=alignment,
        track_length_cm=args.track_length_cm,
        speed_threshold_cm_s=args.speed_threshold_cm_s,
        speed_smooth_sigma_frames=args.speed_smooth_sigma_frames,
        sampling_rate_hz=args.sampling_rate_hz,
    )


def load_sessions(path: Path, args: argparse.Namespace) -> list[SessionData]:
    if path.is_dir():
        files = sorted(path.glob("*.npz"))
        if not files:
            raise FileNotFoundError(f"No NPZ files found in {path}.")
        return [load_npz_session(file, index, args) for index, file in enumerate(files)]
    if path.suffix.lower() == ".mat":
        return load_mat_sessions(path, args)
    if path.suffix.lower() == ".npz":
        return [load_npz_session(path, 0, args)]
    raise ValueError("Input must be a .mat file, a .npz file, or a directory of .npz files.")


def position_bin_indices(position_norm: np.ndarray, n_bins: int) -> np.ndarray:
    return np.minimum((position_norm * n_bins).astype(int), n_bins - 1)


def compute_rate_maps_and_si(
    neural_activity: np.ndarray,
    position_norm: np.ndarray,
    mask: np.ndarray,
    n_bins: int,
    smooth_sigma_bins: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if mask.sum() == 0:
        raise ValueError("No frames remain after applying the running mask.")
    bin_index = position_bin_indices(position_norm[mask], n_bins)
    occupancy = np.bincount(bin_index, minlength=n_bins).astype(float)
    one_hot = np.eye(n_bins, dtype=float)[bin_index]
    activity = neural_activity[:, mask]
    activity_sum = activity @ one_hot
    rate_map = np.divide(
        activity_sum,
        occupancy[None, :],
        out=np.zeros_like(activity_sum),
        where=occupancy[None, :] > 0,
    )
    if smooth_sigma_bins > 0:
        rate_map = ndimage.gaussian_filter1d(
            rate_map, sigma=smooth_sigma_bins, axis=1, mode="nearest"
        )

    occupancy_probability = occupancy / max(float(occupancy.sum()), 1.0)
    mean_rate = np.sum(rate_map * occupancy_probability[None, :], axis=1)
    ratio = np.divide(
        rate_map,
        mean_rate[:, None],
        out=np.zeros_like(rate_map),
        where=mean_rate[:, None] > EPS,
    )
    valid = ratio > 0
    information_terms = np.zeros_like(ratio)
    information_terms[valid] = ratio[valid] * np.log2(ratio[valid])
    spatial_information = np.sum(
        occupancy_probability[None, :] * information_terms, axis=1
    )
    return rate_map, occupancy, spatial_information


def trial_circular_shuffle(
    neural_activity: np.ndarray, trial_id: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    shuffled = neural_activity.copy()
    for trial in np.unique(trial_id[trial_id > 0]):
        indices = np.flatnonzero(trial_id == trial)
        n = indices.size
        if n < 3:
            shuffled[:, indices] = neural_activity[:, indices]
            continue
        min_shift = max(1, int(math.ceil(0.20 * n)))
        max_shift = max(min_shift, int(math.floor(0.80 * n)))
        shift = int(rng.integers(min_shift, max_shift + 1))
        shuffled[:, indices] = np.roll(neural_activity[:, indices], shift, axis=1)
    return shuffled


def identify_place_cells(
    session: SessionData, args: argparse.Namespace, rng: np.random.Generator
) -> PlaceCellResult:
    _, _, real_si = compute_rate_maps_and_si(
        neural_activity=session.neural_activity,
        position_norm=session.position_norm,
        mask=session.running_mask,
        n_bins=args.n_bins,
        smooth_sigma_bins=args.tuning_smooth_sigma_bins,
    )
    null_si = np.empty((args.place_shuffles, session.neural_activity.shape[0]), dtype=float)
    shuffle_seeds = rng.integers(0, np.iinfo(np.uint32).max, size=args.place_shuffles, dtype=np.uint32)

    def _place_shuffle(seed: np.uint32) -> np.ndarray:
        local_rng = np.random.default_rng(int(seed))
        shuffled = trial_circular_shuffle(session.neural_activity, session.trial_id, local_rng)
        _, _, shuffled_si = compute_rate_maps_and_si(
            neural_activity=shuffled,
            position_norm=session.position_norm,
            mask=session.running_mask,
            n_bins=args.n_bins,
            smooth_sigma_bins=args.tuning_smooth_sigma_bins,
        )
        return shuffled_si

    progress_step = max(1, args.place_shuffles // 5)
    if args.n_jobs > 1:
        with ThreadPoolExecutor(max_workers=args.n_jobs) as executor:
            for shuffle_index, shuffled_si in enumerate(executor.map(_place_shuffle, shuffle_seeds)):
                null_si[shuffle_index] = shuffled_si
                if (shuffle_index + 1) % progress_step == 0:
                    print(f"    place-cell shuffles: {shuffle_index + 1}/{args.place_shuffles}", flush=True)
    else:
        for shuffle_index, seed in enumerate(shuffle_seeds):
            null_si[shuffle_index] = _place_shuffle(seed)
            if (shuffle_index + 1) % progress_step == 0:
                print(f"    place-cell shuffles: {shuffle_index + 1}/{args.place_shuffles}", flush=True)

    thresholds = np.quantile(null_si, 1.0 - args.place_alpha, axis=0)
    place_mask = real_si > thresholds
    p_values = (1.0 + np.sum(null_si >= real_si[None, :], axis=0)) / (
        args.place_shuffles + 1.0
    )
    indices = np.flatnonzero(place_mask)
    n_cells = session.neural_activity.shape[0]
    return PlaceCellResult(
        n_total_cells=n_cells,
        n_place_cells=int(indices.size),
        place_cell_ratio=float(indices.size / n_cells) if n_cells else float("nan"),
        place_cell_indices=indices,
        spatial_information=real_si,
        p_values=p_values,
        null_thresholds=thresholds,
    )


def make_trial_folds(
    trial_id: np.ndarray,
    running_mask: np.ndarray,
    n_splits: int,
    random_state: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    trials = np.unique(trial_id[running_mask & (trial_id > 0)])
    if trials.size < n_splits:
        raise ValueError(
            f"Need at least {n_splits} valid trials, but found {trials.size}."
        )
    splitter = KFold(n_splits=n_splits, shuffle=True, random_state=random_state)
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for train_indices, test_indices in splitter.split(trials):
        folds.append((trials[train_indices], trials[test_indices]))
    return folds


def decode_with_folds(
    neural_activity: np.ndarray,
    position_norm: np.ndarray,
    position_cm: np.ndarray,
    trial_id: np.ndarray,
    running_mask: np.ndarray,
    cell_indices: np.ndarray,
    folds: Sequence[tuple[np.ndarray, np.ndarray]],
    n_bins: int,
    track_length_cm: float,
    smooth_sigma_bins: float,
) -> tuple[np.ndarray, list[float]]:
    if cell_indices.size == 0:
        raise ValueError("Decoder received an empty cell set.")
    selected_activity = neural_activity[cell_indices]
    bin_centers_cm = (np.arange(n_bins, dtype=float) + 0.5) * (
        track_length_cm / n_bins
    )
    all_errors: list[np.ndarray] = []
    fold_errors: list[float] = []

    for train_trials, test_trials in folds:
        train_mask = running_mask & np.isin(trial_id, train_trials)
        test_mask = running_mask & np.isin(trial_id, test_trials)
        if train_mask.sum() == 0 or test_mask.sum() == 0:
            raise ValueError("A cross-validation fold has no train or test frames.")

        rate_map, _, _ = compute_rate_maps_and_si(
            neural_activity=selected_activity,
            position_norm=position_norm,
            mask=train_mask,
            n_bins=n_bins,
            smooth_sigma_bins=smooth_sigma_bins,
        )
        rate_map = np.clip(rate_map, EPS, None)
        test_activity = selected_activity[:, test_mask].T
        # Poisson log-likelihood up to constants independent of position.
        log_posterior = test_activity @ np.log(rate_map) - np.sum(
            rate_map, axis=0, keepdims=True
        )
        predicted_cm = bin_centers_cm[np.argmax(log_posterior, axis=1)]
        errors = np.abs(predicted_cm - position_cm[test_mask])
        all_errors.append(errors)
        fold_errors.append(float(np.median(errors)))

    return np.concatenate(all_errors), fold_errors


def run_decoding_benchmark(
    session: SessionData,
    place_result: PlaceCellResult,
    args: argparse.Namespace,
    rng: np.random.Generator,
) -> DecodingResult:
    if args.decoder_cells == "all":
        cell_indices = np.arange(session.neural_activity.shape[0], dtype=int)
    else:
        cell_indices = place_result.place_cell_indices
    if cell_indices.size == 0:
        raise ValueError("No cells are available for decoding.")

    folds = make_trial_folds(
        trial_id=session.trial_id,
        running_mask=session.running_mask,
        n_splits=args.cv_folds,
        random_state=args.seed + session.session_index,
    )
    real_errors, fold_errors = decode_with_folds(
        neural_activity=session.neural_activity,
        position_norm=session.position_norm,
        position_cm=session.position_cm,
        trial_id=session.trial_id,
        running_mask=session.running_mask,
        cell_indices=cell_indices,
        folds=folds,
        n_bins=args.n_bins,
        track_length_cm=args.track_length_cm,
        smooth_sigma_bins=args.tuning_smooth_sigma_bins,
    )
    real_median = float(np.median(real_errors))

    shuffle_seeds = rng.integers(0, np.iinfo(np.uint32).max, size=args.decoding_shuffles, dtype=np.uint32)

    def _decode_shuffle(seed: np.uint32) -> float:
        local_rng = np.random.default_rng(int(seed))
        shuffled = trial_circular_shuffle(session.neural_activity, session.trial_id, local_rng)
        shuffled_errors, _ = decode_with_folds(
            neural_activity=shuffled,
            position_norm=session.position_norm,
            position_cm=session.position_cm,
            trial_id=session.trial_id,
            running_mask=session.running_mask,
            cell_indices=cell_indices,
            folds=folds,
            n_bins=args.n_bins,
            track_length_cm=args.track_length_cm,
            smooth_sigma_bins=args.tuning_smooth_sigma_bins,
        )
        return float(np.median(shuffled_errors))

    progress_step = max(1, args.decoding_shuffles // 5)
    shuffle_medians: list[float] = []
    if args.n_jobs > 1:
        with ThreadPoolExecutor(max_workers=args.n_jobs) as executor:
            for shuffle_index, error in enumerate(executor.map(_decode_shuffle, shuffle_seeds)):
                shuffle_medians.append(error)
                if (shuffle_index + 1) % progress_step == 0:
                    print(f"    decoding shuffles: {shuffle_index + 1}/{args.decoding_shuffles}", flush=True)
    else:
        for shuffle_index, seed in enumerate(shuffle_seeds):
            shuffle_medians.append(_decode_shuffle(seed))
            if (shuffle_index + 1) % progress_step == 0:
                print(f"    decoding shuffles: {shuffle_index + 1}/{args.decoding_shuffles}", flush=True)

    shuffle_array = np.asarray(shuffle_medians, dtype=float)
    shuffle_median = float(np.median(shuffle_array))
    reduction = float(shuffle_median - real_median)
    improvement_ratio = (
        float(reduction / shuffle_median) if shuffle_median > EPS else float("nan")
    )
    p_value = float(
        (1.0 + np.sum(shuffle_array <= real_median))
        / (args.decoding_shuffles + 1.0)
    )
    significant = bool(real_median < shuffle_median and p_value < args.decoding_alpha)

    mean_cv = float(np.mean(fold_errors))
    std_cv = float(np.std(fold_errors, ddof=1)) if len(fold_errors) > 1 else 0.0
    cv_error = float(std_cv / mean_cv) if mean_cv > EPS else float("nan")
    depends = bool(np.isfinite(cv_error) and cv_error > args.cv_threshold)

    return DecodingResult(
        real_median_decoding_error_cm=real_median,
        shuffle_median_decoding_error_cm=shuffle_median,
        decoding_error_reduction=reduction,
        decoding_improvement_ratio=improvement_ratio,
        decoding_p_value=p_value,
        decoding_significant=significant,
        fold_decoding_errors_cm=fold_errors,
        mean_cv_error_cm=mean_cv,
        std_cv_error_cm=std_cv,
        cv_decoding_error=cv_error,
        depends_on_trial_split=depends,
        shuffle_errors_cm=shuffle_medians,
    )


def finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def aggregate_results(
    session_rows: list[dict[str, Any]],
    decoding_results: list[DecodingResult],
    args: argparse.Namespace,
) -> dict[str, Any]:
    ratios = np.asarray([row["place_cell_ratio"] for row in session_rows], dtype=float)
    ratio_mean = float(np.mean(ratios)) if ratios.size else float("nan")
    ratio_std = (
        float(np.std(ratios, ddof=1)) if ratios.size > 1 else 0.0
    )

    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "benchmark_name": "rsc_place_cell_benchmark",
        "metric_aggregation": "equal-session weighting; medians across sessions",
        "config": {
            "track_length_cm": args.track_length_cm,
            "n_bins": args.n_bins,
            "speed_threshold_cm_s": args.speed_threshold_cm_s,
            "place_shuffles": args.place_shuffles,
            "place_alpha": args.place_alpha,
            "decoding_shuffles": args.decoding_shuffles,
            "decoding_alpha": args.decoding_alpha,
            "cv_folds": args.cv_folds,
            "cv_threshold": args.cv_threshold,
            "decoder_cells": args.decoder_cells,
            "seed": args.seed,
            "n_jobs": args.n_jobs,
        },
        "cross_session_place_cell_stability": {
            "n_sessions_evaluated": len(session_rows),
            "place_cell_ratio_mean": finite_or_none(ratio_mean),
            "place_cell_ratio_std": finite_or_none(ratio_std),
        },
    }

    if decoding_results:
        real_session = np.asarray(
            [result.real_median_decoding_error_cm for result in decoding_results]
        )
        real_median = float(np.median(real_session))
        shuffle_matrix = np.asarray(
            [result.shuffle_errors_cm for result in decoding_results], dtype=float
        )
        aggregate_shuffle_distribution = np.median(shuffle_matrix, axis=0)
        shuffle_median = float(np.median(aggregate_shuffle_distribution))
        reduction = float(shuffle_median - real_median)
        improvement = (
            float(reduction / shuffle_median) if shuffle_median > EPS else float("nan")
        )
        p_value = float(
            (1.0 + np.sum(aggregate_shuffle_distribution <= real_median))
            / (aggregate_shuffle_distribution.size + 1.0)
        )
        significant = bool(
            real_median < shuffle_median and p_value < args.decoding_alpha
        )

        fold_matrix = np.asarray(
            [result.fold_decoding_errors_cm for result in decoding_results], dtype=float
        )
        aggregate_fold_errors = np.median(fold_matrix, axis=0)
        mean_cv = float(np.mean(aggregate_fold_errors))
        std_cv = (
            float(np.std(aggregate_fold_errors, ddof=1))
            if aggregate_fold_errors.size > 1
            else 0.0
        )
        cv_error = float(std_cv / mean_cv) if mean_cv > EPS else float("nan")
        depends = bool(np.isfinite(cv_error) and cv_error > args.cv_threshold)

        summary["position_decoding_significance"] = {
            "real_median_decoding_error_cm": real_median,
            "shuffle_median_decoding_error_cm": shuffle_median,
            "decoding_error_reduction": reduction,
            "decoding_improvement_ratio": finite_or_none(improvement),
            "decoding_p_value": p_value,
            "decoding_significant": significant,
            "reliable_position_information": significant,
            "conclusion": (
                "RSC population activity contains reliable positional information."
                if significant
                else "Reliable positional information was not established under the benchmark criterion."
            ),
        }
        summary["decoding_stability"] = {
            "fold_decoding_errors_cm": aggregate_fold_errors.tolist(),
            "mean_cv_error_cm": mean_cv,
            "std_cv_error_cm": std_cv,
            "cv_decoding_error": finite_or_none(cv_error),
            "depends_on_trial_split": depends,
            "stability_label": "split_sensitive" if depends else "stable",
        }
    else:
        summary["position_decoding_significance"] = None
        summary["decoding_stability"] = None
    return summary


def write_outputs(
    output_dir: Path,
    summary: dict[str, Any],
    session_rows: list[dict[str, Any]],
    shuffle_rows: list[dict[str, Any]],
    cell_rows: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "benchmark_summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2, allow_nan=False)

    if session_rows:
        fieldnames = list(session_rows[0].keys())
        with (output_dir / "session_metrics.csv").open(
            "w", encoding="utf-8", newline=""
        ) as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(session_rows)

    if shuffle_rows:
        with (output_dir / "shuffle_decoding_errors.csv").open(
            "w", encoding="utf-8", newline=""
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=("session_index", "session_name", "shuffle_index", "median_decoding_error_cm"),
            )
            writer.writeheader()
            writer.writerows(shuffle_rows)

    if cell_rows:
        with (output_dir / "cell_place_metrics.csv").open(
            "w", encoding="utf-8", newline=""
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=(
                    "session_index",
                    "session_name",
                    "cell_index",
                    "spatial_information",
                    "shuffle_p_value",
                    "null_threshold",
                    "is_place_cell",
                ),
            )
            writer.writeheader()
            writer.writerows(cell_rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.n_bins < 2:
        parser.error("--n-bins must be at least 2.")
    if args.place_shuffles < 1 or args.decoding_shuffles < 1:
        parser.error("Shuffle counts must be positive.")
    if args.n_jobs < 1:
        parser.error("--n-jobs must be at least 1.")
    if args.cv_folds != 5:
        parser.error("This benchmark requires exactly 5 cross-validation folds.")

    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    if not input_path.exists():
        parser.error(f"Input does not exist: {input_path}")

    print(f"Loading input: {input_path}")
    sessions = load_sessions(input_path, args)
    if not sessions:
        raise RuntimeError("No sessions were loaded.")
    print(f"Loaded {len(sessions)} session(s).")

    session_rows: list[dict[str, Any]] = []
    shuffle_rows: list[dict[str, Any]] = []
    cell_rows: list[dict[str, Any]] = []
    decoding_results: list[DecodingResult] = []
    skipped_sessions: list[dict[str, str]] = []

    for offset, session in enumerate(sessions):
        print(
            f"\n[{offset + 1}/{len(sessions)}] {session.session_name}: "
            f"{session.neural_activity.shape[0]} cells, "
            f"{session.neural_activity.shape[1]} frames, "
            f"{np.unique(session.trial_id[session.trial_id > 0]).size} trials, "
            f"{session.running_mask.sum()} running frames"
        )
        session_rng = np.random.default_rng(args.seed + 1009 * session.session_index)
        try:
            place_result = identify_place_cells(session, args, session_rng)
        except Exception as exc:  # keep other sessions evaluable
            skipped_sessions.append(
                {"session_name": session.session_name, "reason": f"place-cell stage: {exc}"}
            )
            print(f"  SKIPPED: {exc}", file=sys.stderr)
            continue

        print(
            f"  Place cells: {place_result.n_place_cells}/{place_result.n_total_cells} "
            f"({place_result.place_cell_ratio:.3f})"
        )
        place_cell_set = set(place_result.place_cell_indices.tolist())
        for cell_index in range(place_result.n_total_cells):
            cell_rows.append(
                {
                    "session_index": session.session_index,
                    "session_name": session.session_name,
                    "cell_index": cell_index,
                    "spatial_information": float(place_result.spatial_information[cell_index]),
                    "shuffle_p_value": float(place_result.p_values[cell_index]),
                    "null_threshold": float(place_result.null_thresholds[cell_index]),
                    "is_place_cell": bool(cell_index in place_cell_set),
                }
            )

        row: dict[str, Any] = {
            "session_index": session.session_index,
            "session_number": session.session_index + 1,
            "session_name": session.session_name,
            "alignment_method": session.alignment_method,
            "n_total_cells": place_result.n_total_cells,
            "n_place_cells": place_result.n_place_cells,
            "place_cell_ratio": place_result.place_cell_ratio,
            "n_frames": session.neural_activity.shape[1],
            "n_running_frames": int(session.running_mask.sum()),
            "n_trials": int(np.unique(session.trial_id[session.trial_id > 0]).size),
        }

        try:
            decoding = run_decoding_benchmark(session, place_result, args, session_rng)
            decoding_results.append(decoding)
            row.update(
                {
                    "real_median_decoding_error_cm": decoding.real_median_decoding_error_cm,
                    "shuffle_median_decoding_error_cm": decoding.shuffle_median_decoding_error_cm,
                    "decoding_error_reduction": decoding.decoding_error_reduction,
                    "decoding_improvement_ratio": decoding.decoding_improvement_ratio,
                    "decoding_p_value": decoding.decoding_p_value,
                    "decoding_significant": decoding.decoding_significant,
                    "mean_cv_error_cm": decoding.mean_cv_error_cm,
                    "std_cv_error_cm": decoding.std_cv_error_cm,
                    "cv_decoding_error": decoding.cv_decoding_error,
                    "depends_on_trial_split": decoding.depends_on_trial_split,
                }
            )
            for fold_index, error in enumerate(decoding.fold_decoding_errors_cm, start=1):
                row[f"fold_{fold_index}_error_cm"] = error
            for shuffle_index, error in enumerate(decoding.shuffle_errors_cm):
                shuffle_rows.append(
                    {
                        "session_index": session.session_index,
                        "session_name": session.session_name,
                        "shuffle_index": shuffle_index,
                        "median_decoding_error_cm": error,
                    }
                )
        except Exception as exc:
            print(f"  Decoding skipped: {exc}", file=sys.stderr)
            row.update(
                {
                    "real_median_decoding_error_cm": "",
                    "shuffle_median_decoding_error_cm": "",
                    "decoding_error_reduction": "",
                    "decoding_improvement_ratio": "",
                    "decoding_p_value": "",
                    "decoding_significant": "",
                    "mean_cv_error_cm": "",
                    "std_cv_error_cm": "",
                    "cv_decoding_error": "",
                    "depends_on_trial_split": "",
                }
            )
            for fold_index in range(1, args.cv_folds + 1):
                row[f"fold_{fold_index}_error_cm"] = ""
            skipped_sessions.append(
                {"session_name": session.session_name, "reason": f"decoding stage: {exc}"}
            )

        session_rows.append(row)

    if not session_rows:
        raise RuntimeError("No session completed the place-cell benchmark.")

    summary = aggregate_results(session_rows, decoding_results, args)
    summary["input"] = str(input_path)
    summary["skipped_sessions"] = skipped_sessions
    write_outputs(output_dir, summary, session_rows, shuffle_rows, cell_rows)

    print(f"\nBenchmark complete. Results: {output_dir}")
    print("  - benchmark_summary.json")
    print("  - session_metrics.csv")
    print("  - shuffle_decoding_errors.csv")
    print("  - cell_place_metrics.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
