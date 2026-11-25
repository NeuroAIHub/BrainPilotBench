"""Native attention-head → MLP interventions at the last visible prefix token."""
from contextlib import ExitStack
from itertools import combinations

import numpy as np


class PathModel:
    def __init__(self, model, eos):
        self.model, self.eos = model.eval(), eos
        self.gpt = model.config.model_type == 'gpt2'
        if not self.gpt and model.config.model_type != 'llama':
            raise ValueError('unsupported circuit architecture')
        blocks = model.transformer.h if self.gpt else model.model.layers
        self.mlps = [b.mlp for b in blocks]
        self.norms = [b.ln_2 if self.gpt else b.post_attention_layernorm for b in blocks]
        self.head_projs = [b.attn.c_proj if self.gpt else b.self_attn.o_proj for b in blocks]
        self.down = [m.c_proj if self.gpt else m.down_proj for m in self.mlps]
        self.layers = len(blocks)
        self.heads = model.config.num_attention_heads
        self.width = self.down[0].weight.shape[0 if self.gpt else 1]
        self.pairs = list(combinations(range(self.layers), 2))

    def matrix(self, projection):
        # GPT-2 Conv1D stores [input, output], Llama Linear stores [output, input].
        return projection.weight if self.gpt else projection.weight.T

    def contributions(self, sender, heads):
        import torch
        h = heads.reshape(len(heads), self.heads, -1)
        weights = self.matrix(self.head_projs[sender]).reshape(self.heads, h.shape[2], -1)
        return torch.einsum('bhd,hdi->bhi', h, weights)

    def activated(self, receiver, residual):
        x = self.norms[receiver](residual)
        mlp = self.mlps[receiver]
        if self.gpt:
            return mlp.act(mlp.c_fc(x))
        return mlp.act_fn(mlp.gate_proj(x)) * mlp.up_proj(x)

    def inputs(self, pairs):
        import torch
        clean, corrupt, targets = [], [], []
        for pair in pairs:
            normal, reverse = pair['clean_ids'], pair['corrupt_ids']
            if len(normal) != len(reverse) or len(normal) < 2 or normal[-1] != reverse[-1]:
                raise ValueError('paired prefixes must preserve target token and position')
            clean.append(normal[:-1])
            corrupt.append(reverse[:-1])
            targets.append(normal[-1])
        lengths = torch.tensor([len(v) for v in clean])
        longest = int(lengths.max())
        if longest > self.model.config.max_position_embeddings:
            raise ValueError('prefix exceeds context')
        mask = (torch.arange(longest)[None, :] < lengths[:, None]).long()

        def pad(items):
            return torch.tensor([s + [self.eos] * (longest - len(s)) for s in items])
        return pad(clean), pad(corrupt), mask, lengths - 1, torch.tensor(targets)

    def logp(self, ids, mask, last, targets):
        import torch
        rows = torch.arange(len(ids))
        hidden = self.model.base_model(input_ids=ids, attention_mask=mask, use_cache=False).last_hidden_state
        logits = self.model.get_output_embeddings()(hidden[rows, last])
        return logits.log_softmax(-1)[rows, targets]

    def trace(self, ids, mask, last, targets, senders, receivers, gradients=False):
        import torch
        heads, residuals, units, raw = {}, {}, {}, {}
        rows = torch.arange(len(ids))

        def capture(dest, layer, track=False):
            def hook(module, args):
                dest[layer] = args[0][rows, last].detach()
                if track:
                    raw[layer] = args[0]
            return hook

        with ExitStack() as stack:
            for layer in senders:
                stack.callback(self.head_projs[layer].register_forward_pre_hook(capture(heads, layer)).remove)
            for layer in receivers:
                stack.callback(self.norms[layer].register_forward_pre_hook(capture(residuals, layer)).remove)
                stack.callback(self.down[layer].register_forward_pre_hook(capture(units, layer, gradients)).remove)
            lp = self.logp(ids, mask, last, targets)
            grad = {}
            if gradients:
                derivatives = torch.autograd.grad(lp.sum(), [raw[r] for r in receivers])
                grad = {r: g[rows, last].detach() for r, g in zip(receivers, derivatives)}
        return lp.detach(), heads, residuals, units, grad

    def training(self, pairs, folder, batch_size, folds):
        """Fold averages of first-order target log-p changes for every direct path/unit."""
        import torch
        proxy = np.lib.format.open_memmap(folder / 'training_gain_proxy.npy', mode='w+', dtype='float32',
                                          shape=(folds, len(self.pairs), self.heads, self.width))
        clean_units = np.lib.format.open_memmap(folder / 'train_units.npy', mode='w+', dtype='float32',
                                                shape=(len(pairs), self.layers, self.width))
        proxy.fill(0.)
        fold_ids = np.arange(len(pairs)) % folds
        counts = np.bincount(fold_ids, minlength=folds)
        all_layers = range(self.layers)
        for start in range(0, len(pairs), batch_size):
            batch = slice(start, start + batch_size)
            clean, corrupt, mask, last, targets = self.inputs(pairs[batch])
            with torch.no_grad():
                _, clean_heads, _, acts, _ = self.trace(clean, mask, last, targets, all_layers, all_layers)
                clean_units[batch] = torch.stack([acts[i] for i in all_layers], dim=1).numpy()
            _, corr_heads, residuals, base, grad = self.trace(corrupt, mask, last, targets, all_layers, all_layers, True)
            with torch.no_grad():
                messages = [self.contributions(s, clean_heads[s] - corr_heads[s]) for s in all_layers]
                for i, (s, r) in enumerate(self.pairs):
                    changed = self.activated(r, residuals[r][:, None] + messages[s]) - base[r][:, None]
                    effects = (changed * grad[r][:, None]).numpy()
                    for fold in np.unique(fold_ids[batch]):
                        proxy[fold, i] += effects[fold_ids[batch] == fold].sum(axis=0) / counts[fold]
        proxy.flush()
        clean_units.flush()

    def effects(self, pairs, path, batch_size, cut=False):
        """Exact target-log-p restoration for each head with the same selected receiver units."""
        import torch
        s, r, units = path['sender_layer'], path['receiver_layer'], path['units']
        effects, gaps, intact, blocked = [], [], [], []
        with torch.inference_mode():
            for start in range(0, len(pairs), batch_size):
                clean, corrupt, mask, last, targets = self.inputs(pairs[start:start + batch_size])
                clean_lp, ch, cr, cu, _ = self.trace(clean, mask, last, targets, [s], [r])
                base_lp, bh, br, bu, _ = self.trace(corrupt, mask, last, targets, [s], [r])
                messages = self.contributions(s, ch[s] - bh[s])
                after = self.activated(r, br[r][:, None] + messages)[:, :, units]
                delta = (after - bu[r][:, None, units]) @ self.matrix(self.down[r])[units]
                gains = []
                # Batch counterfactual heads while bounding the number of full prefixes per pass.
                for chunk in delta.split(max(1, 32 // len(clean)), dim=1):
                    n = chunk.shape[1]
                    pos = last.repeat_interleave(n)

                    def inject(module, args, output):
                        output = output.clone()
                        output[torch.arange(len(output)), pos] += chunk.reshape(len(output), -1)
                        return output

                    with self.down[r].register_forward_hook(inject):
                        lp = self.logp(corrupt.repeat_interleave(n, dim=0), mask.repeat_interleave(n, dim=0),
                                       pos, targets.repeat_interleave(n))
                    gains.append(lp.reshape(len(clean), n) - base_lp[:, None])
                effects.append(torch.cat(gains, dim=1).numpy())
                gaps.append((clean_lp - base_lp).numpy())
                if cut:
                    contribution = self.contributions(s, ch[s])[:, path['head']]
                    intact.append(cu[r][:, units].numpy())
                    blocked.append(self.activated(r, cr[r] - contribution)[:, units].numpy())
        return (np.concatenate(effects).astype('float64'), np.concatenate(gaps),
                np.concatenate(intact) if cut else None, np.concatenate(blocked) if cut else None)
