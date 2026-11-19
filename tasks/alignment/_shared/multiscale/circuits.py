"""L3. Restore only one attention head's direct residual input to a downstream MLP group."""
from contextlib import ExitStack

import numpy as np

from .analysis import search
from .model import LanguageModel
from .preparation import Packet


def head_paths(lm, entries, altered, units, sender=1, receiver=2, batch_size=8):
    """Clean → corrupted direct edge, followed by a receiver-only patch into the corrupted run."""
    import torch
    send, recv = lm.model.transformer.h[sender], lm.model.transformer.h[receiver]
    heads = lm.model.config.n_head
    restored, clean_gaps = [], []
    with torch.inference_mode():
        for first in range(0, len(entries), batch_size):
            normal, corrupt = entries[first:first + batch_size], altered[first:first + batch_size]
            rows = torch.arange(len(normal))
            targets = torch.tensor([v['ids'][v['start']] for v in normal])
            last = torch.tensor([v['start'] - 1 for v in normal])
            if any(a['start'] != b['start'] or a['ids'][a['start']] != b['ids'][b['start']] for a, b in zip(normal, corrupt)):
                raise ValueError('path probes require identical target position and token')

            def forward(items, injection=None):
                ids, mask = lm.batch([v['ids'][:v['start']] for v in items])
                cache = {}
                def save(name):
                    def hook(module, args):
                        cache[name] = args[0][rows, last].clone()
                    return hook
                def add_delta(module, args, output):
                    output = output.clone()
                    output[rows, last] += injection
                    return output
                with ExitStack() as stack:
                    if injection is None:
                        for module, name in [(send.attn.c_proj, 'heads'), (recv.ln_2, 'residual'), (recv.mlp.c_proj, 'mlp')]:
                            stack.callback(module.register_forward_pre_hook(save(name)).remove)
                    else:
                        stack.callback(recv.mlp.c_proj.register_forward_hook(add_delta).remove)
                    hidden = lm.model.transformer(ids, attention_mask=mask, use_cache=False).last_hidden_state
                logp = lm.model.lm_head(hidden[rows, last]).log_softmax(-1)[rows, targets]
                return cache, logp

            clean, clean_lp = forward(normal)
            base, base_lp = forward(corrupt)
            parts = (clean['heads'] - base['heads']).chunk(heads, dim=1)
            weights = send.attn.c_proj.weight.chunk(heads, dim=0)
            results = []
            for contribution, projection in zip(parts, weights):
                residual = base['residual'] + contribution @ projection
                alternative = recv.mlp.act(recv.mlp.c_fc(recv.ln_2(residual)))
                # All other recipients of the head and all unselected MLP units stay corrupted.
                delta = (alternative[:, units] - base['mlp'][:, units]) @ recv.mlp.c_proj.weight[units]
                _, logp = forward(corrupt, delta)
                results.append((logp - base_lp).numpy())
            restored.append(np.stack(results, axis=1))
            clean_gaps.extend((clean_lp - base_lp).tolist())
    return np.concatenate(restored).astype('float64'), np.array(clean_gaps)


def circuit_task(directory, model_dir):
    packet, lm = Packet(directory), LanguageModel(model_dir)
    receiver = next(r for r in search(packet) if r['layer'] == 2 and r['position'] == 'pre1')['order_units']
    effects, gaps, pair_ids = [], [], []
    for split in ('search', 'confirm'):
        pairs = packet.pairs[split][:32]
        entries = [packet.meta['originals'][p['row']] for p in pairs]
        diff, gap = head_paths(lm, entries, [p['reverse'] for p in pairs], receiver)
        effects.append(diff)
        gaps.append(float(gap.mean()))
        pair_ids.append([packet.meta['ids'][p['row']] for p in pairs])
    public, private = [], {}
    for head in range(effects[0].shape[1]):
        key = f'L1-H{head}-to-L2-MLP'
        for idx, data in enumerate(effects):
            observed = data[:, head]
            other = np.delete(data, head, axis=1).mean(axis=1)
            record = {'patched_logp_gain': float(observed.mean()), 'other_heads_mean': float(other.mean()),
                      'intact_minus_corrupt_logp': gaps[idx]}
            value = float((observed - other).mean())
            if idx == 0:
                public.append({'id': key, 'train_value': value, **record})
            else:
                private[key] = {'value': value, **record, 'pair_effects': (observed - other).tolist()}
    facts = {'model_revision': lm.revision, 'packet_sha256': packet.digest, 'source_layer': 1, 'receiver_layer': 2,
             'receiver_units': receiver, 'position': 'pre1', 'pairs_train_test': list(map(len, pair_ids)),
             'search_sentence_ids': pair_ids[0], 'comparison': 'eleven other heads at the same sender layer and receiver'}
    return facts, public, private
