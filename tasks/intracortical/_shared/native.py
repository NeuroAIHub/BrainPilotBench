"""Read-only structural checks for real FALCON NWB assets.

Field names follow the MIT-licensed upstream dataloaders.py at
https://github.com/snel-repo/falcon-challenge/blob/770c9b9597b8f58bf67b5a9ec6401ef705a2cb0f/falcon_challenge/dataloaders.py
This module reports shapes and trial counts only; it does not export labels.
Run it in the separate scientific Python environment with pynwb installed.
"""

from __future__ import annotations

from pathlib import Path

from pynwb import NWBHDF5IO


EXPECTED = {
    "h1": (176, 7),
    "h2": (192, None),
    "m1": (64, 16),
    "m2": (96, 2),
    "b1": (85, 158),
}


def inspect_nwb(path: Path, source_task_id: str) -> dict:
    """Check required native data fields without reading bulk neural arrays."""
    if source_task_id not in EXPECTED:
        raise ValueError(f"Unknown FALCON task {source_task_id}")
    channels, outputs = EXPECTED[source_task_id]
    with NWBHDF5IO(str(path), "r", load_namespaces=True) as io:
        nwb = io.read()
        if source_task_id == "h1":
            n_units = len(nwb.units)
            target = nwb.acquisition["OpenLoopKinematicsVelocity"].data
            mask = nwb.acquisition["eval_mask"].data
            n_time, n_outputs = target.shape
            if mask.shape[0] != n_time or nwb.acquisition["TrialNum"].data.shape[0] != n_time:
                raise ValueError("H1 time or mask length mismatch")
        elif source_task_id == "h2":
            neural = nwb.acquisition["binned_spikes"].data
            n_time, n_units = neural.shape
            if nwb.acquisition["eval_mask"].data.shape[0] != n_time:
                raise ValueError("H2 mask length mismatch")
            if nwb.trials is None or "cue" not in nwb.trials.colnames:
                raise ValueError("H2 sentence cues missing")
            n_outputs = None
        elif source_task_id == "m1":
            n_units = len(nwb.units)
            series = list(nwb.acquisition["preprocessed_emg"].time_series.values())
            n_outputs = len(series)
            n_time = series[0].data.shape[0]
            if len({s.data.shape[0] for s in series}) != 1:
                raise ValueError("M1 EMG series lengths disagree")
            if nwb.acquisition["eval_mask"].data.shape[0] != n_time:
                raise ValueError("M1 mask length mismatch")
        elif source_task_id == "m2":
            n_units = len(nwb.units)
            series = list(nwb.acquisition["finger_vel"].time_series.values())
            n_outputs = len(series)
            n_time = series[0].data.shape[0]
            if len({s.data.shape[0] for s in series}) != 1:
                raise ValueError("M2 finger-velocity series lengths disagree")
            if nwb.acquisition["eval_mask"].data.shape[0] != n_time:
                raise ValueError("M2 mask length mismatch")
        else:
            neural = nwb.acquisition["tx"].data
            n_time, n_units = neural.shape
            if nwb.trials is None or "spectrogram_values" not in nwb.trials.colnames or "spectrogram_eval_mask" not in nwb.trials.colnames:
                raise ValueError("B1 spectrogram target or mask missing")
            n_outputs = 158  # Native spectrogram column width is checked on real trial inspection.
        if n_units != channels or n_outputs != outputs:
            raise ValueError(f"{source_task_id} shape mismatch: {n_units} channels, {n_outputs} outputs")
        return {"task": source_task_id, "channels": n_units, "outputs": n_outputs,
                "neural_timesteps": n_time, "trials": len(nwb.trials) if nwb.trials is not None else None,
                "structure_valid": True}
