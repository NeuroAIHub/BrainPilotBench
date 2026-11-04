"""Explicit, resumable owner downloads from a frozen public source lock."""
from pathlib import Path
import tarfile
import urllib.error
import urllib.request
import zipfile
from http.client import HTTPException

from real_brainscore.common import outside_repository, read_json, sha256
from . import ExpansionError


def entries(task):
    return [v for v in read_json(Path(__file__).with_name('sources.json'))['files'] if v['task'] == task]


def verify_source(root, entry):
    path = Path(root) / entry['file']
    if (path.is_symlink() or not path.is_file() or path.stat().st_size != entry['bytes']
            or sha256(path) != entry['sha256']):
        raise ExpansionError('incomplete or mismatched locked source: ' + entry['file'])
    return path


def download(raw, task):
    root = outside_repository(raw)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for entry in entries(task):
        path = root / entry['file']
        if path.exists():
            verify_source(root, entry)
            continue
        part = path.with_name(path.name + '.part')
        if part.is_symlink():
            raise ExpansionError('download partial is a symlink')
        last_error = None
        for attempt in range(12):
            start = part.stat().st_size if part.exists() else 0
            if start == entry['bytes']:
                break
            if start > entry['bytes']:
                raise ExpansionError('download partial exceeds locked source size')
            request = urllib.request.Request(entry['url'], headers={'Range': 'bytes=%d-' % start} if start else {})
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    if start and response.status != 206:
                        raise ExpansionError('server did not honor byte-range resume; retain partial for operator inspection')
                    if response.status == 206 and not response.headers.get('Content-Range', '').startswith('bytes %d-' % start):
                        raise ExpansionError('download range differs')
                    with part.open('ab' if start else 'wb') as stream:
                        while True:
                            block = response.read(1024 * 1024)
                            if not block:
                                break
                            if stream.tell() + len(block) > entry['bytes']:
                                raise ExpansionError('server sent more bytes than the source lock')
                            stream.write(block)
            except (OSError, urllib.error.URLError, HTTPException) as exc:
                last_error = str(exc)
            print('%s attempt %d: %d/%d bytes' % (entry['file'], attempt + 1,
                  part.stat().st_size if part.exists() else 0, entry['bytes']), flush=True)
        if not part.exists() or part.stat().st_size != entry['bytes'] or sha256(part) != entry['sha256']:
            raise ExpansionError('locked download incomplete/hash mismatch; partial retained: ' + str(last_error))
        part.rename(path)
    unpack(root, task)
    return {'raw': str(root), 'task': task, 'verified_sources': len(entries(task))}


def unpack(raw, task):
    root = outside_repository(raw)
    for entry in entries(task):
        verify_source(root, entry)
    def write(name, contents):
        path = root / name
        if path.exists():
            if path.is_symlink() or path.read_bytes() != contents:
                raise ExpansionError('existing extracted file differs: ' + name)
        else:
            path.write_bytes(contents)
    if task == 'F':
        with tarfile.open(root / 'f-data.tar') as archive:
            name = 'data/brain-lang-data_participant_20230728.csv'
            member = archive.getmember(name)
            if not member.isfile() or member.size > 64 * 1024 * 1024:
                raise ExpansionError('unexpected author CSV archive member')
            write('f-' + Path(name).name, archive.extractfile(member).read())
    if task == 'C':
        with zipfile.ZipFile(root / 'things-it.zip') as archive:
            for subject in ('01', '02', '03'):
                for suffix in ('_StimulusMetadataTestset.csv', '_TestResponsesIT.npy'):
                    name = 'sub-' + subject + suffix
                    item = 'betas_csv_testset/' + name
                    if archive.getinfo(item).file_size > 64 * 1024 * 1024:
                        raise ExpansionError('oversized IT archive member')
                    write(name, archive.read(item))
    return {'raw': str(root), 'task': task, 'verified_sources': len(entries(task))}
