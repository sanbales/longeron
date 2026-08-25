"""View persistence: saving diagrams as SysML v2 views (longeron.views).

The ratified design is docs/design/view-persistence.md; these tests pin
its contract: the standard tier (a typed view usage with exposes and a
render reference, appended to the owning package, textual fixpoint), the
sidecar tier (versioned JSON keyed by qualified name, forward
compatible), the expose-closure semantics restore runs on, and the
warn-and-skip behavior for dangling exposes.  API-record round-trips
live in test_api_json.py, the diagram drawing in test_diagrams.py, the
diagnostic in test_validation.py, and the explorer seam in
test_explorer.py -- each with the behavior's home surface.
"""

import json
import warnings

import pytest

import longeron
from longeron import model as M
from longeron import views
from longeron.errors import SysMLError

RIG = """
package Rig {
    part def Axle {
        part hub : Hub [2];
    }
    part def Hub;
    part axle : Axle;
}
"""

CLOSURE_MODEL = """
package P {
    part def A {
        part inner : B;
    }
    part def B;
    connection def C;
    part a : A;
    connection c : C connect a to a;
    view vMember {
        expose P::a;
    }
    view vMemberRecursive {
        expose P::A::**;
    }
    view vNamespace {
        expose P::*;
    }
    view vNamespaceFiltered {
        expose P::*[not @SysML::ConnectionUsage];
    }
    view vFiltered {
        expose P::**;
        filter @SysML::PartUsage;
    }
    view vDangling {
        expose P::gone;
        expose P::a;
    }
}
"""


def rig_model():
    return longeron.loads(RIG)


# ---------------------------------------------------------------------------
# save_view: the standard tier
# ---------------------------------------------------------------------------


class TestSaveView:
    def test_writes_the_design_docs_example(self):
        # the ratified textual shape, byte for byte (design doc "What a
        # saved diagram writes")
        model = rig_model()
        views.save_view(model, "Rig", name="axle structure", kind="structure")
        assert longeron.to_sysml(model) == (
            "package Rig {\n"
            "    part def Axle {\n"
            "        part hub : Hub [2];\n"
            "    }\n"
            "    part def Hub;\n"
            "    part axle : Axle;\n"
            "    view 'axle structure' : StandardViewDefinitions::InterconnectionView {\n"
            "        expose Rig::**;\n"
            "        render Views::asInterconnectionDiagram;\n"
            "    }\n"
            "}\n"
        )

    def test_saved_text_round_trips_at_a_fixpoint(self):
        model = rig_model()
        views.save_view(model, "Rig", name="axle structure")
        text = longeron.to_sysml(model)
        assert longeron.to_sysml(longeron.loads(text)) == text

    def test_saved_view_validates_cleanly_with_the_stdlib(self):
        model = rig_model()
        views.save_view(model, "Rig", name="axle structure")
        assert longeron.validate(model) == []

    def test_view_is_appended_to_the_owning_package(self):
        # append-only (ratified question 1): existing members keep their
        # positions, so index-path element ids stay stable
        model = rig_model()
        rig = model.find("Rig")
        before = list(rig.members)
        view = views.save_view(model, "Rig")
        assert rig.members[: len(before)] == before
        assert rig.members[-1] is view

    def test_nested_element_saves_into_its_owning_package(self):
        model = rig_model()
        view = views.save_view(model, "Rig::axle", name="axle view")
        assert view.owner is model.find("Rig")
        exposes = [m for m in view.members if isinstance(m, M.Expose)]
        assert [(e.target, e.is_recursive, e.is_namespace) for e in exposes] == [
            ("Rig::axle", True, False)
        ]

    def test_typing_matches_the_diagram_kind(self):
        model = longeron.loads("""
        package P {
            state def Machine { entry; then idle; state idle; }
            action def Act { action step1; }
            requirement def R;
        }
        """)
        cases = {
            "structure": "StandardViewDefinitions::InterconnectionView",
            "state": "StandardViewDefinitions::StateTransitionView",
            "action": "StandardViewDefinitions::ActionFlowView",
            "requirements": "StandardViewDefinitions::GeneralView",
        }
        for kind, definition in cases.items():
            view = views.save_view(model, "P", kind=kind, name=f"as {kind}")
            assert view.types == [definition]

    def test_kind_inferred_from_the_element(self):
        model = longeron.loads("""
        package P { state def Machine { entry; then idle; state idle; } }
        """)
        view = views.save_view(model, "P::Machine")
        assert view.types == ["StandardViewDefinitions::StateTransitionView"]
        assert view.name == "Machine state"

    def test_default_name_is_element_and_kind(self):
        model = rig_model()
        view = views.save_view(model, "Rig")
        assert view.name == "Rig structure"

    def test_explicit_element_list_gets_one_expose_each(self):
        model = rig_model()
        view = views.save_view(model, ["Rig::Axle", "Rig::Hub"], name="defs")
        exposes = [m for m in view.members if isinstance(m, M.Expose)]
        assert [e.target for e in exposes] == ["Rig::Axle", "Rig::Hub"]

    def test_saving_under_an_existing_name_replaces_the_recipe(self):
        # save is idempotent by qualified name (design doc collision
        # semantics): the element identity is kept -- no index shift
        model = rig_model()
        first = views.save_view(model, "Rig", name="axle structure")
        again = views.save_view(model, "Rig::axle", name="axle structure")
        assert again is first
        exposes = [m for m in again.members if isinstance(m, M.Expose)]
        assert [e.target for e in exposes] == ["Rig::axle"]
        renders = [m for m in again.members if isinstance(m, M.Usage) and m.kind == "render"]
        assert len(renders) == 1
        assert [m for m in model.find("Rig").members if m.name == "axle structure"] == [first]

    def test_unknown_kind_rejected(self):
        with pytest.raises(SysMLError, match="kind must be one of"):
            views.save_view(rig_model(), "Rig", kind="mystery")

    def test_unaddressable_element_rejected(self):
        model = rig_model()
        stray = M.Usage(kind="part", name="stray")  # never added to the model
        with pytest.raises(SysMLError, match="not addressable"):
            views.save_view(model, stray)

    def test_empty_exposed_rejected(self):
        with pytest.raises(SysMLError, match="at least one exposed element"):
            views.save_view(rig_model(), [])


class TestListViews:
    def test_lists_kind_and_exposes(self):
        model = rig_model()
        views.save_view(model, "Rig", name="axle structure")
        infos = views.list_views(model)
        assert [i.qualified_name for i in infos] == ["Rig::axle structure"]
        assert infos[0].kind == "structure"
        assert [e.target for e in infos[0].exposes] == ["Rig"]

    def test_untyped_views_have_no_kind(self):
        model = longeron.loads("package P { view v { expose P::*; } }")
        (info,) = views.list_views(model)
        assert info.kind is None

    def test_view_kinds_mirror_the_explorer_vocabulary(self):
        # the sidecar 'kind' values are explorer.DIAGRAM_KINDS by contract
        explorer = pytest.importorskip("longeron.explorer")
        assert views.VIEW_KINDS == explorer.DIAGRAM_KINDS


# ---------------------------------------------------------------------------
# the expose closure (restore step 2)
# ---------------------------------------------------------------------------


class TestExposeClosure:
    @pytest.fixture(scope="class")
    @staticmethod
    def model():
        return longeron.loads(CLOSURE_MODEL)

    @staticmethod
    def closure(model, name):
        view = model.find(f"P::{name}")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return sorted(e.label for e in views.expose_closure(model, view))

    def test_membership_expose_yields_the_element(self, model):
        assert self.closure(model, "vMember") == ["a"]

    def test_recursive_membership_expose_yields_the_subtree(self, model):
        assert self.closure(model, "vMemberRecursive") == ["A", "inner"]

    def test_namespace_expose_yields_the_members_not_the_namespace(self, model):
        result = self.closure(model, "vNamespace")
        assert "P" not in result
        assert {"A", "B", "C", "a"} <= set(result)

    def test_bracket_filter_restricts_the_closure(self, model):
        result = self.closure(model, "vNamespaceFiltered")
        assert "c" not in result  # the connection USAGE fails not @ConnectionUsage
        assert "C" in result  # the connection DEF is not a ConnectionUsage
        assert {"A", "B", "a"} <= set(result)

    def test_view_filter_restricts_the_recursive_closure(self, model):
        # expose P::** + filter @SysML::PartUsage: part USAGES only
        assert self.closure(model, "vFiltered") == ["a", "inner"]

    def test_dangling_expose_warns_and_skips(self, model):
        view = model.find("P::vDangling")
        with pytest.warns(UserWarning, match="dangling expose.*'P::gone'"):
            closure = views.expose_closure(model, view)
        assert [e.label for e in closure] == ["a"]  # the resolvable expose survives


# ---------------------------------------------------------------------------
# the sidecar tier
# ---------------------------------------------------------------------------


class TestSidecar:
    def test_round_trip(self, tmp_path):
        entries = {
            "Rig::axle structure": {
                "kind": "structure",
                "direction": "down",
                "routing": "splines",
                "collapsed": ["Rig::Axle"],
                "options": {"membership": "edges"},
            }
        }
        file = views.save_sidecar(tmp_path, entries)
        assert file == tmp_path / ".longeron" / "views.json"
        assert views.load_sidecar(file) == entries

    def test_document_shape_matches_the_design_doc(self, tmp_path):
        file = views.save_sidecar(tmp_path, {"P::v": {"kind": "structure"}})
        data = json.loads(file.read_text(encoding="utf-8"))
        assert data["schema"] == "longeron/views"
        assert data["version"] == 1
        assert set(data) == {"schema", "version", "views"}

    def test_missing_file_loads_empty(self, tmp_path):
        assert views.load_sidecar(tmp_path / "nothing.json") == {}

    def test_unknown_future_keys_survive_a_rewrite(self, tmp_path):
        # forward compatibility: keep unknown per-view keys intact
        entries = {"P::v": {"kind": "structure", "hologram": {"depth": 3}}}
        file = views.save_sidecar(tmp_path, entries)
        rewritten = views.save_sidecar(tmp_path, views.load_sidecar(file))
        assert views.load_sidecar(rewritten)["P::v"]["hologram"] == {"depth": 3}

    def test_future_versions_load(self, tmp_path):
        file = tmp_path / "views.json"
        file.write_text(
            json.dumps(
                {
                    "schema": "longeron/views",
                    "version": 7,
                    "views": {"P::v": {"kind": "structure", "warp": True}},
                }
            ),
            encoding="utf-8",
        )
        assert views.load_sidecar(file)["P::v"]["warp"] is True

    def test_foreign_files_are_rejected_not_clobbered(self, tmp_path):
        file = tmp_path / "views.json"
        file.write_text('{"something": "else"}', encoding="utf-8")
        with pytest.raises(SysMLError, match="not a 'longeron/views' sidecar"):
            views.load_sidecar(file)

    def test_bad_version_rejected(self, tmp_path):
        file = tmp_path / "views.json"
        file.write_text(
            '{"schema": "longeron/views", "version": "one", "views": {}}', encoding="utf-8"
        )
        with pytest.raises(SysMLError, match="unsupported sidecar version"):
            views.load_sidecar(file)

    def test_orphan_entries_pruned_on_write_with_a_model(self, tmp_path):
        model = rig_model()
        views.save_view(model, "Rig", name="kept")
        entries = {
            "Rig::kept": {"kind": "structure"},
            "Rig::deleted elsewhere": {"kind": "structure"},
        }
        file = views.save_sidecar(tmp_path, entries, model=model)
        assert list(views.load_sidecar(file)) == ["Rig::kept"]

    def test_save_view_writes_the_entry(self, tmp_path):
        model = rig_model()
        view = views.save_view(
            model,
            "Rig",
            name="axle structure",
            options={"direction": "down", "membership": "edges"},
            sidecar=tmp_path,
        )
        entry = views.load_sidecar(tmp_path)["Rig::axle structure"]
        assert entry["kind"] == "structure"
        assert entry["direction"] == "down"
        assert entry["options"] == {"membership": "edges"}
        # the elementId hint is the API projection's index-path UUID
        pytest.importorskip("pyecore")
        from longeron.ecore import to_spec

        spec = to_spec(model)
        assert entry["elementId"] == spec.instances[id(view)].elementId

    def test_sidecar_path_for_files_dirs_and_models(self, tmp_path):
        source = tmp_path / "rig.sysml"
        source.write_text(RIG, encoding="utf-8")
        expected = tmp_path / ".longeron" / "views.json"
        assert views.sidecar_path(source) == expected
        assert views.sidecar_path(tmp_path) == expected
        model = longeron.load(source)
        assert views.sidecar_path(model) == expected
        assert views.sidecar_path(rig_model()) is None  # in-memory model


# ---------------------------------------------------------------------------
# restore (needs the diagram toolchain)
# ---------------------------------------------------------------------------


class TestRestoreView:
    @pytest.fixture(autouse=True)
    def _needs_ipyelk(self):
        pytest.importorskip("ipyelk")

    def _node_ids(self, widget):
        def walk(node):
            yield node
            for child in node.children:
                yield from walk(child)

        return {str(node.id) for node in walk(widget.source.value) if node.id}

    def test_round_trip_save_then_restore(self):
        model = rig_model()
        views.save_view(model, "Rig", name="axle structure")
        widget = views.restore_view(model, "Rig::axle structure")
        state = widget._lgn_view_state
        assert state["kind"] == "structure"
        assert state["element"] is model.find("Rig")
        assert {"Rig", "Rig::Axle", "Rig::axle"} <= self._node_ids(widget)

    def test_typing_picks_the_builder(self):
        model = longeron.loads("""
        package P {
            state def Machine { entry; then idle; state idle; }
        }
        """)
        views.save_view(model, "P::Machine", name="machine view")
        widget = views.restore_view(model, "P::machine view")
        assert widget._lgn_view_state["kind"] == "state"
        assert widget._lgn_view_state["element"] is model.find("P::Machine")

    def test_sidecar_presentation_is_applied(self, tmp_path):
        model = rig_model()
        views.save_view(
            model,
            "Rig",
            name="axle structure",
            options={"direction": "down", "routing": "splines", "collapsed": ["Rig::Axle"]},
            sidecar=tmp_path,
        )
        widget = views.restore_view(model, "Rig::axle structure", sidecar=tmp_path)
        root = widget.source.value
        assert root.layoutOptions["elk.direction"] == "DOWN"
        assert root.layoutOptions["elk.edgeRouting"] == "SPLINES"
        axle = next(n for n in self._walk(root) if n.id == "Rig::Axle")
        assert axle.children and all(child.properties.hidden for child in axle.children)

    def _walk(self, node):
        yield node
        for child in node.children:
            yield from self._walk(child)

    def test_no_sidecar_means_default_presentation(self):
        # the degraded mode IS the standard mode
        model = rig_model()
        views.save_view(model, "Rig", name="axle structure")
        widget = views.restore_view(model, "Rig::axle structure")
        root = widget.source.value
        assert root.layoutOptions["elk.direction"] == "RIGHT"
        assert root.layoutOptions["elk.edgeRouting"] == "ORTHOGONAL"

    def test_sidecar_options_reach_the_builder(self, tmp_path):
        model = rig_model()
        views.save_view(
            model,
            "Rig",
            name="axle structure",
            options={"show_attributes": False},
            sidecar=tmp_path,
        )
        widget = views.restore_view(model, "Rig::axle structure", sidecar=tmp_path)
        assert widget._lgn_view_state["options"] == {"show_attributes": False}

    def test_unknown_sidecar_options_warn_and_drop(self):
        model = rig_model()
        views.save_view(model, "Rig", name="axle structure")
        entries = {
            "Rig::axle structure": {"kind": "structure", "options": {"chrome_flavor": "mint"}}
        }
        with pytest.warns(UserWarning, match="unknown sidecar option.*chrome_flavor"):
            widget = views.restore_view(model, "Rig::axle structure", sidecar=entries)
        assert widget is not None

    def test_unknown_view_definition_falls_back_with_a_warning(self):
        model = longeron.loads("""
        package P {
            view def Exotic;
            part a;
            view v : Exotic {
                expose P::a;
            }
        }
        """)
        with pytest.warns(UserWarning, match="unknown view definition"):
            widget = views.restore_view(model, "P::v")
        assert widget._lgn_view_state["kind"] == "structure"

    def test_untyped_view_uses_the_sidecar_kind(self):
        model = longeron.loads("""
        package P {
            state def Machine { entry; then idle; state idle; }
            view v {
                expose P::Machine;
            }
        }
        """)
        entries = {"P::v": {"kind": "state"}}
        widget = views.restore_view(model, "P::v", sidecar=entries)
        assert widget._lgn_view_state["kind"] == "state"

    def test_unrendered_rendering_falls_back_to_structure(self):
        model = longeron.loads("""
        package P {
            part a;
            view v {
                expose P::a;
                render Views::asElementTable;
            }
        }
        """)
        with pytest.warns(UserWarning, match="asElementTable"):
            widget = views.restore_view(model, "P::v")
        assert widget._lgn_view_state["kind"] == "structure"

    def test_fully_dangling_view_restores_empty_with_warnings(self):
        model = longeron.loads("package P { view v { expose P::gone; } }")
        with pytest.warns(UserWarning):
            widget = views.restore_view(model, "P::v")
        assert widget is not None  # an empty diagram, never an exception

    def test_multi_expose_view_draws_all_tops(self):
        model = rig_model()
        views.save_view(model, ["Rig::Axle", "Rig::Hub"], name="defs")
        widget = views.restore_view(model, "Rig::defs")
        ids = self._node_ids(widget)
        assert {"Rig::Axle", "Rig::Hub"} <= ids
        assert "Rig::axle" not in ids  # not exposed

    def test_not_a_view_rejected(self):
        with pytest.raises(SysMLError, match="not a view usage"):
            views.restore_view(rig_model(), "Rig::axle")

    def test_capture_presentation_round_trips_through_save(self, tmp_path):
        from longeron import diagrams

        model = rig_model()
        widget = diagrams.structure_diagram(model.find("Rig"), direction="down")
        captured = views.capture_presentation(widget)
        assert captured == {"direction": "down"}
        views.save_view(model, widget, name="axle structure", sidecar=tmp_path)
        entry = views.load_sidecar(tmp_path)["Rig::axle structure"]
        assert entry["direction"] == "down"
        restored = views.restore_view(model, "Rig::axle structure", sidecar=tmp_path)
        assert restored.source.value.layoutOptions["elk.direction"] == "DOWN"
