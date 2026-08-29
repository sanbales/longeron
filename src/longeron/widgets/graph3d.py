"""Explore the RDF projection as a 3D force-directed graph (anywidget).

:func:`graph_viewer` turns the :mod:`longeron.rdf` projection of a model
into an interactive three.js scene: every element is an instanced
sphere, every relationship triple a line segment, and a deterministic
force-directed embedding (computed kernel-side, in numpy) gives the
graph its shape.  Instancing keeps the whole default view at a handful
of draw calls, so orbiting a five-figure graph stays smooth.

The default view is deliberately smaller than the triple count.  A
projected model is mostly *literals* -- names, kinds, flags, attribute
values -- and drawing them as nodes would drown the structure (the
DeepScout program projects to ~8.6k triples but only ~1.1k elements).
So the view shows **element nodes and relationship edges** only:
containment (``ownedMember``), specialization (``specializes`` /
``subsets`` / ``redefines``), typing (``definedBy`` / ``references`` /
``crosses``), connections (``connects``), satisfaction
(``satisfiedBy``), and the reference family (imports, aliases,
dependencies, metadata).  Every literal folds into its element's hover
payload instead; ``literals=True`` opts value literals
(``sysml:value`` / ``evaluatedValue`` / ``valueExpression``) back in as
leaf nodes when the full picture is wanted.

Nodes speak the explorer's kind-color language: the same family colors
the tree rows use as chips (structure blue, behavior purple, data
green, connector amber, requirement red, package gray) color the
spheres, and node size grows with degree, so hubs -- the shared
``MultiRotor`` airframe abstraction, the package roots -- are visible
at a glance.  Edges color by predicate family (:data:`EDGE_STYLES`),
with the reference family dashed.

Layout runs in the kernel, not the browser: :func:`spring_layout` is a
~40-line Fruchterman-Reingold simulation in 3D with a seeded generator,
so the same model always lands in the same shape and tests can assert
on coordinates.  Repulsion is exact O(n^2) (vectorized and chunked);
that is trivial at the default view's size and the honest ceiling for
very large graphs, which is why :func:`graph_viewer` caps the view at
``node_cap`` nodes (highest degree first, with an in-scene notice)
instead of degrading silently.

Interaction follows :mod:`longeron.analysis.viewer3d`: drag to orbit,
shift-drag or right-drag to pan, scroll to zoom, double-click to
re-fit.  Hovering a sphere names it (qualified name plus the folded
literals); clicking selects it -- the selected node pops in the
JupyterLab accent, its neighbors keep their color, everything else
dims, and the incident edges re-draw on an accent overlay.  A filter
panel (native checkboxes) toggles top-level namespaces and edge
families; every change re-layouts kernel-side, which is fast at this
size.

Linked views: the widget exposes the explorer's selection contract --
a two-way ``selected`` trait of qualified names plus
``on_select(callback)`` -- so a graph click can drive the
same consumers a tree or diagram selection drives, and kernel code can
select programmatically by assigning ``widget.selected``.

Offline tradeoff: the front-end imports three.js from the jsDelivr CDN
at view time, exactly like :mod:`longeron.analysis.viewer3d`; offline
front-ends get a printed notice instead of a scene.

Requires the ``rdf`` extra for rdflib and the ``viz`` extra for
anywidget and numpy: ``pip install "longeron[rdf,viz]"``.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from .. import rdf
from ..analysis.viewer3d import THREE_URL
from ..errors import MissingExtraError
from ..rdf import ELEMENT_BASE, VOCABULARY

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Iterable

    import anywidget
    from rdflib import Graph

    from .. import model as M

__all__ = ["EDGE_STYLES", "NODE_COLORS", "graph_view", "graph_viewer", "spring_layout"]

#: node color per family -- the explorer tree's chip palette, so the
#: graph and the explorer name kinds in the same colors
NODE_COLORS: dict[str, str] = {
    "package": "#6d6d6d",
    "structure": "#3d6fb4",
    "behavior": "#7b4bab",
    "data": "#3f7a1f",
    "connector": "#b07a26",
    "requirement": "#b0413e",
    "relationship": "#9a9fa8",  # imports, aliases, dependencies
    "literal": "#8fbf6f",  # opt-in value leaves (literals=True)
    "external": "#c0c4cb",  # opt-in unresolved reference targets
}

#: edge family -> (color, dashed, opacity); ``value`` only exists with
#: ``literals=True``.  The dense membership skeleton stays faint so the
#: colored cross-cutting families read on top of it.
EDGE_STYLES: dict[str, tuple[str, bool, float]] = {
    "membership": ("#c9ccd1", False, 0.3),
    "specialization": ("#3d6fb4", False, 0.75),
    "typing": ("#7b4bab", False, 0.75),
    "connection": ("#b07a26", False, 0.85),
    "satisfy": ("#b0413e", False, 0.9),
    "reference": ("#9a9fa8", True, 0.6),
    "value": ("#8fbf6f", False, 0.4),
}

#: object-valued projection predicate -> edge family
_EDGE_FAMILIES: dict[str, str] = {
    "ownedMember": "membership",
    "specializes": "specialization",
    "subsets": "specialization",
    "redefines": "specialization",
    "definedBy": "typing",
    "references": "typing",
    "crosses": "typing",
    "connects": "connection",
    "satisfiedBy": "satisfy",
    "importedElement": "reference",
    "aliasFor": "reference",
    "client": "reference",
    "supplier": "reference",
    "metadata": "reference",
    "annotatedElement": "reference",
}

#: usage/definition ``kind`` -> node family; anything unlisted is
#: ``structure``.  Mirrors ``longeron.explorer._KIND_FAMILIES`` verbatim
#: (kept local so this module stays importable without anywidget; a test
#: asserts the two stay identical).
_KIND_FAMILIES: dict[str, str] = {
    "requirement": "requirement",
    "concern": "requirement",
    "satisfy": "requirement",
    "verify": "requirement",
    "frame": "requirement",
    "objective": "requirement",
    "action": "behavior",
    "state": "behavior",
    "calc": "behavior",
    "constraint": "behavior",
    "case": "behavior",
    "analysis": "behavior",
    "verification": "behavior",
    "use_case": "behavior",
    "attribute": "data",
    "enum": "data",
    "enum_literal": "data",
    "metadata": "data",
    "port": "connector",
    "connection": "connector",
    "interface": "connector",
    "flow": "connector",
    "binding": "connector",
    "allocation": "connector",
    "message": "connector",
    "event": "connector",
    "event_occurrence": "connector",
}

#: rdf:type class -> node family for elements that carry no ``kind``
_CLASS_FAMILIES: dict[str, str] = {
    "Package": "package",
    "Membership": "relationship",  # aliases
    "Dependency": "relationship",
    "NamespaceImport": "relationship",
    "MembershipImport": "relationship",
}


def _require_numpy() -> Any:
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - exercised without extra
        raise MissingExtraError("the 3D graph layout", "numpy", "viz") from exc
    return numpy


def _family_table(literals: bool) -> list[dict[str, Any]]:
    """The stable edge-family style table payload edges index into."""

    return [
        {"name": name, "color": color, "dashed": dashed, "opacity": opacity}
        for name, (color, dashed, opacity) in EDGE_STYLES.items()
        if literals or name != "value"
    ]


def graph_view(
    model_or_graph: M.Model | Graph,
    *,
    namespaces: Iterable[str] | None = None,
    families: Iterable[str] | None = None,
    literals: bool = False,
    external: bool = False,
    isolated: bool = True,
) -> dict[str, Any]:
    """Extract the drawable node/edge view from a projected graph.

    ``model_or_graph`` is a :class:`~longeron.model.Model` (projected via
    :func:`longeron.rdf.to_graph`) or an already-built ``rdflib.Graph``.
    Nodes are the typed subjects (every projected element, anonymous
    ones included); edges are the object-valued relationship triples,
    grouped into the :data:`EDGE_STYLES` families.  Literal triples fold
    into each node's ``info`` hover lines.  Filters: ``namespaces``
    keeps only elements under the named top-level namespaces,
    ``families`` keeps only the named edge families, ``isolated=False``
    drops nodes left edgeless by the filters.  ``literals=True`` adds
    value literals as leaf nodes (edge family ``value``);
    ``external=True`` adds reference targets that resolve outside the
    projection (standard-library types, dangling names).

    Returns a dict with ``nodes`` (id, label, kind, family, color, ns,
    deg, r, info), ``edges`` (``[source, target, family]`` index
    triples), ``families`` (the style table the family indices point
    into), and ``namespaces`` (every top-level namespace in the graph,
    for filter options).  Node ids are qualified names; anonymous
    elements get stable ``~``-prefixed ids.  Ordering is deterministic,
    so a view built twice from the same model is identical.
    """

    rdflib = rdf._require_rdflib()
    graph = rdf._as_graph(model_or_graph)
    ns = rdflib.Namespace(VOCABULARY)

    def local(term: Any) -> str:
        text = str(term)
        if text.startswith(VOCABULARY):
            return text[len(VOCABULARY) :]
        return text.rsplit("#", 1)[-1].rsplit("/", 1)[-1]

    predicate_family = {ns[name]: family for name, family in _EDGE_FAMILIES.items()}
    identity_props = {ns["name"], ns["qualifiedName"], rdflib.RDFS.label}
    value_props = (ns["value"], ns["evaluatedValue"], ns["valueExpression"])

    types = {subject: local(cls) for subject, cls in graph.subject_objects(rdflib.RDF.type)}
    names: dict[Any, str] = {}
    qnames: dict[Any, str] = {}
    kinds: dict[Any, str] = {}
    info: dict[Any, list[str]] = {}
    parents: dict[Any, Any] = {}
    links: set[tuple[Any, Any, str]] = set()
    for subject, predicate, obj in graph:
        if subject not in types:
            continue
        if isinstance(obj, rdflib.Literal):
            text = str(obj)
            if predicate == ns["name"]:
                names[subject] = text
            elif predicate == ns["qualifiedName"]:
                qnames[subject] = text
            elif predicate not in identity_props:
                if predicate == ns["kind"]:
                    kinds[subject] = text
                clipped = text if len(text) <= 96 else text[:95] + "\u2026"
                info.setdefault(subject, []).append(f"{local(predicate)}: {clipped}")
            continue
        family = predicate_family.get(predicate)
        if family is None or subject == obj:
            continue
        if obj not in types and not external:
            continue
        if family == "membership":
            parents.setdefault(obj, subject)
        links.add((subject, obj, family))

    def identity(node: Any) -> str:
        qname = qnames.get(node)
        if qname:
            return qname
        text = str(node)
        if isinstance(node, rdflib.URIRef) and text.startswith(ELEMENT_BASE):
            return "::".join(unquote(seg) for seg in text[len(ELEMENT_BASE) :].split("/"))
        if isinstance(node, rdflib.BNode):
            return "~" + text
        return text

    def top_namespace(node: Any) -> str:
        current, seen = node, set()
        while current is not None and current not in seen:
            seen.add(current)
            ident = identity(current)
            if not ident.startswith("~"):
                return ident.split("::", 1)[0]
            current = parents.get(current)
        return "(anonymous)"

    universe: dict[Any, dict[str, Any]] = {}
    for node, class_name in types.items():
        kind = kinds.get(node, "")
        if kind:
            family = _KIND_FAMILIES.get(kind, "structure")
        else:
            family = _CLASS_FAMILIES.get(class_name, "structure")
        universe[node] = {
            "id": identity(node),
            "label": names.get(node) or kind or class_name,
            "kind": kind or class_name,
            "family": family,
            "ns": top_namespace(node),
        }
    if external:
        for _, obj, _family in links:
            if obj in universe:
                continue
            ident = identity(obj)
            universe[obj] = {
                "id": ident,
                "label": ident.rsplit("::", 1)[-1],
                "kind": "external",
                "family": "external",
                "ns": ident.split("::", 1)[0],
            }

    all_namespaces = sorted({entry["ns"] for entry in universe.values()})
    active_ns = None if namespaces is None else set(namespaces)
    active_family = None if families is None else set(families)
    kept = {
        node for node, entry in universe.items() if active_ns is None or entry["ns"] in active_ns
    }
    edges: list[tuple[Any, Any, str]] = [
        (source, target, family)
        for source, target, family in links
        if source in kept and target in kept and (active_family is None or family in active_family)
    ]

    # opt-in value-literal leaves, keyed and ordered deterministically
    leaves: list[dict[str, Any]] = []
    if literals and (active_family is None or "value" in active_family):
        for node in sorted(kept, key=lambda n: universe[n]["id"]):
            entry = universe[node]
            for prop in value_props:
                values = sorted(str(value) for value in graph.objects(node, prop))
                for ordinal, text in enumerate(values):
                    clipped = text if len(text) <= 40 else text[:39] + "\u2026"
                    leaves.append(
                        {
                            "id": f"~lit:{entry['id']}:{local(prop)}:{ordinal}",
                            "label": clipped,
                            "kind": "literal",
                            "family": "literal",
                            "ns": entry["ns"],
                            "info": [f"{local(prop)} of {entry['id']}"],
                            "owner": node,
                        }
                    )

    degree: Counter[Any] = Counter()
    for source, target, _family in edges:
        degree[source] += 1
        degree[target] += 1
    for leaf in leaves:
        degree[leaf["owner"]] += 1
    if not isolated:
        kept = {node for node in kept if degree[node] > 0}
        edges = [edge for edge in edges if edge[0] in kept and edge[1] in kept]
        leaves = [leaf for leaf in leaves if leaf["owner"] in kept]

    ordered = sorted(kept, key=lambda n: universe[n]["id"])
    index = {node: position for position, node in enumerate(ordered)}
    nodes_out: list[dict[str, Any]] = []
    for node in ordered:
        entry = universe[node]
        deg = degree[node]
        nodes_out.append(
            {
                **entry,
                "color": NODE_COLORS[entry["family"]],
                "deg": deg,
                "r": round(0.09 * (1 + math.log2(1 + deg)), 4),
                "info": sorted(info.get(node, ())),
            }
        )
    table = _family_table(literals)
    family_index = {entry["name"]: position for position, entry in enumerate(table)}
    edges_out = sorted(
        [index[source], index[target], family_index[family]] for source, target, family in edges
    )
    for leaf in leaves:
        owner = leaf.pop("owner")
        edges_out.append([index[owner], len(nodes_out), family_index["value"]])
        nodes_out.append({**leaf, "color": NODE_COLORS["literal"], "deg": 1, "r": 0.09})
    return {
        "nodes": nodes_out,
        "edges": edges_out,
        "families": table,
        "namespaces": all_namespaces,
    }


def spring_layout(
    count: int,
    edges: Iterable[tuple[int, int]],
    *,
    seed: int = 7,
    iterations: int = 60,
    radius: float = 10.0,
) -> list[list[float]]:
    """A deterministic 3D Fruchterman-Reingold embedding (numpy).

    ``count`` nodes and ``edges`` (index pairs; duplicates and
    self-loops are ignored) settle under the classic forces: k^2/d
    pairwise repulsion, d^2/k attraction along edges, plus a mild pull
    toward the origin so disconnected components stay in frame.  The
    temperature cools linearly over ``iterations`` steps and ``seed``
    fixes the starting positions, so the result is reproducible.  The
    returned positions are centered and scaled to fit a sphere of
    ``radius``.
    """

    np = _require_numpy()
    if count <= 0:
        return []
    rng = np.random.default_rng(seed)
    pos = rng.uniform(-1.0, 1.0, (count, 3))
    pairs = sorted({(s, t) for s, t in edges if s != t})
    src = np.array([pair[0] for pair in pairs], dtype=np.intp)
    dst = np.array([pair[1] for pair in pairs], dtype=np.intp)
    k = (8.0 / count) ** (1.0 / 3.0)  # ideal spacing in an 8-unit^3 box
    heat = 0.25
    cooling = heat / (iterations + 1)
    for _ in range(iterations):
        push = np.zeros((count, 3))
        # ponytail: exact O(n^2) repulsion, chunked for memory; swap in
        # Barnes-Hut if graphs far beyond ~10k nodes ever matter
        for low in range(0, count, 512):
            high = min(low + 512, count)
            delta = pos[low:high, None, :] - pos[None, :, :]
            dist2 = np.einsum("ijk,ijk->ij", delta, delta) + 1e-9
            push[low:high] += np.einsum("ijk,ij->ik", delta, k * k / dist2)
        if src.size:
            delta = pos[src] - pos[dst]
            dist = np.sqrt(np.einsum("ij,ij->i", delta, delta))
            pull = delta * (dist / k)[:, None]
            np.subtract.at(push, src, pull)
            np.add.at(push, dst, pull)
        push -= pos * 0.05  # gravity keeps disconnected components in frame
        length = np.sqrt(np.einsum("ij,ij->i", push, push)) + 1e-9
        pos += push / length[:, None] * np.minimum(length, heat)[:, None]
        heat -= cooling
    pos -= pos.mean(axis=0)
    extent = float(np.sqrt((pos * pos).sum(axis=1)).max())
    if extent > 0:
        pos *= radius / extent
    result: list[list[float]] = np.round(pos, 3).tolist()
    return result


# Conventions follow longeron.analysis.viewer3d's front-end: DOM built
# once, geometry rebuilt only when the payload traitlet changes, the
# same ~30-line spherical orbit handler, rendering on demand.  New here:
# one InstancedMesh carries every node (one draw call), one LineSegments
# per edge family carries every edge, the hover raycast reports the
# instanceId, and the filter panel is a native <details> of checkboxes
# that writes filters_json for the kernel to re-layout.
_ESM = r"""
async function render({ model, el }) {
  el.classList.add("longeron-graph3d");
  el.innerHTML = "";
  let THREE;
  try {
    THREE = await import("%THREE_URL%");
  } catch (err) {
    const note = document.createElement("div");
    note.className = "longeron-graph3d-offline";
    note.textContent = "3D graph unavailable: three.js could not be " +
      "loaded from the CDN (offline front-end?).";
    el.appendChild(note);
    return;
  }

  const aspect = Math.max(
    0.4, model.get("width_px") / Math.max(1, model.get("height_px")));
  const stage = document.createElement("div");
  stage.className = "longeron-graph3d-stage";
  el.appendChild(stage);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  stage.appendChild(renderer.domElement);
  renderer.domElement.setAttribute("role", "img");
  renderer.domElement.setAttribute("aria-label", "3D RDF graph view");
  const hint = document.createElement("div");
  hint.className = "longeron-graph3d-hint";
  hint.textContent = "drag orbit \u00b7 shift-drag or right-drag pan " +
    "\u00b7 wheel zoom \u00b7 click select \u00b7 double-click fit";
  const counts = document.createElement("div");
  counts.className = "longeron-graph3d-counts";
  const notice = document.createElement("div");
  notice.className = "longeron-graph3d-notice";
  const hover = document.createElement("div");
  hover.className = "longeron-graph3d-hover";
  stage.append(hint, counts, notice, hover);

  // --- filter panel: namespace + edge-family checkboxes -> filters_json
  const panel = document.createElement("details");
  panel.className = "longeron-graph3d-panel";
  panel.open = true;
  const summary = document.createElement("summary");
  summary.textContent = "filters";
  panel.appendChild(summary);
  stage.appendChild(panel);
  const boxes = [];
  let muteFilters = false;
  function pushFilters() {
    if (muteFilters) return;
    const filters = { namespaces: [], families: [], isolated: true };
    for (const box of boxes) {
      if (box.group === "isolated") filters.isolated = box.input.checked;
      else if (box.input.checked) filters[box.group].push(box.name);
    }
    model.set("filters_json", JSON.stringify(filters));
    model.save_changes();
  }
  function addHeading(text) {
    const heading = document.createElement("div");
    heading.className = "longeron-graph3d-panel-heading";
    heading.textContent = text;
    panel.appendChild(heading);
  }
  function addBox(group, name, swatch) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = true;
    input.addEventListener("change", pushFilters);
    label.appendChild(input);
    if (swatch) {
      const chip = document.createElement("span");
      chip.className = "longeron-graph3d-swatch";
      chip.style.background = swatch;
      label.appendChild(chip);
    }
    label.append(name);
    panel.appendChild(label);
    boxes.push({ input, group, name });
  }
  const options = JSON.parse(model.get("options_json") || "{}");
  addHeading("namespaces");
  for (const name of options.namespaces || []) addBox("namespaces", name);
  addHeading("edges");
  for (const fam of options.families || []) addBox("families", fam.name, fam.color);
  addHeading("show");
  addBox("isolated", "unlinked nodes");
  function pullFilters() {
    let filters;
    try { filters = JSON.parse(model.get("filters_json") || "{}"); }
    catch (err) { return; }
    muteFilters = true;
    for (const box of boxes) {
      if (box.group === "isolated") box.input.checked = filters.isolated !== false;
      else box.input.checked = (filters[box.group] || []).includes(box.name);
    }
    muteFilters = false;
  }

  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#f4f4f2");
  const camera = new THREE.PerspectiveCamera(42, aspect, 0.01, 400);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f98, 1.05));
  const key = new THREE.DirectionalLight(0xffffff, 1.1);
  key.position.set(2, 3, 1.5);
  scene.add(key);
  const content = new THREE.Group();  // rebuilt on payload changes
  scene.add(content);

  // --- camera: spherical orbit about a fit target, render on demand
  let target = new THREE.Vector3();
  let radius = 30, theta = 0.9, phi = 1.05;
  let height = model.get("height_px");
  let pending = false;
  function requestRender() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false;
                                  renderer.render(scene, camera); });
  }
  function applyCamera() {
    camera.position.set(
      target.x + radius * Math.sin(phi) * Math.cos(theta),
      target.y + radius * Math.cos(phi),
      target.z + radius * Math.sin(phi) * Math.sin(theta));
    camera.lookAt(target);
    requestRender();
  }
  function fit() {
    if (!payload || !payload.nodes.length) { requestRender(); return; }
    const box = new THREE.Box3();
    const point = new THREE.Vector3();
    for (const p of payload.positions) box.expandByPoint(point.set(p[0], p[1], p[2]));
    box.getCenter(target);
    const size = box.getSize(new THREE.Vector3());
    const span = Math.max(size.x, size.y, size.z, 1e-6);
    radius = (span / 2) / Math.tan((camera.fov / 2) * Math.PI / 180) * 1.4;
    applyCamera();
  }

  // --- sizing: fill the host width at a fixed aspect; re-fit on resize
  function layout(refit) {
    const w = Math.max(240, el.clientWidth || model.get("width_px"));
    height = Math.round(w / aspect);
    stage.style.height = height + "px";
    renderer.setSize(w, height);
    camera.aspect = w / height;
    camera.updateProjectionMatrix();
    if (refit) fit(); else requestRender();
  }
  let lastWidth = 0;
  const observer = new ResizeObserver(() => {
    const w = el.clientWidth;
    if (w && Math.abs(w - lastWidth) > 1) { lastWidth = w; layout(true); }
  });
  observer.observe(el);
  layout(false);

  // --- scene build: one InstancedMesh for every node, one LineSegments
  // per edge family -- a handful of draw calls however big the graph
  let payload = null;
  let nodesMesh = null;
  let overlay = null;
  let idIndex = new Map();
  let adjacency = [];
  function disposeContent() {
    content.traverse((node) => {
      if (node.geometry) node.geometry.dispose();
      if (node.material) node.material.dispose();
    });
    content.clear();
    nodesMesh = null;
    overlay = null;
  }
  function build() {
    disposeContent();
    try { payload = JSON.parse(model.get("payload_json") || "null"); }
    catch (err) { payload = null; }
    idIndex = new Map();
    adjacency = [];
    notice.textContent = (payload && payload.notice) || "";
    if (!payload || !payload.nodes.length) {
      counts.textContent = "no nodes in view";
      requestRender();
      return;
    }
    const nodes = payload.nodes;
    const positions = payload.positions;
    nodes.forEach((node, i) => { idIndex.set(node.id, i); adjacency.push([]); });
    payload.edges.forEach(([s, t]) => { adjacency[s].push(t); adjacency[t].push(s); });
    const sphere = new THREE.SphereGeometry(1, 12, 8);
    nodesMesh = new THREE.InstancedMesh(
      sphere, new THREE.MeshLambertMaterial({ color: 0xffffff }), nodes.length);
    const matrix = new THREE.Matrix4();
    const color = new THREE.Color();
    nodes.forEach((node, i) => {
      const [x, y, z] = positions[i];
      matrix.makeScale(node.r, node.r, node.r).setPosition(x, y, z);
      nodesMesh.setMatrixAt(i, matrix);
      nodesMesh.setColorAt(i, color.set(node.color));
    });
    content.add(nodesMesh);
    const byFamily = payload.families.map(() => []);
    for (const [s, t, f] of payload.edges) byFamily[f].push(s, t);
    payload.families.forEach((family, f) => {
      const ends = byFamily[f];
      if (!ends.length) return;
      const array = new Float32Array(ends.length * 3);
      ends.forEach((n, j) => array.set(positions[n], j * 3));
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(array, 3));
      const material = family.dashed
        ? new THREE.LineDashedMaterial({ color: family.color, transparent: true,
            opacity: family.opacity, dashSize: 0.14, gapSize: 0.1 })
        : new THREE.LineBasicMaterial({ color: family.color, transparent: true,
            opacity: family.opacity });
      const lines = new THREE.LineSegments(geometry, material);
      if (family.dashed) lines.computeLineDistances();
      lines.raycast = () => {};  // hover and click belong to the spheres
      content.add(lines);
    });
    counts.textContent =
      payload.counts.nodes + " nodes \u00b7 " + payload.counts.edges + " edges";
    applyEmphasis(false);
    fit();
  }

  // --- selection emphasis: the selected node pops in the JupyterLab
  // accent (and scales up), neighbors keep their color, the rest dim,
  // and the incident edges re-draw on an accent overlay
  function applyEmphasis(paint = true) {
    if (!nodesMesh || !payload) return;
    if (overlay) {
      overlay.geometry.dispose();
      overlay.material.dispose();
      content.remove(overlay);
      overlay = null;
    }
    const chosen = new Set((model.get("selected") || [])
      .map((id) => idIndex.get(id)).filter((i) => i !== undefined));
    const color = new THREE.Color();
    const dim = new THREE.Color("#f4f4f2");
    const matrix = new THREE.Matrix4();
    const accent = (getComputedStyle(el)
      .getPropertyValue("--jp-brand-color2") || "").trim() || "#2196f3";
    const near = new Set(chosen);
    for (const i of chosen) for (const j of adjacency[i]) near.add(j);
    payload.nodes.forEach((node, i) => {
      color.set(node.color);
      let scale = node.r;
      if (chosen.size) {
        if (chosen.has(i)) { color.set(accent); scale = node.r * 1.6; }
        else if (!near.has(i)) color.lerp(dim, 0.82);
      }
      nodesMesh.setColorAt(i, color);
      const [x, y, z] = payload.positions[i];
      matrix.makeScale(scale, scale, scale).setPosition(x, y, z);
      nodesMesh.setMatrixAt(i, matrix);
    });
    if (chosen.size) {
      const ends = [];
      for (const [s, t] of payload.edges) {
        if (chosen.has(s) || chosen.has(t)) ends.push(s, t);
      }
      if (ends.length) {
        const array = new Float32Array(ends.length * 3);
        ends.forEach((n, j) => array.set(payload.positions[n], j * 3));
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute("position", new THREE.BufferAttribute(array, 3));
        overlay = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({
          color: accent, transparent: true, opacity: 0.9 }));
        overlay.raycast = () => {};
        content.add(overlay);
      }
    }
    nodesMesh.instanceColor.needsUpdate = true;
    nodesMesh.instanceMatrix.needsUpdate = true;
    if (paint) requestRender();
  }

  // --- hover: raycast the instanced spheres, name the hit node
  const raycaster = new THREE.Raycaster();
  const canvas = renderer.domElement;
  function pickIndex(event) {
    if (!nodesMesh) return -1;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return -1;
    raycaster.setFromCamera(new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1), camera);
    const hit = raycaster.intersectObject(nodesMesh, false)[0];
    return hit && hit.instanceId !== undefined ? hit.instanceId : -1;
  }
  function showHover(event) {
    const index = pickIndex(event);
    if (index < 0) { hover.style.display = "none"; return; }
    const node = payload.nodes[index];
    hover.textContent = [node.label, node.id, ...node.info].join("\n");
    const rect = stage.getBoundingClientRect();
    hover.style.left = Math.min(event.clientX - rect.left + 14,
                                Math.max(0, rect.width - 260)) + "px";
    hover.style.top = (event.clientY - rect.top + 12) + "px";
    hover.style.display = "block";
  }

  // --- interaction: drag orbits, shift/right-drag pans, wheel zooms,
  // a still click selects, double-click re-fits
  canvas.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  let dragging = null;  // { mode: "orbit" | "pan", x, y, x0, y0, moved }
  let hoverEvent = null, hoverQueued = false;
  canvas.addEventListener("pointerdown", (event) => {
    const pan = event.button === 2 || event.shiftKey;
    dragging = { mode: pan ? "pan" : "orbit",
                 x: event.clientX, y: event.clientY,
                 x0: event.clientX, y0: event.clientY, moved: false };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) {
      hoverEvent = event;
      if (hoverQueued) return;
      hoverQueued = true;
      requestAnimationFrame(() => {
        hoverQueued = false;
        if (!dragging) showHover(hoverEvent);
      });
      return;
    }
    hover.style.display = "none";
    const dx = event.clientX - dragging.x;
    const dy = event.clientY - dragging.y;
    dragging.x = event.clientX;
    dragging.y = event.clientY;
    if (Math.abs(event.clientX - dragging.x0)
        + Math.abs(event.clientY - dragging.y0) > 5) dragging.moved = true;
    if (dragging.mode === "pan") {
      const scale = 2 * radius
        * Math.tan((camera.fov / 2) * Math.PI / 180) / height;
      camera.updateMatrixWorld();
      const right = new THREE.Vector3()
        .setFromMatrixColumn(camera.matrixWorld, 0);
      const up = new THREE.Vector3()
        .setFromMatrixColumn(camera.matrixWorld, 1);
      target.addScaledVector(right, -dx * scale);
      target.addScaledVector(up, dy * scale);
    } else {
      theta += dx * 0.008;
      phi = Math.min(Math.PI - 0.15,
                     Math.max(0.1, phi + dy * 0.008));
    }
    applyCamera();
  });
  canvas.addEventListener("pointerup", (event) => {
    const wasClick = dragging && dragging.mode === "orbit" && !dragging.moved;
    dragging = null;
    if (!wasClick || !payload) return;
    const index = pickIndex(event);
    model.set("selected", index >= 0 ? [payload.nodes[index].id] : []);
    model.save_changes();
  });
  canvas.addEventListener("pointerleave", () => { hover.style.display = "none"; });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    radius = Math.min(300, Math.max(0.05,
                                    radius * Math.exp(event.deltaY * 0.001)));
    applyCamera();
  }, { passive: false });
  canvas.addEventListener("dblclick", fit);

  model.on("change:payload_json", build);
  model.on("change:selected", () => applyEmphasis());
  model.on("change:filters_json", pullFilters);
  pullFilters();
  build();
  return () => { observer.disconnect(); renderer.dispose(); };
}
export default { render };
""".replace("%THREE_URL%", THREE_URL)

_CSS = """
.longeron-graph3d { font-family: Helvetica, Arial, sans-serif; }
.longeron-graph3d-stage {
  border: 1px solid #e2e2e2; border-radius: 8px; overflow: hidden;
  background: #f4f4f2; position: relative; width: 100%;
}
.longeron-graph3d-stage canvas { display: block; cursor: grab; }
.longeron-graph3d-stage canvas:active { cursor: grabbing; }
.longeron-graph3d-hint {
  position: absolute; right: 8px; bottom: 6px; font-size: 10px;
  color: #8a8f98; background: rgba(244, 244, 242, 0.78);
  padding: 2px 8px; border-radius: 9px; pointer-events: none;
  user-select: none;
}
.longeron-graph3d-counts {
  position: absolute; left: 8px; bottom: 6px; font-size: 10px;
  color: #8a8f98; background: rgba(244, 244, 242, 0.78);
  padding: 2px 8px; border-radius: 9px; pointer-events: none;
  font-variant-numeric: tabular-nums;
}
.longeron-graph3d-notice {
  position: absolute; top: 8px; right: 8px; font-size: 11px;
  color: #8a6d1f; background: rgba(255, 244, 214, 0.92);
  padding: 3px 10px; border-radius: 9px; pointer-events: none;
  max-width: 46%;
}
.longeron-graph3d-notice:empty { display: none; }
.longeron-graph3d-hover {
  position: absolute; display: none; pointer-events: none;
  background: rgba(43, 45, 49, 0.92); color: #f4f4f2; font-size: 11px;
  line-height: 1.45; padding: 6px 9px; border-radius: 6px;
  white-space: pre-line; max-width: 320px; z-index: 3;
}
.longeron-graph3d-panel {
  position: absolute; top: 8px; left: 8px; font-size: 11px;
  color: #2b2d31; background: rgba(244, 244, 242, 0.92);
  border: 1px solid #e2e2e2; border-radius: 8px;
  padding: 4px 10px 6px; max-height: 85%; overflow-y: auto;
  user-select: none; z-index: 2;
}
.longeron-graph3d-panel summary {
  cursor: pointer; font-weight: 600; color: #555555;
}
.longeron-graph3d-panel label {
  display: flex; align-items: center; gap: 6px; margin: 2px 0;
  cursor: pointer;
}
.longeron-graph3d-panel input { margin: 0; }
.longeron-graph3d-panel-heading {
  margin: 6px 0 2px; font-size: 10px; text-transform: uppercase;
  letter-spacing: 0.04em; color: #8a8f98;
}
.longeron-graph3d-swatch {
  width: 10px; height: 10px; border-radius: 3px; display: inline-block;
  flex: none;
}
.longeron-graph3d-offline {
  border: 1px dashed #d4d4d4; border-radius: 8px; padding: 14px;
  font-size: 12px; color: #777777;
}
"""

_VIEWER_CLS: type[anywidget.AnyWidget] | None = None


def _viewer_class() -> type[anywidget.AnyWidget]:
    """Define RdfGraphViewer lazily -- anywidget is an optional extra."""

    global _VIEWER_CLS
    if _VIEWER_CLS is not None:
        return _VIEWER_CLS
    try:
        import anywidget as _anywidget
        import traitlets
    except ImportError as err:
        raise MissingExtraError("the 3D graph viewer", "anywidget", "viz") from err

    class RdfGraphViewer(_anywidget.AnyWidget):
        """three.js rendering of an RDF projection's node/edge view."""

        _esm = _ESM
        _css = _CSS
        #: the drawable view: nodes, positions, edges, families, notice
        payload_json = traitlets.Unicode("").tag(sync=True)
        #: filter options (all namespaces + the edge-family style table)
        options_json = traitlets.Unicode("{}").tag(sync=True)
        #: active filters; the front-end panel writes this, the kernel
        #: observer re-extracts and re-layouts the view
        filters_json = traitlets.Unicode("{}").tag(sync=True)
        #: the selection seam (two-way): qualified names of the selected
        #: nodes; clicks write it, kernel assignment drives the emphasis
        selected = traitlets.List(traitlets.Unicode()).tag(sync=True)
        #: aspect ratio + fallback width; the canvas fills the host width
        width_px = traitlets.Int(760).tag(sync=True)
        height_px = traitlets.Int(520).tag(sync=True)

        def __init__(
            self,
            graph: Any,
            *,
            namespaces: Iterable[str] | None,
            families: Iterable[str] | None,
            literals: bool,
            external: bool,
            isolated: bool,
            seed: int,
            iterations: int,
            node_cap: int,
            **kwargs: Any,
        ) -> None:
            # set BEFORE super().__init__: trait kwargs may fire observers
            self._select_callbacks: list[Callable[[list[str]], None]] = []
            self._graph = graph
            self._literals = literals
            self._external = external
            self._seed = seed
            self._iterations = iterations
            self._node_cap = node_cap
            #: seconds the last kernel-side layout took
            self.layout_seconds = 0.0
            super().__init__(**kwargs)
            full = graph_view(graph, literals=literals, external=external)
            self.options_json = json.dumps(
                {"namespaces": full["namespaces"], "families": full["families"]}
            )
            self.filters_json = json.dumps(
                {
                    "namespaces": (
                        sorted(set(namespaces)) if namespaces is not None else full["namespaces"]
                    ),
                    "families": (
                        sorted(set(families))
                        if families is not None
                        else [entry["name"] for entry in full["families"]]
                    ),
                    "isolated": bool(isolated),
                }
            )
            self.observe(self._on_filters, names="filters_json")
            self.observe(self._notify_select, names="selected")
            self._recompute()

        @property
        def counts(self) -> dict[str, int]:
            """Node and edge counts of the current (filtered) view."""

            data = json.loads(self.payload_json or "{}")
            counts: dict[str, int] = data.get("counts", {"nodes": 0, "edges": 0})
            return counts

        def on_select(self, callback: Callable[[list[str]], None]) -> None:
            """Call ``callback`` with the selected ids on every selection."""

            self._select_callbacks.append(callback)

        def filter(
            self,
            *,
            namespaces: Iterable[str] | None = None,
            families: Iterable[str] | None = None,
            isolated: bool | None = None,
        ) -> dict[str, int]:
            """Update the active filters kernel-side; returns the new counts.

            ``None`` leaves a dimension unchanged.  The same re-extract +
            re-layout path serves the browser panel's checkboxes, so
            headless callers and clicks see identical views.
            """

            filters = json.loads(self.filters_json)
            if namespaces is not None:
                filters["namespaces"] = sorted(set(namespaces))
            if families is not None:
                filters["families"] = sorted(set(families))
            if isolated is not None:
                filters["isolated"] = bool(isolated)
            self.filters_json = json.dumps(filters)  # observer recomputes
            return self.counts

        # -- internals -------------------------------------------------------

        def _on_filters(self, change: Any) -> None:
            self._recompute()

        def _notify_select(self, change: Any) -> None:
            for callback in self._select_callbacks:
                callback(list(change["new"]))

        def _recompute(self) -> None:
            filters = json.loads(self.filters_json or "{}")
            view = graph_view(
                self._graph,
                namespaces=filters.get("namespaces"),
                families=filters.get("families"),
                literals=self._literals,
                external=self._external,
                isolated=filters.get("isolated", True),
            )
            nodes = view["nodes"]
            edges = view["edges"]
            notice = ""
            if len(nodes) > self._node_cap:
                total = len(nodes)
                by_degree = sorted(range(total), key=lambda i: (-nodes[i]["deg"], nodes[i]["id"]))
                keep = sorted(by_degree[: self._node_cap])
                remap = {old: new for new, old in enumerate(keep)}
                nodes = [nodes[i] for i in keep]
                edges = [[remap[s], remap[t], f] for s, t, f in edges if s in remap and t in remap]
                notice = (
                    f"showing {self._node_cap} of {total} nodes (highest degree) -- "
                    "filter namespaces or raise node_cap"
                )
            start = time.perf_counter()
            positions = spring_layout(
                len(nodes),
                ((s, t) for s, t, _ in edges),
                seed=self._seed,
                iterations=self._iterations,
            )
            self.layout_seconds = time.perf_counter() - start
            self.payload_json = json.dumps(
                {
                    "nodes": nodes,
                    "edges": edges,
                    "families": view["families"],
                    "positions": positions,
                    "notice": notice,
                    "counts": {"nodes": len(nodes), "edges": len(edges)},
                }
            )

    _VIEWER_CLS = RdfGraphViewer
    return RdfGraphViewer


def graph_viewer(
    model_or_graph: M.Model | Graph,
    *,
    namespaces: Iterable[str] | None = None,
    families: Iterable[str] | None = None,
    literals: bool = False,
    external: bool = False,
    isolated: bool = True,
    seed: int = 7,
    iterations: int = 60,
    node_cap: int = 5000,
    width_px: int = 760,
    height_px: int = 520,
) -> anywidget.AnyWidget:
    """Explore a model's RDF projection as an interactive 3D graph.

    ``model_or_graph`` is a :class:`~longeron.model.Model` or a graph
    already built with :func:`longeron.rdf.to_graph` (pass the latter to
    keep ``evaluated=True`` literals in the hover payloads).
    ``namespaces`` / ``families`` / ``literals`` / ``external`` /
    ``isolated`` select the initial view exactly as in
    :func:`graph_view`; the in-scene filter panel (or
    ``widget.filter(...)``) changes them later, re-layouting
    kernel-side on every change.  ``seed`` and ``iterations`` steer the
    deterministic :func:`spring_layout` embedding.

    Views larger than ``node_cap`` nodes keep the ``node_cap``
    highest-degree nodes and say so in an in-scene notice: rendering is
    instanced and stays fluid into five figures, but the exact O(n^2)
    layout is the honest ceiling, so the cap protects the kernel rather
    than the GPU.

    The widget's ``selected`` trait (qualified names, two-way) plus
    ``on_select(callback)`` form the same selection contract the
    explorer's tree exposes: clicks land in the kernel, kernel
    assignments drive the in-scene emphasis, and ``counts`` /
    ``layout_seconds`` report the current view's size and layout cost.
    """

    cls = _viewer_class()
    return cls(
        rdf._as_graph(model_or_graph),
        namespaces=namespaces,
        families=families,
        literals=literals,
        external=external,
        isolated=isolated,
        seed=seed,
        iterations=iterations,
        node_cap=node_cap,
        width_px=width_px,
        height_px=height_px,
    )
