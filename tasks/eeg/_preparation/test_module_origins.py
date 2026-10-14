#!/usr/bin/env python3
"""Synthetic lazy-import and pinned-package-origin checks; no EEG data access."""

from importlib.machinery import ModuleSpec
from pathlib import Path
import tempfile
from types import ModuleType
from unittest.mock import patch

import export_classification_native as exporter


def module(name: str, locations: list[Path], file: Path | None) -> ModuleType:
    result = ModuleType(name)
    spec = ModuleSpec(name, loader=None, is_package=True)
    spec.origin = str(file) if file else None
    spec.submodule_search_locations = [str(path) for path in locations]
    result.__spec__ = spec
    result.__file__ = str(file) if file else None
    return result


def checked(source: Path, candidate: ModuleType):
    with patch.object(exporter, "NATIVE_PACKAGES", ("neuralfetch",)), \
         patch.object(exporter.importlib, "import_module", return_value=candidate) as loader:
        value = exporter.verify_module_origins(source)
        loader.assert_called_once_with("neuralfetch")
        return value


def rejected(action, phrase: str) -> None:
    try:
        action()
    except ValueError as error:
        assert phrase in str(error), error
    else:
        raise AssertionError(f"untrusted module origin accepted: {phrase}")


def main() -> None:
    cache = Path.cwd() / ".cache" / "eeg-d-expansion"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="module-origins-", dir=cache) as directory:
        root = Path(directory)
        trusted = root / "source/neuralfetch-repo/neuralfetch"
        trusted.mkdir(parents=True)
        trusted_file = trusted / "__init__.py"
        trusted_file.write_text("", encoding="utf-8")
        foreign = root / "foreign/neuralfetch"
        foreign.mkdir(parents=True)
        foreign_file = foreign / "__init__.py"
        foreign_file.write_text("", encoding="utf-8")
        source = root / "source"

        regular = checked(source, module("neuralfetch", [trusted], trusted_file))
        assert regular["neuralfetch"]["file"] == str(trusted_file)
        namespace = checked(source, module("neuralfetch", [trusted], None))
        assert namespace["neuralfetch"]["file"] is None
        rejected(lambda: checked(source, module("neuralfetch", [foreign], foreign_file)),
                 "foreign or missing package search locations")
        rejected(lambda: checked(source, module("neuralfetch", [trusted, foreign], None)),
                 "foreign or missing package search locations")
        rejected(lambda: checked(source, module("neuralfetch", [], None)),
                 "foreign or missing package search locations")
        rejected(lambda: checked(source, module("neuralfetch", [trusted], foreign_file)),
                 "resolves outside the pinned source")
        missing_spec = ModuleType("neuralfetch")
        rejected(lambda: checked(source, missing_spec), "no matching import specification")
        redirected_source = root / "redirected-source"
        (redirected_source / "neuralfetch-repo").mkdir(parents=True)
        (redirected_source / "neuralfetch-repo/neuralfetch").symlink_to(foreign, target_is_directory=True)
        with patch.object(exporter, "NATIVE_PACKAGES", ("neuralfetch",)), \
             patch.object(exporter.importlib, "import_module") as loader:
            rejected(lambda: exporter.verify_module_origins(redirected_source),
                     "package directory escapes the pinned source")
            loader.assert_not_called()
    print("lazy regular/namespace origins accepted; missing and foreign origins rejected")


if __name__ == "__main__":
    main()
