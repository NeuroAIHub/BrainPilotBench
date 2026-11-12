"""Offline source-constructor/export and model-wrapper tests on generated inputs."""
import argparse
from contextlib import ExitStack
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from brainscore.local_sources import benchmark
from brainscore.models import configuration, subject
from brainscore.official import arrays_to_assemblies, compute
from brainscore.packet import save_fixture
from brainscore.preparation import CapturedMetric, CapturedSubject, equivalent_records, export_values
from brainscore.registry import load
from brainscore.runtime import offline
from brainscore.scientific_fixtures import packet


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bpb-bs-binding-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = load()
        self.stack = ExitStack()
        self.stack.enter_context(offline())
        self.addCleanup(self.stack.close)

    def test_language_official_constructors_context_and_export(self):
        if OPTIONS.ecosystem != 'language':
            self.skipTest('language constructors only')
        from brainscore_core.metrics import Score
        from brainscore_core.supported_data_standards.brainio.assemblies import NeuroidAssembly, BehavioralAssembly
        from brainscore_language.benchmarks.blank2014.ceiling import ExtrapolationCeiling
        for index, bid in enumerate(('Fedorenko2016-ridge', 'Blank2014-ridge', 'Futrell2018-pearsonr')):
            p = packet(self.root / ('packet%d' % index), self.registry, bid, 'distilgpt2')
            source, target = arrays_to_assemblies(p)
            target.attrs['bibtex'] = 'synthetic integration test, not a dataset citation'
            features = p['aligned']['candidate'].astype(np.float32)
            is_behavior = features.ndim == 1
            class Candidate:
                def start_neural_recording(self, **kwargs):
                    self.recording = kwargs
                def start_behavioral_task(self, task):
                    self.task = task
                def digest_text(self, text):
                    rows = [int(str(value).split()[-1]) if ' ' in str(value) else int(str(value)[4:]) for value in text]
                    if is_behavior:
                        value = BehavioralAssembly(features[rows], dims=['presentation'], coords={'word': ('presentation', list(text))})
                    else:
                        value = NeuroidAssembly(features[rows], dims=['presentation', 'neuroid'],
                                coords={'stimulus': ('presentation', list(text)),
                                        'neuroid_id': ('neuroid', list(range(features.shape[1]))),
                                        'recording_type': ('neuroid', ['synthetic'] * features.shape[1]),
                                        'layer': ('neuroid', ['transformer.h.5'] * features.shape[1])})
                    return {'behavior' if is_behavior else 'neural': value}
            with patch('brainscore.local_sources.assembly', return_value=(target, {'files': {}})), \
                 patch.object(ExtrapolationCeiling, '__call__', return_value=Score(.8)), \
                 benchmark('unused', self.root, self.registry, bid) as (official, audit):
                capture = CapturedMetric(official.metric, not is_behavior)
                official.metric = capture
                candidate = CapturedSubject(Candidate())
                live = official(candidate)
                self.assertEqual(len(capture.calls), 1)
                source, goal, raw, records = capture.calls[0]
                if is_behavior:
                    goal = official.data
                    self.assertEqual(len(candidate.calls), 1)
                else:
                    self.assertEqual(len(candidate.calls), 24 if 'Fedorenko' in bid else 12)
                metadata, arrays = export_values(self.registry, bid, 'distilgpt2', source, goal,
                    configuration(self.registry, bid, 'distilgpt2'), official.ceiling, candidate.calls)
                cached = save_fixture(self.root / ('export%d' % index), self.registry, bid, 'distilgpt2', metadata, arrays)
                score, replay = compute(cached)
                self.assertAlmostEqual(float(live), score['normalized'], places=6)
                self.assertTrue(equivalent_records(records, replay))
                self.assertIn('stimulus_id', metadata['presentations'][0]['source_coordinates'])

    def test_tiny_huggingface_wrapper_context_reset_and_surprisal_units(self):
        if OPTIONS.ecosystem != 'language':
            self.skipTest('language wrapper only')
        import torch
        from tokenizers import Tokenizer, models, pre_tokenizers
        from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast
        from brainscore_language.model_helpers.huggingface import HuggingfaceSubject
        from brainscore_language.artificial_subject import ArtificialSubject
        tokenizer = Tokenizer(models.WordLevel({'[UNK]': 0, 'one': 1, 'two': 2, 'three': 3}, unk_token='[UNK]'))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        tokenizer = PreTrainedTokenizerFast(tokenizer_object=tokenizer, unk_token='[UNK]', model_max_length=32)
        torch.manual_seed(11)
        model = GPT2LMHeadModel(GPT2Config(n_layer=1, n_head=2, n_embd=8, n_positions=32, vocab_size=4)).eval()
        neural = HuggingfaceSubject('generated-toy', {'language_system': ['transformer.h.0']}, model=model, tokenizer=tokenizer)
        neural.start_neural_recording(ArtificialSubject.RecordingTarget.language_system, ArtificialSubject.RecordingType.fMRI)
        first = neural.digest_text(['one two', 'three'])['neural'].values
        repeated = neural.digest_text(['one two', 'three'])['neural'].values
        np.testing.assert_array_equal(first, repeated)
        self.assertEqual(first.shape, (2, 8))
        behavior = HuggingfaceSubject('generated-toy', {}, model=model, tokenizer=tokenizer)
        behavior.start_behavioral_task(ArtificialSubject.Task.reading_times)
        values = behavior.digest_text(['one', 'two', 'three'])['behavior'].values
        self.assertTrue(np.isnan(values[0]))
        with torch.no_grad():
            logits = model(**tokenizer('one two three', return_tensors='pt')).logits[0]
            expected = -torch.log_softmax(logits[:-1], -1)[range(2), [2, 3]] / np.log(2)
        np.testing.assert_allclose(values[1:], expected.numpy(), atol=1e-6)

    def test_vision_preprocessing_and_fixed_mapping(self):
        if OPTIONS.ecosystem != 'vision':
            self.skipTest('vision wrapper only')
        from PIL import Image
        from brainscore_vision.model_helpers.activations.pytorch import load_preprocess_images
        from brainscore_core.supported_data_standards.brainio.stimuli import StimulusSet
        path = self.root / 'generated.png'
        Image.fromarray(np.full((13, 29, 3), 128, dtype=np.uint8)).save(path)
        value = load_preprocess_images([str(path)], image_size=224)
        self.assertEqual(tuple(value.shape), (1, 3, 224, 224))
        expected = (128 / 255 - np.asarray([.485, .456, .406])) / [.229, .224, .225]
        np.testing.assert_allclose(np.asarray(value)[0, :, 0, 0], expected, atol=1e-6)
        stimuli = StimulusSet({'stimulus_id': ['generated']})
        stimuli.identifier = 'generated-wrapper-test'
        stimuli.stimulus_paths = {'generated': path}
        for region, layer in [('V1', 'features.2'), ('V2', 'features.7'), ('V4', 'features.7'), ('IT', 'features.12')]:
            bid = ('FreemanZiemba2013public.' if region in ('V1', 'V2') else 'MajajHong2015public.') + region + '-pls'
            self.assertEqual(configuration(self.registry, bid, 'alexnet')['layer'], layer)
            model, config, manifest = subject(self.registry, bid, 'pixels')
            model.start_recording(region, time_bins=[(50, 200)])
            values = model.look_at(stimuli)
            self.assertEqual(values.sizes['neuroid'], 256 * 256 * 3)
            self.assertTrue((values.values == 128).all())
            self.assertIsNone(manifest)

    def test_vision_official_region_time_and_repetition_preprocessing(self):
        if OPTIONS.ecosystem != 'vision':
            self.skipTest('vision constructors only')
        from brainscore_core.supported_data_standards.brainio.assemblies import NeuronRecordingAssembly
        from brainscore_core.supported_data_standards.brainio.stimuli import StimulusSet
        for index, (family, region) in enumerate([('MajajHong2015', 'IT'), ('MajajHong2015', 'V4'),
                                                 ('FreemanZiemba2013', 'V1'), ('FreemanZiemba2013', 'V2')]):
            bid = family + 'public.' + region + '-pls'
            p = packet(self.root / ('vision%d' % index), self.registry, bid, 'pixels')
            goal = p['arrays']['responses']
            freeman = family == 'FreemanZiemba2013'
            times = np.arange(50, 200) if freeman else np.array([70])
            expected = goal + 1 + (np.arange(150).mean() / 1000 if freeman else 0)
            values = np.repeat(goal, 2, axis=0)[:, :, None] + np.tile([0, 2], 120)[:, None, None]
            values = values + (np.arange(len(times)) / 1000)[None, None, :]
            ids = [row['stimulus_id'] for row in p['metadata']['presentations']]
            coords = {'stimulus_id': ('presentation', np.repeat(ids, 2)),
                      'repetition': ('presentation', np.tile([0, 1], 120)),
                      'object_name': ('presentation', np.repeat(['obj%d' % (i % 3) for i in range(120)], 2)),
                      'texture_type': ('presentation', np.repeat(['noise' if i % 2 else 'texture' for i in range(120)], 2)),
                      'neuroid_id': ('neuroid', list(range(6))), 'region': ('neuroid', [region] * 6),
                      'time_bin_start': ('time_bin', times),
                      'time_bin_end': ('time_bin', times + (1 if freeman else 100))}
            if not freeman:
                coords['animal'] = 'neuroid', ['synthetic-monkey'] * 6
            raw = NeuronRecordingAssembly(values, dims=['presentation', 'neuroid', 'time_bin'], coords=coords)
            stimuli = StimulusSet({'stimulus_id': ids})
            stimuli.identifier = 'synthetic-constructor-%d' % index
            raw.attrs.update(stimulus_set=stimuli, identifier=stimuli.identifier)
            with patch('brainscore.local_sources.assembly', return_value=(raw, {'files': {}})), \
                 benchmark('unused', self.root, self.registry, bid) as (official, audit):
                self.assertEqual(official.region, region)
                self.assertEqual([np.asarray(value).tolist() for value in official.timebins],
                                 [(50, 200)] if freeman else [(70, 170)])
                self.assertEqual(official._number_of_trials, 20 if freeman else 50)
                processed = official._assembly.sortby('stimulus_id')
                np.testing.assert_allclose(processed.values, expected, atol=1e-12)

    def test_vision_local_csv_zip_merge_preserves_source_coordinates(self):
        if OPTIONS.ecosystem != 'vision':
            self.skipTest('vision source objects only')
        import pandas as pd
        import xarray as xr
        from PIL import Image
        from brainscore.local_sources import assembly, source_definition
        bid = 'MajajHong2015public.IT-pls'
        definition = source_definition(self.registry, bid)
        data, csv, images = self.root / 'data.nc', self.root / 'stimuli.csv', self.root / 'images.zip'
        xr.DataArray(np.ones((2, 2)), dims=['presentation', 'neuroid'],
                     coords={'stimulus_id': ('presentation', ['a', 'b']),
                             'repetition': ('presentation', [0, 0]),
                             'neuroid_id': ('neuroid', ['u1', 'u2']), 'region': ('neuroid', ['IT', 'IT'])}).to_netcdf(data)
        pd.DataFrame({'image_id': ['b', 'a'], 'filename': ['b.png', 'a.png'],
                      'object_name': ['second', 'first']}).to_csv(csv, index=False)
        with zipfile.ZipFile(images, 'w') as archive:
            for name in ('a', 'b'):
                path = self.root / (name + '.png')
                Image.new('RGB', (2, 2)).save(path)
                archive.write(path, arcname=path.name)
        paths = {'data_only_assembly': data, 'stimulus_metadata': csv, 'stimulus_images_zip': images}
        report = {'local_objects_complete': True, 'missing': [],
                  'files': {row['asset_id']: {'path': str(paths[row['kind']])} for row in definition['assets']}}
        with patch('brainscore.local_sources.audit', return_value=report):
            value, _ = assembly('unused', self.root / 'decoded', self.registry, bid)
        self.assertEqual(list(value['object_name'].values), ['first', 'second'])
        self.assertIn('image_id', value.stimulus_set.columns)
        self.assertTrue(value.stimulus_set.get_stimulus('a').is_file())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ecosystem', choices=['vision', 'language'], required=True)
    OPTIONS, rest = parser.parse_known_args()
    unittest.main(argv=[__file__, *rest], verbosity=2)
