"""Fixed candidates from local weights only. No data-driven layer selection."""
from pathlib import Path
import functools
import hashlib
import shutil

from real_brainscore.common import new_directory, read_json, separate_paths, sha256, write_json
from .protocols import specification, fingerprint
from .registry import require


def configuration(registry, benchmark_id, candidate_id):
    require(benchmark_id in registry['benchmarks'], 'unknown benchmark')
    family = registry['families'][registry['benchmarks'][benchmark_id]['family_id']]
    require(candidate_id in family['candidate_ids'], 'candidate is not in the family whitelist')
    spec = specification(benchmark_id)
    candidate = registry['candidates'][candidate_id]
    mapping = candidate['layer_mapping']
    layer = None if spec['readout'] == 'none' else mapping[spec['region']]
    return {'schema': 'bpb-bs-fixed-candidate/1', 'candidate_id': candidate_id, 'model_name': candidate['model_name'],
            'weight_revision': candidate['weight_revision'], 'tokenizer_revision': candidate['tokenizer_revision'],
            'layer': layer, 'region_layer_map': mapping, 'dtype': 'float32', 'device': 'cpu',
            'visual_degrees': 8 if spec['ecosystem'] == 'vision' else None,
            'preprocessing': candidate['preprocessing'], 'context_group': spec['context_group'],
            'recording_type': spec['recording_type'], 'use_localizer': False}


def local_model_files(directory, config, registry):
    require(directory is not None, 'provide an existing --model-dir; no weights are fetched')
    directory = Path(directory).expanduser().resolve()
    manifest = read_json(directory / 'model-manifest.json')
    require(manifest.get('schema') == 'bpb-bs-local-model/1' and manifest.get('candidate_id') == config['candidate_id'], 'model identity differs')
    for field in ('weight_revision', 'tokenizer_revision'):
        require(manifest.get(field) == config[field], 'model revision differs: ' + field)
    files = manifest.get('files')
    require(isinstance(files, dict) and files, 'missing local model file inventory')
    for name, expected in files.items():
        path = directory / name
        require(not Path(name).is_absolute() and '..' not in Path(name).parts and path.is_file() and not path.is_symlink(), 'unsafe model file')
        require(expected == sha256(path), 'local model checksum differs: ' + name)
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file() and p.name != 'model-manifest.json'}
    require(actual == set(files), 'unrecorded local model files')
    require(set(verified_assets(directory, config['candidate_id'], registry)) == set(files), 'model files differ from upstream asset inventory')
    return directory, manifest


def verified_assets(source, candidate_id, registry):
    """Bind local bytes to pinned upstream metadata, independently of a local manifest."""
    require(candidate_id in registry['candidates'] and candidate_id != 'pixels', 'candidate has no weight files')
    source = Path(source).expanduser().resolve()
    candidate = registry['candidates'][candidate_id]
    files = {}
    if candidate_id == 'alexnet':
        path = source / 'alexnet.pth'
        require(path.is_file() and sha256(path).startswith(candidate['weight_artifact']['sha256_prefix']), 'alexnet does not match the official published hash prefix')
        files['alexnet.pth'] = path
    else:
        assets = read_json(registry['root'] / 'model-assets.json')[candidate_id]
        require(assets['revision'] == candidate['weight_revision'], 'model asset revision differs')
        allow = {'config.json', 'generation_config.json', 'tokenizer.json', 'tokenizer_config.json',
                 'special_tokens_map.json', 'vocab.json', 'merges.txt', 'added_tokens.json', 'model.safetensors'}
        for asset in assets['files']:
            name = asset['name']
            if name not in allow or not (source / name).is_file():
                continue
            path = source / name
            require(path.stat().st_size == asset['bytes'], 'model asset size differs: ' + name)
            if asset['sha256']:
                require(sha256(path) == asset['sha256'], 'model asset SHA256 differs: ' + name)
            else:
                value = hashlib.sha1(('blob %d\0' % path.stat().st_size).encode())
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        value.update(chunk)
                require(value.hexdigest() == asset['git_blob_sha1'], 'model asset Git blob hash differs: ' + name)
            files[name] = path
        require({'config.json', 'model.safetensors'} <= set(files) and
                ('tokenizer.json' in files or {'vocab.json', 'merges.txt'} <= set(files)), 'required local model/tokenizer files missing')
    return files


def seal_model(source, output, candidate_id, registry):
    """Copy verified existing model assets; no download path."""
    separate_paths(source, output)
    files = verified_assets(source, candidate_id, registry)
    candidate = registry['candidates'][candidate_id]
    root = new_directory(output)
    for name, path in files.items():
        shutil.copyfile(path, root / name)
    manifest = {'schema': 'bpb-bs-local-model/1', 'candidate_id': candidate_id,
                'weight_revision': candidate['weight_revision'], 'tokenizer_revision': candidate['tokenizer_revision'],
                'files': {name: sha256(root / name) for name in files}}
    write_json(root / 'model-manifest.json', manifest)
    return {'model_dir': str(root), 'files': len(files), 'downloaded': False}


def subject(registry, benchmark_id, candidate_id, model_dir=None):
    spec, config = specification(benchmark_id), configuration(registry, benchmark_id, candidate_id)
    directory, manifest = (None, None) if candidate_id == 'pixels' else local_model_files(model_dir, config, registry)
    if spec['ecosystem'] == 'language':
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from brainscore_language.model_helpers.huggingface import HuggingfaceSubject
        model = AutoModelForCausalLM.from_pretrained(str(directory), local_files_only=True, use_safetensors=True,
                                                    trust_remote_code=False, torch_dtype=torch.float32)
        model.eval()
        tokenizer = AutoTokenizer.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False, truncation_side='left')
        require(config['layer'] is None or config['layer'] in dict(model.named_modules()), 'declared model layer is absent')
        candidate = HuggingfaceSubject(model_id=config['model_name'], model=model, tokenizer=tokenizer,
                    region_layer_mapping={'language_system': [config['layer']]} if config['layer'] else {}, use_localizer=False)
    else:
        from brainscore_vision.model_helpers.brain_transformation import ModelCommitment
        if candidate_id == 'pixels':
            from brainscore_vision.models.pixels.model import PixelModel
            wrapper = PixelModel()
        else:
            import torch
            import torchvision.models
            from brainscore_vision.model_helpers.activations.pytorch import PytorchWrapper, load_preprocess_images
            require('alexnet.pth' in manifest['files'], 'local alexnet.pth is required')
            require(manifest['files']['alexnet.pth'].startswith(registry['candidates'][candidate_id]['weight_artifact']['sha256_prefix']),
                    'alexnet weight fingerprint differs from the official artifact')
            model = torchvision.models.alexnet(weights=None)
            model.load_state_dict(torch.load(directory / 'alexnet.pth', map_location='cpu', weights_only=True), strict=True)
            model.eval()
            wrapper = PytorchWrapper(identifier='bpb-fixed-alexnet-' + fingerprint(config)[:12], model=model,
                                     preprocessing=functools.partial(load_preprocess_images, image_size=224))
            wrapper.image_size = 224
        candidate = ModelCommitment(identifier='bpb-fixed-' + candidate_id + '-' + fingerprint(config)[:12], activations_model=wrapper,
                                    layers=list(dict.fromkeys(config['region_layer_map'].values())),
                                    region_layer_map=config['region_layer_map'], visual_degrees=8)
    return candidate, config, manifest
