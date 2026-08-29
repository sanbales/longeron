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

Layout runs in the kernel, not the browser, and every payload ships
**two** embeddings of the same view.  :func:`spring_layout` is a
~40-line Fruchterman-Reingold simulation in 3D with a seeded generator,
so the same model always lands in the same shape and tests can assert
on coordinates.  :func:`dag_layout` is its layered counterpart: the
hierarchy edges (membership plus specialization) assign each node a
layer by longest path, a barycenter pass orders each layer to shorten
edges, and the layers stack as rings on the y axis -- packages on top,
the specialization fringe at the bottom.  A prominent in-scene slider
morphs between the two by pure front-end interpolation: dragging it
never touches the kernel, and edges, labels, and picking follow at
frame rate.  Repulsion in the force layout is exact O(n^2) (vectorized
and chunked); that is trivial at the default view's size and the honest
ceiling for very large graphs, which is why :func:`graph_viewer` caps
the view at ``node_cap`` nodes (highest degree first, with an in-scene
notice) instead of degrading silently.

Interaction follows :mod:`longeron.analysis.viewer3d`: drag to orbit,
shift-drag or right-drag to pan, scroll to zoom, double-click to
re-fit.  Hovering a sphere names it (qualified name plus the folded
literals) and lights its k=1 neighborhood; clicking selects it -- the
selected node pops in the JupyterLab accent, neighbors keep their
color, everything else recedes toward the canvas color, base edges drop
to a fraction of their opacity, and the incident edges re-draw on an
accent overlay.  Billboard labels name the highest-degree nodes (a
panel slider budgets the density, camera distance fades them) and
always name the selection and its neighbors.  A legend chip names the
node kinds, edge families, and the degree-size cue in-scene.

The control surface is the house widget chrome
(:mod:`longeron.widgets._chrome`): a veiled, collapsible panel with a
type-ahead search over qualified names, toggle pills (real checkboxes
under the styling) for namespaces, edge families, and unlinked nodes,
and slim filled-track sliders.  Every filter change re-extracts and
re-layouts kernel-side, exactly like the ``widget.filter(...)`` seam.
The chrome and the scene are theme-aware end to end: JupyterLab theme
tokens drive the panel, the text, and the canvas clear color, and a
theme flip re-reads them live.

Focus mode isolates a neighborhood: select a node and press ``f`` (or
click the focus chip) and the kernel re-extracts the k-hop neighborhood
(k = 1 or 2 from the panel), re-layouts both embeddings -- instant at
sub-graph size -- and a breadcrumb chip steps back out.  The camera
flies to selections and search hits with a 600ms eased move, and an
optional idle orbit (a panel pill) spins the scene slowly until any
interaction cancels it.

Linked views: the widget exposes the explorer's selection contract --
a two-way ``selected`` trait of qualified names plus
``on_select(callback)`` -- so a graph click can drive the
same consumers a tree or diagram selection drives, and kernel code can
select programmatically by assigning ``widget.selected``.  Focus mode
leaves the contract untouched.

``widget.export_html(path)`` writes the current view as a
self-contained standalone page: the payload, the front-end module, and
a tiny model shim are inlined, so the file opens in any browser with no
kernel and no anywidget.  Kernel-backed controls (filters, focus) hide
themselves in the standalone page; the morph slider, search, labels,
legend, and selection emphasis all work.

Offline tradeoff: the front-end imports three.js from the jsDelivr CDN
at view time, exactly like :mod:`longeron.analysis.viewer3d`; offline
front-ends (and the exported page, offline) get a printed notice
instead of a scene.

Requires the ``rdf`` extra for rdflib and the ``viz`` extra for
anywidget and numpy: ``pip install "longeron[rdf,viz]"``.
"""

from __future__ import annotations

import heapq
import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from .. import rdf
from ..analysis.viewer3d import THREE_URL
from ..errors import MissingExtraError
from ..rdf import ELEMENT_BASE, VOCABULARY
from ._chrome import CONTROL_CSS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Iterable

    import anywidget
    from rdflib import Graph

    from .. import model as M

__all__ = [
    "EDGE_STYLES",
    "NODE_COLORS",
    "dag_layout",
    "graph_view",
    "graph_viewer",
    "spring_layout",
]

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


def _assign_layers(count: int, edges: list[tuple[int, int]]) -> list[int]:
    """Longest-path layering: ``layer[v] >= layer[u] + 1`` per edge.

    Kahn's algorithm with a min-heap ready queue, so the result is
    deterministic.  Nodes with no incoming constraint sit at layer 0.
    A cycle (malformed hierarchies only) releases its lowest-index node
    at the current depth; monotonicity along the residual back edge is
    impossible, determinism is preserved.
    """

    outgoing: list[list[int]] = [[] for _ in range(count)]
    incoming = [0] * count
    for u, v in edges:
        outgoing[u].append(v)
        incoming[v] += 1
    layer = [0] * count
    done = [False] * count
    ready = [node for node in range(count) if incoming[node] == 0]
    heapq.heapify(ready)
    remaining = count
    while remaining:
        if not ready:
            stuck = min(node for node in range(count) if not done[node])
            incoming[stuck] = 0
            heapq.heappush(ready, stuck)
            continue
        node = heapq.heappop(ready)
        if done[node]:
            continue
        done[node] = True
        remaining -= 1
        for child in outgoing[node]:
            if done[child]:
                continue  # a broken cycle's back edge
            layer[child] = max(layer[child], layer[node] + 1)
            incoming[child] -= 1
            if incoming[child] == 0:
                heapq.heappush(ready, child)
    return layer


def dag_layout(
    count: int,
    hierarchy: Iterable[tuple[int, int]],
    links: Iterable[tuple[int, int]] = (),
    *,
    radius: float = 10.0,
    sweeps: int = 4,
) -> list[list[float]]:
    """A deterministic layered ("hierarchy") 3D embedding.

    ``hierarchy`` pairs are directed ``(above, below)`` constraints --
    in the graph view, membership parents sit above their children and
    specializations sit below their generals.  Longest-path layering
    assigns each node a layer (roots at layer 0, strictly monotone
    along every hierarchy edge); ``links`` adds undirected edges that
    only influence the within-layer ordering.  Each layer becomes a
    ring around the y axis: ``sweeps`` alternating barycenter passes
    order every ring against its neighbor layers to shorten edges, and
    the ring radius grows with the layer's population so spacing stays
    readable.  Everything is scaled to sit inside ``radius`` like
    :func:`spring_layout`, so a front-end can interpolate between the
    two embeddings without re-fitting.

    Pure Python and seed-free: the same input always returns the same
    positions, regardless of edge iteration order.
    """

    if count <= 0:
        return []
    above = sorted({(u, v) for u, v in hierarchy if u != v})
    layer = _assign_layers(count, above)
    rings: dict[int, list[int]] = {}
    for node in range(count):
        rings.setdefault(layer[node], []).append(node)
    levels = sorted(rings)

    undirected = {(min(u, v), max(u, v)) for u, v in above}
    for u, v in links:
        if u != v:
            undirected.add((min(u, v), max(u, v)))
    neighbors: list[list[int]] = [[] for _ in range(count)]
    for u, v in sorted(undirected):
        neighbors[u].append(v)
        neighbors[v].append(u)

    # within-layer order: normalized ranks, refined by alternating
    # barycenter sweeps against the layer just above / just below
    pos = [0.0] * count

    def respace(ring: list[int]) -> None:
        span = max(len(ring) - 1, 1)
        for rank, node in enumerate(ring):
            pos[node] = rank / span

    for level in levels:
        rings[level].sort()
        respace(rings[level])
    for sweep in range(sweeps):
        forward = sweep % 2 == 0
        slots = range(1, len(levels)) if forward else range(len(levels) - 2, -1, -1)
        for slot in slots:
            level = levels[slot]
            side = levels[slot - 1] if forward else levels[slot + 1]
            ring = rings[level]
            weight: dict[int, float] = {}
            for node in ring:
                adjacent = [pos[m] for m in neighbors[node] if layer[m] == side]
                weight[node] = sum(adjacent) / len(adjacent) if adjacent else pos[node]
            ring[:] = [node for _, _, node in sorted((weight[n], n, n) for n in ring)]
            respace(ring)

    # placement: one ring per layer, stacked down the y axis; ring
    # radius follows population, the whole stack scaled into `radius`.
    # ponytail: one ring per layer; concentric sub-rings if very large
    # layers ever crowd
    tau = 2.0 * math.pi
    ring_radius = {
        level: 0.0 if len(ring) == 1 else max(0.75, len(ring) / tau)
        for level, ring in rings.items()
    }
    widest = max(ring_radius.values())
    xz_scale = (0.72 * radius / widest) if widest > 0 else 1.0
    floor = 0.12 * radius  # sparse rings stay readable, never a point
    top = 0.62 * radius if len(levels) > 1 else 0.0
    step = (2 * top) / max(len(levels) - 1, 1)
    points = [[0.0, 0.0, 0.0] for _ in range(count)]
    for slot, level in enumerate(levels):
        ring = rings[level]
        y = round(top - slot * step, 3)
        r = 0.0 if len(ring) == 1 else max(ring_radius[level] * xz_scale, floor)
        for rank, node in enumerate(ring):
            angle = tau * rank / len(ring)
            points[node] = [round(r * math.cos(angle), 3), y, round(r * math.sin(angle), 3)]
    return points


# Conventions follow longeron.analysis.viewer3d's front-end: DOM built
# once, geometry rebuilt only when the payload traitlet changes, the
# same ~30-line spherical orbit handler, rendering on demand.  Here:
# one InstancedMesh carries every node, one LineSegments per edge
# family carries every edge, and the layout morph lerps the two
# embeddings into a shared `live` position buffer that every mesh,
# label, and overlay reads.  The control surface (panel, pills,
# sliders, search, legend, chips) is the shared lgw-* chrome; filter
# and focus changes write traitlets for the kernel to recompute, while
# the morph, labels, search, and camera moves stay front-end-local.
# `standalone` (set by the export_html shim) hides kernel-backed
# controls so the exported page never shows a dead switch.
_ESM = r"""
async function render({ model, el }) {
  el.classList.add("longeron-graph3d", "lgw");
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
  const standalone = !!model.get("standalone");

  const aspect = Math.max(
    0.4, model.get("width_px") / Math.max(1, model.get("height_px")));
  const stage = document.createElement("div");
  stage.className = "longeron-graph3d-stage";
  el.appendChild(stage);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  stage.appendChild(renderer.domElement);
  const canvas = renderer.domElement;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "3D RDF graph view");
  canvas.tabIndex = 0;  // keyboard seam: f = focus, Escape = step out
  const hint = document.createElement("div");
  hint.className = "longeron-graph3d-hint";
  hint.textContent = "drag orbit \u00b7 shift-drag or right-drag pan " +
    "\u00b7 wheel zoom \u00b7 click select \u00b7 " +
    (standalone ? "" : "f focus \u00b7 ") + "double-click fit";
  const counts = document.createElement("div");
  counts.className = "longeron-graph3d-counts";
  const notice = document.createElement("div");
  notice.className = "longeron-graph3d-notice";
  const hover = document.createElement("div");
  hover.className = "longeron-graph3d-hover";
  stage.append(hint, counts, notice, hover);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog("#f4f4f2", 24, 96);  // depth cue, tracks zoom
  const camera = new THREE.PerspectiveCamera(42, aspect, 0.01, 400);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f98, 1.05));
  const key = new THREE.DirectionalLight(0xffffff, 1.1);
  key.position.set(2, 3, 1.5);
  scene.add(key);
  const content = new THREE.Group();  // rebuilt on payload changes
  const labels = new THREE.Group();   // billboard label sprites
  scene.add(content, labels);

  // --- theme: the Lab tokens style the chrome in pure CSS; read here
  // they also drive the scene -- clear color, fog, the dim tint, and
  // the label ink -- and a theme flip re-reads everything live
  const theme = { bg: new THREE.Color("#f4f4f2"), ink: "#2b2d31",
                  halo: "#f4f4f2", accent: "#2196f3" };
  function retheme() {
    const style = getComputedStyle(el);
    const token = (style.getPropertyValue("--jp-layout-color1") || "").trim();
    const ink = (style.getPropertyValue("--jp-ui-font-color1") || "").trim();
    theme.accent = (style.getPropertyValue("--jp-brand-color2") || "").trim()
      || "#2196f3";
    const bg = new THREE.Color(token || "#f6f6f4");
    const hsl = { h: 0, s: 0, l: 0 };
    bg.getHSL(hsl);
    bg.offsetHSL(0, 0, hsl.l > 0.5 ? -0.015 : 0.025);  // canvas off the panel
    theme.bg.copy(bg);
    theme.ink = ink || (hsl.l > 0.5 ? "#2b2d31" : "#d6d9de");
    theme.halo = "#" + theme.bg.getHexString();
    scene.background = theme.bg;
    scene.fog.color.copy(theme.bg);
    dropLabels();  // label canvases bake the old ink; repaint them
    updateLabels();
    applyEmphasis(false);
    requestRender();
  }
  const themeWatch = new MutationObserver(() => retheme());
  themeWatch.observe(document.body, { attributes: true,
    attributeFilter: ["data-jp-theme-light", "data-jp-theme-name"] });
  const scheme = matchMedia("(prefers-color-scheme: dark)");
  scheme.addEventListener("change", retheme);

  // --- camera: spherical orbit about a fit target, render on demand;
  // fog and label fade re-tune against the zoom radius
  let target = new THREE.Vector3();
  let radius = 30, theta = 0.9, phi = 1.05;
  let fitRadius = 30;
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
    scene.fog.near = radius * 0.8;
    scene.fog.far = radius * 2.9;
    fadeLabels();
    requestRender();
  }
  function fit() {
    if (!payload || !payload.nodes.length) { requestRender(); return; }
    const box = new THREE.Box3();
    const point = new THREE.Vector3();
    for (let i = 0; i < payload.nodes.length; i++) {
      box.expandByPoint(point.set(
        live[3 * i], live[3 * i + 1], live[3 * i + 2]));
    }
    box.getCenter(target);
    const size = box.getSize(new THREE.Vector3());
    const span = Math.max(size.x, size.y, size.z, 1e-6);
    radius = (span / 2) / Math.tan((camera.fov / 2) * Math.PI / 180) * 1.4;
    fitRadius = radius;
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

  // --- the layout morph: both embeddings ship in the payload; the
  // slider lerps them into `live` entirely front-end (zero kernel
  // round trips) and every mesh, edge, label, and pick reads `live`
  let payload = null;
  let live = new Float32Array(0);
  let morphT = 0;
  function remorph() {
    if (!payload) return;
    const from = payload.positions, to = payload.positions_dag;
    for (let i = 0; i < payload.nodes.length; i++) {
      const a = from[i], b = to[i];
      live[3 * i] = a[0] + (b[0] - a[0]) * morphT;
      live[3 * i + 1] = a[1] + (b[1] - a[1]) * morphT;
      live[3 * i + 2] = a[2] + (b[2] - a[2]) * morphT;
    }
  }
  function setMorph(t) {
    morphT = Math.min(1, Math.max(0, t));
    if (!payload) return;
    remorph();
    for (const rec of edgeRecs) refreshEdges(rec);
    applyEmphasis(false);
    placeLabels();
    requestRender();
  }

  // --- scene build: one InstancedMesh for every node, one
  // LineSegments per edge family -- a handful of draw calls
  let nodesMesh = null;
  let edgeRecs = [];
  let overlay = null;
  let idIndex = new Map();
  let adjacency = [];
  let topDegree = [];
  function disposeContent() {
    content.traverse((node) => {
      if (node.geometry) node.geometry.dispose();
      if (node.material) node.material.dispose();
    });
    content.clear();
    nodesMesh = null;
    overlay = null;
    edgeRecs = [];
  }
  function refreshEdges(rec) {
    const array = rec.geometry.attributes.position.array;
    for (let j = 0; j < rec.ends.length; j++) {
      const n = rec.ends[j];
      array[3 * j] = live[3 * n];
      array[3 * j + 1] = live[3 * n + 1];
      array[3 * j + 2] = live[3 * n + 2];
    }
    rec.geometry.attributes.position.needsUpdate = true;
    if (rec.dashed) rec.lines.computeLineDistances();
  }
  function build() {
    disposeContent();
    dropLabels();
    try { payload = JSON.parse(model.get("payload_json") || "null"); }
    catch (err) { payload = null; }
    idIndex = new Map();
    adjacency = [];
    topDegree = [];
    notice.textContent = (payload && payload.notice) || "";
    if (!payload || !payload.nodes.length) {
      counts.textContent = "no nodes in view";
      syncChips();
      buildLegend();
      requestRender();
      return;
    }
    const nodes = payload.nodes;
    live = new Float32Array(nodes.length * 3);
    remorph();
    nodes.forEach((node, i) => { idIndex.set(node.id, i); adjacency.push([]); });
    payload.edges.forEach(([s, t]) => { adjacency[s].push(t); adjacency[t].push(s); });
    topDegree = nodes.map((node, i) => i).sort((a, b) =>
      (nodes[b].deg - nodes[a].deg) || (nodes[a].id < nodes[b].id ? -1 : 1));
    const sphere = new THREE.SphereGeometry(1, 12, 8);
    nodesMesh = new THREE.InstancedMesh(
      sphere, new THREE.MeshLambertMaterial({ color: 0xffffff }), nodes.length);
    nodesMesh.frustumCulled = false;  // instances morph; skip stale culling
    content.add(nodesMesh);
    const byFamily = payload.families.map(() => []);
    for (const [s, t, f] of payload.edges) byFamily[f].push(s, t);
    payload.families.forEach((family, f) => {
      const ends = byFamily[f];
      if (!ends.length) return;
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position",
        new THREE.BufferAttribute(new Float32Array(ends.length * 3), 3));
      const material = family.dashed
        ? new THREE.LineDashedMaterial({ color: family.color, transparent: true,
            opacity: family.opacity, dashSize: 0.14, gapSize: 0.1 })
        : new THREE.LineBasicMaterial({ color: family.color, transparent: true,
            opacity: family.opacity });
      const lines = new THREE.LineSegments(geometry, material);
      lines.frustumCulled = false;
      lines.raycast = () => {};  // hover and click belong to the spheres
      const rec = { lines, geometry, material, ends,
                    dashed: !!family.dashed, opacity: family.opacity };
      refreshEdges(rec);
      edgeRecs.push(rec);
      content.add(lines);
    });
    counts.textContent =
      payload.counts.nodes + " nodes \u00b7 " + payload.counts.edges + " edges";
    applyEmphasis(false);
    updateLabels();
    buildLegend();
    syncChips();
    fit();
  }

  // --- emphasis: the selection (and the hovered node) pops in the Lab
  // accent, k=1 neighbors stay lit, the rest recede toward the canvas
  // color; base edges drop to a fraction of their opacity and the
  // incident edges re-draw on an accent overlay
  let hoverIdx = -1;
  function selectionIndices() {
    return (model.get("selected") || [])
      .map((id) => idIndex.get(id)).filter((i) => i !== undefined);
  }
  function applyEmphasis(paint = true) {
    if (!nodesMesh || !payload) return;
    if (overlay) {
      overlay.geometry.dispose();
      overlay.material.dispose();
      content.remove(overlay);
      overlay = null;
    }
    const picked = selectionIndices();
    const selected = new Set(picked);
    const chosen = new Set(picked);
    if (hoverIdx >= 0) chosen.add(hoverIdx);
    const color = new THREE.Color();
    const matrix = new THREE.Matrix4();
    const near = new Set(chosen);
    for (const i of chosen) for (const j of adjacency[i]) near.add(j);
    payload.nodes.forEach((node, i) => {
      color.set(node.color);
      let scale = node.r;
      if (chosen.size) {
        if (selected.has(i)) { color.set(theme.accent); scale = node.r * 1.6; }
        else if (i === hoverIdx) scale = node.r * 1.25;
        else if (!near.has(i)) color.lerp(theme.bg, 0.82);
      }
      nodesMesh.setColorAt(i, color);
      matrix.makeScale(scale, scale, scale)
        .setPosition(live[3 * i], live[3 * i + 1], live[3 * i + 2]);
      nodesMesh.setMatrixAt(i, matrix);
    });
    for (const rec of edgeRecs) {
      rec.material.opacity = rec.opacity * (chosen.size ? 0.22 : 1);
    }
    if (chosen.size) {
      const ends = [];
      for (const [s, t] of payload.edges) {
        if (chosen.has(s) || chosen.has(t)) ends.push(s, t);
      }
      if (ends.length) {
        const array = new Float32Array(ends.length * 3);
        ends.forEach((n, j) => {
          array[3 * j] = live[3 * n];
          array[3 * j + 1] = live[3 * n + 1];
          array[3 * j + 2] = live[3 * n + 2];
        });
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute("position", new THREE.BufferAttribute(array, 3));
        overlay = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({
          color: theme.accent, transparent: true, opacity: 0.9 }));
        overlay.raycast = () => {};
        overlay.frustumCulled = false;
        content.add(overlay);
      }
    }
    nodesMesh.instanceColor.needsUpdate = true;
    nodesMesh.instanceMatrix.needsUpdate = true;
    if (paint) requestRender();
  }

  // --- billboard labels: canvas-texture sprites for the top-degree
  // nodes (the panel slider budgets the density), always for the
  // selection, its strongest neighbors, and the hovered node; opacity
  // fades with camera distance so a crowded shell quiets down
  let labelBudget = 12;
  const spriteByNode = new Map();
  function dropLabels() {
    for (const sprite of spriteByNode.values()) {
      sprite.material.map.dispose();
      sprite.material.dispose();
    }
    spriteByNode.clear();
    labels.clear();
  }
  function makeSprite(i) {
    const node = payload.nodes[i];
    const text = node.label || node.id;
    const surface = document.createElement("canvas");
    const probe = surface.getContext("2d");
    const font = "600 26px " + (getComputedStyle(el).fontFamily || "sans-serif");
    probe.font = font;
    const width = Math.min(360, Math.ceil(probe.measureText(text).width) + 22);
    surface.width = width * 2;
    surface.height = 76;
    const draw = surface.getContext("2d");
    draw.scale(2, 2);
    draw.font = font;
    draw.textAlign = "center";
    draw.textBaseline = "middle";
    draw.lineWidth = 6;
    draw.lineJoin = "round";
    draw.strokeStyle = theme.halo;
    draw.strokeText(text, width / 2, 19);
    draw.fillStyle = theme.ink;
    draw.fillText(text, width / 2, 19);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: new THREE.CanvasTexture(surface), transparent: true,
      depthTest: false, fog: false }));
    const h = 0.62;
    sprite.scale.set(h * surface.width / surface.height, h, 1);
    sprite.renderOrder = 2;
    return sprite;
  }
  function labelSet() {
    const want = new Set();
    if (!payload) return want;
    for (const i of topDegree.slice(0, labelBudget)) want.add(i);
    for (const i of selectionIndices()) {
      want.add(i);
      adjacency[i].slice()
        .sort((a, b) => payload.nodes[b].deg - payload.nodes[a].deg)
        .slice(0, 24).forEach((j) => want.add(j));
    }
    if (hoverIdx >= 0) want.add(hoverIdx);
    return want;
  }
  function updateLabels() {
    if (!payload) { dropLabels(); return; }
    const want = labelSet();
    for (const [i, sprite] of [...spriteByNode]) {
      if (want.has(i)) continue;
      labels.remove(sprite);
      sprite.material.map.dispose();
      sprite.material.dispose();
      spriteByNode.delete(i);
    }
    for (const i of want) {
      if (spriteByNode.has(i)) continue;
      const sprite = makeSprite(i);
      spriteByNode.set(i, sprite);
      labels.add(sprite);
    }
    placeLabels();
    fadeLabels();
  }
  function placeLabels() {
    if (!payload) return;
    for (const [i, sprite] of spriteByNode) {
      sprite.position.set(
        live[3 * i],
        live[3 * i + 1] + payload.nodes[i].r * 1.7 + 0.28,
        live[3 * i + 2]);
    }
  }
  function fadeLabels() {
    if (!spriteByNode.size) return;
    const anchor = new Set(selectionIndices());
    if (hoverIdx >= 0) anchor.add(hoverIdx);
    const near = radius * 0.6, far = radius * 2.4;
    for (const [i, sprite] of spriteByNode) {
      const d = camera.position.distanceTo(sprite.position);
      let a = Math.min(1, Math.max(0, (far - d) / (far - near)));
      if (anchor.has(i)) a = Math.max(a, 0.95);
      sprite.material.opacity = a;
      sprite.visible = a > 0.03;
    }
  }

  // --- hover: raycast the instanced spheres; the hit node is named in
  // the tooltip and its neighborhood emphasized live
  const raycaster = new THREE.Raycaster();
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
    if (index !== hoverIdx) {
      hoverIdx = index;
      applyEmphasis(false);
      updateLabels();
      requestRender();
    }
    if (index < 0) { hover.style.display = "none"; return; }
    const node = payload.nodes[index];
    hover.textContent = [node.label, node.id, ...node.info].join("\n");
    const rect = stage.getBoundingClientRect();
    hover.style.left = Math.min(event.clientX - rect.left + 14,
                                Math.max(0, rect.width - 260)) + "px";
    hover.style.top = (event.clientY - rect.top + 12) + "px";
    hover.style.display = "block";
  }
  function clearHover() {
    hover.style.display = "none";
    if (hoverIdx < 0) return;
    hoverIdx = -1;
    applyEmphasis(false);
    updateLabels();
    requestRender();
  }

  // --- camera choreography: an eased 600ms fly-to on selection and
  // search, an optional slow idle orbit; any hand on the camera
  // (drag, wheel, key) cancels both
  let fly = null;
  let orbitOn = false, orbitMark = 0;
  let orbitPill = null;
  function flyTo(i) {
    if (i === undefined || !payload) return;
    fly = {
      start: performance.now(),
      fromX: target.x, fromY: target.y, fromZ: target.z, fromR: radius,
      toX: live[3 * i], toY: live[3 * i + 1], toZ: live[3 * i + 2],
      toR: Math.max(2.5, Math.min(radius, fitRadius * 0.45)),
    };
    requestAnimationFrame(stepFly);
  }
  function stepFly(now) {
    if (!fly) return;
    const u = Math.min(1, (now - fly.start) / 600);
    const e = 1 - Math.pow(1 - u, 3);  // ease-out cubic
    target.set(fly.fromX + (fly.toX - fly.fromX) * e,
               fly.fromY + (fly.toY - fly.fromY) * e,
               fly.fromZ + (fly.toZ - fly.fromZ) * e);
    radius = fly.fromR + (fly.toR - fly.fromR) * e;
    applyCamera();
    if (u < 1) requestAnimationFrame(stepFly);
    else fly = null;
  }
  function stepOrbit(now) {
    if (!orbitOn) return;
    theta += Math.min(64, now - orbitMark) * 0.00011;
    orbitMark = now;
    applyCamera();
    requestAnimationFrame(stepOrbit);
  }
  function setOrbit(on) {
    orbitOn = on;
    if (orbitPill) orbitPill.checked = on;
    if (on) { orbitMark = performance.now(); requestAnimationFrame(stepOrbit); }
  }
  function cancelMotion() {
    fly = null;
    if (orbitOn) setOrbit(false);
  }

  // --- interaction: drag orbits, shift/right-drag pans, wheel zooms,
  // a still click selects, double-click re-fits, f focuses
  canvas.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  let dragging = null;  // { mode: "orbit" | "pan", x, y, x0, y0, moved }
  let hoverEvent = null, hoverQueued = false;
  canvas.addEventListener("pointerdown", (event) => {
    cancelMotion();
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
  canvas.addEventListener("pointerleave", clearHover);
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    cancelMotion();
    radius = Math.min(300, Math.max(0.05,
                                    radius * Math.exp(event.deltaY * 0.001)));
    applyCamera();
  }, { passive: false });
  canvas.addEventListener("dblclick", fit);
  canvas.addEventListener("keydown", (event) => {
    if (event.key === "f" || event.key === "F") {
      cancelMotion();
      const picked = selectionIndices();
      if (picked.length && !standalone) {
        writeFocus(payload.nodes[picked[0]].id);
        event.preventDefault();
      }
    } else if (event.key === "Escape") {
      cancelMotion();
      if (payload && payload.focus && !standalone) {
        writeFocus(null);
        event.preventDefault();
      }
    }
  });

  // --- the control surface --------------------------------------------
  // the morph slider rides top-center: pure force layout on the left
  // end, the layered hierarchy on the right, a front-end lerp between
  const morphBar = document.createElement("div");
  morphBar.className = "lgw-morphbar";
  const endForce = document.createElement("span");
  endForce.textContent = "force";
  endForce.className = "on";
  const endDag = document.createElement("span");
  endDag.textContent = "hierarchy";
  const morphSlider = document.createElement("input");
  morphSlider.type = "range";
  morphSlider.min = "0";
  morphSlider.max = "1";
  morphSlider.step = "0.01";
  morphSlider.value = "0";
  morphSlider.className = "lgw-slider";
  morphSlider.setAttribute("aria-label", "layout morph: force to hierarchy");
  morphSlider.style.setProperty("--p", "0");
  morphBar.append(endForce, morphSlider, endDag);
  stage.appendChild(morphBar);
  let morphQueued = false;
  morphSlider.addEventListener("input", () => {
    const t = +morphSlider.value;
    morphSlider.style.setProperty("--p", String(t));
    endForce.classList.toggle("on", t < 0.5);
    endDag.classList.toggle("on", t >= 0.5);
    if (morphQueued) return;
    morphQueued = true;
    requestAnimationFrame(() => {
      morphQueued = false;
      setMorph(+morphSlider.value);
    });
  });

  // breadcrumb chips: step into a focus, step back out
  const chipBar = document.createElement("div");
  chipBar.className = "lgw-chipbar";
  stage.appendChild(chipBar);
  let currentK = 1;
  function writeFocus(id) {
    model.set("focus_json", JSON.stringify(id ? { id: id, k: currentK } : {}));
    model.save_changes();
  }
  function syncChips() {
    chipBar.innerHTML = "";
    const focus = payload && payload.focus;
    if (focus) {
      if (!standalone) {
        const back = document.createElement("button");
        back.type = "button";
        back.className = "lgw-crumb";
        back.textContent = "\u25c2 all " + focus.of + " nodes";
        back.addEventListener("click", () => writeFocus(null));
        chipBar.appendChild(back);
      }
      const here = document.createElement("span");
      here.className = "lgw-crumb lgw-crumb-static";
      here.textContent = focus.id.split("::").pop() + " \u00b7 " + focus.k
        + "-hop \u00b7 " + payload.counts.nodes + " nodes";
      chipBar.appendChild(here);
      return;
    }
    if (standalone || !payload) return;
    const picked = selectionIndices();
    if (!picked.length) return;
    const node = payload.nodes[picked[0]];
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "lgw-crumb";
    chip.textContent = "\u2316 focus " + (node.label || node.id);
    chip.title = "isolate the " + currentK + "-hop neighborhood (f)";
    chip.addEventListener("click", () => writeFocus(node.id));
    chipBar.appendChild(chip);
  }

  // the panel: search, view controls, focus depth, and the filter
  // pills -- real checkboxes under the styling, filters_json beneath
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
  function addPill(row, group, name, swatch) {
    const label = document.createElement("label");
    label.className = "lgw-pill";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = true;
    label.appendChild(input);
    if (swatch) {
      label.style.setProperty("--c", swatch);
      const chip = document.createElement("span");
      chip.className = "lgw-chip";
      label.appendChild(chip);
    }
    const text = document.createElement("span");
    text.textContent = name;
    label.appendChild(text);
    row.appendChild(label);
    if (group !== "local") {
      input.addEventListener("change", pushFilters);
      boxes.push({ input: input, group: group, name: name });
    }
    return input;
  }

  const panel = document.createElement("div");
  panel.className = "lgw-panel";
  const head = document.createElement("div");
  head.className = "lgw-panel-head";
  const panelToggle = document.createElement("button");
  panelToggle.type = "button";
  panelToggle.className = "lgw-panel-toggle";
  panelToggle.setAttribute("aria-expanded", "true");
  const panelCaret = document.createElement("span");
  panelCaret.className = "lgw-caret";
  panelCaret.textContent = "\u25be";
  panelToggle.append(panelCaret, document.createTextNode("controls"));
  panelToggle.addEventListener("click", () => {
    const closed = panel.classList.toggle("closed");
    panelToggle.setAttribute("aria-expanded", String(!closed));
  });
  head.appendChild(panelToggle);
  const bodyWrap = document.createElement("div");
  bodyWrap.className = "lgw-panel-body";
  const body = document.createElement("div");
  bodyWrap.appendChild(body);
  panel.append(head, bodyWrap);
  stage.appendChild(panel);

  function addHeading(text) {
    const heading = document.createElement("div");
    heading.className = "lgw-heading";
    heading.textContent = text;
    body.appendChild(heading);
  }
  function pillRow() {
    const row = document.createElement("div");
    row.className = "lgw-pills";
    body.appendChild(row);
    return row;
  }

  // search: type-ahead over qualified names; Enter or click selects
  // the node and flies the camera to it
  const searchWrap = document.createElement("div");
  searchWrap.className = "lgw-search";
  const searchInput = document.createElement("input");
  searchInput.type = "search";
  searchInput.placeholder = "search nodes";
  searchInput.setAttribute("aria-label", "search nodes by qualified name");
  const searchList = document.createElement("div");
  searchList.className = "lgw-search-list";
  searchList.setAttribute("role", "listbox");
  searchWrap.append(searchInput, searchList);
  body.appendChild(searchWrap);
  let searchActive = -1;
  function clearSearch() {
    searchList.innerHTML = "";
    searchActive = -1;
  }
  function pickNode(id) {
    clearSearch();
    searchInput.value = "";
    model.set("selected", [id]);
    model.save_changes();  // change:selected flies the camera
  }
  function runSearch() {
    clearSearch();
    const query = searchInput.value.trim().toLowerCase();
    if (!query || !payload) return;
    const hits = [];
    for (const node of payload.nodes) {
      if (node.id.toLowerCase().includes(query)) {
        hits.push(node);
        if (hits.length >= 8) break;
      }
    }
    for (const node of hits) {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "lgw-option";
      option.setAttribute("role", "option");
      const name = document.createElement("span");
      name.textContent = node.label || node.id;
      const qual = document.createElement("span");
      qual.className = "lgw-option-id";
      qual.textContent = node.id;
      option.append(name, qual);
      option.addEventListener("click", () => pickNode(node.id));
      searchList.appendChild(option);
    }
  }
  function moveActive(step) {
    const options = [...searchList.children];
    if (!options.length) return;
    if (searchActive >= 0) options[searchActive].removeAttribute("aria-selected");
    searchActive = (searchActive + step + options.length) % options.length;
    options[searchActive].setAttribute("aria-selected", "true");
    options[searchActive].scrollIntoView({ block: "nearest" });
  }
  searchInput.addEventListener("input", runSearch);
  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") { moveActive(1); event.preventDefault(); }
    else if (event.key === "ArrowUp") { moveActive(-1); event.preventDefault(); }
    else if (event.key === "Enter") {
      const options = [...searchList.children];
      const hit = options[searchActive >= 0 ? searchActive : 0];
      if (hit) hit.click();
      event.preventDefault();
    } else if (event.key === "Escape") { clearSearch(); }
  });

  addHeading("view");
  const labelRow = document.createElement("div");
  labelRow.className = "lgw-row";
  const labelName = document.createElement("span");
  labelName.textContent = "labels";
  const labelSlider = document.createElement("input");
  labelSlider.type = "range";
  labelSlider.min = "0";
  labelSlider.max = "48";
  labelSlider.step = "1";
  labelSlider.value = String(labelBudget);
  labelSlider.className = "lgw-slider";
  labelSlider.setAttribute("aria-label", "billboard label budget");
  labelSlider.style.setProperty("--p", String(labelBudget / 48));
  const labelValue = document.createElement("span");
  labelValue.className = "lgw-value";
  labelValue.textContent = String(labelBudget);
  labelRow.append(labelName, labelSlider, labelValue);
  body.appendChild(labelRow);
  labelSlider.addEventListener("input", () => {
    labelBudget = +labelSlider.value;
    labelSlider.style.setProperty("--p", String(labelBudget / 48));
    labelValue.textContent = labelBudget ? String(labelBudget) : "off";
    updateLabels();
    requestRender();
  });
  const viewPills = pillRow();
  orbitPill = addPill(viewPills, "local", "idle orbit", null);
  orbitPill.checked = false;
  orbitPill.addEventListener("change", () => setOrbit(orbitPill.checked));

  function kButton(row, k) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "lgw-pill";
    button.textContent = k + "-hop";
    button.setAttribute("aria-pressed", String(k === currentK));
    button.addEventListener("click", () => {
      currentK = k;
      for (const sibling of row.children) {
        sibling.setAttribute("aria-pressed", String(sibling === button));
      }
      if (payload && payload.focus) writeFocus(payload.focus.id);
      else syncChips();
    });
    row.appendChild(button);
    return button;
  }
  const options = JSON.parse(model.get("options_json") || "{}");
  if (!standalone) {
    addHeading("focus");
    const focusRow = pillRow();
    kButton(focusRow, 1);
    kButton(focusRow, 2);
    const focusHint = document.createElement("div");
    focusHint.className = "lgw-note";
    focusHint.textContent = "select a node, then f (or the chip) to isolate";
    body.appendChild(focusHint);
    addHeading("namespaces");
    const nsRow = pillRow();
    for (const name of options.namespaces || []) {
      addPill(nsRow, "namespaces", name, null);
    }
    addHeading("edges");
    const famRow = pillRow();
    for (const fam of options.families || []) {
      addPill(famRow, "families", fam.name, fam.color);
    }
    addHeading("show");
    addPill(pillRow(), "isolated", "unlinked nodes", null);
  }

  // --- the in-scene legend: node kinds, edge families, the size cue
  const legend = document.createElement("div");
  legend.className = "lgw-legend";
  const legendToggle = document.createElement("button");
  legendToggle.type = "button";
  legendToggle.className = "lgw-panel-toggle";
  legendToggle.setAttribute("aria-expanded", "true");
  const legendCaret = document.createElement("span");
  legendCaret.className = "lgw-caret";
  legendCaret.textContent = "\u25be";
  legendToggle.append(legendCaret, document.createTextNode("legend"));
  legendToggle.addEventListener("click", () => {
    const closed = legend.classList.toggle("closed");
    legendToggle.setAttribute("aria-expanded", String(!closed));
  });
  const legendWrap = document.createElement("div");
  legendWrap.className = "lgw-panel-body";
  const legendBody = document.createElement("div");
  legendWrap.appendChild(legendBody);
  legend.append(legendToggle, legendWrap);
  stage.appendChild(legend);
  const KIND_ORDER = ["package", "structure", "behavior", "data", "connector",
                      "requirement", "relationship", "literal", "external"];
  function legendRow() {
    const row = document.createElement("div");
    row.className = "lgw-key";
    legendBody.appendChild(row);
    return row;
  }
  function buildLegend() {
    legendBody.innerHTML = "";
    if (!payload || !payload.nodes.length) return;
    const seen = new Map();
    for (const node of payload.nodes) {
      if (!seen.has(node.family)) seen.set(node.family, node.color);
    }
    for (const family of KIND_ORDER) {
      if (!seen.has(family)) continue;
      const row = legendRow();
      const dot = document.createElement("span");
      dot.className = "lgw-dot";
      dot.style.background = seen.get(family);
      const name = document.createElement("span");
      name.textContent = family;
      row.append(dot, name);
    }
    const used = new Set(payload.edges.map((edge) => edge[2]));
    payload.families.forEach((family, f) => {
      if (!used.has(f)) return;
      const row = legendRow();
      const line = document.createElement("span");
      line.className = "lgw-line";
      line.style.borderTopColor = family.color;
      line.style.borderTopStyle = family.dashed ? "dashed" : "solid";
      const name = document.createElement("span");
      name.textContent = family.name;
      row.append(line, name);
    });
    const cue = legendRow();
    cue.classList.add("lgw-cue");
    for (const size of [4, 7, 10]) {
      const dot = document.createElement("span");
      dot.className = "lgw-dot";
      dot.style.width = size + "px";
      dot.style.height = size + "px";
      cue.appendChild(dot);
    }
    const name = document.createElement("span");
    name.textContent = "degree";
    cue.appendChild(name);
  }

  function onSelection() {
    applyEmphasis(false);
    updateLabels();
    syncChips();
    const picked = selectionIndices();
    if (picked.length) flyTo(picked[0]);
    requestRender();
  }

  model.on("change:payload_json", build);
  model.on("change:selected", onSelection);
  model.on("change:filters_json", pullFilters);
  retheme();
  pullFilters();
  build();
  return () => {
    observer.disconnect();
    themeWatch.disconnect();
    scheme.removeEventListener("change", retheme);
    orbitOn = false;
    fly = null;
    renderer.dispose();
  };
}
export default { render };
""".replace("%THREE_URL%", THREE_URL)

_CSS = (
    CONTROL_CSS
    + """
.longeron-graph3d {
  font-family: var(--jp-ui-font-family, Helvetica, Arial, sans-serif);
}
.longeron-graph3d-stage {
  border: 1px solid var(--lgw-line); border-radius: 8px;
  overflow: hidden; background: var(--lgw-bg); position: relative;
  width: 100%;
}
.longeron-graph3d-stage canvas { display: block; cursor: grab; }
.longeron-graph3d-stage canvas:active { cursor: grabbing; }
.longeron-graph3d-stage canvas:focus-visible {
  outline: 2px solid var(--lgw-accent); outline-offset: -2px;
}
.longeron-graph3d-hint {
  position: absolute; right: 8px; bottom: 6px; font-size: 10px;
  color: var(--lgw-mute); background: var(--lgw-veil);
  padding: 2px 8px; border-radius: 9px; pointer-events: none;
  user-select: none;
}
.longeron-graph3d-counts {
  position: absolute; left: 8px; bottom: 6px; font-size: 10px;
  color: var(--lgw-mute); background: var(--lgw-veil);
  padding: 2px 8px; border-radius: 9px; pointer-events: none;
  font-variant-numeric: tabular-nums;
}
.longeron-graph3d-notice {
  position: absolute; top: 8px; right: 8px; font-size: 11px;
  color: color-mix(in srgb, #8a6d1f 75%, var(--lgw-ink));
  background: color-mix(in srgb, #e9b23c 22%, var(--lgw-bg));
  padding: 3px 10px; border-radius: 9px; pointer-events: none;
  max-width: 40%;
}
.longeron-graph3d-notice:empty { display: none; }
.longeron-graph3d-hover {
  position: absolute; display: none; pointer-events: none;
  background: rgba(28, 30, 34, 0.94); color: #f2f3f5; font-size: 11px;
  line-height: 1.45; padding: 6px 9px; border-radius: 6px;
  white-space: pre-line; max-width: 320px; z-index: 4;
}
.longeron-graph3d-offline {
  border: 1px dashed #d4d4d4; border-radius: 8px; padding: 14px;
  font-size: 12px; color: #777777;
}
"""
)

#: the standalone page written by ``export_html``: the widget CSS and
#: ESM inlined next to a tiny model shim; dark mode maps the OS scheme
#: onto the same JupyterLab tokens the live widget reads
_EXPORT_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%TITLE%</title>
<style>
:root { color-scheme: light dark; }
@media (prefers-color-scheme: dark) {
  :root {
    --jp-layout-color1: #15181d;
    --jp-ui-font-color1: #d6d9de;
    --jp-ui-font-color2: #99a0a9;
    --jp-border-color1: #343a42;
    --jp-brand-color1: #4c9fea;
    --jp-brand-color2: #4c9fea;
  }
}
body { margin: 0; background: var(--jp-layout-color1, #f6f6f4); }
main { padding: 12px; }
%CSS%
</style>
</head>
<body>
<main id="view"></main>
<script type="module">
const data = %DATA%;
data.standalone = true;
const listeners = {};
const model = {
  get: (name) => data[name],
  set: (name, value) => {
    data[name] = value;
    for (const fn of listeners["change:" + name] || []) fn();
  },
  save_changes: () => {},
  on: (event, fn) => { (listeners[event] = listeners[event] || []).push(fn); },
};
%ESM%
render({ model, el: document.getElementById("view") });
</script>
</body>
</html>
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
        #: the drawable view: nodes, both position arrays, edges,
        #: families, focus breadcrumb, notice
        payload_json = traitlets.Unicode("").tag(sync=True)
        #: filter options (all namespaces + the edge-family style table)
        options_json = traitlets.Unicode("{}").tag(sync=True)
        #: active filters; the front-end panel writes this, the kernel
        #: observer re-extracts and re-layouts the view
        filters_json = traitlets.Unicode("{}").tag(sync=True)
        #: focus mode: ``{"id": qualified_name, "k": hops}`` isolates a
        #: neighborhood, ``{}`` restores the full view; the front-end
        #: chips write it, the kernel observer recomputes
        focus_json = traitlets.Unicode("{}").tag(sync=True)
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
            #: seconds the last kernel-side layout took (both embeddings)
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
            self.observe(self._on_view_change, names=["filters_json", "focus_json"])
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
            re-layout path serves the browser panel's toggle pills, so
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

        def focus(self, node_id: str, *, k: int = 1) -> dict[str, int]:
            """Isolate ``node_id``'s k-hop neighborhood; returns counts.

            The kernel re-extracts the neighborhood from the current
            filtered view and re-layouts both embeddings -- instant at
            sub-graph size.  The browser's focus chip and the ``f`` key
            write the same ``focus_json`` seam.  A ``node_id`` missing
            from the current view leaves the full view in place.  The
            selection contract is untouched by focus.
            """

            self.focus_json = json.dumps({"id": str(node_id), "k": int(k)})
            return self.counts

        def unfocus(self) -> dict[str, int]:
            """Restore the full (filtered) view; returns the new counts."""

            self.focus_json = "{}"
            return self.counts

        def export_html(self, path: str | Path) -> Path:
            """Write the current view as a self-contained HTML page.

            The page inlines the payload (both embeddings), the widget
            front-end, its stylesheet, and a small model shim, so it
            opens in any browser with no kernel, no anywidget, and no
            Jupyter.  The morph slider, search, labels, legend, and
            selection emphasis all work; kernel-backed controls
            (filters, focus) hide themselves.  Dark mode follows the OS
            scheme.  Like the live widget, the page loads three.js from
            the CDN at view time, so an offline reader sees the printed
            notice instead of a scene.  Returns the written path.
            """

            data = {
                "payload_json": self.payload_json,
                "options_json": self.options_json,
                "filters_json": self.filters_json,
                "focus_json": self.focus_json,
                "selected": list(self.selected),
                "width_px": self.width_px,
                "height_px": self.height_px,
            }
            page = (
                _EXPORT_PAGE.replace("%TITLE%", "longeron \u00b7 3D RDF graph")
                .replace("%CSS%", _CSS)
                .replace("%ESM%", _ESM)
                .replace("%DATA%", json.dumps(data).replace("</", "<\\/"))
            )
            target = Path(path)
            target.write_text(page, encoding="utf-8")
            return target

        # -- internals -------------------------------------------------------

        def _on_view_change(self, change: Any) -> None:
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
            # focus: restrict to the k-hop neighborhood of the target
            # (searched in the full filtered view, before the cap)
            focus = json.loads(self.focus_json or "{}")
            focus_out: dict[str, Any] | None = None
            wanted = focus.get("id")
            if wanted is not None:
                start = next((i for i, node in enumerate(nodes) if node["id"] == wanted), None)
                if start is not None:
                    hops = max(1, min(int(focus.get("k", 1)), 4))
                    neighbors: list[list[int]] = [[] for _ in nodes]
                    for s, t, _f in edges:
                        neighbors[s].append(t)
                        neighbors[t].append(s)
                    keep = {start}
                    frontier = [start]
                    for _ in range(hops):
                        reached = {m for n in frontier for m in neighbors[n]} - keep
                        keep |= reached
                        frontier = sorted(reached)
                    total = len(nodes)
                    kept = sorted(keep)
                    remap = {old: new for new, old in enumerate(kept)}
                    nodes = [nodes[i] for i in kept]
                    edges = [
                        [remap[s], remap[t], f] for s, t, f in edges if s in remap and t in remap
                    ]
                    focus_out = {"id": wanted, "k": hops, "of": total}
            notice = ""
            if len(nodes) > self._node_cap:
                total = len(nodes)
                by_degree = sorted(range(total), key=lambda i: (-nodes[i]["deg"], nodes[i]["id"]))
                keep_cap = sorted(by_degree[: self._node_cap])
                remap = {old: new for new, old in enumerate(keep_cap)}
                nodes = [nodes[i] for i in keep_cap]
                edges = [[remap[s], remap[t], f] for s, t, f in edges if s in remap and t in remap]
                notice = (
                    f"showing {self._node_cap} of {total} nodes (highest degree) -- "
                    "filter namespaces or raise node_cap"
                )
            # hierarchy pairs for the layered embedding: membership and
            # value leaves point down, specialization points up
            family_names = [entry["name"] for entry in view["families"]]
            hierarchy: list[tuple[int, int]] = []
            for s, t, f in edges:
                name = family_names[f]
                if name in ("membership", "value"):
                    hierarchy.append((s, t))
                elif name == "specialization":
                    hierarchy.append((t, s))
            begun = time.perf_counter()
            positions = spring_layout(
                len(nodes),
                ((s, t) for s, t, _ in edges),
                seed=self._seed,
                iterations=self._iterations,
            )
            positions_dag = dag_layout(len(nodes), hierarchy, ((s, t) for s, t, _ in edges))
            self.layout_seconds = time.perf_counter() - begun
            self.payload_json = json.dumps(
                {
                    "nodes": nodes,
                    "edges": edges,
                    "families": view["families"],
                    "positions": positions,
                    "positions_dag": positions_dag,
                    "focus": focus_out,
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
    :func:`graph_view`; the in-scene panel (or ``widget.filter(...)``)
    changes them later, re-layouting kernel-side on every change.
    ``seed`` and ``iterations`` steer the deterministic
    :func:`spring_layout` embedding; the layered :func:`dag_layout`
    embedding ships alongside it and the in-scene slider morphs
    between the two without kernel round trips.

    Views larger than ``node_cap`` nodes keep the ``node_cap``
    highest-degree nodes and say so in an in-scene notice: rendering is
    instanced and stays fluid into five figures, but the exact O(n^2)
    layout is the honest ceiling, so the cap protects the kernel rather
    than the GPU.

    The widget's ``selected`` trait (qualified names, two-way) plus
    ``on_select(callback)`` form the same selection contract the
    explorer's tree exposes: clicks land in the kernel, kernel
    assignments drive the in-scene emphasis (and an eased camera
    fly-to), and ``counts`` / ``layout_seconds`` report the current
    view's size and layout cost.  ``focus(id, k=...)`` / ``unfocus()``
    isolate a neighborhood kernel-side, and ``export_html(path)``
    writes the current view as a self-contained standalone page.
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
