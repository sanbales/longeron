"""A model explorer for Jupyter: tree navigator beside a diagram pane.

:func:`explore` builds the widget::

    import longeron
    from longeron import explorer

    model = longeron.load("examples/drone.sysml")
    explorer.explore(model)

The LEFT pane is :class:`ModelTree` -- a small self-contained anywidget
tree over the model's OWNING structure (packages, definitions, usages,
nested members; node ids are qualified names).  Rows carry a kind badge
(``part def`` / ``state`` / ``requirement`` ...) colored by family, a dim
``: Type`` suffix for typed usages, disclosure triangles with lazy child
rendering (only expanded rows reach the DOM, so the biggest shipped
example stays snappy), roving-focus keyboard navigation (arrows move
focus, Enter/Space selects), and the toolbar search idiom from
:mod:`longeron.toolbar`: a live substring filter over names and
qualified names with a ``matches/total`` count that prunes the tree to
matches plus their ancestors.

The RIGHT pane shows the selected element through the diagram kind
picked by a compact toggle switcher that only offers the APPLICABLE
kinds: ``structure`` for everything (:func:`~longeron.diagrams.
structure_diagram` scoped to the nearest owning package, so the element
appears among its siblings and relationship edges), ``state`` / ``action``
for state and action definitions/usages, and ``requirements`` -- the
structure view re-scoped to the containing package's requirement
definitions/usages, satisfy usages and their satisfying elements (see
:func:`requirements_view`).  Switching kinds preserves the selection;
every diagram keeps its own toolbar (fit / center / routing / search).

Selection links BOTH ways and is echo-free by idempotence: selecting a
tree row renders (or reuses -- diagrams are cached per scope and kind)
the applicable diagram and highlights the element through the diagram's
selection tool; clicking a diagram node (:func:`~longeron.diagrams.
on_select`) selects and reveals the element in the tree -- ancestors
expand, the row scrolls into view -- WITHOUT rebuilding the diagram that
was clicked.  Every hop writes a trait only when the value actually
changes, so a selection echo dies at its first fixpoint instead of
ping-ponging.

Composed strictly from public surfaces: the diagram constructors and
``on_select`` from :mod:`longeron.diagrams`, the model vocabulary, and
the resolver.  Needs the diagram toolchain (the vendored ipyelk) plus
anywidget, like :mod:`longeron.replay`.

The tree pane sits behind a SMALL EXPLICIT SEAM -- the :class:`TreeView`
protocol (``set_nodes`` / ``selected`` / ``on_select`` / ``reveal`` /
``filter``) over :class:`TreeNode` dicts -- so the engine can be swapped
(say, for a react-arborist-based tree widget) without touching any
explorer logic: pass any conforming engine as ``Explorer(model,
tree=...)``.  :class:`ModelTree` is the built-in engine.

Layout is a second small seam: ``explore(model, layout=...)`` composes
the SAME panes either ``inline`` (a plain HBox, works everywhere) or
into a resizable JupyterLab split panel via ipylab (``lab``; the
``explorer`` extra); ``auto`` picks ``lab`` only when ipylab is
installed and a Lab frontend is detected, else falls back inline.
"""

from __future__ import annotations

import itertools
import json
import os
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Protocol, TypedDict, runtime_checkable

try:
    import anywidget
    import ipywidgets as W
    import traitlets as T
except ImportError as _err:  # pragma: no cover - exercised without anywidget
    from .errors import MissingExtraError

    raise MissingExtraError("longeron.explorer", "anywidget", "replay") from _err

from . import diagrams
from . import model as M
from .interpreter import Interpreter, Resolver
from .toolbar import SEARCH_HIT_COLOR

__all__ = [
    "DIAGRAM_KINDS",
    "Explorer",
    "ModelTree",
    "TreeNode",
    "TreeView",
    "applicable_kinds",
    "explore",
    "requirements_view",
]

#: every diagram kind the switcher can offer, in display order
DIAGRAM_KINDS = ("structure", "state", "action", "requirements")

#: tooltip per diagram kind (rides the switcher buttons)
_KIND_TOOLTIPS = {
    "structure": "Containment, typing and connection structure around the selection",
    "state": "The selection's state machine: states, entry markers, transitions",
    "action": "The selection's succession control-flow graph",
    "requirements": "Requirement definitions/usages and satisfy edges in the owning package",
}

#: synthetic tree-node id prefix for elements without a qualified name
#: (anonymous usages, the model root); never collides with a qualified
#: name because '~' cannot start a SysML identifier
_SYNTH_PREFIX = "~"

#: badge family per usage/definition ``kind``; anything unlisted is
#: ``structure`` (parts, items, occurrences, ...)
_KIND_FAMILIES = {
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

#: kinds whose declaration keyword contains an underscore (display form)
_KIND_DISPLAY = {"use_case": "use case", "enum_literal": "literal", "event_occurrence": "event"}


# ---------------------------------------------------------------------------
# the tree-engine seam: TreeNode + TreeView
# ---------------------------------------------------------------------------


class _TreeNodeBase(TypedDict):
    id: str  # unique node id (a qualified name, or a '~N' synthetic)
    label: str  # display name
    kind: str  # styling family: package/structure/behavior/data/connector/requirement
    badge: str  # type-badge text ('part def', 'state', 'pkg', ...)
    has_children: bool  # lazy-loading hint (True iff 'children' is present)


class TreeNode(_TreeNodeBase, total=False):
    """One tree node, as plain data.

    ``children`` nests the owned members (engines that lazy-load may key
    off ``has_children`` instead of materializing them up front);
    ``suffix`` is an optional dim tail (``: Type`` for typed usages).
    Engines must ignore keys they do not understand.
    """

    children: list[TreeNode]
    suffix: str


@runtime_checkable
class TreeView(Protocol):
    """The seam between the explorer and its tree pane.

    The explorer drives the tree ONLY through this surface, so the
    engine can be swapped -- e.g. for a react-arborist-based widget --
    without touching any explorer logic.  An engine that is also an
    ipywidget joins the explorer's layout; a headless engine (like the
    test suite's stub) simply is not displayed.

    ``selected`` holds the selected node ids (at most one for a
    single-selection engine) and must be plain-assignable; assignment
    from the explorer MAY re-enter :meth:`on_select` callbacks -- the
    explorer is idempotent against that echo.
    """

    selected: list[str]

    def set_nodes(self, nodes: Sequence[TreeNode]) -> None:
        """Replace the tree's contents with ``nodes`` (nested)."""
        ...

    def on_select(self, callback: Callable[[list[str]], None]) -> None:
        """Call ``callback`` with the selected ids on every selection."""
        ...

    def reveal(self, node_id: str) -> None:
        """Expand the node's ancestors and scroll it into view."""
        ...

    def filter(self, text: str) -> int:
        """Live-filter the tree; returns how many nodes match."""
        ...


# ---------------------------------------------------------------------------
# tree data: the model's owning structure as plain dicts
# ---------------------------------------------------------------------------


def _family(element: M.Element) -> str:
    if isinstance(element, (M.Package, M.Model)):
        return "package"
    kind = getattr(element, "kind", "")
    return _KIND_FAMILIES.get(kind, "structure")


def _chip(element: M.Element) -> str:
    """The kind badge text: the declaration keyword, ``def``-suffixed."""

    if isinstance(element, M.Model):
        return "model"
    if isinstance(element, M.Package):
        return "pkg"
    kind = getattr(element, "kind", None) or type(element).__name__.lower()
    text = _KIND_DISPLAY.get(kind, kind)
    if isinstance(element, M.Definition):
        return f"{text} def"
    return text


def _display_name(element: M.Element) -> str:
    if isinstance(element, M.Model):
        return element.source_name or "model"
    if element.name or element.short_name:
        return str(element.name or element.short_name)
    if isinstance(element, M.SatisfyUsage):
        target = element.subsets[0] if element.subsets else (element.references or element.by)
        if target:
            return f"satisfy {target.split('::')[-1]}"
    if isinstance(element, M.Usage) and element.types:
        return f": {element.types[0].split('::')[-1]}"
    return f"anonymous {_chip(element)}"


def _suffix(element: M.Element) -> str:
    """The dim ``: Type`` tail for named, typed usages."""

    if isinstance(element, M.Usage) and element.name and element.types:
        return f" : {', '.join(t.split('::')[-1] for t in element.types)}"
    return ""


def _in_tree(element: M.Element) -> bool:
    return isinstance(element, (M.Package, M.Definition, M.Usage))


def _tree_data(
    model: M.Model,
) -> tuple[list[TreeNode], dict[str, M.Element]]:
    """The nested :class:`TreeNode` dicts plus id -> element.

    Node ids are qualified names where the element has one; anonymous
    elements (and the model root) get unique ``~N`` synthetic ids, which
    still select in the tree but never match a diagram node.
    """

    index: dict[str, M.Element] = {}
    counter = itertools.count()

    def build(element: M.Element) -> TreeNode:
        node_id = element.qualified_name
        if not node_id or node_id in index:
            node_id = f"{_SYNTH_PREFIX}{next(counter)}"
        index[node_id] = element
        node: TreeNode = {
            "id": node_id,
            "label": _display_name(element),
            "kind": _family(element),
            "badge": _chip(element),
            "has_children": False,
        }
        suffix = _suffix(element)
        if suffix:
            node["suffix"] = suffix
        if isinstance(element, M.Namespace):
            children = [build(member) for member in element.members if _in_tree(member)]
            if children:
                node["children"] = children
                node["has_children"] = True
        return node

    return [build(model)], index


# ---------------------------------------------------------------------------
# the tree widget (anywidget: disclosure rows, badges, filter, keyboard)
# ---------------------------------------------------------------------------

_TREE_ESM = """
function render({ model, el }) {
  el.classList.add("lgx-tree-host");

  const bar = document.createElement("div");
  bar.className = "lgx-tree-bar";
  const input = document.createElement("input");
  input.type = "search";
  input.placeholder = "filter\\u2026";
  input.className = "lgx-tree-search";
  input.setAttribute("aria-label", "Filter the model tree");
  const count = document.createElement("span");
  count.className = "lgx-tree-count";
  bar.append(input, count);

  const tree = document.createElement("div");
  tree.className = "lgx-tree";
  tree.setAttribute("role", "tree");
  el.append(bar, tree);

  // ---- index --------------------------------------------------------------
  let roots = [];
  const byId = new Map();
  const parentOf = new Map();
  const expanded = new Set();
  function rebuild() {
    byId.clear();
    parentOf.clear();
    expanded.clear();
    roots = JSON.parse(model.get("nodes_json") || "[]");
    (function index(nodes, parent) {
      for (const n of nodes) {
        n._hay = ((n.label || "") + "\\u0000" + n.id).toLowerCase();
        byId.set(n.id, n);
        parentOf.set(n.id, parent);
        if (n.children) index(n.children, n.id);
      }
    })(roots, null);
    for (const n of roots) expanded.add(n.id); // roots start open
    focusId = null;
    applyFilter(); // re-applies the query (or clears) and renders
  }
  model.on("change:nodes_json", rebuild);

  let filtered = null; // Set of ids visible under an active filter
  let hits = new Set();
  let visibleIds = [];
  let focusId = null;
  const rows = new Map(); // id -> live row element

  function ancestorsOf(id) {
    const out = [];
    let p = parentOf.get(id);
    while (p !== null && p !== undefined) {
      out.push(p);
      p = parentOf.get(p);
    }
    return out;
  }
  function visibleKids(n) {
    const kids = n.children || [];
    return filtered ? kids.filter((k) => filtered.has(k.id)) : kids;
  }

  // ---- rendering (lazy: only expanded rows reach the DOM) ------------------
  function rowFor(n, depth) {
    const row = document.createElement("div");
    row.className = "lgx-row";
    row.setAttribute("role", "treeitem");
    row.setAttribute("aria-level", String(depth + 1));
    row.dataset.id = n.id;
    row.tabIndex = -1;
    row.style.paddingLeft = `${depth * 14 + 6}px`;
    const twist = document.createElement("span");
    twist.className = "lgx-twist";
    const kids = visibleKids(n);
    if (kids.length) {
      row.setAttribute("aria-expanded", expanded.has(n.id) ? "true" : "false");
      twist.textContent = expanded.has(n.id) ? "\\u25be" : "\\u25b8";
      twist.addEventListener("click", (ev) => {
        ev.stopPropagation();
        toggle(n.id);
      });
    }
    const chip = document.createElement("span");
    chip.className = `lgx-chip lgx-chip-${n.kind}`;
    chip.textContent = n.badge;
    const name = document.createElement("span");
    name.className = "lgx-name";
    name.textContent = n.label;
    name.title = n.id;
    if (hits.has(n.id)) row.classList.add("lgx-hit");
    row.append(twist, chip, name);
    if (n.suffix) {
      const suffix = document.createElement("span");
      suffix.className = "lgx-suffix";
      suffix.textContent = n.suffix;
      row.append(suffix);
    }
    row.addEventListener("click", () => {
      focusId = n.id;
      select(n.id);
    });
    row.addEventListener("dblclick", () => toggle(n.id));
    rows.set(n.id, row);
    return row;
  }

  function renderTree() {
    tree.textContent = "";
    rows.clear();
    visibleIds = [];
    const frag = document.createDocumentFragment();
    const emit = (nodes, depth) => {
      for (const n of nodes) {
        if (filtered && !filtered.has(n.id)) continue;
        frag.append(rowFor(n, depth));
        visibleIds.push(n.id);
        if (expanded.has(n.id)) emit(visibleKids(n), depth + 1);
      }
    };
    emit(roots, 0);
    tree.append(frag);
    updateSelection();
  }

  function selectedId() {
    const sel = model.get("selected") || [];
    return sel.length ? sel[0] : "";
  }

  function updateSelection() {
    const id = selectedId();
    let stop = rows.has(id) ? id : visibleIds[0];
    if (focusId && rows.has(focusId)) stop = focusId;
    for (const [rid, row] of rows) {
      row.classList.toggle("lgx-selected", rid === id);
      row.setAttribute("aria-selected", rid === id ? "true" : "false");
      row.tabIndex = rid === stop ? 0 : -1;
    }
  }

  function toggle(id) {
    if (!expanded.delete(id)) expanded.add(id);
    renderTree();
  }

  // ---- selection (two-way; idempotent at every hop) -------------------------
  function select(id) {
    const sel = model.get("selected") || [];
    if (sel.length !== 1 || sel[0] !== id) {
      model.set("selected", [id]);
      model.save_changes();
    } else {
      updateSelection();
    }
  }

  function reveal(id) {
    let changed = false;
    for (const a of ancestorsOf(id)) {
      if (!expanded.has(a)) {
        expanded.add(a);
        changed = true;
      }
    }
    if (filtered && !filtered.has(id)) {
      filtered.add(id); // a python-side reveal outranks the filter
      for (const a of ancestorsOf(id)) filtered.add(a);
      changed = true;
    }
    if (changed) renderTree();
    else updateSelection();
    const row = rows.get(id);
    if (row) row.scrollIntoView({ block: "nearest" });
  }

  model.on("change:selected", () => {
    const id = selectedId();
    if (id && byId.has(id)) reveal(id);
    else updateSelection();
  });

  // an explicit reveal (the TreeView protocol) arrives as a custom message
  model.on("msg:custom", (msg) => {
    if (msg && msg.type === "reveal" && byId.has(msg.id)) reveal(msg.id);
  });

  // ---- filter (live substring over name + qualified name) -------------------
  function applyFilter() {
    const q = (model.get("query") || "").trim().toLowerCase();
    if (!q) {
      filtered = null;
      hits = new Set();
      count.textContent = "";
      count.classList.remove("lgx-zero");
    } else {
      hits = new Set();
      for (const [id, n] of byId) if (n._hay.includes(q)) hits.add(id);
      filtered = new Set(hits);
      for (const id of hits) {
        for (const a of ancestorsOf(id)) {
          filtered.add(a);
          expanded.add(a); // matches auto-reveal
        }
      }
      count.textContent = `${hits.size}/${byId.size}`;
      count.classList.toggle("lgx-zero", hits.size === 0);
    }
    renderTree();
  }
  input.addEventListener("input", () => {
    if (model.get("query") !== input.value) {
      model.set("query", input.value);
      model.save_changes();
    }
  });
  model.on("change:query", () => {
    if (input.value !== model.get("query")) input.value = model.get("query");
    applyFilter();
  });

  // ---- keyboard (roving focus; Enter/Space selects) --------------------------
  function focusRow(id) {
    focusId = id;
    updateSelection();
    const row = rows.get(id);
    if (row) {
      row.focus();
      row.scrollIntoView({ block: "nearest" });
    }
  }
  tree.addEventListener("keydown", (ev) => {
    if (!visibleIds.length) return;
    const current =
      focusId && rows.has(focusId)
        ? focusId
        : rows.has(selectedId())
          ? selectedId()
          : visibleIds[0];
    const idx = Math.max(0, visibleIds.indexOf(current));
    const node = byId.get(current);
    let handled = true;
    if (ev.key === "ArrowDown") {
      focusRow(visibleIds[Math.min(idx + 1, visibleIds.length - 1)]);
    } else if (ev.key === "ArrowUp") {
      focusRow(visibleIds[Math.max(idx - 1, 0)]);
    } else if (ev.key === "Home") {
      focusRow(visibleIds[0]);
    } else if (ev.key === "End") {
      focusRow(visibleIds[visibleIds.length - 1]);
    } else if (ev.key === "ArrowRight") {
      if (node && visibleKids(node).length) {
        if (!expanded.has(current)) {
          expanded.add(current);
          renderTree();
          focusRow(current);
        } else {
          focusRow(visibleKids(node)[0].id);
        }
      }
    } else if (ev.key === "ArrowLeft") {
      if (expanded.has(current) && visibleKids(node).length) {
        expanded.delete(current);
        renderTree();
        focusRow(current);
      } else if (parentOf.get(current)) {
        focusRow(parentOf.get(current));
      }
    } else if (ev.key === "Enter" || ev.key === " ") {
      select(current);
    } else {
      handled = false;
    }
    if (handled) {
      ev.preventDefault();
      ev.stopPropagation();
    }
  });

  rebuild();
  const selected0 = selectedId();
  if (selected0 && byId.has(selected0)) reveal(selected0);
}
export default { render };
"""

# Theming rides the JupyterLab CSS variables (with plain-light fallbacks),
# so the tree follows lab's light/dark themes like the diagram widgets do;
# search hits reuse toolbar.SEARCH_HIT_COLOR -- one search accent everywhere.
_TREE_CSS = """
.lgx-tree-host {
  display: flex; flex-direction: column; height: 100%; min-height: 320px;
  box-sizing: border-box; overflow: hidden;
  font-family: var(--jp-ui-font-family, system-ui, sans-serif);
  color: var(--jp-ui-font-color1, #333333);
  background: var(--jp-layout-color1, #ffffff);
  border: 1px solid var(--jp-border-color2, #e0e0e0); border-radius: 6px;
}
.lgx-tree-bar {
  display: flex; align-items: center; gap: 6px; padding: 6px; flex: none;
  border-bottom: 1px solid var(--jp-border-color2, #e0e0e0);
}
.lgx-tree-search {
  flex: 1; min-width: 0; font-size: 12px; padding: 3px 8px;
  border: 1px solid var(--jp-border-color2, #d4d4d4); border-radius: 4px;
  background: var(--jp-input-background, var(--jp-layout-color0, #ffffff));
  color: inherit; outline: none;
}
.lgx-tree-search:focus { border-color: var(--jp-brand-color1, #1976d2); }
.lgx-tree-count {
  font-size: 11px; color: var(--jp-ui-font-color2, #666666);
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
.lgx-tree-count.lgx-zero { color: var(--jp-warn-color0, #9a6700); }
.lgx-tree { flex: 1; overflow: auto; padding: 4px 0; outline: none; }
.lgx-row {
  display: flex; align-items: center; gap: 6px; cursor: pointer;
  padding: 2px 8px 2px 6px; white-space: nowrap; line-height: 1.5;
  font-size: 13px;
}
.lgx-row:hover { background: var(--jp-layout-color2, #f2f2f2); }
.lgx-row:focus {
  outline: 1px solid var(--jp-brand-color1, #1976d2); outline-offset: -1px;
}
.lgx-row.lgx-selected {
  background: var(--jp-brand-color1, #1976d2);
  color: var(--jp-ui-inverse-font-color1, #ffffff);
}
.lgx-row.lgx-selected .lgx-suffix,
.lgx-row.lgx-selected .lgx-twist { color: inherit; opacity: 0.8; }
.lgx-twist {
  width: 14px; flex: none; text-align: center; user-select: none;
  color: var(--jp-ui-font-color2, #666666); font-size: 11px;
}
.lgx-chip {
  flex: none; font-size: 9.5px; font-weight: 600; letter-spacing: 0.02em;
  padding: 0 5px; border-radius: 8px; line-height: 1.6;
}
.lgx-chip-package   { color: #6d6d6d; background: rgba(128, 128, 128, 0.16); }
.lgx-chip-structure { color: #3d6fb4; background: rgba(61, 111, 180, 0.14); }
.lgx-chip-behavior  { color: #7b4bab; background: rgba(123, 75, 171, 0.14); }
.lgx-chip-data      { color: #3f7a1f; background: rgba(63, 122, 31, 0.14); }
.lgx-chip-connector { color: #b07a26; background: rgba(176, 122, 38, 0.16); }
.lgx-chip-requirement { color: #b0413e; background: rgba(176, 65, 62, 0.14); }
.lgx-row.lgx-selected .lgx-chip {
  color: var(--jp-ui-inverse-font-color1, #ffffff);
  background: rgba(255, 255, 255, 0.22);
}
.lgx-name { overflow: hidden; text-overflow: ellipsis; }
.lgx-row.lgx-hit .lgx-name { color: %HIT%; font-weight: 600; }
.lgx-row.lgx-selected.lgx-hit .lgx-name { color: inherit; }
.lgx-suffix { color: var(--jp-ui-font-color2, #888888); font-size: 11.5px; }
""".replace("%HIT%", SEARCH_HIT_COLOR)


class _SearchEntry:
    """One searchable tree node: pre-lowered name and qualified-name."""

    __slots__ = ("name", "qname")

    def __init__(self, name: str, qname: str) -> None:
        self.name = name
        self.qname = qname


class ModelTree(anywidget.AnyWidget):
    """The built-in :class:`TreeView` engine (a self-contained anywidget).

    Disclosure rows, kind badges, filter, keyboard navigation.  Pure
    presentation over :class:`TreeNode` dicts -- it holds no model
    references, only ids (qualified names).  ``selected`` is the two-way
    selection trait (at most one id); setting it from Python reveals the
    node in the browser (ancestors expand, the row scrolls into view).
    ``query`` live-filters the tree exactly like the diagram toolbar's
    search (case-insensitive substring over label and qualified name);
    ``match_count`` / ``total_count`` mirror its ``matches/total``
    counter and are computed kernel-side too, so headless tests see the
    same numbers the browser shows.
    """

    _esm = _TREE_ESM
    _css = _TREE_CSS

    nodes_json = T.Unicode("[]").tag(sync=True)
    selected = T.List(T.Unicode(), help="selected node ids; [] = no selection").tag(sync=True)
    query = T.Unicode("", help="live filter text; empty shows the whole tree").tag(sync=True)
    match_count = T.Int(0, help="how many nodes match the query").tag(sync=True)
    total_count = T.Int(0, help="how many nodes the tree has").tag(sync=True)

    def __init__(self, nodes: Sequence[TreeNode] = (), **kwargs: Any) -> None:
        # set BEFORE super().__init__: trait kwargs may fire the observers
        self._select_callbacks: list[Callable[[list[str]], None]] = []
        self._entries: tuple[_SearchEntry, ...] = ()
        super().__init__(**kwargs)
        self.set_nodes(nodes)

    # -- the TreeView protocol -------------------------------------------------

    def set_nodes(self, nodes: Sequence[TreeNode]) -> None:
        """Replace the tree's contents (the browser re-indexes and re-renders)."""

        materialized = list(nodes)
        self._entries = tuple(self._flatten(materialized))
        self.nodes_json = json.dumps(materialized)
        self.total_count = len(self._entries)
        self._recount()

    def on_select(self, callback: Callable[[list[str]], None]) -> None:
        """Call ``callback`` with the selected ids on every selection change."""

        self._select_callbacks.append(callback)

    def reveal(self, node_id: str) -> None:
        """Expand the node's ancestors and scroll it into view (browser-side)."""

        self.send({"type": "reveal", "id": node_id})

    def filter(self, text: str) -> int:
        """Live-filter the tree; returns the kernel-side match count."""

        self.query = text
        return self.match_count

    # -- internals ---------------------------------------------------------------

    @staticmethod
    def _flatten(nodes: Sequence[TreeNode]) -> Iterator[_SearchEntry]:
        for node in nodes:
            yield _SearchEntry(str(node.get("label", "")).lower(), str(node["id"]).lower())
            yield from ModelTree._flatten(node.get("children", []))

    @T.observe("selected")
    def _dispatch_select(self, change: Any) -> None:
        ids = list(change["new"])
        for callback in list(getattr(self, "_select_callbacks", ())):
            callback(ids)

    def _recount(self) -> None:
        query = self.query.strip().lower()
        if not query:
            self.match_count = 0
            return
        self.match_count = sum(
            1 for entry in self._entries if query in entry.name or query in entry.qname
        )

    @T.observe("query")
    def _on_query(self, change: Any) -> None:
        self._recount()


# ---------------------------------------------------------------------------
# applicable diagram kinds + the requirements view
# ---------------------------------------------------------------------------


def _nearest_container(element: M.Element) -> M.Element:
    """The nearest ancestor-or-self package (or the model root)."""

    node: M.Element | None = element
    while node is not None:
        if isinstance(node, (M.Package, M.Model)):
            return node
        node = node.owner
    return element


def _has_requirements(scope: M.Element) -> bool:
    return any(
        isinstance(el, M.SatisfyUsage)
        or (isinstance(el, (M.Definition, M.Usage)) and el.kind == "requirement")
        for el in scope.iter_tree()
    )


def applicable_kinds(element: M.Element) -> tuple[str, ...]:
    """Which :data:`DIAGRAM_KINDS` apply to ``element``.

    ``structure`` always applies; ``state`` / ``action`` apply to state
    and action definitions/usages (usages typed by a definition expand
    its submachine, exactly like :func:`~longeron.diagrams.state_diagram`);
    ``requirements`` applies when the nearest owning package (or the
    model root) contains requirement definitions/usages or satisfies.
    """

    kinds = ["structure"]
    kind = getattr(element, "kind", None)
    if kind == "state":
        kinds.append("state")
    if kind == "action":
        kinds.append("action")
    if _has_requirements(_nearest_container(element)):
        kinds.append("requirements")
    return tuple(kinds)


def requirements_view(scope: M.Namespace, *, resolver: Resolver | None = None) -> Any:
    """The requirements landscape of ``scope`` as a structure diagram.

    Collects the requirement definitions and usages under ``scope``, the
    satisfy usages, and each satisfy's satisfying element (its ``by``
    target and satisfied requirements, resolved against the real model),
    then renders them through :func:`~longeron.diagrams.structure_diagram`
    under a synthetic ``requirements`` package.  The collected elements
    are listed in the synthetic package WITHOUT re-parenting (their
    ``owner`` chains -- and therefore their qualified names, the diagram
    node ids -- stay exactly those of the real model), so the view is a
    pure read-only projection: satisfy keyword edges, reference
    subsetting into «requirement» boxes, and typing edges all draw from
    the same public structure view the explorer uses everywhere else.

    Elements whose ancestor is already collected are skipped -- they are
    drawn nested inside that ancestor's box, and a second top-level node
    would duplicate their qualified-name id.
    """

    if resolver is None:
        owner: M.Element = scope
        while owner.owner is not None:
            owner = owner.owner
        resolver = Interpreter(owner if isinstance(owner, M.Model) else M.Model()).resolver

    collected: dict[int, M.Element] = {}

    def include(element: M.Element | None) -> None:
        if element is not None and id(element) not in collected:
            collected[id(element)] = element

    def resolve(name: str, context: M.Element) -> M.Element | None:
        try:
            return resolver.resolve(name, context)
        except Exception:
            return None

    for element in scope.iter_tree():
        if isinstance(element, M.SatisfyUsage):
            include(element)
            if element.by:
                include(resolve(element.by, element))
            satisfied = [*element.subsets, *([element.references] if element.references else [])]
            for name in satisfied:
                include(resolve(name, element))
        elif isinstance(element, (M.Definition, M.Usage)) and element.kind == "requirement":
            include(element)

    def has_collected_ancestor(element: M.Element) -> bool:
        node = element.owner
        while node is not None:
            if id(node) in collected:
                return True
            node = node.owner
        return False

    kept = [el for el in collected.values() if not has_collected_ancestor(el)]
    view = M.Package(name="requirements")
    # deliberately NOT view.add(*kept): add() re-parents, and these are
    # the real model's elements -- the members list alone is enough for
    # the structure builder to draw them (ids stay real qualified names)
    view.members = kept
    root = M.Model(source_name="requirements view")
    root.add(view)
    return diagrams.structure_diagram(root)


# ---------------------------------------------------------------------------
# the explorer widget
# ---------------------------------------------------------------------------

#: the layout strategies :func:`explore` accepts
_LAYOUTS = ("auto", "inline", "lab")


def _lab_frontend_detected() -> bool:
    """Best-effort, synchronous: is a jupyter-server frontend hosting us?

    ``JPY_SESSION_NAME`` is set by jupyter-server when it launches a
    kernel for a browser session (JupyterLab, Notebook 7) and absent
    under headless runners (pytest, nbclient) and self-launched kernels
    (VS Code) -- exactly the split ``layout='auto'`` needs.  A true
    frontend handshake would be asynchronous (the ipylab comm answers
    after the cell returns), so this proxy is deliberate.
    """

    return bool(os.environ.get("JPY_SESSION_NAME"))


def _resolve_layout(choice: str) -> str:
    """Resolve ``auto``/``inline``/``lab`` to a concrete strategy.

    ``lab`` without ipylab raises the house :class:`MissingExtraError`
    (the ``explorer`` extra provides it); ``auto`` falls back to
    ``inline`` silently when ipylab is missing or no Lab frontend is
    detected.
    """

    if choice not in _LAYOUTS:
        options = ", ".join(repr(name) for name in _LAYOUTS)
        raise ValueError(f"layout must be one of {options}; not {choice!r}")
    if choice == "inline":
        return "inline"
    try:
        import ipylab  # noqa: F401
    except ImportError as err:
        if choice == "lab":
            from .errors import MissingExtraError

            raise MissingExtraError("the explorer's 'lab' layout", "ipylab", "explorer") from err
        return "inline"  # auto: silent fallback
    if choice == "lab":
        return "lab"
    return "lab" if _lab_frontend_detected() else "inline"


def _walk_source(node: Any) -> Iterator[Any]:
    yield node
    for child in node.children:
        yield from _walk_source(child)


def _diagram_node_ids(widget: Any) -> frozenset[str]:
    """Every node id in a diagram widget's source tree (qualified names
    plus synthetic transport ids; only qualified names are ever looked
    up, so the synthetics never match)."""

    root = widget.source.value
    if root is None:
        return frozenset()
    return frozenset(str(node.id) for node in _walk_source(root) if node.id)


class Explorer(W.HBox):
    """Tree navigator (left) + applicable-kind diagram pane (right).

    Build one with :func:`explore`.  The public knobs:

    * :attr:`tree` -- the tree engine, any :class:`TreeView` (default
      :class:`ModelTree`; its ``selected`` / ``query`` traits are the
      headless automation surface);
    * :attr:`kind_switcher` -- the toggle buttons offering the applicable
      diagram kinds for the current selection;
    * :attr:`diagram` -- the currently displayed diagram widget;
    * :meth:`select` -- programmatic selection by qualified name or
      element;
    * :attr:`element` / :attr:`kind` -- the current selection and view;
    * :attr:`layout_strategy` -- the resolved layout (``"inline"`` or
      ``"lab"``; see :func:`explore`).

    The panes are built ONCE; the layout strategy only composes them:
    ``inline`` puts them side by side in this HBox (28%/72%), ``lab``
    docks them as a resizable JupyterLab split panel (:attr:`lab_panel`)
    and leaves a small placeholder in the cell output.

    Diagrams are cached per (scope, kind): re-selecting inside the same
    package reuses the SAME widget (the browser keeps its layout), so a
    selection change costs one trait write, not a diagram rebuild.
    """

    def __init__(
        self,
        model: M.Model,
        *,
        tree: TreeView | None = None,
        layout: str = "auto",
        structure_scope: str = "package",
        height: str = "600px",
    ) -> None:
        if structure_scope not in ("package", "element"):
            raise ValueError(
                f"structure_scope must be 'package' or 'element', not {structure_scope!r}"
            )
        self.model = model
        self._structure_scope = structure_scope
        self._resolver = Interpreter(model).resolver

        nodes, index = _tree_data(model)
        self._index = index  # node id -> element
        self._ids = {id(el): nid for nid, el in index.items()}  # element -> node id
        self._root_id = nodes[0]["id"]

        engine: TreeView = tree if tree is not None else ModelTree()
        engine.set_nodes(nodes)
        self.tree = engine
        # a widget engine joins the layout; a headless engine is not displayed
        self._tree_widget: Any = engine if isinstance(engine, W.DOMWidget) else None

        self.kind_switcher = W.ToggleButtons(
            options=("structure",),
            tooltips=(_KIND_TOOLTIPS["structure"],),
            style={"button_width": "auto"},
        )
        self._crumb = W.HTML(layout=W.Layout(margin="0 0 0 auto"))
        header = W.HBox(
            [self.kind_switcher, self._crumb],
            layout=W.Layout(align_items="center", width="100%"),
        )
        self._diagram_box = W.Box(layout=W.Layout(width="100%"))
        # the right pane is built ONCE, strategy-independently; the layout
        # strategy below only composes it (asserted by the test suite)
        self._pane = W.VBox([header, self._diagram_box], layout=W.Layout(flex="1 1 auto"))

        self.lab_panel: Any = None
        self._lab_app: Any = None
        self.layout_strategy = _resolve_layout(layout)
        super().__init__(
            self._compose(height),
            layout=W.Layout(width="100%", align_items="stretch"),
        )

        self._diagrams: dict[tuple[int, str], Any] = {}
        self._diagram_ids: dict[int, frozenset[str]] = {}
        self._req_cache: dict[int, bool] = {}
        self._element: M.Element | None = None
        self._kind: str = "structure"
        self._syncing = False

        engine.on_select(self._on_tree_select)
        self.kind_switcher.observe(self._on_kind, "value")
        self._apply_selection(self._root_id, origin="init")

    # -- layout strategies (panes are shared; only composition differs) -------

    def _compose(self, height: str) -> list[Any]:
        """The HBox children for the resolved strategy."""

        if self.layout_strategy == "lab":
            self._dock_in_lab(height)
            return [
                W.HTML(
                    '<em style="font-size: 12px; color: var(--jp-ui-font-color2, #666);">'
                    "model explorer docked as a JupyterLab panel "
                    "(<code>layout='lab'</code>); this output is a placeholder</em>"
                )
            ]
        if self._tree_widget is not None:
            self._tree_widget.layout = W.Layout(
                width="28%", min_width="220px", height=height, flex="0 0 auto"
            )
            self._pane.layout.width = "72%"
            self._pane.layout.margin = "0 0 0 8px"
            return [self._tree_widget, self._pane]
        self._pane.layout.width = "100%"
        return [self._pane]

    def _dock_in_lab(self, height: str) -> None:
        """Compose the SAME panes into a resizable JupyterLab split panel.

        The split handle is Lab's own (lumino), so the user resizes the
        tree/diagram split through the dock -- no hardcoded percentages.
        """

        import ipylab  # _resolve_layout guarantees it imports

        panel = ipylab.SplitPanel()
        panel.orientation = "horizontal"
        children = []
        if self._tree_widget is not None:
            self._tree_widget.layout = W.Layout(
                width="100%", height="100%", min_width="180px", flex="1 1 auto"
            )
            children.append(self._tree_widget)
        self._pane.layout.width = "100%"
        self._pane.layout.height = "100%"
        children.append(self._pane)
        panel.children = children
        panel.title.label = f"Explorer: {_display_name(self.model)}"
        app = ipylab.JupyterFrontEnd()
        app.shell.add(panel, "main", {"mode": "split-right"})
        self.lab_panel = panel
        self._lab_app = app

    # -- public surface ------------------------------------------------------

    @property
    def element(self) -> M.Element | None:
        """The currently selected model element (None before a selection)."""

        return self._element

    @property
    def kind(self) -> str:
        """The active diagram kind (one of :data:`DIAGRAM_KINDS`)."""

        return self._kind

    @kind.setter
    def kind(self, value: str) -> None:
        if value not in self.kind_switcher.options:
            applicable = ", ".join(self.kind_switcher.options)
            raise ValueError(f"kind must be one of {applicable}; not {value!r}")
        self.kind_switcher.value = value  # the observer renders

    @property
    def diagram(self) -> Any:
        """The diagram widget currently shown in the right pane."""

        children = self._diagram_box.children
        return children[0] if children else None

    def select(self, target: str | M.Element) -> None:
        """Select by tree node id / qualified name, or by element."""

        if isinstance(target, str):
            node_id: str | None = target if target in self._index else None
            if node_id is None:
                node_id = self._ids.get(id(self._resolver.resolve(target)))
        else:
            node_id = self._ids.get(id(target))
        if node_id is None:
            raise KeyError(f"{target!r} is not in this explorer's tree")
        self._apply_selection(node_id, origin="api")

    # -- selection plumbing (idempotent at every hop; see module docstring) ---

    def _kinds_for(self, element: M.Element) -> tuple[str, ...]:
        kinds = ["structure"]
        kind = getattr(element, "kind", None)
        if kind == "state":
            kinds.append("state")
        if kind == "action":
            kinds.append("action")
        scope = _nearest_container(element)
        if id(scope) not in self._req_cache:
            self._req_cache[id(scope)] = _has_requirements(scope)
        if self._req_cache[id(scope)]:
            kinds.append("requirements")
        return tuple(kinds)

    def _on_tree_select(self, ids: list[str]) -> None:
        if self._syncing or not ids:
            return
        self._apply_selection(str(ids[0]), origin="tree")

    def _on_kind(self, change: Any) -> None:
        if self._syncing or change["new"] is None:
            return
        self._kind = str(change["new"])
        if self._element is not None:
            self._show(self._element, self._kind, highlight=True)

    def _from_diagram(self, widget: Any, elements: list[M.Element]) -> None:
        if self._syncing or widget is not self.diagram or not elements:
            return
        node_id = None
        node: M.Element | None = elements[0]
        while node is not None and node_id is None:  # nearest tree-known ancestor
            node_id = self._ids.get(id(node))
            node = node.owner
        if node_id is None or [node_id] == list(self.tree.selected):
            return  # unknown element, or already selected: the echo stops here
        self._apply_selection(node_id, origin="diagram")

    def _apply_selection(self, node_id: str, origin: str) -> None:
        element = self._index.get(node_id)
        if element is None:
            return
        kinds = self._kinds_for(element)
        kind = self._kind if self._kind in kinds else kinds[0]
        self._syncing = True
        try:
            if list(self.tree.selected) != [node_id]:
                self.tree.selected = [node_id]
            if tuple(self.kind_switcher.options) != kinds:
                self.kind_switcher.options = kinds
                self.kind_switcher.tooltips = tuple(_KIND_TOOLTIPS[k] for k in kinds)
            if self.kind_switcher.value != kind:
                self.kind_switcher.value = kind
        finally:
            self._syncing = False
        if origin != "tree":  # the engine expands ancestors + scrolls into view
            self.tree.reveal(node_id)
        self._element = element
        self._kind = kind
        qname = element.qualified_name
        self._crumb.value = (
            '<span style="font-size: 11px; color: var(--jp-ui-font-color2, #666);'
            f' white-space: nowrap;">{qname or _display_name(element)}</span>'
        )
        # a diagram-originated selection is already visible and highlighted
        # in the diagram that was clicked: update tree + switcher only
        self._show(element, kind, highlight=origin != "diagram")

    def _scope(self, element: M.Element, kind: str) -> M.Element:
        if kind in ("state", "action"):
            # the OUTERMOST enclosing machine of the same kind: selecting a
            # nested state (or action step) shows its whole machine with
            # the selection highlighted, not a one-box diagram of the leaf
            scope: M.Element = element
            node = element.owner
            while node is not None:
                if getattr(node, "kind", None) == kind:
                    scope = node
                node = node.owner
            return scope
        if kind == "structure" and self._structure_scope == "element":
            if isinstance(element, M.Namespace):
                return element
        return _nearest_container(element)

    def _show(self, element: M.Element, kind: str, highlight: bool) -> None:
        scope = self._scope(element, kind)
        key = (id(scope), kind)
        widget = self._diagrams.get(key)
        if widget is None:
            widget = self._build(scope, kind)
            widget.layout.width = "100%"
            self._diagrams[key] = widget
            self._diagram_ids[id(widget)] = _diagram_node_ids(widget)

            def deliver(els: list[M.Element], w: Any = widget) -> None:
                self._from_diagram(w, els)

            diagrams.on_select(widget, self.model, deliver)
        if self._diagram_box.children != (widget,):
            self._diagram_box.children = (widget,)
        if not highlight:
            return
        # highlight the element (or its nearest drawn ancestor) through the
        # diagram's own selection tool; write the trait only on change
        drawn = self._diagram_ids[id(widget)]
        target: M.Element | None = element
        while target is not None and (target.qualified_name or "") not in drawn:
            target = target.owner
        want = (target.qualified_name,) if target is not None else ()
        selection = widget.view.selection
        if tuple(selection.ids) != want:
            self._syncing = True
            try:
                selection.ids = want
            finally:
                self._syncing = False

    def _build(self, scope: M.Element, kind: str) -> Any:
        if kind == "state":
            return diagrams.state_diagram(scope)  # type: ignore[arg-type]
        if kind == "action":
            return diagrams.action_diagram(scope)  # type: ignore[arg-type]
        if kind == "requirements":
            return requirements_view(scope, resolver=self._resolver)  # type: ignore[arg-type]
        return diagrams.structure_diagram(scope)  # type: ignore[arg-type]


def explore(model: M.Model, **kwargs: Any) -> Explorer:
    """Explore ``model``: a tree navigator beside a diagram pane.

    Keyword arguments reach :class:`Explorer`:

    * ``layout`` -- ``"auto"`` (the default: dock into JupyterLab when
      ipylab is installed and a Lab frontend is detected, else render
      inline), ``"inline"`` (a plain side-by-side HBox; works everywhere
      -- nbclient, VS Code, docs), or ``"lab"`` (require the ipylab
      docking; raises :class:`~longeron.errors.MissingExtraError` unless
      the ``explorer`` extra is installed);
    * ``tree`` -- a custom :class:`TreeView` engine (default
      :class:`ModelTree`);
    * ``structure_scope`` -- ``"package"`` (the default) scopes the
      structure view to the selection's owning package so relationship
      edges to siblings stay visible; ``"element"`` scopes it to the
      selected namespace itself;
    * ``height`` -- the tree pane's CSS height (default ``"600px"``).
    """

    return Explorer(model, **kwargs)
