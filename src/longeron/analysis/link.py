"""Linked selection between 2D diagrams and the 3D viewer.

:func:`link_selection` composes two existing public seams -- the
diagrams' click-selection callback (:func:`longeron.diagrams.on_select`,
whose node ids are qualified names) and the mesh viewer's highlight
traitlet (:mod:`longeron.analysis.viewer3d`) -- so clicking a part in a
structure diagram pops the corresponding geometry in the three.js
scene, and clicking a mesh selects the diagram node.

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
* an **M0 individual id** key (``Drone::QuadCopter#0.motors#2``)
  belongs to the usage its dotted path derives from
  (:func:`individual_qname` -- here ``Drone::QuadCopter::motors``), so
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
from .geometry import tag_parts

__all__ = ["individual_qname", "link_selection", "selection_keys"]

#: an M0 instance-index suffix on one dotted id segment (``motors#2``)
_INSTANCE_INDEX = re.compile(r"#\d+$")


def individual_qname(key: str) -> str | None:
    """The M1 usage qualified name an M0 individual id derives from.

    :func:`longeron.m0.interpret` ids are dotted feature paths whose
    segments optionally carry a ``#index`` -- ``Drone::QuadCopter#0.
    motors#2`` is the third motor individual of the root ``QuadCopter``.
    The derivation strips each segment's instance index and joins the
    segments with ``::`` (the first segment is already a qualified
    name), so that id derives ``Drone::QuadCopter::motors`` -- the one
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
    :func:`longeron.analysis.viewer3d.mesh_viewer`.  Every browser (or
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

    def _scene_keys() -> list[str]:
        keys: list[str] = []
        for trait in ("mesh_json", "mesh_b_json"):
            raw = getattr(viewer, trait, "") or ""
            if not raw:
                continue
            for part in json.loads(raw).get("parts", []):
                keys.append(part.get("key") or part["name"])
        return keys

    def _on_elements(elements: list[M.Element]) -> None:
        if not active:
            return
        matched = selection_keys(model, elements, _scene_keys(), interpreter=interp)
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
        diagram.view.selection.ids = ids  # on_select then drives the highlight

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
