"""Server integration regressions; run with the pinned Python 3.11 environment."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from real_brainscore.upstream import CachedSubject
from real_brainscore import evaluation


class CachedSubjectTests(unittest.TestCase):
    def test_official_benchmark_can_assign_stimulus_coordinates(self):
        # The official Pereira entry assigns these coordinates to each passage
        # returned by digest_text. BrainIO stores cached metadata in a MultiIndex.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'features').mkdir()
            (root / 'config.json').write_text(json.dumps({'layers': ['block.0']}))
            rows = [dict(stimulus_id=str(i), stimulus='Sentence %d.' % i,
                         story='story', passage_label='passage', passage_index=i)
                    for i in range(2)]
            (root / 'stimuli.json').write_text(json.dumps(rows))
            values = np.arange(6, dtype=np.float32).reshape(2, 3)
            np.save(root / 'features/layer-000.npy', values)
            subject = CachedSubject(root, 'block.0')
            subject.start_neural_recording('language_system', 'fMRI')
            sentences = [row['stimulus'] for row in rows]
            neural = subject.digest_text(sentences)['neural']
            neural['stimulus_id'] = 'presentation', [row['stimulus_id'] for row in rows]
            np.testing.assert_array_equal(neural.values, values)
            self.assertEqual(list(neural['stimulus_id'].values), ['0', '1'])
            # The next official operation selects a layer; its metric requires
            # the neuroid axis to survive that MultiIndex selection.
            selected = neural.sel(layer='block.0')
            self.assertEqual(selected.dims, ('presentation', 'neuroid'))
            np.testing.assert_array_equal(selected.values, values)
            # A benchmark's coordinate/value mutations must not corrupt replay.
            neural.values[:] = -1
            np.testing.assert_array_equal(subject.digest_text(sentences)['neural'].values, values)


class WorkerFailureTests(unittest.TestCase):
    def evaluate_failure(self, started):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, source, output = (root / name for name in ('cache', 'source', 'output'))
            cache.mkdir()
            source.mkdir()
            (source / 'analyze.py').write_text('raise SystemExit(125)\n')
            provenance = {'packages': {}, 'adapter_sources': {}}

            def reference(inputs, destination, device):
                destination.mkdir()
                (destination / 'runtime.json').write_text(json.dumps(provenance))

            def docker(command, **kwargs):
                if command[1:3] == ['image', 'inspect']:
                    return SimpleNamespace(returncode=0, stdout='sha256:local-test-image')
                if command[1] == 'inspect':
                    return SimpleNamespace(returncode=0 if started else 1,
                                           stdout=json.dumps({'Error': '', 'ExitCode': 125}))
                if '-c' in command:
                    return SimpleNamespace(returncode=0, stdout=json.dumps(provenance))
                return SimpleNamespace(returncode=125 if command[1] == 'run' else 0)

            with patch.object(evaluation, 'load_cache', return_value=(cache, {}, {})), \
                 patch.object(evaluation, 'score_fixed', side_effect=reference), \
                 patch.object(evaluation.os, 'getuid', return_value=1000), \
                 patch.object(evaluation.subprocess, 'run', side_effect=docker):
                return evaluation.evaluate(cache, source, output, 'local-test-image')

    def test_container_creation_failure_is_infrastructure_failure(self):
        report = self.evaluate_failure(started=False)
        self.assertEqual(report['state'], 'scoring_failed')
        self.assertIsNone(report['analysis_success'])

    def test_program_exit_125_is_still_a_submission_failure(self):
        report = self.evaluate_failure(started=True)
        self.assertEqual(report['state'], 'scored')
        self.assertEqual(report['analysis_success'], 0)


if __name__ == '__main__':
    unittest.main()
