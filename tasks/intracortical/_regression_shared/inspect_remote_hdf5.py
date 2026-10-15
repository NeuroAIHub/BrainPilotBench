"""Read bounded HDF5 metadata from one pinned M2 asset over HTTP ranges.

Only group names, dataset shapes, and storage sizes are reported. The command
does not export a data array or change the frozen source verification policy.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
import io
import json
import re
from urllib.request import Request, urlopen

import h5py

from fetch_resumable import prepare


RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)\Z")


class BoundedRangeFile(io.RawIOBase):
    def __init__(self, asset: dict, budget: int, block: int = 65_536):
        self.asset = asset
        self.budget = budget
        self.block = block
        self.pos = 0
        self.downloaded = 0
        self.requests = 0
        self.cache = OrderedDict()

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        base = (0, self.pos, self.asset["size_bytes"])[whence]
        self.pos = base + offset
        if self.pos < 0:
            raise ValueError("negative file seek")
        return self.pos

    def _block(self, number: int) -> bytes:
        if number in self.cache:
            self.cache.move_to_end(number)
            return self.cache[number]
        begin = number * self.block
        end = min(begin + self.block, self.asset["size_bytes"]) - 1
        needed = end - begin + 1
        if self.downloaded + needed > self.budget:
            raise RuntimeError("remote metadata read exceeded byte budget")
        request = Request(f"{prepare.API}/assets/{self.asset['asset_id']}/download/",
                          headers={"Range": f"bytes={begin}-{end}"})
        with urlopen(request, timeout=30) as response:
            header = RANGE.fullmatch(response.headers.get("Content-Range", ""))
            if (response.status != 206 or header is None
                    or tuple(map(int, header.groups())) != (begin, end, self.asset["size_bytes"])):
                raise ValueError("server did not honor exact metadata range")
            data = response.read(needed + 1)
        if len(data) != needed:
            raise ValueError("short or oversized metadata range")
        self.downloaded += len(data)
        self.requests += 1
        self.cache[number] = data
        self.cache.move_to_end(number)
        while len(self.cache) > 32:
            self.cache.popitem(last=False)
        return data

    def read(self, size=-1):
        remaining = max(0, self.asset["size_bytes"] - self.pos)
        if size < 0:
            size = remaining
        size = min(size, remaining)
        parts = []
        while size:
            number, inside = divmod(self.pos, self.block)
            block = self._block(number)
            piece = block[inside:inside + size]
            parts.append(piece)
            self.pos += len(piece)
            size -= len(piece)
        return b"".join(parts)

    def readinto(self, target):
        data = self.read(len(target))
        target[:len(data)] = data
        return len(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--budget-bytes", type=int, default=5_000_000)
    args = parser.parse_args()
    if not 1 <= args.budget_bytes <= 5_000_000:
        parser.error("remote metadata budget cannot exceed 5,000,000 bytes")
    selected = [asset for asset in prepare.load_manifest()["assets"]
                if asset["task_id"] == "falcon-m2-finger-velocity" and asset["asset_id"] == args.asset_id]
    if len(selected) != 1:
        parser.error("asset ID is not in frozen M2 inventory")
    source = BoundedRangeFile(selected[0], args.budget_bytes)
    datasets = []
    with h5py.File(source, "r") as h5:
        def visit(name, item):
            if isinstance(item, h5py.Dataset):
                datasets.append({"path": name, "shape": list(item.shape), "dtype": str(item.dtype),
                                 "logical_bytes": int(item.size * item.dtype.itemsize),
                                 "storage_bytes": int(item.id.get_storage_size())})
        h5.visititems(visit)
    datasets.sort(key=lambda item: item["storage_bytes"], reverse=True)
    print(json.dumps({"asset_id": args.asset_id, "source_bytes": selected[0]["size_bytes"],
                      "metadata_bytes_downloaded": source.downloaded,
                      "range_requests": source.requests,
                      "dataset_count": len(datasets), "largest_datasets": datasets[:25]}, sort_keys=True))


if __name__ == "__main__":
    main()
