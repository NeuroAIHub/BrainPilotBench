"""Verify and open original local source objects. This module has no fetch path."""
from contextlib import ExitStack, contextmanager
import hashlib
import importlib
from pathlib import Path
import shutil
import stat
from unittest.mock import patch
import zipfile

from real_brainscore.common import new_directory, read_json, sha256
from .protocols import specification
from .registry import require


def source_definition(registry, benchmark_id):
    require(benchmark_id in registry['benchmarks'], 'unknown benchmark id')
    definitions = read_json(registry['root'] / 'source-assets.json')
    return next(source for source in definitions['sources'] if benchmark_id in source['benchmark_ids'])


def audit(raw, registry, benchmark_id, images=True):
    root = Path(raw).expanduser().resolve()
    source = source_definition(registry, benchmark_id)
    found, missing = {}, []
    for asset in source['assets']:
        if asset['kind'].startswith('ceiling') and not asset['asset_id'].startswith(benchmark_id + ':'):
            continue
        if asset['kind'] == 'stimulus_images_zip' and not images:
            continue
        path = root / asset['original_filename']
        if not path.is_file():
            missing.append({'asset_id': asset['asset_id'], 'expected_path': str(path)})
            continue
        require(not path.is_symlink(), 'original source must be a regular file: ' + str(path))
        value = hashlib.sha1()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                value.update(chunk)
        require(value.hexdigest() == asset['sha1'], 'original source checksum differs: ' + asset['asset_id'])
        found[asset['asset_id']] = {'path': str(path), 'sha1': value.hexdigest(), 'sha256': sha256(path), 'bytes': path.stat().st_size}
    return {'source_id': source['source_id'], 'benchmark_id': benchmark_id, 'files': found, 'missing': missing,
            'local_objects_complete': not missing, 'remote_access_attempted': False}


def unpack_images(path, output, max_bytes=20 * 1024 ** 3):
    root = new_directory(output)
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        require(len(members) <= 100000 and sum(row.file_size for row in members) <= max_bytes, 'stimulus archive exceeds limits')
        names = set()
        for row in members:
            name = Path(row.filename)
            mode = row.external_attr >> 16
            require(not name.is_absolute() and '..' not in name.parts and '\\' not in row.filename
                    and not stat.S_ISLNK(mode) and row.filename not in names, 'unsafe stimulus archive entry')
            names.add(row.filename)
            if row.is_dir():
                continue
            require(stat.S_IFMT(mode) in (0, stat.S_IFREG), 'nonregular stimulus archive entry')
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(row) as source, destination.open('xb') as target:
                shutil.copyfileobj(source, target)
    return root


def assembly(raw, temporary, registry, benchmark_id, images=True):
    import pandas as pd
    from brainscore_core.supported_data_standards.brainio import assemblies
    from brainscore_core.supported_data_standards.brainio.stimuli import StimulusSet
    report = audit(raw, registry, benchmark_id, images=images)
    require(report['local_objects_complete'], 'missing local source objects: ' + ', '.join(row['asset_id'] for row in report['missing']))
    definition = source_definition(registry, benchmark_id)
    cls = getattr(assemblies, definition['import_contract']['data_only']['assembly_class'])
    data_asset = next(a for a in definition['assets'] if a['kind'] == 'data_only_assembly')
    path = report['files'][data_asset['asset_id']]['path']
    if definition['domain'] == 'vision':
        csv = next(a for a in definition['assets'] if a['kind'] == 'stimulus_metadata')
        frame = pd.read_csv(report['files'][csv['asset_id']]['path'])
        if 'stimulus_id' not in frame and 'image_id' in frame:
            frame['stimulus_id'] = frame['image_id']  # upstream preserves the original column
        require('stimulus_id' in frame and not frame['stimulus_id'].duplicated().any(), 'stimulus metadata needs unique ids')
        stimuli = StimulusSet(frame)
        stimuli.identifier = definition['stimulus_registry_id']
        if images:
            image_asset = next(a for a in definition['assets'] if a['kind'] == 'stimulus_images_zip')
            directory = unpack_images(report['files'][image_asset['asset_id']]['path'], Path(temporary) / 'images')
            require('filename' in frame, 'stimulus metadata has no image filename')
            paths = {}
            for _, row in frame.iterrows():
                name = Path(str(row['filename']))
                require(not name.is_absolute() and '..' not in name.parts, 'unsafe stimulus filename')
                file = directory / name
                require(file.is_file(), 'stimulus image missing: ' + str(name))
                paths[row['stimulus_id']] = file
            stimuli.stimulus_paths = paths
        value = assemblies.StimulusMergeAssemblyLoader(cls, path, stimulus_set=stimuli,
                    stimulus_set_identifier=stimuli.identifier).load()
    else:
        value = assemblies.AssemblyLoader(cls, path).load()
        data_module = importlib.import_module('brainscore_language.data.' + definition['source_id'])
        value.attrs['bibtex'] = data_module.BIBTEX
    value.attrs['identifier'] = definition['import_contract']['identity_postload']
    value.load()
    return value, report


@contextmanager
def benchmark(raw, temporary, registry, benchmark_id):
    """Keep official constructors/preprocessing; replace only remote object resolution."""
    from brainscore_core.metrics import Score
    from brainscore_core.supported_data_standards.brainio.assemblies import AssemblyLoader
    spec = specification(benchmark_id)
    data, report = assembly(raw, temporary, registry, benchmark_id, images=spec['ecosystem'] == 'vision')
    definition = source_definition(registry, benchmark_id)
    module = importlib.import_module('brainscore_' + spec['ecosystem'] + '.benchmarks.' + definition['source_id']
                                    + ('.benchmarks.benchmark' if definition['source_id'] == 'freemanziemba2013' else '.benchmark'))
    def local_dataset(identifier):
        require(identifier == definition['data_registry_id'], 'unexpected dataset request: ' + identifier)
        return data.copy(deep=True)
    with ExitStack() as stack:
        stack.enter_context(patch.object(module, 'load_dataset', local_dataset))
        if definition['source_id'] == 'pereira2018':
            def local_ceiling(self, identifier, sha1, version_id=None, assembly_prefix='ceiling_', raw_kwargs=None):
                filename = assembly_prefix + identifier.replace('.', '_') + '.nc'
                asset = next(a for a in definition['assets'] if a['original_filename'] == filename)
                require(asset['sha1'] == sha1, 'ceiling source lock differs')
                result = AssemblyLoader(Score, report['files'][asset['asset_id']]['path']).load()
                if raw_kwargs:
                    result.attrs['raw'] = local_ceiling(self, identifier, assembly_prefix=assembly_prefix + 'raw_', **raw_kwargs)
                return result
            stack.enter_context(patch.object(module._Pereira2018Experiment, '_load_ceiling', local_ceiling))
        if spec['ecosystem'] == 'vision':
            if definition['source_id'] == 'majajhong2015':
                value = getattr(module, 'MajajHong' + spec['region'] + 'PublicBenchmark')()
            else:
                public = importlib.import_module('brainscore_vision.benchmarks.freemanziemba2013.benchmarks.public_benchmarks')
                value = getattr(public, 'FreemanZiemba' + spec['region'] + 'PublicBenchmark')()
        elif definition['source_id'] == 'pereira2018':
            value = getattr(module, 'Pereira2018_' + benchmark_id.split('.')[1].split('-')[0] + '_ridge')()
        elif definition['source_id'] == 'futrell2018':
            value = module.Futrell2018Pearsonr()
        else:
            value = getattr(module, spec['family'] + '_ridge')()
        require(value.identifier == spec['benchmark_identifier'] and value.version == spec['benchmark_version'], 'official constructor identity/version drift')
        yield value, report
