"""A deterministic retrieval substrate for LLM/RAG pipelines (stdlib only).

This module carries **no** LLM, embedding, or vendor dependencies: it turns
a model into stable, re-parseable textual chunks that an embedding index, a
keyword search, or an agent's context window can consume -- and is useful
without any of them via :func:`search`.

* :func:`model_chunks` -- deterministic chunking: one chunk per package,
  definition, and package-level usage, each re-printed as valid SysML v2
  text by the existing exporter (:func:`longeron.to_sysml`), with a stable
  qualified-name ``id``, an ancestry breadcrumb, outgoing references, and
  doc text.  Same model in, byte-identical chunks out -- so embedding
  caches keyed on ``(id, text)`` stay warm across runs.
* :func:`neighborhood` -- graph-RAG helper: the chunks of an element's
  semantic neighborhood (specializations, types, members, incoming and
  outgoing references), breadth-first by hop count.
* :func:`search` -- an embedding-free fallback: TF-IDF-style token scoring
  (camelCase-aware, stdlib ``math`` only) over the chunks.

The intended LLM workflow is retrieval -> **cite qualified names** ->
resolve those names back through :class:`~longeron.interpreter.Interpreter`
for ground truth (evaluate the calc, check the constraint) instead of
trusting generated text -- the chunks exist to get the right element names
into the conversation, not to replace execution.
"""

from __future__ import annotations

import math
import re
from typing import TypedDict

from . import model as M
from .ast import (
    AllOf,
    ArrowOp,
    Cast,
    Classification,
    Constructor,
    Expr,
    FeatureRef,
    Invocation,
    MetadataAccess,
)
from .errors import SysMLError
from .export import to_sysml
from .interpreter import Resolver


class Chunk(TypedDict):
    """One retrievable unit of a model."""

    id: str  # stable qualified name (synthesized for anonymous elements)
    kind: str  # human keyword: 'part def', 'calc def', 'package', ...
    text: str  # the element re-printed as SysML v2 text
    context: str  # one-line ancestry breadcrumb
    refs: list[str]  # outgoing referenced qualified names (document order)
    doc: str | None  # doc comment text, if any


class SearchResult(TypedDict):
    """A scored :func:`search` hit."""

    score: float
    chunk: Chunk


#: default chunk-size budget, in characters of printed SysML text
MAX_CHARS = 4000


def model_chunks(model: M.Model, *, max_chars: int = MAX_CHARS) -> list[Chunk]:
    """Deterministic retrieval chunks for a model, in document order.

    Chunk units are packages, definitions, and package-level usages.
    Packages chunk *shallow* (declaration, doc, imports -- their
    definitions are chunks of their own, so no text is duplicated).  A
    definition whose printed text exceeds ``max_chars`` also chunks
    shallow, and its named nested members become chunks of their own
    (best-effort: a single oversized leaf is emitted whole rather than
    dropped).  Ids, ordering, and text are stable across runs.
    """

    return _Chunker(model, max_chars).run()


def neighborhood(
    model: M.Model, qname: str, hops: int = 1, *, max_chars: int = MAX_CHARS
) -> list[Chunk]:
    """The chunks of an element's semantic neighborhood.

    Starting from the chunk containing ``qname``, follows outgoing
    references (typing, specialization, subsetting, values), incoming
    references (who mentions me), and ownership (members and owner) for
    ``hops`` steps.  The seed chunk comes first; the rest follow in
    (distance, document order).
    """

    chunks = model_chunks(model, max_chars=max_chars)
    position = {chunk["id"]: index for index, chunk in enumerate(chunks)}
    seed = _enclosing_chunk_id(model, qname, position)
    if seed is None:
        raise SysMLError(f"no chunk contains {qname!r}")
    forward: dict[str, set[str]] = {chunk["id"]: set() for chunk in chunks}
    backward: dict[str, set[str]] = {chunk["id"]: set() for chunk in chunks}
    for chunk in chunks:
        cid = chunk["id"]
        targets = {_resolve_to_chunk(ref, position) for ref in chunk["refs"]}
        targets.add(_parent_chunk_id(cid, position))  # ownership: owner ...
        for other in position:  # ... and members
            if other != cid and _parent_chunk_id(other, position) == cid:
                targets.add(other)
        for target in targets:
            if target is None or target == cid:
                continue
            forward[cid].add(target)
            backward[target].add(cid)
    distance = {seed: 0}
    frontier = [seed]
    for hop in range(1, hops + 1):
        next_frontier = []
        for cid in frontier:
            for neighbor in sorted(forward[cid] | backward[cid], key=position.__getitem__):
                if neighbor not in distance:
                    distance[neighbor] = hop
                    next_frontier.append(neighbor)
        frontier = next_frontier
    by_id = {chunk["id"]: chunk for chunk in chunks}
    order = sorted(distance, key=lambda cid: (distance[cid], position[cid]))
    return [by_id[cid] for cid in order]


def search(
    model: M.Model | list[Chunk],
    terms: str | list[str],
    *,
    limit: int = 10,
    max_chars: int = MAX_CHARS,
) -> list[SearchResult]:
    """Embedding-free keyword retrieval over the model's chunks.

    ``terms`` is a query string (split on whitespace) or a list of terms.
    Scoring is TF-IDF-style token overlap -- camelCase-aware, so
    ``"station"`` matches ``stationMinutes`` -- with name and doc tokens
    weighted above body text.  Returns the ``limit`` best chunks with
    positive scores, ties broken by document order.
    """

    chunks = model if isinstance(model, list) else model_chunks(model, max_chars=max_chars)
    query = [t.lower() for t in (terms.split() if isinstance(terms, str) else list(terms))]
    fields = [
        (
            _tokens(chunk["id"]) + _tokens(chunk["kind"]),  # names
            _tokens(chunk["doc"] or ""),  # documentation
            _tokens(chunk["text"]),  # printed body
        )
        for chunk in chunks
    ]
    total = len(chunks) or 1
    frequency: dict[str, int] = {}
    for name_tokens, doc_tokens, text_tokens in fields:
        for token in set(name_tokens) | set(doc_tokens) | set(text_tokens):
            frequency[token] = frequency.get(token, 0) + 1
    results: list[SearchResult] = []
    for chunk, (name_tokens, doc_tokens, text_tokens) in zip(chunks, fields, strict=True):
        score = 0.0
        for term in query:
            weight = (
                3.0 * name_tokens.count(term)
                + 2.0 * doc_tokens.count(term)
                + 1.0 * text_tokens.count(term)
            )
            if weight:
                score += weight * math.log(1.0 + total / frequency.get(term, 1))
        if score > 0.0:
            length = len(name_tokens) + len(doc_tokens) + len(text_tokens)
            results.append({"score": score / (1.0 + math.log(1.0 + length)), "chunk": chunk})
    results.sort(key=lambda result: -result["score"])
    return results[:limit]


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

_KIND_WORDS = {"use_case": "use case", "enum_literal": "enum literal", "feature": "feature"}

#: usage kinds whose textual form only parses inside their owner (a bare
#: ``subject``/``require constraint``/``variant`` is not a root element),
#: so they always stay inline in the owning chunk
_CONTEXT_BOUND_KINDS = frozenset(
    {
        "subject",
        "actor",
        "stakeholder",
        "objective",
        "constraint",
        "satisfy",
        "verify",
        "frame",
        "include",
        "enum_literal",
    }
)


def _kind_word(element: M.Element) -> str:
    if isinstance(element, M.Package):
        return "package"
    if isinstance(element, M.Definition):
        keyword = _KIND_WORDS.get(element.kind, element.kind)
        return f"{keyword} def"
    if isinstance(element, M.Usage):
        return _KIND_WORDS.get(element.kind, element.kind)
    return type(element).__name__.lower()


class _Chunker:
    def __init__(self, model: M.Model, max_chars: int):
        self.model = model
        self.max_chars = max_chars
        self.resolver = Resolver(model)
        self.chunks: list[Chunk] = []

    def run(self) -> list[Chunk]:
        for member in self.model.members:
            self.visit(member, breadcrumb=[])
        return self.chunks

    def visit(self, element: M.Element, breadcrumb: list[str]) -> None:
        if not self.is_unit(element):
            return
        trail = [*breadcrumb, f"{_kind_word(element)} {element.label}"]
        assert isinstance(element, M.Namespace)
        if isinstance(element, M.Package):
            self.emit(element, breadcrumb, shallow=True)
            self.descend(element, trail)
            return
        text = to_sysml(element)
        if len(text) <= self.max_chars or not any(map(self.is_unit, element.members)):
            self.emit(element, breadcrumb, shallow=False, text=text)
            return
        self.emit(element, breadcrumb, shallow=True)  # oversized: split
        self.descend(element, trail)

    def descend(self, namespace: M.Namespace, trail: list[str]) -> None:
        for member in namespace.members:
            self.visit(member, trail)

    def is_unit(self, element: M.Element) -> bool:
        """Chunk units: packages, definitions, and *named* non-parameter
        usages.  Anonymous members and in/out/return parameters always
        stay inline in their owner's chunk (a calc's signature and result
        expression are meaningless apart)."""

        if isinstance(element, (M.Package, M.Definition)):
            return True
        return (
            isinstance(element, M.Usage)
            and bool(element.name or element.short_name)
            and element.direction is None
            and element.kind not in _CONTEXT_BOUND_KINDS
            and not element.is_variant
        )

    def emit(
        self,
        element: M.Namespace,
        breadcrumb: list[str],
        *,
        shallow: bool,
        text: str | None = None,
    ) -> None:
        if shallow:
            kept = [m for m in element.members if not self.is_unit(m)]
            saved = element.members
            element.members = kept
            try:
                text = to_sysml(element)
            finally:
                element.members = saved
        assert text is not None
        qname = element.qualified_name
        if qname is None:  # anonymous: synthesize a stable positional id
            owner = element.owner
            if isinstance(owner, M.Namespace):
                qname = f"{owner.qualified_name or '<root>'}::[{owner.members.index(element)}]"
            else:
                qname = "<root>::[0]"
        self.chunks.append(
            {
                "id": qname,
                "kind": _kind_word(element),
                "text": text,
                "context": " > ".join(breadcrumb),
                "refs": self.refs(element),
                "doc": element.doc,
            }
        )

    # -- outgoing references --------------------------------------------------

    def refs(self, element: M.Namespace) -> list[str]:
        """Outgoing referenced names, canonicalized where resolvable,
        internal references dropped, first-seen document order."""

        qname = element.qualified_name
        seen: set[str] = set()
        out: list[str] = []
        for name, context in _raw_refs(element):
            resolved = self.canonical(name, context)
            if qname is not None and (resolved == qname or resolved.startswith(qname + "::")):
                continue  # internal to this chunk
            if resolved not in seen:
                seen.add(resolved)
                out.append(resolved)
        return out

    def canonical(self, name: str, context: M.Element) -> str:
        try:
            target = self.resolver.resolve(name, context=context)
        except SysMLError:
            return name
        return target.qualified_name or name


def _raw_refs(element: M.Element):
    """Yield ``(referenced-name, context-element)`` pairs from an element
    subtree (types, specializations, subsets/redefines, connector ends,
    metadata, and names mentioned inside value/result expressions)."""

    for node in element.iter_tree():
        names: list[str] = list(node.metadata)
        if isinstance(node, M.Definition):
            names += node.supers
            _expr_refs(node.result, names)
        if isinstance(node, M.Usage):
            names += node.types + node.subsets + node.redefines
            names += [n for n in (node.references, node.crosses) if n]
            if node.value is not None:
                _expr_refs(node.value.expr, names)
            _expr_refs(node.result, names)
            for end in getattr(node, "ends", None) or []:
                names.append(end.target)
        if isinstance(node, M.BindingConnector):
            for end in (node.source_end, node.target_end):
                if end is not None:
                    names.append(end.target)
        if isinstance(node, M.SatisfyUsage) and node.by:
            names.append(node.by)
        if isinstance(node, M.Import):
            names.append(node.target)
        if isinstance(node, M.Alias):
            names.append(node.target)
        if isinstance(node, M.MetadataUsage):
            names.append(node.typed_by)
            names += node.about
        context = node if isinstance(node, M.Namespace) else element
        for name in names:
            yield name, context


def _expr_refs(expr: Expr | None, out: list[str]) -> None:
    """Collect qualified names mentioned by an expression tree."""

    if expr is None:
        return
    if isinstance(expr, FeatureRef):
        out.append("::".join(expr.parts))
    elif isinstance(expr, Invocation):
        out.append("::".join(expr.target))
    elif isinstance(expr, Constructor):
        out.append("::".join(expr.type))
    elif isinstance(expr, (Classification, Cast, AllOf)):
        out.append("::".join(expr.type))
    elif isinstance(expr, MetadataAccess):
        out.append("::".join(expr.target))
    elif isinstance(expr, ArrowOp) and expr.func is not None:
        out.append("::".join(expr.func))
    for value in vars(expr).values():
        if isinstance(value, Expr):
            _expr_refs(value, out)
        elif isinstance(value, tuple):
            for item in value:
                if isinstance(item, Expr):
                    _expr_refs(item, out)
                elif isinstance(item, tuple):  # ('name', expr) pairs
                    for sub in item:
                        if isinstance(sub, Expr):
                            _expr_refs(sub, out)


# ---------------------------------------------------------------------------
# Neighborhood helpers
# ---------------------------------------------------------------------------


def _enclosing_chunk_id(model: M.Model, qname: str, position: dict[str, int]) -> str | None:
    """Map a qualified name to the chunk that contains it: itself, or the
    nearest ancestor with a chunk (resolving through the model first so
    aliases and short names canonicalize)."""

    try:
        element = Resolver(model).resolve(qname)
        canonical = element.qualified_name or qname
    except SysMLError:
        canonical = qname
    return _resolve_to_chunk(canonical, position)


def _resolve_to_chunk(qname: str, position: dict[str, int]) -> str | None:
    parts = qname.split("::")
    while parts:
        candidate = "::".join(parts)
        if candidate in position:
            return candidate
        parts.pop()
    return None


def _parent_chunk_id(chunk_id: str, position: dict[str, int]) -> str | None:
    parts = chunk_id.split("::")[:-1]
    if not parts:
        return None
    return _resolve_to_chunk("::".join(parts), position)


_TOKEN = re.compile(r"[A-Za-z][a-z]*|[A-Z]+(?![a-z])|\d+")


def _tokens(text: str) -> list[str]:
    """Lowercased word tokens, splitting camelCase (``stationMinutes`` ->
    ``station``, ``minutes``) and qualified names."""

    return [match.group(0).lower() for match in _TOKEN.finditer(text)]
