#!/usr/bin/env python3
"""Benchmark cold vs warm model loads through the content-addressed cache.

Regenerates the README's warm-load speedup claim.  Each measurement runs in
a fresh Python process (the dominant cold cost -- ANTLR ATN warmup -- is
paid per process, which is what CLI users experience), against a private
temporary cache directory:

    python scripts/bench_cache.py                     # examples/uav_missions.sysml
    python scripts/bench_cache.py path/to/model.sysml --warm-runs 5

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_CHILD = """
import json, sys, time
sys.path[:0] = json.loads(sys.argv[2])
from longeron.workspace import load_file  # import cost excluded from the timing
start = time.perf_counter()
model = load_file(sys.argv[1], cache=True)
elapsed = time.perf_counter() - start
print(json.dumps({"seconds": elapsed, "elements": sum(1 for _ in model.iter_tree())}))
"""


def _timed_load(source: Path, cache_dir: Path) -> dict:
    env = dict(os.environ, LONGERON_CACHE_DIR=str(cache_dir))
    result = subprocess.run(
        [sys.executable, "-c", _CHILD, str(source), json.dumps(sys.path)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def main(argv: list[str] | None = None) -> int:
    default = Path(__file__).resolve().parent.parent / "examples" / "uav_missions.sysml"
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", nargs="?", default=default, type=Path, help=f"({default})")
    parser.add_argument("--warm-runs", type=int, default=3, help="warm samples; best is kept")
    args = parser.parse_args(argv)
    if not args.file.is_file():
        parser.error(f"no such file: {args.file}")

    with tempfile.TemporaryDirectory(prefix="longeron-bench-") as tmp:
        cache_dir = Path(tmp)
        wall = time.perf_counter()
        cold = _timed_load(args.file, cache_dir)  # empty cache: parse + build + store
        warm = min(
            (_timed_load(args.file, cache_dir) for _ in range(max(1, args.warm_runs))),
            key=lambda r: r["seconds"],
        )
        wall = time.perf_counter() - wall

    ratio = cold["seconds"] / warm["seconds"] if warm["seconds"] > 0 else float("inf")
    print(f"file:      {args.file} ({cold['elements']} elements)")
    print(f"cold load: {cold['seconds']:.3f} s   (fresh process, empty cache)")
    print(f"warm load: {warm['seconds']:.4f} s   (fresh process, cache hit)")
    print(f"speedup:   ~{ratio:,.0f}x   (benchmark wall time {wall:.1f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
