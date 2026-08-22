"""Best-effort projection of a SysML model onto KerML textual notation.

SysML v2 is defined as an extension of KerML: every SysML definition kind
maps to a kernel metatype (``part def`` -> ``struct``, ``calc def`` ->
``function``, ``constraint`` -> ``inv``/``predicate``, ...).  ``to_kerml``
renders that projection for the *structural* subset of a model.  It is
one-way and lossy: behavioral statements (assignments, control flow,
transitions), connections, views, and metadata have no kernel-level textual
equivalent here and are emitted as ``/* omitted: ... */`` comments.

The output is guaranteed parseable by the bundled KerML grammar (this is
enforced by the test suite).
"""

from __future__ import annotations

from . import model as M
from .ast import expr_to_text
from .export import find_emitter, fmt_name, fmt_qname, indent_string

#: SysML definition kind -> KerML classifier keyword
_DEF_KEYWORDS: dict[str, str] = {
    "part": "struct",
    "item": "struct",
    "occurrence": "class",
    "individual": "struct",
    "attribute": "datatype",
    "enum": "datatype",
    "port": "struct",
    "connection": "assoc struct",
    "interface": "assoc struct",
    "allocation": "assoc",
    "flow": "interaction",
    "action": "behavior",
    "state": "behavior",
    "case": "behavior",
    "analysis": "behavior",
    "verification": "behavior",
    "use_case": "behavior",
    "calc": "function",
    "constraint": "predicate",
    "requirement": "predicate",
    "concern": "predicate",
    "viewpoint": "predicate",
    "view": "struct",
    "rendering": "struct",
    "metadata": "metaclass",
    "extended": "classifier",
}

#: usage kinds projected as plain kernel features
_FEATURE_KINDS = frozenset(
    "part item attribute port ref feature enum enum_literal occurrence "
    "individual snapshot timeslice event event_occurrence subject actor "
    "stakeholder extended".split()
)

#: usage kinds projected as steps (behavioral features)
_STEP_KINDS = frozenset("action calc state case analysis verification use_case".split())


def to_kerml(element: M.Element, indent: int | str = 4) -> str:
    """Render a model element as KerML textual notation (see module doc).

    ``indent`` is a number of spaces (or, for back-compat, a literal
    indentation string).
    """

    printer = _KerMLPrinter(indent_string(indent))
    if isinstance(element, M.Model):
        for member in element.members:
            printer.emit(member, 0)
    else:
        printer.emit(element, 0)
    return "\n".join(printer.lines) + "\n"


class _KerMLPrinter:
    def __init__(self, indent: str):
        self.indent = indent
        self.lines: list[str] = []
        #: True while emitting members of a 'function'/'predicate' body,
        #: where 'return' members and bare result expressions are legal
        self._function_body = False

    def line(self, level: int, text: str) -> None:
        for piece in text.split("\n"):
            self.lines.append(self.indent * level + piece if piece else "")

    def omitted(self, level: int, what: str) -> None:
        self.line(level, f"/* omitted (no KerML projection): {what} */")

    # -- shared fragments ----------------------------------------------------

    def names(self, el: M.Element) -> str:
        bits = []
        if el.short_name:
            bits.append(f"<{fmt_name(el.short_name)}>")
        if el.name:
            bits.append(fmt_name(el.name))
        return " ".join(bits)

    def prefix(self, el: M.Element) -> str:
        return f"{el.visibility} " if el.visibility else ""

    def body(
        self,
        members: list[M.Element],
        level: int,
        head: str,
        result=None,
        result_as_expr: bool = False,
        function_body: bool = False,
    ) -> None:
        if not members and result is None:
            self.line(level, head.rstrip() + ";")
            return
        self.line(level, f"{head.rstrip()} {{")
        enclosing = self._function_body
        self._function_body = function_body
        try:
            for member in members:
                self.emit(member, level + 1)
        finally:
            self._function_body = enclosing
        if result is not None:
            text = expr_to_text(result)
            # A bare result expression is only legal in a *function* body
            # ('function'/'predicate'/'expr'); type bodies ('behavior',
            # 'step') carry it as an owned expression feature instead.
            self.line(level + 1, f"expr {{ {text} }}" if result_as_expr else text)
        self.line(level, "}")

    # -- dispatch ----------------------------------------------------------------

    def emit(self, el: M.Element, level: int) -> None:
        # Same handler-per-class dispatch as export._Printer (most specific
        # class along the MRO wins); the projection is best-effort, so an
        # element without a handler is emitted as an omission comment
        # rather than raising.
        handler = find_emitter(self, el)
        if handler is None:
            self.omitted(level, type(el).__name__)
            return
        handler(el, level)

    def emit_Package(self, el: M.Package, level: int) -> None:
        head = self.prefix(el)
        if el.is_standard:
            head += "standard "
        if el.is_library:
            head += "library "
        head += f"package {self.names(el)}"
        self.body(el.members, level, head)

    def emit_Import(self, el: M.Import, level: int) -> None:
        target = fmt_qname(el.target)
        if el.is_namespace:
            target += "::*"
        if el.is_recursive:
            target += "::**"
        self.line(level, f"{self.prefix(el)}import {target};")

    def emit_Alias(self, el: M.Alias, level: int) -> None:
        self.line(level, f"{self.prefix(el)}alias {self.names(el)} for {fmt_qname(el.target)};")

    def emit_Documentation(self, el: M.Documentation, level: int) -> None:
        self.line(level, f"doc {el.body}")

    def emit_Comment(self, el: M.Comment, level: int) -> None:
        self.line(level, el.body)

    def emit_Dependency(self, el: M.Dependency, level: int) -> None:
        head = f"{self.prefix(el)}dependency "
        names = self.names(el)
        if names:
            head += f"{names} from "
        head += ", ".join(fmt_qname(c) for c in el.clients)
        head += " to " + ", ".join(fmt_qname(s) for s in el.suppliers)
        self.line(level, head + ";")

    def emit_Definition(self, el: M.Definition, level: int) -> None:
        self._definition(el, level)

    def emit_Usage(self, el: M.Usage, level: int) -> None:
        self._usage(el, level)

    def emit_Unsupported(self, el: M.Unsupported, level: int) -> None:
        self.omitted(level, el.rule or "unsupported element")

    def _definition(self, el: M.Definition, level: int) -> None:
        keyword = _DEF_KEYWORDS.get(el.kind, "classifier")
        head = self.prefix(el)
        if el.is_abstract:
            head += "abstract "
        head += f"{keyword} {self.names(el)}".rstrip()
        if el.supers:
            head += " specializes " + ", ".join(fmt_qname(s) for s in el.supers)
        if el.kind in ("calc", "constraint", "requirement", "concern", "viewpoint"):
            # keyword is 'function'/'predicate': a function body may end with
            # a bare result expression
            self.body(el.members, level, head, result=el.result, function_body=True)
        elif el.kind in ("case", "analysis", "verification", "use_case"):
            # keyword is 'behavior': a type body cannot end with a bare
            # result expression, so wrap it as an expression feature
            self.body(el.members, level, head, result=el.result, result_as_expr=True)
        else:
            self.body(el.members, level, head)

    def _usage(self, el: M.Usage, level: int) -> None:
        if el.kind == "constraint":
            self._invariant(el, level)
            return
        if el.kind in _STEP_KINDS:
            head = self.prefix(el) + self._direction(el) + "step"
            decl = self._feature_declaration(el)
            if decl:
                head += f" {decl}"
            # steps have a *type* body, so any result expression must be
            # wrapped as an expression feature to stay parseable
            self.body(el.members, level, head, result=el.result, result_as_expr=True)
            return
        if el.kind not in _FEATURE_KINDS:
            self.omitted(level, f"{el.kind} usage" + (f" '{el.name}'" if el.name else ""))
            return
        head = self.prefix(el) + self._direction(el)
        if el.is_derived:
            head += "derived "
        if el.is_abstract:
            head += "abstract "
        if el.is_readonly:
            head += "const "
        if el.is_end:
            head += "end "
        head += "feature"
        decl = self._feature_declaration(el)
        if decl:
            head += f" {decl}"
        self.body(el.members, level, head)

    def _direction(self, el: M.Usage) -> str:
        if el.direction == "return":
            # 'return' members are function-body syntax; type bodies
            # ('behavior', 'step', ...) carry results as output parameters
            return "return " if self._function_body else "out "
        return f"{el.direction} " if el.direction else ""

    def _feature_declaration(self, el: M.Usage) -> str:
        bits = []
        names = self.names(el)
        if names:
            bits.append(names)
        if el.types:
            types = [t for t in el.types if not t.startswith("~")]
            if types:
                bits.append(": " + ", ".join(fmt_qname(t) for t in types))
        if el.subsets:
            bits.append(":> " + ", ".join(fmt_qname(s) for s in el.subsets))
        if el.redefines:
            bits.append(":>> " + ", ".join(fmt_qname(r) for r in el.redefines))
        if el.multiplicity is not None:
            if el.multiplicity.lower is not None and el.multiplicity.upper is not None:
                bits.append(
                    f"[{expr_to_text(el.multiplicity.lower)}.."
                    f"{expr_to_text(el.multiplicity.upper)}]"
                )
            elif el.multiplicity.upper is not None:
                bits.append(f"[{expr_to_text(el.multiplicity.upper)}]")
            if el.multiplicity.is_ordered:
                bits.append("ordered")
            if el.multiplicity.is_nonunique:
                bits.append("nonunique")
        if el.value is not None:
            op = ":=" if el.value.is_initial else "="
            if el.value.is_default:
                op = f"default {op}"
            bits.append(f"{op} {expr_to_text(el.value.expr)}")
        return " ".join(bits)

    def _invariant(self, el: M.Usage, level: int) -> None:
        head = self.prefix(el) + "inv"
        if el.is_negated:
            head += " false"
        names = self.names(el)
        if names:
            head += f" {names}"
        expr = el.result
        if expr is None and el.value is not None:
            expr = el.value.expr
        if expr is None:
            ref = fmt_qname(el.subsets[0]) if el.subsets else "true"
            self.line(level, f"{head} {{ {ref} }}")
            return
        self.line(level, f"{head} {{ {expr_to_text(expr)} }}")
