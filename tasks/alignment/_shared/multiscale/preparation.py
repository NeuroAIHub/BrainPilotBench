"""Owner preparation. Only the search and inspect responses are released to the researcher."""
import csv
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from expansion.packet import load, verify
from expansion.selection import load_hidden, response_pool, stimulus_id
from real_brainscore.common import outside_repository, read_json, seal, sha256, write_json
from . import CSV_SHA256, PROTOCOL, fingerprint
from .model import LanguageModel, encode, variants


def prepare(csv_file, model_dir, output, f_inputs=None, f_hidden=None):
    dest = outside_repository(output)
    if dest.exists():
        raise ValueError('output exists; select an existing experiment or a fresh root')
    if sha256(csv_file) != CSV_SHA256:
        raise ValueError('CSV differs from the locked Tuckute experiment')
    pool = response_pool(csv_file)
    meta = pool.metadata
    if bool(f_inputs) != bool(f_hidden):
        raise ValueError('supply both existing F packets together')
    f_identity = None
    if f_inputs:
        old = load(f_inputs)
        private = load_hidden(f_hidden, old)
        if (old['task'] != 'F' or old['manifest']['synthetic_only'] or old['metadata'] != meta
                or private['subjects'] != list(map(str, pool.held_subjects))
                or not np.array_equal(old['arrays']['train_responses'], pool.train)
                or not np.array_equal(private['responses'], pool.hidden)):
            raise ValueError('F packets and raw sentence/subject/response tables differ')
        f_identity = old['manifest_sha256']
    ids = meta['train_ids'] + meta['candidate_ids']
    texts = meta['train_sentences'] + meta['candidate_sentences']
    if (pool.train.shape != (988, 5) or pool.hidden.shape != (500, 3)
            or pool.conditions.count('D') != 250 or pool.conditions.count('S') != 250
            or len(set(ids)) != len(ids) or len(set(texts)) != len(texts)):
        raise ValueError('unexpected real F population or duplicate sentence identity')
    lm = LanguageModel(model_dir)
    originals = [encode(lm.tokenizer, text) for text in texts]
    order = sorted(range(len(pool.train)), key=lambda i: fingerprint([PROTOCOL, ids[i]]))
    split = {'search': order[:720], 'dev': order[720:864], 'confirm': order[864:],
             'brain_test': list(range(len(pool.train), len(ids)))}
    pairs = {}
    sentence_family = {text: row for row, text in enumerate(texts)}
    for name, count in [('search', 96), ('dev', 32), ('confirm', 32)]:
        selected = []
        for row in split[name]:
            changed = variants(lm.tokenizer, originals[row])
            if not changed or any(sentence_family.get(v['text'], row) != row for v in changed.values()):
                continue
            selected.append({'row': row, **changed})
            sentence_family.update({v['text']: row for v in changed.values()})
            if len(selected) == count:
                break
        if len(selected) != count:
            raise ValueError('too few aligned single-token targets in ' + name)
        pairs[name] = selected
    trials = {}
    with Path(csv_file).open() as stream:
        for record in csv.DictReader(stream):
            if record['roi'] == 'lang_LH_netw' and record['target_UID'] == meta['train_subjects'][0]:
                trials[stimulus_id(record['item_id'])] = {k: record[k] for k in
                                                         ('target_UID', 'session_id', 'run_id', 'trial_num')}
    dest.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=dest.parent) as tmp:
        root = Path(tmp) / 'experiment'
        packet, hidden = root / 'packet', root / 'hidden'
        packet.mkdir(parents=True)
        hidden.mkdir()
        common = {'protocol': PROTOCOL, 'source_csv_sha256': CSV_SHA256, 'legacy_f_manifest': f_identity,
                  'model_revision': lm.revision, 'runtime': lm.runtime, 'train_subjects': meta['train_subjects'],
                  'ids': ids, 'originals': originals, 'split': split, 'pairs': pairs, 'trials': trials}
        write_json(packet / 'items.json', common)
        units, controls, whole = lm.features(originals)
        for name, values in [('units', units), ('controls', controls), ('whole', whole), ('train_y', pool.train)]:
            np.save(packet / (name + '.npy'), values, allow_pickle=False)
        for name in ('search', 'dev'):
            changed = [p['reverse'] for p in pairs[name]]
            perturbed, _, _ = lm.features(changed)
            np.save(packet / (name + '_reverse.npy'), perturbed, allow_pickle=False)
        seal(packet, {'schema': PROTOCOL + '/packet'})
        identity = sha256(packet / 'manifest.json')
        np.save(hidden / 'responses.npy', pool.hidden, allow_pickle=False)
        write_json(hidden / 'identities.json', {'ids': meta['candidate_ids'], 'subjects': list(map(str, pool.held_subjects)),
                                                'conditions': pool.conditions})
        seal(hidden, {'schema': PROTOCOL + '/hidden', 'packet_sha256': identity})
        root.rename(dest)
    return {'packet_sha256': identity, 'root': str(dest), 'splits': {k: len(v) for k, v in split.items()},
            'pairs': {k: len(v) for k, v in pairs.items()}}


class Packet:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        packet, _ = verify(self.root / 'packet', PROTOCOL + '/packet')
        self.digest = sha256(packet / 'manifest.json')
        meta = read_json(packet / 'items.json')
        self.meta = meta
        self.split = meta['split']
        self.pairs = meta['pairs']
        self.arrays = {p.stem: np.load(p, mmap_mode='r', allow_pickle=False) for p in packet.glob('*.npy')}

    def outcome(self):
        hidden, manifest = verify(self.root / 'hidden', PROTOCOL + '/hidden')
        identities = read_json(hidden / 'identities.json')
        ids = [self.meta['ids'][i] for i in self.split['brain_test']]
        if manifest['packet_sha256'] != self.digest or identities['ids'] != ids:
            raise ValueError('hidden labels and frozen packet identities differ')
        return identities, np.load(hidden / 'responses.npy', allow_pickle=False)
