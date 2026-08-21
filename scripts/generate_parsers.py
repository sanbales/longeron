#!/usr/bin/env python3
"""Regenerate the ANTLR parsers in src/sysml2/_gen from grammars/*.g4.

Requires Java 11+ and the ANTLR 4.13.2 tool jar.  The jar is located via
(in order): $ANTLR_JAR, ~/.m2/repository/org/antlr/antlr4/<ver>/, or it is
downloaded from Maven Central.  Java is located via $JAVA_HOME, PATH, or a
conda/mamba env (e.g. `mamba create -n jdk openjdk`).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ANTLR_VERSION = "4.13.2"
ROOT = Path(__file__).resolve().parent.parent
GRAMMARS = {
    "SysML.g4": "sysml",
    "KerML.g4": "kerml",
}
MAVEN_URL = (
    f"https://repo1.maven.org/maven2/org/antlr/antlr4/{ANTLR_VERSION}"
    f"/antlr4-{ANTLR_VERSION}-complete.jar"
)


def find_antlr4() -> list[str] | None:
    """An `antlr4` tool on PATH (e.g. conda-forge's `antlr`, via pixi)."""

    tool = shutil.which("antlr4")
    if tool is None:
        return None
    probe = subprocess.run([tool], capture_output=True, text=True)
    banner = probe.stdout + probe.stderr
    if ANTLR_VERSION not in banner:
        print(f"warning: {tool} is not ANTLR {ANTLR_VERSION}; ignoring it")
        return None
    return [tool]


def find_java() -> str:
    if os.environ.get("JAVA_HOME"):
        for sub in ("bin/java", "lib/jvm/bin/java"):
            candidate = Path(os.environ["JAVA_HOME"]) / sub
            if candidate.exists():
                return str(candidate)
    if shutil.which("java"):
        return "java"
    for pattern in (
        "~/mamba/envs/*/lib/jvm/bin/java",
        "~/mamba/envs/*/bin/java",
        "~/miniforge3/envs/*/lib/jvm/bin/java",
        "~/miniconda3/envs/*/bin/java",
    ):
        matches = sorted(Path.home().glob(pattern.replace("~/", "")))
        if matches:
            return str(matches[0])
    sys.exit("error: no Java found. Try: mamba create -n jdk openjdk")


def find_jar() -> str:
    if os.environ.get("ANTLR_JAR"):
        return os.environ["ANTLR_JAR"]
    m2 = (
        Path.home()
        / ".m2/repository/org/antlr/antlr4"
        / ANTLR_VERSION
        / f"antlr4-{ANTLR_VERSION}-complete.jar"
    )
    if m2.exists():
        return str(m2)
    m2.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {MAVEN_URL} ...")
    urllib.request.urlretrieve(MAVEN_URL, m2)
    return str(m2)


def main() -> None:
    runner = find_antlr4()
    if runner is None:
        java, jar = find_java(), find_jar()
        runner = [java, "-jar", jar]
    for grammar, subdir in GRAMMARS.items():
        out = ROOT / "src/sysml2/_gen" / subdir
        out.mkdir(parents=True, exist_ok=True)
        (out / "__init__.py").touch()
        cmd = [
            *runner,
            "-Dlanguage=Python3",
            "-visitor",
            "-no-listener",
            "-Xexact-output-dir",
            "-o",
            str(out),
            f"grammars/{grammar}",
        ]
        print("$", " ".join(cmd))
        # run from the repo root with a relative grammar path so the header
        # comment in generated files is machine-independent
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        for line in result.stderr.splitlines():
            if "warning(154)" not in line:  # rule-can-match-empty warnings
                print(line)
        if result.returncode != 0:
            sys.exit(f"ANTLR failed for {grammar}")
    (ROOT / "src/sysml2/_gen/__init__.py").touch()
    print("done.")


if __name__ == "__main__":
    main()
