"""The JupyterLab model app: sidebar composition, model ops, launch wiring.

Headless throughout, on the fake-ipylab pattern from ``test_explorer.py``:
a stub ipylab module records what would reach the JupyterLab shell, so
docking, identity, command registration, and launch plumbing are all
asserted without a browser (the browser-truth tier is
``tests/browser/test_browser_app.py``).
"""

import sys
import types
from pathlib import Path
from typing import ClassVar

import pytest

pytest.importorskip("ipyelk")
pytest.importorskip("anywidget")

import longeron
from longeron import app as app_module
from longeron import explorer as explorer_module
from longeron.app import ModelEntry
from longeron.errors import MissingExtraError, SysMLError

ROOT = Path(__file__).resolve().parent.parent

REQUIREMENTS_MODEL = """
package Scored {
    part def System { attribute mass : Real = 10.0; }
    part sys : System;
    requirement mission {
        attribute weight : Real = 2.0;
        requirement r1 { attribute measure : Real = sys.mass; }
        requirement r2;
    }
}
"""

PLAIN_MODEL = """
package Plain {
    part def Widget { attribute mass : Real = 1.0; }
    part widget : Widget;
}
"""


@pytest.fixture()
def req_model():
    return longeron.loads(REQUIREMENTS_MODEL, source_name="scored demo")


@pytest.fixture()
def plain_model():
    return longeron.loads(PLAIN_MODEL, source_name="plain demo")


@pytest.fixture(autouse=True)
def _fresh_registries(monkeypatch):
    # module-level on purpose (they must outlive any one app); isolate per test
    monkeypatch.setattr(app_module, "_OPEN_APPS", {})
    monkeypatch.setattr(app_module, "_DOCKED_PANELS", {})
    monkeypatch.setattr(app_module, "_PALETTE_ADDED", False)
    monkeypatch.setattr(explorer_module, "_DOCKED_PANELS", {})


# ---------------------------------------------------------------------------
# the fake ipylab (the test_explorer pattern, grown for the app's needs)
# ---------------------------------------------------------------------------


class _StubShell:
    def __init__(self):
        self.added = []

    def add(self, panel, area, options=None):
        self.added.append((panel, area, options))


class _StubCommands:
    def __init__(self):
        self.registered = {}
        self.removed = []
        self.preexisting = []

    def list_commands(self):
        return [*self.preexisting, *self.registered]

    def add_command(self, command_id, execute, **kwargs):
        if command_id in self.registered:
            raise Exception(f"Command {command_id} is already registered")
        self.registered[command_id] = (execute, kwargs)

    def remove_command(self, command_id):
        self.removed.append(command_id)
        self.registered.pop(command_id, None)
        if command_id in self.preexisting:
            self.preexisting.remove(command_id)


class _StubFrontEnd:
    instances: ClassVar[list] = []

    def __init__(self):
        self.shell = _StubShell()
        self.commands = _StubCommands()
        type(self).instances.append(self)


class _StubTitle:
    def __init__(self):
        self.label = ""
        self.caption = ""
        self.dataset = {}
        self.icon = None
        self.icon_class = ""


class _StubPanel:
    def __init__(self):
        self.children = ()
        self.orientation = ""
        self.title = _StubTitle()
        self.classes = []
        self.closed = False

    def add_class(self, name):
        self.classes.append(name)

    def close(self):
        self.closed = True


class _StubIcon:
    def __init__(self, name="", svgstr=""):
        self.name = name
        self.svgstr = svgstr


class _StubPalette:
    items: ClassVar[list] = []

    def add_item(self, command_id, category, **kwargs):
        type(self).items.append((command_id, category))


def _install_stub_ipylab(monkeypatch):
    module = types.ModuleType("ipylab")
    module.Panel = _StubPanel
    module.SplitPanel = _StubPanel
    module.Icon = _StubIcon
    module.JupyterFrontEnd = _StubFrontEnd
    commands = types.ModuleType("ipylab.commands")
    commands.CommandPalette = _StubPalette
    module.commands = commands
    monkeypatch.setitem(sys.modules, "ipylab", module)
    monkeypatch.setitem(sys.modules, "ipylab.commands", commands)
    monkeypatch.setattr(_StubFrontEnd, "instances", [])
    monkeypatch.setattr(_StubPalette, "items", [])
    return module


def _open_lab(monkeypatch, **kwargs):
    _install_stub_ipylab(monkeypatch)
    return app_module.open(layout="lab", **kwargs)


# ---------------------------------------------------------------------------
# composition + layout resolution
# ---------------------------------------------------------------------------


class TestOpen:
    def test_auto_falls_back_inline_headless(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "ipylab", raising=False)
        monkeypatch.delenv("JPY_SESSION_NAME", raising=False)
        app = app_module.open()
        assert app.layout_strategy == "inline"
        assert app.lab_panel is None and app._sweeper is None

    def test_lab_without_ipylab_raises_the_house_error(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "ipylab", None)
        with pytest.raises(MissingExtraError) as err:
            app_module.open(layout="lab")
        assert 'pip install "longeron[explorer]"' in str(err.value)

    def test_unknown_layout_rejected(self):
        with pytest.raises(ValueError, match="layout must be one of"):
            app_module.open(layout="galaxy")

    def test_auto_uses_lab_when_frontend_detected(self, monkeypatch):
        _install_stub_ipylab(monkeypatch)
        monkeypatch.setenv("JPY_SESSION_NAME", "notebooks/demo.ipynb")
        assert app_module.open().layout_strategy == "lab"

    def test_content_sections_exist(self, monkeypatch):
        app = _open_lab(monkeypatch)
        assert app._path_field.placeholder
        assert app._load_button.description == "Load"
        # NO wordmark row (maintainer QA): the tab icon is the identity,
        # so the panel opens straight onto the Models section header
        first = app.children[0]
        assert "lgx-app-section" in first.value and "Models" in first.value
        assert app._busy_html.layout.display == "none"  # idle: no busy strip
        assert app._browse_box.layout.display == "none"  # folded until toggled
        assert app._browse_load.disabled  # nothing selected yet
        assert app._push_bar.layout.display == "none"
        assert app._api_project.disabled and app._api_fetch.disabled
        # the empty list shows a hint, not zero children
        (hint,) = app._list_box.children
        assert "no models loaded" in hint.value


class TestSidebarDocking:
    def test_docks_left_with_identity_and_icon(self, monkeypatch):
        app = _open_lab(monkeypatch)
        ((panel, area, options),) = app._frontend.shell.added
        assert panel is app.lab_panel and area == "left"
        assert options == {"rank": 610}
        # ICON-ONLY tab (maintainer QA): JupyterLab renders sidebar labels
        # (rotated) rather than hiding them -- builtin sidebar tabs are
        # icon-only because their labels are EMPTY, so ours must be too,
        # with the identity on the hover caption
        assert panel.title.label == ""
        assert panel.title.caption.startswith("Longeron")
        assert panel.title.icon.name == "longeron:app"
        assert "<svg" in panel.title.icon.svgstr
        assert panel.title.dataset["lgxkey"] == "longeron-app"
        assert panel.title.dataset["lgxstamp"].isdigit()
        assert panel.classes == ["lgx-app"]
        assert panel.children == (app,)

    def test_tab_icon_contract(self, monkeypatch):
        # the maintainer's icon spec: builtin intrinsic sizing (width=16
        # on a 24 viewBox), theme-following fill (jp-icon3), and NEVER the
        # trademarked 'SysML' wordmark (OMG registered trademark)
        for svg in (app_module._ICON_SVG,):
            assert 'width="16"' in svg
            assert 'viewBox="0 0 24 24"' in svg
            assert 'class="jp-icon3"' in svg
            assert "SysML" not in svg and "OMG" not in svg
            assert "<text" not in svg  # a glyph, not lettering
        # the sidebar sizing rule rides the app CSS (ipylab assigns the
        # icon after Lab's sideBar-stylesheet pass; the CSS restates it)
        assert ".lm-TabBar-tabIcon svg" in app_module._APP_CSS

    def test_reopen_replaces_the_panel(self, monkeypatch):
        first = _open_lab(monkeypatch)
        second = app_module.open(layout="lab")
        assert first.lab_panel.closed
        assert not second.lab_panel.closed
        assert app_module._OPEN_APPS == {"longeron-app": second.lab_panel}

    def test_stamps_strictly_increase(self, monkeypatch):
        first = _open_lab(monkeypatch)
        second = app_module.open(layout="lab")
        older = int(first.lab_panel.title.dataset["lgxstamp"])
        newer = int(second.lab_panel.title.dataset["lgxstamp"])
        assert older < newer  # the sweeper only ever closes OLDER stamps

    def test_sweeper_rides_hidden_inside_the_app(self, monkeypatch):
        app = _open_lab(monkeypatch)
        sweeper = app._sweeper
        assert sweeper is app.children[-1]  # ships INSIDE the panel content
        assert sweeper.layout.display == "none"
        assert sweeper.key == "longeron-app"
        assert sweeper.stamp == app.lab_panel.title.dataset["lgxstamp"]
        assert sweeper.swept == 0 and sweeper.activate is True

    def test_activate_false_reaches_the_sweeper(self, monkeypatch):
        app = _open_lab(monkeypatch, activate=False)
        assert app._sweeper.activate is False


class TestCommandRegistration:
    def test_command_and_palette_item_registered(self, monkeypatch):
        app = _open_lab(monkeypatch)
        assert app.command_registered
        assert "longeron:open-app" in app._frontend.commands.registered
        assert _StubPalette.items == [("longeron:open-app", "Longeron")]

    def test_stale_registration_is_replaced_not_fatal(self, monkeypatch):
        # a dead kernel's command id can already be in the synced list;
        # the app must remove + re-add instead of crashing on the raise
        _install_stub_ipylab(monkeypatch)

        first = app_module.open(layout="lab")
        registry = first._frontend.commands
        second_registry_seed = ["longeron:open-app"]

        class _SeededFrontEnd(_StubFrontEnd):
            def __init__(self):
                super().__init__()
                self.commands.preexisting = list(second_registry_seed)

        monkeypatch.setattr(sys.modules["ipylab"], "JupyterFrontEnd", _SeededFrontEnd)
        second = app_module.open(layout="lab")
        assert second.command_registered
        assert "longeron:open-app" in second._frontend.commands.removed
        assert registry.registered  # the first app's registry is untouched

    def test_palette_item_added_once_per_kernel(self, monkeypatch):
        _open_lab(monkeypatch)
        app_module.open(layout="lab")
        assert _StubPalette.items == [("longeron:open-app", "Longeron")]

    def test_command_execute_pokes_the_sweeper(self, monkeypatch):
        app = _open_lab(monkeypatch)
        execute, _kwargs = app._frontend.commands.registered["longeron:open-app"]
        before = app._sweeper.poke
        execute()
        assert app._sweeper.poke == before + 1

    def test_registration_failure_is_non_fatal(self, monkeypatch):
        module = _install_stub_ipylab(monkeypatch)

        class _BrokenFrontEnd(_StubFrontEnd):
            def __init__(self):
                super().__init__()
                self.commands = None  # attribute access explodes downstream

        monkeypatch.setattr(module, "JupyterFrontEnd", _BrokenFrontEnd)
        app = app_module.open(layout="lab")
        assert app.lab_panel is not None  # the panel still docked
        assert app.command_registered is False


# ---------------------------------------------------------------------------
# model list operations
# ---------------------------------------------------------------------------


class TestModelOps:
    def test_load_file(self, monkeypatch):
        app = _open_lab(monkeypatch)
        events = []
        app.on_model_selected(events.append)
        model = app.load_path(ROOT / "examples" / "drone.sysml")
        (entry,) = app.entries
        assert entry.model is model and entry.origin == "file"
        assert entry.path == ROOT / "examples" / "drone.sysml"
        assert app.current_model is model
        assert events == [model]
        assert app.models == (model,)

    def test_load_directory(self, monkeypatch, tmp_path):
        (tmp_path / "a.sysml").write_text("package A { part a; }", encoding="utf-8")
        (tmp_path / "b.sysml").write_text("package B { part b; }", encoding="utf-8")
        app = _open_lab(monkeypatch)
        model = app.load_path(tmp_path)
        (entry,) = app.entries
        assert entry.origin == "dir"
        names = {member.name for member in model.members}
        assert {"A", "B"} <= names

    def test_load_path_defaults_to_the_field(self, monkeypatch):
        app = _open_lab(monkeypatch)
        app._path_field.value = str(ROOT / "examples" / "drone.sysml")
        model = app.load_path()
        assert app.current_model is model

    def test_load_errors_are_raised_programmatically(self, monkeypatch):
        app = _open_lab(monkeypatch)
        with pytest.raises(SysMLError, match="no such file or directory"):
            app.load_path("/definitely/not/here.sysml")
        with pytest.raises(SysMLError, match="enter a path"):
            app.load_path("")

    def test_load_button_guards_errors_into_the_status_line(self, monkeypatch):
        app = _open_lab(monkeypatch)
        app._path_field.value = "/definitely/not/here.sysml"
        app._load_button.click()
        assert "load failed" in app._status_html.value
        assert "lgx-error" in app._status_html.value
        assert app.entries == ()

    def test_same_source_reload_replaces_the_entry(self, monkeypatch):
        app = _open_lab(monkeypatch)
        first = app.load_path(ROOT / "examples" / "drone.sysml")
        second = app.load_path(ROOT / "examples" / "drone.sysml")
        (entry,) = app.entries
        assert entry.model is second and first is not second

    def test_add_model_is_text_origin(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        app.add_model(req_model, source="inline text")
        (entry,) = app.entries
        assert entry.origin == "text" and entry.path is None
        assert entry.source == "inline text"

    def test_close_model(self, monkeypatch, req_model, plain_model):
        app = _open_lab(monkeypatch)
        app.add_model(req_model)
        app.add_model(plain_model)
        events = []
        app.on_model_selected(events.append)
        app.close_model(plain_model)  # the current one: falls back
        assert app.models == (req_model,)
        assert app.current_model is req_model
        app.close_model(req_model)
        assert app.models == ()
        assert app.current_model is None
        assert events == [req_model, None]

    def test_unknown_model_rejected(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        with pytest.raises(KeyError):
            app.explore_model(req_model)


# ---------------------------------------------------------------------------
# the per-model rows
# ---------------------------------------------------------------------------


def _row_buttons(app, index=0):
    row = app._list_box.children[index]
    name, actions = row.children  # two lines: the name, then the action strip
    explore_btn, score_btn, save_btn, close_btn = actions.children
    return name, explore_btn, score_btn, save_btn, close_btn


class TestRows:
    def test_row_composition_and_tooltip(self, monkeypatch):
        app = _open_lab(monkeypatch)
        model = app.load_path(ROOT / "examples" / "drone.sysml")
        name, explore_btn, score_btn, save_btn, close_btn = _row_buttons(app)
        assert name.description == "drone.sysml"
        assert str(ROOT / "examples" / "drone.sysml") in name.tooltip
        assert explore_btn.description == "Explore"
        # drone.sysml has a requirement DEF but no usages: not scoreable
        assert score_btn.disabled
        # Save is dirty-gated: a freshly loaded model has nothing to save
        assert save_btn.description == "Save" and save_btn.disabled
        assert "No unsaved edits" in save_btn.tooltip
        assert close_btn.description == "\u2715"
        assert model is app.current_model

    def test_scoreboard_enabled_for_requirement_usages(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        app.add_model(req_model)
        _, _, score_btn, _, _ = _row_buttons(app)
        assert not score_btn.disabled

    def test_scoreboard_disabled_with_honest_tooltip(self, monkeypatch, plain_model):
        # a model without requirement USAGES cannot produce scoreboard
        # rows (scoreboard() raises); the button must be disabled AND say
        # why -- never an enabled button opening an empty tab
        app = _open_lab(monkeypatch)
        app.add_model(plain_model)
        _, _, score_btn, _, _ = _row_buttons(app)
        assert score_btn.disabled
        assert score_btn.tooltip == "No requirement usages in this model"

    def test_save_disabled_for_text_and_dir_models(self, monkeypatch, req_model, tmp_path):
        (tmp_path / "a.sysml").write_text("package A { part a; }", encoding="utf-8")
        app = _open_lab(monkeypatch)
        app.add_model(req_model)
        app.load_path(tmp_path)
        _, _, _, text_save, _ = _row_buttons(app, 0)
        _, _, _, dir_save, _ = _row_buttons(app, 1)
        assert text_save.disabled and dir_save.disabled

    def test_name_click_selects_the_model(self, monkeypatch, req_model, plain_model):
        app = _open_lab(monkeypatch)
        app.add_model(req_model)
        app.add_model(plain_model)
        assert app.current_model is plain_model
        name, *_ = _row_buttons(app, 0)
        name.click()
        assert app.current_model is req_model

    def test_close_button_drops_the_row(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        app.add_model(req_model)
        *_, close_btn = _row_buttons(app)
        close_btn.click()
        assert app.models == ()


# ---------------------------------------------------------------------------
# launch wiring + the inspector seam
# ---------------------------------------------------------------------------


class TestLaunchWiring:
    def test_explore_docks_a_lab_explorer(self, monkeypatch):
        app = _open_lab(monkeypatch)
        model = app.load_path(ROOT / "examples" / "drone.sysml")
        _, explore_btn, *_ = _row_buttons(app)
        explore_btn.click()
        (ex,) = app.explorers
        assert ex.layout_strategy == "lab"
        assert ex.model is model
        # the explorer docked through its own frontend into the main area
        assert explorer_module._DOCKED_PANELS  # its registry, its identity

    def test_explorer_selection_feeds_the_seam(self, monkeypatch):
        app = _open_lab(monkeypatch)
        app.load_path(ROOT / "examples" / "drone.sysml")
        elements = []
        app.on_element_selected(elements.append)
        ex = app.explore_model(app.models[0])
        # launching seeds the seam with the explorer's initial root selection
        assert app.current_element is not None
        assert app.current_element.qualified_name == "Drone"
        ex.select("Drone::QuadCopter")
        assert app.current_element.qualified_name == "Drone::QuadCopter"
        assert [el.qualified_name for el in elements] == ["Drone", "Drone::QuadCopter"]
        assert app.current_model is ex.model

    def test_element_selection_switches_the_current_model(
        self, monkeypatch, req_model, plain_model
    ):
        app = _open_lab(monkeypatch)
        app.add_model(req_model)
        app.add_model(plain_model)
        ex = app.explore_model(req_model)
        assert app.current_model is req_model
        app._set_current_model(plain_model)
        ex.select("Scored::sys")
        assert app.current_model is req_model  # follows the selection's model

    def test_scoreboard_docks_keyed_and_replaces(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        app.add_model(req_model)
        widget = app.scoreboard_model(req_model)
        key = "scoreboard-scored-demo"
        assert key in app_module._DOCKED_PANELS
        panel = app_module._DOCKED_PANELS[key]
        assert panel.title.label == "Scoreboard: scored demo"
        assert panel.title.dataset["lgxkey"] == key
        assert panel.children[0] is widget
        # the explorer's main-area sweeper rides inside (the same idiom)
        sweeper = panel.children[1]
        assert isinstance(sweeper, explorer_module._DockSweeper)
        # docked as a BACKGROUND tab that the sweeper reveals with a real
        # synthetic tab click: docking pre-activated leaves lumino's dock
        # layout without the currentChanged pass that assigns the panel
        # geometry -- a permanently EMPTY tab (maintainer QA)
        assert sweeper.reveal is True
        added = app._frontend.shell.added
        assert added[-1][1] == "main"
        assert added[-1][2] == {"mode": "tab-after", "activate": False}
        app.scoreboard_model(req_model)
        assert panel.closed  # relaunch replaces, never stacks

    def test_scoreboard_selection_feeds_the_seam(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        app.add_model(req_model)
        widget = app.scoreboard_model(req_model)
        widget.selected = ["Scored::mission::r1"]
        assert app.current_element is not None
        assert app.current_element.qualified_name == "Scored::mission::r1"

    def test_scoreboard_on_plain_model_raises(self, monkeypatch, plain_model):
        from longeron.analysis import AnalysisError

        app = _open_lab(monkeypatch)
        app.add_model(plain_model)
        with pytest.raises(AnalysisError, match="no requirement usages"):
            app.scoreboard_model(plain_model)

    def test_inline_app_builds_inline_launchers(self, monkeypatch, req_model):
        monkeypatch.delitem(sys.modules, "ipylab", raising=False)
        monkeypatch.delenv("JPY_SESSION_NAME", raising=False)
        app = app_module.open()
        app.add_model(req_model)
        ex = app.explore_model(req_model)
        assert ex.layout_strategy == "inline"
        widget = app.scoreboard_model(req_model)
        assert not app_module._DOCKED_PANELS  # nothing to dock into
        assert type(widget).__name__ == "ScoreboardWidget"


class TestInspectorReveal:
    """The one-time inspector reveal on the first app-launched selection.

    Maintainer QA: the inspector docks COLLAPSED by design, which failed
    discoverability -- the FIRST element that flows through the seam now
    reveals it once (sweeper: activate + poke); every later selection
    leaves the layout alone, and ``reveal_inspector=False`` disables it.
    """

    def test_first_selection_reveals_once(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        sweeper = app.inspector._sweeper
        assert sweeper.activate is False and sweeper.poke == 0  # docked collapsed
        app.add_model(req_model)
        assert sweeper.poke == 0  # loading alone selects no element
        app.explore_model(req_model)  # seeds the seam with the root selection
        assert sweeper.activate is True and sweeper.poke == 1
        app.explorers[0].select("Scored::sys")  # a later selection
        assert sweeper.poke == 1  # once per app instance, never again

    def test_scoreboard_selection_also_reveals(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        sweeper = app.inspector._sweeper
        app.add_model(req_model)
        widget = app.scoreboard_model(req_model)
        assert sweeper.poke == 0  # launching selects nothing by itself
        widget.selected = ["Scored::mission::r1"]  # a cell click
        assert sweeper.activate is True and sweeper.poke == 1

    def test_reveal_inspector_false_disables_it(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch, reveal_inspector=False)
        sweeper = app.inspector._sweeper
        app.add_model(req_model)
        app.explore_model(req_model)
        assert sweeper.activate is False and sweeper.poke == 0

    def test_without_an_inspector_it_is_a_noop(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch, inspector=False)
        app.add_model(req_model)
        app.explore_model(req_model)  # must not raise
        assert app.current_element is not None

    def test_inline_inspector_needs_no_reveal(self, monkeypatch, req_model):
        monkeypatch.delitem(sys.modules, "ipylab", raising=False)
        monkeypatch.delenv("JPY_SESSION_NAME", raising=False)
        app = app_module.open()
        app.add_model(req_model)
        app.explore_model(req_model)  # must not raise; nothing docked
        assert app.inspector._sweeper is None


# ---------------------------------------------------------------------------
# save + push
# ---------------------------------------------------------------------------


class TestSavePush:
    def test_save_writes_back_to_the_source(self, monkeypatch, tmp_path):
        source = tmp_path / "m.sysml"
        source.write_text("package Mini { part p; }", encoding="utf-8")
        app = _open_lab(monkeypatch)
        model = app.load_path(source)
        model.members[0].name = "Renamed"
        target = app.save_model(model)
        assert target == source
        assert "package Renamed" in source.read_text(encoding="utf-8")

    def test_save_as_with_explicit_path(self, monkeypatch, req_model, tmp_path):
        app = _open_lab(monkeypatch)
        app.add_model(req_model)
        target = app.save_model(req_model, path=tmp_path / "out.sysml")
        assert target.exists()
        assert "requirement" in target.read_text(encoding="utf-8")

    def test_save_without_a_file_source_raises(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        app.add_model(req_model)
        with pytest.raises(SysMLError, match="no single source file"):
            app.save_model(req_model)

    def test_push_requires_an_api_entry(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        app.add_model(req_model)
        with pytest.raises(SysMLError, match="not loaded from an API server"):
            app.push_model(req_model, "message")


# ---------------------------------------------------------------------------
# the API fold (no network: injected fake client)
# ---------------------------------------------------------------------------


class _FakeClient:
    def __init__(self, model):
        self._model = model
        self.pushes = []

    def list_projects(self):
        return [{"@id": "p-1", "name": "Demo Project"}, {"@id": "p-2", "name": "Other"}]

    def list_commits(self, project):
        assert project == "p-1"
        return [{"@id": "c-abcdef123456", "description": "first commit"}]

    def fetch_model(self, project, commit=None):
        self._model.source_name = f"projects/{project}/commits/{commit or 'working'}"
        return self._model

    def push_commit(self, project, changes, *, description=""):
        self.pushes.append((project, changes, description))
        return {"@id": "c-new", "description": description}


class _ExplodingClient:
    def list_projects(self):
        raise OSError("connection refused")


class TestApiFold:
    def test_connect_populates_the_pickers(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        client = _FakeClient(req_model)
        app.connect_api("http://example.test", client=client)
        assert app._api_project.options == (("Demo Project", "p-1"), ("Other", "p-2"))
        assert not app._api_project.disabled and not app._api_fetch.disabled
        # the commit picker filled for the auto-picked first project
        labels = [label for label, _ in app._api_commit.options]
        assert labels[0] == "working tree (head)"
        assert any(label.startswith("c-abcdef") for label in labels)
        assert "connected" in app._status_html.value

    def test_connect_failure_lands_in_the_status_line(self, monkeypatch):
        app = _open_lab(monkeypatch)
        app._api_connect.click()  # default URL, real Client, no server -> guarded
        assert "connect failed" in app._status_html.value
        assert app._api_project.disabled  # nothing populated

        app._guard("connect", app.connect_api, client=_ExplodingClient())
        assert "connect failed" in app._status_html.value

    def test_fetch_makes_an_api_entry_with_push(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        client = _FakeClient(req_model)
        app.connect_api("http://example.test", client=client)
        model = app.fetch_api_model()
        (entry,) = app.entries
        assert entry.origin == "api" and entry.client is client
        assert entry.project == "p-1" and entry.commit is None
        # the model's human identity is the project NAME (dock labels);
        # the API path survives on the entry source (row tooltip)
        assert model.source_name == "Demo Project"
        assert "projects/p-1" in entry.source
        _, _, _, push_btn, _ = _row_buttons(app)
        assert push_btn.description == "Push"

    def test_push_flow_with_commit_message(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        client = _FakeClient(req_model)
        app.connect_api("http://example.test", client=client)
        app.fetch_api_model()
        _, _, _, push_btn, _ = _row_buttons(app)
        push_btn.click()  # reveals the commit-message prompt
        assert app._push_bar.layout.display is None
        app._push_message.value = "tweak the mission weights"
        app._push_bar.children[1].click()  # Commit
        ((project, changes, description),) = client.pushes
        assert project == "p-1" and changes is req_model
        assert description == "tweak the mission weights"
        assert app._push_bar.layout.display == "none"  # closed on success
        assert "pushed commit" in app._status_html.value

    def test_push_cancel_hides_the_bar(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        client = _FakeClient(req_model)
        app.connect_api("http://example.test", client=client)
        app.fetch_api_model()
        _, _, _, push_btn, _ = _row_buttons(app)
        push_btn.click()
        app._push_bar.children[2].click()  # the cancel cross
        assert app._push_bar.layout.display == "none"
        assert client.pushes == []


# ---------------------------------------------------------------------------
# the browse fold (server-side listing; no OS dialogs exist in Lab)
# ---------------------------------------------------------------------------


@pytest.fixture()
def tree(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "a.sysml").write_text("package A {}", encoding="utf-8")
    (tmp_path / "models" / "notes.txt").write_text("not a model", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    return tmp_path


class TestBrowse:
    def test_toggle_reveals_the_listing(self, monkeypatch, tree):
        app = _open_lab(monkeypatch)
        app._browse_dir = tree
        app._browse_toggle.value = True
        assert app._browse_box.layout.display is None
        labels = [label for label, _ in app._browse_select.options]
        assert labels[0] == "<load this folder>"
        assert ".." in labels
        assert "models/" in labels
        assert ".hidden/" not in labels  # dotfiles stay hidden
        assert "notes.txt" not in labels  # only loadable suffixes

    def test_descend_and_pick_a_file(self, monkeypatch, tree):
        app = _open_lab(monkeypatch)
        app._browse_dir = tree
        app._browse_toggle.value = True
        app._browse_select.value = ("dir:models",)
        assert app._browse_dir == tree / "models"
        labels = [label for label, _ in app._browse_select.options]
        assert "a.sysml" in labels
        app._browse_select.value = ("file:a.sysml",)
        assert app._path_field.value == str(tree / "models" / "a.sysml")

    def test_up_and_load_this_folder(self, monkeypatch, tree):
        app = _open_lab(monkeypatch)
        app._browse_dir = tree / "models"
        app._browse_toggle.value = True
        app._browse_select.value = ("::up::",)
        assert app._browse_dir == tree
        app._browse_select.value = ("::dir::",)
        assert app._path_field.value == str(tree)

    def test_crumb_carries_the_full_path_tooltip(self, monkeypatch, tree):
        app = _open_lab(monkeypatch)
        app._browse_dir = tree
        app._browse_toggle.value = True
        # long paths ellipsize (CSS); the tooltip carries the full path
        assert f'title="{tree}"' in app._browse_crumb.value

    def test_multi_select_enables_load_selected(self, monkeypatch, tree):
        (tree / "models" / "b.sysml").write_text("package B { part b; }", encoding="utf-8")
        app = _open_lab(monkeypatch)
        app._browse_dir = tree / "models"
        app._browse_toggle.value = True
        assert app._browse_load.disabled  # nothing picked yet
        app._browse_select.value = ("file:a.sysml",)
        assert not app._browse_load.disabled
        # the SINGLE pick still fills the path field (the simple case)
        assert app._path_field.value == str(tree / "models" / "a.sysml")
        app._path_field.value = "untouched"
        app._browse_select.value = ("file:a.sysml", "file:b.sysml")
        assert not app._browse_load.disabled
        # a MULTI pick belongs to 'Load selected': the path field is left alone
        assert app._path_field.value == "untouched"

    def test_load_selected_loads_each_file(self, monkeypatch, tree):
        (tree / "models" / "b.sysml").write_text("package B { part b; }", encoding="utf-8")
        app = _open_lab(monkeypatch)
        app._browse_dir = tree / "models"
        app._browse_toggle.value = True
        app._browse_select.value = ("file:a.sysml", "file:b.sysml")
        app._browse_load.click()
        assert [entry.origin for entry in app.entries] == ["file", "file"]
        sources = {Path(entry.source).name for entry in app.entries}
        assert sources == {"a.sysml", "b.sysml"}
        assert "loaded 2 models" in app._status_html.value

    def test_load_selected_ignores_directory_rows(self, monkeypatch, tree):
        app = _open_lab(monkeypatch)
        app._browse_dir = tree
        app._browse_toggle.value = True
        # only non-file rows picked: the action stays disabled and the
        # programmatic surface refuses honestly
        app._browse_select.value = ("::dir::",)
        assert app._browse_load.disabled
        with pytest.raises(SysMLError, match="select one or more model files"):
            app.load_selected()


# ---------------------------------------------------------------------------
# the busy strip (loads take seconds; silence reads as a dead click)
# ---------------------------------------------------------------------------


class TestBusyIndicator:
    def test_busy_strip_shows_during_a_load(self, monkeypatch, tmp_path):
        source = tmp_path / "m.sysml"
        source.write_text("package Mini { part p; }", encoding="utf-8")
        app = _open_lab(monkeypatch)
        observed = {}
        real = app_module.workspace.load

        def spy(target):
            # capture the UI state WHILE the (synchronous) load runs:
            # trait writes reach the browser immediately, so this is
            # exactly what the user sees during a slow load
            observed["display"] = app._busy_html.layout.display
            observed["text"] = app._busy_html.value
            observed["load_disabled"] = app._load_button.disabled
            observed["browse_load_disabled"] = app._browse_load.disabled
            return real(target)

        monkeypatch.setattr(app_module.workspace, "load", spy)
        app.load_path(source)
        assert observed["display"] is None  # the strip was visible mid-load
        assert "loading m.sysml" in observed["text"]
        assert "lgx-app-busy-bar" in observed["text"]  # the animated bar
        assert observed["load_disabled"] and observed["browse_load_disabled"]
        # and everything resets once the load lands
        assert app._busy_html.layout.display == "none"
        assert app._busy_html.value == ""
        assert not app._load_button.disabled

    def test_busy_strip_clears_when_the_load_fails(self, monkeypatch, tmp_path):
        bad = tmp_path / "broken.sysml"
        bad.write_text("part {", encoding="utf-8")  # unparseable
        app = _open_lab(monkeypatch)
        with pytest.raises(SysMLError):
            app.load_path(bad)
        assert app._busy_html.layout.display == "none"
        assert not app._load_button.disabled

    def test_load_selected_wraps_the_batch_in_one_strip(self, monkeypatch, tree):
        (tree / "models" / "b.sysml").write_text("package B { part b; }", encoding="utf-8")
        app = _open_lab(monkeypatch)
        app._browse_dir = tree / "models"
        app._browse_toggle.value = True
        app._browse_select.value = ("file:a.sysml", "file:b.sysml")
        depths = []
        real = app_module.workspace.load

        def spy(target):
            depths.append(app._busy_depth)  # outer batch strip + inner load
            return real(target)

        monkeypatch.setattr(app_module.workspace, "load", spy)
        app.load_selected()
        assert depths == [2, 2]  # nested: the strip never flickered off
        assert app._busy_depth == 0
        assert app._busy_html.layout.display == "none"


# ---------------------------------------------------------------------------
# entries are honest records
# ---------------------------------------------------------------------------


class TestEntries:
    def test_entry_shape(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        app.add_model(req_model, source="inline text")
        (entry,) = app.entries
        assert isinstance(entry, ModelEntry)
        assert entry.model is req_model
        assert (entry.source, entry.origin, entry.path) == ("inline text", "text", None)

    def test_entries_are_copies_of_the_list(self, monkeypatch, req_model):
        app = _open_lab(monkeypatch)
        app.add_model(req_model)
        entries = app.entries
        assert isinstance(entries, tuple)
        app.close_model(req_model)
        assert entries  # the snapshot survives the mutation
