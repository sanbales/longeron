"""The item inspector: selection-driven sheet, edit commits, dirty chrome.

Headless throughout, on the fake-ipylab pattern from ``test_app.py``: a
stub ipylab module records what would reach the JupyterLab shell, so the
right-sidebar docking, the selection -> sheet mapping, the edit-commit
paths (``longeron.edit`` with honest refusals), and the app's
dirty/save/push integration are all asserted without a browser (the
browser-truth tier is ``tests/browser/test_browser_app.py``).
"""

import sys
import types
from pathlib import Path
from typing import ClassVar

import pytest

pytest.importorskip("ipyelk")
pytest.importorskip("anywidget")

import ipywidgets as W

import longeron
from longeron import app as app_module
from longeron import edit
from longeron import explorer as explorer_module
from longeron import inspector as inspector_module
from longeron import model as M

ROOT = Path(__file__).resolve().parent.parent

RIG_MODEL = """
package Rig {
    part def Chassis {
        attribute mass : Real = 10.0;
        attribute payload : MassValue;
    }
    part def Wheel;
    part axle : Chassis {
        doc /* The axle. */
    }
    part wheels : Wheel[4];
    port def P;
    part hub { port p : P; }
    part spinner { port p : P; }
    connection c connect hub.p to spinner.p;
    requirement def R;
    requirement r : R;
    satisfy r by axle;
    calc def C { in speed : Real; return : Real = speed * 2.0; }
}
"""


@pytest.fixture()
def rig_model():
    return longeron.loads(RIG_MODEL, source_name="rig demo")


# one of every relationship kind the inspector must render a meaningful
# sheet for (the explorer's classification model, verbatim shape)
REL_KINDS_MODEL = """
package Rels {
    part def A { attribute x : Real; }
    part a1 : A;
    part b1 : A;
    requirement massBudget;
    satisfy massBudget by a1;
    verification def CheckMass {
        subject rig : A;
        objective { verify massBudget; }
    }
    dependency Dep from a1 to b1;
    import Other::*;
    filter @Safety;
    view scene { expose Rels::**; }
    alias also for a1;
}
package Other { part def C; metadata def Safety; }
"""


@pytest.fixture()
def rels_model():
    return longeron.loads(REL_KINDS_MODEL, source_name="rels demo")


@pytest.fixture(autouse=True)
def _fresh_registries(monkeypatch):
    monkeypatch.setattr(app_module, "_OPEN_APPS", {})
    monkeypatch.setattr(app_module, "_DOCKED_PANELS", {})
    monkeypatch.setattr(app_module, "_PALETTE_ADDED", False)
    monkeypatch.setattr(app_module, "_ACTIVE_APP", None)
    monkeypatch.setattr(explorer_module, "_DOCKED_PANELS", {})
    monkeypatch.setattr(inspector_module, "_OPEN_INSPECTORS", {})


# ---------------------------------------------------------------------------
# the fake ipylab (the test_app pattern, verbatim minimum)
# ---------------------------------------------------------------------------


class _StubShell:
    def __init__(self):
        self.added = []

    def add(self, panel, area, options=None):
        self.added.append((panel, area, options))


class _StubCommands:
    def list_commands(self):
        return []

    def add_command(self, command_id, execute, **kwargs):
        pass

    def remove_command(self, command_id):
        pass


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
    def add_item(self, command_id, category, **kwargs):
        pass


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
    return module


def _open_lab(monkeypatch, **kwargs):
    _install_stub_ipylab(monkeypatch)
    return app_module.open(layout="lab", **kwargs)


def _static_rows(inspector):
    """The rendered read-only rows as (key, value) pairs."""

    import re

    pairs = []
    for child in inspector._body.children:
        if isinstance(child, W.HTML) and "lgx-insp-row" in child.value:
            match = re.search(
                r'lgx-insp-key">([^<]*)</span><span class="lgx-insp-static">([^<]*)<', child.value
            )
            if match:
                pairs.append((match.group(1), match.group(2)))
    return pairs


def _endpoint_rows(inspector):
    return [
        child
        for child in inspector._body.children
        if "lgx-insp-endpoint" in getattr(child, "_dom_classes", ())
    ]


def _row_widgets(app, index=0):
    row = app._list_box.children[index]
    name, actions = row.children
    _explore_btn, _score_btn, save_btn, _close_btn = actions.children
    return name, save_btn


# ---------------------------------------------------------------------------
# docking + construction
# ---------------------------------------------------------------------------


class TestDocking:
    def test_docks_right_with_identity_and_sweeper(self, monkeypatch):
        app = _open_lab(monkeypatch)
        insp = app.inspector
        assert insp is not None and insp.layout_strategy == "lab"
        # the inspector docked through its OWN frontend into the right area
        (frontend,) = [f for f in _StubFrontEnd.instances if f is not app._frontend]
        ((panel, area, options),) = frontend.shell.added
        assert panel is insp.lab_panel and area == "right"
        assert options == {"rank": 610}
        # ICON-ONLY tab, exactly like the app panel's (maintainer QA):
        # empty label, identity on the hover caption, the sibling icon
        assert panel.title.label == ""
        assert panel.title.caption.startswith("Longeron")
        assert panel.title.icon.name == "longeron:inspector"
        assert panel.title.dataset["lgxkey"] == "longeron-inspector"
        assert panel.title.dataset["lgxstamp"].isdigit()
        assert panel.children == (insp,)
        sweeper = insp._sweeper
        assert sweeper is insp.children[-1]  # ships INSIDE the panel content
        assert sweeper.side == "right"
        assert sweeper.key == "longeron-inspector"
        assert sweeper.stamp == panel.title.dataset["lgxstamp"]
        # collapsed-by-default: docking must not reshape the user's layout
        assert sweeper.activate is False

    def test_reopen_replaces_the_panel(self, monkeypatch):
        first = _open_lab(monkeypatch)
        second = app_module.open(layout="lab")
        assert first.inspector.lab_panel.closed
        assert not second.inspector.lab_panel.closed
        registry = inspector_module._OPEN_INSPECTORS
        assert registry == {"longeron-inspector": second.inspector.lab_panel}

    def test_inline_app_builds_an_inline_inspector(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "ipylab", raising=False)
        monkeypatch.delenv("JPY_SESSION_NAME", raising=False)
        app = app_module.open()
        assert app.inspector is not None
        assert app.inspector.layout_strategy == "inline"
        assert app.inspector.lab_panel is None

    def test_inspector_false_skips_it(self, monkeypatch):
        app = _open_lab(monkeypatch, inspector=False)
        assert app.inspector is None

    def test_tab_icon_contract(self, monkeypatch):
        # the maintainer's icon spec, restated for the sibling variant:
        # builtin intrinsic sizing, theme-following fill, and NEVER the
        # trademarked 'SysML' wordmark (OMG registered trademark)
        svg = inspector_module._ICON_SVG
        assert 'width="16"' in svg
        assert 'viewBox="0 0 24 24"' in svg
        assert 'class="jp-icon3"' in svg
        assert "SysML" not in svg and "OMG" not in svg
        assert "<text" not in svg  # a glyph, not lettering
        # the shared sidebar-icon sizing rule rides the inspector CSS too
        assert ".lm-TabBar-tabIcon svg" in inspector_module._INSPECTOR_CSS

    def test_reveal_pokes_the_sweeper(self, monkeypatch):
        app = _open_lab(monkeypatch)
        insp = app.inspector
        sweeper = insp._sweeper
        assert sweeper.activate is False and sweeper.poke == 0
        insp.reveal()
        assert sweeper.activate is True and sweeper.poke == 1
        insp.reveal()  # idempotent mechanics: each call is one more poke
        assert sweeper.poke == 2

    def test_reveal_is_a_noop_inline(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "ipylab", raising=False)
        monkeypatch.delenv("JPY_SESSION_NAME", raising=False)
        app = app_module.open()
        assert app.inspector._sweeper is None
        app.inspector.reveal()  # must not raise


# ---------------------------------------------------------------------------
# selection -> sheet content
# ---------------------------------------------------------------------------


class TestSheet:
    def test_empty_before_any_selection(self, monkeypatch):
        app = _open_lab(monkeypatch)
        insp = app.inspector
        assert insp.element is None
        (hint,) = insp._body.children
        assert "no selection" in hint.value

    def test_selection_fills_header_and_name(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::axle")
        insp = app.inspector
        assert insp.element is rig_model.find("Rig::axle")
        assert "axle" in insp._header.value  # the name
        assert "lgx-chip-structure" in insp._header.value  # the kind chip
        assert "Rig \u203a axle" in insp._header.value  # the breadcrumb
        assert insp._name_field.value == "axle"
        # the source location rides the header tooltip
        assert 'title="rig demo:' in insp._header.value

    def test_direct_explore_selection_fills_the_sheet(self, monkeypatch, rig_model):
        # the OTHER explorer path (maintainer QA): a plain explore() call
        # -- never launched by the app -- is adopted into the newest app,
        # so its tree selections reach this sheet too
        app = _open_lab(monkeypatch)
        ex = explorer_module.explore(rig_model, layout="inline")
        assert app.inspector.element is None  # adoption alone shows nothing
        ex.select("Rig::axle")
        insp = app.inspector
        assert insp.element is rig_model.find("Rig::axle")
        assert insp._name_field.value == "axle"

    def test_read_only_rows_present_and_styled(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::wheels")
        rows = _static_rows(app.inspector)
        assert ("kind", "part") in rows
        assert ("typed by", "Wheel") in rows
        assert ("multiplicity", "[4]") in rows

    def test_direction_row_for_directed_features(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::C::speed")
        rows = _static_rows(app.inspector)
        assert ("direction", "in") in rows

    def test_absent_rows_are_omitted(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Chassis")  # a part def: no typing/mult/direction
        rows = _static_rows(app.inspector)
        assert rows == [("kind", "part def")]
        # and no editable value field for a definition
        assert app.inspector._value_field not in app.inspector._body.children

    def test_doc_and_value_prefilled(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::axle")
        assert app.inspector._doc_field.value == "The axle."
        ex.select("Rig::Chassis::mass")
        # the house expression rendering (ast.expr_to_text) fills the field
        assert app.inspector._value_field.value == "10.0"

    def test_value_field_shows_compact_units(self, monkeypatch):
        # maintainer QA: units are FIRST-CLASS in the sheet -- the value
        # field shows the magnitude + unit symbol compactly ('0.39 kg',
        # never the raw '0.38 [SI::kg]' expression), the typed-by row
        # keeps the TYPE but names the unit beside it ('Real [kg]'), and
        # a dedicated unit row gives the symbol + dimension
        app = _open_lab(monkeypatch)
        model = app.load_path(ROOT / "examples" / "deepscout")
        ex = app.explore_model(model)
        ex.select("ScoutParts::F450Kit::Battery::mass")
        assert app.inspector._value_field.value == "0.39 kg"
        rows = _static_rows(app.inspector)
        assert ("typed by", "Real [kg]") in rows
        assert ("unit", "kg \u2014 mass") in rows

    def test_unit_row_for_quantity_typed_attribute(self, monkeypatch, rig_model):
        # no bracket value, but the unit table derives the dimension from
        # the quantity typing (MassValue): the unit row still shows
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Chassis::payload")
        rows = _static_rows(app.inspector)
        assert ("unit", "kg \u2014 mass") in rows
        assert ("typed by", "MassValue") in rows  # no bracket: type stays bare

    def test_unitless_value_keeps_the_plain_rendering(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Chassis::mass")
        assert app.inspector._value_field.value == "10.0"
        assert not any(key == "unit" for key, _ in _static_rows(app.inspector))

    def test_value_edit_keeps_bracket_units(self, monkeypatch):
        # committing a unit-bearing value goes through longeron.edit; the
        # compact 'magnitude symbol' spelling re-attaches the CURRENT
        # measurement reference, and the field re-normalizes compactly
        app = _open_lab(monkeypatch)
        model = app.load_path(ROOT / "examples" / "deepscout")
        ex = app.explore_model(model)
        ex.select("ScoutParts::F450Kit::Battery::mass")
        app.inspector._value_field.value = "0.4 kg"
        element = model.find("ScoutParts::F450Kit::Battery::mass")
        assert app.inspector._value_field.value == "0.4 kg"
        from longeron.ast import expr_to_text

        assert expr_to_text(element.value.expr) == "0.4 [SI::kg]"
        # the explicit bracket spelling commits too, and normalizes back
        app.inspector._value_field.value = "0.45 [SI::kg]"
        assert app.inspector._value_field.value == "0.45 kg"
        assert expr_to_text(element.value.expr) == "0.45 [SI::kg]"

    def test_sheet_clears_when_the_list_empties(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::axle")
        app.close_model(rig_model)
        assert app.inspector.element is None
        (hint,) = app.inspector._body.children
        assert "no selection" in hint.value


# ---------------------------------------------------------------------------
# edit commits (Enter/blur -> longeron.edit; refusals revert)
# ---------------------------------------------------------------------------


class TestEdits:
    def test_rename_goes_through_edit_rename(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Wheel")
        calls = []
        real = edit.rename

        def spy(model, element, new_name):
            calls.append((model, element, new_name))
            return real(model, element, new_name)

        monkeypatch.setattr(edit, "rename", spy)
        app.inspector._name_field.value = "Tyre"
        ((model, element, new_name),) = calls
        assert model is rig_model and new_name == "Tyre"
        assert element is rig_model.find("Rig::Tyre")

    def test_rename_cascades_and_refreshes_the_tree(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Wheel")
        app.inspector._name_field.value = "Tyre"
        assert rig_model.find("Rig::Tyre") is not None
        # the cascade rewrote the typing on 'wheels : Wheel'
        assert rig_model.find("Rig::wheels").types == ["Tyre"]
        # the app-launched explorer's tree payload rebuilt...
        assert "Tyre" in ex.tree.nodes_json and '"Wheel"' not in ex.tree.nodes_json
        # ...preserving the selection by element IDENTITY (new node id)
        assert ex.tree.selected == ["Rig::Tyre"]
        assert ex.element is rig_model.find("Rig::Tyre")
        # the sheet's own header moved with the qualified name
        assert "Rig \u203a Tyre" in app.inspector._header.value
        assert app.inspector._error.layout.display == "none"

    def test_rename_refusal_shows_the_reference_list_and_reverts(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Wheel")
        app.inspector._name_field.value = "Chassis"  # a sibling collision
        assert app.inspector._name_field.value == "Wheel"  # reverted
        assert app.inspector._error.layout.display is None
        assert "already used by another member" in app.inspector._error.value
        assert rig_model.find("Rig::Wheel") is not None  # nothing changed
        # a later successful commit clears the strip
        app.inspector._name_field.value = "Tyre"
        assert app.inspector._error.layout.display == "none"

    def test_rename_to_an_illegal_name_is_refused(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Wheel")
        app.inspector._name_field.value = "A::B"
        assert "not a legal name" in app.inspector._error.value
        assert app.inspector._name_field.value == "Wheel"

    def test_doc_commit_and_removal(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Chassis")
        app.inspector._doc_field.value = "The frame."
        assert rig_model.find("Rig::Chassis").doc == "The frame."
        app.inspector._doc_field.value = ""
        assert rig_model.find("Rig::Chassis").doc is None

    def test_value_commit_normalizes_through_expr_to_text(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Chassis::mass")
        app.inspector._value_field.value = "2*  6.0"
        mass = rig_model.find("Rig::Chassis::mass")
        assert app.inspector._value_field.value == "2 * 6.0"  # the house rendering
        assert mass.value is not None

    def test_value_parse_error_reverts(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Chassis::mass")
        app.inspector._value_field.value = "(("
        assert "cannot parse" in app.inspector._error.value
        assert app.inspector._value_field.value == "10.0"  # reverted
        assert rig_model.find("Rig::Chassis::mass").value is not None

    def test_value_cleared_removes_the_binding(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Chassis::mass")
        app.inspector._value_field.value = ""
        assert rig_model.find("Rig::Chassis::mass").value is None

    def test_fake_unit_commit_lands_in_the_error_strip(self, monkeypatch):
        # the maintainer's integrity hole: a fake unit must be REFUSED at
        # commit -- error strip, field reverted to the compact display
        # (never the raw expression), model untouched, row not dirtied
        app = _open_lab(monkeypatch)
        model = app.load_path(ROOT / "examples" / "deepscout")
        ex = app.explore_model(model)
        ex.select("ScoutParts::F450Kit::Battery::mass")
        from longeron.ast import expr_to_text

        before = expr_to_text(model.find("ScoutParts::F450Kit::Battery::mass").value.expr)
        app.inspector._value_field.value = "0.42 [SI::kgg]"
        assert app.inspector._error.layout.display is None
        assert "unit &#x27;SI::kgg&#x27; does not resolve" in app.inspector._error.value
        assert "did you mean" in app.inspector._error.value
        assert app.inspector._value_field.value == "0.39 kg"  # compact, not raw
        assert expr_to_text(model.find("ScoutParts::F450Kit::Battery::mass").value.expr) == before
        name, _ = _row_widgets(app)
        assert "lgx-app-dirty" not in name._dom_classes
        assert not edit.track(model).dirty
        # a later good commit clears the strip
        app.inspector._value_field.value = "0.42 kg"
        assert app.inspector._error.layout.display == "none"
        assert (
            expr_to_text(model.find("ScoutParts::F450Kit::Battery::mass").value.expr)
            == "0.42 [SI::kg]"
        )

    def test_wrong_dimension_commit_reverts_and_reports(self, monkeypatch, rig_model):
        # payload : MassValue pins the dimension; SI::s is a real unit of
        # the WRONG one -- refused stating both dimensions
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Chassis::payload")
        app.inspector._value_field.value = "5.0 [SI::s]"
        assert "is mass-typed" in app.inspector._error.value
        assert "is duration" in app.inspector._error.value
        assert app.inspector._value_field.value == ""  # reverted: it had no value
        assert rig_model.find("Rig::Chassis::payload").value is None
        assert not edit.track(rig_model).dirty

    def test_bare_number_commit_keeps_the_current_unit(self, monkeypatch):
        # the field displayed '0.39 kg'; committing '0.42' means a new
        # magnitude in the same unit, never a silently dropped reference
        app = _open_lab(monkeypatch)
        model = app.load_path(ROOT / "examples" / "deepscout")
        ex = app.explore_model(model)
        ex.select("ScoutParts::F450Kit::Battery::mass")
        app.inspector._value_field.value = "0.42"
        assert app.inspector._value_field.value == "0.42 kg"
        from longeron.ast import expr_to_text

        assert (
            expr_to_text(model.find("ScoutParts::F450Kit::Battery::mass").value.expr)
            == "0.42 [SI::kg]"
        )

    def test_same_dimension_unit_change_commits_and_renormalizes(self, monkeypatch):
        # '420.0 [SI::g]' on a kg attribute: a real unit, same dimension --
        # accepted verbatim (the value means what it says), shown compactly
        app = _open_lab(monkeypatch)
        model = app.load_path(ROOT / "examples" / "deepscout")
        ex = app.explore_model(model)
        ex.select("ScoutParts::F450Kit::Battery::mass")
        app.inspector._value_field.value = "420.0 [SI::g]"
        assert app.inspector._error.layout.display == "none"
        assert app.inspector._value_field.value == "420.0 g"
        from longeron.ast import expr_to_text

        assert (
            expr_to_text(model.find("ScoutParts::F450Kit::Battery::mass").value.expr)
            == "420.0 [SI::g]"
        )

    def test_compact_symbol_commit_round_trips(self, monkeypatch):
        # THE maintainer finding: the sheet DISPLAYS '0.39 kg', so typing
        # back what the tool shows -- '390 g' -- must commit.  The symbol
        # resolves through the same table the display reads, stores as
        # the canonical bracket expression, the field re-displays the
        # compact form, and the unit / typed-by rows follow ('g -- mass')
        app = _open_lab(monkeypatch)
        model = app.load_path(ROOT / "examples" / "deepscout")
        ex = app.explore_model(model)
        ex.select("ScoutParts::F450Kit::Battery::mass")
        app.inspector._value_field.value = "390 g"
        assert app.inspector._error.layout.display == "none"
        assert app.inspector._value_field.value == "390 g"
        from longeron.ast import expr_to_text

        assert (
            expr_to_text(model.find("ScoutParts::F450Kit::Battery::mass").value.expr)
            == "390 [SI::g]"
        )
        rows = _static_rows(app.inspector)
        assert ("unit", "g \u2014 mass") in rows
        assert ("typed by", "Real [g]") in rows

    def test_prefixed_symbol_commit_stores_model_derived(self, monkeypatch):
        # 'mg' is no unit the stdlib NAMES: it decomposes through the
        # model's own prefix algebra (SIPrefixes::milli) and stores
        # rescaled in grams; the sheet then shows the canonical compact
        # form -- the honest spelling of a unit the model has no name for
        app = _open_lab(monkeypatch)
        model = app.load_path(ROOT / "examples" / "deepscout")
        ex = app.explore_model(model)
        ex.select("ScoutParts::F450Kit::Battery::mass")
        app.inspector._value_field.value = "17 mg"
        assert app.inspector._error.layout.display == "none"
        assert app.inspector._value_field.value == "0.017 g"
        from longeron.ast import expr_to_text

        assert (
            expr_to_text(model.find("ScoutParts::F450Kit::Battery::mass").value.expr)
            == "0.017 [SI::g]"
        )
        assert ("unit", "g \u2014 mass") in _static_rows(app.inspector)

    def test_compact_wrong_dimension_lands_in_the_error_strip(self, monkeypatch):
        # '17 s' typed compactly on a kg-valued attribute: the dimension
        # gates apply to the compact form unchanged
        app = _open_lab(monkeypatch)
        model = app.load_path(ROOT / "examples" / "deepscout")
        ex = app.explore_model(model)
        ex.select("ScoutParts::F450Kit::Battery::mass")
        app.inspector._value_field.value = "17 s"
        assert app.inspector._error.layout.display is None
        assert "pass validate=False to override" in app.inspector._error.value
        assert app.inspector._value_field.value == "0.39 kg"  # reverted
        assert not edit.track(model).dirty


# ---------------------------------------------------------------------------
# the dirty / save / push chrome
# ---------------------------------------------------------------------------


class TestDirtyChrome:
    def test_dirty_dot_and_save_cycle(self, monkeypatch, tmp_path):
        source = tmp_path / "rig.sysml"
        source.write_text(RIG_MODEL, encoding="utf-8")
        app = _open_lab(monkeypatch)
        model = app.load_path(source)
        name, save_btn = _row_widgets(app)
        assert "\u25cf" not in name.description and save_btn.disabled
        # ANY edit.* on the loaded model reaches the chrome (not just the
        # inspector's commits -- a notebook cell edits the same tracker)
        edit.set_doc(model, "Rig::Chassis", "The frame.")
        name, save_btn = _row_widgets(app)
        assert name.description.endswith("\u25cf")
        assert "lgx-app-dirty" in name._dom_classes
        assert "unsaved changes (1)" in name.tooltip
        assert "documented Rig::Chassis" in name.tooltip
        assert not save_btn.disabled
        save_btn.click()
        assert "The frame." in source.read_text(encoding="utf-8")
        assert not edit.track(model).dirty  # mark_saved ran
        name, save_btn = _row_widgets(app)
        assert "\u25cf" not in name.description and save_btn.disabled

    def test_inspector_edit_marks_the_row_dirty(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Wheel")
        app.inspector._name_field.value = "Tyre"
        name, _ = _row_widgets(app)
        assert "lgx-app-dirty" in name._dom_classes
        assert "renamed Rig::Wheel \u2192 Rig::Tyre" in name.tooltip

    def test_refused_edits_do_not_dirty(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::Wheel")
        app.inspector._name_field.value = "Chassis"  # refused
        name, _ = _row_widgets(app)
        assert "lgx-app-dirty" not in name._dom_classes
        assert not edit.track(rig_model).dirty

    def test_push_cycle_marks_saved(self, monkeypatch, rig_model):
        class _FakeClient:
            def __init__(self):
                self.pushes = []

            def list_projects(self):
                return [{"@id": "p-1", "name": "Demo"}]

            def list_commits(self, project):
                return []

            def fetch_model(self, project, commit=None):
                return rig_model

            def push_commit(self, project, changes, *, description=""):
                self.pushes.append((project, changes, description))
                return {"@id": "c-new"}

        app = _open_lab(monkeypatch)
        client = _FakeClient()
        app.connect_api("http://example.test", client=client)
        app.fetch_api_model()
        name, push_btn = _row_widgets(app)
        assert push_btn.description == "Push" and push_btn.disabled
        edit.set_doc(rig_model, "Rig", "The rig.")
        name, push_btn = _row_widgets(app)
        assert not push_btn.disabled
        push_btn.click()
        app._push_message.value = "document the rig"
        app._push_bar.children[1].click()  # Commit
        assert client.pushes == [("p-1", rig_model, "document the rig")]
        assert not edit.track(rig_model).dirty
        name, push_btn = _row_widgets(app)
        assert push_btn.disabled and "\u25cf" not in name.description


# ---------------------------------------------------------------------------
# relationship-endpoint navigation
# ---------------------------------------------------------------------------


class TestNavigation:
    def test_connection_ends_are_clickable_and_navigate(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        ex.select("Rig::c")
        ends = _endpoint_rows(app.inspector)
        assert [row.children[1].description for row in ends] == ["hub.p", "spinner.p"]
        ends[1].children[1].click()
        # the click routed through the explorer: tree selection + seam
        assert ex.tree.selected == ["Rig::spinner::p"]
        assert app.current_element is rig_model.find("Rig::spinner::p")
        assert app.inspector.element is app.current_element

    def test_satisfy_rows_navigate_both_ways(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        ex = app.explore_model(rig_model)
        satisfy = next(el for el in rig_model.iter_tree() if isinstance(el, M.SatisfyUsage))
        ex.select(satisfy)
        ends = _endpoint_rows(app.inspector)
        assert [row.children[1].description for row in ends] == ["r", "axle"]
        ends[0].children[1].click()
        assert app.current_element is rig_model.find("Rig::r")
        ex.select(satisfy)
        ends = _endpoint_rows(app.inspector)
        ends[1].children[1].click()
        assert app.current_element is rig_model.find("Rig::axle")

    def test_select_element_without_an_explorer_feeds_the_seam(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        target = rig_model.find("Rig::axle")
        app.select_element(target)
        assert app.current_element is target
        assert app.inspector.element is target


# ---------------------------------------------------------------------------
# the relationship sheet (maintainer finding: 'I can't inspect relationships')
# ---------------------------------------------------------------------------


def _select(app, model, predicate):
    element = next(el for el in model.iter_tree() if predicate(el))
    app.select_element(element)
    return element


class TestRelationshipSheet:
    """Every relationship kind renders a meaningful sheet: the
    relationship chip + derived label in the header, ENDPOINTS as
    clickable navigation rows, the full declaration in a read-only
    block, and a name field only where the element HAS a name."""

    def test_anonymous_satisfy_sheet_shape(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        insp = app.inspector
        _select(app, rig_model, lambda el: isinstance(el, M.SatisfyUsage))
        # the relationship chip + the derived label head the sheet
        assert "lgx-chip-relationship" in insp._header.value
        assert "satisfy r" in insp._header.value
        assert ("kind", "satisfy") in _static_rows(insp)
        # anonymous: a declaration is not a nameable thing -- no name field
        assert insp._name_field not in insp._body.children
        # the full declaration, in the read-only block
        blocks = [
            c.value
            for c in insp._body.children
            if isinstance(c, W.HTML) and "lgx-insp-decl" in getattr(c, "value", "")
        ]
        assert len(blocks) == 1 and "satisfy r by axle;" in blocks[0]

    def test_named_connection_keeps_the_name_field(self, monkeypatch, rig_model):
        app = _open_lab(monkeypatch)
        app.add_model(rig_model)
        insp = app.inspector
        app.select_element(rig_model.find("Rig::c"))
        assert insp._name_field in insp._body.children
        assert insp._name_field.value == "c"
        blocks = [
            c.value
            for c in insp._body.children
            if isinstance(c, W.HTML) and "lgx-insp-decl" in getattr(c, "value", "")
        ]
        assert len(blocks) == 1 and "connect hub.p to spinner.p" in blocks[0]

    def test_every_restored_kind_shows_its_endpoints(self, monkeypatch, rels_model):
        # the endpoint table: relationship kind -> the clickable rows'
        # button texts (qualified paths / the exporter's target shapes)
        app = _open_lab(monkeypatch)
        app.add_model(rels_model)
        insp = app.inspector
        table = {
            "satisfy": (lambda el: isinstance(el, M.SatisfyUsage), ["massBudget", "a1"]),
            "verify": (
                lambda el: isinstance(el, M.Usage) and el.kind == "verify",
                ["massBudget"],
            ),
            "dependency": (lambda el: isinstance(el, M.Dependency), ["a1", "b1"]),
            "import": (lambda el: isinstance(el, M.Import), ["Other::*"]),
            "expose": (lambda el: isinstance(el, M.Expose), ["Rels::**"]),
            "alias": (lambda el: isinstance(el, M.Alias), ["a1"]),
        }
        for kind, (finder, expected) in table.items():
            _select(app, rels_model, finder)
            ends = _endpoint_rows(insp)
            assert [row.children[1].description for row in ends] == expected, kind

    def test_import_endpoint_navigates_to_the_namespace(self, monkeypatch, rels_model):
        # the shown text is the exporter's shape (Other::*); the CLICK
        # resolves the bare namespace target and moves the selection
        app = _open_lab(monkeypatch)
        app.add_model(rels_model)
        _select(app, rels_model, lambda el: isinstance(el, M.Import))
        (row,) = _endpoint_rows(app.inspector)
        row.children[1].click()
        assert app.current_element is rels_model.find("Other")
        assert app.inspector.element is app.current_element

    def test_filter_condition_is_a_read_only_row(self, monkeypatch, rels_model):
        app = _open_lab(monkeypatch)
        app.add_model(rels_model)
        _select(app, rels_model, lambda el: isinstance(el, M.ElementFilter))
        rows = _static_rows(app.inspector)
        assert ("kind", "filter") in rows
        assert ("condition", "@Safety") in rows
        assert app.inspector._name_field not in app.inspector._body.children
