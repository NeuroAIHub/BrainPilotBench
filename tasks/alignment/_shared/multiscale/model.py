"""Token-aligned reads and pre-target interventions, using verified local weights."""
from collections import Counter
from contextlib import ExitStack
import re

import numpy as np

from brainscore.models import verified_assets
from brainscore.registry import load as registry
from . import POSITIONS

WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")
PLAIN = re.compile(r"([A-Za-z]+(?:'[A-Za-z]+)?(?: [A-Za-z]+(?:'[A-Za-z]+)?){4,})([.!?]?)")


def encode(tokenizer, text):
    encoding = tokenizer(text, return_offsets_mapping=True, add_special_tokens=False)
    spans = list(WORD.finditer(text))
    if not spans:
        raise ValueError('sentence has no lexical target')
    last = spans[-1]
    overlap = [i for i, (start, stop) in enumerate(encoding['offset_mapping'])
               if start < last.end() and stop > last.start()]
    if not overlap or overlap[0] < len(POSITIONS):
        raise ValueError('target lacks the required prefix: ' + text)
    ids = encoding['input_ids']
    return {'text': text, 'ids': ids, 'tokens': tokenizer.convert_ids_to_tokens(ids),
            'target': last.group(), 'start': overlap[0], 'stop': overlap[-1] + 1}


def variants(tokenizer, original):
    """Allow probes only when both manipulations preserve the target token and its index."""
    match = PLAIN.fullmatch(original['text'])
    if not match or original['stop'] != original['start'] + 1:
        return None
    words = match[1].split()
    middle = words[1:-1]
    result = {}
    for name, interior in [('reverse', middle[::-1]), ('rotate', middle[1:] + middle[:1])]:
        arranged = [words[0], *interior, words[-1]]
        if arranged == words or Counter(arranged) != Counter(words):
            return None
        item = encode(tokenizer, ' '.join(arranged) + match[2])
        start = original['start']
        if (Counter(item['ids']) != Counter(original['ids']) or item['start'] != start or item['stop'] != original['stop']
                or item['ids'][start:] != original['ids'][start:]):
            return None
        result[name] = item
    return result


class LanguageModel:
    def __init__(self, directory):
        import torch
        import transformers
        from transformers import AutoModelForCausalLM, AutoTokenizer
        bindings = registry()
        verified_assets(directory, 'distilgpt2', bindings)
        torch.set_num_threads(2)
        self.model = AutoModelForCausalLM.from_pretrained(
            directory, local_files_only=True, use_safetensors=True, trust_remote_code=False,
            torch_dtype=torch.float32, attn_implementation='eager').cpu().eval()
        self.tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True, trust_remote_code=False)
        self.revision = bindings['candidates']['distilgpt2']['weight_revision']
        self.runtime = {'torch': str(torch.__version__), 'transformers': transformers.__version__,
                        'numpy': np.__version__, 'device': 'cpu', 'dtype': 'float32'}

    def batch(self, sequences):
        import torch
        longest = max(map(len, sequences))
        if longest > self.model.config.n_positions:
            raise ValueError('input exceeds model context')
        ids = torch.full((len(sequences), longest), self.tokenizer.eos_token_id, dtype=torch.long)
        mask = torch.zeros_like(ids)
        for i, tokens in enumerate(sequences):
            ids[i, :len(tokens)] = torch.tensor(tokens)
            mask[i, :len(tokens)] = 1
        return ids, mask

    def features(self, entries):
        import torch
        units, controls, whole = [], [], []
        with torch.inference_mode():
            for offset in range(0, len(entries), 16):
                items = entries[offset:offset + 16]
                ids, mask = self.batch([v['ids'] for v in items])
                start = torch.tensor([v['start'] for v in items])
                rows = torch.arange(len(items))
                positions = start[:, None] - torch.arange(1, len(POSITIONS) + 1)
                layers = []

                def capture(module, args):
                    layers.append(args[0][rows[:, None], positions].numpy().copy())

                with ExitStack() as stack:
                    for block in self.model.transformer.h:
                        handle = block.mlp.c_proj.register_forward_pre_hook(capture)
                        stack.callback(handle.remove)
                    hidden = self.model.transformer(ids, attention_mask=mask, use_cache=False).last_hidden_state
                units.append(np.stack(layers, axis=1))
                lengths = mask.sum(1)
                whole.append(hidden[rows, lengths - 1].numpy().copy())
                logits = self.model.lm_head(hidden[:, :-1])
                nll = torch.nn.functional.cross_entropy(logits.transpose(1, 2), ids[:, 1:], reduction='none')
                surprise = (nll * mask[:, 1:]).sum(1) / (lengths - 1)
                controls.extend([len(v['text'].split()), int(length), float(loss)]
                                for v, length, loss in zip(items, lengths, surprise))
        return np.concatenate(units), np.asarray(controls), np.concatenate(whole)

    def target_probabilities(self, entries, layer, position, groups):
        """Run on the prefix only. Column zero is intact, subsequent columns ablate one group."""
        import torch
        batches = []
        with torch.inference_mode():
            for offset in range(0, len(entries), 16):
                items = entries[offset:offset + 16]
                ids, mask = self.batch([v['ids'][:v['start']] for v in items])
                rows = torch.arange(len(items))
                last = mask.sum(1) - 1
                targets = torch.tensor([v['ids'][v['start']] for v in items])
                columns = []
                for group in [None, *groups]:
                    with ExitStack() as stack:
                        if group is not None:
                            def ablate(module, args):
                                activation = args[0].clone()
                                activation[rows[:, None], (last - position)[:, None], group] = 0
                                return (activation,)
                            handle = self.model.transformer.h[layer].mlp.c_proj.register_forward_pre_hook(ablate)
                            stack.callback(handle.remove)
                        hidden = self.model.transformer(ids, attention_mask=mask, use_cache=False).last_hidden_state
                    logits = self.model.lm_head(hidden[rows, last])
                    columns.append(logits.log_softmax(-1)[rows, targets].numpy())
                batches.append(np.stack(columns, axis=1))
        return np.concatenate(batches)
