"""The item inspector: a selection-driven property sheet for the app.

:class:`Inspector` is the consumer of the app's documented inspector
seam (:mod:`longeron.app`, "THE INSPECTOR SEAM"): it subscribes to
``app.on_element_selected`` / ``app.on_model_selected`` and renders the
current ``(current_model, current_element)`` pair as a compact property
sheet.  :func:`longeron.app.open` builds one by default and docks it
into JupyterLab's RIGHT sidebar -- the Lab-native home for property
inspectors -- so clicking any element in an app-launched explorer or
scoreboard tab updates the sheet live::

    import longeron.app

    app = longeron.app.open()      # left: the workbench; right: this sheet
    app.inspector                  # the Inspector widget

The sheet, top to bottom:

* a **header**: the element's kind chip (the explorer's badge vocabulary)
  and display name, over a ``::``-path breadcrumb; the header's tooltip
  carries the element's source location when the builder stamped one;
* an **error strip** (hidden until needed): every refused edit lands
  here verbatim -- :class:`~longeron.errors.EditError` messages are the
  edit seam's honest refusals, e.g. a rename listing the exact
  references it cannot safely rewrite -- and the offending field reverts;
* **editable fields**, each committing on Enter/blur through
  :mod:`longeron.edit` (never by direct mutation): *name* ->
  :func:`~longeron.edit.rename` (cascades into every textual reference
  or refuses), *documentation* -> :func:`~longeron.edit.set_doc`
  (namespaces only), and *value* -> :func:`~longeron.edit.
  set_attribute_value` for attribute usages (and any usage already
  carrying a value); the value field is prefilled from the current
  expression via the house renderer (:func:`longeron.ast.expr_to_text`)
  and re-normalized through it after a commit;
* **read-only rows**, styled distinctly and OMITTED when absent (never
  blank): kind, typed by / specializes / subsets / redefines /
  references, multiplicity, direction.  Units are FIRST-CLASS
  (maintainer finding): a value carrying a bracket unit shows compactly
  in the value field (``1.5 kg``, committed back with the reference
  intact), the typed-by row keeps the TYPE but names the unit beside it
  (``Real [kg]`` -- type and unit are different facts, both visible,
  neither masquerading as the other), and a dedicated **unit** row gives
  the symbol + dimension (``kg \u2014 mass``) from the model's derived
  unit table (:func:`longeron.units.unit_table`);
* **relationship rows**: every relationship kind the explorer's tree
  admits (connections, bindings, interfaces, allocations, flows,
  messages, satisfies, verifies, imports, exposes, aliases,
  dependencies, element filters) renders a meaningful sheet -- the
  relationship chip + derived label in the header, its ENDPOINTS as
  CLICKABLE rows that navigate the selection through
  :meth:`longeron.app.ModelApp.select_element` (an app-launched explorer
  of the same model follows: tree reveal + diagram highlight), and the
  full declaration (the exporter's one textual truth) in a read-only
  block.  The name field appears only where the element HAS a name --
  an anonymous ``satisfy`` is a declaration, not a nameable thing.

Edits flow into the app's dirty/save chrome with no wiring here: every
``edit.*`` operation records on the model's :func:`longeron.edit.track`
tracker, whose callback the APP registered when the model was loaded --
the models-list row grows its dirty dot, Save/Push enable, and launched
explorer tabs refresh their trees (:meth:`longeron.explorer.Explorer.
refresh`).  The inspector only re-renders its own sheet (qualified names
move under a rename).

Docking mirrors the app panel's mechanics exactly, on the RIGHT
sidebar: one panel per Lab window keyed ``longeron-inspector``, replaced
never stacked -- a module-level registry closes the previous panel in
the same kernel, and the panel's tab carries ``data-lgxkey`` /
``data-lgxstamp`` so a fresh kernel's sweeper (the app's
:class:`~longeron.app._AppSweeper`, ``side="right"``) closes a dead
kernel's orphan through lumino's middle-click close path.  The tab is
ICON-ONLY like the app's (empty label; the box-and-lens icon plus a
hover caption).  The panel is docked WITHOUT auto-reveal by default:
the right sidebar starts collapsed and expanding it uninvited would
reshape the user's layout -- the tab is one click away.  ONE exception
(maintainer QA: a collapsed inspector failed discoverability): the
first element selection an app-launched tab feeds through the seam
reveals the inspector once per app (:meth:`Inspector.reveal`, called by
:meth:`longeron.app.ModelApp._reveal_inspector_once`;
``open(reveal_inspector=False)`` disables it).  Headless (an
inline-strategy app) the same widget simply renders wherever it is
displayed.
"""

from __future__ import annotations

import re
import time
from html import escape
from typing import Any

try:
    import ipywidgets as W
    import traitlets as T
except ImportError as _err:  # pragma: no cover - exercised without anywidget
    from .errors import MissingExtraError

    raise MissingExtraError("longeron.inspector", "anywidget", "replay") from _err

from . import edit
from . import model as M
from .app import _TAB_ICON_CSS, _AppSweeper
from .ast import QuantityOp, expr_to_text
from .errors import EditError
from .explorer import _chip, _display_name, _family, _import_shape, _is_relationship
from .interpreter import Interpreter
from .units import Dim, UnitTable, unit_table

__all__ = ["Inspector"]

#: the inspector's constant dock identity: ONE inspector panel per Lab window
_INSPECTOR_KEY = "longeron-inspector"

#: the right-sidebar panels THIS kernel opened, by dock key (same-kernel
#: replacement; cross-kernel orphans are the sweeper's job)
_OPEN_INSPECTORS: dict[str, Any] = {}

#: the inspector's sidebar-tab icon: the app icon's sibling variant --
#: one part box under a magnifier lens (inspect the model element).
#: Same rules as the app's: an abstract glyph, never OMG's trademarked
#: 'SysML' wordmark/logo; ``width="16"`` mirrors the builtin icons'
#: intrinsic sizing; ``jp-icon3`` makes the fill follow the Lab theme.
_ICON_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" width="16" viewBox="0 0 24 24">
  <g class="jp-icon3" fill="#616161">
    <rect x="3" y="3" width="10" height="6" rx="1.2"/>
    <path fill-rule="evenodd" d="M13.75 8.5a5.25 5.25 0 1 0 0 10.5a5.25 5.25
      0 1 0 0-10.5zm0 1.9a3.35 3.35 0 1 1 0 6.7a3.35 3.35 0 1 1 0-6.7z"/>
    <path d="M17.61 16.55l4.1 4.1-1.06 1.06-4.1-4.1z"/>
  </g>
</svg>
"""

# House look on Lab CSS variables (plain-light fallbacks); the right
# sidebar is as narrow as the left one, so everything stays compact.
# The chip palette restates the explorer's tree-badge families -- the
# inspector must color chips even when no ModelTree ever rendered.
_INSPECTOR_CSS = (
    _TAB_ICON_CSS
    + """
.lgx-insp-host {
  height: 100%; overflow-y: auto; overflow-x: hidden;
  padding: 8px 10px; box-sizing: border-box;
  font-family: var(--jp-ui-font-family, system-ui, sans-serif);
  color: var(--jp-ui-font-color1, #333333);
  background: var(--jp-layout-color1, #ffffff);
}
.lgx-insp-host .widget-box { min-width: 0; overflow-x: hidden; }
/* the stock 2px side margins on full-width children guarantee horizontal
   overflow (the app panel's rule, same footgun) */
.lgx-insp-host > .jupyter-widgets,
.lgx-insp-host .lgx-insp-body > .jupyter-widgets {
  margin-left: 0; margin-right: 0;
}
.lgx-insp-host input,
.lgx-insp-host select,
.lgx-insp-host textarea { box-sizing: border-box; }
.lgx-insp-host .widget-text,
.lgx-insp-host .widget-textarea { min-width: 0; }
.lgx-insp-title {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--jp-ui-font-color2, #666666);
  margin: 2px 0 6px; border-bottom: 1px solid var(--jp-border-color2, #e0e0e0);
  padding-bottom: 2px;
}
.lgx-insp-head { display: flex; align-items: center; gap: 6px; padding: 2px 0; }
.lgx-insp-chip {
  flex: none; font-size: 9.5px; font-weight: 600; letter-spacing: 0.02em;
  padding: 0 5px; border-radius: 8px; line-height: 1.6;
}
.lgx-insp-chip.lgx-chip-package   { color: #6d6d6d; background: rgba(128, 128, 128, 0.16); }
.lgx-insp-chip.lgx-chip-structure { color: #3d6fb4; background: rgba(61, 111, 180, 0.14); }
.lgx-insp-chip.lgx-chip-behavior  { color: #7b4bab; background: rgba(123, 75, 171, 0.14); }
.lgx-insp-chip.lgx-chip-data      { color: #3f7a1f; background: rgba(63, 122, 31, 0.14); }
.lgx-insp-chip.lgx-chip-connector { color: #b07a26; background: rgba(176, 122, 38, 0.16); }
.lgx-insp-chip.lgx-chip-requirement { color: #b0413e; background: rgba(176, 65, 62, 0.14); }
.lgx-insp-chip.lgx-chip-relationship {
  color: var(--jp-ui-font-color2, #777777); background: transparent;
  border: 1px dashed var(--jp-border-color1, #bdbdbd); line-height: 1.45;
}
.lgx-insp-name-hdr {
  font-size: 13px; font-weight: 700; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;
}
.lgx-insp-crumb {
  font-size: 10.5px; color: var(--jp-ui-font-color2, #888888);
  overflow-wrap: anywhere; line-height: 1.4; padding-bottom: 4px;
  border-bottom: 1px solid var(--jp-border-color2, #eeeeee);
}
.lgx-insp-error {
  font-size: 11px; line-height: 1.45; color: var(--jp-error-color0, #b0413e);
  background: rgba(176, 65, 62, 0.08);
  border-left: 3px solid var(--jp-error-color0, #b0413e);
  padding: 4px 6px; margin: 4px 0; overflow-wrap: anywhere;
}
.lgx-insp-key {
  font-size: 10px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--jp-ui-font-color2, #777777);
  margin: 7px 0 1px;
}
.lgx-insp-row {
  display: flex; align-items: baseline; gap: 6px; padding: 2px 0;
  border-bottom: 1px solid var(--jp-border-color2, #f2f2f2);
}
.lgx-insp-row .lgx-insp-key { margin: 0; flex: 0 0 auto; min-width: 72px; }
.lgx-insp-static {
  font-size: 11.5px; color: var(--jp-ui-font-color2, #666666);
  font-family: var(--jp-code-font-family, monospace);
  overflow-wrap: anywhere;
}
.lgx-insp-host .widget-text input,
.lgx-insp-host .widget-textarea textarea { font-size: 12px; min-width: 0; }
.lgx-insp-host .jupyter-button.lgx-insp-link {
  width: auto; max-width: 100%; height: 20px; line-height: 18px;
  font-size: 11.5px; padding: 0 2px; background: transparent; border: none;
  box-shadow: none; color: var(--jp-brand-color1, #1976d2);
  text-align: left; justify-content: flex-start;
  overflow: hidden; text-overflow: ellipsis;
}
.lgx-insp-host .jupyter-button.lgx-insp-link:hover { text-decoration: underline; }
.lgx-insp-empty {
  font-size: 11.5px; color: var(--jp-ui-font-color2, #888888);
  font-style: italic; padding: 4px 0;
}
.lgx-insp-decl {
  font-size: 11px; line-height: 1.5;
  font-family: var(--jp-code-font-family, monospace);
  color: var(--jp-ui-font-color1, #444444);
  background: var(--jp-layout-color2, #f5f5f5);
  border-left: 3px solid var(--jp-border-color1, #bdbdbd);
  padding: 4px 6px; margin: 2px 0;
  white-space: pre-wrap; overflow-wrap: anywhere;
}
"""
)


class _InspectorSweeper(_AppSweeper):
    """The app sweeper, re-skinned as the inspector's CSS carrier.

    Same identity/orphan/reveal machinery (``side="right"`` points it at
    the right sidebar's tab bar and stack); only the injected stylesheet
    differs -- the inspector styles its own ``lgx-insp-*`` vocabulary.
    """

    _css = _INSPECTOR_CSS

    side = T.Unicode("right").tag(sync=True)


def _mult_text(mult: M.Multiplicity) -> str:
    """The bracket form of a multiplicity (``[0..4] ordered``), or ``""``."""

    lower = expr_to_text(mult.lower) if mult.lower is not None else None
    upper = expr_to_text(mult.upper) if mult.upper is not None else None
    if lower is None and upper is None:
        return ""
    core = upper if lower is None else f"{lower}..{upper if upper is not None else '*'}"
    flags = ("ordered" if mult.is_ordered else "") + (" nonunique" if mult.is_nonunique else "")
    return f"[{core}]{' ' + flags.strip() if flags.strip() else ''}"


def _bracket_unit(element: M.Element) -> str | None:
    """The value's measurement reference text (``SI::kg``) when the
    element's value is a ``magnitude [unit]`` quantity, else ``None``."""

    if isinstance(element, M.Usage) and element.value is not None:
        expr = element.value.expr
        if isinstance(expr, QuantityOp):
            return expr_to_text(expr.unit)
    return None


def _dim_label(table: UnitTable, dim: Dim) -> str:
    """A human dimension name (``mass``) from the table's quantity
    vocabulary (the bare lowercase-first keys are the quantity
    attributes: ``mass``, ``temperatureDifference``); the SI-base
    formula when no quantity names the dimension."""

    for key, quantity_dim in table._quantities.items():
        if "::" not in key and key[:1].islower() and quantity_dim == dim:
            return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key).lower()
    return table.format_dim(dim)


def _declaration_text(element: M.Element) -> str | None:
    """A relationship's full declaration, straight from the exporter (one
    textual truth -- the same source the tree tooltip's first line uses)."""

    from .export import to_sysml

    try:
        return to_sysml(element).strip() or None
    except Exception:  # pragma: no cover - defensive: the block is chrome
        return None


class Inspector(W.VBox):
    """The property sheet widget (module docstring for the full tour).

    Built for one :class:`~longeron.app.ModelApp` (which exposes it as
    ``app.inspector``); attaches to the app's selection seam in the
    constructor and never detaches -- it lives exactly as long as the
    app.  ``layout`` defaults to the app's own resolved strategy;
    ``activate`` reveals the right sidebar on dock (default False: the
    tab is one click away, and auto-expanding a collapsed sidebar
    reshapes the user's layout uninvited).

    The automation surface (tests, notebooks): :attr:`element` is what
    the sheet shows; ``_name_field`` / ``_doc_field`` / ``_value_field``
    commit like the user's Enter/blur when assigned.
    """

    #: annotation only (no runtime effect): the ipywidgets base class is
    #: import-skipped under mypy, so ``children`` -- reassigned when the
    #: sweeper joins the panel -- needs an explicit type here
    children: Any

    def __init__(self, app: Any, *, layout: str | None = None, activate: bool = False) -> None:
        self.app = app
        strategy = layout if layout is not None else getattr(app, "layout_strategy", "inline")
        if strategy not in ("inline", "lab"):
            raise ValueError(f"layout must be 'inline' or 'lab', not {strategy!r}")
        self.layout_strategy = strategy
        self._activate = bool(activate)
        self._element: M.Element | None = None
        self._syncing = False
        self.lab_panel: Any = None
        self._sweeper: Any = None

        super().__init__(self._build_content(), layout=W.Layout(width="100%"))
        self.add_class("lgx-insp-host")

        app.on_element_selected(self.show_element)
        app.on_model_selected(self._on_model_selected)
        if self.layout_strategy == "lab":
            self._dock_in_sidebar()
        if app.current_element is not None:
            self.show_element(app.current_element)

    # -- content ---------------------------------------------------------------

    def _build_content(self) -> list[Any]:
        self._header = W.HTML()
        self._header.add_class("lgx-insp-header")
        self._error = W.HTML(layout=W.Layout(width="100%", display="none"))
        self._error.add_class("lgx-insp-error-box")

        self._name_field = W.Text(
            continuous_update=False,
            placeholder="(anonymous)",
            # 98%, never 100%: full-width inputs + padding/border overflow
            # the flex box into a horizontal scrollbar (the house trick,
            # backed by the box-sizing/min-width CSS) -- sidebar-wide rule
            layout=W.Layout(width="98%"),
        )
        self._name_field.add_class("lgx-insp-name")
        self._name_field.observe(self._on_name_commit, "value")

        self._doc_field = W.Textarea(
            continuous_update=False,
            rows=4,
            placeholder="(no documentation)",
            layout=W.Layout(width="98%"),
        )
        self._doc_field.add_class("lgx-insp-doc")
        self._doc_field.observe(self._on_doc_commit, "value")

        self._value_field = W.Text(
            continuous_update=False,
            placeholder="(no value)",
            layout=W.Layout(width="98%"),
        )
        self._value_field.add_class("lgx-insp-valuefield")
        self._value_field.observe(self._on_value_commit, "value")

        self._body = W.VBox([], layout=W.Layout(width="100%"))
        self._body.add_class("lgx-insp-body")
        self._empty = W.HTML(
            '<div class="lgx-insp-empty">no selection &mdash; click an element '
            "in an explorer or scoreboard tab</div>"
        )
        self._body.children = (self._empty,)

        return [
            W.HTML('<div class="lgx-insp-title">Inspector</div>'),
            self._header,
            self._error,
            self._body,
        ]

    # -- the public surface ------------------------------------------------------

    @property
    def element(self) -> M.Element | None:
        """The element the sheet currently shows (``None`` before any)."""

        return self._element

    def show_element(self, element: M.Element | None) -> None:
        """Render the sheet for ``element`` (the seam callback)."""

        self._element = element
        self._clear_error()
        self._render_sheet()

    def reveal(self) -> None:
        """Expand the right sidebar and select the Inspector tab.

        The sweeper clicks the inspector's own sidebar tab (the same
        gesture a user makes; JupyterLab's ``shell.expand_right`` alone
        would expand whatever tab was last current).  A no-op inline.
        The APP calls this once per session, on the first app-launched
        selection (:meth:`longeron.app.ModelApp._reveal_inspector_once`;
        ``open(reveal_inspector=False)`` disables it) -- every LATER
        selection deliberately leaves the user's layout alone.
        """

        if self._sweeper is None:
            return
        self._sweeper.activate = True
        self._sweeper.poke = self._sweeper.poke + 1

    # -- rendering ---------------------------------------------------------------

    def _render_sheet(self) -> None:
        element = self._element
        if element is None:
            self._header.value = ""
            self._body.children = (self._empty,)
            return
        self._header.value = self._header_html(element)
        rows: list[Any] = []
        # editable name only where the element HAS a name: the root cannot
        # be renamed, and an anonymous relationship (a bare ``satisfy``)
        # is a declaration, not a nameable thing
        if not isinstance(element, M.Model) and (element.name or not _is_relationship(element)):
            self._assign(self._name_field, element.name or "")
            rows += [self._key("name"), self._name_field]
        rows += self._static_rows(element)
        if self._value_editable(element):
            self._assign(self._value_field, self._value_text(element))
            rows += [self._key("value"), self._value_field]
        if isinstance(element, M.Namespace):
            self._assign(self._doc_field, element.doc or "")
            rows += [self._key("documentation"), self._doc_field]
        self._body.children = tuple(rows)

    @staticmethod
    def _header_html(element: M.Element) -> str:
        chip = escape(_chip(element))
        family = _family(element)
        name = escape(_display_name(element))
        qname = element.qualified_name or ""
        location = getattr(element, "source_location", None)
        tooltip = escape(str(location) if location is not None else (qname or name))
        crumb = escape(" \u203a ".join(qname.split("::"))) if qname else ""
        head = (
            f'<div class="lgx-insp-head" title="{tooltip}">'
            f'<span class="lgx-insp-chip lgx-chip-{family}">{chip}</span>'
            f'<span class="lgx-insp-name-hdr">{name}</span></div>'
        )
        return head + (f'<div class="lgx-insp-crumb">{crumb}</div>' if crumb else "")

    @staticmethod
    def _key(text: str) -> Any:
        return W.HTML(f'<div class="lgx-insp-key">{escape(text)}</div>')

    @staticmethod
    def _static_row(key: str, value: str) -> Any:
        return W.HTML(
            f'<div class="lgx-insp-row"><span class="lgx-insp-key">{escape(key)}</span>'
            f'<span class="lgx-insp-static">{escape(value)}</span></div>'
        )

    def _link_row(self, key: str, reference: str, label: str | None = None) -> Any:
        shown = label or reference
        head = W.HTML(f'<span class="lgx-insp-key">{escape(key)}</span>')
        button = W.Button(
            description=shown,
            tooltip=f"Select {reference} (reveals it in the model's explorer tab)",
            layout=W.Layout(width="auto"),
        )
        button.add_class("lgx-insp-link")
        button.on_click(lambda _b, ref=reference: self._navigate(ref))
        row = W.HBox([head, button], layout=W.Layout(width="100%", align_items="center"))
        row.add_class("lgx-insp-endpoint")
        return row

    def _static_rows(self, element: M.Element) -> list[Any]:
        """The read-only property rows; absent facts are OMITTED, not blank."""

        rows: list[Any] = [self._static_row("kind", _chip(element))]
        if isinstance(element, M.Definition) and element.supers:
            rows.append(self._static_row("specializes", ", ".join(element.supers)))
        if isinstance(element, M.Usage):
            # satisfy/verify targets render as ENDPOINT links, not as the
            # generic subsets/references rows
            links_own_targets = isinstance(element, M.SatisfyUsage) or element.kind == "verify"
            unit_label, unit_row = self._unit_facts(element)
            if element.types:
                typed = ", ".join(element.types)
                # the type row IS the typing; the unit rides beside it
                # ('Real [kg]') -- different facts, both visible
                rows.append(
                    self._static_row("typed by", f"{typed} [{unit_label}]" if unit_label else typed)
                )
            if unit_row:
                rows.append(self._static_row("unit", unit_row))
            if element.subsets and not links_own_targets:
                rows.append(self._static_row("subsets", ", ".join(element.subsets)))
            if element.redefines:
                rows.append(self._static_row("redefines", ", ".join(element.redefines)))
            if element.references and not links_own_targets:
                rows.append(self._static_row("references", element.references))
            if element.multiplicity is not None:
                text = _mult_text(element.multiplicity)
                if text:
                    rows.append(self._static_row("multiplicity", text))
            if element.direction:
                rows.append(self._static_row("direction", element.direction))
        if isinstance(element, (M.ConnectionUsage, M.InterfaceUsage, M.AllocationUsage)):
            for end in element.ends:
                if end.target:
                    rows.append(self._link_row("connects", end.target))
        if isinstance(element, M.BindingConnector):
            for bound_end in (element.source_end, element.target_end):
                if bound_end is not None and bound_end.target:
                    rows.append(self._link_row("binds", bound_end.target))
        if isinstance(element, M.SatisfyUsage):
            satisfied = [*element.subsets, *([element.references] if element.references else [])]
            for target in satisfied:
                rows.append(self._link_row("satisfies", target))
            if element.by:
                rows.append(self._link_row("satisfied by", element.by))
        if isinstance(element, M.FlowUsage):
            if element.source:
                rows.append(self._link_row("flow from", element.source))
            if element.target_end:
                rows.append(self._link_row("flow to", element.target_end))
            if element.payload:
                rows.append(self._static_row("payload", element.payload))
        if isinstance(element, M.Usage) and element.kind == "verify":
            targets = element.subsets or ([element.references] if element.references else [])
            for target in targets:
                rows.append(self._link_row("verifies", target))
        if isinstance(element, (M.Import, M.Expose)):
            key = "imports" if isinstance(element, M.Import) else "exposes"
            rows.append(self._link_row(key, element.target, label=_import_shape(element)))
        if isinstance(element, M.Alias):
            rows.append(self._link_row("alias for", element.target))
        if isinstance(element, M.Dependency):
            for client in element.clients:
                rows.append(self._link_row("from", client))
            for supplier in element.suppliers:
                rows.append(self._link_row("to", supplier))
        if isinstance(element, M.ElementFilter):
            rows.append(self._static_row("condition", expr_to_text(element.condition)))
        if _is_relationship(element):
            declaration = _declaration_text(element)
            if declaration:
                block = W.HTML(f'<div class="lgx-insp-decl">{escape(declaration)}</div>')
                rows += [self._key("declaration"), block]
        return rows

    def _unit_facts(self, element: M.Usage) -> tuple[str | None, str | None]:
        """The usage's unit, as ``(value-suffix symbol, unit-row text)``.

        A bracket-united value (``1.5 [SI::kg]``) yields both: the symbol
        the value field appends (``kg``) and the unit row's ``symbol
        \u2014 dimension`` text (``kg \u2014 mass``), resolved against the
        model's derived unit table.  A quantity-typed but unvalued
        attribute yields only the row (its SI-base unit + dimension).
        ``(None, None)`` when the usage carries no unit fact.
        """

        table = unit_table(self._model_of(element))
        reference = _bracket_unit(element)
        if reference is not None:
            info = table.lookup(reference)
            if info is None:
                return None, reference  # honest: the unresolved reference
            return info.label, f"{info.label} \u2014 {_dim_label(table, info.dim)}"
        for name in (*element.types, *element.subsets):
            dim = table.quantity_dimension(name)
            if dim is not None:
                return None, f"{table.format_dim(dim)} \u2014 {_dim_label(table, dim)}"
        return None, None

    def _value_text(self, element: M.Element) -> str:
        """The value field's text: ``1.5 kg`` -- magnitude + unit symbol,
        compactly -- when the value carries a RESOLVABLE bracket unit
        (units are first-class, maintainer finding); the full house
        expression rendering otherwise."""

        if not (isinstance(element, M.Usage) and element.value is not None):
            return ""
        expr = element.value.expr
        if isinstance(expr, QuantityOp):
            label, _ = self._unit_facts(element)
            if label:
                return f"{expr_to_text(expr.base)} {label}"
        return expr_to_text(expr)

    def _compact_to_bracket(self, element: M.Element, text: str) -> str:
        """``0.4 kg`` -> ``0.4 [SI::kg]``: a committed compact value keeps
        the CURRENT measurement reference (the parser's spelling is the
        bracket form); anything else passes through verbatim."""

        reference = _bracket_unit(element)
        if reference is None:
            return text
        label, _ = self._unit_facts(element)  # type: ignore[arg-type]
        if label and text.endswith(f" {label}"):
            return f"{text[: -len(label) - 1].rstrip()} [{reference}]"
        return text

    @staticmethod
    def _value_editable(element: M.Element) -> bool:
        """Attribute usages always; any other usage once it carries a value."""

        return isinstance(element, M.Usage) and (
            element.kind == "attribute" or element.value is not None
        )

    # -- edit commits (Enter/blur; every path goes through longeron.edit) ---------

    def _assign(self, field: Any, value: str) -> None:
        """Set a field WITHOUT firing its commit observer."""

        self._syncing = True
        try:
            field.value = value
        finally:
            self._syncing = False

    def _fail(self, field: Any, revert: str, message: str) -> None:
        """The refused-edit path: revert the field, show the honest refusal."""

        self._assign(field, revert)
        self._error.value = f'<div class="lgx-insp-error">{escape(message)}</div>'
        self._error.layout.display = None

    def _clear_error(self) -> None:
        self._error.value = ""
        self._error.layout.display = "none"

    @staticmethod
    def _model_of(element: M.Element) -> M.Model | None:
        node: M.Element = element
        while node.owner is not None:
            node = node.owner
        return node if isinstance(node, M.Model) else None

    def _on_name_commit(self, change: Any) -> None:
        element = self._element
        if self._syncing or element is None:
            return
        new_name = str(change["new"])
        if new_name == (element.name or ""):
            return  # blur without a change
        model = self._model_of(element)
        if model is None:
            self._fail(self._name_field, element.name or "", "the element is not part of a model")
            return
        try:
            edit.rename(model, element, new_name)
        except EditError as err:
            self._fail(self._name_field, element.name or "", str(err))
            return
        self._clear_error()
        self._render_sheet()  # the breadcrumb (and possibly typings) moved

    def _on_doc_commit(self, change: Any) -> None:
        element = self._element
        if self._syncing or element is None:
            return
        text = str(change["new"])
        if text == ((element.doc or "") if isinstance(element, M.Namespace) else ""):
            return
        model = self._model_of(element)
        if model is None:
            self._fail(self._doc_field, "", "the element is not part of a model")
            return
        current = element.doc or "" if isinstance(element, M.Namespace) else ""
        try:
            edit.set_doc(model, element, text or None)
        except EditError as err:
            self._fail(self._doc_field, current, str(err))
            return
        self._clear_error()

    def _on_value_commit(self, change: Any) -> None:
        element = self._element
        if self._syncing or element is None:
            return
        text = str(change["new"])
        current = self._value_text(element)
        if text == current:
            return
        model = self._model_of(element)
        if model is None:
            self._fail(self._value_field, current, "the element is not part of a model")
            return
        committed = self._compact_to_bracket(element, text)
        try:
            edit.set_attribute_value(model, element, committed or None)  # type: ignore[arg-type]
        except EditError as err:
            self._fail(self._value_field, current, str(err))
            return
        self._clear_error()
        # normalize what the user typed to the sheet's own rendering
        self._assign(self._value_field, self._value_text(element))

    # -- endpoint navigation --------------------------------------------------------

    def _navigate(self, reference: str) -> None:
        """Select the element a relationship endpoint refers to."""

        element = self._element
        if element is None:
            return
        model = self._model_of(element)
        target = self._resolve_reference(model, reference, element) if model else None
        if target is None:
            self._error.value = (
                f'<div class="lgx-insp-error">cannot resolve {escape(reference)!s} '
                "from the selected element</div>"
            )
            self._error.layout.display = None
            return
        self._clear_error()
        self.app.select_element(target)

    @staticmethod
    def _resolve_reference(model: M.Model, text: str, context: M.Element) -> M.Element | None:
        """Resolve a stored reference string exactly like ``validate`` does:
        each ``.``-chain resolves against the previous hop, the first from
        the referring element's owner scope.  A fresh resolver per click:
        resolvers cache resolutions, and edits invalidate those caches."""

        resolver = Interpreter(model).resolver
        node: M.Element | None = None
        for index, chain in enumerate(text.lstrip("~").split(".")):
            scope = (context.owner or model) if index == 0 else node
            try:
                node = resolver.resolve(chain, scope)
            except Exception:
                return None
        return node

    # -- seam bookkeeping -------------------------------------------------------------

    def _on_model_selected(self, model: M.Model | None) -> None:
        """Clear the sheet when the app's model list empties."""

        if model is None:
            self.show_element(None)

    # -- docking ------------------------------------------------------------------------

    def _dock_in_sidebar(self) -> None:
        """Dock into the RIGHT sidebar, replaced never stacked (module docstring).

        Icon-only tab, exactly like the app panel's: empty
        ``title.label`` (builtin sidebar tabs are icon-only because
        JupyterLab renders labels rather than hiding them), identity on
        the hover ``title.caption``, the sibling monogram icon sized by
        the shared ``_TAB_ICON_CSS`` rule.
        """

        import ipylab  # layout_strategy == "lab" guarantees it imports

        stamp = str(time.time_ns())
        panel = ipylab.Panel()
        panel.title.label = ""  # icon-only in the tab strip (maintainer QA)
        panel.title.caption = (
            "Longeron inspector: inspect and edit the selected model element (name, doc, value)"
        )
        try:
            panel.title.icon = ipylab.Icon(name="longeron:inspector", svgstr=_ICON_SVG)
        except Exception:
            # no ipylab.Icon (an older ipylab): a TEXT tab is ugly but
            # discoverable; a blank icon-less tab would be neither
            panel.title.label = "Inspector"
        panel.title.dataset = {"lgxkey": _INSPECTOR_KEY, "lgxstamp": stamp}
        panel.add_class("lgx-inspector")
        self._sweeper = _InspectorSweeper(
            key=_INSPECTOR_KEY,
            stamp=stamp,
            side="right",
            activate=self._activate,
            layout=W.Layout(display="none"),
        )
        extended: tuple[Any, ...] = (*tuple(self.children), self._sweeper)
        self.children = extended
        panel.children = (self,)
        previous = _OPEN_INSPECTORS.pop(_INSPECTOR_KEY, None)
        if previous is not None:
            previous.close()  # same-kernel re-open: replace, never stack
        frontend = ipylab.JupyterFrontEnd()
        frontend.shell.add(panel, "right", {"rank": 610})
        _OPEN_INSPECTORS[_INSPECTOR_KEY] = panel
        self.lab_panel = panel
