"""Exporters: model -> JSON and model -> SysML v2 textual notation.

``to_sysml`` regenerates parseable textual notation from a model (whether it
was parsed from text or built programmatically); ``to_dict``/``to_json``
serialize the model structure, with expressions carried both as structured
trees and rendered text.
"""

from __future__ import annotations

import dataclasses
import json
import re

from . import model as M
from .ast import Expr, expr_to_dict, expr_to_text

# Reserved words of the SysML grammar (cannot be used as basic names).
RESERVED_WORDS = frozenset(
    """
about abstract accept action actor after alias all allocate allocation
analysis and as assert assign assume at attribute bind binding by calc case
comment concern connect connection constant constraint crosses decide def
default defined dependency derived do doc else end entry enum event exhibit
exit expose false filter first flow for fork frame from hastype if implies
import in include individual inout interface istype item join language
library locale loop merge message meta metadata new nonunique not null
objective occurrence of or ordered out package parallel part perform port
private protected public redefines ref references render rendering rep
require requirement return satisfy send snapshot specializes stakeholder
standard state subject subsets succession terminate then timeslice to
transition true until use variant variation verification verify via view
viewpoint when while xor
""".split()
)

_BASIC_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def name_needs_quotes(name: str) -> bool:
    return not _BASIC_NAME.match(name) or name in RESERVED_WORDS


def fmt_name(name: str) -> str:
    if name_needs_quotes(name):
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    return name


def fmt_qname(qname: str) -> str:
    """Format a stored qualified-name string (``::``/``.`` separated)."""

    dotted = []
    for chain_part in qname.split("."):
        dotted.append("::".join(p if p == "$" else fmt_name(p) for p in chain_part.split("::")))
    return ".".join(dotted)


def doc_comment_body(text: str) -> str:
    """The canonical ``/* ... */`` body for documentation ``text``.

    Single-line text becomes ``/* text */``; multi-line text uses the
    conventional ``*``-prefixed continuation lines.  This form is a
    textual-export *fixpoint*: stripping it back to text
    (:meth:`~longeron.model.Documentation.text`) and re-rendering yields
    the identical body, no matter how deeply the owner is indented --
    which is why :meth:`_Printer.emit_Documentation` re-renders
    multi-line bodies through it instead of echoing them verbatim
    (verbatim multi-line bodies accumulate indentation on every
    parse/print cycle).  :func:`longeron.edit.set_doc` writes bodies in
    this same form.
    """

    lines = text.splitlines() or [""]
    if len(lines) == 1:
        return f"/* {lines[0]} */" if lines[0] else "/* */"
    out = [f"/* {lines[0]}" if lines[0] else "/*"]
    out += [f" * {line}" if line else " *" for line in lines[1:]]
    out[-1] += " */"
    return "\n".join(out)


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

_SKIP_FIELDS = {"owner"}


def _field_default(f: dataclasses.Field) -> object:
    if f.default is not dataclasses.MISSING:
        return f.default
    if f.default_factory is not dataclasses.MISSING:
        return f.default_factory()
    return dataclasses.MISSING


def _omit_lossless(value, f: dataclasses.Field) -> bool:
    """True when omitting the field from the JSON round-trips exactly.

    Only the empty/None/False sentinels are ever omitted, and only when the
    dataclass default reconstructs *exactly* that value -- so every flag
    (notably True-valued booleans) is emitted whenever omission would not
    restore it.  The model cache relies on this invariant.
    """

    if value is None or value is False:
        return _field_default(f) is value
    if isinstance(value, (list, tuple)) and not value:
        default = _field_default(f)
        return type(default) is type(value) and not default
    return False


def to_dict(element):
    """Convert a model element (or expression) to JSON-able data."""

    if isinstance(element, Expr):
        return expr_to_dict(element)
    if dataclasses.is_dataclass(element):
        data = {"@type": type(element).__name__}
        for f in dataclasses.fields(element):
            if f.name in _SKIP_FIELDS:
                continue
            value = getattr(element, f.name)
            if _omit_lossless(value, f):
                continue
            data[f.name] = _to_data(value)
        return data
    return _to_data(element)


def _to_data(value):
    if isinstance(value, Expr):
        return expr_to_dict(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return to_dict(value)
    if isinstance(value, (list, tuple)):
        return [_to_data(v) for v in value]
    if isinstance(value, float) and value == float("inf"):
        return "*"
    return value


def to_json(element, indent: int = 2) -> str:
    return json.dumps(to_dict(element), indent=indent)


def save(element: M.Element, path, fmt: str | None = None) -> None:
    """Write a model element to disk as ``.sysml``, ``.kerml``, or ``.json``.

    The format is inferred from the file suffix unless given explicitly.
    """

    from pathlib import Path

    target = Path(path)
    if fmt is None:
        fmt = {".json": "json", ".kerml": "kerml"}.get(target.suffix.lower(), "sysml")
    if fmt == "json":
        text = to_json(element)
    elif fmt == "kerml":
        from .kerml import to_kerml

        text = to_kerml(element)
    elif fmt == "sysml":
        text = to_sysml(element)
    else:
        raise ValueError(f"unknown format {fmt!r}")
    target.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Textual export
# ---------------------------------------------------------------------------

_KIND_KEYWORDS = {
    "use_case": "use case",
    "enum_literal": "",
    "feature": "",
    "extended": "",
    "event_occurrence": "event occurrence",
}

_CONTROL_KEYWORDS = {"merge": "merge", "decision": "decide", "join": "join", "fork": "fork"}

#: usage kinds with a reference form and an inline-declaration form
_REF_OR_INLINE_KINDS = {
    "render": ("render", "rendering"),
    "include": ("include", "use case"),
    "frame": ("frame", "concern"),
    "verify": ("verify", "requirement"),
}


def indent_string(indent: int | str) -> str:
    """Normalize an ``indent`` argument (space count or literal string)."""

    return " " * indent if isinstance(indent, int) else indent


def find_emitter(printer, element: M.Element, prefix: str = "emit_"):
    """Look up ``<prefix><ClassName>`` on ``printer`` along the element's MRO.

    Shared dispatch helper for the textual printers (:class:`_Printer` here
    and :class:`longeron.kerml._KerMLPrinter`): the most specific handler
    wins, and ``None`` signals "no handler" so each printer keeps its own
    unknown-element failure behavior.
    """

    for klass in type(element).__mro__:
        handler = getattr(printer, f"{prefix}{klass.__name__}", None)
        if handler is not None:
            return handler
    return None


def to_sysml(element: M.Element, indent: int | str = 4) -> str:
    """Render a model element (usually a :class:`~longeron.model.Model` or
    :class:`~longeron.model.Package`) to SysML v2 textual notation.

    ``indent`` is a number of spaces (or, for back-compat, a literal
    indentation string).
    """

    printer = _Printer(indent_string(indent))
    if isinstance(element, M.Model):
        for member in element.members:
            printer.emit(member, 0)
    else:
        printer.emit(element, 0)
    return "\n".join(printer.lines) + "\n"


class _Printer:
    def __init__(self, indent: str):
        self.indent = indent
        self.lines: list[str] = []

    def line(self, level: int, text: str) -> None:
        for piece in text.split("\n"):
            self.lines.append(self.indent * level + piece if piece else "")

    # -- shared fragments ---------------------------------------------------

    def names(self, el: M.Element) -> str:
        bits = []
        if el.short_name:
            bits.append(f"<{fmt_name(el.short_name)}>")
        if el.name:
            bits.append(fmt_name(el.name))
        return " ".join(bits)

    def prefix(self, el: M.Element) -> str:
        return f"{el.visibility} " if el.visibility else ""

    def metadata(self, el: M.Element) -> str:
        return "".join(f"#{fmt_qname(m)} " for m in el.metadata)

    def value_text(self, value: M.FeatureValue) -> str:
        op = ":=" if value.is_initial else "="
        if value.is_default:
            op = f"default {op}"
        return f"{op} {expr_to_text(value.expr)}"

    def multiplicity_text(self, mult: M.Multiplicity) -> str:
        if mult.lower is not None and mult.upper is not None:
            text = f"[{expr_to_text(mult.lower)}..{expr_to_text(mult.upper)}]"
        elif mult.upper is not None:
            text = f"[{expr_to_text(mult.upper)}]"
        else:
            text = ""
        if mult.is_ordered:
            text += " ordered"
        if mult.is_nonunique:
            text += " nonunique"
        return text

    def usage_declaration(self, u: M.Usage) -> str:
        bits = []
        name = self.names(u)
        if name:
            bits.append(name)
        if u.types:
            bits.append(": " + ", ".join(fmt_qname(t) for t in u.types))
        if u.subsets:
            bits.append(":> " + ", ".join(fmt_qname(s) for s in u.subsets))
        if u.redefines:
            bits.append(":>> " + ", ".join(fmt_qname(r) for r in u.redefines))
        if u.references:
            bits.append("::> " + fmt_qname(u.references))
        if u.crosses:
            bits.append("=> " + fmt_qname(u.crosses))
        if u.multiplicity is not None:
            mult = self.multiplicity_text(u.multiplicity)
            if mult:
                bits.append(mult)
        if u.value is not None:
            bits.append(self.value_text(u.value))
        return " ".join(bits)

    def body(
        self,
        ns: M.Namespace,
        level: int,
        head: str,
        result: Expr | None = None,
        parallel: bool = False,
    ) -> None:
        opener = "parallel {" if parallel else "{"
        if not ns.members and result is None:
            self.line(level, head.rstrip() + ";")
            return
        self.line(level, f"{head.rstrip()} {opener}")
        for member in ns.members:
            self.emit(member, level + 1)
        if result is not None:
            self.line(level + 1, expr_to_text(result))
        self.line(level, "}")

    # -- statement fragments (no trailing ';') --------------------------------

    def stmt_fragment(self, el: M.Element) -> str:
        """Render an action statement without terminator (for do/entry/...)."""

        if isinstance(el, M.PerformAction):
            if el.action is not None:
                inline = el.action
                if inline.subsets and not inline.name:
                    return fmt_qname(inline.subsets[0]) + (
                        " " + self.value_text(inline.value) if inline.value else ""
                    )
                decl = self.usage_declaration(inline)
                return f"action {decl}" if decl else "action"
            return fmt_qname(el.target or "")
        if isinstance(el, M.AssignmentAction):
            name = f"action {fmt_name(el.name)} " if el.name else ""
            return f"{name}assign {fmt_qname(el.target)} := {expr_to_text(el.expr)}"
        if isinstance(el, M.SendAction):
            name = f"action {fmt_name(el.name)} " if el.name else ""
            text = f"{name}send {expr_to_text(el.payload)}"
            if el.via is not None:
                text += f" via {expr_to_text(el.via)}"
            if el.to is not None:
                text += f" to {expr_to_text(el.to)}"
            return text
        if isinstance(el, M.AcceptAction):
            name = f"action {fmt_name(el.name)} " if el.name else ""
            return f"{name}accept {self.accept_fragment(el)}"
        raise TypeError(f"not a statement fragment: {el!r}")

    def accept_fragment(self, el: M.AcceptAction) -> str:
        bits = []
        if el.payload_name:
            bits.append(fmt_name(el.payload_name))
        if el.payload_types:
            joined = ", ".join(fmt_qname(t) for t in el.payload_types)
            bits.append(f": {joined}" if el.payload_name else joined)
        if el.trigger_kind and el.trigger is not None:
            bits.append(f"{el.trigger_kind} {expr_to_text(el.trigger)}")
        if el.via is not None:
            bits.append(f"via {expr_to_text(el.via)}")
        return " ".join(bits)

    # -- dispatch ---------------------------------------------------------------

    def emit(self, el: M.Element, level: int) -> None:
        handler = find_emitter(self, el)
        if handler is None:
            raise TypeError(f"no printer for {type(el).__name__}")
        handler(el, level)

    def emit_Unsupported(self, el: M.Unsupported, level: int) -> None:
        self.line(level, el.text)

    def emit_Package(self, el: M.Package, level: int) -> None:
        head = self.prefix(el)
        if el.is_standard:
            head += "standard "
        if el.is_library:
            head += "library "
        head += f"package {self.names(el)}"
        self.body(el, level, head)

    def emit_Import(self, el: M.Import, level: int) -> None:
        target = fmt_qname(el.target)
        if el.is_namespace:
            target += "::*"
        if el.is_recursive:
            target += "::**"
        for filter_expr in el.filters:
            target += f"[{expr_to_text(filter_expr)}]"
        allkw = "all " if el.is_import_all else ""
        self.line(level, f"{self.prefix(el)}import {allkw}{target};")

    def emit_ElementFilter(self, el: M.ElementFilter, level: int) -> None:
        self.line(level, f"{self.prefix(el)}filter {expr_to_text(el.condition)};")

    def emit_Expose(self, el: M.Expose, level: int) -> None:
        target = fmt_qname(el.target)
        if el.is_namespace:
            target += "::*"
        if el.is_recursive:
            target += "::**"
        for filter_expr in el.filters:
            target += f"[{expr_to_text(filter_expr)}]"
        self.line(level, f"expose {target};")

    def emit_MetadataUsage(self, el: M.MetadataUsage, level: int) -> None:
        head = self.prefix(el) + self.metadata(el) + "@"
        names = self.names(el)
        if names:
            head += f" {names} : "
        head += fmt_qname(el.typed_by)
        if el.about:
            head += " about " + ", ".join(fmt_qname(a) for a in el.about)
        self.body(el, level, head)

    def emit_MetadataValue(self, el: M.MetadataValue, level: int) -> None:
        head = fmt_qname(el.redefines)
        if el.value is not None:
            head += f" {self.value_text(el.value)}"
        if not el.nested:
            self.line(level, head + ";")
            return
        self.line(level, head + " {")
        for nested in el.nested:
            self.emit_MetadataValue(nested, level + 1)
        self.line(level, "}")

    def emit_Alias(self, el: M.Alias, level: int) -> None:
        self.line(level, f"{self.prefix(el)}alias {self.names(el)} for {fmt_qname(el.target)};")

    def emit_Comment(self, el: M.Comment, level: int) -> None:
        head = ""
        if el.name or el.short_name or el.about:
            head = "comment"
            names = self.names(el)
            if names:
                head += f" {names}"
            if el.about:
                head += " about " + ", ".join(fmt_qname(a) for a in el.about)
        if el.locale:
            head += f' locale "{el.locale}"'
        if head:
            self.line(level, head.strip())
        self.line(level, el.body)

    def emit_Documentation(self, el: M.Documentation, level: int) -> None:
        head = "doc"
        names = self.names(el)
        if names:
            head += f" {names}"
        if el.locale:
            head += f' locale "{el.locale}"'
        self.line(level, head)
        # multi-line bodies are re-rendered in the canonical form (a
        # verbatim echo would re-absorb this printer's indentation on
        # every parse/print cycle and never reach a fixpoint)
        body = doc_comment_body(el.text) if "\n" in el.body else el.body
        self.line(level, body)

    def emit_TextualRepresentation(self, el: M.TextualRepresentation, level: int) -> None:
        head = ""
        if el.name or el.short_name:
            head = f"rep {self.names(el)} "
        self.line(level, f'{head}language "{el.language}"')
        self.line(level, el.body)

    def emit_Dependency(self, el: M.Dependency, level: int) -> None:
        head = f"{self.prefix(el)}{self.metadata(el)}dependency "
        names = self.names(el)
        if names:
            head += f"{names} from "
        head += ", ".join(fmt_qname(c) for c in el.clients)
        head += " to " + ", ".join(fmt_qname(s) for s in el.suppliers)
        self.line(level, head + ";")

    # -- definitions ---------------------------------------------------------

    def emit_Definition(self, el: M.Definition, level: int) -> None:
        head = self.prefix(el)
        if el.is_abstract:
            head += "abstract "
        if el.is_variation:
            head += "variation "
        if el.is_individual:
            head += "individual "
        head += self.metadata(el)
        keyword = _KIND_KEYWORDS.get(el.kind, el.kind)
        if el.kind in ("individual", "extended"):
            head += "def"
        else:
            head += f"{keyword} def"
        names = self.names(el)
        if names:
            head += f" {names}"
        if el.supers:
            head += " :> " + ", ".join(fmt_qname(s) for s in el.supers)
        self.body(el, level, head, result=el.result, parallel=el.is_parallel)

    def emit_EnumerationDefinition(self, el: M.EnumerationDefinition, level: int) -> None:
        self.emit_Definition(el, level)

    def emit_Model(self, el: M.Model, level: int) -> None:
        for member in el.members:
            self.emit(member, level)

    # -- usages ----------------------------------------------------------------

    def _usage_head(self, el: M.Usage) -> str:
        head = self.prefix(el)
        if el.is_variant:
            head += "variant "
        if el.direction and el.direction != "return":
            head += f"{el.direction} "
        if el.direction == "return":
            head += "return "
        if el.is_derived:
            head += "derived "
        if el.is_abstract:
            head += "abstract "
        if el.is_variation:
            head += "variation "
        if el.is_readonly:
            head += "constant "
        if el.is_end:
            head += "end "
        # 'individual' / portion-kind keywords double as usage kinds for the
        # bare forms ('individual car1;', 'snapshot carNow;'); those kinds are
        # emitted as the keyword itself in emit_Usage, so skip the prefix here.
        if el.is_individual and el.kind not in ("individual", "snapshot", "timeslice"):
            head += "individual "
        if el.portion_kind and el.portion_kind != el.kind:
            head += f"{el.portion_kind} "
        head += self.metadata(el)
        return head

    def emit_Usage(self, el: M.Usage, level: int) -> None:
        head = self._usage_head(el)

        if el.kind == "constraint" and el.constraint_kind:
            kw = {"assert": "assert", "assume": "assume", "require": "require"}[el.constraint_kind]
            head += kw + " "
            if el.constraint_kind == "assert" and el.is_negated:
                head += "not "
            reference_form = el.subsets and not el.name and not el.short_name and not el.types
            if reference_form:
                ref = fmt_qname(el.subsets[0])
                probe = M.Usage(
                    kind=el.kind,
                    subsets=el.subsets[1:],
                    redefines=el.redefines,
                    types=[],
                    multiplicity=el.multiplicity,
                    value=el.value,
                )
                rest = self.usage_declaration(probe)
                text = f"{head}{ref}" + (f" {rest}" if rest else "")
                self.body(el, level, text, result=el.result)
                return
            head += "constraint"
        elif el.kind == "state" and el.is_exhibit:
            head += "exhibit"
            if el.name or el.short_name or el.types or not el.subsets:
                head += " state"
            else:
                ref = fmt_qname(el.subsets[0])
                text = f"{head} {ref}"
                if el.value is not None:
                    text += f" {self.value_text(el.value)}"
                self.body(el, level, text, parallel=el.is_parallel)
                return
        elif el.kind == "event" and el.subsets and not el.name:
            ref = fmt_qname(el.subsets[0])
            self.body(el, level, f"{head}event {ref}")
            return
        elif el.kind == "ref" and el.is_variant and el.subsets and not el.name:
            # variant reference: 'variant <ref>;' with optional feature
            # specializations ('variant steel : SteelWheel;')
            probe = M.Usage(
                kind=el.kind,
                types=el.types,
                subsets=el.subsets[1:],
                redefines=el.redefines,
                references=el.references,
                crosses=el.crosses,
            )
            rest = self.usage_declaration(probe)
            text = f"{head}{fmt_qname(el.subsets[0])}"
            if rest:
                text += f" {rest}"
            self.body(el, level, text)
            return
        elif el.kind in _REF_OR_INLINE_KINDS:
            self._emit_ref_or_inline(el, head, level)
            return
        else:
            keyword = _KIND_KEYWORDS.get(el.kind, el.kind)
            if el.is_individual and el.kind in ("snapshot", "timeslice"):
                keyword = f"individual {keyword}"
            if el.kind == "ref" and el.is_ref:
                keyword = "ref"
            elif el.is_ref:
                keyword = f"ref {keyword}" if keyword else "ref"
            if keyword:
                head += keyword

        decl = self.usage_declaration(el)
        head = head.rstrip()
        text = f"{head} {decl}".strip() if decl else head
        parallel = el.is_parallel if el.kind == "state" else False
        self.body(el, level, text, result=el.result, parallel=parallel)

    def _emit_ref_or_inline(self, el: M.Usage, head: str, level: int) -> None:
        """``render X;`` (reference form) vs ``render rendering x : R;``."""

        keyword, inline_keyword = _REF_OR_INLINE_KINDS[el.kind]
        head += keyword
        if el.subsets and not el.name and not el.short_name and not el.types:
            probe = M.Usage(
                kind=el.kind,
                subsets=el.subsets[1:],
                redefines=el.redefines,
                multiplicity=el.multiplicity,
                value=el.value,
            )
            rest = self.usage_declaration(probe)
            text = f"{head} {fmt_qname(el.subsets[0])}"
            if rest:
                text += f" {rest}"
        else:
            decl = self.usage_declaration(el)
            text = f"{head} {inline_keyword} {decl}".rstrip()
        self.body(el, level, text, result=el.result)

    def emit_ConnectionUsage(self, el: M.ConnectionUsage, level: int) -> None:
        head = self._usage_head(el)
        decl = self.usage_declaration(el)
        if el.name or el.types or el.value or not el.ends:
            head += "connection"
            if decl:
                head += f" {decl}"
            if el.ends:
                head += " connect "
        elif el.ends:
            head += "connect "
        if el.ends:
            if len(el.ends) == 2:
                head += f"{self._end(el.ends[0])} to {self._end(el.ends[1])}"
            else:
                head += "(" + ", ".join(self._end(e) for e in el.ends) + ")"
        self.body(el, level, head)

    def _end(self, end: M.ConnectorEnd) -> str:
        if end.name:
            return f"{fmt_name(end.name)} ::> {fmt_qname(end.target)}"
        return fmt_qname(end.target)

    def emit_BindingConnector(self, el: M.BindingConnector, level: int) -> None:
        head = self._usage_head(el)
        if el.name or el.short_name:
            head += f"binding {self.names(el)} "
        head += (
            f"bind {self._end(el.source_end or M.ConnectorEnd())} "
            f"= {self._end(el.target_end or M.ConnectorEnd())}"
        )
        self.body(el, level, head)

    def emit_SatisfyUsage(self, el: M.SatisfyUsage, level: int) -> None:
        head = self._usage_head(el)
        if el.is_assert:
            head += "assert "
        if el.is_negated:
            head += "not "
        head += "satisfy"
        if el.subsets and not el.name and not el.short_name and not el.types:
            head += f" {fmt_qname(el.subsets[0])}"
            if el.value is not None:
                head += f" {self.value_text(el.value)}"
        else:
            head += f" requirement {self.usage_declaration(el)}"
        if el.by:
            head += f" by {fmt_qname(el.by)}"
        self.body(el, level, head)

    def emit_InterfaceUsage(self, el: M.InterfaceUsage, level: int) -> None:
        head = self._usage_head(el) + "interface"
        decl = self.usage_declaration(el)
        if decl:
            head += f" {decl}"
            if el.ends:
                head += " connect "
        elif el.ends:
            head += " "
        head += self._ends_text(el.ends)
        self.body(el, level, head)

    def emit_AllocationUsage(self, el: M.AllocationUsage, level: int) -> None:
        head = self._usage_head(el)
        decl = self.usage_declaration(el)
        if decl:
            head += f"allocation {decl}"
            if el.ends:
                head += " allocate "
        else:
            head += "allocate "
        head += self._ends_text(el.ends)
        self.body(el, level, head)

    def _ends_text(self, ends: list[M.ConnectorEnd]) -> str:
        if not ends:
            return ""
        if len(ends) == 2:
            return f"{self._end(ends[0])} to {self._end(ends[1])}"
        return "(" + ", ".join(self._end(e) for e in ends) + ")"

    def emit_FlowUsage(self, el: M.FlowUsage, level: int) -> None:
        head = self._usage_head(el)
        if el.is_succession:
            head += "succession "
        head += "message" if el.kind == "message" else "flow"
        decl = self.usage_declaration(el)
        declared = bool(decl or el.payload)
        if decl:
            head += f" {decl}"
        if el.payload:
            head += f" of {el.payload}"
        if el.source and el.target_end:
            if declared:
                head += f" from {fmt_qname(el.source)} to {fmt_qname(el.target_end)}"
            else:
                head += f" {fmt_qname(el.source)} to {fmt_qname(el.target_end)}"
        self.body(el, level, head)

    # -- action statements ----------------------------------------------------

    def emit_AssignmentAction(self, el: M.AssignmentAction, level: int) -> None:
        self.line(level, self.stmt_fragment(el) + ";")

    def emit_SendAction(self, el: M.SendAction, level: int) -> None:
        self.line(level, self.stmt_fragment(el) + ";")

    def emit_AcceptAction(self, el: M.AcceptAction, level: int) -> None:
        self.line(level, self.stmt_fragment(el) + ";")

    def emit_PerformAction(self, el: M.PerformAction, level: int) -> None:
        if el.action is not None:
            inline = el.action
            head = "perform "
            if inline.subsets and not inline.name:
                head += fmt_qname(inline.subsets[0])
                if inline.value is not None:
                    head += f" {self.value_text(inline.value)}"
            else:
                head += "action"
                decl = self.usage_declaration(inline)
                if decl:
                    head += f" {decl}"
            self.body(inline, level, head)
            return
        self.line(level, f"perform {fmt_qname(el.target or '')};")

    def emit_TerminateAction(self, el: M.TerminateAction, level: int) -> None:
        if el.target is not None:
            self.line(level, f"terminate {expr_to_text(el.target)};")
        else:
            self.line(level, "terminate;")

    def emit_ControlNode(self, el: M.ControlNode, level: int) -> None:
        name = self.names(el)
        kw = _CONTROL_KEYWORDS[el.kind]
        self.line(level, f"{kw} {name};" if name else f"{kw};")

    def emit_InitialNode(self, el: M.InitialNode, level: int) -> None:
        self.line(level, f"first {fmt_qname(el.target)};")

    def emit_Succession(self, el: M.Succession, level: int) -> None:
        if el.is_else:
            self.line(level, f"else {fmt_qname(el.target)};")
            return
        head = ""
        if el.name or el.short_name:
            head += f"succession {self.names(el)} "
        if el.source:
            head += f"first {fmt_qname(el.source)} "
        if el.guard is not None:
            head += f"if {expr_to_text(el.guard)} "
        head += f"then {fmt_qname(el.target)};"
        self.line(level, head)

    def emit_IfAction(self, el: M.IfAction, level: int) -> None:
        self._if_line(el, level, "if")

    def _if_line(self, el: M.IfAction, level: int, keyword: str) -> None:
        self.line(level, f"{keyword} {expr_to_text(el.condition)} {{")
        for item in el.then_body:
            self.emit(item, level + 1)
        if el.else_body is None:
            self.line(level, "}")
            return
        if isinstance(el.else_body, M.IfAction):
            self.line(level, "} else")
            self._if_line(el.else_body, level, "if")
            return
        self.line(level, "} else {")
        for item in el.else_body:
            self.emit(item, level + 1)
        self.line(level, "}")

    def emit_WhileLoop(self, el: M.WhileLoop, level: int) -> None:
        if el.condition is not None:
            self.line(level, f"while {expr_to_text(el.condition)} {{")
        else:
            self.line(level, "loop {")
        for item in el.body:
            self.emit(item, level + 1)
        if el.until is not None:
            self.line(level, f"}} until {expr_to_text(el.until)};")
        else:
            self.line(level, "}")

    def emit_ForLoop(self, el: M.ForLoop, level: int) -> None:
        self.line(level, f"for {fmt_name(el.var)} in {expr_to_text(el.seq)} {{")
        for item in el.body:
            self.emit(item, level + 1)
        self.line(level, "}")

    # -- states -----------------------------------------------------------------

    def emit_StateAction(self, el: M.StateAction, level: int) -> None:
        if el.action is None:
            self.line(level, f"{el.kind};")
            return
        head = f"{el.kind} {self.stmt_fragment(el.action)}"
        inline = el.action.action if isinstance(el.action, M.PerformAction) else None
        if inline is not None and inline.members:
            # inline action with a body: 'entry action step { in n : Real; }'
            self.body(inline, level, head)
            return
        self.line(level, head + ";")

    def emit_TransitionUsage(self, el: M.TransitionUsage, level: int) -> None:
        if el.source == M.ENTRY_SOURCE:
            head = ""
            if el.guard is not None:
                head += f"if {expr_to_text(el.guard)} "
            self.line(level, head + f"then {fmt_qname(el.target)};")
            return
        head = "transition "
        names = self.names(el)
        if names:
            head += f"{names} "
        head += f"first {fmt_qname(el.source or '')}"
        if el.trigger is not None:
            head += f" accept {self.accept_fragment(el.trigger)}"
        if el.guard is not None:
            head += f" if {expr_to_text(el.guard)}"
        if el.effect is not None:
            head += f" do {self.stmt_fragment(el.effect)}"
        head += f" then {fmt_qname(el.target)};"
        self.line(level, head)
