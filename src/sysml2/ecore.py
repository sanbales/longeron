"""Bridge to the OMG SysML v2 *specification* metamodel (Stage B prototype).

The pragmatic dataclasses in :mod:`sysml2.model` are shaped like the textual
notation.  The OMG abstract syntax is different: ~175 metaclasses where
ownership goes through reified ``OwningMembership`` elements and every
specialization/typing is itself an element.  This module projects a sysml2
model onto that abstract syntax using the pilot implementation's published
``SysML.ecore`` (vendored under ``sysml2/_spec/``) and pyecore.

Scope (prototype): element skeletons, names, common flags, reified
memberships, and Specialization / FeatureTyping / Subsetting / Redefinition
relationships for targets that resolve inside the model.  Expression trees
and unresolved (standard-library) references are counted in the report, not
mapped.  Requires the ``ecore`` extra: ``pip install longeron[ecore]``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import model as M
from .errors import SysMLError
from .interpreter import Resolver

_ECORE_PATH = Path(__file__).parent / "_spec" / "SysML.ecore"
_UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://sysml2-experiments")

#: definition kind -> spec metaclass (fallback chain applied if abstract)
_DEF_CLASSES: dict[str, str] = {
    "part": "PartDefinition", "item": "ItemDefinition",
    "attribute": "AttributeDefinition", "port": "PortDefinition",
    "action": "ActionDefinition", "calc": "CalculationDefinition",
    "constraint": "ConstraintDefinition",
    "requirement": "RequirementDefinition", "concern": "ConcernDefinition",
    "state": "StateDefinition", "occurrence": "OccurrenceDefinition",
    "individual": "OccurrenceDefinition", "enum": "EnumerationDefinition",
    "connection": "ConnectionDefinition", "flow": "FlowDefinition",
    "allocation": "AllocationDefinition", "metadata": "MetadataDefinition",
    "rendering": "RenderingDefinition", "case": "CaseDefinition",
    "analysis": "AnalysisCaseDefinition",
    "verification": "VerificationCaseDefinition",
    "use_case": "UseCaseDefinition", "view": "ViewDefinition",
    "viewpoint": "ViewpointDefinition", "interface": "InterfaceDefinition",
    "extended": "PartDefinition",
}

#: usage kind -> spec metaclass
_USAGE_CLASSES: dict[str, str] = {
    "part": "PartUsage", "item": "ItemUsage", "attribute": "AttributeUsage",
    "port": "PortUsage", "ref": "ReferenceUsage", "feature": "ReferenceUsage",
    "enum": "EnumerationUsage", "enum_literal": "EnumerationUsage",
    "occurrence": "OccurrenceUsage", "individual": "OccurrenceUsage",
    "snapshot": "OccurrenceUsage", "timeslice": "OccurrenceUsage",
    "event": "OccurrenceUsage", "event_occurrence": "EventOccurrenceUsage",
    "action": "ActionUsage", "calc": "CalculationUsage",
    "constraint": "ConstraintUsage", "requirement": "RequirementUsage",
    "concern": "ConcernUsage", "state": "StateUsage", "case": "CaseUsage",
    "analysis": "AnalysisCaseUsage",
    "verification": "VerificationCaseUsage", "use_case": "UseCaseUsage",
    "subject": "ReferenceUsage", "actor": "PartUsage",
    "stakeholder": "PartUsage", "objective": "RequirementUsage",
    "connection": "ConnectionUsage", "binding": "BindingConnectorAsUsage",
    "interface": "InterfaceUsage", "allocation": "AllocationUsage",
    "flow": "FlowUsage", "message": "FlowUsage", "view": "ViewUsage",
    "viewpoint": "ViewpointUsage", "rendering": "RenderingUsage",
    "render": "RenderingUsage", "satisfy": "SatisfyRequirementUsage",
    "verify": "RequirementUsage", "frame": "ConcernUsage",
    "include": "IncludeUseCaseUsage", "extended": "Usage",
}

#: statement element class -> spec metaclass
_STATEMENT_CLASSES: dict[type, str] = {
    M.AssignmentAction: "AssignmentActionUsage",
    M.IfAction: "IfActionUsage",
    M.WhileLoop: "WhileLoopActionUsage",
    M.ForLoop: "ForLoopActionUsage",
    M.SendAction: "SendActionUsage",
    M.AcceptAction: "AcceptActionUsage",
    M.PerformAction: "PerformActionUsage",
    M.TerminateAction: "TerminateActionUsage",
    M.Succession: "SuccessionAsUsage",
    M.TransitionUsage: "TransitionUsage",
}

_CONTROL_CLASSES = {"merge": "MergeNode", "decision": "DecisionNode",
                    "join": "JoinNode", "fork": "ForkNode"}


@dataclass
class SpecReport:
    """What the projection covered (and what it had to skip)."""

    elements: int = 0
    memberships: int = 0
    relationships: int = 0
    skipped_elements: list[str] = field(default_factory=list)
    unresolved_references: list[str] = field(default_factory=list)

    def __str__(self) -> str:  # pragma: no cover - convenience
        return (f"{self.elements} elements, {self.memberships} memberships, "
                f"{self.relationships} relationships; "
                f"{len(self.skipped_elements)} skipped, "
                f"{len(self.unresolved_references)} unresolved refs")


class SpecModel:
    """A model projected onto the OMG abstract syntax."""

    def __init__(self, root: Any, report: SpecReport,
                 instances: dict[int, Any] | None = None):
        self.root = root
        self.report = report
        #: ``id(model element) -> EObject`` for projections built by
        #: :func:`to_spec` (``None`` for models rebuilt from API records);
        #: only meaningful while the source model is alive
        self.instances = instances

    def save_xmi(self, path) -> None:
        from pyecore.resources import URI

        rset = _resource_set()
        resource = rset.create_resource(URI(str(path)))
        resource.append(self.root)
        resource.save()

    def all_instances(self) -> list[Any]:
        return [self.root, *self.root.eAllContents()]


@lru_cache(maxsize=1)
def _resource_set() -> Any:
    from pyecore.resources import ResourceSet

    return ResourceSet()


@lru_cache(maxsize=1)
def spec_metamodel() -> Any:
    """The vendored OMG SysML v2 EPackage (pyecore)."""

    try:
        rset = _resource_set()
    except ImportError as exc:  # pragma: no cover
        raise SysMLError("the spec metamodel requires pyecore: "
                         "pip install 'longeron[ecore]'") from exc
    resource = rset.get_resource(str(_ECORE_PATH))
    package = resource.contents[0]
    rset.metamodel_registry[package.nsURI] = package
    return package


def spec_class(name: str) -> Any:
    """Look up a metaclass (EClass) by name, e.g. ``PartDefinition``."""

    found = spec_metamodel().getEClassifier(name)
    if found is None:
        raise SysMLError(f"no metaclass named {name!r} in the spec metamodel")
    return found


def spec_class_names() -> list[str]:
    return sorted(c.name for c in spec_metamodel().eClassifiers
                  if c.eClass.name == "EClass")


def to_spec(model: M.Model) -> SpecModel:
    """Project a model onto spec abstract-syntax instances."""

    return _Projector(model).project()


class _Projector:
    def __init__(self, model: M.Model):
        self.model = model
        self.package = spec_metamodel()
        self.resolver = Resolver(model)
        self.report = SpecReport()
        self.instances: dict[int, Any] = {}  # id(model element) -> EObject

    # -- helpers ---------------------------------------------------------------

    def _instantiate(self, class_name: str, source: M.Element | None,
                     path: str) -> Any:
        cls = self.package.getEClassifier(class_name)
        if cls is None or cls.abstract:
            cls = self.package.getEClassifier("PartUsage")
        instance = cls()
        self._set(instance, "elementId",
                  str(uuid.uuid5(_UUID_NAMESPACE, path)))
        if source is not None:
            if source.name:
                self._set(instance, "declaredName", source.name)
            if source.short_name:
                self._set(instance, "declaredShortName", source.short_name)
            self.instances[id(source)] = instance
        self.report.elements += 1
        return instance

    def _set(self, instance: Any, feature: str, value: Any) -> None:
        structural = instance.eClass.findEStructuralFeature(feature)
        if structural is None or structural.derived:
            return
        instance.eSet(feature, value)

    def _own(self, parent: Any, child: Any, membership_class: str,
             path: str) -> Any:
        membership = self._instantiate(membership_class, None,
                                       f"{path}#membership")
        parent.ownedRelationship.append(membership)
        membership.ownedRelatedElement.append(child)
        self.report.memberships += 1
        return membership

    def _membership_class(self, child: M.Element) -> str:
        if isinstance(child, M.Usage):
            if child.direction is not None and \
                    self.package.getEClassifier("ParameterMembership"):
                if child.direction == "return":
                    return "ReturnParameterMembership"
                return "ParameterMembership"
            if child.kind == "subject":
                return "SubjectMembership"
            if child.kind == "actor":
                return "ActorMembership"
            if child.kind == "stakeholder":
                return "StakeholderMembership"
            if child.kind == "objective":
                return "ObjectiveMembership"
            if child.is_variant:
                return "VariantMembership"
            return "FeatureMembership"
        if isinstance(child, (M.Definition, M.Package)):
            return "OwningMembership"
        return "OwningMembership"

    # -- projection ----------------------------------------------------------------

    def project(self) -> SpecModel:
        root = self._instantiate("Namespace", None, "$root")
        for index, member in enumerate(self.model.members):
            self._project_member(root, member, f"$root/{index}")
        self._project_relationships()
        return SpecModel(root, self.report, self.instances)

    def _project_member(self, parent: Any, element: M.Element,
                        path: str) -> None:
        instance = self._project_element(element, path)
        if instance is None:
            return
        self._own(parent, instance, self._membership_class(element), path)
        if isinstance(element, M.Namespace):
            for index, child in enumerate(element.members):
                self._project_member(instance, child, f"{path}/{index}")

    def _project_element(self, element: M.Element, path: str) -> Any:
        if isinstance(element, M.Package):
            instance = self._instantiate(
                "LibraryPackage" if element.is_library else "Package",
                element, path)
            self._set(instance, "isStandard", element.is_standard)
            return instance
        if isinstance(element, M.EnumerationDefinition):
            return self._project_definition(element, path)
        if isinstance(element, M.Definition):
            return self._project_definition(element, path)
        if isinstance(element, M.Usage):
            return self._project_usage(element, path)
        if isinstance(element, M.Documentation):
            instance = self._instantiate("Documentation", element, path)
            self._set(instance, "body", element.text)
            return instance
        if isinstance(element, M.Comment):
            instance = self._instantiate("Comment", element, path)
            self._set(instance, "body", element.text)
            return instance
        if isinstance(element, M.TextualRepresentation):
            instance = self._instantiate("TextualRepresentation", element,
                                         path)
            self._set(instance, "language", element.language)
            self._set(instance, "body", element.body)
            return instance
        if isinstance(element, M.Import):
            class_name = ("NamespaceImport" if element.is_namespace
                          else "MembershipImport")
            instance = self._instantiate(class_name, element, path)
            self._set(instance, "isRecursive", element.is_recursive)
            self._set(instance, "isImportAll", element.is_import_all)
            return instance
        if isinstance(element, M.Dependency):
            return self._instantiate("Dependency", element, path)
        if isinstance(element, M.ControlNode):
            return self._instantiate(_CONTROL_CLASSES[element.kind],
                                     element, path)
        if isinstance(element, M.StateAction) and element.action is not None:
            return self._project_element(element.action, path)
        for model_type, class_name in _STATEMENT_CLASSES.items():
            if isinstance(element, model_type):
                return self._instantiate(class_name, element, path)
        self.report.skipped_elements.append(
            f"{type(element).__name__} ({element.label})")
        return None

    def _project_definition(self, defn: M.Definition, path: str) -> Any:
        class_name = _DEF_CLASSES.get(defn.kind, "PartDefinition")
        instance = self._instantiate(class_name, defn, path)
        self._set(instance, "isAbstract", defn.is_abstract)
        self._set(instance, "isVariation", defn.is_variation)
        self._set(instance, "isIndividual",
                  defn.is_individual or defn.kind == "individual")
        self._set(instance, "isParallel", defn.is_parallel)
        return instance

    def _project_usage(self, usage: M.Usage, path: str) -> Any:
        class_name = _USAGE_CLASSES.get(usage.kind, "Usage")
        instance = self._instantiate(class_name, usage, path)
        self._set(instance, "isAbstract", usage.is_abstract)
        self._set(instance, "isVariation", usage.is_variation)
        self._set(instance, "isIndividual", usage.is_individual)
        self._set(instance, "isParallel", usage.is_parallel)
        self._set(instance, "isEnd", usage.is_end)
        self._set(instance, "isDerived", usage.is_derived)
        self._set(instance, "isReadOnly", usage.is_readonly)
        if usage.direction is not None and usage.direction != "return":
            kind = self.package.getEClassifier("FeatureDirectionKind")
            if kind is not None:
                literal = kind.getEEnumLiteral(usage.direction)
                if literal is not None:
                    self._set(instance, "direction", literal)
        return instance

    # -- relationships ------------------------------------------------------------------

    def _project_relationships(self) -> None:
        for element in self.model.iter_tree():
            instance = self.instances.get(id(element))
            if instance is None:
                continue
            if isinstance(element, M.Definition):
                for target in element.supers:
                    self._relate(element, instance, target,
                                 "Subclassification",
                                 "subclassifier", "superclassifier")
            elif isinstance(element, M.Usage):
                for target in element.types:
                    self._relate(element, instance, target.lstrip("~"),
                                 "FeatureTyping", "typedFeature", "type")
                for target in element.subsets:
                    self._relate(element, instance, target, "Subsetting",
                                 "subsettingFeature", "subsettedFeature")
                for target in element.redefines:
                    self._relate(element, instance, target, "Redefinition",
                                 "redefiningFeature", "redefinedFeature")

    def _relate(self, element: M.Element, instance: Any, target_name: str,
                relationship_class: str, source_role: str,
                target_role: str) -> None:
        target = self._resolve_instance(target_name, element)
        if target is None:
            self.report.unresolved_references.append(target_name)
            return
        relationship = self._instantiate(
            relationship_class, None,
            f"{instance.elementId}#{relationship_class}/{target_name}")
        self._set(relationship, source_role, instance)
        self._set(relationship, target_role, target)
        instance.ownedRelationship.append(relationship)
        self.report.relationships += 1

    def _resolve_instance(self, name: str, context: M.Element) -> Any:
        from .errors import ResolutionError

        scope: M.Element | None = context.owner or self.model
        try:
            for segment in name.split("."):
                found = self.resolver.resolve(segment, scope)
                scope = found
        except ResolutionError:
            return None
        return self.instances.get(id(scope))
