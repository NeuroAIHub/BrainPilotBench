#!/usr/bin/env python3
"""Print the pinned ds003688 film filename inventory without signal download."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
SOURCE = json.loads((ROOT / "source_manifest.json").read_text())
COMMIT = SOURCE["dataset_git_commit"]
TREE_URL = f"https://api.github.com/repos/OpenNeuroDatasets/ds003688/git/trees/{COMMIT}?recursive=1"


def main() -> None:
    with urlopen(TREE_URL, timeout=30) as response:
        tree = json.load(response)
    if tree.get("truncated"):
        raise ValueError("The pinned Git tree is incomplete")
    paths = {item["path"]: item["sha"] for item in tree["tree"] if item["type"] == "blob"}
    ieeg = {path: sha for path, sha in paths.items() if re.search(r"^sub-\d+/ses-iemu/ieeg/", path)}
    events = [path for path in ieeg if re.search(r"_task-film_run-\d+_events\.tsv$", path)]
    clinical = [path for path in ieeg if re.search(r"_task-film_acq-clinical_run-\d+_ieeg\.json$", path)]
    subjects = sorted({path.split("/")[0] for path in clinical})
    if len(subjects) != 51 or len(events) != 52 or len(clinical) != 51:
        raise ValueError("The pinned iEEG film inventory differs from the article")
    records = []
    for subject in subjects:
        matching = [path for path in clinical if path.startswith(subject + "/")]
        if len(matching) != 1:
            raise ValueError(f"The subject has ambiguous clinical recordings: {subject}")
        sidecar = matching[0]
        match = re.search(r"_run-(\d+)_ieeg\.json$", sidecar)
        assert match
        run = int(match.group(1))
        stem = sidecar.removesuffix("_ieeg.json")
        directory = sidecar.rsplit("/", 1)[0]
        event_path = f"{directory}/{subject}_ses-iemu_task-film_run-{run}_events.tsv"
        channels_path = stem + "_channels.tsv"
        signal_path = stem + "_ieeg.eeg"
        for key in (event_path, channels_path, signal_path):
            if key not in ieeg:
                raise ValueError(f"The selected clinical recording is incomplete: {key}")
        records.append({
            "subject": subject,
            "selected_clinical_run": run,
            "events": {"path": event_path, "git_blob_sha1": ieeg[event_path]},
            "channels": {"path": channels_path, "git_blob_sha1": ieeg[channels_path]},
            "sidecar": {"path": sidecar, "git_blob_sha1": ieeg[sidecar]},
            "signal_pointer": {"path": signal_path, "git_blob_sha1": ieeg[signal_path]},
        })
    event_counts = {subject: sum(path.startswith(subject + "/") for path in events) for subject in subjects}
    print(json.dumps({
        "schema": "bpb-invasive-cohort-filename-inventory/1",
        "source_git_commit": COMMIT,
        "scope": "Pinned Git filename and blob metadata only. Signal files and event contents were not read. These participants have not passed channel, timing, signal, or artifact QC.",
        "iEEG_subjects_with_clinical_film_sidecars": len(subjects),
        "iEEG_film_event_files": len(events),
        "selection_rule": "Select the unique acquisition-clinical film recording for each subject and its matching run events. Do not count HDgrid or a second playback as another subject.",
        "duplicate_playback_resolution": "The pinned tree names sub-45 clinical run-1 and HDgrid run-2. Select clinical run-1. Other subjects with clinical run-2 have one film events file each. The article names sub-44 for the second playback; this identifier difference remains unresolved.",
        "subjects_with_multiple_film_event_files": [subject for subject, count in event_counts.items() if count > 1],
        "records": records,
    }, indent=2))


if __name__ == "__main__":
    main()
