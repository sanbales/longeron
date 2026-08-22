"""Transform ANTLR parse trees of SysML v2 text into :mod:`longeron.model` objects.

The builder covers the full textual notation: packages, imports/aliases,
comments/docs, every definition and usage kind (including views,
interfaces, flows, allocations, and metadata), expressions, calculations,
constraints, requirements, actions (assign / if / loops / send / accept /
perform / successions) and state machines.  There is no lossy fallback:
every construct maps to a typed model element, and the test suite asserts
that building produces zero :class:`~longeron.model.Unsupported` elements.
``Unsupported`` survives only as a defensive dead-end for grammar rules
the dispatch fails to claim.
"""

from __future__ import annotations

from typing import ClassVar, Literal, TypeVar, cast

from . import ast as A
from . import model as M
from .errors import BuildError, SourceLocation
from .parser import ParseResult, parse_sysml_text

_BodyStyle = Literal["definition", "action", "calculation", "state", "requirement", "case"]

_ElementT = TypeVar("_ElementT", bound="M.Element")

_CASE_USAGES: tuple[tuple[str, M.UsageKind], ...] = (
    ("caseUsage", "case"),
    ("analysisCaseUsage", "analysis"),
    ("verificationCaseUsage", "verification"),
    ("useCaseUsage", "use_case"),
)

_CONTROL_NODES: tuple[tuple[str, M.ControlNodeKind], ...] = (
    ("mergeNode", "merge"),
    ("decisionNode", "decision"),
    ("joinNode", "join"),
    ("forkNode", "fork"),
)

# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def build_model(result: ParseResult) -> M.Model:
    """Build a model from a :class:`~longeron.parser.ParseResult` (SysML only)."""

    if result.language != "sysml":
        raise BuildError(
            "model building is only supported for SysML sources; "
            "KerML support is parse/validate only"
        )
    return _Builder(result).build()


def loads(text: str, source_name: str = "<text>") -> M.Model:
    """Parse SysML v2 text and build a model."""

    return build_model(parse_sysml_text(text, source_name))


def parse_expression(text: str) -> A.Expr:
    """Parse an expression snippet (e.g. ``"2 + x"``) into an AST node."""

    from .parser import parse_expression_text

    result = parse_expression_text(text)
    return _Builder(result).expr(result.tree)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _unquote_name(text: str) -> str:
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        body = text[1:-1]
        return (
            body.replace("\\\\", "\x00")
            .replace("\\'", "'")
            .replace("\\b", "\b")
            .replace("\\f", "\f")
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
            .replace("\x00", "\\")
        )
    return text


def _unquote_string(text: str) -> str:
    body = text[1:-1] if text.startswith('"') and text.endswith('"') else text
    return (
        body.replace("\\\\", "\x00")
        .replace('\\"', '"')
        .replace("\\b", "\b")
        .replace("\\f", "\f")
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
        .replace("\x00", "\\")
    )


class _Builder:
    def __init__(self, result: ParseResult):
        self.result = result

    # -- generic utilities --------------------------------------------------

    @staticmethod
    def _get(ctx, accessor: str):
        """Call an optional sub-rule accessor, tolerating its absence."""

        fn = getattr(ctx, accessor, None)
        return fn() if fn is not None else None

    def src(self, ctx) -> str:
        """Exact original source text for a context."""

        stream = ctx.start.getInputStream()
        return str(stream.getText(ctx.start.start, ctx.stop.stop))

    def locate(self, element: _ElementT, ctx) -> _ElementT:
        """Stamp the element's declaration position (for lint diagnostics).

        A plain attribute, not a dataclass field: source positions stay out
        of JSON exports and text round-trips.  The innermost dispatcher wins
        (it saw the most specific context), so an already-stamped element is
        left alone.
        """

        if getattr(element, "source_location", None) is None:
            token = ctx.start
            element.source_location = SourceLocation(  # type: ignore[assignment]
                self.result.source_name, token.line, token.column + 1
            )
        return element

    def unsupported(self, ctx, rule: str = "") -> M.Unsupported:
        return M.Unsupported(text=self.src(ctx), rule=rule or type(ctx).__name__)

    def name_of(self, terminal) -> str:
        return _unquote_name(terminal.getText() if hasattr(terminal, "getText") else terminal.text)

    def identification(self, ctx) -> tuple[str | None, str | None]:
        if ctx is None:
            return None, None
        short = self.name_of(ctx.declaredShortName) if ctx.declaredShortName else None
        name = self.name_of(ctx.declaredName) if ctx.declaredName else None
        return short, name

    def qname_parts(self, ctx) -> tuple[str, ...]:
        parts: list[str] = []
        if ctx.DOLLAR():
            parts.append("$")
        parts.extend(self.name_of(tok) for tok in ctx.NAME())
        return tuple(parts)

    def qname(self, ctx) -> str:
        return "::".join(self.qname_parts(ctx))

    def chain_str(self, ctx) -> str:
        """featureChainMember / ownedFeatureTyping / ownedSubsetting etc."""

        if ctx is None:
            return ""
        if hasattr(ctx, "qualifiedName") and ctx.qualifiedName() is not None:
            return self.qname(ctx.qualifiedName())
        for accessor in ("ownedFeatureChain", "ownedFeatureChainMember"):
            if hasattr(ctx, accessor):
                sub = getattr(ctx, accessor)()
                if sub is not None:
                    return self.chain_str(sub)
        if hasattr(ctx, "ownedFeatureChaining"):  # the chain itself
            return ".".join(self.qname(c.qualifiedName()) for c in ctx.ownedFeatureChaining())
        raise BuildError(f"cannot extract chain from {type(ctx).__name__}")

    def visibility(self, member_prefix_ctx) -> M.Visibility | None:
        if member_prefix_ctx is None:
            return None
        vis = member_prefix_ctx.visibility()
        if vis is None:
            return None
        return cast("M.Visibility", vis.getText())

    # -- roots ---------------------------------------------------------------

    def build(self) -> M.Model:
        model = M.Model(source_name=self.result.source_name)
        for item in self.result.tree.packageBodyElement():
            self.package_body_element(item, model)
        return model

    def package_body_element(self, ctx, ns: M.Namespace) -> None:
        if ctx.packageMember() is not None:
            member = ctx.packageMember()
            element = None
            if member.definitionElement() is not None:
                element = self.definition_element(member.definitionElement())
            elif member.usageElement() is not None:
                element = self.usage_element(member.usageElement())
            if element is not None:
                element.visibility = self.visibility(member.memberPrefix())
                ns.add(element)
        elif ctx.aliasMember() is not None:
            ns.add(self.alias(ctx.aliasMember()))
        elif ctx.import_() is not None:
            ns.add(self.import_(ctx.import_()))
        else:  # elementFilterMember
            m = ctx.elementFilterMember()
            element = M.ElementFilter(condition=self.expr(m.ownedExpression()))
            element.visibility = self.visibility(m.memberPrefix())
            ns.add(element)

    # -- imports / aliases / annotations --------------------------------------

    def import_(self, ctx) -> M.Import:
        imp = M.Import()
        prefix = ctx.memberPrefix()
        imp.visibility = self.visibility(prefix)
        imp.is_import_all = ctx.isImportAll is not None
        self.locate(imp, ctx)
        decl = ctx.importDeclaration()
        if decl.membershipImport() is not None:
            mi = decl.membershipImport()
            imp.target = self.qname(mi.importedMembership)
            imp.is_recursive = mi.isRecursive is not None
        else:
            ni = decl.namespaceImport()
            if ni.filterPackage() is not None:
                self._apply_filter_package(imp, ni.filterPackage())
            else:
                imp.target = self.qname(ni.qualifiedName())
                imp.is_namespace = True
                imp.is_recursive = ni.isRecursive is not None
        return imp

    def _apply_filter_package(self, imp: M.Import, ctx) -> None:
        """``import X::*[<filter>]`` -- a filtered namespace import."""

        if ctx.membershipImport() is not None:
            mi = ctx.membershipImport()
            imp.target = self.qname(mi.importedMembership)
            imp.is_recursive = mi.isRecursive is not None
        else:
            imp.target = self.qname(ctx.qualifiedName())
            imp.is_namespace = True
            imp.is_recursive = ctx.isRecursive is not None
        imp.filters = [self.expr(m.ownedExpression()) for m in ctx.filterPackageMember()]

    def alias(self, ctx) -> M.Alias:
        alias = M.Alias()
        alias.visibility = self.visibility(ctx.memberPrefix())
        alias.short_name = self.name_of(ctx.memberShortName) if ctx.memberShortName else None
        alias.name = self.name_of(ctx.memberName) if ctx.memberName else None
        alias.target = self.qname(ctx.memberElement)
        return self.locate(alias, ctx)

    def annotating_element(self, ctx) -> M.Element:
        if ctx.comment() is not None:
            c = ctx.comment()
            short, name = self.identification(c.identification())
            about = [self.qname(a.annotatedElement) for a in c.annotation()]
            locale = _unquote_string(c.locale.text) if c.locale else None
            return M.Comment(
                name=name, short_name=short, about=about, locale=locale, body=c.body.text
            )
        if ctx.documentation() is not None:
            d = ctx.documentation()
            short, name = self.identification(d.identification())
            locale = _unquote_string(d.locale.text) if d.locale else None
            return M.Documentation(name=name, short_name=short, locale=locale, body=d.body.text)
        if ctx.textualRepresentation() is not None:
            t = ctx.textualRepresentation()
            short, name = self.identification(t.identification())
            return M.TextualRepresentation(
                name=name,
                short_name=short,
                language=_unquote_string(t.language.text),
                body=t.body.text,
            )
        return self.metadata_feature(ctx.metadataFeature())

    def metadata_feature(self, ctx) -> M.MetadataUsage:
        """``@Safety { level = 3; }`` / ``metadata m : Safety about x;``"""

        usage = M.MetadataUsage()
        for kw in ctx.prefixMetadataMember():
            usage.metadata.append(self.chain_str(kw.prefixMetadataUsage().ownedFeatureTyping()))
        decl = ctx.metadataFeatureDeclaration()
        if decl.identification() is not None:
            usage.short_name, usage.name = self.identification(decl.identification())
        usage.typed_by = self.chain_str(decl.ownedFeatureTyping())
        usage.about = [self.qname(a.annotatedElement) for a in ctx.annotation()]
        self._fill_metadata_body(usage, ctx.metadataBody())
        return usage

    def _fill_metadata_body(self, ns: M.Namespace, body_ctx) -> None:
        if body_ctx is None or body_ctx.LBRACE() is None:
            return
        for child in body_ctx.getChildren():
            rule = type(child).__name__
            if rule == "DefinitionMemberContext":
                element = self.definition_element(child.definitionElement())
                element.visibility = self.visibility(child.memberPrefix())
                ns.add(element)
            elif rule == "MetadataBodyUsageMemberContext":
                ns.add(self.metadata_body_usage(child.metadataBodyUsage()))
            elif rule == "AliasMemberContext":
                ns.add(self.alias(child))
            elif rule == "Import_Context":
                ns.add(self.import_(child))

    def metadata_body_usage(self, ctx) -> M.MetadataValue:
        value = M.MetadataValue(redefines=self.chain_str(ctx.ownedRedefinition()))
        if ctx.valuePart() is not None:
            value.value = self.feature_value(ctx.valuePart().featureValue())
        body = ctx.metadataBody()
        if body is not None and body.LBRACE() is not None:
            for member in body.metadataBodyUsageMember():
                value.nested.append(self.metadata_body_usage(member.metadataBodyUsage()))
        return value

    def dependency(self, ctx) -> M.Element:
        decl = ctx.dependencyDeclaration()
        short, name = self.identification(decl.identification())
        dep = M.Dependency(name=name, short_name=short)
        for ann in ctx.prefixMetadataAnnotation():
            dep.metadata.append(self.chain_str(ann.prefixMetadataUsage().ownedFeatureTyping()))
        dep.clients = [self.qname(q) for q in decl.client]
        dep.suppliers = [self.qname(q) for q in decl.supplier]
        return dep

    # -- definitions -----------------------------------------------------------

    _DEFINITION_DISPATCH: ClassVar[
        tuple[tuple[str, tuple[M.DefinitionKind, _BodyStyle] | None], ...]
    ] = (
        # accessor -> (kind, body_style); None kind => special handler
        ("package", None),
        ("libraryPackage", None),
        ("annotatingElement", None),
        ("dependency", None),
        ("enumerationDefinition", None),
        ("interfaceDefinition", None),
        ("viewDefinition", None),
        ("extendedDefinition", None),
        ("attributeDefinition", ("attribute", "definition")),
        ("occurrenceDefinition", ("occurrence", "definition")),
        ("individualDefinition", ("individual", "definition")),
        ("itemDefinition", ("item", "definition")),
        ("partDefinition", ("part", "definition")),
        ("connectionDefinition", ("connection", "definition")),
        ("flowDefinition", ("flow", "definition")),
        ("allocationDefinition", ("allocation", "definition")),
        ("portDefinition", ("port", "definition")),
        ("renderingDefinition", ("rendering", "definition")),
        ("metadataDefinition", ("metadata", "definition")),
        ("actionDefinition", ("action", "action")),
        ("calculationDefinition", ("calc", "calculation")),
        ("constraintDefinition", ("constraint", "calculation")),
        ("stateDefinition", ("state", "state")),
        ("requirementDefinition", ("requirement", "requirement")),
        ("concernDefinition", ("concern", "requirement")),
        ("viewpointDefinition", ("viewpoint", "requirement")),
        ("caseDefinition", ("case", "case")),
        ("analysisCaseDefinition", ("analysis", "case")),
        ("verificationCaseDefinition", ("verification", "case")),
        ("useCaseDefinition", ("use_case", "case")),
    )

    def definition_element(self, ctx) -> M.Element:
        return self.locate(self._definition_element(ctx), ctx)

    def _definition_element(self, ctx) -> M.Element:
        for accessor, spec in self._DEFINITION_DISPATCH:
            sub = getattr(ctx, accessor)()
            if sub is None:
                continue
            if accessor == "package":
                return self.package(sub, library=False)
            if accessor == "libraryPackage":
                return self.package(sub, library=True)
            if accessor == "annotatingElement":
                return self.annotating_element(sub)
            if accessor == "dependency":
                return self.dependency(sub)
            if accessor == "enumerationDefinition":
                return self.enumeration_definition(sub)
            if accessor == "interfaceDefinition":
                return self.interface_definition(sub)
            if accessor == "viewDefinition":
                return self.view_definition(sub)
            if accessor == "extendedDefinition":
                return self.extended_definition(sub)
            assert spec is not None
            kind, body_style = spec
            return self.standard_definition(sub, kind, body_style)
        raise BuildError(f"unhandled definition element: {self.src(ctx)!r}")

    def package(self, ctx, library: bool) -> M.Element:
        pkg = M.Package(is_library=library)
        for kw in ctx.prefixMetadataMember():
            pkg.metadata.append(self.chain_str(kw.prefixMetadataUsage().ownedFeatureTyping()))
        if library:
            pkg.is_standard = ctx.isStandard is not None
        short, name = self.identification(ctx.packageDeclaration().identification())
        pkg.short_name, pkg.name = short, name
        body = ctx.packageBody()
        if body.LBRACE() is not None:
            for item in body.packageBodyElement():
                self.package_body_element(item, pkg)
        return pkg

    def _definition_prefix_flags(self, defn: M.Definition, prefix_ctx) -> None:
        if prefix_ctx is None:
            return
        basic = getattr(prefix_ctx, "basicDefinitionPrefix", lambda: None)()
        if basic is not None:
            defn.is_abstract = basic.ABSTRACT() is not None
            defn.is_variation = basic.VARIATION() is not None
        if getattr(prefix_ctx, "isIndividual", None) is not None:
            defn.is_individual = True
        for kw in getattr(prefix_ctx, "definitionExtensionKeyword", lambda: [])():
            typing = kw.prefixMetadataMember().prefixMetadataUsage().ownedFeatureTyping()
            defn.metadata.append(self.chain_str(typing))

    def standard_definition(self, ctx, kind: M.DefinitionKind, body_style: _BodyStyle) -> M.Element:
        defn = M.Definition(kind=kind)
        for prefix_accessor in ("occurrenceDefinitionPrefix", "definitionPrefix"):
            prefix = self._get(ctx, prefix_accessor)
            if prefix is not None:
                self._definition_prefix_flags(defn, prefix)
        basic = self._get(ctx, "basicDefinitionPrefix")  # individualDefinition
        if basic is not None:
            defn.is_abstract = basic.ABSTRACT() is not None
            defn.is_variation = basic.VARIATION() is not None
        if getattr(ctx, "isIndividual", None) is not None:
            defn.is_individual = True  # individualDefinition
        if kind == "metadata" and ctx.ABSTRACT() is not None:
            defn.is_abstract = True
        if hasattr(ctx, "definitionExtensionKeyword"):
            for kw in ctx.definitionExtensionKeyword():
                typing = kw.prefixMetadataMember().prefixMetadataUsage().ownedFeatureTyping()
                defn.metadata.append(self.chain_str(typing))

        if body_style == "definition":
            inner = ctx.definition()
            self._apply_definition_declaration(defn, inner.definitionDeclaration())
            self._fill_definition_body(defn, inner.definitionBody())
            return defn

        self._apply_definition_declaration(defn, ctx.definitionDeclaration())
        if body_style == "action":
            self._fill_action_body(defn, ctx.actionBody())
        elif body_style == "calculation":
            self._fill_calculation_body(defn, ctx.calculationBody())
        elif body_style == "state":
            body = ctx.stateDefBody()
            defn.is_parallel = body.PARALLEL() is not None
            self._fill_state_body(defn, body)
        elif body_style == "requirement":
            self._fill_requirement_body(defn, ctx.requirementBody())
        elif body_style == "case":
            self._fill_case_body(defn, ctx.caseBody())
        return defn

    def _apply_definition_declaration(self, defn: M.Definition, decl_ctx) -> None:
        short, name = self.identification(decl_ctx.identification())
        defn.short_name, defn.name = short, name
        sub = decl_ctx.subclassificationPart()
        if sub is not None:
            defn.supers = [self.qname(s.superClassifier) for s in sub.ownedSubclassification()]

    def enumeration_definition(self, ctx) -> M.Element:
        defn = M.EnumerationDefinition()
        for kw in ctx.definitionExtensionKeyword():
            typing = kw.prefixMetadataMember().prefixMetadataUsage().ownedFeatureTyping()
            defn.metadata.append(self.chain_str(typing))
        self._apply_definition_declaration(defn, ctx.definitionDeclaration())
        body = ctx.enumerationBody()
        if body.LBRACE() is not None:
            for child in body.getChildren():
                rule = type(child).__name__
                if rule == "AnnotatingMemberContext":
                    defn.add(self.annotating_element(child.annotatingElement()))
                elif rule == "EnumerationUsageMemberContext":
                    literal = self._usage_from_usage_ctx(
                        "enum_literal", child.enumeratedValue().usage()
                    )
                    literal.metadata = self._metadata_keywords(child.enumeratedValue())
                    literal.visibility = self.visibility(child.memberPrefix())
                    defn.add(literal)
        return defn

    # -- interface / view / extended definitions --------------------------------

    def interface_definition(self, ctx) -> M.Definition:
        defn = M.Definition(kind="interface")
        self._definition_prefix_flags(defn, ctx.occurrenceDefinitionPrefix())
        self._apply_definition_declaration(defn, ctx.definitionDeclaration())
        body = ctx.interfaceBody()
        if body.LBRACE() is not None:
            for item in body.interfaceBodyItem():
                self._interface_body_item(defn, item)
        return defn

    def _interface_body_item(self, ns: M.Namespace, item) -> None:
        if item.definitionMember() is not None:
            m = item.definitionMember()
            element = self.definition_element(m.definitionElement())
            element.visibility = self.visibility(m.memberPrefix())
            ns.add(element)
        elif item.variantUsageMember() is not None:
            m = item.variantUsageMember()
            element = self.variant_usage_element(m.variantUsageElement())
            if isinstance(element, M.Usage):
                element.is_variant = True
            ns.add(element)
        elif item.interfaceNonOccurrenceUsageMember() is not None:
            m = item.interfaceNonOccurrenceUsageMember()
            sub = m.interfaceNonOccurrenceUsageElement()
            usage = self._try_non_occurrence_usage(sub)
            if usage is None:
                raise BuildError(f"unhandled interface member: {self.src(sub)!r}")
            usage.visibility = self.visibility(m.memberPrefix())
            ns.add(usage)
        elif item.interfaceOccurrenceUsageMember() is not None:
            m = item.interfaceOccurrenceUsageMember()
            sub = m.interfaceOccurrenceUsageElement()
            if sub.defaultInterfaceEnd() is not None:
                element = self._usage_from_usage_ctx(
                    "feature", sub.defaultInterfaceEnd().usage(), {"is_end": True}
                )
            else:
                element = self.occurrence_usage_element(sub)
            element.visibility = self.visibility(m.memberPrefix())
            ns.add(element)
        elif item.aliasMember() is not None:
            ns.add(self.alias(item.aliasMember()))
        elif item.import_() is not None:
            ns.add(self.import_(item.import_()))

    def view_definition(self, ctx) -> M.Definition:
        defn = M.Definition(kind="view")
        self._definition_prefix_flags(defn, ctx.occurrenceDefinitionPrefix())
        self._apply_definition_declaration(defn, ctx.definitionDeclaration())
        body = ctx.viewDefinitionBody()
        if body.LBRACE() is not None:
            for item in body.viewDefinitionBodyItem():
                if not self._view_body_common(defn, item):
                    self._definition_body_item(defn, item.definitionBodyItem())
        return defn

    def _view_body_common(self, ns: M.Namespace, item) -> bool:
        """Handle filter/render members shared by view defs and view usages."""

        if self._get(item, "elementFilterMember") is not None:
            m = item.elementFilterMember()
            filter_el = M.ElementFilter(condition=self.expr(m.ownedExpression()))
            filter_el.visibility = self.visibility(m.memberPrefix())
            ns.add(filter_el)
            return True
        if self._get(item, "viewRenderingMember") is not None:
            m = item.viewRenderingMember()
            render_el = self.view_rendering_usage(m.viewRenderingUsage())
            render_el.visibility = self.visibility(m.memberPrefix())
            ns.add(render_el)
            return True
        return False

    def view_rendering_usage(self, ctx) -> M.Usage:
        usage = M.Usage(kind="render")
        if ctx.ownedReferenceSubsetting() is not None:
            usage.subsets.append(self.chain_str(ctx.ownedReferenceSubsetting()))
            if ctx.featureSpecializationPart() is not None:
                for fs in ctx.featureSpecializationPart().featureSpecialization():
                    self._apply_feature_specialization(usage, fs)
            self._fill_definition_body(usage, ctx.usageBody().definitionBody())
        else:
            usage.metadata = self._metadata_keywords(ctx)
            inline = self._usage_from_usage_ctx("render", ctx.usage())
            inline.metadata = usage.metadata
            return inline
        return usage

    def extended_definition(self, ctx) -> M.Definition:
        defn = M.Definition(kind="extended")
        basic = ctx.basicDefinitionPrefix()
        if basic is not None:
            defn.is_abstract = basic.ABSTRACT() is not None
            defn.is_variation = basic.VARIATION() is not None
        for kw in ctx.definitionExtensionKeyword():
            typing = kw.prefixMetadataMember().prefixMetadataUsage().ownedFeatureTyping()
            defn.metadata.append(self.chain_str(typing))
        inner = ctx.definition()
        self._apply_definition_declaration(defn, inner.definitionDeclaration())
        self._fill_definition_body(defn, inner.definitionBody())
        return defn

    # -- definition bodies ------------------------------------------------------

    def _fill_definition_body(self, ns: M.Namespace, body_ctx) -> None:
        if body_ctx is None or body_ctx.LBRACE() is None:
            return
        for item in body_ctx.definitionBodyItem():
            self._definition_body_item(ns, item)

    def _definition_body_item(self, ns: M.Namespace, item) -> None:
        if item.definitionMember() is not None:
            m = item.definitionMember()
            element = self.definition_element(m.definitionElement())
            element.visibility = self.visibility(m.memberPrefix())
            ns.add(element)
        elif item.variantUsageMember() is not None:
            m = item.variantUsageMember()
            element = self.variant_usage_element(m.variantUsageElement())
            element.visibility = self.visibility(m.memberPrefix())
            if isinstance(element, M.Usage):
                element.is_variant = True
            ns.add(element)
        elif item.nonOccurrenceUsageMember() is not None:
            m = item.nonOccurrenceUsageMember()
            element = self.non_occurrence_usage_element(m.nonOccurrenceUsageElement())
            element.visibility = self.visibility(m.memberPrefix())
            ns.add(element)
        elif item.occurrenceUsageMember() is not None:
            m = item.occurrenceUsageMember()
            element = self.occurrence_usage_element(m.occurrenceUsageElement())
            element.visibility = self.visibility(m.memberPrefix())
            ns.add(element)
        elif item.aliasMember() is not None:
            ns.add(self.alias(item.aliasMember()))
        elif item.import_() is not None:
            ns.add(self.import_(item.import_()))

    # -- usages -------------------------------------------------------------------

    def usage_element(self, ctx) -> M.Element:
        if ctx.nonOccurrenceUsageElement() is not None:
            return self.non_occurrence_usage_element(ctx.nonOccurrenceUsageElement())
        return self.occurrence_usage_element(ctx.occurrenceUsageElement())

    def non_occurrence_usage_element(self, ctx) -> M.Element:
        element = self._try_non_occurrence_usage(ctx)
        if element is None:
            raise BuildError(f"unhandled usage element: {self.src(ctx)!r}")
        return self.locate(element, ctx)

    def _try_non_occurrence_usage(self, ctx) -> M.Element | None:
        sub = self._get(ctx, "defaultReferenceUsage")
        if sub is not None:
            flags = self._ref_or_end_flags(sub)
            return self._usage_from_usage_ctx("feature", sub.usage(), flags)
        sub = self._get(ctx, "referenceUsage")
        if sub is not None:
            flags = self._ref_or_end_flags(sub)
            flags["is_ref"] = True
            return self._usage_from_usage_ctx("ref", sub.usage(), flags)
        sub = self._get(ctx, "attributeUsage")
        if sub is not None:
            flags = self._usage_prefix_flags(sub.usagePrefix())
            return self._usage_from_usage_ctx("attribute", sub.usage(), flags)
        sub = self._get(ctx, "enumerationUsage")
        if sub is not None:
            flags = self._usage_prefix_flags(sub.usagePrefix())
            return self._usage_from_usage_ctx("enum", sub.usage(), flags)
        sub = self._get(ctx, "bindingConnectorAsUsage")
        if sub is not None:
            return self.binding_connector(sub)
        sub = self._get(ctx, "successionAsUsage")
        if sub is not None:
            return self.succession_as_usage(sub)
        sub = self._get(ctx, "extendedUsage")
        if sub is not None:
            flags = self._unextended_prefix_flags(sub.unextendedUsagePrefix())
            flags["metadata"] = self._metadata_keywords(sub)
            return self._usage_from_usage_ctx("extended", sub.usage(), flags)
        return None

    def occurrence_usage_element(self, ctx) -> M.Element:
        if ctx.structureUsageElement() is not None:
            return self.structure_usage_element(ctx.structureUsageElement())
        return self.behavior_usage_element(ctx.behaviorUsageElement())

    _SIMPLE_OCCURRENCE_USAGES: ClassVar[dict[str, M.UsageKind]] = {
        "occurrenceUsage": "occurrence",
        "itemUsage": "item",
        "partUsage": "part",
        "portUsage": "port",
    }

    def structure_usage_element(self, ctx) -> M.Element:
        element = self._try_structure_usage(ctx)
        if element is None:
            raise BuildError(f"unhandled structure usage: {self.src(ctx)!r}")
        return self.locate(element, ctx)

    def _try_structure_usage(self, ctx) -> M.Element | None:
        for accessor, kind in self._SIMPLE_OCCURRENCE_USAGES.items():
            sub = self._get(ctx, accessor)
            if sub is not None:
                flags = self._occurrence_usage_prefix_flags(sub.occurrenceUsagePrefix())
                return self._usage_from_usage_ctx(kind, sub.usage(), flags)
        sub = self._get(ctx, "individualUsage")
        if sub is not None:
            flags = self._basic_usage_prefix_flags(sub.basicUsagePrefix())
            flags["is_individual"] = True
            return self._usage_from_usage_ctx("individual", sub.usage(), flags)
        sub = self._get(ctx, "portionUsage")
        if sub is not None:
            flags = self._basic_usage_prefix_flags(sub.basicUsagePrefix())
            flags["is_individual"] = sub.INDIVIDUAL() is not None
            flags["portion_kind"] = cast("M.PortionKind", sub.portionKindToken().getText())
            return self._usage_from_usage_ctx(flags["portion_kind"], sub.usage(), flags)
        sub = self._get(ctx, "eventOccurrenceUsage")
        if sub is not None:
            return self.event_occurrence_usage(sub)
        sub = self._get(ctx, "connectionUsage")
        if sub is not None:
            return self.connection_usage(sub)
        sub = self._get(ctx, "viewUsage")
        if sub is not None:
            return self.view_usage(sub)
        sub = self._get(ctx, "renderingUsage")
        if sub is not None:
            flags = self._occurrence_usage_prefix_flags(sub.occurrenceUsagePrefix())
            return self._usage_from_usage_ctx("rendering", sub.usage(), flags)
        sub = self._get(ctx, "interfaceUsage")
        if sub is not None:
            return self.interface_usage(sub)
        sub = self._get(ctx, "allocationUsage")
        if sub is not None:
            return self.allocation_usage(sub)
        sub = self._get(ctx, "flowUsage")
        if sub is not None:
            return self.flow_usage(
                sub.flowDeclaration(), sub.definitionBody(), sub.occurrenceUsagePrefix(), "flow"
            )
        sub = self._get(ctx, "successionFlowUsage")
        if sub is not None:
            flow = self.flow_usage(
                sub.flowDeclaration(), sub.definitionBody(), sub.occurrenceUsagePrefix(), "flow"
            )
            flow.is_succession = True
            return flow
        sub = self._get(ctx, "message")
        if sub is not None:
            return self.message_usage(sub)
        return None

    def behavior_usage_element(self, ctx) -> M.Element:
        return self.locate(self._behavior_usage_element(ctx), ctx)

    def _behavior_usage_element(self, ctx) -> M.Element:
        if ctx.actionUsage() is not None:
            c = ctx.actionUsage()
            usage = self._behavioral_usage(
                "action", c.occurrenceUsagePrefix(), c.actionUsageDeclaration()
            )
            self._fill_action_body(usage, c.actionBody())
            return usage
        if ctx.calculationUsage() is not None:
            c = ctx.calculationUsage()
            usage = self._behavioral_usage(
                "calc",
                c.occurrenceUsagePrefix(),
                c.calculationUsageDeclaration().actionUsageDeclaration(),
            )
            self._fill_calculation_body(usage, c.calculationBody())
            return usage
        if ctx.constraintUsage() is not None:
            c = ctx.constraintUsage()
            usage = self._behavioral_usage(
                "constraint", c.occurrenceUsagePrefix(), c.constraintUsageDeclaration()
            )
            self._fill_calculation_body(usage, c.calculationBody())
            return usage
        if ctx.assertConstraintUsage() is not None:
            return self.assert_constraint_usage(ctx.assertConstraintUsage())
        if ctx.requirementUsage() is not None:
            c = ctx.requirementUsage()
            usage = self._behavioral_usage(
                "requirement", c.occurrenceUsagePrefix(), c.constraintUsageDeclaration()
            )
            self._fill_requirement_body(usage, c.requirementBody())
            return usage
        if ctx.concernUsage() is not None:
            c = ctx.concernUsage()
            usage = self._behavioral_usage(
                "concern", c.occurrenceUsagePrefix(), c.constraintUsageDeclaration()
            )
            self._fill_requirement_body(usage, c.requirementBody())
            return usage
        for accessor, kind in _CASE_USAGES:
            sub = getattr(ctx, accessor)()
            if sub is not None:
                usage = self._behavioral_usage(
                    kind, sub.occurrenceUsagePrefix(), sub.constraintUsageDeclaration()
                )
                self._fill_case_body(usage, sub.caseBody())
                return usage
        if ctx.stateUsage() is not None:
            c = ctx.stateUsage()
            usage = self._behavioral_usage(
                "state", c.occurrenceUsagePrefix(), c.actionUsageDeclaration()
            )
            body = c.stateUsageBody()
            usage.is_parallel = body.PARALLEL() is not None
            self._fill_state_body(usage, body)
            return usage
        if ctx.exhibitStateUsage() is not None:
            return self.exhibit_state_usage(ctx.exhibitStateUsage())
        if ctx.viewpointUsage() is not None:
            c = ctx.viewpointUsage()
            usage = self._behavioral_usage(
                "viewpoint", c.occurrenceUsagePrefix(), c.constraintUsageDeclaration()
            )
            self._fill_requirement_body(usage, c.requirementBody())
            return usage
        if ctx.performActionUsage() is not None:
            c = ctx.performActionUsage()
            return self.perform_action(
                c.performActionUsageDeclaration(), c.actionBody(), c.occurrenceUsagePrefix()
            )
        if ctx.includeUseCaseUsage() is not None:
            return self.include_use_case_usage(ctx.includeUseCaseUsage())
        if ctx.satisfyRequirementUsage() is not None:
            return self.satisfy_requirement_usage(ctx.satisfyRequirementUsage())
        raise BuildError(f"unhandled behavior usage: {self.src(ctx)!r}")

    def include_use_case_usage(self, ctx) -> M.Usage:
        usage = M.Usage(kind="include")
        self._apply_flags(usage, self._occurrence_usage_prefix_flags(ctx.occurrenceUsagePrefix()))
        if ctx.ownedReferenceSubsetting() is not None:
            usage.subsets.append(self.chain_str(ctx.ownedReferenceSubsetting()))
            if ctx.featureSpecializationPart() is not None:
                for fs in ctx.featureSpecializationPart().featureSpecialization():
                    self._apply_feature_specialization(usage, fs)
        elif ctx.usageDeclaration() is not None:
            self._apply_usage_declaration(usage, ctx.usageDeclaration())
        if ctx.valuePart() is not None:
            usage.value = self.feature_value(ctx.valuePart().featureValue())
        self._fill_case_body(usage, ctx.caseBody())
        return usage

    def satisfy_requirement_usage(self, ctx) -> M.SatisfyUsage:
        usage = M.SatisfyUsage()
        self._apply_flags(usage, self._occurrence_usage_prefix_flags(ctx.occurrenceUsagePrefix()))
        usage.is_assert = ctx.ASSERT() is not None
        usage.is_negated = ctx.NOT() is not None
        if ctx.ownedReferenceSubsetting() is not None:
            usage.subsets.append(self.chain_str(ctx.ownedReferenceSubsetting()))
            if ctx.featureSpecializationPart() is not None:
                for fs in ctx.featureSpecializationPart().featureSpecialization():
                    self._apply_feature_specialization(usage, fs)
        elif ctx.usageDeclaration() is not None:
            self._apply_usage_declaration(usage, ctx.usageDeclaration())
        if ctx.valuePart() is not None:
            usage.value = self.feature_value(ctx.valuePart().featureValue())
        if ctx.satisfactionSubjectMember() is not None:
            chain = (
                ctx.satisfactionSubjectMember()
                .satisfactionParameter()
                .satisfactionFeatureValue()
                .satisfactionReferenceExpression()
                .featureChainMember()
            )
            usage.by = self.chain_str(chain)
        self._fill_requirement_body(usage, ctx.requirementBody())
        return usage

    def view_usage(self, ctx) -> M.Usage:
        usage = M.Usage(kind="view")
        self._apply_flags(usage, self._occurrence_usage_prefix_flags(ctx.occurrenceUsagePrefix()))
        if ctx.usageDeclaration() is not None:
            self._apply_usage_declaration(usage, ctx.usageDeclaration())
        if ctx.valuePart() is not None:
            usage.value = self.feature_value(ctx.valuePart().featureValue())
        body = ctx.viewBody()
        if body.LBRACE() is not None:
            for item in body.viewBodyItem():
                self._view_usage_body_item(usage, item)
        return usage

    def _view_usage_body_item(self, ns: M.Namespace, item) -> None:
        if self._view_body_common(ns, item):
            return
        if item.expose() is not None:
            e = item.expose()
            exp = M.Expose()
            decl = (
                e.membershipExpose().membershipImport()
                if e.membershipExpose() is not None
                else None
            )
            if decl is not None:
                exp.target = self.qname(decl.importedMembership)
                exp.is_recursive = decl.isRecursive is not None
            else:
                ni = e.namespaceExpose().namespaceImport()
                if ni.filterPackage() is not None:
                    # `expose X::**[@M];` -- mirror _apply_filter_package
                    fp = ni.filterPackage()
                    if fp.membershipImport() is not None:
                        mi = fp.membershipImport()
                        exp.target = self.qname(mi.importedMembership)
                        exp.is_recursive = mi.isRecursive is not None
                    else:
                        exp.target = self.qname(fp.qualifiedName())
                        exp.is_namespace = True
                        exp.is_recursive = fp.isRecursive is not None
                    exp.filters = [self.expr(m.ownedExpression()) for m in fp.filterPackageMember()]
                else:
                    exp.target = self.qname(ni.qualifiedName())
                    exp.is_namespace = True
                    exp.is_recursive = ni.isRecursive is not None
            ns.add(exp)
            return
        if item.satisfyRequirementUsage() is not None:
            ns.add(self.satisfy_requirement_usage(item.satisfyRequirementUsage()))
            return
        if item.requirementConstraintMember() is not None:
            m = item.requirementConstraintMember()
            kind = cast("M.ConstraintKind", m.requirementKind().getText())
            usage = self.requirement_constraint_usage(m.requirementConstraintUsage(), kind)
            usage.visibility = self.visibility(m.memberPrefix())
            ns.add(usage)
            return
        self._definition_body_item(ns, item.definitionBodyItem())

    def interface_usage(self, ctx) -> M.InterfaceUsage:
        usage = M.InterfaceUsage()
        self._apply_flags(usage, self._occurrence_usage_prefix_flags(ctx.occurrenceUsagePrefix()))
        decl = ctx.interfaceUsageDeclaration()
        if decl.usageDeclaration() is not None:
            self._apply_usage_declaration(usage, decl.usageDeclaration())
        if decl.valuePart() is not None:
            usage.value = self.feature_value(decl.valuePart().featureValue())
        part = decl.interfacePart()
        if part is not None:
            binary = part.binaryInterfacePart()
            members = (
                binary.interfaceEndMember()
                if binary is not None
                else part.naryInterfacePart().interfaceEndMember()
            )
            usage.ends = [self.connector_end(m.interfaceEnd()) for m in members]
        body = ctx.interfaceBody()
        if body.LBRACE() is not None:
            for item in body.interfaceBodyItem():
                self._interface_body_item(usage, item)
        return usage

    def allocation_usage(self, ctx) -> M.AllocationUsage:
        usage = M.AllocationUsage()
        self._apply_flags(usage, self._occurrence_usage_prefix_flags(ctx.occurrenceUsagePrefix()))
        decl = ctx.allocationUsageDeclaration()
        if decl.usageDeclaration() is not None:
            self._apply_usage_declaration(usage, decl.usageDeclaration())
        part = decl.connectorPart()
        if part is not None:
            binary = part.binaryConnectorPart()
            members = (
                binary.connectorEndMember()
                if binary is not None
                else part.naryConnectorPart().connectorEndMember()
            )
            usage.ends = [self.connector_end(m.connectorEnd()) for m in members]
        self._fill_definition_body(usage, ctx.usageBody().definitionBody())
        return usage

    def flow_usage(self, decl_ctx, body_ctx, prefix_ctx, kind: M.UsageKind) -> M.FlowUsage:
        usage = M.FlowUsage(kind=kind)
        self._apply_flags(usage, self._occurrence_usage_prefix_flags(prefix_ctx))
        ends = decl_ctx.flowEndMember()
        if decl_ctx.usageDeclaration() is not None or not ends:
            if decl_ctx.usageDeclaration() is not None:
                self._apply_usage_declaration(usage, decl_ctx.usageDeclaration())
            if decl_ctx.valuePart() is not None:
                usage.value = self.feature_value(decl_ctx.valuePart().featureValue())
        if decl_ctx.flowPayloadFeatureMember() is not None:
            payload = decl_ctx.flowPayloadFeatureMember().flowPayloadFeature().payloadFeature()
            usage.payload = self._payload_text(payload)
        if len(ends) == 2:
            usage.source = self._flow_end(ends[0].flowEnd())
            usage.target_end = self._flow_end(ends[1].flowEnd())
        self._fill_definition_body(usage, body_ctx)
        return usage

    def _flow_end(self, ctx) -> str:
        parts: list[str] = []
        sub = ctx.flowEndSubsetting()
        if sub is not None:
            if sub.qualifiedName() is not None:
                parts.append(self.qname(sub.qualifiedName()))
            else:
                prefix = sub.featureChainPrefix()
                parts.extend(self.qname(c.qualifiedName()) for c in prefix.ownedFeatureChaining())
        feature = ctx.flowFeatureMember().flowFeature().flowFeatureRedefinition()
        parts.append(self.qname(feature.redefinedFeature))
        return ".".join(parts)

    def _payload_text(self, payload_ctx) -> str:
        """Canonical text for a flow payload feature (``x : T`` / ``T``)."""

        probe = M.AcceptAction()
        self._payload_feature_into(probe, payload_ctx)
        bits: list[str] = []
        if probe.payload_name:
            bits.append(probe.payload_name)
        if probe.payload_types:
            joined = ", ".join(probe.payload_types)
            bits.append(f": {joined}" if probe.payload_name else joined)
        return " ".join(bits)

    def message_usage(self, ctx) -> M.FlowUsage:
        usage = M.FlowUsage(kind="message")
        self._apply_flags(usage, self._occurrence_usage_prefix_flags(ctx.occurrenceUsagePrefix()))
        decl = ctx.messageDeclaration()
        if decl.usageDeclaration() is not None:
            self._apply_usage_declaration(usage, decl.usageDeclaration())
        if decl.valuePart() is not None:
            usage.value = self.feature_value(decl.valuePart().featureValue())
        if decl.flowPayloadFeatureMember() is not None:
            payload = decl.flowPayloadFeatureMember().flowPayloadFeature().payloadFeature()
            usage.payload = self._payload_text(payload)
        events = decl.messageEventMember()
        if len(events) == 2:
            usage.source = self.chain_str(events[0].messageEvent().ownedReferenceSubsetting())
            usage.target_end = self.chain_str(events[1].messageEvent().ownedReferenceSubsetting())
        self._fill_definition_body(usage, ctx.definitionBody())
        return usage

    def variant_usage_element(self, ctx) -> M.Element:
        return self.locate(self._variant_usage_element(ctx), ctx)

    def _variant_usage_element(self, ctx) -> M.Element:
        if ctx.variantReference() is not None:
            c = ctx.variantReference()
            usage = M.Usage(kind="ref", is_variant=True)
            usage.subsets = [self.chain_str(c.ownedReferenceSubsetting())]
            for fs in c.featureSpecialization():
                self._apply_feature_specialization(usage, fs)
            self._fill_definition_body(usage, c.usageBody().definitionBody())
            return usage
        element = self._try_non_occurrence_usage(ctx)
        if element is None:
            element = self._try_structure_usage(ctx)
        if element is None and self._get(ctx, "behaviorUsageElement") is not None:
            element = self.behavior_usage_element(ctx.behaviorUsageElement())
        return element if element is not None else self.unsupported(ctx, "variantUsageElement")

    # -- prefix flag extraction --------------------------------------------------

    def _ref_prefix_flags(self, ctx) -> dict:
        flags: dict = {}
        if ctx is None:
            return flags
        if ctx.featureDirection() is not None:
            flags["direction"] = cast("M.Direction", ctx.featureDirection().getText())
        if ctx.DERIVED() is not None:
            flags["is_derived"] = True
        if ctx.ABSTRACT() is not None:
            flags["is_abstract"] = True
        if ctx.VARIATION() is not None:
            flags["is_variation"] = True
        if ctx.CONSTANT() is not None:
            flags["is_readonly"] = True
        return flags

    def _basic_usage_prefix_flags(self, ctx) -> dict:
        flags = self._ref_prefix_flags(ctx.refPrefix() if ctx else None)
        if ctx is not None and ctx.REF() is not None:
            flags["is_ref"] = True
        return flags

    def _unextended_prefix_flags(self, ctx) -> dict:
        if ctx is None:
            return {}
        if ctx.endUsagePrefix() is not None:
            return {"is_end": True}
        return self._basic_usage_prefix_flags(ctx.basicUsagePrefix())

    def _metadata_keywords(self, ctx) -> list[str]:
        if ctx is None or not hasattr(ctx, "usageExtensionKeyword"):
            return []
        out = []
        for kw in ctx.usageExtensionKeyword():
            typing = kw.prefixMetadataMember().prefixMetadataUsage().ownedFeatureTyping()
            out.append(self.chain_str(typing))
        return out

    def _usage_prefix_flags(self, ctx) -> dict:
        if ctx is None:
            return {}
        flags = self._unextended_prefix_flags(ctx.unextendedUsagePrefix())
        flags["metadata"] = self._metadata_keywords(ctx)
        return flags

    def _occurrence_usage_prefix_flags(self, ctx) -> dict:
        if ctx is None:
            return {}
        flags = self._unextended_prefix_flags(ctx.unextendedUsagePrefix())
        if ctx.INDIVIDUAL() is not None:
            flags["is_individual"] = True
        if ctx.portionKindToken() is not None:
            flags["portion_kind"] = cast("M.PortionKind", ctx.portionKindToken().getText())
        flags["metadata"] = self._metadata_keywords(ctx)
        return flags

    def _ref_or_end_flags(self, ctx) -> dict:
        if ctx.endUsagePrefix() is not None:
            return {"is_end": True}
        return self._ref_prefix_flags(ctx.refPrefix())

    # -- usage declaration / completion --------------------------------------------

    def _usage_from_usage_ctx(
        self, kind: M.UsageKind, usage_ctx, flags: dict | None = None
    ) -> M.Usage:
        usage = M.Usage(kind=kind)
        self._apply_flags(usage, flags or {})
        self._apply_usage_declaration(usage, usage_ctx.usageDeclaration())
        completion = usage_ctx.usageCompletion()
        if completion.valuePart() is not None:
            usage.value = self.feature_value(completion.valuePart().featureValue())
        self._fill_definition_body(usage, completion.usageBody().definitionBody())
        return usage

    def _apply_flags(self, usage: M.Usage, flags: dict) -> None:
        for key, value in flags.items():
            setattr(usage, key, value)

    def _apply_usage_declaration(self, usage: M.Usage, decl_ctx) -> None:
        if decl_ctx is None:
            return
        short, name = self.identification(decl_ctx.identification())
        usage.short_name, usage.name = short, name
        fsp = decl_ctx.featureSpecializationPart()
        if fsp is not None:
            for fs in fsp.featureSpecialization():
                self._apply_feature_specialization(usage, fs)
            mp = fsp.multiplicityPart()
            if mp is not None:
                self._apply_multiplicity(usage, mp)

    def _apply_feature_specialization(self, usage: M.Usage, fs_ctx) -> None:
        if fs_ctx.typings() is not None:
            t = fs_ctx.typings()
            typings = [t.typedBy().featureTyping(), *t.featureTyping()]
            for typing in typings:
                if typing.ownedFeatureTyping() is not None:
                    usage.types.append(self.chain_str(typing.ownedFeatureTyping()))
                else:  # conjugated port typing '~Q'
                    conj = typing.conjugatedPortTyping()
                    usage.types.append("~" + self.qname(conj.qualifiedName()))
        elif fs_ctx.subsettings() is not None:
            s = fs_ctx.subsettings()
            subs = [s.subsets().ownedSubsetting(), *s.ownedSubsetting()]
            usage.subsets.extend(self.chain_str(x) for x in subs)
        elif fs_ctx.references() is not None:
            usage.references = self.chain_str(fs_ctx.references().ownedReferenceSubsetting())
        elif fs_ctx.crosses() is not None:
            usage.crosses = self.chain_str(fs_ctx.crosses().ownedCrossSubsetting())
        elif fs_ctx.redefinitions() is not None:
            r = fs_ctx.redefinitions()
            redefs = [r.redefines().ownedRedefinition(), *r.ownedRedefinition()]
            usage.redefines.extend(self.chain_str(x) for x in redefs)

    def _apply_multiplicity(self, usage: M.Usage, mp_ctx) -> None:
        mult = M.Multiplicity()
        owned = mp_ctx.ownedMultiplicity()
        if owned is not None:
            rng = owned.multiplicityRange()
            bounds = [self._multiplicity_bound(m) for m in rng.multiplicityExpressionMember()]
            if len(bounds) == 2:
                mult.lower, mult.upper = bounds
            else:
                mult.upper = bounds[0]
        mult.is_ordered = getattr(mp_ctx, "isOrdered", None) is not None
        mult.is_nonunique = getattr(mp_ctx, "isNonunique", None) is not None
        usage.multiplicity = mult

    def _multiplicity_bound(self, ctx) -> A.Expr:
        if ctx.literalExpression() is not None:
            return self.literal(ctx.literalExpression())
        ref = ctx.featureReferenceExpression()
        return A.FeatureRef(
            self.qname_parts(ref.featureReferenceMember().featureReference().qualifiedName())
        )

    def feature_value(self, ctx) -> M.FeatureValue:
        return M.FeatureValue(
            expr=self.expr(ctx.ownedExpression()),
            is_default=ctx.DEFAULT() is not None,
            is_initial=ctx.COLON_EQUALS() is not None,
        )

    # -- behavioral usages ------------------------------------------------------------

    def _behavioral_usage(self, kind: M.UsageKind, prefix_ctx, decl_ctx) -> M.Usage:
        """action/calc/constraint/requirement/case usages share this shape."""

        usage = M.Usage(kind=kind)
        self._apply_flags(usage, self._occurrence_usage_prefix_flags(prefix_ctx))
        if decl_ctx is not None:
            self._apply_usage_declaration(usage, decl_ctx.usageDeclaration())
            if decl_ctx.valuePart() is not None:
                usage.value = self.feature_value(decl_ctx.valuePart().featureValue())
        return usage

    def assert_constraint_usage(self, ctx) -> M.Usage:
        usage = M.Usage(kind="constraint", constraint_kind="assert")
        self._apply_flags(usage, self._occurrence_usage_prefix_flags(ctx.occurrenceUsagePrefix()))
        usage.is_negated = ctx.NOT() is not None
        if ctx.ownedReferenceSubsetting() is not None:
            usage.subsets.append(self.chain_str(ctx.ownedReferenceSubsetting()))
            if ctx.featureSpecializationPart() is not None:
                for fs in ctx.featureSpecializationPart().featureSpecialization():
                    self._apply_feature_specialization(usage, fs)
        elif ctx.constraintUsageDeclaration() is not None:
            decl = ctx.constraintUsageDeclaration()
            self._apply_usage_declaration(usage, decl.usageDeclaration())
            if decl.valuePart() is not None:
                usage.value = self.feature_value(decl.valuePart().featureValue())
        self._fill_calculation_body(usage, ctx.calculationBody())
        return usage

    def exhibit_state_usage(self, ctx) -> M.Usage:
        usage = M.Usage(kind="state", is_exhibit=True)
        self._apply_flags(usage, self._occurrence_usage_prefix_flags(ctx.occurrenceUsagePrefix()))
        if ctx.ownedReferenceSubsetting() is not None:
            usage.subsets.append(self.chain_str(ctx.ownedReferenceSubsetting()))
            if ctx.featureSpecializationPart() is not None:
                for fs in ctx.featureSpecializationPart().featureSpecialization():
                    self._apply_feature_specialization(usage, fs)
        elif ctx.usageDeclaration() is not None:
            self._apply_usage_declaration(usage, ctx.usageDeclaration())
        if ctx.valuePart() is not None:
            usage.value = self.feature_value(ctx.valuePart().featureValue())
        body = ctx.stateUsageBody()
        usage.is_parallel = body.PARALLEL() is not None
        self._fill_state_body(usage, body)
        return usage

    def perform_action(self, decl_ctx, body_ctx, prefix_ctx=None) -> M.Element:
        target = None
        inline: M.Usage | None = None
        if decl_ctx is not None and decl_ctx.ownedReferenceSubsetting() is not None:
            target = self.chain_str(decl_ctx.ownedReferenceSubsetting())
            if decl_ctx.featureSpecializationPart() is not None or (
                body_ctx is not None and body_ctx.LBRACE() is not None
            ):
                inline = M.Usage(kind="action")
                inline.subsets.append(target)
                if decl_ctx.featureSpecializationPart() is not None:
                    for fs in decl_ctx.featureSpecializationPart().featureSpecialization():
                        self._apply_feature_specialization(inline, fs)
        elif decl_ctx is not None and decl_ctx.usageDeclaration() is not None:
            inline = M.Usage(kind="action")
            self._apply_usage_declaration(inline, decl_ctx.usageDeclaration())
        if decl_ctx is not None and decl_ctx.valuePart() is not None:
            if inline is None:
                inline = M.Usage(kind="action")
                if target:
                    inline.subsets.append(target)
            inline.value = self.feature_value(decl_ctx.valuePart().featureValue())
        if inline is not None:
            self._fill_action_body(inline, body_ctx)
            return M.PerformAction(action=inline, target=None if inline.subsets else target)
        return M.PerformAction(target=target)

    # -- connections ------------------------------------------------------------------

    def connector_end(self, ctx) -> M.ConnectorEnd:
        end = M.ConnectorEnd(target=self.chain_str(ctx.ownedReferenceSubsetting()))
        if ctx.declaredName is not None:
            end.name = self.name_of(ctx.declaredName)
        return end

    def connection_usage(self, ctx) -> M.Element:
        usage = M.ConnectionUsage()
        self._apply_flags(usage, self._occurrence_usage_prefix_flags(ctx.occurrenceUsagePrefix()))
        if ctx.usageDeclaration() is not None:
            self._apply_usage_declaration(usage, ctx.usageDeclaration())
        if ctx.valuePart() is not None:
            usage.value = self.feature_value(ctx.valuePart().featureValue())
        part = ctx.connectorPart()
        if part is not None:
            binary = part.binaryConnectorPart()
            members = (
                binary.connectorEndMember()
                if binary is not None
                else part.naryConnectorPart().connectorEndMember()
            )
            usage.ends = [self.connector_end(m.connectorEnd()) for m in members]
        self._fill_definition_body(usage, ctx.usageBody().definitionBody())
        return usage

    def binding_connector(self, ctx) -> M.Element:
        usage = M.BindingConnector()
        self._apply_flags(usage, self._usage_prefix_flags(ctx.usagePrefix()))
        if ctx.usageDeclaration() is not None:
            self._apply_usage_declaration(usage, ctx.usageDeclaration())
        ends = [self.connector_end(m.connectorEnd()) for m in ctx.connectorEndMember()]
        usage.source_end, usage.target_end = ends[0], ends[1]
        self._fill_definition_body(usage, ctx.usageBody().definitionBody())
        return usage

    def succession_as_usage(self, ctx) -> M.Element:
        succession = M.Succession()
        if ctx.usageDeclaration() is not None:
            short, name = self.identification(ctx.usageDeclaration().identification())
            succession.short_name, succession.name = short, name
        ends = [self.connector_end(m.connectorEnd()) for m in ctx.connectorEndMember()]
        succession.source, succession.target = ends[0].target, ends[1].target
        return succession

    def event_occurrence_usage(self, ctx) -> M.Usage:
        usage = M.Usage(kind="event")
        self._apply_flags(usage, self._occurrence_usage_prefix_flags(ctx.occurrenceUsagePrefix()))
        if ctx.ownedReferenceSubsetting() is not None:
            usage.subsets.append(self.chain_str(ctx.ownedReferenceSubsetting()))
            if ctx.featureSpecializationPart() is not None:
                for fs in ctx.featureSpecializationPart().featureSpecialization():
                    self._apply_feature_specialization(usage, fs)
        elif ctx.usageDeclaration() is not None:
            usage.kind = "event_occurrence"
            self._apply_usage_declaration(usage, ctx.usageDeclaration())
        completion = ctx.usageCompletion()
        if completion.valuePart() is not None:
            usage.value = self.feature_value(completion.valuePart().featureValue())
        self._fill_definition_body(usage, completion.usageBody().definitionBody())
        return usage

    # -- action bodies -------------------------------------------------------------------

    def _fill_action_body(self, ns: M.Namespace, body_ctx) -> None:
        if body_ctx is None or body_ctx.LBRACE() is None:
            return
        for item in body_ctx.actionBodyItem():
            self._action_body_item(ns, item)

    def _action_body_item(self, ns: M.Namespace, item) -> None:
        if item.nonBehaviorBodyItem() is not None:
            self._non_behavior_body_item(ns, item.nonBehaviorBodyItem())
            return
        if item.initialNodeMember() is not None:
            init = item.initialNodeMember()
            target = self.qname(init.memberFeature)
            ns.add(M.InitialNode(target=target))
            for succ in item.actionTargetSuccessionMember():
                ns.add(self.action_target_succession(succ.actionTargetSuccession(), source=target))
            return
        if item.guardedSuccessionMember() is not None:
            g = item.guardedSuccessionMember().guardedSuccession()
            succession = M.Succession(
                source=self.chain_str(g.featureChainMember()),
                guard=self.expr(g.guardExpressionMember().ownedExpression()),
                target=self._transition_target(g.transitionSuccessionMember()),
            )
            if g.usageDeclaration() is not None:
                short, name = self.identification(g.usageDeclaration().identification())
                succession.short_name, succession.name = short, name
            ns.add(succession)
            return
        # sourceSuccessionMember? actionBehaviorMember actionTargetSuccessionMember*
        member = item.actionBehaviorMember()
        element: M.Element | None = None
        if member is not None:
            if member.behaviorUsageMember() is not None:
                m = member.behaviorUsageMember()
                element = self.behavior_usage_element(m.behaviorUsageElement())
                element.visibility = self.visibility(m.memberPrefix())
            else:
                m = member.actionNodeMember()
                element = self.action_node(m.actionNode())
                element.visibility = self.visibility(m.memberPrefix())
            ns.add(element)
        source_name = element.name if element is not None else None
        for succ in item.actionTargetSuccessionMember():
            ns.add(self.action_target_succession(succ.actionTargetSuccession(), source=source_name))

    def _non_behavior_body_item(self, ns: M.Namespace, ctx) -> None:
        if ctx.import_() is not None:
            ns.add(self.import_(ctx.import_()))
        elif ctx.aliasMember() is not None:
            ns.add(self.alias(ctx.aliasMember()))
        elif ctx.definitionMember() is not None:
            m = ctx.definitionMember()
            element = self.definition_element(m.definitionElement())
            element.visibility = self.visibility(m.memberPrefix())
            ns.add(element)
        elif ctx.variantUsageMember() is not None:
            m = ctx.variantUsageMember()
            element = self.variant_usage_element(m.variantUsageElement())
            if isinstance(element, M.Usage):
                element.is_variant = True
            ns.add(element)
        elif ctx.nonOccurrenceUsageMember() is not None:
            m = ctx.nonOccurrenceUsageMember()
            element = self.non_occurrence_usage_element(m.nonOccurrenceUsageElement())
            element.visibility = self.visibility(m.memberPrefix())
            ns.add(element)
        elif ctx.structureUsageMember() is not None:
            m = ctx.structureUsageMember()
            element = self.structure_usage_element(m.structureUsageElement())
            element.visibility = self.visibility(m.memberPrefix())
            ns.add(element)

    def action_target_succession(self, ctx, source: str | None) -> M.Succession:
        if ctx.targetSuccession() is not None:
            t = ctx.targetSuccession()
            return M.Succession(
                source=source,
                target=self.connector_end(t.connectorEndMember().connectorEnd()).target,
            )
        if ctx.guardedTargetSuccession() is not None:
            g = ctx.guardedTargetSuccession()
            return M.Succession(
                source=source,
                guard=self.expr(g.guardExpressionMember().ownedExpression()),
                target=self._transition_target(g.transitionSuccessionMember()),
            )
        d = ctx.defaultTargetSuccession()
        return M.Succession(
            source=source,
            is_else=True,
            target=self._transition_target(d.transitionSuccessionMember()),
        )

    def _transition_target(self, ctx) -> str:
        connector_end = ctx.transitionSuccession().connectorEndMember().connectorEnd()
        return self.connector_end(connector_end).target

    # -- action nodes -----------------------------------------------------------------------

    def action_node(self, ctx) -> M.Element:
        if ctx.controlNode() is not None:
            return self.control_node(ctx.controlNode())
        if ctx.sendNode() is not None:
            return self.send_node(ctx.sendNode())
        if ctx.acceptNode() is not None:
            c = ctx.acceptNode()
            return self.accept_from_declaration(c.acceptNodeDeclaration())
        if ctx.assignmentNode() is not None:
            c = ctx.assignmentNode()
            return self.assignment_from_declaration(c.assignmentNodeDeclaration())
        if ctx.terminateNode() is not None:
            c = ctx.terminateNode()
            expr = None
            if c.nodeParameterMember() is not None:
                expr = self.node_parameter(c.nodeParameterMember())
            return M.TerminateAction(target=expr)
        if ctx.ifNode() is not None:
            return self.if_node(ctx.ifNode())
        if ctx.whileLoopNode() is not None:
            return self.while_node(ctx.whileLoopNode())
        return self.for_node(ctx.forLoopNode())

    def control_node(self, ctx) -> M.Element:
        for accessor, kind in _CONTROL_NODES:
            sub = getattr(ctx, accessor)()
            if sub is not None:
                node = M.ControlNode(kind=kind)
                short, name = self.identification(sub.usageDeclaration().identification())
                node.short_name, node.name = short, name
                return node
        raise BuildError("unknown control node")

    def node_parameter(self, ctx) -> A.Expr:
        return self.expr(ctx.nodeParameter().featureBinding().ownedExpression())

    def _decl_name(self, action_node_decl_ctx) -> tuple[str | None, str | None]:
        if action_node_decl_ctx is None:
            return None, None
        decl = action_node_decl_ctx.usageDeclaration()
        if decl is None:
            return None, None
        return self.identification(decl.identification())

    def send_node(self, ctx) -> M.SendAction:
        send = M.SendAction()
        if ctx.actionNodeUsageDeclaration() is not None:
            # LOCAL PATCH form: `action publish send ...` (see grammar patch 8)
            send.short_name, send.name = self._decl_name(ctx.actionNodeUsageDeclaration())
        elif ctx.actionUsageDeclaration() is not None:
            decl = ctx.actionUsageDeclaration()
            short, name = self.identification(decl.usageDeclaration().identification())
            send.short_name, send.name = short, name
        if ctx.nodeParameterMember() is not None:
            send.payload = self.node_parameter(ctx.nodeParameterMember())
        self._apply_sender_receiver(send, ctx.senderReceiverPart())
        return send

    def send_from_declaration(self, ctx) -> M.SendAction:
        send = M.SendAction()
        send.short_name, send.name = self._decl_name(ctx.actionNodeUsageDeclaration())
        send.payload = self.node_parameter(ctx.nodeParameterMember())
        self._apply_sender_receiver(send, ctx.senderReceiverPart())
        return send

    def _apply_sender_receiver(self, send: M.SendAction, ctx) -> None:
        if ctx is None:
            return
        nodes = ctx.nodeParameterMember()
        if ctx.VIA() is not None:
            send.via = self.node_parameter(nodes[0])
            if ctx.TO() is not None:
                send.to = self.node_parameter(nodes[1])
        elif ctx.TO() is not None:
            send.to = self.node_parameter(nodes[0])

    def accept_from_declaration(self, ctx) -> M.AcceptAction:
        accept = M.AcceptAction()
        accept.short_name, accept.name = self._decl_name(ctx.actionNodeUsageDeclaration())
        part = ctx.acceptParameterPart()
        payload = part.payloadParameterMember().payloadParameter()
        self._apply_payload(accept, payload)
        if part.nodeParameterMember() is not None:
            accept.via = self.node_parameter(part.nodeParameterMember())
        return accept

    def _apply_payload(self, accept: M.AcceptAction, ctx) -> None:
        if ctx.payloadFeature() is not None:
            self._payload_feature_into(accept, ctx.payloadFeature())
            return
        if ctx.identification() is not None:
            _, accept.payload_name = self.identification(ctx.identification())
        if ctx.payloadFeatureSpecializationPart() is not None:
            self._payload_types_from_fsp(accept, ctx.payloadFeatureSpecializationPart())
        trigger = ctx.triggerValuePart().triggerFeatureValue().triggerExpression()
        accept.trigger_kind = cast("M.TriggerKind", trigger.kind.text)
        if trigger.argumentMember() is not None:
            accept.trigger = self.expr(trigger.argumentMember().argument().argumentValue().value)
        else:
            arg = trigger.argumentExpressionMember().argumentExpression()
            accept.trigger = self.expr(
                arg.argumentExpressionValue()
                .ownedExpressionReference()
                .ownedExpressionMember()
                .ownedExpression()
            )

    def _payload_feature_into(self, accept: M.AcceptAction, pf) -> None:
        if pf.identification() is not None:
            _, accept.payload_name = self.identification(pf.identification())
        if pf.ownedFeatureTyping() is not None:
            accept.payload_types.append(self.chain_str(pf.ownedFeatureTyping()))
        if pf.payloadFeatureSpecializationPart() is not None:
            self._payload_types_from_fsp(accept, pf.payloadFeatureSpecializationPart())

    def _payload_types_from_fsp(self, accept: M.AcceptAction, fsp_ctx) -> None:
        probe = M.Usage()
        for fs in fsp_ctx.featureSpecialization():
            self._apply_feature_specialization(probe, fs)
        accept.payload_types.extend(probe.types)
        accept.payload_types.extend(probe.subsets)

    def assignment_from_declaration(self, ctx) -> M.AssignmentAction:
        assign = M.AssignmentAction()
        assign.short_name, assign.name = self._decl_name(ctx.actionNodeUsageDeclaration())
        target_parts = []
        binding = ctx.assignmentTargetMember().assignmentTargetParameter()
        if binding.assignmentTargetBinding() is not None:
            expr = self.non_feature_chain_primary(
                binding.assignmentTargetBinding().nonFeatureChainPrimaryExpression()
            )
            target_parts.append(expr.to_text())
        target_parts.append(self.chain_str(ctx.featureChainMember()))
        assign.target = ".".join(target_parts)
        assign.expr = self.node_parameter(ctx.nodeParameterMember())
        return assign

    def if_node(self, ctx) -> M.IfAction:
        node = M.IfAction()
        node.short_name, node.name = self._decl_name(
            ctx.actionNodePrefix().actionNodeUsageDeclaration()
            if ctx.actionNodePrefix() is not None
            else None
        )
        node.condition = self.expr(ctx.expressionParameterMember().ownedExpression())
        bodies = ctx.actionBodyParameterMember()
        node.then_body = self.action_body_parameter(bodies[0])
        if ctx.ELSE() is not None:
            if len(bodies) > 1:
                node.else_body = self.action_body_parameter(bodies[1])
            else:
                node.else_body = self.if_node(ctx.ifNodeParameterMember().ifNode())
        return node

    def action_body_parameter(self, member_ctx) -> list[M.Element]:
        body = member_ctx.actionBodyParameter()
        holder = M.Namespace()
        for item in body.actionBodyItem():
            self._action_body_item(holder, item)
        return list(holder.members)

    def while_node(self, ctx) -> M.WhileLoop:
        node = M.WhileLoop()
        exprs = ctx.expressionParameterMember()
        index = 0
        if ctx.WHILE() is not None:
            node.condition = self.expr(exprs[index].ownedExpression())
            index += 1
        node.body = self.action_body_parameter(ctx.actionBodyParameterMember())
        if ctx.UNTIL() is not None:
            node.until = self.expr(exprs[index].ownedExpression())
        return node

    def for_node(self, ctx) -> M.ForLoop:
        node = M.ForLoop()
        decl = ctx.forVariableDeclarationMember().forVariableDeclaration()
        _, name = self.identification(decl.usageDeclaration().identification())
        node.var = name or ""
        node.seq = self.node_parameter(ctx.nodeParameterMember())
        node.body = self.action_body_parameter(ctx.actionBodyParameterMember())
        return node

    # -- calculation bodies --------------------------------------------------------------------

    def _fill_calculation_body(self, ns: M.Definition | M.Usage, body_ctx) -> None:
        if body_ctx is None or body_ctx.LBRACE() is None:
            return
        part = body_ctx.calculationBodyPart()
        for item in part.calculationBodyItem():
            if item.actionBodyItem() is not None:
                self._action_body_item(ns, item.actionBodyItem())
            else:
                ret = item.returnParameterMember()
                element = self.usage_element(ret.usageElement())
                if isinstance(element, M.Usage):
                    element.direction = "return"
                ns.add(element)
        if part.resultExpressionMember() is not None:
            ns.result = self.expr(part.resultExpressionMember().ownedExpression())

    # -- requirement / case bodies ---------------------------------------------------------------

    def _fill_requirement_body(self, ns: M.Namespace, body_ctx) -> None:
        if body_ctx is None or body_ctx.LBRACE() is None:
            return
        for item in body_ctx.requirementBodyItem():
            self._requirement_body_item(ns, item)

    def _requirement_body_item(self, ns: M.Namespace, item) -> None:
        if item.definitionBodyItem() is not None:
            self._definition_body_item(ns, item.definitionBodyItem())
        elif item.subjectMember() is not None:
            m = item.subjectMember()
            usage = self._usage_from_usage_ctx("subject", m.subjectUsage().usage())
            usage.visibility = self.visibility(m.memberPrefix())
            ns.add(usage)
        elif item.requirementConstraintMember() is not None:
            m = item.requirementConstraintMember()
            kind = cast("M.ConstraintKind", m.requirementKind().getText())
            usage = self.requirement_constraint_usage(m.requirementConstraintUsage(), kind)
            usage.visibility = self.visibility(m.memberPrefix())
            ns.add(usage)
        elif item.actorMember() is not None:
            m = item.actorMember()
            usage = self._usage_from_usage_ctx("actor", m.actorUsage().usage())
            usage.visibility = self.visibility(m.memberPrefix())
            ns.add(usage)
        elif item.stakeholderMember() is not None:
            m = item.stakeholderMember()
            usage = self._usage_from_usage_ctx("stakeholder", m.stakeholderUsage().usage())
            usage.visibility = self.visibility(m.memberPrefix())
            ns.add(usage)
        else:  # framedConcernMember / requirementVerificationMember
            self._framed_or_verification(ns, item)

    def _framed_or_verification(self, ns: M.Namespace, item) -> None:
        if item.framedConcernMember() is not None:
            m = item.framedConcernMember()
            c = m.framedConcernUsage()
            usage = M.Usage(kind="frame")
            if c.ownedReferenceSubsetting() is not None:
                usage.subsets.append(self.chain_str(c.ownedReferenceSubsetting()))
                if c.featureSpecializationPart() is not None:
                    for fs in c.featureSpecializationPart().featureSpecialization():
                        self._apply_feature_specialization(usage, fs)
            else:
                usage.metadata = self._metadata_keywords(c)
                decl = c.calculationUsageDeclaration().actionUsageDeclaration()
                self._apply_usage_declaration(usage, decl.usageDeclaration())
                if decl.valuePart() is not None:
                    usage.value = self.feature_value(decl.valuePart().featureValue())
            self._fill_calculation_body(usage, c.calculationBody())
            usage.visibility = self.visibility(m.memberPrefix())
            ns.add(usage)
            return
        m = item.requirementVerificationMember()
        v = m.requirementVerificationUsage()
        usage = M.Usage(kind="verify")
        if v.ownedReferenceSubsetting() is not None:
            usage.subsets.append(self.chain_str(v.ownedReferenceSubsetting()))
            for fs in v.featureSpecialization():
                self._apply_feature_specialization(usage, fs)
        else:
            usage.metadata = self._metadata_keywords(v)
            decl = v.constraintUsageDeclaration()
            self._apply_usage_declaration(usage, decl.usageDeclaration())
            if decl.valuePart() is not None:
                usage.value = self.feature_value(decl.valuePart().featureValue())
        self._fill_requirement_body(usage, v.requirementBody())
        usage.visibility = self.visibility(m.memberPrefix())
        ns.add(usage)

    def requirement_constraint_usage(self, ctx, kind: M.ConstraintKind) -> M.Usage:
        usage = M.Usage(kind="constraint", constraint_kind=kind)
        if ctx.ownedReferenceSubsetting() is not None:
            usage.subsets.append(self.chain_str(ctx.ownedReferenceSubsetting()))
            if ctx.featureSpecializationPart() is not None:
                for fs in ctx.featureSpecializationPart().featureSpecialization():
                    self._apply_feature_specialization(usage, fs)
            self._fill_requirement_body(usage, ctx.requirementBody())
        else:
            usage.metadata = self._metadata_keywords(ctx)
            decl = ctx.constraintUsageDeclaration()
            self._apply_usage_declaration(usage, decl.usageDeclaration())
            if decl.valuePart() is not None:
                usage.value = self.feature_value(decl.valuePart().featureValue())
            self._fill_calculation_body(usage, ctx.calculationBody())
        return usage

    def _fill_case_body(self, ns: M.Definition | M.Usage, body_ctx) -> None:
        if body_ctx is None or body_ctx.LBRACE() is None:
            return
        for item in body_ctx.caseBodyItem():
            if item.actionBodyItem() is not None:
                self._action_body_item(ns, item.actionBodyItem())
            elif item.subjectMember() is not None:
                m = item.subjectMember()
                usage = self._usage_from_usage_ctx("subject", m.subjectUsage().usage())
                usage.visibility = self.visibility(m.memberPrefix())
                ns.add(usage)
            elif item.actorMember() is not None:
                m = item.actorMember()
                usage = self._usage_from_usage_ctx("actor", m.actorUsage().usage())
                usage.visibility = self.visibility(m.memberPrefix())
                ns.add(usage)
            elif item.objectiveMember() is not None:
                m = item.objectiveMember()
                obj = m.objectiveRequirementUsage()
                usage = M.Usage(kind="objective")
                usage.metadata = self._metadata_keywords(obj)
                decl = obj.constraintUsageDeclaration()
                self._apply_usage_declaration(usage, decl.usageDeclaration())
                if decl.valuePart() is not None:
                    usage.value = self.feature_value(decl.valuePart().featureValue())
                self._fill_requirement_body(usage, obj.requirementBody())
                usage.visibility = self.visibility(m.memberPrefix())
                ns.add(usage)
            else:  # returnParameterMember
                ret = item.returnParameterMember()
                element = self.usage_element(ret.usageElement())
                if isinstance(element, M.Usage):
                    element.direction = "return"
                ns.add(element)
        if body_ctx.resultExpressionMember() is not None:
            ns.result = self.expr(body_ctx.resultExpressionMember().ownedExpression())

    # -- state bodies ------------------------------------------------------------------------------

    def _fill_state_body(self, ns: M.Namespace, body_ctx) -> None:
        if body_ctx is None or body_ctx.LBRACE() is None:
            return
        for item in body_ctx.stateBodyItem():
            self._state_body_item(ns, item)

    def _state_body_item(self, ns: M.Namespace, item) -> None:
        if item.nonBehaviorBodyItem() is not None:
            self._non_behavior_body_item(ns, item.nonBehaviorBodyItem())
            return
        if item.entryActionMember() is not None:
            action = self.state_action_usage(item.entryActionMember().stateActionUsage())
            ns.add(M.StateAction(kind="entry", action=action))
            for entry in item.entryTransitionMember():
                ns.add(self.entry_transition(entry))
            return
        if item.doActionMember() is not None:
            action = self.state_action_usage(item.doActionMember().stateActionUsage())
            ns.add(M.StateAction(kind="do", action=action))
            return
        if item.exitActionMember() is not None:
            action = self.state_action_usage(item.exitActionMember().stateActionUsage())
            ns.add(M.StateAction(kind="exit", action=action))
            return
        if item.transitionUsageMember() is not None:
            ns.add(self.transition_usage(item.transitionUsageMember().transitionUsage()))
            return
        # sourceSuccessionMember? behaviorUsageMember targetTransitionUsageMember*
        m = item.behaviorUsageMember()
        element = self.behavior_usage_element(m.behaviorUsageElement())
        element.visibility = self.visibility(m.memberPrefix())
        ns.add(element)
        for tm in item.targetTransitionUsageMember():
            ns.add(self.target_transition_usage(tm.targetTransitionUsage(), source=element.name))

    def state_action_usage(self, ctx) -> M.Element | None:
        if ctx.emptyActionUsage() is not None:
            return None
        if ctx.statePerformActionUsage() is not None:
            c = ctx.statePerformActionUsage()
            return self.perform_action(c.performActionUsageDeclaration(), c.actionBody())
        if ctx.stateAcceptActionUsage() is not None:
            c = ctx.stateAcceptActionUsage()
            return self.accept_from_declaration(c.acceptNodeDeclaration())
        if ctx.stateSendActionUsage() is not None:
            c = ctx.stateSendActionUsage()
            return self.send_from_declaration(c.sendNodeDeclaration())
        c = ctx.stateAssignmentActionUsage()
        return self.assignment_from_declaration(c.assignmentNodeDeclaration())

    def entry_transition(self, ctx) -> M.TransitionUsage:
        transition = M.TransitionUsage(source=M.ENTRY_SOURCE)
        if ctx.guardedTargetSuccession() is not None:
            g = ctx.guardedTargetSuccession()
            transition.guard = self.expr(g.guardExpressionMember().ownedExpression())
            transition.target = self._transition_target(g.transitionSuccessionMember())
        else:
            t = ctx.targetSuccession()
            transition.target = self.connector_end(t.connectorEndMember().connectorEnd()).target
        return transition

    def _trigger_action(self, trigger_member_ctx) -> M.AcceptAction:
        accept = M.AcceptAction()
        part = trigger_member_ctx.triggerAction().acceptParameterPart()
        self._apply_payload(accept, part.payloadParameterMember().payloadParameter())
        if part.nodeParameterMember() is not None:
            accept.via = self.node_parameter(part.nodeParameterMember())
        return accept

    def effect_behavior(self, ctx) -> M.Element | None:
        usage = ctx.effectBehaviorUsage()
        if usage.emptyActionUsage() is not None:
            return None
        if usage.transitionPerformActionUsage() is not None:
            c = usage.transitionPerformActionUsage()
            return self.perform_action(c.performActionUsageDeclaration(), None)
        if usage.transitionAcceptActionUsage() is not None:
            c = usage.transitionAcceptActionUsage()
            return self.accept_from_declaration(c.acceptNodeDeclaration())
        if usage.transitionSendActionUsage() is not None:
            c = usage.transitionSendActionUsage()
            return self.send_from_declaration(c.sendNodeDeclaration())
        c = usage.transitionAssignmentActionUsage()
        return self.assignment_from_declaration(c.assignmentNodeDeclaration())

    def transition_usage(self, ctx) -> M.TransitionUsage:
        transition = M.TransitionUsage()
        if ctx.usageDeclaration() is not None:
            short, name = self.identification(ctx.usageDeclaration().identification())
            transition.short_name, transition.name = short, name
        transition.source = self.chain_str(ctx.featureChainMember())
        if ctx.triggerActionMember() is not None:
            transition.trigger = self._trigger_action(ctx.triggerActionMember())
        if ctx.guardExpressionMember() is not None:
            transition.guard = self.expr(ctx.guardExpressionMember().ownedExpression())
        if ctx.effectBehaviorMember() is not None:
            transition.effect = self.effect_behavior(ctx.effectBehaviorMember())
        transition.target = self._transition_target(ctx.transitionSuccessionMember())
        return transition

    def target_transition_usage(self, ctx, source: str | None) -> M.TransitionUsage:
        transition = M.TransitionUsage(source=source)
        if ctx.triggerActionMember() is not None:
            transition.trigger = self._trigger_action(ctx.triggerActionMember())
        if ctx.guardExpressionMember() is not None:
            transition.guard = self.expr(ctx.guardExpressionMember().ownedExpression())
        if ctx.effectBehaviorMember() is not None:
            transition.effect = self.effect_behavior(ctx.effectBehaviorMember())
        transition.target = self._transition_target(ctx.transitionSuccessionMember())
        return transition

    # -- expressions ---------------------------------------------------------

    _BINARY_ACCESSORS: ClassVar[tuple[str, ...]] = (
        "exponentialOperator",
        "multiplicativeOperator",
        "additiveOperator",
        "rangeOperator",
        "relationalOperator",
        "equalityOperator",
        "bitwiseOperator",
        "conditionalBinaryOperator",
    )

    def expr(self, ctx) -> A.Expr:
        if ctx.IF() is not None:
            exprs = ctx.ownedExpression()
            return A.Conditional(self.expr(exprs[0]), self.expr(exprs[1]), self.expr(exprs[2]))
        if ctx.primaryExpression() is not None:
            return self.primary(ctx.primaryExpression())
        if ctx.unaryOperator() is not None:
            return A.Unary(
                cast("A.UnaryOp", ctx.unaryOperator().getText()), self.expr(ctx.ownedExpression(0))
            )
        if ctx.classificationTestOperator() is not None:
            type_ = self._type_ref(ctx.typeReferenceMember().typeReference())
            operand = self.expr(ctx.ownedExpression(0)) if ctx.ownedExpression() else None
            return A.Classification(
                cast("A.ClassificationOp", ctx.classificationTestOperator().getText()),
                type_,
                operand,
            )
        if ctx.castOperator() is not None:
            type_ = self._type_ref(ctx.typeResultMember().typeReference())
            operand = self.expr(ctx.ownedExpression(0)) if ctx.ownedExpression() else None
            return A.Cast(type_, operand)
        if ctx.metadataAccessExpression() is not None:
            meta = A.MetadataAccess(
                self.qname_parts(
                    ctx.metadataAccessExpression().elementReferenceMember().qualifiedName()
                )
            )
            if ctx.metaclassificationTestOperator() is not None:
                type_ = self._type_ref(ctx.typeReferenceMember().typeReference())
                return A.Classification("@@", type_, meta)
            type_ = self._type_ref(ctx.typeResultMember().typeReference())
            return A.Cast(type_, meta, op="meta")
        if ctx.ALL() is not None:
            return A.AllOf(self._type_ref(ctx.typeReferenceMember().typeReference()))
        for accessor in self._BINARY_ACCESSORS:
            op_ctx = getattr(ctx, accessor)()
            if op_ctx is not None:
                return A.Binary(
                    cast("A.BinaryOp", op_ctx.getText()),
                    self.expr(ctx.ownedExpression(0)),
                    self.expr(ctx.ownedExpression(1)),
                )
        raise BuildError(f"unhandled expression form: {self.src(ctx)!r}")

    def _type_ref(self, type_reference_ctx) -> tuple[str, ...]:
        return self.qname_parts(type_reference_ctx.referenceTyping().qualifiedName())

    def primary(self, ctx) -> A.Expr:
        if ctx.baseExpression() is not None:
            return self.base_expression(ctx.baseExpression())
        if ctx.primaryExpression() is None:  # '(' sequenceExpressionList ')'
            return self._sequence_from_list(ctx.sequenceExpressionList())
        base = self.primary(ctx.primaryExpression())
        if ctx.LBRACKET() is not None:
            items, _ = self._sequence_items(
                ctx.sequenceExpressionListMember().sequenceExpressionList()
            )
            unit = items[0] if len(items) == 1 else A.SequenceExpr(tuple(items))
            return A.QuantityOp(base, unit)
        if ctx.HASH() is not None:
            items, _ = self._sequence_items(
                ctx.sequenceExpressionListMember().sequenceExpressionList()
            )
            return A.IndexOp(base, tuple(items))
        if ctx.featureChainMember() is not None:
            chain = self.chain_str(ctx.featureChainMember())
            return A.ChainAccess(base, tuple(chain.split(".")))
        if ctx.DOT_QUESTION() is not None:
            return A.SelectOp(
                base,
                self.body_expr(
                    ctx.bodyArgumentMember().bodyArgument().bodyArgumentValue().bodyExpression()
                ),
            )
        if ctx.DOT() is not None:  # collect
            return A.CollectOp(
                base,
                self.body_expr(
                    ctx.bodyArgumentMember().bodyArgument().bodyArgumentValue().bodyExpression()
                ),
            )
        # ARROW invocationTypeMember (...)
        name = self.chain_str(ctx.invocationTypeMember().invocationType().ownedFeatureTyping())
        arrow = A.ArrowOp(base, tuple(name.split("::")))
        if ctx.bodyArgumentMember() is not None:
            arrow.body = self.body_expr(
                ctx.bodyArgumentMember().bodyArgument().bodyArgumentValue().bodyExpression()
            )
        elif ctx.functionReferenceArgumentMember() is not None:
            ref = (
                ctx.functionReferenceArgumentMember()
                .functionReferenceArgument()
                .functionReferenceArgumentValue()
                .functionReferenceExpression()
                .functionReferenceMember()
                .functionReference()
            )
            arrow.func = self.qname_parts(ref.referenceTyping().qualifiedName())
        else:
            args, _named = self.argument_list(ctx.argumentList())
            arrow.args = tuple(args)
        return arrow

    def non_feature_chain_primary(self, ctx) -> A.Expr:
        if ctx.baseExpression() is not None:
            return self.base_expression(ctx.baseExpression())
        return self.expr_from_text(self.src(ctx))

    def expr_from_text(self, text: str) -> A.Expr:
        from .parser import parse_expression_text

        result = parse_expression_text(text)
        return _Builder(result).expr(result.tree)

    def _sequence_items(self, list_ctx) -> tuple[list[A.Expr], bool]:
        """Flatten a sequenceExpressionList into items + had-comma flag."""

        if list_ctx.ownedExpression() is not None:
            had_comma = list_ctx.COMMA() is not None
            return [self.expr(list_ctx.ownedExpression())], had_comma
        op = list_ctx.sequenceOperatorExpression()
        first = self.expr(op.ownedExpressionMember().ownedExpression())
        rest, _ = self._sequence_items(op.sequenceExpressionListMember().sequenceExpressionList())
        return [first, *rest], True

    def _sequence_from_list(self, list_ctx) -> A.Expr:
        items, had_comma = self._sequence_items(list_ctx)
        if len(items) == 1 and not had_comma:
            return items[0]  # plain grouping parentheses
        return A.SequenceExpr(tuple(items))

    def base_expression(self, ctx) -> A.Expr:
        if ctx.nullExpression() is not None:
            return A.Literal(None)
        if ctx.literalExpression() is not None:
            return self.literal(ctx.literalExpression())
        if ctx.featureReferenceExpression() is not None:
            qn = (
                ctx.featureReferenceExpression()
                .featureReferenceMember()
                .featureReference()
                .qualifiedName()
            )
            return A.FeatureRef(self.qname_parts(qn))
        if ctx.metadataAccessExpression() is not None:
            return A.MetadataAccess(
                self.qname_parts(
                    ctx.metadataAccessExpression().elementReferenceMember().qualifiedName()
                )
            )
        if ctx.invocationExpression() is not None:
            c = ctx.invocationExpression()
            target = self._instantiated_type(c.instantiatedTypeMember())
            args, named = self.argument_list(c.argumentList())
            return A.Invocation(target, tuple(args), tuple(named))
        if ctx.constructorExpression() is not None:
            c = ctx.constructorExpression()
            target = self._instantiated_type(c.instantiatedTypeMember())
            args, named = self.argument_list(
                c.constructorResultMember().constructorResult().argumentList()
            )
            return A.Constructor(target, tuple(args), tuple(named))
        return self.body_expr(ctx.bodyExpression())

    def _instantiated_type(self, ctx) -> tuple[str, ...]:
        if ctx.instantiatedTypeReference() is not None:
            return self.qname_parts(ctx.instantiatedTypeReference().qualifiedName())
        chain = self.chain_str(ctx.ownedFeatureChainMember())
        return tuple(chain.split("."))

    def argument_list(self, ctx):
        args: list[A.Expr] = []
        named: list[tuple[str, A.Expr]] = []
        if ctx.positionalArgumentList() is not None:
            for member in ctx.positionalArgumentList().argumentMember():
                args.append(self.expr(member.argument().argumentValue().value))
        elif ctx.namedArgumentList() is not None:
            for member in ctx.namedArgumentList().namedArgumentMember():
                arg = member.namedArgument()
                name = self.qname(arg.parameterRedefinition().qualifiedName())
                named.append((name, self.expr(arg.argumentValue().value)))
        return args, named

    def body_expr(self, body_expression_ctx) -> A.BodyExpr:
        expression_body = body_expression_ctx.expressionBodyMember().expressionBody()
        holder = M.Usage(kind="calc")
        self._fill_calculation_body_from_part(holder, expression_body.calculationBodyPart())
        params: list[A.Param] = []
        lets: list[tuple[str, A.Expr]] = []
        for member in holder.members:
            if not isinstance(member, M.Usage) or member.name is None:
                continue
            if member.value is not None:
                lets.append((member.name, member.value.expr))
            elif member.direction != "return":
                params.append(A.Param(member.name, member.direction))
        return A.BodyExpr(tuple(params), tuple(lets), holder.result)

    def _fill_calculation_body_from_part(self, ns: M.Definition | M.Usage, part_ctx) -> None:
        for item in part_ctx.calculationBodyItem():
            if item.actionBodyItem() is not None:
                self._action_body_item(ns, item.actionBodyItem())
            else:
                ret = item.returnParameterMember()
                element = self.usage_element(ret.usageElement())
                if isinstance(element, M.Usage):
                    element.direction = "return"
                ns.add(element)
        if part_ctx.resultExpressionMember() is not None:
            ns.result = self.expr(part_ctx.resultExpressionMember().ownedExpression())

    def literal(self, ctx) -> A.Literal:
        if ctx.literalBoolean() is not None:
            return A.Literal(ctx.literalBoolean().getText() == "true")
        if ctx.literalString() is not None:
            return A.Literal(_unquote_string(ctx.literalString().value.text))
        if ctx.literalInteger() is not None:
            return A.Literal(int(ctx.literalInteger().value.text))
        if ctx.literalReal() is not None:
            return A.Literal(float(ctx.literalReal().getText()))
        return A.Literal(A.INF)  # literalInfinity '*'
