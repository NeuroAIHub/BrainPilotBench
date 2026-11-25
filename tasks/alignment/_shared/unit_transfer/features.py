"""Extract native intermediate MLP channels from a local causal language model."""
from contextlib import ExitStack
from pathlib import Path

import numpy as np

from brainscore.models import verified_assets
from brainscore.registry import load as registry
from multiscale.model import encode
from real_brainscore.common import read_json, sha256
from . import MODELS, POSITIONS


def projections(model):
    """Both hooks see the activated intermediate vector immediately before projection."""
    family = model.config.model_type
    if family == 'gpt2':
        blocks = model.transformer.h
        return [block.mlp.c_proj for block in blocks], blocks[0].mlp.c_proj.weight.shape[0]
    if family == 'llama':
        return [block.mlp.down_proj for block in model.model.layers], model.config.intermediate_size
    raise ValueError(f'unsupported causal LM architecture: {family}')


def load_local(candidate, directory):
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    directory = Path(directory).expanduser().resolve()
    if candidate not in MODELS or not (directory / 'config.json').is_file():
        raise ValueError(f'{candidate} requires a complete local model and tokenizer in {directory}')
    config = read_json((directory / 'config.json').resolve())
    if candidate == 'llama-3.2-1b':
        if (config.get('model_type'), config.get('hidden_size'), config.get('num_hidden_layers'),
                config.get('intermediate_size')) != ('llama', 2048, 16, 8192):
            raise ValueError('expected a Llama 3.2 1B configuration')
    else:
        verified_assets(directory, candidate, registry())
    # The content identity also binds the tokenizer, including optional local overrides.
    assets = sorted(p for p in directory.iterdir() if p.is_file() and
                    (p.suffix in ('.json', '.safetensors', '.model', '.txt') and
                     p.name not in ('model-manifest.json', 'LICENSE.txt')))
    if not any(p.suffix == '.safetensors' for p in assets):
        raise ValueError('missing local safetensors weights')
    binding = {p.name: sha256(p) for p in assets}
    tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True, trust_remote_code=False)
    if not tokenizer.is_fast or tokenizer.eos_token_id is None:
        raise ValueError('expected a tokenizer with lexical offsets and an EOS token')
    torch.set_num_threads(2)
    model, loading = AutoModelForCausalLM.from_pretrained(
        directory, local_files_only=True, use_safetensors=True, trust_remote_code=False,
        dtype=torch.float32, attn_implementation='eager', output_loading_info=True)
    if any(loading.get(k) for k in ('missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs')):
        raise ValueError('weights do not fully match the model configuration')
    hooks, width = projections(model)
    info = {'id': candidate, 'family': model.config.model_type, 'layers': len(hooks), 'width': width,
            'assets_sha256': binding, 'torch': str(torch.__version__), 'transformers': transformers.__version__,
            'dtype': 'float32', 'device': 'cpu'}
    return model.cpu().eval(), tokenizer, info


def batch_features(model, entries, eos):
    import torch
    from torch.nn.functional import cross_entropy

    lengths = torch.tensor([len(e['ids']) for e in entries])
    if lengths.max().item() > model.config.max_position_embeddings:
        raise ValueError('sentence exceeds the model context')
    ids = torch.full((len(entries), int(lengths.max())), eos, dtype=torch.long)
    for row, entry in enumerate(entries):
        ids[row, :lengths[row]] = torch.tensor(entry['ids'])
    mask = torch.arange(ids.shape[1])[None, :] < lengths[:, None]
    rows = torch.arange(len(entries))[:, None]
    positions = torch.tensor([e['start'] for e in entries])[:, None] - torch.arange(1, len(POSITIONS) + 1)
    activations = []

    def capture(module, args):
        activations.append(args[0][rows, positions].float().cpu().numpy().copy())

    with torch.inference_mode(), ExitStack() as stack:
        for projection in projections(model)[0]:
            stack.callback(projection.register_forward_pre_hook(capture).remove)
        logits = model(input_ids=ids, attention_mask=mask.long(), use_cache=False).logits
        nll = cross_entropy(logits[:, :-1].transpose(1, 2), ids[:, 1:], reduction='none')
        surprisal = (nll * mask[:, 1:]).sum(1) / (lengths - 1)
    units = np.stack(activations, axis=1)
    controls = np.column_stack((lengths.numpy(), surprisal.numpy()))
    if not np.isfinite(units).all() or not np.isfinite(controls).all():
        raise ValueError('nonfinite model features')
    return units, controls


def write_features(directory, texts, model, tokenizer, batch_size):
    hooks, width = projections(model)
    units = np.lib.format.open_memmap(directory / 'units.npy', mode='w+', dtype='float32',
                                      shape=(len(texts), len(hooks), len(POSITIONS), width))
    controls = np.empty((len(texts), 2), dtype='float64')
    for start in range(0, len(texts), batch_size):
        batch = slice(start, start + batch_size)
        entries = [encode(tokenizer, text) for text in texts[batch]]
        units[batch], controls[batch] = batch_features(model, entries, tokenizer.eos_token_id)
    units.flush()
    np.save(directory / 'controls.npy', controls, allow_pickle=False)
