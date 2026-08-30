"""Command-line interface: ``longeron <command> ...``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import ParseError, SysMLError

#: failure classes a CLI user can cause (and fix): missing or unreadable
#: files, syntax/build/resolution/evaluation errors, malformed .json inputs,
#: and missing optional extras.  Anything else is a bug and keeps its
#: traceback.
_EXPECTED_ERRORS = (SysMLError, OSError, ImportError, json.JSONDecodeError)


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


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, OSError) and exc.filename is not None:
        return f"{exc.filename}: {exc.strerror or exc}"
    return str(exc)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="longeron",
        description="Parse, export, and execute SysML v2 models. "
        "Model inputs may be a .sysml file, a .json export, or "
        "a directory of .sysml files.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    flags = argparse.ArgumentParser(add_help=False)
    flags.add_argument(
        "--traceback", action="store_true", help="show the full Python traceback on errors"
    )

    common = argparse.ArgumentParser(add_help=False, parents=[flags])
    common.add_argument("file", help=".sysml file, .json export, or directory")
    common.add_argument("--no-cache", action="store_true", help="bypass the model cache")
    common.add_argument(
        "--stdlib", action="store_true", help="add the vendored SysML standard library"
    )

    p = sub.add_parser(
        "parse", parents=[flags], help="syntax-check .sysml/.kerml files (file or directory)"
    )
    p.add_argument("file")
    p.add_argument("--kerml", action="store_true", help="force KerML grammar")
    p.add_argument("--tree", action="store_true", help="print the raw parse tree")

    p = sub.add_parser(
        "export",
        parents=[common],
        help="export a model to JSON, SysML, KerML, or the OMG API JSON (requires pyecore)",
    )
    p.add_argument("--format", choices=["json", "sysml", "kerml", "api"], default="json")
    p.add_argument(
        "--no-derived",
        action="store_true",
        help="--format api: omit the derived 'source'/'target' relationship "
        "endpoint arrays that pilot-API consumers use for navigation",
    )
    p.add_argument("-o", "--output", help="output path (default stdout)")

    p = sub.add_parser(
        "lint",
        parents=[common],
        help="validate a model: dangling references, "
        "duplicate names, cycles; names resolve "
        "against the vendored standard library "
        "unless --no-stdlib",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="strict mode: unresolved references and other resolution "
        "failures become errors, and a bare 'import' (no visibility "
        "prefix) warns (bare-import)",
    )
    p.add_argument(
        "--strict-imports",
        action="store_true",
        help="warn when bare stdlib names are used without an import (stdlib-implicit-name)",
    )
    p.add_argument(
        "--evidence-coverage",
        action="store_true",
        help="warn on stated attribute values with no SourceEvidence citation "
        "(unevidenced-value; evidence-drift needs no flag)",
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

    p = sub.add_parser(
        "evidence",
        help="provenance: set up LFS storage for evidence documents, "
        "or verify a model's SourceEvidence citations",
    )
    esub = p.add_subparsers(dest="evidence_command", required=True)
    q = esub.add_parser(
        "init",
        parents=[flags],
        help="write the evidence/ git-LFS stanza into .gitattributes",
    )
    q.add_argument("path", nargs="?", default=".", help="repository root (default: .)")
    q = esub.add_parser(
        "verify",
        parents=[common],
        help="re-check every citation; exit code = drifted + lost count",
    )
    q.add_argument(
        "--no-fetch",
        action="store_true",
        help="stay offline: verify URL documents against the local cache only",
    )

    p = sub.add_parser(
        "serve",
        parents=[flags],
        help="serve a workspace over the OMG Systems Modeling API "
        "(git-backed; requires longeron[server])",
    )
    p.add_argument("path", nargs="?", default=".", help="directory or .sysml file to serve")
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address (default 127.0.0.1: local-first, no authentication)",
    )
    p.add_argument("--port", type=int, default=9000, help="port (default 9000)")

    ns = parser.parse_args(argv)

    try:
        return _run(ns)
    except _EXPECTED_ERRORS as exc:
        if ns.traceback:
            raise
        print(f"error: {_error_text(exc)}", file=sys.stderr)
        return 1


def _run(ns: argparse.Namespace) -> int:
    from . import Interpreter, load, parse_file, to_json, to_kerml, to_sysml

    if ns.command == "parse":
        target = Path(ns.file)
        if target.is_dir():
            pattern = "**/*.kerml" if ns.kerml else "**/*.sysml"
            files = sorted(target.glob(pattern))
            if not files:
                print(f"no {pattern[3:]} files under {target}")
                return 1
            failed = 0
            for path in files:
                try:
                    result = parse_file(path, language="kerml" if ns.kerml else None)
                except ParseError as exc:
                    failed += 1
                    print(f"FAIL: {exc}")
                    continue
                print(f"OK: {path} parses as {result.language}")
            if failed:
                print(f"{failed} of {len(files)} file(s) failed to parse")
            return 1 if failed else 0
        result = parse_file(ns.file, language="kerml" if ns.kerml else None)
        if ns.tree:
            print(result.tree_text())
        else:
            print(f"OK: {ns.file} parses as {result.language}")
        return 0

    if ns.command == "serve":
        from .server import serve

        serve(ns.path, host=ns.host, port=ns.port)
        return 0

    if ns.command == "evidence" and ns.evidence_command == "init":
        from .evidence import init_lfs

        print(f"wrote {init_lfs(ns.path)}")
        return 0

    model = load(ns.file, cache=False if ns.no_cache else None)
    if ns.stdlib:
        from .stdlib import add_standard_library

        add_standard_library(model)
    if ns.command == "lint":
        from .validation import validate

        diagnostics = validate(
            model,
            stdlib=False if ns.no_stdlib else None,
            strict_imports=ns.strict_imports,
            strict=ns.strict,
            evidence_coverage=ns.evidence_coverage,
        )
        for diagnostic in diagnostics:
            print(diagnostic)
        errors = sum(d.severity == "error" for d in diagnostics)
        warnings = len(diagnostics) - errors
        print(f"{errors} error(s), {warnings} warning(s)")
        return 1 if errors else 0

    if ns.command == "evidence":  # verify (init returned before the load)
        from .evidence import format_table, verify

        verdicts = verify(model, fetch=not ns.no_fetch)
        rows = [(v.status, v.citation.qname, v.citation.document, v.detail) for v in verdicts]
        print(format_table(("status", "element", "document", "detail"), rows))
        broken = sum(v.status in ("drifted", "lost") for v in verdicts)
        print(f"{len(verdicts)} citation(s): {broken} drifted or lost")
        return broken

    if ns.command == "export":
        if ns.format == "api":
            from .api import to_api_json

            text = to_api_json(model, derived=not ns.no_derived)
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
