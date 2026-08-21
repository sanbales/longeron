"""Command-line interface: ``longeron <command> ...``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _parse_value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _kv_pairs(pairs):
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"expected name=value, got {pair!r}")
        name, value = pair.split("=", 1)
        out[name] = _parse_value(value)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="longeron",
        description="Parse, export, and execute SysML v2 models. "
        "Model inputs may be a .sysml file, a .json export, or "
        "a directory of .sysml files.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("file", help=".sysml file, .json export, or directory")
    common.add_argument("--no-cache", action="store_true", help="bypass the model cache")
    common.add_argument(
        "--stdlib", action="store_true", help="add the vendored SysML standard library"
    )

    p = sub.add_parser("parse", help="syntax-check .sysml/.kerml files (file or directory)")
    p.add_argument("file")
    p.add_argument("--kerml", action="store_true", help="force KerML grammar")
    p.add_argument("--tree", action="store_true", help="print the raw parse tree")

    p = sub.add_parser(
        "export",
        parents=[common],
        help="export a model to JSON, SysML, KerML, or the OMG API JSON (requires pyecore)",
    )
    p.add_argument("--format", choices=["json", "sysml", "kerml", "api"], default="json")
    p.add_argument("-o", "--output", help="output path (default stdout)")

    p = sub.add_parser(
        "lint",
        parents=[common],
        help="validate a model: dangling references, "
        "duplicate names, cycles; names resolve "
        "against the vendored standard library "
        "unless --no-stdlib",
    )
    p.add_argument("--strict", action="store_true", help="treat warnings as errors")
    p.add_argument(
        "--strict-imports",
        action="store_true",
        help="warn when bare stdlib names are used without an import (stdlib-implicit-name)",
    )
    p.add_argument(
        "--no-stdlib", action="store_true", help="do not resolve names against the standard library"
    )

    p = sub.add_parser("calc", parents=[common], help="invoke a calc def as a function")
    p.add_argument("name", help="qualified name, e.g. Pkg::MyCalc")
    p.add_argument("args", nargs="*", help="name=value arguments")

    p = sub.add_parser(
        "check", parents=[common], help="instantiate a part def and check its constraints"
    )
    p.add_argument("name", help="qualified name of a part def")
    p.add_argument("args", nargs="*", help="name=value attribute bindings")

    p = sub.add_parser("run", parents=[common], help="execute an action def")
    p.add_argument("name")
    p.add_argument("args", nargs="*", help="name=value inputs")
    p.add_argument("--events", help="comma-separated event names")

    p = sub.add_parser("simulate", parents=[common], help="simulate a state def")
    p.add_argument("name")
    p.add_argument("--events", help="comma-separated event names", default="")

    ns = parser.parse_args(argv)

    from . import Interpreter, load, parse_file, to_json, to_kerml, to_sysml

    if ns.command == "parse":
        target = Path(ns.file)
        if target.is_dir():
            pattern = "**/*.kerml" if ns.kerml else "**/*.sysml"
            files = sorted(target.glob(pattern))
            if not files:
                print(f"no {pattern[3:]} files under {target}")
                return 1
            for path in files:
                result = parse_file(path, language="kerml" if ns.kerml else None)
                print(f"OK: {path} parses as {result.language}")
            return 0
        result = parse_file(ns.file, language="kerml" if ns.kerml else None)
        if ns.tree:
            print(result.tree_text())
        else:
            print(f"OK: {ns.file} parses as {result.language}")
        return 0

    model = load(ns.file, cache=False if ns.no_cache else None)
    if ns.stdlib:
        from .stdlib import add_standard_library

        add_standard_library(model)
    if ns.command == "lint":
        from .validation import validate

        diagnostics = validate(
            model, stdlib=False if ns.no_stdlib else None, strict_imports=ns.strict_imports
        )
        for diagnostic in diagnostics:
            print(diagnostic)
        errors = sum(d.severity == "error" for d in diagnostics)
        warnings = len(diagnostics) - errors
        print(f"{errors} error(s), {warnings} warning(s)")
        failed = errors or (ns.strict and warnings)
        return 1 if failed else 0

    if ns.command == "export":
        if ns.format == "api":
            from .api import to_api_json

            text = to_api_json(model)
        else:
            renderers: dict[str, Callable[[Any], str]] = {
                "json": to_json,
                "sysml": to_sysml,
                "kerml": to_kerml,
            }
            text = renderers[ns.format](model)
        if ns.output:
            Path(ns.output).write_text(text, encoding="utf-8")
        else:
            print(text)
        return 0

    interp = Interpreter(model)
    if ns.command == "calc":
        print(interp.call(ns.name, **_kv_pairs(ns.args)))
        return 0

    if ns.command == "check":
        instance = interp.instantiate(ns.name, **_kv_pairs(ns.args))
        print(json.dumps(instance.to_dict(), indent=2))
        failures = 0
        for check in interp.check(instance):
            status = {True: "PASS", False: "FAIL", None: "SKIP"}[check.passed]
            failures += check.passed is False
            message = f" -- {check.message}" if check.message else ""
            print(f"[{status}] {check.kind} {check.name}: {check.expression}{message}")
        return 1 if failures else 0

    if ns.command == "run":
        events = [e for e in (ns.events or "").split(",") if e]
        run = interp.run_action(ns.name, inputs=_kv_pairs(ns.args), events=events)
        for line in run.trace:
            print(f"  {line}")
        print("outputs:", json.dumps({k: _jsonable(v) for k, v in run.outputs.items()}))
        if run.sends:
            print("sends:", [repr(s.payload) for s in run.sends])
        return 0

    if ns.command == "simulate":
        events = [e for e in ns.events.split(",") if e]
        sim = interp.simulate(ns.name, events=events)
        for step in sim.trace:
            print(f"  {step}")
        print(f"final state: {sim.final_state}")
        if sim.ignored_events:
            print(f"ignored events: {sim.ignored_events}")
        return 0

    return 2  # pragma: no cover


def _jsonable(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
