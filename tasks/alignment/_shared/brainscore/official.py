"""Official metric execution with trace capture; no local replacement solvers."""
from .protocols import specification
from .registry import require


def metric(protocol):
    if protocol['ecosystem'] == 'vision':
        from brainscore_vision.metrics.regression_correlation.metric import CrossRegressedCorrelation, pls_regression, pearsonr_correlation
        return CrossRegressedCorrelation(pls_regression(), pearsonr_correlation(), crossvalidation_kwargs=protocol['crossvalidation_kwargs'])
    if protocol['readout'] == 'none':
        from brainscore_language.metrics.pearson_correlation.metric import PearsonCorrelation
        return PearsonCorrelation()
    from brainscore_language.metrics.linear_predictivity.metric import CrossRegressedCorrelation, ridge_regression, pearsonr_correlation
    return CrossRegressedCorrelation(ridge_regression(), pearsonr_correlation(), crossvalidation_kwargs=protocol['crossvalidation_kwargs'])


def arrays_to_assemblies(packet):
    import numpy as np
    from brainscore_core.supported_data_standards.brainio.assemblies import NeuroidAssembly, BehavioralAssembly
    meta, aligned = packet['metadata'], packet['aligned']
    protocol = specification(packet['manifest']['benchmark_id'])
    rows, units = meta['presentations'], meta['units']
    # Upstream uses stimulus_id as its alignment key. This cache preserves a unique
    # presentation key separately and refuses ambiguity at this official seam.
    ids = [row['source_coordinates'].get('_upstream_stimulus_id', row['stimulus_id']) for row in rows]
    require(len(set(ids)) == len(ids), 'official metric requires unique stimulus_id after source preprocessing')
    coords = {'stimulus_id': ('presentation', ids), 'presentation_id': ('presentation', aligned['presentation_ids'])}
    keys = set.intersection(*(set(row['source_coordinates']) for row in rows))
    for name in keys - set(coords) - {'presentation', 'neuroid', 'subject'}:
        values = [row['source_coordinates'][name] for row in rows]
        if all(isinstance(value, (str, int, float, bool)) for value in values):
            coords[name] = 'presentation', values
    if protocol['readout'] == 'none':
        target = BehavioralAssembly(aligned['responses'], dims=['presentation', 'subject'],
                                    coords={**coords, 'subject_id': ('subject', [u['subject_id'] for u in units]),
                                            'measurement_id': ('subject', aligned['unit_ids'])})
        source = BehavioralAssembly(aligned['candidate'], dims=['presentation'], coords=coords)
    else:
        unit_coords = {'neuroid_id': ('neuroid', aligned['unit_ids']),
                       'subject': ('neuroid', [u['subject_id'] or 'not-recorded' for u in units]),
                       'region': ('neuroid', [u['source_coordinates'].get('region', protocol['region']) for u in units])}
        target = NeuroidAssembly(aligned['responses'], dims=['presentation', 'neuroid'], coords={**coords, **unit_coords})
        n = aligned['candidate'].shape[1]
        source = NeuroidAssembly(aligned['candidate'], dims=['presentation', 'neuroid'],
                                coords={**coords, 'neuroid_id': ('neuroid', ['feature-%d' % i for i in range(n)]),
                                        'layer': ('neuroid', [meta['candidate_configuration']['layer']] * n)})
    return source, target


def traced_metric(function, source, target):
    """Record actual upstream train/test calls without changing fitting or aggregation."""
    import numpy as np
    records = []
    original_apply = function.apply
    original_predict = function.regression.predict
    pending = {}
    # BrainIO stores coordinates as MultiIndex levels: membership in .coords
    # can be false even when assembly[name] is available.
    try:
        presentations = source['presentation_id'].values
    except KeyError:
        presentations = source['stimulus_id'].values
    identities = dict(zip(map(str, source['stimulus_id'].values), map(str, presentations)))
    def ids(assembly):
        return [identities[str(value)] for value in assembly['stimulus_id'].values]

    def predict(values):
        prediction = original_predict(values)
        pending['prediction'] = prediction.copy(deep=True)
        return prediction

    def apply(source_train, target_train, source_test, target_test):
        pending.clear()
        result = original_apply(source_train, target_train, source_test, target_test)
        prediction = pending['prediction'].sortby('neuroid_id')
        scores = result.sortby('neuroid_id')
        require(list(prediction['neuroid_id'].values) == list(scores['neuroid_id'].values), 'trace unit alignment differs')
        record = {'id': 'fold-%d' % len(records),
                  'train_ids': ids(source_train),
                  'test_ids': ids(prediction),
                  'unit_ids': [str(x) for x in prediction['neuroid_id'].values],
                  'prediction': np.asarray(prediction.values, dtype=np.float64),
                  'unit_scores': np.asarray(scores.values, dtype=np.float64),
                  'alpha': None}
        alpha = getattr(function.regression._regression, 'alpha_', None)
        if alpha is not None:
            record['alpha'] = np.asarray(alpha).tolist()
        records.append(record)
        return result
    function.apply, function.regression.predict = apply, predict
    try:
        score = function(source, target)
    finally:
        function.apply, function.regression.predict = original_apply, original_predict
    return score, records


def split_manifest(packet):
    """Ask the official splitter for identities without fitting a readout."""
    import numpy as np
    from brainscore_core.metrics import Score
    protocol = specification(packet['manifest']['benchmark_id'])
    if protocol['readout'] == 'none':
        return []
    source, target = arrays_to_assemblies(packet)
    function, records = metric(protocol), []
    def capture(source_train, target_train, source_test, target_test):
        records.append({'id': 'fold-%d' % len(records),
                        'train_ids': [str(x) for x in source_train['presentation_id'].values],
                        'test_ids': [str(x) for x in source_test['presentation_id'].values]})
        return Score(np.zeros(target_test.sizes['neuroid']), dims=['neuroid'],
                     coords={'neuroid_id': ('neuroid', target_test['neuroid_id'].values)})
    function.cross_validation(source, target, apply=capture, aggregate=function.aggregate)
    return records


def compute(packet):
    import numpy as np
    from brainscore_core.metrics import Score
    protocol = specification(packet['manifest']['benchmark_id'])
    frozen = packet['metadata']['protocol']
    require(frozen.get('official_specification') == protocol, 'official protocol differs from audited specification')
    ceiling = frozen.get('ceiling')
    require(type(ceiling) in (float, int) and np.isfinite(ceiling) and ceiling > 0, 'positive verified ceiling required')
    source, target = arrays_to_assemblies(packet)
    function = metric(protocol)
    if protocol['readout'] == 'none':
        keep = np.asarray(target['word_within_sentence_id'].values) != 1
        raw = function(source[keep], target[keep].mean('subject'))
        records = []
        extra = {'signed_r': float(raw.attrs['rvalue']), 'pvalue': float(raw.attrs['pvalue']),
                 'included_ids': np.asarray(target['presentation_id'].values)[keep].astype(str).tolist()}
    else:
        require(np.isfinite(target.values).all(), 'source preprocessing must resolve neural missingness exactly as upstream; no implicit imputation')
        raw, records = traced_metric(function, source, target)
        extra = {}
        actual = [{'id': r['id'], 'train_ids': r['train_ids'], 'test_ids': r['test_ids']} for r in records]
        require(actual == frozen['folds'], 'recorded folds differ from the frozen official split manifest')
    if protocol['ecosystem'] == 'vision':
        from brainscore_vision.benchmark_helpers.neural_common import explained_variance
        normalized = explained_variance(raw, Score(ceiling))
    else:
        from brainscore_language.utils.ceiling import ceiling_normalize
        normalized = ceiling_normalize(raw, Score(ceiling))
    require(np.isfinite(float(raw)) and np.isfinite(float(normalized)), 'official metric produced a nonfinite score')
    values = {'raw': float(raw), 'ceiling': ceiling, 'normalized': float(normalized),
              'unclipped': float(raw) ** (2 if protocol['ecosystem'] == 'vision' else 1) / ceiling,
              'normalization': protocol['normalization'], 'aggregation': protocol['aggregation'], **extra}
    return values, records
