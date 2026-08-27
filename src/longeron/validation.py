"""Model validation: dangling references, duplicate names, cycles.

``validate`` walks a model and returns :class:`Diagnostic` records.  Name
resolution is stdlib-aware: unless disabled (``stdlib=False``), references
resolve against the vendored standard library as a fallback, so
``ScalarValues::Real`` -- or a bare ``Real``, without any import --
validates silently while a misspelled ``Reall`` warns.  Implied
specializations are honored too: a plain ``action def`` implicitly
specializes ``Actions::Action``, so inherited names like ``start`` and
``done`` resolve in expressions.  Unresolved references are *warnings*;
structural problems (duplicate names, specialization cycles, transitions
to unknown states) are *errors*.

The dimensional lint (design: ``docs/design/units.md``) also lives here:
unit annotations must resolve (``unresolved-unit``), arithmetic over
attributes with known dimension vectors must agree (``dimension-mismatch``
-- the ``mass + flightTime`` bug the interpreter silently evaluates),
mixed measurement scales under ``+``/``-`` are an error
(``scale-mismatch``: ``dBW + W``, ``°C + K``), same-dimension operands in
different units warn without the ``[units]`` extra (``mixed-units``), and
scoreboard ramp/target anchors are checked against their requirement's
``measure`` (``anchor-dimension-mismatch``).  Dimensions come from
:mod:`longeron.units`, derived from the vendored library's own
definitional algebra; unknown dimensions are bottom and propagate
silently -- the lint only speaks when two *known* vectors conflict.

Flow connectivity gets the same treatment: a ``flow`` / ``message`` end
that does not resolve warns (``dangling-flow``, the moral twin of
``dangling-expose``), and a declared payload typing with no
specialization relationship to the target end's declared typing warns
(``flow-payload-mismatch``).  Typing absent on either side stays silent
-- the check only speaks when two known typings conflict.

The kind-level well-formedness checks (``usage-type``,
``attribute-composite-feature``, ``redefinition-featuring-types``, and
friends -- the full table lives in ``docs/guides/validation.md``) apply
the same contract to the SysML v2 metamodel's clause-8.3 constraints:
they only speak when a reference *resolves* and the resolved element's
kind is known to conflict.  Unresolved references stay warnings, kinds
outside the vocabulary families below ('extended' definitions, bare
``feature``/``ref`` usages) are bottom, and a resolved-but-wrong-kind
target -- a part typed by an attribute definition, a variant outside a
variation, two subjects in one requirement -- is a structural
self-contradiction and therefore an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from . import ast as A
from . import model as M
from . import stdlib as stdlib_module
from . import units as units_module
from .errors import ResolutionError, SourceLocation
from .interpreter import BUILTINS, IMPLIED_SPECIALIZATIONS, Resolver, _in_library_package

Severity = Literal["error", "warning"]

# ---------------------------------------------------------------------------
# Metamodel kind families (SysML v2 clause 8.3 / KerML clause 8.4)
# ---------------------------------------------------------------------------
#
# 'flow' is deliberately in none of the three families: a
# FlowConnectionDefinition is both a ConnectionDefinition (a Structure)
# and an ActionDefinition (a Behavior).  'occurrence' and 'individual'
# sit above the structure/behavior split; 'extended' is a language
# extension of unknown kind.  All three are bottom for the kind checks.

#: definition kinds that are KerML DataTypes
_DATA_DEFS = frozenset({"attribute", "enum"})
#: definition kinds that are KerML Structures (occurrence, non-behavior)
_STRUCTURE_DEFS = frozenset(
    {
        "part",
        "item",
        "port",
        "connection",
        "interface",
        "allocation",
        "metadata",
        "view",
        "rendering",
    }
)
#: definition kinds that are KerML Behaviors
_BEHAVIOR_DEFS = frozenset(
    {
        "action",
        "calc",
        "state",
        "constraint",
        "requirement",
        "concern",
        "case",
        "analysis",
        "verification",
        "use_case",
        "viewpoint",
    }
)
#: every definition kind that is an OccurrenceDefinition (not a DataType)
_OCCURRENCE_DEFS = (
    _STRUCTURE_DEFS | _BEHAVIOR_DEFS | frozenset({"occurrence", "individual", "flow"})
)

#: usage kinds whose metamodel class is unambiguous (everything except
#: keyword-less features, bare refs, events, and language extensions --
#: those are bottom: the checks below never judge them)
_KNOWN_USAGES = frozenset(M.USAGE_KINDS) - frozenset(
    {"feature", "ref", "extended", "event", "event_occurrence"}
)
#: usage kinds that are KerML Steps (performable; ActionUsage and subtypes)
_ACTION_USAGES = frozenset(
    {"action", "calc", "state", "case", "analysis", "verification", "use_case", "flow", "message"}
)
#: usage kinds that are composite occurrence features by default --
#: the vocabulary for the attribute-body and port-body checks
_COMPOSITE_OCCURRENCE_USAGES = frozenset(
    {
        "part",
        "port",
        "action",
        "state",
        "occurrence",
        "individual",
        "connection",
        "interface",
        "flow",
    }
)
# 'item' is deliberately absent: the spec rule text covers items too, but
# the spec's own corpus nests composite items in attribute definitions
# ('attribute def Show { item picture : Picture; }' in the messaging
# training models), so judging them would reject official models.
#: the subset of those that a port body must declare ``ref`` (connectors
#: and nested ports are legitimate port-definition members)
_PORT_COMPOSITE_USAGES = frozenset({"part", "item", "action", "state", "occurrence", "individual"})


#: usage kind -> (conflicting definition kinds, the rule's phrasing).
#: A conflict fires ``usage-type`` only when the declared type RESOLVES
#: to a definition of a conflicting kind; kinds absent from the map
#: (connectors, subjects, views, ...) and definition kinds outside the
#: conflict set are bottom.
_USAGE_TYPE_RULES: dict[str, tuple[frozenset[str], str]] = {
    "attribute": (_OCCURRENCE_DEFS, "an attribute must be typed by attribute definitions"),
    "enum": (_OCCURRENCE_DEFS, "an enumeration must be typed by enumeration definitions"),
    "part": (
        _DATA_DEFS | _BEHAVIOR_DEFS | {"port"},
        "a part must be typed by part or item definitions",
    ),
    "item": (
        _DATA_DEFS | _BEHAVIOR_DEFS | {"port"},
        "an item must be typed by item definitions",
    ),
    "port": (_DATA_DEFS | _BEHAVIOR_DEFS, "a port must be typed by port definitions"),
    "action": (_DATA_DEFS | _STRUCTURE_DEFS, "an action must be typed by action definitions"),
    "state": (_DATA_DEFS | _STRUCTURE_DEFS, "a state must be typed by state definitions"),
    "calc": (
        _DATA_DEFS | _STRUCTURE_DEFS,
        "a calculation must be typed by calculation definitions",
    ),
    "constraint": (
        _DATA_DEFS | _STRUCTURE_DEFS,
        "a constraint must be typed by constraint definitions",
    ),
    "requirement": (
        _DATA_DEFS | _STRUCTURE_DEFS,
        "a requirement must be typed by requirement definitions",
    ),
    "concern": (_DATA_DEFS | _STRUCTURE_DEFS, "a concern must be typed by concern definitions"),
    "case": (_DATA_DEFS | _STRUCTURE_DEFS, "a case must be typed by case definitions"),
    "analysis": (
        _DATA_DEFS | _STRUCTURE_DEFS,
        "an analysis case must be typed by analysis definitions",
    ),
    "verification": (
        _DATA_DEFS | _STRUCTURE_DEFS,
        "a verification case must be typed by verification definitions",
    ),
    "use_case": (_DATA_DEFS | _STRUCTURE_DEFS, "a use case must be typed by use case definitions"),
    "occurrence": (_DATA_DEFS, "an occurrence must be typed by occurrence definitions"),
    "individual": (_DATA_DEFS, "an individual must be typed by occurrence definitions"),
}

#: usage kinds whose declaration references another element by name
#: (``satisfy R1 by ...``, ``verify R1``, ``include uc``): the builder
#: stores the reference as a subsetting, and naming a *definition* there
#: is legal (the pilot mints a usage typed by it) -- so the
#: subsets-non-feature judgment skips them
_REFERENCE_USAGE_KINDS = frozenset({"satisfy", "verify", "include", "frame", "render", "objective"})

#: definition-kind family -> the definition kinds it may not specialize
#: (KerML validateDataTypeSpecialization / the Behavior-Structure split)
_SPECIALIZATION_CONFLICTS: dict[str, frozenset[str]] = {
    "datatype": _OCCURRENCE_DEFS,  # a DataType may not specialize a Class or Association
    "behavior": _STRUCTURE_DEFS | _DATA_DEFS,  # a Behavior may not specialize a Structure
    "structure": _BEHAVIOR_DEFS | _DATA_DEFS,  # a Structure may not specialize a Behavior
}


@dataclass
class Diagnostic:
    severity: Severity
    code: str
    message: str
    element: str  # qualified name (or best-effort label) of the subject
    location: SourceLocation | None = None  # file:line:column, when parsed

    def __str__(self) -> str:
        prefix = f"{self.location}: " if self.location is not None else ""
        return f"{prefix}{self.severity}[{self.code}] {self.element}: {self.message}"


def validate(
    model: M.Model, *, stdlib: bool | None = None, strict_imports: bool = False
) -> list[Diagnostic]:
    """Validate a model; returns diagnostics sorted errors-first.

    ``stdlib`` controls the standard-library fallback used for name
    resolution: ``None`` (default) auto-attaches the vendored library when
    it loads, ``True`` forces it, ``False`` disables it.  The library is
    only consulted by the resolver -- ``model`` is never mutated.

    ``strict_imports`` additionally warns (``stdlib-implicit-name``) for
    bare standard-library names that resolve *only* through the implicit
    library-visibility hop -- the KerML global-namespace convenience for
    standard library packages.  Qualified names (``ScalarValues::Real``)
    and explicitly imported names stay silent.

    Elements inside ``library`` packages are never the subject of
    diagnostics: a merged-in standard library (e.g. via the CLI's
    ``--stdlib``) is resolution context, not the model under validation.
    """

    library: M.Model | None = None
    if stdlib is None:
        try:
            library = stdlib_module.standard_library_model(cache=True)
        except Exception:
            library = None  # degrade to resolution without the library
    elif stdlib:
        library = stdlib_module.standard_library_model(cache=True)
    checker = _Checker(model, library=library, strict_imports=strict_imports)
    checker.check_all()
    order = {"error": 0, "warning": 1}
    return sorted(checker.diagnostics, key=lambda d: (order[d.severity], d.element, d.code))


class _Checker:
    def __init__(
        self, model: M.Model, library: M.Model | None = None, strict_imports: bool = False
    ):
        self.model = model
        self.resolver = Resolver(model, library=library)
        self.strict_imports = strict_imports
        self._used_implicit = False  # set by _resolves, read right after
        self.diagnostics: list[Diagnostic] = []
        self._unit_table: units_module.UnitTable | None = None
        self._meanings: dict[int, _Meaning | None] = {}  # id(usage) -> declared meaning
        #: tree-walk parent for elements the builder does not own-link
        #: (state entry/do/exit actions, if/loop body members); used to
        #: anchor name resolution for those elements
        self._parents: dict[int, M.Element] = {}

    def report(self, severity: Severity, code: str, element: M.Element, message: str) -> None:
        where = element.qualified_name
        node = element.owner
        while where is None and node is not None:  # anonymous: nearest named owner
            where = node.qualified_name
            node = node.owner
        if where is None:
            where = element.label
        location = getattr(element, "source_location", None)
        self.diagnostics.append(Diagnostic(severity, code, message, where, location))

    # -- driver ---------------------------------------------------------------

    def check_all(self) -> None:
        self._check_tree(self.model)

    def _check_tree(self, element: M.Element) -> None:
        if isinstance(element, M.Package) and (element.is_library or element.is_standard):
            return  # library packages are resolution context, not subjects
        if isinstance(element, M.Namespace):
            self.check_duplicate_names(element)
        if isinstance(element, (M.Definition, M.Usage)):
            self.check_references(element)
            self.check_specialization_cycle(element)
            self.check_expressions(element)
            self.check_units(element)
            self.check_scoreboard_anchors(element)
            self.check_member_counts(element)
            self.check_owned_composites(element)
            self.check_variation_members(element)
        if isinstance(element, M.Definition):
            self.check_definition_specialization(element)
            if element.kind == "interface":
                self.check_interface_definition_ends(element)
        if isinstance(element, M.Usage):
            self.check_usage_typing(element)
            self.check_feature_relationships(element)
        if isinstance(element, (M.ConnectionUsage, M.InterfaceUsage)):
            self.check_connector_ends(element, element.ends)
        if isinstance(element, M.BindingConnector):
            ends = [e for e in (element.source_end, element.target_end) if e is not None]
            self.check_connector_ends(element, ends)
        if isinstance(element, M.SendAction):
            self.check_send(element)
        if isinstance(element, M.PerformAction):
            self.check_perform(element)
        if isinstance(element, (M.Succession, M.InitialNode)):
            self.check_succession_ends(element)
        if element.metadata or isinstance(element, M.MetadataUsage):
            self.check_metadata_refs(element)
        if isinstance(element, M.Import):
            self.check_target(element, element.target, "import")
        if isinstance(element, M.Expose):
            self.check_expose(element)
        if isinstance(element, M.FlowUsage):
            self.check_flow(element)
        if isinstance(element, M.Alias):
            self.check_target(element, element.target, "alias")
        if isinstance(element, M.Dependency):
            for ref in element.clients + element.suppliers:
                self.check_target(element, ref, "dependency")
        if isinstance(element, (M.Definition, M.Usage)) and element.kind == "state":
            self.check_state_machine(element)
        if isinstance(element, M.Usage) and element.kind == "calc":
            self.check_calc_result(element)
        if isinstance(element, M.Definition) and element.kind == "calc":
            self.check_calc_result(element)
        for child in element.children():
            if child.owner is None:
                self._parents[id(child)] = element
            self._check_tree(child)

    # -- checks ------------------------------------------------------------------

    def check_duplicate_names(self, ns: M.Namespace) -> None:
        seen: dict[str, M.Element] = {}
        for member in ns.members:
            for name in (member.name, member.short_name):
                if name is None:
                    continue
                if name in seen and seen[name] is not member:
                    self.report(
                        "error",
                        "duplicate-name",
                        member,
                        f"name {name!r} is already used by another member of {ns.label}",
                    )
                else:
                    seen[name] = member

    def _reference_fields(self, element: M.Definition | M.Usage) -> list[tuple[str, str]]:
        refs: list[tuple[str, str]] = []
        if isinstance(element, M.Definition):
            refs += [("specializes", s) for s in element.supers]
            return refs
        refs += [("typed by", t.lstrip("~")) for t in element.types]
        refs += [("subsets", s) for s in element.subsets]
        refs += [("redefines", r) for r in element.redefines]
        if element.references:
            refs.append(("references", element.references))
        if element.crosses:
            refs.append(("crosses", element.crosses))
        if isinstance(element, (M.ConnectionUsage, M.InterfaceUsage, M.AllocationUsage)):
            refs += [("connects", e.target) for e in element.ends]
        if isinstance(element, M.BindingConnector):
            for end in (element.source_end, element.target_end):
                if end is not None:
                    refs.append(("binds", end.target))
        if isinstance(element, M.SatisfyUsage) and element.by:
            refs.append(("satisfied by", element.by))
        return refs

    def check_references(self, element: M.Definition | M.Usage) -> None:
        for role, ref in self._reference_fields(element):
            self.check_target(element, ref, role)

    def check_target(self, element: M.Element, ref: str, role: str) -> None:
        if not ref:
            return
        if self._resolves(ref, element):
            self._check_implicit(element, ref)
            return
        self.report("warning", "unresolved-reference", element, f"{role} {ref!r} does not resolve")

    def check_expose(self, expose: M.Expose) -> None:
        """dangling-expose: an ``expose`` inside a view usage names an
        element that no longer resolves.  Restore skips such exposes with
        a warning (:mod:`longeron.views`); this diagnostic surfaces the
        same condition in ``validate`` / ``longeron lint``.  Warning, not
        error: the spec places no well-formedness constraint on an import
        target's continued existence, and the target may live in a file
        that was not loaded."""

        if not expose.target or self._resolves(expose.target, expose):
            return
        owner = expose.owner
        where = (owner.qualified_name or owner.label) if owner is not None else expose.label
        location = getattr(expose, "source_location", None)
        self.diagnostics.append(
            Diagnostic(
                "warning",
                "dangling-expose",
                f"expose target {expose.target!r} does not resolve",
                where,
                location,
            )
        )

    def check_flow(self, flow: M.FlowUsage) -> None:
        """dangling-flow / flow-payload-mismatch: the flow-connectivity
        checks.  A ``flow of Payload from a.out to b.in`` stores its ends
        and payload as strings the model layer never resolves; a dangling
        end (warning, like ``dangling-expose``: the target may live in a
        file that was not loaded) or a payload whose declared typing has
        no specialization relationship with the target end's declared
        typing (warning) is invisible until here."""

        keyword = "message" if flow.kind == "message" else "flow"
        for role, ref in (("source", flow.source), ("target", flow.target_end)):
            if not ref or self._resolves(ref, flow):
                continue
            self._report_flow("dangling-flow", flow, f"{keyword} {role} {ref!r} does not resolve")
        self.check_flow_payload(flow, keyword)

    def check_flow_payload(self, flow: M.FlowUsage, keyword: str) -> None:
        """flow-payload-mismatch, honestly: only when *both* the payload
        and the target end carry resolvable declared typing, and no pair
        of those types is related by the specialization walk (in either
        direction -- a supertype payload may still hold a conforming
        value at runtime, so only provably unrelated types conflict)."""

        if not flow.payload or not flow.target_end:
            return
        payload_types: list[M.Element] = []
        for ref in self._flow_payload_refs(flow):
            types = self._declared_types(self._resolve_path(ref, flow))
            if not types:
                return  # untyped or unresolved payload: no guessing
            payload_types.extend(types)
        if not payload_types:
            return  # bare payload name with no typing ('flow of x from ...')
        accepted = self._declared_types(self._resolve_path(flow.target_end, flow))
        if not accepted:
            return  # dangling or untyped target end: silent here
        for payload_type in payload_types:
            for target_type in accepted:
                if self._conforms(payload_type, target_type) or self._conforms(
                    target_type, payload_type
                ):
                    return
        names = ", ".join(repr(t.label) for t in accepted)
        self._report_flow(
            "flow-payload-mismatch",
            flow,
            f"payload {flow.payload!r} is incompatible with {keyword} "
            f"target {flow.target_end!r} (accepts {names})",
        )

    def _report_flow(self, code: str, flow: M.FlowUsage, message: str) -> None:
        """Report against the flow's own qualified name when it has one,
        else its owner's (flows are usually anonymous, like exposes)."""

        where = flow.qualified_name
        if where is None:
            owner = flow.owner
            where = (owner.qualified_name or owner.label) if owner is not None else flow.label
        location = getattr(flow, "source_location", None)
        self.diagnostics.append(Diagnostic("warning", code, message, where, location))

    @staticmethod
    def _flow_payload_refs(flow: M.FlowUsage) -> list[str]:
        """Type references declared by the payload feature.  The model
        keeps the payload as canonical text (``'x : T'`` / ``'T'`` /
        ``'x : T1, T2'``); the part after the colon is the declared
        typing, and a colon-free payload is a single reference (a type,
        or a feature whose declaration carries the typing)."""

        text = flow.payload or ""
        if ":" in text:
            return [t.strip() for t in text.split(":", 1)[1].split(",") if t.strip()]
        return [text.strip()] if text.strip() else []

    def _declared_types(self, element: M.Element | None) -> list[M.Element]:
        """The declared typing behind a resolved payload/end reference: a
        definition is its own type, a usage contributes its resolved
        ``types``, an accept action its payload types.  Empty = unknown."""

        if element is None:
            return []
        if isinstance(element, M.Definition):
            return [element]
        names: list[str] = []
        if isinstance(element, M.AcceptAction):
            names = list(element.payload_types)
        elif isinstance(element, M.Usage):
            names = list(element.types)
        out: list[M.Element] = []
        for name in names:
            resolved = self._resolve_path(name.lstrip("~"), element)
            if resolved is not None:
                out.append(resolved)
        return out

    def _conforms(self, special: M.Element, general: M.Element) -> bool:
        """True when ``special`` reaches ``general`` through the
        specialization walk (``supers`` / ``types`` / ``subsets`` plus
        implied bases; redefinition edges excluded, as in the cycle
        check)."""

        if special is general:
            return True
        seen: set[int] = set()
        stack: list[M.Element] = [special]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            for g in self._cycle_generals(node):
                if g is general:
                    return True
                stack.append(g)
        return False

    def _check_implicit(self, element: M.Element, ref: str) -> None:
        """stdlib-implicit-name: ``ref`` resolved, but only through the
        resolver's implicit library-visibility hop (strict mode only)."""

        if self.strict_imports and self._used_implicit:
            self.report(
                "warning",
                "stdlib-implicit-name",
                element,
                f"stdlib name {ref!r} used without import",
            )

    def _scope_of(self, context: M.Element) -> M.Element:
        """The scope name resolution starts from: the context's owner --
        or, for body elements the builder does not own-link (state
        entry/do/exit actions, inline perform bodies), the tree-walk
        parent recorded during the visit."""

        return context.owner or self._parents.get(id(context)) or self.model

    def _resolves(self, ref: str, context: M.Element) -> bool:
        scope: M.Element = self._scope_of(context)
        implicit = False
        for segment in ref.split("."):
            if segment == "$":  # root escape: re-anchor at the model root
                scope = self.model
                continue
            try:
                scope = self.resolver.resolve(segment, scope)
            except ResolutionError:
                self._used_implicit = False
                return False
            implicit = implicit or self.resolver.last_hop == "library-implicit"
        self._used_implicit = implicit
        return True

    def check_specialization_cycle(self, element: M.Definition | M.Usage) -> None:
        seen: set[int] = set()
        stack: list[M.Element] = [element]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            for general in self._cycle_generals(node):
                if general is element:
                    self.report(
                        "error",
                        "specialization-cycle",
                        element,
                        "specialization hierarchy is cyclic",
                    )
                    return
                stack.append(general)

    def _cycle_generals(self, node: M.Element) -> list[M.Namespace]:
        """Specialization edges for the cycle check: ``supers`` / ``types`` /
        ``subsets`` plus implied bases -- but *not* redefinition edges.

        A redefinition (``attribute x :>> x``) legitimately reuses the
        redefined feature's name, so resolving it lands on the redefining
        element itself; folding redefinition edges into the walk (as the
        resolver's ``_generals`` does) turns that shadowing into a false
        "cyclic" error.
        """

        names: list[str] = []
        if isinstance(node, M.Definition):
            names = list(node.supers)
        elif isinstance(node, M.Usage):
            names = list(node.types) + list(node.subsets)
        out: list[M.Namespace] = []
        for name in names:
            if name.startswith("~"):
                name = name[1:]
            try:
                general = self.resolver.resolve(name, node.owner or self.model)
            except ResolutionError:
                continue
            if isinstance(general, M.Namespace):
                out.append(general)
        for general in self.resolver.implied_generals(node):
            if general not in out:
                out.append(general)
        return out

    # -- kind-level well-formedness (SysML v2 clause 8.3 / KerML 8.4) ------------

    def check_member_counts(self, element: M.Definition | M.Usage) -> None:
        """only-one-subject / only-one-return-parameter / state-subaction-kind:
        the \"at most one\" cardinalities over owned members
        (validateRequirementDefinitionOnlyOneSubject and its case twin;
        KerML's single result parameter for functions;
        validateStateDefinitionStateSubactionKind, spec p. 336)."""

        subjects = [m for m in element.members if isinstance(m, M.Usage) and m.kind == "subject"]
        if len(subjects) > 1:
            self.report(
                "error",
                "only-one-subject",
                element,
                f"{len(subjects)} subjects declared; only one subject is allowed",
            )
        returns = [m for m in element.members if isinstance(m, M.Usage) and m.direction == "return"]
        if len(returns) > 1:
            self.report(
                "error",
                "only-one-return-parameter",
                element,
                f"{len(returns)} return parameters declared; only one return parameter is allowed",
            )
        for kind in ("entry", "do", "exit"):
            actions = [
                m for m in element.members if isinstance(m, M.StateAction) and m.kind == kind
            ]
            if len(actions) > 1:
                self.report(
                    "error",
                    "state-subaction-kind",
                    element,
                    f"{len(actions)} {kind!r} actions declared; at most one "
                    "state subaction of each kind is allowed",
                )

    def check_owned_composites(self, element: M.Definition | M.Usage) -> None:
        """attribute-composite-feature / port-composite-usage: composite
        occurrence features where the metamodel demands referential ones
        (validateAttributeDefinitionFeatures, spec p. 278;
        validateAttributeUsageFeatures, p. 279;
        pilot:validatePortDefinitionOwnedUsagesNotComposite)."""

        is_attribute = element.kind in ("attribute", "enum")
        is_port = element.kind == "port"
        if not is_attribute and not is_port:
            return
        for member in element.members:
            if not isinstance(member, M.Usage) or member.is_ref or member.is_end:
                continue
            if member.direction is not None:
                continue  # directed features ('out item fuel') are the port idiom
            if is_attribute and member.kind in _COMPOSITE_OCCURRENCE_USAGES:
                shape = "definition" if isinstance(element, M.Definition) else "usage"
                self.report(
                    "error",
                    "attribute-composite-feature",
                    member,
                    f"a composite {member.kind} is not a valid feature of an attribute "
                    f"{shape}: all features of an attribute must be non-composite",
                )
            elif is_port and member.kind in _PORT_COMPOSITE_USAGES:
                self.report(
                    "error",
                    "port-composite-usage",
                    member,
                    f"owned usages of a port (other than ports) must be referential: "
                    f"declare {member.label!r} with 'ref'",
                )

    def check_variation_members(self, element: M.Definition | M.Usage) -> None:
        """variation-membership: an owned usage of a variation must be a
        variant (pilot:validateDefinitionVariationMembership /
        validateUsageVariationMembership).  Non-usage members (docs,
        imports) are fine; only usage members are judged."""

        if not element.is_variation:
            return
        for member in element.members:
            if isinstance(member, M.Usage) and not member.is_variant:
                self.report(
                    "error",
                    "variation-membership",
                    member,
                    f"an owned usage of variation {element.label!r} must be a variant",
                )

    def check_definition_specialization(self, defn: M.Definition) -> None:
        """datatype- / behavior- / structure-specialization: cross-family
        specializations the kernel forbids (KerML
        validateDataTypeSpecialization: 'Cannot specialize class or
        association', and the Behavior/Structure split).  Only resolved
        supers of a known conflicting kind speak."""

        if defn.kind in _DATA_DEFS:
            family = "datatype"
        elif defn.kind in _BEHAVIOR_DEFS:
            family = "behavior"
        elif defn.kind in _STRUCTURE_DEFS:
            family = "structure"
        else:
            return  # flow / occurrence / individual / extended: bottom
        conflicts = _SPECIALIZATION_CONFLICTS[family]
        for ref in defn.supers:
            target = self._resolve_path(ref.lstrip("~"), defn)
            if (
                isinstance(target, M.Definition)
                and target.kind in conflicts
                and not _in_library_package(target)
            ):
                self.report(
                    "error",
                    f"{family}-specialization",
                    defn,
                    f"a {defn.kind} definition cannot specialize {ref!r}, "
                    f"a {target.kind} definition",
                )

    def check_usage_typing(self, usage: M.Usage) -> None:
        """usage-type / individual-definition / enum-attribute-type: the
        declared-typing kind checks.  Fires only on types that resolve;
        an unresolved type already warns as [unresolved-reference]."""

        rule = _USAGE_TYPE_RULES.get(usage.kind)
        individuals: list[str] = []
        enum_typed = False
        for ref in usage.types:
            target = self._resolve_path(ref.lstrip("~"), usage)
            if target is None:
                continue
            if isinstance(target, M.Package):
                self.report(
                    "error",
                    "usage-type",
                    usage,
                    f"typed by {ref!r}: a usage must be typed by a definition, not a package",
                )
                continue
            if not isinstance(target, M.Definition):
                continue
            if rule is not None and target.kind in rule[0] and not _in_library_package(target):
                self.report(
                    "error",
                    "usage-type",
                    usage,
                    f"typed by {ref!r}: {rule[1]}, not a {target.kind} definition",
                )
            if target.is_individual or target.kind == "individual":
                individuals.append(ref)
            if target.kind == "enum":
                enum_typed = True
        if len(individuals) > 1:
            self.report(
                "error",
                "individual-definition",
                usage,
                "at most one individual definition is allowed "
                f"(typed by {', '.join(repr(r) for r in individuals)})",
            )
        if enum_typed and len(usage.types) > 1 and usage.kind in ("attribute", "enum"):
            self.report(
                "error",
                "enum-attribute-type",
                usage,
                "an enumeration attribute cannot have more than one declared type",
            )

    def check_feature_relationships(self, usage: M.Usage) -> None:
        """The per-usage relationship checks: subsets-non-feature,
        redefinition-featuring-types, variant-membership,
        parameter-membership, the multiplicity-bound checks, and
        exhibit-state-reference."""

        for role, refs in (("subsets", usage.subsets), ("redefines", usage.redefines)):
            for ref in refs:
                target = self._resolve_path(ref.lstrip("~"), usage)
                if isinstance(target, (M.Package, M.Definition)) and role == "subsets":
                    kind = (
                        "package" if isinstance(target, M.Package) else f"{target.kind} definition"
                    )
                    if usage.is_exhibit or usage.kind in _REFERENCE_USAGE_KINDS:
                        continue  # reference usages may legally name definitions
                    self.report(
                        "error",
                        "subsets-non-feature",
                        usage,
                        f"{role} {ref!r}: the subsetted element must be a feature, not a {kind}",
                    )
                elif (
                    role == "redefines"
                    and isinstance(target, M.Usage)
                    and target is not usage
                    and target.owner is not None
                    and target.owner is usage.owner
                ):
                    where = (
                        "a package-level feature cannot be redefined"
                        if isinstance(usage.owner, (M.Package, M.Model))
                        else "the featuring types of the redefining and redefined "
                        "features cannot be the same"
                    )
                    self.report(
                        "error",
                        "redefinition-featuring-types",
                        usage,
                        f"redefines sibling feature {ref!r}: {where}",
                    )
        if usage.is_variant:
            owner = usage.owner
            owner_is_variation = isinstance(owner, (M.Definition, M.Usage)) and owner.is_variation
            if not owner_is_variation:
                self.report(
                    "error",
                    "variant-membership",
                    usage,
                    "a variant must be owned by a variation-point definition or usage "
                    "(mark the owner 'variation')",
                )
        # NOTE deliberately absent: a directed-feature-outside-behavior check
        # (KerML validateParameterMembershipOwningType).  The pilot's own
        # corpus places directed features in part definitions and usages
        # ('in item scene;' in Camera.sysml, 'in ref y: A, B;' in
        # ItemTest.sysml), so SysML textual direction does not map to
        # KerML ParameterMembership and any validation-time check here
        # rejects official models.
        self.check_multiplicity(usage)
        if usage.is_exhibit:
            self.check_exhibit(usage)

    def check_multiplicity(self, usage: M.Usage) -> None:
        """multiplicity-bound-type / multiplicity-bound-order and the
        bound-resolution warning (KerML
        validateMultiplicityRangeResultTypes: 'Must have a Natural
        value').  ``*`` parses as an infinity literal and is always a
        valid upper bound; name bounds must resolve."""

        mult = usage.multiplicity
        if mult is None:
            return
        values: dict[str, int] = {}
        for role, expr in (("lower", mult.lower), ("upper", mult.upper)):
            if expr is None:
                continue
            if isinstance(expr, A.Literal):
                value = expr.value
                if isinstance(value, float) and value == float("inf"):
                    continue  # '*'
                if isinstance(value, int) and not isinstance(value, bool):
                    values[role] = value
                    continue
                self.report(
                    "error",
                    "multiplicity-bound-type",
                    usage,
                    f"multiplicity {role} bound {value!r} must be a natural number",
                )
            elif isinstance(expr, A.FeatureRef):
                ref = ".".join(expr.parts)
                if not self._resolves(ref, usage):
                    self.report(
                        "warning",
                        "unresolved-reference",
                        usage,
                        f"multiplicity bound {ref!r} does not resolve",
                    )
            # other expression shapes (arithmetic bounds) stay unchecked
        if "lower" in values and "upper" in values and values["lower"] > values["upper"]:
            self.report(
                "error",
                "multiplicity-bound-order",
                usage,
                f"multiplicity lower bound {values['lower']} exceeds upper bound {values['upper']}",
            )

    def check_exhibit(self, usage: M.Usage) -> None:
        """exhibit-state-reference: 'Must reference a state'
        (validateExhibitStateUsageReference, spec p. 333).  Judged only
        when the reference resolves to a usage of known kind."""

        for ref in usage.subsets:
            target = self._resolve_path(ref.lstrip("~"), usage)
            if target is None or target is usage:
                continue
            if isinstance(target, M.Usage) and target.kind in _KNOWN_USAGES - {"state"}:
                self.report(
                    "error",
                    "exhibit-state-reference",
                    usage,
                    f"exhibit must reference a state; {ref!r} is a {target.kind}",
                )
            elif isinstance(target, (M.Package, M.Definition)):
                kind = "package" if isinstance(target, M.Package) else f"{target.kind} definition"
                self.report(
                    "error",
                    "exhibit-state-reference",
                    usage,
                    f"exhibit must reference a state usage; {ref!r} is a {kind}",
                )

    def check_interface_definition_ends(self, defn: M.Definition) -> None:
        """interface-end-not-port for definitions: 'An interface
        definition end must be a port' (pilot:validateInterfaceDefinitionEnd).
        Untyped ends stay silent (their kind is unknown here)."""

        for member in defn.members:
            if not isinstance(member, M.Usage) or not member.is_end:
                continue
            if member.kind == "port":
                continue
            for ref in member.types:
                target = self._resolve_path(ref.lstrip("~"), member)
                if isinstance(target, M.Definition) and target.kind not in ("port", "extended"):
                    self.report(
                        "error",
                        "interface-end-not-port",
                        member,
                        f"an interface definition end must be a port; "
                        f"{member.label!r} is typed by {ref!r}, a {target.kind} definition",
                    )

    def check_connector_ends(self, usage: M.Usage, ends: list[M.ConnectorEnd]) -> None:
        """connector-end-not-feature / interface-end-not-port for usages:
        a connector's relatedFeatures must be Features (KerML 8.3), and
        an interface end must be a port (pilot:validateInterfaceUsageEnd).
        Dangling ends are the resolver checks' business."""

        for end in ends:
            if not end.target:
                continue
            target = self._resolve_path(end.target, usage)
            if target is None:
                continue
            if isinstance(target, (M.Definition, M.Package)):
                kind = "package" if isinstance(target, M.Package) else f"{target.kind} definition"
                self.report(
                    "error",
                    "connector-end-not-feature",
                    usage,
                    f"connector end {end.target!r} must be a feature, not a {kind}",
                )
            elif (
                isinstance(usage, M.InterfaceUsage)
                and isinstance(target, M.Usage)
                and target.kind in _KNOWN_USAGES - {"port"}
            ):
                self.report(
                    "error",
                    "interface-end-not-port",
                    usage,
                    f"an interface end must be a port; {end.target!r} is a {target.kind}",
                )

    def check_send(self, send: M.SendAction) -> None:
        """send-payload: 'A send action must have a payload'
        (pilot:validateSendActionUsagePayloadArgument).  A bare ``send;``
        builds a null-literal payload.  Named send declarations
        (``action snd send { in :>> payload = s; }``) and sends that at
        least route (``send via this to x;``) bind their payload
        elsewhere, so only the anonymous, unrouted form is judged."""

        if send.name is not None or send.via is not None or send.to is not None:
            return
        if isinstance(send.payload, A.Literal) and send.payload.value is None:
            self.report(
                "error",
                "send-payload",
                send,
                "a send action must have a payload argument",
            )

    def _hidden_member(self, name: str, context: M.Element) -> bool:
        """True when ``name`` is visible from ``context`` through structure
        the resolver cannot walk: inline ``perform action X;`` declarations
        (their name lives on the wrapped usage, not on a namespace
        membership) and scope chains broken by body elements the builder
        does not own-link (followed here via the tree-walk parents)."""

        node: M.Element | None = context
        while node is not None:
            members: list[M.Element] = []
            if isinstance(node, (M.Definition, M.Usage)):
                members = self.resolver.members_of(node, implied=True)
            elif isinstance(node, M.Namespace):
                members = node.members
            for member in members:
                if name in (member.name, member.short_name):
                    return True
                if (
                    isinstance(member, M.PerformAction)
                    and member.action is not None
                    and name in (member.action.name, member.action.short_name)
                ):
                    return True
            node = node.owner or self._parents.get(id(node))
        return False

    def check_perform(self, perform: M.PerformAction) -> None:
        """perform-action-reference: 'Must reference an action'
        (pilot:validatePerformActionUsageReference) -- plus the
        unresolved-target warning its exhibit twin already gets."""

        if perform.action is not None or not perform.target:
            return
        ref = perform.target
        if not self._resolves(ref, perform):
            segments = ref.split(".")
            if len(segments) > 1 and self._resolve_path(segments[0], perform) is not None:
                # a chained target with a live head may reach its action
                # through featuring semantics the model does not carry:
                # bottom, no judgment
                return
            if self._hidden_member(segments[0], perform):
                return  # an inline 'perform action X;' declares the name
            if not self._inherited_name(segments[0], perform):
                self.report(
                    "warning",
                    "unresolved-reference",
                    perform,
                    f"performs {ref!r} does not resolve",
                )
            return
        target = self._resolve_path(ref, perform)
        if isinstance(target, M.Usage) and target.kind in _KNOWN_USAGES - _ACTION_USAGES:
            self.report(
                "error",
                "perform-action-reference",
                perform,
                f"perform must reference an action; {ref!r} is a {target.kind}",
            )
        elif isinstance(target, M.Definition) and target.kind in _DATA_DEFS | _STRUCTURE_DEFS:
            self.report(
                "error",
                "perform-action-reference",
                perform,
                f"perform must reference an action; {ref!r} is a {target.kind} definition",
            )
        elif isinstance(target, M.Package):
            self.report(
                "error",
                "perform-action-reference",
                perform,
                f"perform must reference an action; {ref!r} is a package",
            )

    def check_succession_ends(self, element: M.Succession | M.InitialNode) -> None:
        """dangling-succession: a succession's ends must resolve (the
        action-body analog of [unknown-state]; warning like the other
        reference checks -- the end may be an inherited step from a file
        that was not loaded).  Bottom-guards, per the lint contract: the
        owner must be of a kind whose implied library base we know
        (``use case`` is not mapped, so its inherited ``start``/``done``
        are unknowable here), must declare no explicit specializations
        (those suppress the implied base and may inherit steps we cannot
        enumerate), and must not own ``terminate``-style actions whose
        declared names the model layer drops."""

        scope = self._scope_of(element)
        if not isinstance(scope, (M.Definition, M.Usage)):
            return
        if scope.kind not in IMPLIED_SPECIALIZATIONS:
            return
        declared = (
            list(scope.supers)
            if isinstance(scope, M.Definition)
            else list(scope.types) + list(scope.subsets) + list(scope.redefines)
        )
        if declared:
            return
        if any(isinstance(m, M.TerminateAction) for m in scope.members):
            return
        refs = (
            [element.source, element.target]
            if isinstance(element, M.Succession)
            else [element.target]
        )
        for ref in refs:
            if not ref or ref == M.ENTRY_SOURCE:
                continue
            if self._resolves(ref, element):
                continue
            if self._inherited_name(ref.split(".")[0], element):
                continue
            if self._hidden_member(ref.split(".")[0], element):
                continue
            self.report(
                "warning",
                "dangling-succession",
                element,
                f"succession end {ref!r} does not resolve",
            )

    def check_metadata_refs(self, element: M.Element) -> None:
        """metadata-usage-type: metadata must be typed by metadata
        definitions (pilot:validateMetadataUsageType).  Unresolved
        annotation names stay silent -- user-defined keywords may live in
        files that were not loaded."""

        refs = list(element.metadata)
        if isinstance(element, M.MetadataUsage) and element.typed_by:
            refs.append(element.typed_by)
        for ref in refs:
            target = self._resolve_path(ref, element)
            if target is None:
                continue
            if isinstance(target, M.Definition):
                if target.kind not in ("metadata", "extended"):
                    self.report(
                        "error",
                        "metadata-usage-type",
                        element,
                        f"metadata annotation {ref!r} must reference a metadata "
                        f"definition, not a {target.kind} definition",
                    )
            elif isinstance(target, M.Package):
                self.report(
                    "error",
                    "metadata-usage-type",
                    element,
                    f"metadata annotation {ref!r} must reference a metadata "
                    "definition, not a package",
                )

    # -- expressions ------------------------------------------------------------------

    def check_expressions(self, element: M.Definition | M.Usage) -> None:
        local_names = self._local_names(element)
        for owner, expr in self._owned_expressions(element):
            for head in _expression_heads(expr):
                if head in local_names or head in BUILTINS or head == "$":
                    continue
                if self._resolves(head, owner):
                    self._check_implicit(owner, head)
                    continue
                if self._inherited_name(head, owner):
                    continue
                self.report(
                    "warning",
                    "unresolved-name",
                    owner,
                    f"expression name {head!r} does not resolve",
                )
            for parts in _expression_chains(expr):
                if parts[0] in local_names or parts[0] in BUILTINS:
                    continue
                self.check_chain(parts, owner)

    def check_chain(self, parts: tuple[str, ...], owner: M.Element) -> None:
        """unresolved-name for dotted/qualified expression references whose
        *head* resolves but a later segment does not (``d.nope``,
        ``P::D::nope``, ``E::c`` with no such literal).  Honest per the
        lint contract: a failing step is only reported when the container
        it failed in has fully-known members -- an unresolved typing
        anywhere in the container's specialization closure is bottom."""

        scope: M.Element = owner.owner or self.model
        try:
            self.resolver.resolve(parts, scope)
            return  # resolves through scoping, inheritance, and imports
        except ResolutionError:
            pass
        try:
            node: M.Element = self.resolver.resolve(parts[0], scope)
        except ResolutionError:
            return  # an unresolved head is the head check's business
        for segment in parts[1:]:
            if not isinstance(node, M.Namespace):
                return  # chained through a non-namespace: no judgment
            found: M.Element | None = None
            for member in self.resolver.members_of(node, implied=True):
                if segment in (member.name, member.short_name):
                    found = member
                    break
            if found is None:
                if not isinstance(node, (M.Package, M.Definition)):
                    # a usage's member closure (featuring contexts, variant
                    # configurations, subject redefinitions) is richer than
                    # the model's static members: bottom, no judgment
                    return
                if _in_library_package(node):
                    return  # the vendored library projection is not the judge
                if segment == "result":
                    return  # the implicit result parameter is not reified
                if not self._members_fully_known(node):
                    return  # bottom: the container's members are not all known
                self.report(
                    "warning",
                    "unresolved-name",
                    owner,
                    f"expression name {'.'.join(parts)!r} does not resolve: "
                    f"{segment!r} is not a member of {node.qualified_name or node.label}",
                )
                return
            node = found

    def _members_fully_known(self, node: M.Namespace) -> bool:
        """True when every declared specialization reference in ``node``'s
        closure resolves -- i.e. a member lookup miss is a real miss, not
        an unknown propagating up from an unresolved typing."""

        seen: set[int] = set()
        stack: list[M.Element] = [node]
        while stack:
            current = stack.pop()
            if id(current) in seen:
                continue
            seen.add(id(current))
            if not isinstance(current, (M.Definition, M.Usage)):
                continue
            if isinstance(current, M.Definition):
                names = list(current.supers)
            else:
                names = list(current.types) + list(current.subsets) + list(current.redefines)
            for name in names:
                try:
                    general = self.resolver.resolve(name.lstrip("~"), current.owner or self.model)
                except ResolutionError:
                    return False
                if isinstance(general, M.Namespace):
                    stack.append(general)
        return True

    def _inherited_name(self, name: str, context: M.Element) -> bool:
        """True when ``name`` is a member inherited through an *implied*
        specialization (e.g. ``start``/``done`` via ``Actions::Action``)."""

        node: M.Element | None = context
        while node is not None:
            if isinstance(node, (M.Definition, M.Usage)):
                for member in self.resolver.members_of(node, implied=True):
                    if name in (member.name, member.short_name):
                        return True
            node = node.owner or self._parents.get(id(node))
        return False

    def _local_names(self, element: M.Namespace) -> set[str]:
        names: set[str] = set()
        for item in element.iter_tree():
            if isinstance(item, M.ForLoop):
                names.add(item.var)
            elif isinstance(item, M.AcceptAction) and item.payload_name:
                names.add(item.payload_name)
            elif (
                isinstance(item, M.TransitionUsage)
                and item.trigger is not None
                and item.trigger.payload_name
            ):
                names.add(item.trigger.payload_name)
        return names

    def _owned_expressions(self, element: M.Definition | M.Usage) -> list[tuple[M.Element, A.Expr]]:
        out: list[tuple[M.Element, A.Expr]] = []
        if isinstance(element, M.Usage) and element.value is not None:
            out.append((element, element.value.expr))
        if element.result is not None:
            out.append((element, element.result))
        for item in element.members:
            if isinstance(item, M.AssignmentAction):
                out.append((item if item.name else element, item.expr))
            elif isinstance(item, M.IfAction):
                out.append((element, item.condition))
            elif isinstance(item, M.WhileLoop):
                if item.condition is not None:
                    out.append((element, item.condition))
                if item.until is not None:
                    out.append((element, item.until))
            elif isinstance(item, M.ForLoop):
                out.append((element, item.seq))
            elif isinstance(item, M.SendAction):
                out.append((element, item.payload))
            elif isinstance(item, (M.Succession, M.TransitionUsage)) and item.guard is not None:
                out.append((element, item.guard))
        return out

    # -- state machines / calcs -----------------------------------------------------------

    def check_state_machine(self, machine: M.Definition | M.Usage) -> None:
        states = {
            m.name
            for m in machine.members
            if isinstance(m, M.Usage) and m.kind == "state" and m.name
        }
        if not states:
            return
        transitions = [m for m in machine.members if isinstance(m, M.TransitionUsage)]
        has_entry = any(t.source == M.ENTRY_SOURCE for t in transitions)
        if not has_entry:
            self.report(
                "warning",
                "no-entry-transition",
                machine,
                "state machine has states but no 'entry; then <state>;' transition",
            )
        for transition in transitions:
            if transition.source not in (None, M.ENTRY_SOURCE) and transition.source not in states:
                self.report(
                    "error",
                    "unknown-state",
                    machine,
                    f"transition source {transition.source!r} is not a state of {machine.label}",
                )
            if transition.target and transition.target not in states:
                self.report(
                    "error",
                    "unknown-state",
                    machine,
                    f"transition target {transition.target!r} is not a state of {machine.label}",
                )

    def check_calc_result(self, calc: M.Definition | M.Usage) -> None:
        if calc.result is not None:
            return
        for member in calc.members:
            if (
                isinstance(member, M.Usage)
                and member.direction == "return"
                and member.value is not None
            ):
                return
        if (
            not calc.members
            and isinstance(calc, M.Usage)
            and (calc.types or calc.subsets or calc.value)
        ):
            return  # reference/typed calc usages delegate their result
        self.report("warning", "calc-without-result", calc, "calculation has no result expression")

    # -- units ------------------------------------------------------------------

    def _units(self) -> units_module.UnitTable:
        """The unit table for this model (standard + model-derived), built
        lazily once per checker; degrades to an empty table on failure."""

        if self._unit_table is None:
            try:
                self._unit_table = units_module.unit_table(
                    self.model, include_standard=self.resolver.library is not None
                )
            except Exception:
                self._unit_table = units_module.UnitTable()
        return self._unit_table

    def check_units(self, element: M.Definition | M.Usage) -> None:
        """The dimensional lint: walk every owned expression, resolving
        unit annotations (``unresolved-unit``) and checking arithmetic
        over known dimension vectors and scale tags
        (``dimension-mismatch`` / ``scale-mismatch`` / ``mixed-units``)."""

        for owner, expr in self._owned_expressions(element):
            self._unit_meaning(owner, expr, report=True)

    _COMPARISONS = ("<", ">", "<=", ">=", "==", "!=")

    def _unit_meaning(self, owner: M.Element, expr: A.Expr, *, report: bool) -> _Meaning | None:
        """Bottom-up dimensional meaning of ``expr`` (``None`` = unknown),
        emitting diagnostics at conflicting operators when ``report``.

        Unknowns are bottom: a bare literal has *no* dimension (35.0 could
        be anything), unknown operands silence the check, and only two
        *known* vectors can conflict -- per the design's lint contract.
        """

        if isinstance(expr, A.QuantityOp):
            self._unit_meaning(owner, expr.base, report=report)
            return self._annotation_meaning(owner, expr.unit, report=report)
        if isinstance(expr, (A.FeatureRef, A.ChainAccess)):
            return self._feature_meaning(owner, expr)
        if isinstance(expr, A.Unary):
            operand = self._unit_meaning(owner, expr.operand, report=report)
            return operand if expr.op in ("+", "-") else None
        if isinstance(expr, A.Conditional):
            self._unit_meaning(owner, expr.test, report=report)
            then = self._unit_meaning(owner, expr.then, report=report)
            orelse = self._unit_meaning(owner, expr.orelse, report=report)
            if then is not None and orelse is not None and then.dim == orelse.dim:
                return then
            return None
        if isinstance(expr, A.Binary):
            return self._binary_meaning(owner, expr, report=report)
        # anything else: recurse for nested reporting, meaning unknown
        for field_name in ("base", "index", "items", "args", "result"):
            value = getattr(expr, field_name, None)
            if isinstance(value, A.Expr):
                self._unit_meaning(owner, value, report=report)
            elif isinstance(value, tuple):
                for item in value:
                    if isinstance(item, A.Expr):
                        self._unit_meaning(owner, item, report=report)
        return None

    def _binary_meaning(self, owner: M.Element, expr: A.Binary, *, report: bool) -> _Meaning | None:
        left = self._unit_meaning(owner, expr.left, report=report)
        right = self._unit_meaning(owner, expr.right, report=report)
        op = expr.op
        if op in ("+", "-") or op in self._COMPARISONS:
            if left is None or right is None:
                if op in ("+", "-"):
                    return left or right  # additive: the known side carries
                return None
            if len(left.dim.exp) != len(right.dim.exp):
                return None  # different bases (foreign system): incomparable
            table = self._units()
            if (
                op in ("+", "-")
                and left.scale is not None
                and right.scale is not None
                and left.scale != right.scale
            ):
                if report:
                    self.report(
                        "error",
                        "scale-mismatch",
                        owner,
                        f"operands of '{op}' mix measurement scales: "
                        f"{left.display(table)} is {left.scale}-scale, "
                        f"{right.display(table)} is {right.scale}-scale; "
                        "convert explicitly",
                    )
                return None
            if left.dim != right.dim:
                if report:
                    self.report(
                        "warning",
                        "dimension-mismatch",
                        owner,
                        f"operands of '{op}' have different dimensions: "
                        f"{left.display(table)} vs {right.display(table)}",
                    )
                return None
            if left.ident is not None and right.ident is not None and left.ident != right.ident:
                if report and not units_module.units_extra_available():
                    self.report(
                        "warning",
                        "mixed-units",
                        owner,
                        f"operands of '{op}' use different units of one "
                        f"dimension: {left.display(table)} vs {right.display(table)}; "
                        "magnitudes are not normalized without the [units] extra",
                    )
                if op in ("+", "-"):
                    return _Meaning(left.dim, left.scale, None, None)
            if op in ("+", "-"):
                return left
            return None  # comparisons yield booleans
        if op in ("*", "/"):
            # scaling by a bare numeric literal cannot change dimension
            # (`3 * x [m/s]`: the annotation binds to the primary `x`)
            if left is None and right is not None and _literal_number(expr.left) is not None:
                return right if op == "*" else None
            if right is None and left is not None and _literal_number(expr.right) is not None:
                return left
            if left is None or right is None:
                return None
            if len(left.dim.exp) != len(right.dim.exp):
                return None
            dim = left.dim * right.dim if op == "*" else left.dim / right.dim
            scale = "linear" if left.scale == right.scale == "linear" else None
            return _Meaning(dim, scale, None, None)
        if op in ("^", "**"):
            if left is None:
                return None
            power = _literal_number(expr.right)
            if power is None:
                return None
            scale = "linear" if left.scale == "linear" else None
            return _Meaning(left.dim ** Fraction(power).limit_denominator(1000), scale, None, None)
        return None  # logic, range, equality-of-identity, ...

    def _annotation_meaning(
        self, owner: M.Element, unit_expr: A.Expr, *, report: bool
    ) -> _Meaning | None:
        """The meaning carried by a ``[unit]`` annotation.  Reports
        ``unresolved-unit`` (once per dangling reference) when asked."""

        if isinstance(unit_expr, A.FeatureRef):
            info = self._resolve_unit(owner, unit_expr, report=report)
            if info is None:
                return None
            return _Meaning(info.dim, info.scale, info.qname, info.label)
        if isinstance(unit_expr, A.Binary) and unit_expr.op in ("*", "/", "^", "**"):
            left = self._annotation_meaning(owner, unit_expr.left, report=report)
            if unit_expr.op in ("^", "**"):
                power = _literal_number(unit_expr.right)
                if left is None or power is None:
                    return None
                dim = left.dim ** Fraction(power).limit_denominator(1000)
                return _Meaning(dim, left.scale, f"({left.ident}^{power})", None)
            right = self._annotation_meaning(owner, unit_expr.right, report=report)
            if left is None or right is None:
                return None
            if len(left.dim.exp) != len(right.dim.exp):
                return None
            dim = left.dim * right.dim if unit_expr.op == "*" else left.dim / right.dim
            scale = "linear" if left.scale == right.scale == "linear" else None
            ident = f"({left.ident}{unit_expr.op}{right.ident})"
            return _Meaning(dim, scale, ident, None)
        if isinstance(unit_expr, A.Literal) and isinstance(unit_expr.value, (int, float)):
            table = self._units()
            return _Meaning(table.dimensionless, "linear", None, None)
        return None  # exotic annotation shapes stay unchecked

    def _resolve_unit(
        self, owner: M.Element, ref: A.FeatureRef, *, report: bool
    ) -> units_module.UnitInfo | None:
        """Resolve one unit reference; ``unresolved-unit`` when it dangles.

        Bare stdlib unit names (``[kg]``) resolve through the implicit
        library hop *without* tripping ``strict_imports`` -- units are the
        measurement library's vocabulary, and bare references to it are
        the spec's own idiom.  A reference that resolves but is not a
        derivable unit contributes no dimension (bottom, silent).
        """

        scope = owner.owner or self.model
        try:
            element = self.resolver.resolve(ref.parts, scope)
        except ResolutionError:
            if report:
                self.report(
                    "warning",
                    "unresolved-unit",
                    owner,
                    f"unit {'::'.join(ref.parts)!r} does not resolve",
                )
            return None
        qname = element.qualified_name
        return self._units().lookup(qname) if qname else None

    def _feature_meaning(self, owner: M.Element, expr: A.Expr) -> _Meaning | None:
        """Meaning of a name in value position, from its declaration."""

        target = self._resolve_feature(owner, expr)
        if isinstance(target, M.Usage):
            return self._declared_meaning(target)
        return None

    def _resolve_feature(self, owner: M.Element, expr: A.Expr) -> M.Element | None:
        parts: tuple[str, ...]
        if isinstance(expr, A.FeatureRef):
            parts = expr.parts
        elif isinstance(expr, A.ChainAccess) and isinstance(expr.base, A.FeatureRef):
            parts = expr.base.parts + expr.parts
        else:
            return None
        return self._resolve_path(".".join(parts), owner)

    def _resolve_path(self, ref: str, context: M.Element) -> M.Element | None:
        """Resolve a dotted path from ``context``'s scope (the shared walk
        behind ``_resolves``, keeping the element); ``None`` on failure."""

        scope: M.Element = self._scope_of(context)
        for segment in ref.split("."):
            if segment == "$":
                scope = self.model
                continue
            try:
                scope = self.resolver.resolve(segment, scope)
            except ResolutionError:
                return None
        return scope

    def _declared_meaning(self, usage: M.Usage) -> _Meaning | None:
        """Dimensional meaning of an attribute declaration: its value
        expression's annotation first, then quantity typing/subsetting
        (``:> ISQ::mass``), then the declaration it redefines or subsets.
        Memoized and cycle-guarded per checker."""

        key = id(usage)
        if key in self._meanings:
            return self._meanings[key]
        self._meanings[key] = None  # cycle guard: recursion sees bottom
        meaning: _Meaning | None = None
        if usage.value is not None:
            meaning = self._unit_meaning(usage, usage.value.expr, report=False)
        if meaning is None:
            meaning = self._quantity_typing_meaning(usage)
        self._meanings[key] = meaning
        return meaning

    def _quantity_typing_meaning(self, usage: M.Usage) -> _Meaning | None:
        table = self._units()
        scope = usage.owner or self.model
        for ref in list(usage.types) + list(usage.subsets) + list(usage.redefines):
            try:
                element = self.resolver.resolve(ref.lstrip("~").replace(".", "::"), scope)
            except ResolutionError:
                continue
            qname = element.qualified_name
            if qname is not None:
                dim = table.quantity_dimension(qname)
                if dim is not None:
                    # scale/identity unknown: quantity kinds type dimensions,
                    # not units, so only dimension-mismatch can fire
                    return _Meaning(dim, None, None, None)
            if isinstance(element, M.Usage) and element is not usage:
                inherited = self._declared_meaning(element)
                if inherited is not None:
                    return inherited
        return None

    #: the scoreboard convention's utility-shape parameters (kept in sync
    #: with :mod:`longeron.analysis.scoreboard`)
    _ANCHOR_ATTRS = ("ramp0", "ramp1", "target", "limit")

    def check_scoreboard_anchors(self, element: M.Definition | M.Usage) -> None:
        """anchor-dimension-mismatch: a scoreboard-convention ``ramp0`` /
        ``ramp1`` / ``target`` / ``limit`` attribute disagrees
        dimensionally with its sibling ``measure`` -- a ramp anchored in
        minutes scoring a measure computed in hours."""

        attributes = {
            member.name: member
            for member in element.members
            if isinstance(member, M.Usage) and member.kind == "attribute" and member.name
        }
        measure = attributes.get("measure")
        if measure is None:
            return
        measured = self._declared_meaning(measure)
        if measured is None:
            return
        table = self._units()
        for name in self._ANCHOR_ATTRS:
            anchor = attributes.get(name)
            if anchor is None:
                continue
            anchored = self._declared_meaning(anchor)
            if anchored is None:
                continue
            if anchored.dim != measured.dim:
                self.report(
                    "warning",
                    "anchor-dimension-mismatch",
                    anchor,
                    f"'{name}' {anchored.display(table)} disagrees dimensionally "
                    f"with 'measure' {measured.display(table)}",
                )
            elif (
                anchored.ident is not None
                and measured.ident is not None
                and anchored.ident != measured.ident
                and not units_module.units_extra_available()
            ):
                # the design's own example: a ramp anchored in minutes
                # scoring a measure computed in hours -- dimensionally
                # fine, numerically 60x off until the [units] extra
                # converts anchors at scoreboard build time
                self.report(
                    "warning",
                    "anchor-dimension-mismatch",
                    anchor,
                    f"'{name}' {anchored.display(table)} and 'measure' "
                    f"{measured.display(table)} use different units; magnitudes "
                    "are not normalized without the [units] extra",
                )


def _literal_number(expr: A.Expr) -> float | None:
    """The numeric value of a literal (or negated literal) exponent."""

    if isinstance(expr, A.Literal) and isinstance(expr.value, (int, float)):
        return float(expr.value)
    if isinstance(expr, A.Unary) and expr.op == "-":
        inner = _literal_number(expr.operand)
        return -inner if inner is not None else None
    return None


@dataclass(frozen=True)
class _Meaning:
    """What the dimensional lint knows about one expression: its exponent
    vector, its scale tag (``None`` = unknown), and -- when the value is
    still in one declared unit -- that unit's identity and label."""

    dim: units_module.Dim
    scale: str | None
    ident: str | None  # unit identity (qualified name / canonical compound)
    label: str | None  # display label ('kg', 'm / s'); None for derived

    def display(self, table: units_module.UnitTable) -> str:
        dim_text = table.format_dim(self.dim)
        if self.label:
            return f"'{self.label}' [{dim_text}]"
        return f"[{dim_text}]"


def _expression_heads(expr: A.Expr) -> set[str]:
    """First name segments referenced by an expression (skipping locals of
    nested body expressions)."""

    heads: set[str] = set()
    for parts in _walk_references(expr):
        heads.add(parts[0])
    return heads


def _expression_chains(expr: A.Expr) -> set[tuple[str, ...]]:
    """Multi-segment reference paths in an expression (``d.nope``,
    ``P::D::nope``); the single-segment heads are ``_expression_heads``'s
    business."""

    return {parts for parts in _walk_references(expr) if len(parts) > 1 and parts[0] != "$"}


def _walk_references(expr: A.Expr) -> set[tuple[str, ...]]:
    """Reference paths in an expression, with body-expression locals
    excluded: FeatureRef parts, ChainAccess chains over FeatureRef bases,
    and Invocation/Constructor targets."""

    refs: set[tuple[str, ...]] = set()

    def walk(node: A.Expr, bound: frozenset[str]) -> None:
        if isinstance(node, A.FeatureRef):
            if node.parts and node.parts[0] not in bound:
                refs.add(node.parts)
            return
        if isinstance(node, A.ChainAccess) and isinstance(node.base, A.FeatureRef):
            base = node.base
            if base.parts and base.parts[0] not in bound:
                refs.add(base.parts + node.parts)
            return
        if isinstance(node, (A.Invocation, A.Constructor)):
            target = node.target if isinstance(node, A.Invocation) else node.type
            if target and target[0] not in bound:
                refs.add(target)
            for arg in node.args:
                walk(arg, bound)
            for _, arg in node.named:
                walk(arg, bound)
            return
        if isinstance(node, A.BodyExpr):
            inner = bound | {p.name for p in node.params} | {name for name, _ in node.lets}
            for _, let_expr in node.lets:
                walk(let_expr, inner)
            if node.result is not None:
                walk(node.result, inner)
            return
        if isinstance(node, A.ArrowOp):
            walk(node.base, bound)
            for arg in node.args:
                walk(arg, bound)
            if node.body is not None:
                walk(node.body, bound)
            return
        if isinstance(node, (A.CollectOp, A.SelectOp)):
            walk(node.base, bound)
            walk(node.body, bound)
            return
        for field_name in (
            "operand",
            "left",
            "right",
            "test",
            "then",
            "orelse",
            "base",
            "index",
            "items",
        ):
            # note: QuantityOp.unit is deliberately skipped here -- unit
            # references get their own resolution check (unresolved-unit)
            value = getattr(node, field_name, None)
            if isinstance(value, A.Expr):
                walk(value, bound)
            elif isinstance(value, tuple):
                for item in value:
                    if isinstance(item, A.Expr):
                        walk(item, bound)

    walk(expr, frozenset())
    return refs
