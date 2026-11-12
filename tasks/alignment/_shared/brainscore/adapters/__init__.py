"""Local cache contracts, not implementations of the upstream regression solvers."""
from ..registry import require


def identities(values, label):
    require(isinstance(values, list) and values and all(isinstance(v, str) and v for v in values), label + ': expected nonempty string ids')
    require(len(values) == len(set(values)), label + ': duplicate ids')
    return values


def align_rows(values, available_ids, requested_ids):
    """Align by presentation identity. Stimulus strings alone can repeat across contexts."""
    import numpy as np
    available_ids = identities(available_ids, 'available presentations')
    requested_ids = identities(requested_ids, 'requested presentations')
    require(len(values) == len(available_ids), 'candidate row count differs')
    require(set(available_ids) == set(requested_ids), 'presentation coverage differs')
    if available_ids == requested_ids:
        return np.asarray(values)
    positions = {value: i for i, value in enumerate(available_ids)}
    return np.asarray(values)[[positions[value] for value in requested_ids]]


def validate(metadata, arrays, benchmark):
    """Check aligned, prepared two-dimensional targets without changing missing values."""
    import numpy as np
    presentations, units = metadata.get('presentations'), metadata.get('units')
    require(isinstance(presentations, list) and all(isinstance(p, dict) for p in presentations), 'missing presentations')
    require(isinstance(units, list) and all(isinstance(u, dict) for u in units), 'missing measurement units')
    ids = identities([p.get('presentation_id') for p in presentations], 'presentations')
    unit_ids = identities([u.get('unit_id') for u in units], 'units')
    for row in presentations:
        require(isinstance(row.get('stimulus_id'), str) and row['stimulus_id'], 'missing original stimulus identity')
        require(isinstance(row.get('source_coordinates'), dict), 'missing original presentation coordinates')
    for row in units:
        require(row.get('kind') == benchmark['measurement_unit'], 'measurement unit semantics differ')
        require(isinstance(row.get('source_coordinates'), dict), 'missing original unit coordinates')
        require('subject_id' in row, 'subject identity or explicit null is required')
        require(row['subject_id'] is None or isinstance(row['subject_id'], str) and row['subject_id'], 'invalid subject identity')
        if benchmark['adapter'].startswith('language-'):
            require(row['subject_id'] is not None, 'language measurements require subject identity')
    responses, valid = arrays['responses'], arrays['response_valid']
    require(responses.dtype.kind == 'f' and responses.shape == (len(ids), len(unit_ids)), 'response shape/dtype differs')
    require(valid.dtype.kind == 'b' and valid.shape == responses.shape, 'response mask shape/dtype differs')
    require(not np.isinf(responses).any() and np.array_equal(np.isfinite(responses), valid),
            'response missingness must be NaN with an exact finite-value mask; exclusion is separate')
    candidate_ids = metadata.get('candidate_presentation_ids')
    candidate = align_rows(arrays['candidate'], candidate_ids, ids)
    behavior = benchmark['adapter'] == 'language-behavior'
    if behavior:
        candidate_valid = align_rows(arrays['candidate_valid'], candidate_ids, ids)
        require(candidate.shape == (len(ids),) and candidate.dtype.kind == 'f', 'behavior requires one reading-time output per word')
        require(candidate_valid.dtype.kind == 'b' and candidate_valid.shape == candidate.shape, 'invalid behavior mask')
        require(not np.isinf(candidate).any() and np.array_equal(np.isfinite(candidate), candidate_valid), 'behavior missingness differs')
    else:
        require(candidate.ndim == 2 and candidate.shape[1] > 0 and candidate.dtype.kind == 'f'
                and all(np.isfinite(candidate[start:start + 64]).all() for start in range(0, len(candidate), 64)),
                'neural features must be a finite presentation-by-feature matrix')
    protocol = metadata.get('protocol')
    require(isinstance(protocol, dict) and protocol.get('schema') == 'bpb-bs-cache-protocol/1', 'invalid cache protocol')
    for field in ('readout', 'split_group', 'normalization'):
        require(field in protocol and protocol[field] == benchmark[field], 'protocol differs: ' + field)
    included = identities(protocol.get('included_presentation_ids'), 'included presentations')
    excluded = protocol.get('excluded_presentations')
    require(isinstance(excluded, dict) and all(isinstance(reason, str) and reason for reason in excluded.values()), 'exclusions need reasons')
    require(not set(included) & set(excluded) and set(included) | set(excluded) == set(ids), 'inclusion/exclusion coverage differs')
    folds = protocol.get('folds')
    require(isinstance(folds, list), 'explicit folds required (empty for behavior)')
    if behavior:
        require(not folds, 'behavior must not invent regression folds')
        positions = [ids.index(value) for value in included]
        require(candidate_valid[positions].all(), 'included words must have valid model behavior')
    else:
        require(folds, 'neural protocol needs explicit official train/test identities')
        identities([fold.get('id') for fold in folds if isinstance(fold, dict)], 'folds')
        for fold in folds:
            require(isinstance(fold, dict), 'invalid fold')
            train = set(identities(fold.get('train_ids'), 'training fold'))
            test = set(identities(fold.get('test_ids'), 'test fold'))
            require(not train & test and train | test == set(included), 'train/test overlap or incomplete fold coverage')
            if benchmark['split_group']:
                groups = {}
                for row in presentations:
                    group = row['source_coordinates'].get(benchmark['split_group'])
                    require((isinstance(group, str) and group) or type(group) is int, 'missing split-group identity')
                    groups[row['presentation_id']] = (type(group).__name__, group)
                require(not {groups[i] for i in train} & {groups[i] for i in test}, 'train/test group leakage')
    return {'presentation_ids': ids, 'unit_ids': unit_ids, 'candidate': candidate,
            'responses': responses, 'response_valid': valid, 'protocol': protocol}
