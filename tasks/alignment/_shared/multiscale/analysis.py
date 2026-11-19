"""Shared computations for the fixed top-k policy, researcher tools and owner scorer."""
import numpy as np

from . import ALPHA, K, POSITIONS, RANDOM_GROUPS, fingerprint


def pearson(x, y):
    a, b = np.asarray(x, dtype='float64'), np.asarray(y, dtype='float64')
    a, b = a - a.mean(), b - b.mean()
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / norm) if norm > 0 else None


def difference(value, base):
    return None if value is None or base is None else value - base


def readout(x, y, train, test):
    """Persist the actual ridge map in the input feature units, including the intercept."""
    xfit = x[train].astype('float64')
    mean, scale = xfit.mean(axis=0), xfit.std(axis=0)
    scale[scale == 0] = 1.
    z = (xfit - mean) / scale
    yfit = y[train]
    gram = z.T @ z
    gram.flat[::len(mean) + 1] += ALPHA
    weights = np.linalg.solve(gram, z.T @ (yfit - yfit.mean())) / scale
    intercept = float(yfit.mean() - mean @ weights)
    pred = x[test].astype('float64') @ weights + intercept
    if not np.isfinite(pred).all():
        raise ValueError('nonfinite ridge prediction')
    return {'weights': weights.tolist(), 'intercept': intercept, 'predictions': pred.tolist()}


def site(packet, group):
    return packet.arrays['units'][:, group['layer'], POSITIONS.index(group['position']), :]


def check_group(packet, data):
    layer, position, units = data['layer'], data['position'], data['units']
    _, layers, _, width = packet.arrays['units'].shape
    if type(layer) is not int or not 0 <= layer < layers or position not in POSITIONS:
        raise ValueError('invalid layer or read position')
    if (not isinstance(units, list) or len(units) != K
            or any(type(u) is not int or not 0 <= u < width for u in units) or len(set(units)) != K):
        raise ValueError(f'exactly {K} distinct unit IDs from one layer are required')
    return {'layer': layer, 'position': position, 'units': sorted(units)}


def scale_on_search(x, rows):
    scale = x[rows].std(axis=0, dtype='float64')
    return np.where(scale > 0, scale, 1.)


def pair_effect(packet, name, group, scale):
    position = POSITIONS.index(group['position'])
    selected = group['units']
    rows = [p['row'] for p in packet.pairs[name]]
    original = site(packet, group)[rows][:, selected]
    changed = packet.arrays[name + '_reverse'][:, group['layer'], position, :][:, selected]
    return ((original - changed) / scale).mean(axis=1)


def search(packet):
    train = packet.split['search']
    y = packet.arrays['train_y'][train].mean(axis=1)
    y -= y.mean()
    pairs = [p['row'] for p in packet.pairs['search']]
    groups = []
    for layer in range(packet.arrays['units'].shape[1]):
        for p, position in enumerate(POSITIONS):
            x = packet.arrays['units'][:, layer, p, :]
            std = scale_on_search(x, train)
            order = (x[pairs] - packet.arrays['search_reverse'][:, layer, p]).mean(axis=0) / std
            association = (y @ x[train]) / (len(y) * y.std() * std)
            top = np.argsort(-order, kind='stable')[:K]
            brain = np.argsort(-np.abs(association), kind='stable')[:K]
            groups.append({'layer': layer, 'position': position, 'order_units': top.tolist(),
                           'order_mean': float(order[top].mean()), 'brain_units': brain.tolist(),
                           'brain_mean_abs_r': float(np.abs(association[brain]).mean())})
    return sorted(groups, key=lambda g: -g['order_mean'])


def inspection(packet, group):
    x = site(packet, group)[:, group['units']]
    train, dev = packet.split['search'], packet.split['dev']
    mean, scale = x[train].mean(axis=0), scale_on_search(x, train)
    strength = ((x[train] - mean) / scale).mean(axis=1)
    examples = []
    for i in (int(np.argmax(strength)), int(np.argmin(strength))):
        row = train[i]
        examples.append({'id': packet.meta['ids'][row], 'text': packet.meta['originals'][row]['text'],
                         'mean_z': float(strength[i])})
    control = packet.arrays['controls']
    joint = np.column_stack((control, x))
    y = packet.arrays['train_y'].mean(axis=1)
    base = pearson(readout(control, y, train, dev)['predictions'], y[dev])
    enhanced = pearson(readout(joint, y, train, dev)['predictions'], y[dev])
    return {'group': group, 'search_order_z': float(pair_effect(packet, 'search', group, scale).mean()),
            'dev_order_z': float(pair_effect(packet, 'dev', group, scale).mean()),
            'dev_control_r': base, 'dev_joint_r': enhanced, 'dev_delta_r': difference(enhanced, base),
            'examples': examples}


def matched_groups(packet, group):
    x = site(packet, group)[packet.split['search']].astype('float64')
    rms = np.sqrt(np.square(x).mean(axis=0))
    chosen = group['units']
    rng = np.random.default_rng(73)
    groups = []
    for _ in range(RANDOM_GROUPS):
        picks = []
        for u in chosen:
            distance = np.abs(rms - rms[u])
            distance[chosen + picks] = np.inf
            neighbors = np.argsort(distance, kind='stable')[:32]
            picks.append(int(rng.choice(neighbors)))
        groups.append(picks)
    return groups


def fit_brain(packet, group):
    train = packet.split['search'] + packet.split['dev']
    test = packet.split['brain_test']
    ids = packet.meta['ids']
    control = packet.arrays['controls']
    y = packet.arrays['train_y'].mean(axis=1)
    x = site(packet, group)
    random = matched_groups(packet, group)
    maps = {'control': readout(control, y, train, test),
            'whole': readout(np.column_stack((control, packet.arrays['whole'])), y, train, test)}
    for name, units in [('selected', group['units']), *[(f'random{i}', g) for i, g in enumerate(random)]]:
        maps[name] = readout(np.column_stack((control, x[:, units])), y, train, test)
    return {'candidate_ids': [ids[i] for i in test], 'fit_ids_sha256': fingerprint([ids[i] for i in train]),
            'group': group, 'alpha': ALPHA, 'random_groups': random, 'maps': maps}


def brain_scores(frozen, identities, y):
    if frozen['candidate_ids'] != identities['ids'] or y.shape != (len(identities['ids']), len(identities['subjects'])):
        raise ValueError('predictions and outcomes must have identical sentence and participant axes')
    labels = np.asarray(identities['conditions'])
    maps = frozen['maps']
    scores = {}
    for population, mask in [('all', np.ones(len(labels), dtype=bool)), ('D', labels == 'D'), ('S', labels == 'S')]:
        if mask.sum() < 2:
            raise ValueError('empty or undersized condition')
        subjects = {}
        for j, subject in enumerate(identities['subjects']):
            rs = {key: pearson(np.asarray(v['predictions'])[mask], y[mask, j]) for key, v in maps.items()}
            base = rs['control']
            random = [difference(rs[f'random{i}'], base) for i in range(len(frozen['random_groups']))]
            subjects[subject] = {'control_r': base, 'selected_r': rs['selected'],
                                 'delta_r': difference(rs['selected'], base), 'whole_delta_r': difference(rs['whole'], base),
                                 'random_delta_r': random,
                                 'random_mean': None if None in random else float(np.mean(random))}
        scores[population] = {'n': int(mask.sum()), 'subjects': subjects}
    return scores
