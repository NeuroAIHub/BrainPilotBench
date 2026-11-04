"""Owner converter, executed only in an offline Docker container.

The author stores dictionaries in NumPy object files. Input hashes must be
verified against the downloaded OSF metadata before invoking this converter.
It writes numerical arrays/JSON, so no pickle crosses into Agent tasks/scoring.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    import numpy as np
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    source, output = Path(args.source), Path(args.output)
    expected = json.loads((source / 'conversion-lock.json').read_text())
    for name, digest in expected['sha256'].items():
        h = hashlib.sha256()
        with (source / name).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(chunk)
        if h.hexdigest() != digest:
            raise ValueError('official author source digest differs: ' + name)
    image = np.load(source / 'eeg-image_metadata.npy', allow_pickle=True).item()
    # Official metadata maps the 200 EEG condition indices directly to images.
    metadata = {'image_ids': [str(v) for v in image['test_img_files']],
                'concept_ids': [str(v) for v in image['test_img_concepts']],
                'subjects': ['01', '02']}
    recordings = []
    for subject in ('01', '02'):
        with zipfile.ZipFile(source / ('eeg-sub-' + subject + '.zip')) as archive:
            names = [n for n in archive.namelist() if n.endswith('/preprocessed_eeg_test.npy') or n == 'preprocessed_eeg_test.npy']
            if len(names) != 1 or archive.getinfo(names[0]).file_size > 512 * 1024 * 1024:
                raise ValueError('ambiguous or oversized author test array')
            with archive.open(names[0]) as stream:
                data = np.load(stream, allow_pickle=True).item()
        x = data['preprocessed_eeg_data']
        if x.shape[:3] != (200, 80, 17) or not np.isfinite(x).all():
            raise ValueError('unexpected author EEG test data')
        times = np.asarray(data['times'], dtype='float64')
        channels = [str(v) for v in data['ch_names']]
        if recordings and (not np.array_equal(times, previous_times) or channels != metadata['channels']):
            raise ValueError('subject time/channel axes differ')
        metadata['channels'] = channels
        previous_times = times
        recordings.append(x.astype('float64').mean(axis=1))
    np.save(output / 'eeg.npy', np.stack(recordings), allow_pickle=False)
    np.save(output / 'times.npy', times, allow_pickle=False)
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2))
    (output / 'provenance.json').write_text(json.dumps(expected, indent=2))


if __name__ == '__main__':
    main()
