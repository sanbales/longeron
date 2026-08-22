#!/usr/bin/env python3
"""Sweep the OMG SysML-v2-Release corpus: parse and build every ``.sysml`` file.

This is the reproducible check behind the "SysML v2 corpus 309/309" badge.
The corpus is not vendored; this script downloads the pinned upstream commit
(the same revision ``scripts/vendor_stdlib.py`` pins the vendored standard
library to), extracts its ``.sysml`` files, and runs parse + build over each:

    python scripts/check_corpus.py            # download (cached) + sweep
    python scripts/check_corpus.py --jobs 1   # serial sweep

The first run downloads a ~110 MB tarball; extracted files are cached under
``~/.cache/longeron/corpus/<commit>`` (``$LONGERON_CACHE_DIR`` and
``$XDG_CACHE_HOME`` are honored).  Uses only the standard library and
longeron itself.  Exits non-zero if any file fails, or if the file count
does not match the pinned expectation.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

REPO = "Systems-Modeling/SysML-v2-Release"
#: tag 2026-05 -- the same commit src/longeron/_stdlib is vendored from
PINNED_COMMIT = "de1070ae8e79c21532b8004fc663d47b35d0e9fa"
#: every .sysml file in the repository at PINNED_COMMIT
EXPECTED_FILES = 309


def cache_root() -> Path:
    override = os.environ.get("LONGERON_CACHE_DIR")
    if override:
        return Path(override) / "corpus"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "longeron" / "corpus"


def fetch_corpus(ref: str, dest: Path) -> Path:
    """Download the release tarball for ``ref`` and extract its .sysml files."""

    target = dest / ref
    if target.is_dir() and any(target.rglob("*.sysml")):
        return target
    url = f"https://github.com/{REPO}/archive/{ref}.tar.gz"
    print(f"downloading {url} ...")
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as handle:
        with urllib.request.urlopen(url, timeout=600) as response:
            while chunk := response.read(1 << 20):
                handle.write(chunk)
        tarball = Path(handle.name)
    try:
        print(f"extracting .sysml files to {target} ...")
        with tarfile.open(tarball) as archive:
            members = [m for m in archive.getmembers() if m.name.endswith(".sysml")]
            archive.extractall(target, members=members, filter="data")
    finally:
        tarball.unlink()
    return target


def check_file(path: str) -> str | None:
    """Parse + build one file; return a one-line failure description or None."""

    from longeron.builder import build_model
    from longeron.parser import parse_sysml_text

    try:
        text = Path(path).read_text("utf-8")
        build_model(parse_sysml_text(text, source_name=path))
    except Exception as exc:  # report, don't crash the sweep
        first_line = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        return f"{path}: {type(exc).__name__}: {first_line[:200]}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default=PINNED_COMMIT, help="corpus git ref (default: pinned)")
    parser.add_argument("--dest", type=Path, default=None, help="extraction cache directory")
    parser.add_argument(
        "--jobs", type=int, default=os.cpu_count() or 1, help="parallel workers (default: CPUs)"
    )
    ns = parser.parse_args(argv)

    corpus = fetch_corpus(ns.ref, ns.dest or cache_root())
    files = sorted(str(p) for p in corpus.rglob("*.sysml"))
    print(f"sweeping {len(files)} files with {ns.jobs} worker(s) ...")

    if ns.jobs > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=ns.jobs) as pool:
            results = list(pool.map(check_file, files))
    else:
        results = [check_file(path) for path in files]
    failures = [failure for failure in results if failure]

    for failure in failures:
        print(f"FAIL {failure}")
    passed = len(files) - len(failures)
    print(f"{passed}/{len(files)} files parse and build")
    if ns.ref == PINNED_COMMIT and len(files) != EXPECTED_FILES:
        print(
            f"error: expected {EXPECTED_FILES} corpus files "
            f"at the pinned commit, found {len(files)}"
        )
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
