"""Linked selection between 2D diagrams and the 3D viewer.

:func:`link_selection` composes two existing public seams -- the
diagrams' click-selection callback (:func:`longeron.diagrams.on_select`,
whose node ids are qualified names) and the mesh viewer's highlight
traitlet (:mod:`longeron.widgets.viewer3d`) -- so clicking a part in a
structure diagram pops the corresponding geometry in the three.js
scene, and clicking a mesh selects the diagram node.

:func:`bind_config_view` promotes the link from *highlight* to *scene*:
the selection also decides WHICH craft the viewer shows.  Clicking any
element resolves the configuration that owns it
(:func:`owning_config`; a variant usage resolves to the definition
that types it), bakes that craft's scene
(:func:`longeron.analysis.grand.scene_for` dispatches both DeepScout
families), and swaps the viewer -- tutorial 7's inline handler as one
reusable call, and the grand tour's 3D pane.

The bridge between the two worlds is the mesh part ``key`` stamped by
:func:`longeron.analysis.geometry.tag_parts`: the qualified name of the
model part a mesh component renders, or -- for per-instance parts --
the **M0 individual id** from :func:`longeron.m0.interpret`.
Selections resolve to keys with containment-and-typing semantics (see
:func:`selection_keys`):

* a **usage** matches every key equal to its qualified name or nested
  under it, so selecting an assembly highlights all of its rendered
  children;
* a **definition** additionally matches every usage *directly typed* by
  it (``part motors : Motor`` lights up for ``Motor``) -- one def, all
  its occurrences; specializations of the def do not count;
* an **M0 individual id** key (``Rotorcraft::QuadCopter#0.motors#2``)
  belongs to the usage its dotted path derives from
  (:func:`individual_qname` -- here ``Rotorcraft::QuadCopter::motors``), so
  selecting the one M1 usage lights up every rendered individual;
* a selection that touches nothing in the scene **clears** the
  highlight rather than dimming the whole craft -- only affirmative
  matches dim the rest.

Everything runs in Python via traitlets observers (the house pattern of
:mod:`longeron.analysis.dashboard`), so the wiring works headless; only
the pixel-level effects (emissive pop, raycast picking) need a browser.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .. import model as M
from ..interpreter import Interpreter
from ._expr import AnalysisError
from .geometry import tag_parts

__all__ = [
    "ConfigViewBinding",
    "bind_config_view",
    "individual_qname",
    "link_selection",
    "owning_config",
    "selection_keys",
]

#: an M0 instance-index suffix on one dotted id segment (``motors#2``)
_INSTANCE_INDEX = re.compile(r"#\d+$")


def owning_config(model: M.Model, element: M.Element | str) -> M.Definition | None:
    """The top-level configuration definition that owns ``element``.

    Climbs the ownership chain from ``element`` (an element or a
    qualified name) to the outermost :class:`~longeron.model.Definition`
    whose owner is a package -- for the DeepScout program,
    ``Rotorcraft::TriCopter::tailMotor`` (or any attribute, connection, or
    nested part of the tricopter) resolves to the ``TriCopter``
    definition itself, and a configuration resolves to itself.  Pair
    with :func:`longeron.analysis.grand.drone_scene` so a diagram
    selection anywhere inside a configuration renders THAT
    configuration's geometry (the tri boom, the hexa's six arms, the
    coax stacks), not a hardcoded build.  The outermost definition of
    ANY kind is returned (a calc def resolves to itself); callers that
    render hand the result to ``drone_scene``, which rejects
    non-assembly shapes loudly.  Returns ``None`` for elements owned
    by no definition (a package, the model root).
    """

    node: M.Element | None = model.find(element) if isinstance(element, str) else element
    found: M.Definition | None = None
    while node is not None:
        if isinstance(node, M.Definition):
            found = node
        node = node.owner
    return found


def individual_qname(key: str) -> str | None:
    """The M1 usage qualified name an M0 individual id derives from.

    :func:`longeron.m0.interpret` ids are dotted feature paths whose
    segments optionally carry a ``#index`` -- ``Rotorcraft::QuadCopter#0.
    motors#2`` is the third motor individual of the root ``QuadCopter``.
    The derivation strips each segment's instance index and joins the
    segments with ``::`` (the first segment is already a qualified
    name), so that id derives ``Rotorcraft::QuadCopter::motors`` -- the one
    usage all four motor individuals belong to.  Returns ``None`` for a
    key that carries no instance index (a plain qualified name or a
    bare part name), so pure-qname keys keep their exact semantics.
    """

    segments = key.split(".")
    stripped = [_INSTANCE_INDEX.sub("", segment) for segment in segments]
    if stripped == segments:
        return None
    return "::".join(stripped)


def _typed_usage_qnames(model: M.Model, definition: M.Definition, interp: Interpreter) -> set[str]:
    """Qualified names of every usage in ``model`` directly typed by
    ``definition`` (resolved in each usage's own scope, so short type
    names like ``: Rotor`` count)."""

    qnames: set[str] = set()
    for element in model.iter_tree():
        if not isinstance(element, M.Usage) or not element.qualified_name:
            continue
        for type_name in element.types:
            try:
                resolved = interp.resolver.resolve(type_name.lstrip("~"), context=element)
            except Exception:
                continue
            if resolved is definition:
                qnames.add(element.qualified_name)
                break
    return qnames


def selection_keys(
    model: M.Model,
    elements: Iterable[M.Element],
    keys: Iterable[str],
    *,
    interpreter: Interpreter | None = None,
) -> set[str]:
    """The mesh identity keys a diagram selection resolves to.

    ``keys`` are the identities present in a scene (each part's tagged
    ``key`` or bare ``name``); ``elements`` are the selected model
    elements as delivered by :func:`longeron.diagrams.on_select`.  A key
    matches a selected element's qualified name exactly or nested under
    it (``A::b`` matches selecting ``A``); a selected
    :class:`~longeron.model.Definition` also matches through every
    usage directly typed by it.  A key that is an **M0 individual id**
    additionally matches through the usage qualified name it derives
    (see :func:`individual_qname`), so selecting the one ``motors``
    usage matches every ``motors#i`` individual key.  Untagged keys
    (bare part names) only ever match themselves, so an untagged scene
    stays inert.
    """

    interp = interpreter if interpreter is not None else Interpreter(model)
    targets: set[str] = set()
    for element in elements:
        qname = getattr(element, "qualified_name", None)
        if qname:
            targets.add(qname)
        if isinstance(element, M.Definition):
            targets.update(_typed_usage_qnames(model, element, interp))
    matched: set[str] = set()
    for key in keys:
        identities = [key]
        derived = individual_qname(key)
        if derived is not None:
            identities.append(derived)
        if any(
            identity == target or identity.startswith(target + "::")
            for identity in identities
            for target in targets
        ):
            matched.add(key)
    return matched


def _scene_keys(viewer: Any) -> list[str]:
    """The identity keys of every part in the viewer's current scene(s)."""

    keys: list[str] = []
    for trait in ("mesh_json", "mesh_b_json"):
        raw = getattr(viewer, trait, "") or ""
        if not raw:
            continue
        for part in json.loads(raw).get("parts", []):
            keys.append(part.get("key") or part["name"])
    return keys


def _picked_ids(interp: Interpreter, picked: Iterable[str]) -> list[str]:
    """The model identities a raycast pick resolves to.

    A picked M0 individual id projects onto the usage it derives
    (:func:`individual_qname`); keys that resolve to nothing in the
    model (the background, untagged parts) contribute nothing.
    """

    ids: list[str] = []
    for key in picked:
        for identity in (key, individual_qname(key)):
            if identity is None:
                continue
            try:
                interp.resolve(identity)
            except Exception:
                continue
            if identity not in ids:
                ids.append(identity)
            break
    return ids


def link_selection(
    diagram: Any,
    viewer: Any,
    model: M.Model,
    *,
    part_map: Mapping[str, str] | None = None,
    bidirectional: bool = True,
    on_pick: Callable[[list[str]], None] | None = None,
) -> Callable[[], None]:
    """Wire diagram clicks to 3D highlights (and mesh picks back).

    ``diagram`` is an interactive diagram from :mod:`longeron.diagrams`
    (node ids are qualified names), ``viewer`` a widget from
    :func:`longeron.widgets.viewer3d.mesh_viewer`.  Every browser (or
    programmatic) selection on the diagram resolves through
    :func:`selection_keys` and lands on the viewer's ``highlight_json``
    -- affirmative matches pop and dim the rest, no match clears.  A
    convenience ``part_map`` (mesh part name -> qualified name, see
    :func:`longeron.analysis.geometry.tag_parts`) tags the viewer's
    current mesh(es) in place at link time.

    With ``bidirectional`` (the default), a plain click on a mesh
    (reported by the viewer's raycaster on ``picked_json``) selects the
    matching diagram node by qualified name -- a picked **M0 individual
    id** selects the usage it derives (:func:`individual_qname`): the
    diagram has no individual nodes, so M0 -> M1 is a many-to-one
    projection; picks that resolve to nothing in the model -- the
    background, or an untagged part -- clear the diagram selection.
    ``on_pick`` preserves what the projection discards: it is called on
    every pick report with the raw key list exactly as the raycaster
    wrote it (the individual id for a per-instance part, ``[]`` for a
    background click), *before* the diagram selection is driven, and it
    fires even with ``bidirectional=False``.  One traitlets caveat:
    repeating the *identical* pick twice in a row (same part, or
    background twice) does not re-fire -- equal traitlet values coalesce
    -- so the second click is a no-op until something else changes the
    pick.

    Returns an ``unlink()`` callable that deactivates both directions
    and clears the highlight.  (:func:`longeron.diagrams.on_select`
    exposes no disposal handle, so its observer stays attached but
    inert after ``unlink`` -- the one seam this glue cannot close.)
    """

    from ..diagrams import on_select  # lazy: pulls in the vendored ipyelk

    if part_map:
        viewer.mesh_json = json.dumps(tag_parts(json.loads(viewer.mesh_json), part_map))
        if getattr(viewer, "mesh_b_json", ""):
            viewer.mesh_b_json = json.dumps(
                tag_parts(json.loads(viewer.mesh_b_json), part_map, strict=False)
            )

    interp = Interpreter(model)
    active = True

    def _on_elements(elements: list[M.Element]) -> None:
        if not active:
            return
        matched = selection_keys(model, elements, _scene_keys(viewer), interpreter=interp)
        viewer.highlight_json = json.dumps(sorted(matched))

    on_select(diagram, model, _on_elements)

    def _on_pick(change: Any) -> None:
        if not active:
            return
        picked: list[str] = json.loads(change["new"] or "[]")
        if on_pick is not None:
            on_pick(list(picked))
        if not bidirectional:
            return
        diagram.view.selection.ids = _picked_ids(interp, picked)  # on_select drives the highlight

    picking = (bool(bidirectional) or on_pick is not None) and viewer.has_trait("picked_json")
    if picking:
        viewer.observe(_on_pick, names="picked_json")

    def unlink() -> None:
        nonlocal active
        if not active:
            return
        active = False
        if picking:
            viewer.unobserve(_on_pick, names="picked_json")
        viewer.highlight_json = "[]"

    return unlink


class ConfigViewBinding:
    """The disposable handle :func:`bind_config_view` returns.

    ``current`` is the qualified name of the configuration the viewer
    shows (the ``showing`` hint until the first swap, else ``None``).
    ``scenes`` is the bake cache: configuration qualified name ->
    ``(mesh, part_map)``, with ``None`` caching a definition the scene
    baker rejected, so failing bakes are not retried on every click.
    :meth:`unbind` is idempotent, and a binding replaced by a newer
    :func:`bind_config_view` call on the same viewer is already
    inactive.
    """

    def __init__(self, viewer: Any) -> None:
        self.current: str | None = None
        self.scenes: dict[str, tuple[dict[str, Any], dict[str, str]] | None] = {}
        self._viewer = viewer
        self._active = True
        self._disposers: list[Callable[[], None]] = []

    def unbind(self) -> None:
        """Deactivate both directions and clear the highlight.

        The scene stays as last rendered.
        """

        if not self._active:
            return
        self._active = False
        for dispose in self._disposers:
            dispose()
        self._viewer.highlight_json = "[]"
        if getattr(self._viewer, "_lgn_config_view", None) is self:
            self._viewer._lgn_config_view = None


def bind_config_view(
    source: Any,
    viewer: Any,
    model: M.Model,
    *,
    showing: str | None = None,
    scene: Callable[[M.Model, str], tuple[dict[str, Any], dict[str, str]]] | None = None,
    decorate: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    bidirectional: bool = True,
) -> ConfigViewBinding:
    """Selections drive WHICH craft the 3D viewer shows, not just the
    highlight.

    ``source`` is anything with the house selection surface: an
    interactive diagram from :mod:`longeron.diagrams` (selections
    arrive through :func:`longeron.diagrams.on_select`), or any widget
    with the explorer protocol's ``on_select(callback)`` /
    ``selected`` pair (the model explorer's tree, the scoreboard
    widget) delivering qualified names.  Every selection resolves to
    its craft: :func:`owning_config` climbs from the clicked element
    to the outermost definition, and -- the one extension -- a variant
    usage whose owning definition is not bakeable resolves to the
    definition that *types* it, so the mission catalog's
    ``teardropQuad`` variant renders the ``TeardropQuad`` shell.  The
    resolved configuration bakes through ``scene`` (default:
    :func:`longeron.analysis.grand.scene_for`, which dispatches both
    the MultiRotor build family and the fleet airframe shells), the
    viewer swaps to it, the viewer label takes the qualified name, and
    :func:`selection_keys` lights the selected parts -- per M0
    individual where the scene carries individual ids.

    The scene only swaps when the resolved configuration CHANGES:
    re-selecting inside the shown craft never rewrites ``mesh_json``,
    and elements that resolve to no bakeable configuration keep the
    current scene (their highlight semantics are unchanged --
    affirmative matches pop, no match clears).  ``showing`` names the
    configuration the viewer's initial mesh renders so re-selecting it
    is such a no-op too.  ``decorate`` maps ``(qname, mesh) -> mesh``
    immediately before each swap is written -- the grand dashboard
    re-appends its translucent view cone to its home craft here -- so
    a swap is always ONE traitlet write.

    With ``bidirectional`` (the default), a mesh pick selects the
    matching source node exactly as in :func:`link_selection` (a
    picked M0 individual id selects the usage it derives; background
    picks clear), driving ``source.view.selection.ids`` on a diagram
    and ``source.selected`` on an explorer-protocol source.

    Rebinding is idempotent: a viewer holds ONE binding, and binding
    again (any source) unbinds the previous one first.  Returns a
    :class:`ConfigViewBinding`; neither diagram ``on_select`` nor the
    explorer protocol expose observer disposal, so ``unbind`` leaves
    those callbacks attached but inert (the :func:`link_selection`
    caveat).
    """

    previous = getattr(viewer, "_lgn_config_view", None)
    if isinstance(previous, ConfigViewBinding):
        previous.unbind()

    if scene is None:
        from .grand import scene_for  # lazy: grand pulls the widget stack

        scene = scene_for

    interp = Interpreter(model)
    binding = ConfigViewBinding(viewer)
    binding.current = showing
    viewer._lgn_config_view = binding

    def _bake(qname: str) -> tuple[dict[str, Any], dict[str, str]] | None:
        if qname not in binding.scenes:
            try:
                binding.scenes[qname] = scene(model, qname)
            except Exception:
                binding.scenes[qname] = None
        return binding.scenes[qname]

    def _config_qnames(element: M.Element) -> Iterable[str]:
        config = owning_config(model, element)
        if config is not None and config.qualified_name:
            yield config.qualified_name
        if isinstance(element, M.Usage):  # a variant usage renders its type
            for type_name in element.types:
                try:
                    resolved = interp.resolver.resolve(type_name.lstrip("~"), context=element)
                except Exception:
                    continue
                qname = getattr(resolved, "qualified_name", None)
                if isinstance(resolved, M.Definition) and qname:
                    yield qname

    def _on_elements(elements: list[M.Element]) -> None:
        if not binding._active:
            return
        for element in elements:
            baked = next(
                (
                    (qname, hit)
                    for qname in _config_qnames(element)
                    if (hit := _bake(qname)) is not None
                ),
                None,
            )
            if baked is None:
                continue  # no bakeable craft: keep the current scene
            qname, (mesh, _part_map) = baked
            if qname != binding.current:
                viewer.mesh_json = json.dumps(decorate(qname, mesh) if decorate else mesh)
                viewer.label = qname
                binding.current = qname
            break
        matched = selection_keys(model, elements, _scene_keys(viewer), interpreter=interp)
        viewer.highlight_json = json.dumps(sorted(matched))

    if hasattr(source, "view") and hasattr(source.view, "selection"):  # a diagram
        from ..diagrams import on_select  # lazy: pulls in the vendored ipyelk

        on_select(source, model, _on_elements)

        def _drive(ids: list[str]) -> None:
            source.view.selection.ids = ids

    elif callable(getattr(source, "on_select", None)):  # the explorer protocol

        def _from_ids(ids: list[str]) -> None:
            elements = []
            for identifier in ids:
                try:
                    elements.append(interp.resolve(identifier))
                except Exception:
                    continue
            _on_elements(elements)

        source.on_select(_from_ids)

        def _drive(ids: list[str]) -> None:
            if hasattr(source, "selected"):
                source.selected = ids

    else:
        raise AnalysisError(
            "bind_config_view: source exposes neither a diagram selection "
            "(.view.selection) nor the explorer protocol (.on_select)"
        )

    def _on_pick(change: Any) -> None:
        if not binding._active:
            return
        picked: list[str] = json.loads(change["new"] or "[]")
        _drive(_picked_ids(interp, picked))  # the selection then drives the highlight

    if bidirectional and viewer.has_trait("picked_json"):
        viewer.observe(_on_pick, names="picked_json")
        binding._disposers.append(lambda: viewer.unobserve(_on_pick, names="picked_json"))

    return binding
