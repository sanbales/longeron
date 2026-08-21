#!/usr/bin/env python3
"""(Re)vendor the SysML v2 standard library subset into src/longeron/_stdlib.

Downloads the pinned file set from Systems-Modeling/SysML-v2-Release and
rebuilds the prebuilt JSON. Run after changing the file lists, to bump the
pinned upstream revision, or after builder changes (`make stdlib` shortcut
rebuilds only the prebuilt JSON).
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STDLIB = ROOT / "src/longeron/_stdlib"
REPO = "Systems-Modeling/SysML-v2-Release"
BRANCH = "master"

SYSTEMS = """Actions Allocations AnalysisCases Attributes Calculations Cases
Connections Constraints Flows Interfaces Items Metadata Parts Ports
Requirements StandardViewDefinitions States SysML UseCases VerificationCases
Views""".split()

QUANTITIES = """ISQ ISQBase Quantities QuantityCalculations
MeasurementReferences MeasurementRefCalculations SI SIPrefixes Time
VectorCalculations TensorCalculations""".split()


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def main() -> None:
    sha = json.loads(fetch(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"))["sha"]
    print(f"pinning {REPO}@{sha}")
    base = f"https://raw.githubusercontent.com/{REPO}/{sha}/sysml.library"
    for subdir, names, upstream in (
        ("systems", SYSTEMS, "Systems%20Library"),
        ("quantities", QUANTITIES, "Domain%20Libraries/Quantities%20and%20Units"),
    ):
        target = STDLIB / subdir
        target.mkdir(parents=True, exist_ok=True)
        for name in names:
            data = fetch(f"{base}/{upstream}/{name}.sysml")
            (target / f"{name}.sysml").write_bytes(data)
            print(f"  {subdir}/{name}.sysml ({len(data)} bytes)")
    readme = STDLIB / "README.md"
    text = readme.read_text()
    import re

    text = re.sub(r"Pinned commit: \S+", f"Pinned commit: {sha}", text)
    readme.write_text(text)

    print("rebuilding prebuilt JSON ...")
    sys.path.insert(0, str(ROOT / "src"))
    rebuild_prebuilt()


def rebuild_prebuilt() -> None:
    from longeron import stdlib

    stdlib._PREBUILT.unlink(missing_ok=True)
    stdlib._raw_prebuilt = None
    stdlib._fingerprint_cache = None
    model = stdlib.standard_library_model()
    print(f"prebuilt: {len(model.members)} packages, {stdlib._PREBUILT.stat().st_size} bytes")


if __name__ == "__main__":
    if "--prebuilt-only" in sys.argv:
        sys.path.insert(0, str(ROOT / "src"))
        rebuild_prebuilt()
    else:
        main()
