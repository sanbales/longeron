"""Command-line interface: ``sysml2 <command> ...``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


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
        prog="sysml2",
        description="Parse, export, and execute SysML v2 models.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="syntax-check a .sysml/.kerml file")
    p.add_argument("file")
    p.add_argument("--kerml", action="store_true",
                   help="force KerML grammar")
    p.add_argument("--tree", action="store_true",
                   help="print the raw parse tree")

    p = sub.add_parser("export", help="export a model to JSON or SysML text")
    p.add_argument("file")
    p.add_argument("--format", choices=["json", "sysml"], default="json")
    p.add_argument("-o", "--output", help="output path (default stdout)")

    p = sub.add_parser("calc", help="invoke a calc def as a function")
    p.add_argument("file")
    p.add_argument("name", help="qualified name, e.g. Pkg::MyCalc")
    p.add_argument("args", nargs="*", help="name=value arguments")

    p = sub.add_parser("check", help="instantiate a part def and check its "
                                     "constraints")
    p.add_argument("file")
    p.add_argument("name", help="qualified name of a part def")
    p.add_argument("args", nargs="*", help="name=value attribute bindings")

    p = sub.add_parser("run", help="execute an action def")
    p.add_argument("file")
    p.add_argument("name")
    p.add_argument("args", nargs="*", help="name=value inputs")
    p.add_argument("--events", help="comma-separated event names")

    p = sub.add_parser("simulate", help="simulate a state def")
    p.add_argument("file")
    p.add_argument("name")
    p.add_argument("--events", help="comma-separated event names", default="")

    ns = parser.parse_args(argv)

    from . import (Interpreter, load, parse_file, to_json, to_sysml)

    if ns.command == "parse":
        result = parse_file(ns.file,
                            language="kerml" if ns.kerml else None)
        if ns.tree:
            print(result.tree_text())
        else:
            print(f"OK: {ns.file} parses as {result.language}")
        return 0

    model = load(ns.file)
    if ns.command == "export":
        text = to_json(model) if ns.format == "json" else to_sysml(model)
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
        for result in interp.check(instance):
            status = {True: "PASS", False: "FAIL", None: "SKIP"}[result.passed]
            failures += result.passed is False
            print(f"[{status}] {result.kind} {result.name}: "
                  f"{result.expression}{' -- ' + result.message if result.message else ''}")
        return 1 if failures else 0

    if ns.command == "run":
        events = [e for e in (ns.events or "").split(",") if e]
        result = interp.run_action(ns.name, inputs=_kv_pairs(ns.args),
                                   events=events)
        for line in result.trace:
            print(f"  {line}")
        print("outputs:", json.dumps({k: _jsonable(v) for k, v in
                                      result.outputs.items()}))
        if result.sends:
            print("sends:", [repr(s.payload) for s in result.sends])
        return 0

    if ns.command == "simulate":
        events = [e for e in ns.events.split(",") if e]
        result = interp.simulate(ns.name, events=events)
        for step in result.trace:
            print(f"  {step}")
        print(f"final state: {result.final_state}")
        if result.ignored_events:
            print(f"ignored events: {result.ignored_events}")
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
