"""Project a model onto RDF for SPARQL querying and linked-data interchange.

The projection turns a :class:`~longeron.model.Model` into an
`rdflib <https://rdflib.readthedocs.io>`_ ``Graph``: every element becomes a
subject, its spec metaclass becomes the ``rdf:type``, and memberships,
specialization/subsetting/redefinition/typing, and attribute *values*
(typed literals) become predicates.  Requires the ``rdf`` extra
(``pip install "longeron[rdf]"``)::

    from longeron import rdf

    graph = rdf.to_graph(model)              # rdflib.Graph
    rdf.to_turtle(model, "model.ttl")        # Turtle serialization
    rdf.to_jsonld(model)                     # JSON-LD text
    rows = rdf.sparql(model, '''
        SELECT ?def ?mass WHERE {
            ?def a sysml:PartDefinition ; sysml:ownedMember ?attr .
            ?attr sysml:name "mass" ; sysml:value ?mass .
        }''')

Vocabulary design
-----------------

*Class names derive from the OMG projection, not a parallel invention.*
``rdf:type`` uses the same spec metaclass per element ``kind`` that
:mod:`longeron.ecore` / :mod:`longeron.api` emit as ``@type`` in Systems
Modeling API records (``part def`` -> ``sysml:PartDefinition``, a
``subject`` usage -> ``sysml:ReferenceUsage``, ...), so the RDF view and
the API JSON view of one model agree on what things *are*.  Property names
likewise follow the spec's derived-property vocabulary (``ownedMember``,
``specializes``, ``subsets``, ``redefines``, ``definedBy``) rather than the
reified relationship records: RDF triples are already edges, so the
``Subclassification``/``FeatureTyping`` reification the flat API records
need is collapsed into direct predicates (the reified form stays available
via :mod:`longeron.api`).

*The namespace is this package's own, not OMG's.*  Classes and properties
live under ``https://sanbales.github.io/longeron/rdf/sysml#`` (bound to the
prefix ``sysml:``), elements under ``.../rdf/element/`` by default.  OMG has
not (yet) published an official RDF vocabulary for SysML v2; squatting on a
plausible-looking OMG IRI would be worse than owning an honest one.  When an
official vocabulary lands, the local names here -- taken verbatim from the
spec metamodel -- should map 1:1, making migration a namespace substitution
(and an ``owl:equivalentClass``/``owl:equivalentProperty`` bridge trivial to
generate).  Element IRIs are minted from qualified names
(``UavMissions::Propulsion::HoverPower`` ->
``.../element/UavMissions/Propulsion/HoverPower``, percent-encoded per
segment); anonymous elements fall back to blank nodes labeled in document
order, so a rebuilt graph is isomorphic to the last one.

Scope mirrors the :mod:`longeron.ecore` prototype: structure, names, flags,
relationships, documentation, and attribute values -- expression *trees*
are carried as rendered text (``sysml:valueExpression``), not as RDF
sub-structure.  Action/state statement bodies are not projected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from . import model as M
from .ast import Literal as LiteralExpr
from .ast import expr_to_text
from .ecore import _DEF_CLASSES, _USAGE_CLASSES
from .errors import MissingExtraError, SysMLError
from .interpreter import Interpreter, Resolver

if TYPE_CHECKING:  # pragma: no cover - typing only
    from rdflib import Graph

#: default namespace for classes and properties (prefix ``sysml``)
VOCABULARY = "https://sanbales.github.io/longeron/rdf/sysml#"
#: default namespace under which element IRIs are minted
ELEMENT_BASE = "https://sanbales.github.io/longeron/rdf/element/"

#: model classes projected as their own class name (no ``kind`` dispatch)
_DIRECT_CLASSES: dict[type, str] = {
    M.Package: "Package",
    M.Alias: "Membership",  # an aliasing membership, per the spec
    M.Dependency: "Dependency",
    M.MetadataUsage: "MetadataUsage",
}

#: usage flags emitted (only when true), spec property spelling
_FLAG_PROPERTIES: tuple[tuple[str, str], ...] = (
    ("is_abstract", "isAbstract"),
    ("is_variation", "isVariation"),
    ("is_variant", "isVariant"),
    ("is_individual", "isIndividual"),
    ("is_readonly", "isReadOnly"),
    ("is_derived", "isDerived"),
    ("is_end", "isEnd"),
    ("is_parallel", "isParallel"),
)


def _require_rdflib() -> Any:
    try:
        import rdflib
    except ImportError as exc:  # pragma: no cover - exercised without extra
        raise MissingExtraError("the RDF projection", "rdflib", "rdf") from exc
    return rdflib


def to_graph(
    model: M.Model,
    *,
    base: str = ELEMENT_BASE,
    evaluated: bool = False,
) -> Graph:
    """Project a model onto an ``rdflib.Graph``.

    ``base`` overrides the namespace under which element IRIs are minted.
    With ``evaluated=True``, attribute values that are *expressions* (not
    plain literals) are additionally evaluated by the
    :class:`~longeron.interpreter.Interpreter` per owning definition and
    emitted as ``sysml:evaluatedValue`` typed literals (best-effort:
    definitions that fail to instantiate are skipped silently).
    """

    return _Projector(model, base=base, evaluated=evaluated).project()


def to_turtle(model_or_graph: M.Model | Graph, path: Any = None, **kwargs: Any) -> str:
    """Serialize a model (or an existing graph) as Turtle; optionally write it."""

    return _serialize(model_or_graph, "turtle", path, **kwargs)


def to_jsonld(model_or_graph: M.Model | Graph, path: Any = None, **kwargs: Any) -> str:
    """Serialize a model (or an existing graph) as JSON-LD; optionally write it."""

    kwargs.setdefault("auto_compact", True)
    return _serialize(model_or_graph, "json-ld", path, **kwargs)


def sparql(model_or_graph: M.Model | Graph, query: str, **kwargs: Any) -> Any:
    """Run a SPARQL query against a model (or an existing graph).

    The prefixes ``sysml:``, ``rdf:``, ``rdfs:``, and ``xsd:`` are
    pre-bound, so queries can use them without ``PREFIX`` headers.  Returns
    the ``rdflib`` result (iterable of rows).
    """

    rdflib = _require_rdflib()
    graph = _as_graph(model_or_graph)
    namespaces = {
        "sysml": rdflib.Namespace(VOCABULARY),
        "rdf": rdflib.RDF,
        "rdfs": rdflib.RDFS,
        "xsd": rdflib.XSD,
    }
    return graph.query(query, initNs=namespaces, **kwargs)


def _as_graph(model_or_graph: M.Model | Graph) -> Graph:
    if isinstance(model_or_graph, M.Model):
        return to_graph(model_or_graph)
    return model_or_graph


def _serialize(model_or_graph: M.Model | Graph, format: str, path: Any, **kwargs: Any) -> str:
    graph = _as_graph(model_or_graph)
    text: str = graph.serialize(format=format, **kwargs)
    if path is not None:
        from pathlib import Path

        Path(path).write_text(text, encoding="utf-8")
    return text


class _Projector:
    def __init__(self, model: M.Model, *, base: str, evaluated: bool):
        rdflib = self.rdflib = _require_rdflib()
        self.model = model
        self.base = base
        self.evaluated = evaluated
        self.ns = rdflib.Namespace(VOCABULARY)
        self.resolver = Resolver(model)
        self.graph = rdflib.Graph()
        self.graph.bind("sysml", self.ns)
        self.nodes: dict[int, Any] = {}  # id(element) -> IRI / BNode
        self.anonymous = 0

    # -- node minting -------------------------------------------------------

    def node(self, element: M.Element) -> Any:
        key = id(element)
        existing = self.nodes.get(key)
        if existing is not None:
            return existing
        qname = element.qualified_name
        if qname is not None:
            iri = self.rdflib.URIRef(self.base + _iri_path(qname))
        else:  # blank-node fallback, labeled in document order
            self.anonymous += 1
            iri = self.rdflib.BNode(f"anon{self.anonymous}")
        self.nodes[key] = iri
        return iri

    def ref_node(self, name: str, context: M.Element) -> Any:
        """The node for a referenced name: resolved to its element when
        possible, otherwise an IRI minted from the reference text as
        written (so dangling and standard-library references stay
        queryable)."""

        try:
            target = self.resolver.resolve(name, context=context)
        except SysMLError:
            target = None
        if target is not None and target.qualified_name:
            return self.node(target)
        return self.rdflib.URIRef(self.base + _iri_path(name))

    # -- projection ----------------------------------------------------------

    def project(self) -> Graph:
        for member in self.model.members:
            self.element(member)
        if self.evaluated:
            self.evaluate_defaults()
        return self.graph

    def element(self, element: M.Element) -> Any | None:
        class_name = self.class_name(element)
        if class_name is None:
            return None
        subject = self.node(element)
        add = self.graph.add
        literal = self.rdflib.Literal
        add((subject, self.rdflib.RDF.type, self.ns[class_name]))
        if element.name:
            add((subject, self.ns.name, literal(element.name)))
            add((subject, self.rdflib.RDFS.label, literal(element.name)))
        if element.short_name:
            add((subject, self.ns.shortName, literal(element.short_name)))
        if element.qualified_name:
            add((subject, self.ns.qualifiedName, literal(element.qualified_name)))
        for keyword in element.metadata:
            add((subject, self.ns.metadata, self.ref_node(keyword, element)))
        if isinstance(element, (M.Definition, M.Usage)):
            add((subject, self.ns.kind, literal(element.kind)))
            self.flags(subject, element)
        if isinstance(element, M.Definition):
            for super_name in element.supers:
                add((subject, self.ns.specializes, self.ref_node(super_name, element)))
            if element.result is not None:
                add((subject, self.ns.expression, literal(expr_to_text(element.result))))
        if isinstance(element, M.Usage):
            self.usage(subject, element)
        if isinstance(element, M.Import):
            add((subject, self.ns.importedElement, self.ref_node(element.target, element)))
        if isinstance(element, M.Alias):
            add((subject, self.ns.aliasFor, self.ref_node(element.target, element)))
        if isinstance(element, M.Dependency):
            for client in element.clients:
                add((subject, self.ns.client, self.ref_node(client, element)))
            for supplier in element.suppliers:
                add((subject, self.ns.supplier, self.ref_node(supplier, element)))
        if isinstance(element, M.MetadataUsage):
            add((subject, self.ns.definedBy, self.ref_node(element.typed_by, element)))
            for about in element.about:
                add((subject, self.ns.annotatedElement, self.ref_node(about, element)))
        if isinstance(element, M.Namespace):
            self.members(subject, element)
        return subject

    def class_name(self, element: M.Element) -> str | None:
        """The spec metaclass name (mirrors the ecore/api projection)."""

        if isinstance(element, M.Definition):
            return _DEF_CLASSES.get(element.kind, "Definition")
        if isinstance(element, M.Usage):
            return _USAGE_CLASSES.get(element.kind, "Usage")
        if isinstance(element, M.Import):
            return "NamespaceImport" if element.is_namespace else "MembershipImport"
        for cls, name in _DIRECT_CLASSES.items():
            if type(element) is cls:
                return name
        return None  # statements, comments, unsupported: not projected

    def flags(self, subject: Any, element: M.Definition | M.Usage) -> None:
        for attr, prop in _FLAG_PROPERTIES:
            if getattr(element, attr, False):
                self.graph.add((subject, self.ns[prop], self.rdflib.Literal(True)))

    def usage(self, subject: Any, usage: M.Usage) -> None:
        add = self.graph.add
        literal = self.rdflib.Literal
        for type_name in usage.types:
            add((subject, self.ns.definedBy, self.ref_node(type_name, usage)))
        for subset in usage.subsets:
            add((subject, self.ns.subsets, self.ref_node(subset, usage)))
        for redefined in usage.redefines:
            add((subject, self.ns.redefines, self.ref_node(redefined, usage)))
        if usage.references:
            add((subject, self.ns.references, self.ref_node(usage.references, usage)))
        if usage.crosses:
            add((subject, self.ns.crosses, self.ref_node(usage.crosses, usage)))
        if usage.direction:
            add((subject, self.ns.direction, literal(usage.direction)))
        if usage.constraint_kind:
            add((subject, self.ns.constraintKind, literal(usage.constraint_kind)))
        if usage.result is not None:
            add((subject, self.ns.expression, literal(expr_to_text(usage.result))))
        if usage.multiplicity is not None:
            self.bounds(subject, usage.multiplicity)
        if usage.value is not None:
            self.value(subject, usage, usage.value)
        for end in getattr(usage, "ends", None) or []:
            add((subject, self.ns.connects, self.ref_node(end.target, usage)))
        if isinstance(usage, M.BindingConnector):
            for end in (usage.source_end, usage.target_end):
                if end is not None:
                    add((subject, self.ns.connects, self.ref_node(end.target, usage)))
        if isinstance(usage, M.SatisfyUsage) and usage.by:
            add((subject, self.ns.satisfiedBy, self.ref_node(usage.by, usage)))

    def value(self, subject: Any, usage: M.Usage, value: M.FeatureValue) -> None:
        add = self.graph.add
        if isinstance(value.expr, LiteralExpr) and value.expr.value is not None:
            add((subject, self.ns.value, self.rdflib.Literal(value.expr.value)))
        else:
            add((subject, self.ns.valueExpression, self.rdflib.Literal(expr_to_text(value.expr))))
        if value.is_default:
            add((subject, self.ns.isDefault, self.rdflib.Literal(True)))
        if value.is_initial:
            add((subject, self.ns.isInitial, self.rdflib.Literal(True)))

    def bounds(self, subject: Any, multiplicity: M.Multiplicity) -> None:
        for expr, prop in ((multiplicity.lower, "lowerBound"), (multiplicity.upper, "upperBound")):
            if isinstance(expr, LiteralExpr) and isinstance(expr.value, int):
                self.graph.add((subject, self.ns[prop], self.rdflib.Literal(expr.value)))

    def members(self, subject: Any, namespace: M.Namespace) -> None:
        for member in namespace.members:
            if isinstance(member, M.Documentation):
                self.comment(subject, member.text)
                continue
            if isinstance(member, M.Comment):
                self.annotate(subject, member)
                continue
            child = self.element(member)
            if child is not None:
                self.graph.add((subject, self.ns.ownedMember, child))

    def comment(self, subject: Any, text: str) -> None:
        if text:
            self.graph.add((subject, self.rdflib.RDFS.comment, self.rdflib.Literal(text)))

    def annotate(self, owner: Any, comment: M.Comment) -> None:
        """A ``comment about a, b`` annotates its targets; a plain comment
        annotates its owner."""

        if not comment.about:
            self.comment(owner, comment.text)
            return
        context = comment.owner or self.model
        for target in comment.about:
            self.comment(self.ref_node(target, context), comment.text)

    # -- evaluated values -----------------------------------------------------

    def evaluate_defaults(self) -> None:
        """Best-effort ``sysml:evaluatedValue`` triples for expression-valued
        attributes, one instantiation per definition."""

        interpreter = Interpreter(self.model)
        for element in self.model.iter_tree():
            if not isinstance(element, M.Definition) or element.is_abstract:
                continue
            targets = {
                member.name: member
                for member in element.members
                if isinstance(member, M.Usage)
                and member.name
                and member.value is not None
                and not isinstance(member.value.expr, LiteralExpr)
            }
            if not targets:
                continue
            try:
                instance = interpreter.instantiate(element)
            except Exception:  # unevaluable definitions are skipped
                continue
            for name, member in targets.items():
                value = instance.slots.get(name)
                if isinstance(value, (bool, int, float, str)):
                    self.graph.add(
                        (self.node(member), self.ns.evaluatedValue, self.rdflib.Literal(value))
                    )


def _iri_path(qname: str) -> str:
    """``A::B c`` -> ``A/B%20c``: percent-encoded qualified-name segments."""

    return "/".join(quote(part, safe="") for part in qname.split("::"))
