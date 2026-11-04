"""Thin adapters to the pinned upstream implementation; imports remain lazy."""
from pathlib import Path

from . import BackendError
from .common import read_json

CV = {'split_coord': 'story', 'kfold': 'group', 'random_state': 1234}


def model_subject(configuration, layers=None, online=False):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from brainscore_language.artificial_subject import ArtificialSubject
    from brainscore_language.model_helpers.huggingface import HuggingfaceSubject
    model_spec = configuration['model']
    model = AutoModelForCausalLM.from_pretrained(
        model_spec['id'], revision=model_spec['revision'], local_files_only=not online,
        torch_dtype=torch.float32, use_safetensors=True, trust_remote_code=False)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(
        model_spec['id'], revision=model_spec['tokenizer_revision'], local_files_only=not online,
        truncation_side='left', trust_remote_code=False)
    layers = layers or configuration['layers']
    modules = dict(model.named_modules())
    if any(layer not in modules for layer in layers):
        raise BackendError('configured module path does not exist in this model')
    return HuggingfaceSubject(model_id=model_spec['id'], model=model, tokenizer=tokenizer,
                             region_layer_mapping={ArtificialSubject.RecordingTarget.language_system: layers})


def load_brain(root):
    from brainscore_core.supported_data_standards.brainio.assemblies import AssemblyLoader, NeuroidAssembly
    brain = AssemblyLoader(cls=NeuroidAssembly, file_path=Path(root) / 'brain.nc').load()
    brain.attrs['identifier'] = 'Pereira2018.language.384sentences'
    return brain


def cached_benchmark(root):
    from brainscore_core.metrics import Score
    from brainscore_language.benchmarks.pereira2018.benchmark import _Pereira2018Experiment
    class LocalPereira(_Pereira2018Experiment):
        def _load_data(self, experiment, atlas):
            return load_brain(root)

        def _load_ceiling(self, **kwargs):
            return Score(read_json(Path(root) / 'ceiling.json')['value'])
    return LocalPereira(experiment='384sentences', metric='ridge_pearsonr',
                        crossvalidation_kwargs=CV, ceiling_s3_kwargs={'sha1': 'local-verified-manifest'})


def feature_assembly(root, layer):
    import numpy as np
    from brainscore_core.supported_data_standards.brainio.assemblies import NeuroidAssembly
    configuration = read_json(Path(root) / 'config.json')
    index = configuration['layers'].index(layer)
    stimuli = read_json(Path(root) / 'stimuli.json')
    values = np.load(Path(root) / 'features' / ('layer-%03d.npy' % index), allow_pickle=False)
    if values.ndim != 2 or values.shape[0] != len(stimuli) or values.dtype != np.dtype('float32') or not np.isfinite(values).all():
        raise BackendError('invalid cached features')
    return NeuroidAssembly(values, dims=['presentation', 'neuroid'], coords={
        **{key: ('presentation', [row[key] for row in stimuli])
           for key in ('stimulus_id', 'stimulus', 'story', 'passage_label', 'passage_index')},
        'layer': ('neuroid', [layer] * values.shape[1]),
        # Match HuggingfaceSubject's recording coordinates. With only layer and
        # neuroid_id, selecting a layer collapses the axis name to neuroid_id.
        'region': ('neuroid', ['language_system'] * values.shape[1]),
        'recording_type': ('neuroid', ['fMRI'] * values.shape[1]),
        'neuron_number_in_layer': ('neuroid', np.arange(values.shape[1])),
        'neuroid_id': ('neuroid', ['%s--%d' % (layer, i) for i in range(values.shape[1])]),
    })


class CachedSubject:
    """Replay complete passage calls; never look up isolated sentences out of context."""
    def __init__(self, root, layer):
        import numpy as np
        self.features = feature_assembly(root, layer)
        self.calls = {}
        passages = self.features['passage_label'].values
        for passage in sorted(set(passages)):
            rows = np.flatnonzero(passages == passage)
            subset = self.features.isel(presentation=rows)
            key = tuple(str(value) for value in subset['stimulus'].values)
            if key in self.calls:
                raise BackendError('ambiguous identical passage calls require an explicit replay mapping')
            self.calls[key] = subset

    def start_neural_recording(self, recording_target, recording_type):
        if recording_target != 'language_system' or recording_type != 'fMRI':
            raise BackendError('unsupported cached recording request')

    def digest_text(self, text):
        key = (text,) if isinstance(text, str) else tuple(str(value) for value in text)
        if key not in self.calls:
            raise BackendError('cache has no exact passage/context match')
        # The official benchmark assigns stimulus_id to the returned passage.
        # Keep cached metadata as ordinary coordinates so that assignment does
        # not collide with BrainIO's presentation MultiIndex level names.
        neural = self.calls[key].reset_index('presentation').copy(deep=True)
        return {'behavior': None, 'neural': neural}


def traced_metric(metric, run):
    """Record actual upstream fit/predict/correlation outputs without replacing the solver."""
    import numpy as np
    regression, correlation = metric.regression, metric.correlation
    records, pending = [], {}
    class Regression:
        def fit(self, source, target):
            pending.clear()
            pending['train_ids'] = [str(x) for x in source['stimulus_id'].values]
            regression.fit(source, target)
            pending['alpha'] = np.asarray(regression._regression.alpha_).tolist()

        def predict(self, source):
            prediction = regression.predict(source)
            pending['prediction'] = prediction.copy(deep=True)
            return prediction

    def correlate(prediction, target):
        result = correlation(prediction, target)
        records.append({**pending, 'correlations': result.copy(deep=True)})
        return result
    metric.regression, metric.correlation = Regression(), correlate
    try:
        score = run()
    finally:
        metric.regression, metric.correlation = regression, correlation
    return score, records


def traced_score(benchmark, candidate):
    return traced_metric(benchmark.metric, lambda: benchmark(candidate))
