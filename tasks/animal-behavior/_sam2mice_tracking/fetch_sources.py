"""Download and verify the author's public SAM2Mice source archive."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.request


FILE_NAME = "SAM2_Mice.zip"
FILE_ID = 69058690
EXPECTED_BYTES = 724781382
EXPECTED_MD5 = "b86c08e2d11174bf53560453160bb658"
SOURCE_URL = f"https://ndownloader.figshare.com/files/{FILE_ID}"
ARTICLE = "10.6084/m9.figshare.33942097.v1"
CHUNK_BYTES = 32 * 1024 * 1024


def ordinary_file(path):
    if path.is_symlink():
        raise ValueError("source path is a symbolic link")
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError("source path must be an independent regular file")


def hash_file(path):
    ordinary_file(path)
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            md5.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest()


def atomic_json(path, value):
    ordinary_file(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def verified_receipt(path):
    md5, sha256 = hash_file(path)
    if path.stat().st_size != EXPECTED_BYTES or md5 != EXPECTED_MD5:
        raise ValueError("archive bytes or published MD5 differ; preserve the file for inspection")
    return {
        "schema": "bpb-sam2mice-source/1",
        "status": "verified",
        "file": FILE_NAME,
        "file_id": FILE_ID,
        "bytes": EXPECTED_BYTES,
        "md5": md5,
        "sha256": sha256,
        "source_url": SOURCE_URL,
        "source_article": ARTICLE,
        "license": "CC-BY-4.0",
    }


def download(output_dir):
    target = output_dir / FILE_NAME
    partial = output_dir / (FILE_NAME + ".partial")
    receipt_path = output_dir / "source-receipt.json"
    for path in (target, partial, receipt_path):
        ordinary_file(path)
    if target.exists():
        receipt = verified_receipt(target)
        atomic_json(receipt_path, receipt)
        return receipt
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > EXPECTED_BYTES:
        raise ValueError("partial archive exceeds the published source size")
    deadline = time.monotonic() + 3600
    context = ssl.create_default_context()
    failures = 0
    while offset < EXPECTED_BYTES:
        if time.monotonic() > deadline:
            raise TimeoutError("one-hour source download bound reached")
        end = min(EXPECTED_BYTES - 1, offset + CHUNK_BYTES - 1)
        request = urllib.request.Request(SOURCE_URL, headers={
            "Range": f"bytes={offset}-{end}",
            "Accept-Encoding": "identity",
            "User-Agent": "BrainPilotBench-source-preparation",
        })
        try:
            with urllib.request.urlopen(request, context=context, timeout=90) as response:
                expected_range = f"bytes {offset}-{end}/{EXPECTED_BYTES}"
                if response.status != 206 or response.headers.get("Content-Range") != expected_range:
                    raise ValueError("source server did not honor the exact requested byte range")
                with partial.open("ab") as output:
                    while chunk := response.read(min(1024 * 1024, end + 1 - offset)):
                        if offset + len(chunk) > end + 1:
                            raise ValueError("download response exceeded its selected byte range")
                        output.write(chunk)
                        offset += len(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if offset != end + 1:
                    raise OSError("short source response")
            failures = 0
            print(json.dumps({"status": "downloading", "bytes": offset,
                              "expected_bytes": EXPECTED_BYTES}), flush=True)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"source HTTP {error.code}; partial archive preserved") from None
        except (OSError, urllib.error.URLError) as error:
            failures += 1
            if failures >= 3:
                raise RuntimeError("source transfer stopped after three consecutive errors") from error
            time.sleep(failures * 2)
    receipt = verified_receipt(partial)
    os.link(partial, target)
    partial.unlink()
    atomic_json(receipt_path, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output.absolute()
    if output_dir in (Path("/"), Path.home()) or ".." in output_dir.parts:
        raise ValueError("a dedicated source output directory is required")
    if any(path.is_symlink() for path in (output_dir, *output_dir.parents)):
        raise ValueError("source directory has a linked ancestor")
    repo = Path(__file__).resolve().parents[3]
    if output_dir.is_relative_to(repo) and not output_dir.is_relative_to(repo / ".cache"):
        raise ValueError("source data inside the checkout must stay under .cache")
    os.umask(0o077)
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output_dir.stat().st_mode & 0o077:
        raise ValueError("source output must be owner-only")
    print(json.dumps(download(output_dir), sort_keys=True))


if __name__ == "__main__":
    main()
