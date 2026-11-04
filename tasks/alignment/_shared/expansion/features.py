"""Owner-only extraction with already cached, immutable local model weights."""
from real_brainscore.common import load_cache, runtime
from . import ExpansionError


def local_text_features(texts, cache, candidates=False):
    import numpy as np
    _, _, config = load_cache(cache)
    execution = runtime('cpu', online=False)
    import torch
    from transformers import AutoModel, AutoTokenizer
    model_spec = config['model']
    tokenizer = AutoTokenizer.from_pretrained(model_spec['id'], revision=model_spec['tokenizer_revision'],
                                             local_files_only=True, trust_remote_code=False)
    model = AutoModel.from_pretrained(model_spec['id'], revision=model_spec['revision'],
                                     local_files_only=True, trust_remote_code=False, use_safetensors=True,
                                     torch_dtype=torch.float32).eval()
    torch.set_num_threads(4)
    features = []
    lengths = []
    with torch.no_grad():
        for index, text in enumerate(texts):
            tokens = tokenizer(text, return_tensors='pt', truncation=False)
            lengths.append(tokens['input_ids'].shape[1])
            if lengths[-1] > tokenizer.model_max_length:
                raise ExpansionError('text exceeds context limit; no silent truncation')
            output = model(**tokens, use_cache=False, output_hidden_states=candidates)
            values = (torch.stack([output.hidden_states[1][0, -1], output.last_hidden_state[0, -1]]).cpu().numpy()
                      if candidates else output.last_hidden_state[0, -1].cpu().numpy())
            if not np.isfinite(values).all():
                raise ExpansionError('nonfinite model features')
            features.append(values)
            if (index + 1) % 200 == 0:
                print('local frozen text features: %d/%d' % (index + 1, len(texts)), flush=True)
    values = np.stack(features).transpose(1, 0, 2) if candidates else np.stack(features)
    return values, {'model': model_spec, 'representation': ('first transformer block and final normalized block, final token' if candidates else 'AutoModel.last_hidden_state, final token, including final normalization'),
                                'context': 'each supplied string independently; no padding, truncation, cache or sampling',
                                'max_tokens': max(lengths), 'runtime': execution}
