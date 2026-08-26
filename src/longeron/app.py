"""The longeron JupyterLab app: a left-sidebar model workbench.

:func:`open` docks a compact panel into JupyterLab's LEFT sidebar (its
tab carries a longeron monogram :class:`ipylab.Icon`) from which models
are loaded and the analysis surfaces are launched as main-area tabs::

    import longeron.app

    app = longeron.app.open()          # docks the sidebar panel

The sidebar has one MODELS section:

* a **path field + Load button** loads a ``.sysml``/``.kerml``/``.json``
  file or a whole directory through :func:`longeron.load` (which
  dispatches to :func:`~longeron.workspace.load_dir` for directories).
  A **Browse** toggle reveals a small server-side directory listing --
  JupyterLab has no OS file dialog, and its ``filebrowser:*`` commands
  navigate the FILE BROWSER (they cannot return a selection to the
  kernel), so the least fragile picker is the kernel's own filesystem:
  selecting a directory descends into it, selecting a file fills the
  path field, and the ``<load this folder>`` row targets the directory
  itself;
* a **Connect to API...** fold drives :class:`longeron.client.Client`
  against any Systems Modeling API server (``longeron serve``, the OMG
  pilot, Flexo per ``docs/design/openmbee-integration.md``): URL +
  optional bearer token, then project and commit pickers feeding
  :meth:`~longeron.client.Client.fetch_model`.  Every network hop is
  guarded -- failures land in the status line, never as tracebacks;
* the **loaded-models list**: one row per model (display name, source
  tooltip) with per-model actions -- **Explore** docks a
  :func:`longeron.explorer.explore` tab; **Score** docks a requirements
  :func:`~longeron.analysis.scoreboard.scoreboard` tab (disabled unless
  the model carries requirement usages); **Save** writes the model back
  to its source file (:func:`longeron.export.save`; disabled for
  directory-merged, in-memory, and API models -- pass an explicit
  ``path`` to :meth:`ModelApp.save_model` for a save-as); API models get
  **Push** instead, which prompts for a commit message and posts through
  :meth:`~longeron.client.Client.push_commit`; the closing ``x`` drops
  the row.

Docking is IDEMPOTENT exactly like the explorer's (one panel, replaced
never stacked), by the same two cooperating mechanisms keyed by the
constant ``longeron-app`` identity: a module-level registry closes the
previous panel in the same kernel, and the panel's sidebar tab carries
``data-lgxkey``/``data-lgxstamp`` (lumino's base TabBar renderer puts
``title.dataset`` on every tab, sidebar tabs included) so a fresh
kernel's :class:`_AppSweeper` can close a DEAD kernel's orphan.  Sidebar
tabs have no close icon, so the sweeper closes orphans through lumino's
OTHER user close path: a synthetic middle-button pointer sequence on the
stale tab (lumino's ``TabBar`` emits ``tabCloseRequested`` for a
middle-click on a closable tab; ipylab connects that signal to
``title.owner.close()`` for left/right-area widgets).  The sweeper also
reveals the panel on open (``activate=True``): JupyterLab's shell does
not activate left-area additions, so the sweeper clicks the app's own
tab -- once, verified against the panel's visibility.

THE INSPECTOR SEAM (the contract a parallel item-inspector attaches to,
without touching this module's internals):

* ``app.current_model`` -- the most recently loaded/selected
  :class:`~longeron.model.Model` (``None`` before the first load), and
  ``app.on_model_selected(cb)`` -- ``cb(model_or_none)`` fires on every
  change (loading, clicking a row name, launching a tab, closing the
  current row passes the new current, or ``None`` when the list
  empties);
* ``app.current_element`` -- the most recently selected
  :class:`~longeron.model.Element` in ANY app-launched tab, and
  ``app.on_element_selected(cb)`` -- ``cb(element)`` fires on every
  change.  App-launched explorer tabs report through the explorer's own
  public tree-selection hook (:meth:`longeron.explorer.TreeView.
  on_select`); scoreboard tabs report through the scoreboard widget's
  ``selected`` trait.  Element selection also updates
  ``current_model`` to the owning model, so an inspector can always
  pair ``(current_model, current_element)``;
* ``app.models`` / ``app.entries`` / ``app.explorers`` enumerate the
  loaded models, their source records, and the launched explorer
  widgets.

Command palette: :func:`open` registers ``longeron:open-app`` (category
*Longeron*) through ipylab's command registry when it can; executing it
reveals the live sidebar panel.  Registration is best-effort chrome: a
stale entry from a dead kernel is replaced (the ipylab frontend disposes
same-id commands on re-add), and any registration failure is swallowed
-- the panel itself never depends on it.  A dead kernel's palette ITEM
can linger until its command is re-registered; ipylab exposes no
palette-item removal.

Headless (``layout='auto'`` outside a Lab frontend, or
``layout='inline'``) the SAME widget renders inline in the cell output
-- which is how the tutorial notebook and nbclient execute it -- and the
launchers build inline explorers/scoreboards instead of docking tabs.
The sidebar CSS rides the sweeper widget, so the inline fallback keeps
default ipywidgets styling; it is a fallback, not the product.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import anywidget
    import ipywidgets as W
    import traitlets as T
except ImportError as _err:  # pragma: no cover - exercised without anywidget
    from .errors import MissingExtraError

    raise MissingExtraError("longeron.app", "anywidget", "replay") from _err

from . import export, workspace
from . import model as M
from .analysis.scoreboard import _root_requirements
from .analysis.scoreboard import scoreboard as _build_scoreboard
from .errors import MissingExtraError, SysMLError
from .explorer import (
    _display_name,
    _dock_key,
    _DockSweeper,
    _lab_frontend_detected,
    explore,
)

if TYPE_CHECKING:
    from .explorer import Explorer

__all__ = ["ModelApp", "open"]

#: the app's constant dock identity: ONE app panel per Lab window
_APP_KEY = "longeron-app"

#: the command palette registration (see the module docstring's caveats)
_COMMAND_ID = "longeron:open-app"

#: file suffixes the browse listing offers (everything longeron loads)
_MODEL_SUFFIXES = (".sysml", ".kerml", ".json")

#: the sidebar panels THIS kernel opened, by dock key (same-kernel
#: replacement; cross-kernel orphans are the sweeper's job)
_OPEN_APPS: dict[str, Any] = {}

#: the main-area panels THIS kernel docked (scoreboard tabs), by dock key
_DOCKED_PANELS: dict[str, Any] = {}

#: palette items are add-only in ipylab; add ours at most once per kernel
_PALETTE_ADDED = False

#: the longeron monogram: two stacked longerons (structural L-beams).
#: ``jp-icon3`` makes the fill follow the Lab theme like the stock icons.
_ICON_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <g class="jp-icon3" fill="#616161">
    <path d="M4 2.5h4.4v13h11.6v5.5H4z"/>
    <path d="M11.4 2.5h8.6v5.4h-4.2v5h-4.4z" fill-opacity="0.45"/>
  </g>
</svg>
"""

#: the layout strategies :func:`open` accepts
_LAYOUTS = ("auto", "inline", "lab")


def _resolve_layout(choice: str) -> str:
    """``auto``/``inline``/``lab`` -> a concrete strategy (explorer's rules).

    ``lab`` without ipylab raises the house :class:`MissingExtraError`
    (the ``explorer`` extra provides it); ``auto`` silently falls back
    inline when ipylab is missing or no Lab frontend is detected.
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
            raise MissingExtraError("the longeron app's sidebar", "ipylab", "explorer") from err
        return "inline"  # auto: silent fallback
    if choice == "lab":
        return "lab"
    return "lab" if _lab_frontend_detected() else "inline"


# ---------------------------------------------------------------------------
# the sidebar sweeper: identity, orphan sweep, reveal (see module docstring)
# ---------------------------------------------------------------------------

# The left-sidebar sibling of the explorer's ``_DockSweeper``, same
# identity idiom (``data-lgxkey``/``data-lgxstamp`` on the tab, stamps
# strictly increase, BigInt because time_ns exceeds 2^53), different
# close path: sidebar tabs render no close icon, so stale tabs are closed
# with a synthetic MIDDLE-button pointer sequence -- lumino's TabBar
# emits ``tabCloseRequested`` for a middle-click on a closable tab
# (verified in the shipped lumino bundle), and ipylab connects that
# signal to ``title.owner.close()`` for left/right-area widgets.  Each
# sweeper also tags its OWN panel node (class + dataset stamp), which is
# both the DOM handle tests use and the success signal a LATER sweeper
# checks after middle-clicking (the panel node detaches synchronously on
# close; the tab's own re-render is deferred a frame).  ``activate``
# reveals the panel on open: the Lab shell does not activate left-area
# additions, so the sweeper clicks the app's own tab, retrying from the
# MutationObserver until the panel measures visible; bumping ``poke``
# re-runs the reveal (the command palette's hook).
_APP_SWEEPER_ESM = """
function render({ model, el }) {
  el.style.display = "none";
  const key = model.get("key");
  const stamp = BigInt(model.get("stamp"));
  let revealed = false;
  let revealAttempts = 0;
  const tabs = () => [
    ...document.querySelectorAll(".jp-SideBar.jp-mod-left .lm-TabBar-tab[data-lgxkey]"),
  ];
  const ownPanel = () =>
    el.closest(".jp-SideAreaWidget") || el.closest("#jp-left-stack > .lm-Widget");
  const tagOwnPanel = () => {
    const panel = ownPanel();
    if (!panel) return;
    panel.classList.add("lgx-app", `lgx-app-${key}`);
    panel.dataset.lgxkey = key;
    panel.dataset.lgxstamp = model.get("stamp");
  };
  const staleTab = () => {
    for (const tab of tabs()) {
      const theirs = tab.dataset.lgxstamp;
      if (tab.dataset.lgxswept) continue; // already closed; render pending
      if (tab.dataset.lgxkey === key && theirs && BigInt(theirs) < stamp) return tab;
    }
    return null;
  };
  const pointer = (target, type, button, rect) => {
    target.dispatchEvent(
      new PointerEvent(type, {
        bubbles: true,
        cancelable: true,
        button,
        clientX: rect.x + rect.width / 2,
        clientY: rect.y + rect.height / 2,
      }),
    );
  };
  const closeTab = (tab) => {
    const rect = tab.getBoundingClientRect();
    if (!rect.width || !rect.height) return false; // hidden bar: no hit test
    // the stale panel node was tagged by ITS OWN sweeper: it detaches
    // synchronously on close, while the tab re-render is deferred
    const panel = [...document.querySelectorAll(`.lgx-app-${key}`)].find(
      (node) => node.dataset.lgxstamp === tab.dataset.lgxstamp,
    );
    pointer(tab, "pointerdown", 1, rect);
    pointer(tab, "pointerup", 1, rect);
    const ok = panel ? !panel.isConnected : !tab.isConnected;
    if (ok) tab.dataset.lgxswept = "1";
    return ok;
  };
  const reveal = () => {
    if (revealed || !model.get("activate") || revealAttempts > 12) return;
    const panel = ownPanel();
    if (panel && panel.getBoundingClientRect().width > 0) {
      revealed = true; // already visible: never click (a click would toggle)
      return;
    }
    const own = tabs().find(
      (tab) => tab.dataset.lgxkey === key && tab.dataset.lgxstamp === model.get("stamp"),
    );
    if (!own) return; // the tab attaches after render; retry on mutation
    const rect = own.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    revealAttempts += 1;
    pointer(own, "pointerdown", 0, rect);
    pointer(own, "pointerup", 0, rect);
    revealed = Boolean(panel && panel.getBoundingClientRect().width > 0);
  };
  const sweep = () => {
    tagOwnPanel();
    reveal();
    let closed = 0;
    for (let round = 0; round < 16; round += 1) {
      const tab = staleTab(); // re-query: closing re-renders the tab bar
      if (!tab || !closeTab(tab)) break;
      closed += 1;
    }
    if (closed) {
      model.set("swept", model.get("swept") + closed);
      model.save_changes();
    }
  };
  model.on("change:poke", () => {
    revealed = false;
    revealAttempts = 0;
    reveal();
  });
  sweep();
  const observer = new MutationObserver(sweep);
  observer.observe(document.body, { childList: true, subtree: true });
  return () => observer.disconnect();
}
export default { render };
"""

# House look on Lab CSS variables (plain-light fallbacks), riding the
# sweeper so it is injected exactly when the panel renders.  Compact:
# the left sidebar is ~280px wide.
_APP_CSS = """
.lgx-app-host {
  height: 100%; overflow-y: auto; padding: 8px 10px; box-sizing: border-box;
  font-family: var(--jp-ui-font-family, system-ui, sans-serif);
  color: var(--jp-ui-font-color1, #333333);
  background: var(--jp-layout-color1, #ffffff);
}
.lgx-app-host .widget-text input,
.lgx-app-host .widget-password input {
  font-size: 12px;
}
.lgx-app-brand {
  font-size: 14px; font-weight: 700; letter-spacing: 0.08em;
  padding: 2px 0 0;
}
.lgx-app-brand small {
  display: block; font-weight: 400; letter-spacing: normal;
  color: var(--jp-ui-font-color2, #666666); font-size: 11px; margin-top: 1px;
}
.lgx-app-section {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--jp-ui-font-color2, #666666);
  margin: 10px 0 2px; border-bottom: 1px solid var(--jp-border-color2, #e0e0e0);
  padding-bottom: 2px;
}
.lgx-app-status { font-size: 11px; line-height: 1.5; min-height: 17px; }
.lgx-app-status .lgx-ok { color: var(--jp-success-color0, #1b7d2c); }
.lgx-app-status .lgx-error { color: var(--jp-error-color0, #b0413e); }
.lgx-app-status .lgx-info { color: var(--jp-ui-font-color2, #666666); }
.lgx-app-crumb {
  font-size: 11px; color: var(--jp-ui-font-color2, #666666);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.lgx-app-row {
  display: flex; flex-direction: column; gap: 1px; width: 100%;
  padding: 3px 0 4px;
  border-bottom: 1px solid var(--jp-border-color2, #eeeeee);
}
.lgx-app-actions { display: flex; align-items: center; gap: 3px; width: 100%; }
.lgx-app-host .lgx-app-actions .jupyter-button {
  height: 22px; line-height: 20px; font-size: 10.5px; padding: 0 6px;
  width: auto;
}
.lgx-app-host .jupyter-button.lgx-app-name {
  width: 100%; min-width: 0; overflow: hidden; text-overflow: ellipsis;
  text-align: left; justify-content: flex-start; height: 22px;
  background: transparent; border: none; box-shadow: none;
  font-size: 12px; font-weight: 500; color: inherit; padding: 0 4px;
}
.lgx-app-host .jupyter-button.lgx-app-name.lgx-app-current {
  border-left: 2px solid var(--jp-brand-color1, #1976d2);
  background: var(--jp-layout-color2, #f2f2f2);
  font-weight: 700;
}
.lgx-app-empty {
  font-size: 11.5px; color: var(--jp-ui-font-color2, #888888);
  font-style: italic; padding: 2px 0;
}
"""


class _AppSweeper(anywidget.AnyWidget):
    """A hidden janitor + concierge inside the sidebar panel.

    Frontend-only, riding inside the app panel (which also makes it the
    carrier of the app CSS).  On render it tags its own panel node with
    the ``lgx-app`` classes and identity dataset, closes any STALE
    sidebar tab with the same ``data-lgxkey`` and an older
    ``data-lgxstamp`` (a dead kernel's orphan, unreachable from Python)
    through lumino's middle-click close path, and -- when
    :attr:`activate` -- reveals the panel by clicking its own tab (the
    Lab shell does not activate left-area additions).  :attr:`swept`
    counts verified orphan closures; bumping :attr:`poke` re-runs the
    reveal (how the ``longeron:open-app`` command surfaces the panel).
    """

    _esm = _APP_SWEEPER_ESM
    _css = _APP_CSS

    key = T.Unicode("", help="the dock key this sweeper guards").tag(sync=True)
    stamp = T.Unicode("", help="this panel's birth stamp (time_ns)").tag(sync=True)
    swept = T.Int(0, help="how many stale panels this sweeper closed").tag(sync=True)
    activate = T.Bool(True, help="reveal the panel once it attaches").tag(sync=True)
    poke = T.Int(0, help="bump to re-reveal the panel (command hook)").tag(sync=True)


# ---------------------------------------------------------------------------
# model records
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ModelEntry:
    """One loaded model and where it came from.

    ``origin`` is ``"file"`` (Save enabled, back to ``path``), ``"dir"``
    (a directory merge; save needs an explicit path), ``"text"`` (an
    in-memory model), or ``"api"`` (Push enabled through ``client``).
    """

    model: M.Model
    source: str
    origin: str
    path: Path | None = None
    client: Any = None
    project: str | None = None
    commit: str | None = None


# ---------------------------------------------------------------------------
# the app widget
# ---------------------------------------------------------------------------


class ModelApp(W.VBox):
    """The sidebar workbench widget.  Build one with :func:`open`.

    The programmatic surface mirrors every UI affordance (the notebook
    and test automation path): :meth:`load_path`, :meth:`add_model`,
    :meth:`connect_api` / :meth:`fetch_api_model`, :meth:`explore_model`,
    :meth:`scoreboard_model`, :meth:`save_model`, :meth:`push_model`,
    :meth:`close_model` -- plus the inspector seam documented in the
    module docstring (:attr:`current_model` / :meth:`on_model_selected`,
    :attr:`current_element` / :meth:`on_element_selected`).
    """

    #: annotation only (no runtime effect): the ipywidgets base class is
    #: import-skipped under mypy, so ``children`` -- read AND reassigned when
    #: the sweeper joins the panel -- needs an explicit type here
    children: Any

    def __init__(self, *, layout: str = "auto", activate: bool = True) -> None:
        self.layout_strategy = _resolve_layout(layout)
        self._activate = bool(activate)
        self._entries: list[ModelEntry] = []
        self._explorers: list[Explorer] = []
        self._current_model: M.Model | None = None
        self._current_element: M.Element | None = None
        self._model_callbacks: list[Callable[[M.Model | None], None]] = []
        self._element_callbacks: list[Callable[[M.Element], None]] = []
        self._api_client: Any = None
        self._push_target: ModelEntry | None = None
        self._browse_dir = Path.cwd()
        self._browse_syncing = False
        self.lab_panel: Any = None
        self._frontend: Any = None
        self._sweeper: Any = None
        self.command_registered = False

        super().__init__(self._build_content(), layout=W.Layout(width="100%"))
        self.add_class("lgx-app-host")

        if self.layout_strategy == "lab":
            self._dock_in_sidebar()

    # -- content ---------------------------------------------------------------

    def _build_content(self) -> list[Any]:
        brand = W.HTML(
            '<div class="lgx-app-brand">LONGERON'
            "<small>SysML v2 models: load, explore, score, save</small></div>"
        )

        self._path_field = W.Text(
            placeholder="path to a .sysml/.json file or a model directory",
            layout=W.Layout(width="100%", flex="1 1 0"),
        )
        self._path_field.add_class("lgx-app-path")
        self._load_button = W.Button(
            description="Load",
            tooltip="Load the file (longeron.load) or directory (load_dir) at this path",
            layout=W.Layout(width="52px", flex="0 0 auto"),
        )
        self._load_button.add_class("lgx-app-load")
        self._load_button.on_click(lambda _b: self._guard("load", self.load_path, None))

        self._browse_toggle = W.ToggleButton(
            value=False,
            description="Browse\u2026",
            tooltip="Browse the server's filesystem (no OS dialogs exist in JupyterLab)",
            layout=W.Layout(width="auto"),
        )
        self._browse_toggle.add_class("lgx-app-browse-toggle")
        self._browse_crumb = W.HTML()
        self._browse_crumb.add_class("lgx-app-crumb")
        self._browse_select = W.Select(
            options=(), rows=8, layout=W.Layout(width="100%"), disabled=False
        )
        self._browse_select.add_class("lgx-app-browser")
        self._browse_select.observe(self._on_browse_pick, "value")
        self._browse_box = W.VBox(
            [self._browse_crumb, self._browse_select],
            layout=W.Layout(width="100%", display="none"),
        )
        self._browse_toggle.observe(self._on_browse_toggle, "value")

        self._status_html = W.HTML()
        self._status_html.add_class("lgx-app-status")

        self._list_box = W.VBox([], layout=W.Layout(width="100%"))
        self._list_box.add_class("lgx-app-list")

        self._push_message = W.Text(
            placeholder="commit message",
            layout=W.Layout(width="100%", flex="1 1 0"),
        )
        self._push_message.add_class("lgx-app-push-message")
        push_confirm = W.Button(
            description="Commit",
            button_style="primary",
            tooltip="Push the model as a commit with this message",
            layout=W.Layout(width="64px", flex="0 0 auto"),
        )
        push_confirm.add_class("lgx-app-push-confirm")
        push_confirm.on_click(lambda _b: self._confirm_push())
        push_cancel = W.Button(description="\u2715", layout=W.Layout(width="28px", flex="0 0 auto"))
        push_cancel.on_click(lambda _b: self._hide_push_bar())
        self._push_bar = W.HBox(
            [self._push_message, push_confirm, push_cancel],
            layout=W.Layout(width="100%", display="none", align_items="center"),
        )
        self._push_bar.add_class("lgx-app-push-bar")

        self._refresh_list()

        return [
            brand,
            W.HTML('<div class="lgx-app-section">Models</div>'),
            W.HBox(
                [self._path_field, self._load_button],
                layout=W.Layout(width="100%", align_items="center"),
            ),
            W.HBox([self._browse_toggle], layout=W.Layout(width="100%")),
            self._browse_box,
            self._build_api_section(),
            self._status_html,
            self._list_box,
            self._push_bar,
        ]

    def _build_api_section(self) -> Any:
        self._api_url = W.Text(
            value="http://localhost:9000",
            placeholder="Systems Modeling API server URL",
            layout=W.Layout(width="100%"),
        )
        self._api_url.add_class("lgx-app-api-url")
        self._api_token = W.Password(
            placeholder="bearer token (optional; Flexo JWT)",
            layout=W.Layout(width="100%"),
        )
        self._api_token.add_class("lgx-app-api-token")
        self._api_connect = W.Button(
            description="Connect",
            tooltip="List the server's projects (longeron.client.Client)",
            layout=W.Layout(width="auto"),
        )
        self._api_connect.add_class("lgx-app-api-connect")
        self._api_connect.on_click(lambda _b: self._guard("connect", self.connect_api))
        self._api_project = W.Dropdown(options=(), disabled=True, layout=W.Layout(width="100%"))
        self._api_project.add_class("lgx-app-api-project")
        self._api_project.observe(self._on_project_change, "value")
        self._api_commit = W.Dropdown(options=(), disabled=True, layout=W.Layout(width="100%"))
        self._api_commit.add_class("lgx-app-api-commit")
        self._api_fetch = W.Button(
            description="Fetch model",
            disabled=True,
            tooltip="Download and rebuild the model at the picked project/commit",
            layout=W.Layout(width="auto"),
        )
        self._api_fetch.add_class("lgx-app-api-fetch")
        self._api_fetch.on_click(lambda _b: self._guard("fetch", self.fetch_api_model))
        box = W.VBox(
            [
                self._api_url,
                self._api_token,
                W.HBox([self._api_connect, self._api_fetch], layout=W.Layout(width="100%")),
                self._api_project,
                self._api_commit,
            ],
            layout=W.Layout(width="100%"),
        )
        accordion = W.Accordion(children=[box], selected_index=None)
        accordion.set_title(0, "Connect to API\u2026")
        accordion.add_class("lgx-app-api")
        accordion.layout = W.Layout(width="100%")
        return accordion

    # -- status + guarding -------------------------------------------------------

    def _status(self, text: str, kind: str = "info") -> None:
        self._status_html.value = f'<span class="lgx-{kind}">{escape(text)}</span>'

    def _guard(self, action: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run a UI action; failures land in the status line, never raise."""

        try:
            return fn(*args, **kwargs)
        except Exception as err:
            self._status(f"{action} failed: {err}", kind="error")
            return None

    # -- the inspector seam (module docstring: THE INSPECTOR SEAM) ---------------

    @property
    def current_model(self) -> M.Model | None:
        """The most recently loaded/selected model (``None`` before any)."""

        return self._current_model

    @property
    def current_element(self) -> M.Element | None:
        """The most recently selected element in any app-launched tab."""

        return self._current_element

    def on_model_selected(self, callback: Callable[[M.Model | None], None]) -> None:
        """Call ``callback(model_or_none)`` on every current-model change."""

        self._model_callbacks.append(callback)

    def on_element_selected(self, callback: Callable[[M.Element], None]) -> None:
        """Call ``callback(element)`` on every current-element change."""

        self._element_callbacks.append(callback)

    def _set_current_model(self, model: M.Model | None) -> None:
        if model is self._current_model:
            return
        self._current_model = model
        for callback in list(self._model_callbacks):
            callback(model)
        self._refresh_list()

    def _set_current_element(self, element: M.Element, model: M.Model | None = None) -> None:
        if model is not None:
            self._set_current_model(model)
        if element is self._current_element:
            return
        self._current_element = element
        for callback in list(self._element_callbacks):
            callback(element)

    # -- the model list -----------------------------------------------------------

    @property
    def entries(self) -> tuple[ModelEntry, ...]:
        """The loaded models' source records, in load order."""

        return tuple(self._entries)

    @property
    def models(self) -> tuple[M.Model, ...]:
        """The loaded models, in load order."""

        return tuple(entry.model for entry in self._entries)

    @property
    def explorers(self) -> tuple[Explorer, ...]:
        """Every explorer this app launched (in launch order)."""

        return tuple(self._explorers)

    def load_path(self, path: str | Path | None = None) -> M.Model:
        """Load the file or directory at ``path`` (default: the path field).

        Files go through :func:`longeron.load` (``.sysml``/``.kerml``
        parse, ``.json`` import); directories merge every ``.sysml``
        under them (:func:`~longeron.workspace.load_dir`).  The loaded
        model joins the list (replacing a previous load of the same
        source) and becomes :attr:`current_model`.
        """

        raw = str(path) if path is not None else self._path_field.value
        raw = raw.strip()
        if not raw:
            raise SysMLError("enter a path to a model file or directory first")
        target = Path(raw).expanduser()
        if not target.exists():
            raise SysMLError(f"no such file or directory: {target}")
        model = workspace.load(target)
        origin = "dir" if target.is_dir() else "file"
        entry = ModelEntry(model=model, source=str(target), origin=origin, path=target)
        self._add_entry(entry)
        self._status(f"loaded {_display_name(model)} from {target}", kind="ok")
        return model

    def add_model(self, model: M.Model, *, source: str | None = None) -> M.Model:
        """Adopt an in-memory model (origin ``"text"``; Save disabled)."""

        entry = ModelEntry(
            model=model,
            source=source or (model.source_name or "<in-memory>"),
            origin="text",
        )
        self._add_entry(entry)
        self._status(f"added {_display_name(model)}", kind="ok")
        return model

    def close_model(self, model: M.Model | ModelEntry) -> None:
        """Drop the model's row (launched tabs stay; they own their views)."""

        entry = self._entry_for(model)
        self._entries.remove(entry)
        if self._current_model is entry.model:
            fallback = self._entries[-1].model if self._entries else None
            self._set_current_model(fallback)
        self._refresh_list()
        self._status(f"closed {_display_name(entry.model)}")

    def _entry_for(self, target: M.Model | ModelEntry) -> ModelEntry:
        if isinstance(target, ModelEntry):
            if target in self._entries:
                return target
            raise KeyError(f"{target!r} is not in this app's model list")
        for entry in self._entries:
            if entry.model is target:
                return entry
        raise KeyError(f"{target!r} is not loaded in this app")

    def _add_entry(self, entry: ModelEntry) -> None:
        self._entries = [e for e in self._entries if e.source != entry.source]
        self._entries.append(entry)
        self._set_current_model(entry.model)
        self._refresh_list()

    def _refresh_list(self) -> None:
        if not self._entries:
            hint = W.HTML('<div class="lgx-app-empty">no models loaded yet</div>')
            self._list_box.children = (hint,)
            return
        self._list_box.children = tuple(self._row(entry) for entry in self._entries)

    def _row(self, entry: ModelEntry) -> Any:
        name = W.Button(
            description=_display_name(entry.model),
            tooltip=f"{entry.origin}: {entry.source}",
            layout=W.Layout(width="100%"),
        )
        name.add_class("lgx-app-name")
        if entry.model is self._current_model:
            name.add_class("lgx-app-current")
        name.on_click(lambda _b, e=entry: self._set_current_model(e.model))

        explore_btn = W.Button(
            description="Explore",
            tooltip="Open a model explorer tab (tree + diagrams)",
        )
        explore_btn.add_class("lgx-app-explore")
        explore_btn.on_click(lambda _b, e=entry: self._guard("explore", self.explore_model, e))

        scoreable = self._scoreboard_applicable(entry.model)
        score_btn = W.Button(
            description="Score",
            disabled=not scoreable,
            tooltip=(
                "Open a requirements scoreboard tab (MAUT treemap)"
                if scoreable
                else "No requirement usages in this model"
            ),
        )
        score_btn.add_class("lgx-app-score")
        score_btn.on_click(lambda _b, e=entry: self._guard("scoreboard", self.scoreboard_model, e))

        if entry.origin == "api":
            save_btn = W.Button(
                description="Push",
                tooltip="Push the model back to the API server as a commit",
            )
            save_btn.add_class("lgx-app-push")
            save_btn.on_click(lambda _b, e=entry: self._show_push_bar(e))
        else:
            can_save = entry.origin == "file"
            save_btn = W.Button(
                description="Save",
                disabled=not can_save,
                tooltip=(
                    f"Write the model back to {entry.source}"
                    if can_save
                    else "No single source file to save back to "
                    "(use app.save_model(model, path=...) for a save-as)"
                ),
            )
            save_btn.add_class("lgx-app-save")
            save_btn.on_click(lambda _b, e=entry: self._guard("save", self.save_model, e.model))

        close_btn = W.Button(
            description="\u2715",
            tooltip="Remove this model from the list",
            layout=W.Layout(width="26px"),
        )
        close_btn.add_class("lgx-app-close")
        close_btn.on_click(lambda _b, e=entry: self._guard("close", self.close_model, e))

        actions = W.HBox(
            [explore_btn, score_btn, save_btn, close_btn],
            layout=W.Layout(width="100%", align_items="center"),
        )
        actions.add_class("lgx-app-actions")
        row = W.VBox([name, actions], layout=W.Layout(width="100%"))
        row.add_class("lgx-app-row")
        return row

    @staticmethod
    def _scoreboard_applicable(model: M.Model) -> bool:
        """Whether the scoreboard can score this model (requirement usages)."""

        try:
            return bool(_root_requirements(model))
        except Exception:
            return False

    # -- launchers ------------------------------------------------------------------

    def explore_model(self, model: M.Model | ModelEntry) -> Explorer:
        """Launch an explorer tab (inline widget headless) for the model.

        The explorer docks through its own idempotent identity (one tab
        per model, replaced on relaunch).  Its tree selection feeds the
        inspector seam: every selection in the tab updates
        :attr:`current_element` (and :attr:`current_model`).
        """

        entry = self._entry_for(model)
        layout = "lab" if self.layout_strategy == "lab" else "inline"
        ex = explore(entry.model, layout=layout)
        self._explorers.append(ex)

        def deliver(ids: list[str], ex: Explorer = ex) -> None:
            if not ids:
                return
            element = ex._index.get(ids[0])
            if element is not None:
                self._set_current_element(element, model=ex.model)

        ex.tree.on_select(deliver)
        # the explorer selected its root during construction -- BEFORE the
        # seam callback above could hear it; seed the seam so launching a
        # tab immediately yields a (current_model, current_element) pair
        if ex.element is not None:
            self._set_current_element(ex.element, model=entry.model)
        self._set_current_model(entry.model)
        self._status(f"explorer opened for {_display_name(entry.model)}", kind="ok")
        return ex

    def scoreboard_model(self, model: M.Model | ModelEntry) -> Any:
        """Launch a requirements scoreboard tab; returns the widget.

        Raises :class:`~longeron.analysis.AnalysisError` when the model
        has no requirement usages (the row button is pre-disabled by the
        same test).  Cell clicks in the tab feed the inspector seam
        through the widget's ``selected`` trait.
        """

        entry = self._entry_for(model)
        board = _build_scoreboard(entry.model)
        widget = board.widget()

        def deliver(change: Any) -> None:
            selected = list(change["new"] or [])
            if not selected:
                return
            node = board._index.get(selected[0])
            element = getattr(node, "element", None)
            if element is not None:
                self._set_current_element(element, model=entry.model)

        widget.observe(deliver, "selected")
        if self.layout_strategy == "lab":
            self._dock_scoreboard(entry, widget)
        self._set_current_model(entry.model)
        self._status(f"scoreboard opened for {_display_name(entry.model)}", kind="ok")
        return widget

    def _dock_scoreboard(self, entry: ModelEntry, widget: Any) -> Any:
        """Dock the scoreboard as a main-area tab, replaced not stacked.

        The explorer's :class:`~longeron.explorer._DockSweeper` rides
        inside (the main-area identity idiom verbatim; the panel node
        picks up its ``lgx-explorer`` tagging, which is cosmetic), keyed
        ``scoreboard-<model slug>`` so scoreboards and explorers of the
        same model coexist.
        """

        import ipylab  # layout_strategy == "lab" guarantees it imports

        key = f"scoreboard-{_dock_key(entry.model)}"
        stamp = str(time.time_ns())
        panel = ipylab.Panel()
        panel.title.label = f"Scoreboard: {_display_name(entry.model)}"
        panel.title.dataset = {"lgxkey": key, "lgxstamp": stamp}
        panel.add_class("lgx-app-scoreboard")
        sweeper = _DockSweeper(key=key, stamp=stamp, layout=W.Layout(display="none"))
        panel.children = (widget, sweeper)
        previous = _DOCKED_PANELS.pop(key, None)
        if previous is not None:
            previous.close()  # same-kernel relaunch: replace, never stack
        frontend = self._frontend if self._frontend is not None else ipylab.JupyterFrontEnd()
        frontend.shell.add(panel, "main", {"mode": "tab-after", "activate": True})
        _DOCKED_PANELS[key] = panel
        return panel

    # -- save / push -------------------------------------------------------------------

    def save_model(self, model: M.Model | ModelEntry, path: str | Path | None = None) -> Path:
        """Write the model back to its source file (or ``path``: save-as).

        Only single-file models save back implicitly; directory-merged,
        in-memory, and API models need an explicit ``path`` (one merged
        file).  API models push instead: :meth:`push_model`.
        """

        entry = self._entry_for(model)
        if path is not None:
            target = Path(path)
        elif entry.origin == "file" and entry.path is not None:
            target = entry.path
        else:
            raise SysMLError(
                f"{_display_name(entry.model)} has no single source file "
                f"(origin {entry.origin!r}); pass an explicit path to save-as"
            )
        export.save(entry.model, target)
        self._status(f"saved {_display_name(entry.model)} to {target}", kind="ok")
        return target

    def push_model(self, model: M.Model | ModelEntry, message: str = "") -> dict[str, Any]:
        """Push an API-loaded model back as a commit (``client.push_commit``)."""

        entry = self._entry_for(model)
        if entry.origin != "api" or entry.client is None or entry.project is None:
            raise SysMLError(
                f"{_display_name(entry.model)} was not loaded from an API server; "
                "use Save (or app.save_model) instead"
            )
        response = entry.client.push_commit(entry.project, entry.model, description=message)
        commit_id = str(response.get("@id", "")) if isinstance(response, dict) else ""
        self._status(f"pushed commit {commit_id[:12] or '(accepted)'}", kind="ok")
        return dict(response) if isinstance(response, dict) else {"response": response}

    def _show_push_bar(self, entry: ModelEntry) -> None:
        self._push_target = entry
        self._push_message.value = ""
        self._push_bar.layout.display = None
        self._status(f"commit message for {_display_name(entry.model)}:")

    def _hide_push_bar(self) -> None:
        self._push_target = None
        self._push_bar.layout.display = "none"

    def _confirm_push(self) -> None:
        entry = self._push_target
        if entry is None:
            return
        result = self._guard("push", self.push_model, entry, self._push_message.value)
        if result is not None:
            self._hide_push_bar()

    # -- the API fold --------------------------------------------------------------------

    def connect_api(
        self, url: str | None = None, token: str | None = None, *, client: Any = None
    ) -> Any:
        """Connect to a Systems Modeling API server and list its projects.

        ``url``/``token`` default to the fold's fields; ``client``
        injects a pre-built :class:`~longeron.client.Client`-compatible
        object (the in-process test idiom).  A bearer ``token`` rides an
        ``Authorization`` header (the Flexo JWT convention).  Returns
        the connected client; the project picker fills on success.
        """

        url = (url if url is not None else self._api_url.value).strip()
        token = token if token is not None else self._api_token.value
        if client is None:
            from .client import Client  # MissingExtraError without the [client] extra

            http = None
            if token:
                try:
                    import httpx
                except ImportError as err:  # pragma: no cover - needs env without httpx
                    raise MissingExtraError("the API connection", "httpx", "client") from err
                http = httpx.Client(
                    base_url=url,
                    timeout=30.0,
                    follow_redirects=True,
                    headers={"Authorization": f"Bearer {token}"},
                )
            client = Client(url, http=http)
        projects = client.list_projects()
        options = []
        for record in projects:
            pid = str(record.get("@id", ""))
            label = str(record.get("name") or pid)
            if pid:
                options.append((label, pid))
        self._api_client = client
        self._api_project.options = tuple(options)
        self._api_project.disabled = not options
        self._api_fetch.disabled = not options
        if options:
            self._api_project.value = options[0][1]
            self._refresh_commits()
        self._status(f"connected to {url}: {len(options)} project(s)", kind="ok")
        return client

    def _on_project_change(self, change: Any) -> None:
        if change["new"] is None or self._api_client is None:
            return
        self._guard("list commits", self._refresh_commits)

    def _refresh_commits(self) -> None:
        project = self._api_project.value
        if project is None or self._api_client is None:
            return
        options: list[tuple[str, str | None]] = [("working tree (head)", None)]
        for record in self._api_client.list_commits(project):
            cid = str(record.get("@id", ""))
            note = str(record.get("description") or "")[:48]
            if cid:
                options.append((f"{cid[:8]} {note}".strip(), cid))
        self._api_commit.options = tuple(options)
        self._api_commit.disabled = False
        self._api_commit.value = None

    def fetch_api_model(self) -> M.Model:
        """Fetch the picked project/commit into the model list."""

        if self._api_client is None:
            raise SysMLError("connect to an API server first")
        project = self._api_project.value
        if project is None:
            raise SysMLError("pick a project first")
        commit = self._api_commit.value
        model = self._api_client.fetch_model(project, commit)
        if not isinstance(model, M.Model):
            raise SysMLError(f"the API client returned {type(model).__name__}, not a Model")
        label = str(self._api_project.label or project)
        api_path = model.source_name or f"projects/{project}"
        # the API path makes an unreadable dock label; the project NAME is
        # the model's human identity (the raw path stays on the tooltip)
        model.source_name = label
        entry = ModelEntry(
            model=model,
            source=f"{self._api_url.value.strip()} :: {api_path}",
            origin="api",
            client=self._api_client,
            project=project,
            commit=commit,
        )
        self._add_entry(entry)
        self._status(f"fetched {label} ({commit or 'working tree'})", kind="ok")
        return model

    # -- the browse fold --------------------------------------------------------------------

    def _on_browse_toggle(self, change: Any) -> None:
        if change["new"]:
            self._browse_box.layout.display = None
            self._refresh_browser()
        else:
            self._browse_box.layout.display = "none"

    def _refresh_browser(self) -> None:
        options: list[tuple[str, str]] = [("<load this folder>", "::dir::")]
        if self._browse_dir.parent != self._browse_dir:
            options.append(("..", "::up::"))
        try:
            children = sorted(
                self._browse_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            )
        except OSError as err:
            self._status(f"cannot list {self._browse_dir}: {err}", kind="error")
            children = []
        for child in children:
            if child.name.startswith("."):
                continue
            if child.is_dir():
                options.append((f"{child.name}/", f"dir:{child.name}"))
            elif child.suffix.lower() in _MODEL_SUFFIXES:
                options.append((child.name, f"file:{child.name}"))
        self._browse_syncing = True
        try:
            self._browse_select.options = tuple(options)
            self._browse_select.value = None
        finally:
            self._browse_syncing = False
        self._browse_crumb.value = escape(str(self._browse_dir))

    def _on_browse_pick(self, change: Any) -> None:
        value = change["new"]
        if value is None or self._browse_syncing:
            return
        if value == "::up::":
            self._browse_dir = self._browse_dir.parent
            self._refresh_browser()
        elif value == "::dir::":
            self._path_field.value = str(self._browse_dir)
        elif value.startswith("dir:"):
            self._browse_dir = self._browse_dir / value[4:]
            self._refresh_browser()
        elif value.startswith("file:"):
            self._path_field.value = str(self._browse_dir / value[5:])

    # -- docking --------------------------------------------------------------------------

    def _dock_in_sidebar(self) -> None:
        """Dock this widget into the LEFT sidebar, replaced never stacked.

        The panel's tab carries the monogram :class:`ipylab.Icon` (the
        ipylab frontend renders ``title.icon`` as a real ``LabIcon``;
        the stable icon name dedupes re-registrations) and the
        ``lgxkey``/``lgxstamp`` identity dataset the sweeper reconciles
        on (module docstring).  ``rank`` places the tab below the stock
        Lab sidebar items.
        """

        import ipylab  # layout_strategy == "lab" guarantees it imports

        stamp = str(time.time_ns())
        panel = ipylab.Panel()
        panel.title.label = "Longeron"
        panel.title.caption = "Longeron: load SysML v2 models, launch explorer and scoreboard tabs"
        try:
            panel.title.icon = ipylab.Icon(name="longeron:app", svgstr=_ICON_SVG)
        except Exception:
            panel.title.icon_class = "lgx-app-tab-icon"
        panel.title.dataset = {"lgxkey": _APP_KEY, "lgxstamp": stamp}
        panel.add_class("lgx-app")
        self._sweeper = _AppSweeper(
            key=_APP_KEY,
            stamp=stamp,
            activate=self._activate,
            layout=W.Layout(display="none"),
        )
        extended: tuple[Any, ...] = (*tuple(self.children), self._sweeper)
        self.children = extended
        panel.children = (self,)
        previous = _OPEN_APPS.pop(_APP_KEY, None)
        if previous is not None:
            previous.close()  # same-kernel re-open: replace, never stack
        frontend = ipylab.JupyterFrontEnd()
        frontend.shell.add(panel, "left", {"rank": 610})
        _OPEN_APPS[_APP_KEY] = panel
        self.lab_panel = panel
        self._frontend = frontend
        self._register_command(frontend)

    def _register_command(self, frontend: Any) -> None:
        """Best-effort ``longeron:open-app`` registration (never fatal).

        The ipylab frontend disposes a same-id command on re-add, so
        replacing a previous kernel's registration is safe; the
        Python-side registry raises on ids it has SEEN synced back, so
        those are removed first.  The palette item is added once per
        kernel (ipylab palette items are add-only).  Any failure leaves
        :attr:`command_registered` False and the app fully functional.
        """

        global _PALETTE_ADDED
        try:
            registry = frontend.commands
            if _COMMAND_ID in registry.list_commands():
                registry.remove_command(_COMMAND_ID)
            registry.add_command(
                _COMMAND_ID,
                self._on_open_command,
                label="Longeron: Open Model App",
                caption="Reveal the longeron model sidebar",
            )
            self.command_registered = True
        except Exception:
            self.command_registered = False
            return
        if _PALETTE_ADDED:
            return
        try:
            from ipylab.commands import CommandPalette

            CommandPalette().add_item(_COMMAND_ID, "Longeron")
            _PALETTE_ADDED = True
        except Exception:
            pass

    def _on_open_command(self, **_args: Any) -> None:
        """The ``longeron:open-app`` body: reveal the live sidebar panel."""

        if self._sweeper is not None:
            self._sweeper.poke = self._sweeper.poke + 1


def open(*, layout: str = "auto", activate: bool = True) -> ModelApp:
    """Open the longeron model app (module docstring for the full tour).

    * ``layout`` -- ``"auto"`` (the default: dock into the JupyterLab
      LEFT sidebar when ipylab is installed and a Lab frontend is
      detected, else render inline), ``"inline"`` (the same widget in
      the cell output; works everywhere), or ``"lab"`` (require the
      sidebar docking; raises :class:`~longeron.errors.MissingExtraError`
      unless the ``explorer`` extra is installed);
    * ``activate`` -- reveal the sidebar panel once it attaches (the
      sweeper clicks the app's own tab; JupyterLab does not activate
      left-area additions itself).

    Re-running ``open()`` -- or restarting the kernel and re-running --
    REPLACES the docked panel instead of stacking a second one; the
    fresh app starts with an empty model list (the returned handle owns
    the models).
    """

    return ModelApp(layout=layout, activate=activate)
