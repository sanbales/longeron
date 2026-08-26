"""Model editing (longeron.edit): the mutation seam UI inspectors use.

These tests pin the module's contract: every operation leaves the model
exporting to parseable text at a fixpoint, renames cascade into every
textual reference (typing, subsetting, redefining, expressions, satisfy,
expose, imports, aliases, connector ends, state-machine targets) or are
honestly refused, sibling order never changes (index-path element-id
stability), and the tracker seam records every change for the app layer.
"""

import pytest

import longeron
from longeron import edit
from longeron import model as M
from longeron.errors import EditError
from longeron.interpreter import Interpreter, Resolver

CASCADE = """
package P {
    part def Vehicle {
        attribute mass : Real = 100.0;
        part hub : Hub;
    }
    part def Hub;
    part v : Vehicle {
        attribute doubled : Real = 2 * mass;
    }
    part special :> v;
    requirement def MassReq;
    requirement massReq : MassReq;
    satisfy massReq by v;
    view w {
        expose P::Vehicle::**;
    }
    calc def Total {
        in vv : Vehicle;
        return : Real = vv.mass + P::Vehicle::mass;
    }
}
"""


def cascade_model():
    return longeron.loads(CASCADE)


def assert_fixpoint(model):
    """to_sysml reparses cleanly and re-exports byte-identically."""

    text = longeron.to_sysml(model)
    again = longeron.to_sysml(longeron.loads(text, source_name="<reprint>"))
    assert again == text, f"export is not a fixpoint:\n{text}"


def assert_resolves_clean(model):
    assert longeron.validate(model) == []


# ---------------------------------------------------------------------------
# rename: basics and input validation
# ---------------------------------------------------------------------------


class TestRenameBasics:
    def test_renames_and_returns_the_element(self):
        model = cascade_model()
        element = edit.rename(model, "P::Hub", "WheelHub")
        assert element is model.find("P::WheelHub")
        assert element.name == "WheelHub"
        assert model.find("P::Hub") is None

    def test_accepts_the_element_itself(self):
        model = cascade_model()
        hub = model.find("P::Hub")
        assert edit.rename(model, hub, "WheelHub") is hub

    def test_subtree_qualified_names_move_with_the_rename(self):
        model = cascade_model()
        mass = model.find("P::Vehicle::mass")
        edit.rename(model, "P::Vehicle", "Car")
        assert mass.qualified_name == "P::Car::mass"
        assert model.find("P::Car::mass") is mass

    def test_rename_to_same_name_is_a_noop(self):
        model = cascade_model()
        tracker = edit.track(model)
        edit.rename(model, "P::Hub", "Hub")
        assert tracker.changes == []

    def test_rename_can_name_an_anonymous_element(self):
        model = longeron.loads("package P { part a { part b; } }")
        part = model.find("P::a")
        part.name = None  # make it anonymous in place
        edit.rename(model, part, "renamed")
        assert part.qualified_name == "P::renamed"
        assert_fixpoint(model)

    def test_quoted_names_survive_the_round_trip(self):
        model = cascade_model()
        edit.rename(model, "P::Hub", "wheel hub")
        text = longeron.to_sysml(model)
        assert "part def 'wheel hub';" in text
        assert_fixpoint(model)
        assert_resolves_clean(model)

    @pytest.mark.parametrize("bad", ["", "A::B", "a.b", "$", "line\nbreak"])
    def test_illegal_names_are_refused(self, bad):
        model = cascade_model()
        with pytest.raises(EditError):
            edit.rename(model, "P::Hub", bad)
        assert model.find("P::Hub") is not None

    def test_sibling_collision_is_refused(self):
        model = cascade_model()
        with pytest.raises(EditError, match="already used"):
            edit.rename(model, "P::Hub", "Vehicle")

    def test_short_name_collision_is_refused(self):
        model = longeron.loads("package P { part <a> alpha; part beta; }")
        with pytest.raises(EditError, match="already used"):
            edit.rename(model, "P::beta", "a")

    def test_unknown_target_is_refused(self):
        model = cascade_model()
        with pytest.raises(EditError):
            edit.rename(model, "P::Nope", "Anything")

    def test_model_root_is_refused(self):
        model = cascade_model()
        with pytest.raises(EditError, match="model root"):
            edit.rename(model, model, "Root")

    def test_foreign_elements_are_refused(self):
        model = cascade_model()
        other = longeron.loads("package Q { part def X; }")
        with pytest.raises(EditError, match="not part of this model"):
            edit.rename(model, other.find("Q::X"), "Y")


# ---------------------------------------------------------------------------
# rename: the reference cascade
# ---------------------------------------------------------------------------


class TestRenameCascade:
    def test_definition_rename_rewrites_typing_expose_and_expressions(self):
        # the brief's pinned scenario: typing, expose, and expression
        # references (plain, chained through a typing, and fully
        # qualified) all follow the definition's new name
        model = cascade_model()
        edit.rename(model, "P::Vehicle", "Car")
        assert model.find("P::v").types == ["Car"]
        assert model.find("P::Total::vv").types == ["Car"]
        expose = next(m for m in model.find("P::w").members if isinstance(m, M.Expose))
        assert expose.target == "P::Car"
        result = next(
            m for m in model.find("P::Total").members if m.direction == "return"
        ).value.expr
        assert result.to_text() == "vv.mass + P::Car::mass"
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_usage_rename_rewrites_subsetting_and_satisfy_by(self):
        model = cascade_model()
        edit.rename(model, "P::v", "prototype")
        assert model.find("P::special").subsets == ["prototype"]
        satisfy = next(m for m in model.iter_tree() if isinstance(m, M.SatisfyUsage))
        assert satisfy.by == "prototype"
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_requirement_rename_rewrites_the_satisfy_reference(self):
        model = cascade_model()
        edit.rename(model, "P::massReq", "weightReq")
        satisfy = next(m for m in model.iter_tree() if isinstance(m, M.SatisfyUsage))
        assert satisfy.subsets == ["weightReq"]
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_feature_rename_rewrites_inherited_and_chained_references(self):
        model = cascade_model()
        edit.rename(model, "P::Vehicle::mass", "weight")
        doubled = model.find("P::v::doubled")
        assert doubled.value.expr.to_text() == "2 * weight"
        result = next(
            m for m in model.find("P::Total").members if m.direction == "return"
        ).value.expr
        assert result.to_text() == "vv.weight + P::Vehicle::weight"
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_package_rename_rewrites_qualified_references(self):
        model = cascade_model()
        edit.rename(model, "P", "Q")
        expose = next(m for m in model.find("Q::w").members if isinstance(m, M.Expose))
        assert expose.target == "Q::Vehicle"
        result = next(
            m for m in model.find("Q::Total").members if m.direction == "return"
        ).value.expr
        assert result.to_text() == "vv.mass + Q::Vehicle::mass"
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_import_and_alias_targets_are_rewritten(self):
        model = longeron.loads("""
        package Lib { part def Widget; }
        package App {
            import Lib::Widget;
            alias W for Lib::Widget;
            part w : Widget;
        }
        """)
        edit.rename(model, "Lib::Widget", "Gadget")
        imp = next(m for m in model.find("App").members if isinstance(m, M.Import))
        alias = next(m for m in model.find("App").members if isinstance(m, M.Alias))
        assert imp.target == "Lib::Gadget"
        assert alias.target == "Lib::Gadget"
        assert model.find("App::w").types == ["Gadget"]
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_connector_ends_follow_a_dotted_feature_rename(self):
        model = longeron.loads("""
        package P {
            part def Plug { port p; }
            part sys {
                part a : Plug;
                part b;
                connect a.p to b;
            }
        }
        """)
        edit.rename(model, "P::Plug::p", "outlet")
        connection = next(m for m in model.iter_tree() if isinstance(m, M.ConnectionUsage))
        assert [end.target for end in connection.ends] == ["a.outlet", "b"]
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_conjugated_port_typing_keeps_its_tilde(self):
        model = longeron.loads("""
        package P {
            port def PIn;
            part def Sys { port p : ~PIn; }
        }
        """)
        edit.rename(model, "P::PIn", "PowerIn")
        assert model.find("P::Sys::p").types == ["~PowerIn"]
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_state_rename_rewrites_transitions_and_entry(self):
        model = longeron.loads("""
        package P {
            state def Machine {
                entry; then idle;
                state idle;
                transition first idle if true then done;
                state done;
            }
        }
        """)
        edit.rename(model, "P::Machine::idle", "waiting")
        transitions = [
            m for m in model.find("P::Machine").members if isinstance(m, M.TransitionUsage)
        ]
        targets = {(t.source, t.target) for t in transitions}
        assert (M.ENTRY_SOURCE, "waiting") in targets
        assert ("waiting", "done") in targets
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_self_shadowing_redefinition_is_rewritten(self):
        # 'attribute mass :>> mass' -- the redefinition shadows the very
        # name it redefines; the reference must still follow the rename
        model = longeron.loads("""
        package P {
            part def Vehicle { attribute mass : Real = 1.0; }
            part named_redef : Vehicle {
                attribute mass :>> mass = 300.0;
            }
        }
        """)
        edit.rename(model, "P::Vehicle::mass", "weight")
        redefining = model.find("P::named_redef::mass")
        assert redefining.redefines == ["weight"]
        assert redefining.name == "mass"  # the local redeclaration keeps its name
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_short_name_references_are_left_alone(self):
        model = longeron.loads("""
        package P {
            part def <V> Vehicle;
            part v : V;
        }
        """)
        edit.rename(model, "P::Vehicle", "Car")
        assert model.find("P::v").types == ["V"]  # short name did not change
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_dependency_ends_are_rewritten(self):
        model = longeron.loads("""
        package P {
            part client;
            part supplier;
            dependency from client to supplier;
        }
        """)
        edit.rename(model, "P::supplier", "backend")
        dependency = next(m for m in model.iter_tree() if isinstance(m, M.Dependency))
        assert dependency.suppliers == ["backend"]
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_metadata_prefixes_typings_and_value_fields_are_rewritten(self):
        model = longeron.loads("""
        package P {
            metadata def Safety { attribute level : Real; }
            part def Vehicle;
            #Safety part v : Vehicle;
            @Safety about P::v {
                level = 3.0;
            }
        }
        """)
        edit.rename(model, "P::Safety", "SafetyLevel")
        assert model.find("P::v").metadata == ["SafetyLevel"]
        usage = next(m for m in model.iter_tree() if isinstance(m, M.MetadataUsage))
        assert usage.typed_by == "SafetyLevel"
        # the metadata value's field reference follows a field rename too
        edit.rename(model, "P::SafetyLevel::level", "severity")
        value = next(m for m in model.iter_tree() if isinstance(m, M.MetadataValue))
        assert value.redefines == "severity"
        assert_resolves_clean(model)
        assert_fixpoint(model)


# ---------------------------------------------------------------------------
# rename: honest refusal
# ---------------------------------------------------------------------------


class TestRenameRefusal:
    def test_dynamic_member_access_is_refused_with_the_sites(self):
        # (v, v)#(1).mass accesses 'mass' on a computed value; no static
        # rewrite can be proven correct, so the rename must refuse and
        # name the offending reference
        model = longeron.loads("""
        package P {
            part def Vehicle { attribute mass : Real = 100.0; }
            part v : Vehicle;
            part q { attribute z : Real = (v, v)#(1).mass; }
        }
        """)
        with pytest.raises(EditError, match=r"rename would break 1 reference.*P::q::z"):
            edit.rename(model, "P::Vehicle::mass", "weight")
        # honest refusal leaves the model untouched
        assert model.find("P::Vehicle::mass").name == "mass"
        assert_resolves_clean(model)

    def test_name_capture_is_rolled_back_and_refused(self):
        # renaming inner -> A would shadow P::A for the sibling typing
        # 'x : A'; the post-verification must catch the capture, roll the
        # model back, and refuse
        model = longeron.loads("""
        package P {
            part def A;
            part outer {
                part inner;
                part x : A;
            }
        }
        """)
        before = longeron.to_sysml(model)
        with pytest.raises(EditError, match="name capture"):
            edit.rename(model, "P::outer::inner", "A")
        assert longeron.to_sysml(model) == before
        assert model.find("P::outer::inner").name == "inner"
        assert_resolves_clean(model)

    def test_dangling_references_do_not_block_unrelated_renames(self):
        model = longeron.loads("""
        package P {
            part def Vehicle;
            part broken : Missing;
        }
        """)
        edit.rename(model, "P::Vehicle", "Car")
        assert model.find("P::broken").types == ["Missing"]  # still dangling, untouched
        assert_fixpoint(model)


# ---------------------------------------------------------------------------
# set_attribute_value
# ---------------------------------------------------------------------------


class TestSetAttributeValue:
    def test_sets_and_the_interpreter_evaluates(self):
        model = cascade_model()
        element = edit.set_attribute_value(model, "P::Vehicle::mass", "2 * 210.0")
        assert element is model.find("P::Vehicle::mass")
        instance = Interpreter(model).instantiate("P::Vehicle")
        assert instance.slots["mass"] == 420.0
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_preserves_the_default_flag(self):
        model = longeron.loads("package P { part def V { attribute x : Real default = 1.0; } }")
        edit.set_attribute_value(model, "P::V::x", "5.0")
        value = model.find("P::V::x").value
        assert value.is_default and not value.is_initial
        assert "default = 5.0" in longeron.to_sysml(model)
        assert_fixpoint(model)

    def test_preserves_the_initial_flag(self):
        model = longeron.loads("package P { action def A { attribute x : Real := 1.0; } }")
        edit.set_attribute_value(model, "P::A::x", "5.0")
        value = model.find("P::A::x").value
        assert value.is_initial and not value.is_default
        assert ":= 5.0" in longeron.to_sysml(model)
        assert_fixpoint(model)

    def test_creates_a_value_where_none_existed(self):
        model = longeron.loads("package P { part def V { attribute x : Real; } }")
        edit.set_attribute_value(model, "P::V::x", "3.0")
        value = model.find("P::V::x").value
        assert value is not None and not value.is_default and not value.is_initial
        assert_fixpoint(model)

    def test_none_clears_the_value(self):
        model = cascade_model()
        edit.set_attribute_value(model, "P::Vehicle::mass", None)
        assert model.find("P::Vehicle::mass").value is None
        assert "attribute mass : Real;" in longeron.to_sysml(model)
        assert_fixpoint(model)

    def test_bad_text_raises_with_the_parse_error(self):
        model = cascade_model()
        before = model.find("P::Vehicle::mass").value
        with pytest.raises(EditError, match="syntax error"):
            edit.set_attribute_value(model, "P::Vehicle::mass", "2 +")
        assert model.find("P::Vehicle::mass").value is before  # untouched

    def test_non_usage_targets_are_refused(self):
        model = cascade_model()
        with pytest.raises(EditError, match="not a usage"):
            edit.set_attribute_value(model, "P::Vehicle", "1.0")

    def test_unknown_targets_are_refused(self):
        model = cascade_model()
        with pytest.raises(EditError):
            edit.set_attribute_value(model, "P::Nope::x", "1.0")


# ---------------------------------------------------------------------------
# set_doc
# ---------------------------------------------------------------------------


class TestSetDoc:
    def test_creates_by_appending(self):
        model = cascade_model()
        vehicle = model.find("P::Vehicle")
        before = list(vehicle.members)
        doc = edit.set_doc(model, "P::Vehicle", "A road vehicle.")
        assert vehicle.members[: len(before)] == before  # siblings keep positions
        assert vehicle.members[-1] is doc
        assert vehicle.doc == "A road vehicle."
        assert_resolves_clean(model)
        assert_fixpoint(model)

    def test_updates_in_place(self):
        model = cascade_model()
        first = edit.set_doc(model, "P::Vehicle", "Draft.")
        vehicle = model.find("P::Vehicle")
        members = list(vehicle.members)
        second = edit.set_doc(model, "P::Vehicle", "Final.")
        assert second is first  # the same member, edited in place
        assert list(vehicle.members) == members
        assert vehicle.doc == "Final."
        assert_fixpoint(model)

    def test_multiline_text_round_trips_at_a_fixpoint(self):
        model = cascade_model()
        text = "A road vehicle.\n\nWith a second paragraph."
        edit.set_doc(model, "P::Vehicle", text)
        assert model.find("P::Vehicle").doc == text
        exported = longeron.to_sysml(model)
        reparsed = longeron.loads(exported)
        assert reparsed.find("P::Vehicle").doc == text
        assert_fixpoint(model)

    def test_none_removes_the_documentation(self):
        model = cascade_model()
        edit.set_doc(model, "P::Vehicle", "Temporary.")
        assert edit.set_doc(model, "P::Vehicle", None) is None
        assert model.find("P::Vehicle").doc is None
        assert_fixpoint(model)

    def test_comment_terminator_in_text_is_refused(self):
        model = cascade_model()
        with pytest.raises(EditError, match=r"\*/"):
            edit.set_doc(model, "P::Vehicle", "bad */ text")

    def test_non_namespace_targets_are_refused(self):
        model = longeron.loads("package P { import ScalarValues::Real; part def V; }")
        imp = next(m for m in model.find("P").members if isinstance(m, M.Import))
        with pytest.raises(EditError, match="only namespaces"):
            edit.set_doc(model, imp, "text")


# ---------------------------------------------------------------------------
# sibling-order stability (index-path element ids)
# ---------------------------------------------------------------------------


class TestSiblingStability:
    def test_rename_and_set_value_never_touch_member_lists(self):
        model = cascade_model()
        lists = {
            id(el): list(el.members) for el in model.iter_tree() if isinstance(el, M.Namespace)
        }
        edit.rename(model, "P::Vehicle", "Car")
        edit.set_attribute_value(model, "P::Car::mass", "7.0")
        for el in model.iter_tree():
            if isinstance(el, M.Namespace):
                assert lists[id(el)] == list(el.members)

    def test_set_doc_only_ever_appends(self):
        model = cascade_model()
        vehicle = model.find("P::Vehicle")
        before = list(vehicle.members)
        edit.set_doc(model, "P::Vehicle", "One.")
        edit.set_doc(model, "P::Vehicle", "Two.")
        assert vehicle.members[: len(before)] == before
        assert len(vehicle.members) == len(before) + 1


# ---------------------------------------------------------------------------
# change tracking
# ---------------------------------------------------------------------------


class TestTracker:
    def test_track_is_idempotent(self):
        model = cascade_model()
        assert edit.track(model) is edit.track(model)

    def test_dirty_flips_and_changes_accumulate(self):
        model = cascade_model()
        tracker = edit.track(model)
        assert not tracker.dirty
        edit.rename(model, "P::Hub", "WheelHub")
        edit.set_attribute_value(model, "P::Vehicle::mass", "7.0")
        edit.set_doc(model, "P::Vehicle", "A vehicle.")
        assert tracker.dirty
        assert [c.op for c in tracker.changes] == ["rename", "set_value", "set_doc"]

    def test_changes_unpack_as_tuples(self):
        model = cascade_model()
        tracker = edit.track(model)
        edit.rename(model, "P::Hub", "WheelHub")
        op, qname, detail = tracker.changes[0]
        assert (op, qname) == ("rename", "P::WheelHub")
        assert detail["old_qname"] == "P::Hub"
        assert detail["new_name"] == "WheelHub"

    def test_rename_detail_counts_rewrites(self):
        model = cascade_model()
        tracker = edit.track(model)
        edit.rename(model, "P::Vehicle", "Car")
        detail = tracker.changes[0].detail
        # v typing, vv typing, the expose, and the qualified expression
        assert detail["rewritten"] == 4

    def test_callback_fires_per_change(self):
        model = cascade_model()
        tracker = edit.track(model)
        seen = []
        tracker.on_change(seen.append)
        edit.set_doc(model, "P::Vehicle", "A vehicle.")
        assert [c.op for c in seen] == ["set_doc"]
        assert seen == tracker.changes

    def test_mark_saved_clears_and_edits_redirty(self):
        model = cascade_model()
        tracker = edit.track(model)
        edit.set_doc(model, "P::Vehicle", "A vehicle.")
        tracker.mark_saved()
        assert not tracker.dirty and tracker.changes == []
        edit.set_doc(model, "P::Vehicle", "Again.")
        assert tracker.dirty and len(tracker.changes) == 1

    def test_untrack_stops_recording(self):
        model = cascade_model()
        tracker = edit.track(model)
        edit.untrack(model)
        edit.set_doc(model, "P::Vehicle", "A vehicle.")
        assert tracker.changes == []

    def test_untracked_models_record_nothing(self):
        model = cascade_model()
        edit.set_doc(model, "P::Vehicle", "A vehicle.")  # must not raise
        assert model.find("P::Vehicle").doc == "A vehicle."

    def test_value_detail_carries_old_and_new_text(self):
        model = cascade_model()
        tracker = edit.track(model)
        edit.set_attribute_value(model, "P::Vehicle::mass", "7.0")
        detail = tracker.changes[0].detail
        assert detail == {"text": "7.0", "previous": "100.0"}


# ---------------------------------------------------------------------------
# the round-trip guarantee, end to end
# ---------------------------------------------------------------------------


class TestRoundTripGuarantee:
    def test_every_operation_keeps_the_export_at_a_fixpoint(self):
        model = cascade_model()
        edit.rename(model, "P::Vehicle", "Car")
        edit.rename(model, "P::Car::mass", "weight")
        edit.set_attribute_value(model, "P::Car::weight", "123.0")
        edit.set_doc(model, "P::Car", "Line one.\nLine two.")
        assert_fixpoint(model)
        assert_resolves_clean(model)
        resolver = Resolver(model)
        assert resolver.resolve("P::Car::weight") is model.find("P::Car::weight")

    def test_edited_model_survives_a_full_reparse_with_meaning_intact(self):
        model = cascade_model()
        edit.rename(model, "P::Vehicle::mass", "weight")
        edit.set_attribute_value(model, "P::Vehicle::weight", "50.0")
        reparsed = longeron.loads(longeron.to_sysml(model))
        doubled = Interpreter(reparsed).instantiate("P::v").slots["doubled"]
        assert doubled == 100.0
