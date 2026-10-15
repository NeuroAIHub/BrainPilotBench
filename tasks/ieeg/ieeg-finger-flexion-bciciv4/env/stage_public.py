"""Copy only frozen Train/Valid arrays into a new external Agent workspace."""
import argparse
import os
import shutil
import tempfile
from pathlib import Path
from common import TASK, read_role, sha256, confined


def stage(source, target):
    if (target.is_symlink() or any(p.is_symlink() for p in target.parents) or
            target.resolve().is_relative_to(TASK.parents[2].resolve())):
        raise ValueError("stage target must be outside the repository and contain no symlinks")
    if source.resolve().is_relative_to(target.resolve()) or target.resolve().is_relative_to(source.resolve()):
        raise ValueError("public source and Agent stage must be separate")
    validated = [(role, *read_role(source / role, role)) for role in ("train", "valid")]
    if target.exists():
        if not target.is_dir():
            raise ValueError("Agent stage target must be a directory")
        if any(target.iterdir()):
            expected = {Path(role) / "manifest.json" for role in ("train", "valid")}
            expected.update(Path(role) / entry["path"] for role, manifest, _ in validated
                            for record in manifest["subjects"] for entry in record["files"].values())
            actual = {p.relative_to(target) for p in target.rglob("*") if p.is_file() or p.is_symlink()}
            if actual != expected:
                raise ValueError("existing Agent stage differs from exact public file set")
            for role in ("train", "valid"):
                read_role(target / role, role)
            print(f"Reused 14 verified public files: {target}")
            return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".bpb-bci-stage-", dir=target.parent))
    try:
        for role, manifest, _ in validated:
            folder = temporary / role
            folder.mkdir()
            for record in manifest["subjects"]:
                for entry in record["files"].values():
                    src = confined(source / role, entry["path"])
                    dst = folder / entry["path"]
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                    if sha256(dst) != entry["sha256"]:
                        raise ValueError("copied public data changed")
            shutil.copyfile(source / role / "manifest.json", folder / "manifest.json")
            read_role(folder, role)
        temporary.chmod(0o755)
        if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
            raise FileExistsError("stage target appeared during copy")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    print(f"Staged 12 arrays and 2 public manifests: {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--stage-to", required=True, type=Path)
    args = parser.parse_args()
    stage(args.source, args.stage_to)
