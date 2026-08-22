"""Coverage tests for constructs added in the full-coverage pass:
interfaces, views, flows, allocations, metadata, satisfy/verify/frame,
filtered imports.  All of them must build (no Unsupported) and round-trip.

The second wave (`GRAMMAR_COVERAGE_SOURCES`) extends the corpus to the
remaining grammar surface: case bodies (subject/actor/objective), exhibit
states, inline perform actions, event occurrences, individual/portion
usages, variant references, initial/control nodes, annotations, target
transitions, state actions, and expression forms.
"""

import pytest

import longeron
from longeron import model as M

FULL_COVERAGE_SOURCES = [
    """
    package Interfaces {
        interface def Plug {
            end p1 : PA;
            end p2 : PB;
            attribute voltage : Real = 12.0;
        }
        part sys {
            part a; part b;
            interface i1 : Plug connect a to b;
            interface p1 to p2;
        }
    }
    """,
    """
    package Views {
        view def TreeView {
            filter @Safety;
            render rendering treeRend : TreeR;
        }
        view myView : TreeView {
            expose Pkg::*;
            expose Other::Thing;
            expose Deep::**[@Safety];
            filter @Safety and @Critical;
            render asTree;
        }
        rendering asTree : TreeR;
        viewpoint safetyView {
            require constraint { true }
        }
    }
    """,
    """
    package Flows {
        part sys {
            part pump; part tank;
            flow of fluid : Water from pump.outlet to tank.inlet;
            flow pump.outlet to tank.inlet;
            succession flow f2 from pump.trigger to tank.handler;
            message notify of Alert from sendEvt to recvEvt;
            message startEvt to doneEvt;
        }
    }
    """,
    """
    package Allocations {
        part logical { part fn1; }
        part physical { part cpu1; }
        allocation def Deploy;
        part ctx {
            allocation d1 : Deploy allocate logical.fn1 to physical.cpu1;
            allocate logical to physical;
        }
    }
    """,
    """
    package Meta {
        metadata def Safety { attribute level : Integer; }
        #Safety part def Critical;
        @Safety { level = 3; }
        metadata s2 : Safety about Critical;
        @Safety { level = 4; nested { deep = true; } }
        part widget { @Safety { level = 1; } }
        #command def RunIt;
        #command runIt2;
        #Safety dependency Client from a to b;
        enum def Level {
            uncl : Level = 0;
            #Safety enum secret : Level = 2;
        }
    }
    """,
    """
    package Reqs {
        requirement def R1 { subject s; require constraint { true } }
        requirement r2 : R1 {
            frame concern perf : Performance;
            verify requirement checkIt { require constraint { true } }
            verify existingVerification;
            frame framedConcern;
        }
        part system {
            satisfy R1 by system;
            assert satisfy r2;
            assert not satisfy R1 by system;
        }
        use case def Operate;
        use case op1 : Operate {
            include useIt : Operate;
            include Operate;
        }
    }
    """,
    """
    package Filtered {
        private import Lib::*[@Safety];
        import Deep::**;
        filter @Safety;
    }
    """,
]

CASES_SOURCE = """
package Cases {
    part def Robot;
    part def Operator;
    use case def Wash {
        subject vehicle : Robot;
        actor driver : Operator;
        objective goal { require constraint { true } }
    }
    analysis def Measure {
        subject uut : Robot;
        objective { require constraint { true } }
        return score : Real;
    }
    analysis runIt : Measure;
    verification def CheckMass {
        subject dut : Robot;
        objective verifyMass { verify requirement massReq; }
    }
    verification check1 : CheckMass;
    case def Generic {
        subject thing : Robot;
        thing == thing
    }
    case g1 : Generic;
    use case wash1 : Wash {
        subject v2 : Robot;
    }
}
"""

EXHIBITS_SOURCE = """
package Exhibits {
    state def Mode { state idle; state busy; }
    part robot {
        exhibit state currentMode : Mode {
            entry; then idle;
            state idle;
            state busy;
        }
        exhibit mainMode;
    }
}
"""

PERFORMS_SOURCE = """
package Performs {
    action def Move { in speed : Real; }
    part arm {
        perform action goHome : Move {
            in speed : Real = 1.0;
        }
        perform selfTest;
        perform action reset;
    }
}
"""

EVENTS_SOURCE = """
package Events {
    occurrence def Startup;
    part sys {
        event occurrence boot : Startup;
        event occurrence shutdown;
        event boot;
    }
}
"""

INDIVIDUALS_SOURCE = """
package Individuals {
    part def Car;
    individual def Vin123 :> Car;
    individual part car1 : Vin123;
    snapshot part carNow : Vin123;
    timeslice part carTrip : Vin123;
    individual snapshot part carThen : Vin123;
}
"""

VARIANTS_SOURCE = """
package Variants {
    part def Wheel;
    part def SteelWheel :> Wheel;
    part def AlloyWheel :> Wheel;
    part steel : SteelWheel;
    part alloy : AlloyWheel;
    variation part wheelChoices : Wheel {
        variant steel;
        variant alloy;
    }
    variation part def WheelKind {
        variant part steelK : SteelWheel;
    }
}
"""

INITIAL_NODES_SOURCE = """
package Initials {
    action def Sequence {
        action step1;
        action step2;
        first step1;
        first step1 then step2;
    }
}
"""

META_EXPRS_SOURCE = """
package MetaExprs {
    metadata def Safety;
    part def Widget;
    attribute isMeta : Boolean = Widget.metadata @@ Safety;
    attribute castMeta = Widget.metadata meta Safety;
    attribute everything = all Widget;
}
"""

IFACE_DEFS_SOURCE = """
package IfaceDefs {
    interface def Plug {
        part def Inner;
        attribute voltage : Real;
        end a : Inner;
    }
}
"""

BEHAVIOR_CONSTRAINTS_SOURCE = """
package BehaviorConstraints {
    action def Guarded {
        in x : Real;
        constraint c1 { x > 0.0 }
        assert constraint { x < 100.0 }
    }
}
"""

ANNOTATIONS_SOURCE = """
package Annotations {
    part def Thing;
    part def Consumer;
    alias TheThing for Thing;
    comment note1 about Thing locale "en" /* a note about Thing */
    comment /* an anonymous comment */
    doc intro locale "en" /* package documentation */
    rep raw language "text" /* opaque body */
    dependency Uses from Consumer to Thing;
}
"""

CONTROL_NODES_SOURCE = """
package ControlNodes {
    action def Branchy {
        in x : Real;
        action a1;
        action a2;
        decide d1;
        merge m1;
        fork f1;
        join j1;
        first a1 if x > 0.0 then a2;
        succession s1 first a1 then a2;
    }
}
"""

TARGET_TRANSITIONS_SOURCE = """
package TargetTransitions {
    attribute def TurnOn;
    part lamp;
    state def Power {
        entry; then off;
        state off;
        accept TurnOn then on;
        state on;
        transition if true do send TurnOn() to lamp then off;
    }
}
"""

STATE_ACTIONS_SOURCE = """
package StateActions {
    attribute def Ping;
    part def Target;
    state def Machine {
        attribute count : Integer := 0;
        entry assign count := 0;
        do send Ping() to Machine;
        exit cleanup;
        state working {
            entry action step;
        }
    }
}
"""

EXPR_FORMS_SOURCE = """
package ExprForms {
    part def Point { attribute x : Real; }
    calc def Plus { in a : Real; in b : Real; return : Real = a + b; }
    attribute made : Point = new Point(x = 1.0);
    attribute total : Real = (1.0, 2.0, 3.0)->reduce max;
    attribute plussed : Real = Plus(a = 1.0, b = 2.0);
    attribute second : Real = (10.0, 20.0)#(2);
    attribute qty : Real = 9.81 ['m/s2'];
    attribute escaped : String = "line\\nbreak \\"quoted\\"";
    attribute singleton = (5,);
    attribute casted : Integer = 2.9 as Integer;
    attribute star : Real = *;
    attribute picked = (1, 2, 3, 4)->select { in v; v % 2 == 0 };
    attribute doubled = (1, 2, 3).{ in v; v * 2 };
    attribute filtered = (1, 2, 3).?{ in v; v >= 2 };
}
"""

EXTENDED_DEFS_SOURCE = """
package ExtendedDefs {
    metadata def Tag;
    abstract metadata def AbstractTag;
    abstract #Tag def Zork;
    enum def Level {
        doc /* severity levels */
        low;
        high;
    }
    part def Thing;
    part singleThing : Thing;
    private import ExtendedDefs::singleThing;
}
"""

STATE_FLOW_SOURCE = """
package StateFlow {
    attribute def Sig;
    part lamp;
    state def Power {
        attribute ready : Boolean := true;
        entry; if ready then off;
        state off;
        state on;
        transition t1 first off accept Sig then on;
    }
    action def Flow {
        in x : Real;
        action a1;
        then a2;
        action a2;
        else a3;
        action a3;
        action a4 {
            assign x := x + 1.0;
        }
        send Sig() via lamp to lamp;
    }
}
"""

IFACE_REQ_VIEW_SOURCE = """
package IfaceReqView {
    part def Conn;
    interface def Bus {
        end left : Conn;
        part relay;
        flow left to relay;
        attribute rate : Real = 1.0;
    }
    requirement def Spec {
        subject sys : Conn;
        val : Real = 2.0;
        stakeholder owner;
    }
    view v1 {
        expose IfaceReqView::*;
        satisfy Spec;
    }
}
"""

LIBRARY_FLAGS_SOURCE = """
standard library package LibraryFlags {
    part def Thing;
    attribute count : Integer default := 3;
    part rack : Thing[2..8] ordered nonunique;
    ref observer ::> rack;
    part def Box {
        attribute t : Real = 1.0;
        assert not constraint cool { t > 100.0 }
    }
    ref part spareBox : Box;
}
"""

CONNECT_ACCEPT_SOURCE = """
package ConnectAccept {
    part def Plug; part a; part b; part c;
    connection def Link;
    connection tri : Link connect (pa ::> a, pb ::> b, pc ::> c);
    binding namedBind bind a = b;
    action def Watch {
        in limit : Real;
        accept at 5.0;
        accept after 1.0 via a;
        accept when limit > 2.0;
        if limit > 3.0 {
            assign limit := 3.0;
        } else {
            assign limit := 0.0;
        }
        loop {
            assign limit := limit + 1.0;
        } until limit > 2.0;
        terminate a;
    }
    state def Guarded {
        entry; then off;
        state off;
        transition first off if true do doReset then on;
        state on;
        action doReset;
    }
}
"""

GRAMMAR_COVERAGE_SOURCES = [
    CASES_SOURCE,
    EXHIBITS_SOURCE,
    PERFORMS_SOURCE,
    EVENTS_SOURCE,
    INDIVIDUALS_SOURCE,
    VARIANTS_SOURCE,
    INITIAL_NODES_SOURCE,
    META_EXPRS_SOURCE,
    IFACE_DEFS_SOURCE,
    BEHAVIOR_CONSTRAINTS_SOURCE,
    ANNOTATIONS_SOURCE,
    CONTROL_NODES_SOURCE,
    TARGET_TRANSITIONS_SOURCE,
    STATE_ACTIONS_SOURCE,
    EXPR_FORMS_SOURCE,
    EXTENDED_DEFS_SOURCE,
    STATE_FLOW_SOURCE,
    IFACE_REQ_VIEW_SOURCE,
    LIBRARY_FLAGS_SOURCE,
    CONNECT_ACCEPT_SOURCE,
]

FULL_COVERAGE_SOURCES += GRAMMAR_COVERAGE_SOURCES


@pytest.mark.parametrize("source", FULL_COVERAGE_SOURCES)
def test_no_unsupported(source):
    model = longeron.loads(source)
    leftovers = [e for e in model.iter_tree() if isinstance(e, M.Unsupported)]
    assert not leftovers, f"unsupported: {[u.rule for u in leftovers]}"


@pytest.mark.parametrize("source", FULL_COVERAGE_SOURCES)
def test_round_trip(source):
    model1 = longeron.loads(source)
    text = longeron.to_sysml(model1)
    model2 = longeron.loads(text, source_name="<reprint>")
    d1, d2 = longeron.to_dict(model1), longeron.to_dict(model2)
    d1.pop("source_name", None)
    d2.pop("source_name", None)
    assert d1 == d2, f"round-trip mismatch for:\n{text}"


def test_interface_structure():
    model = longeron.loads(FULL_COVERAGE_SOURCES[0])
    i1 = model.find("Interfaces::sys::i1")
    assert isinstance(i1, M.InterfaceUsage)
    assert i1.types == ["Plug"]
    assert [e.target for e in i1.ends] == ["a", "b"]


def test_flow_structure():
    model = longeron.loads(FULL_COVERAGE_SOURCES[2])
    sys_part = model.find("Flows::sys")
    flows = [m for m in sys_part.members if isinstance(m, M.FlowUsage)]
    assert flows[0].payload == "fluid : Water"
    assert flows[0].source == "pump.outlet"
    assert flows[0].target_end == "tank.inlet"
    assert flows[2].is_succession
    assert flows[3].kind == "message"


def test_metadata_structure():
    model = longeron.loads(FULL_COVERAGE_SOURCES[4])
    pkg = model.find("Meta")
    annotations = [m for m in pkg.members if isinstance(m, M.MetadataUsage)]
    assert annotations[0].typed_by == "Safety"
    values = [m for m in annotations[0].members if isinstance(m, M.MetadataValue)]
    assert values[0].redefines == "level"
    assert values[0].value.expr.to_text() == "3"
    critical = pkg.find("Critical")
    assert critical.metadata == ["Safety"]


def test_satisfy_structure():
    model = longeron.loads(FULL_COVERAGE_SOURCES[5])
    system = model.find("Reqs::system")
    satisfies = [m for m in system.members if isinstance(m, M.SatisfyUsage)]
    assert satisfies[0].subsets == ["R1"]
    assert satisfies[0].by == "system"
    assert satisfies[1].is_assert
    assert satisfies[2].is_negated


def test_filtered_import():
    model = longeron.loads(FULL_COVERAGE_SOURCES[6])
    imports = [m for m in model.find("Filtered").members if isinstance(m, M.Import)]
    assert imports[0].filters and imports[0].filters[0].to_text() == "@Safety"
    assert imports[1].is_recursive


def test_filtered_expose():
    # regression: 'expose X::**[@F];' crashed the builder (filterPackage
    # alternative was only handled for regular imports)
    model = longeron.loads(FULL_COVERAGE_SOURCES[1])
    view = model.find("Views::myView")
    exposes = [m for m in view.members if isinstance(m, M.Expose)]
    assert exposes[0].is_namespace and not exposes[0].filters
    assert exposes[2].is_recursive and not exposes[2].is_namespace
    assert exposes[2].target == "Deep"
    assert exposes[2].filters[0].to_text() == "@Safety"


# -- grammar-corpus structural assertions -------------------------------------


class TestCaseBodies:
    def test_use_case_subject_actor_objective(self):
        model = longeron.loads(CASES_SOURCE)
        wash = model.find("Cases::Wash")
        subject = wash.member_named("vehicle")
        assert subject.kind == "subject" and subject.types == ["Robot"]
        actor = wash.member_named("driver")
        assert actor.kind == "actor" and actor.types == ["Operator"]
        goal = wash.member_named("goal")
        assert goal.kind == "objective"
        inner = [m for m in goal.members if isinstance(m, M.Usage) and m.kind == "constraint"]
        assert inner[0].constraint_kind == "require"

    def test_analysis_return_parameter(self):
        model = longeron.loads(CASES_SOURCE)
        measure = model.find("Cases::Measure")
        score = measure.member_named("score")
        assert score.direction == "return" and score.types == ["Real"]
        assert model.find("Cases::runIt").types == ["Measure"]

    def test_case_result_expression(self):
        model = longeron.loads(CASES_SOURCE)
        generic = model.find("Cases::Generic")
        assert generic.result is not None
        assert generic.result.to_text() == "thing == thing"

    def test_verification_objective_declares_requirement(self):
        model = longeron.loads(CASES_SOURCE)
        objective = model.find("Cases::CheckMass").member_named("verifyMass")
        assert objective.kind == "objective"
        verifies = [m for m in objective.members if isinstance(m, M.Usage) and m.kind == "verify"]
        # 'verify requirement massReq;' *declares* the verified requirement
        assert verifies[0].name == "massReq" and verifies[0].subsets == []


class TestExhibitStates:
    def test_exhibit_with_own_declaration(self):
        model = longeron.loads(EXHIBITS_SOURCE)
        current = model.find("Exhibits::robot").member_named("currentMode")
        assert current.kind == "state" and current.is_exhibit
        assert current.types == ["Mode"]
        states = [m.name for m in current.members if isinstance(m, M.Usage) and m.kind == "state"]
        assert states == ["idle", "busy"]
        entry = next(t for t in current.members if isinstance(t, M.TransitionUsage))
        assert entry.source == M.ENTRY_SOURCE and entry.target == "idle"

    def test_exhibit_reference_form(self):
        model = longeron.loads(EXHIBITS_SOURCE)
        robot = model.find("Exhibits::robot")
        ref = next(
            m for m in robot.members if isinstance(m, M.Usage) and m.kind == "state" and m.subsets
        )
        assert ref.is_exhibit and ref.subsets == ["mainMode"]


class TestPerformActions:
    def test_inline_and_reference_forms(self):
        model = longeron.loads(PERFORMS_SOURCE)
        arm = model.find("Performs::arm")
        performs = [m for m in arm.members if isinstance(m, M.PerformAction)]
        inline = performs[0]
        assert inline.action is not None
        assert inline.action.name == "goHome" and inline.action.types == ["Move"]
        speed = inline.action.member_named("speed")
        assert speed.direction == "in"
        assert speed.value.expr.to_text() == "1.0"
        assert performs[1].target == "selfTest" and performs[1].action is None
        assert performs[2].action is not None and performs[2].action.name == "reset"


class TestEventOccurrences:
    def test_declared_and_reference_forms(self):
        model = longeron.loads(EVENTS_SOURCE)
        sys_part = model.find("Events::sys")
        events = [
            m
            for m in sys_part.members
            if isinstance(m, M.Usage) and m.kind in ("event", "event_occurrence")
        ]
        assert events[0].kind == "event_occurrence"
        assert events[0].name == "boot" and events[0].types == ["Startup"]
        assert events[1].kind == "event_occurrence" and events[1].name == "shutdown"
        assert events[2].kind == "event" and events[2].subsets == ["boot"]


class TestIndividualsAndPortions:
    def test_flags(self):
        model = longeron.loads(INDIVIDUALS_SOURCE)
        vin = model.find("Individuals::Vin123")
        assert vin.is_individual and vin.supers == ["Car"]
        assert model.find("Individuals::car1").is_individual
        now = model.find("Individuals::carNow")
        assert now.portion_kind == "snapshot" and not now.is_individual
        assert model.find("Individuals::carTrip").portion_kind == "timeslice"
        then = model.find("Individuals::carThen")
        assert then.is_individual and then.portion_kind == "snapshot"


class TestVariantReferences:
    def test_reference_and_declared_variants(self):
        model = longeron.loads(VARIANTS_SOURCE)
        choices = model.find("Variants::wheelChoices")
        assert choices.is_variation
        refs = [m for m in choices.members if isinstance(m, M.Usage) and m.is_variant]
        assert [r.subsets for r in refs] == [["steel"], ["alloy"]]
        assert all(r.kind == "ref" for r in refs)
        declared = next(
            m
            for m in model.find("Variants::WheelKind").members
            if isinstance(m, M.Usage) and m.is_variant
        )
        assert declared.name == "steelK" and declared.types == ["SteelWheel"]


class TestInitialNodes:
    def test_first_and_target_succession(self):
        model = longeron.loads(INITIAL_NODES_SOURCE)
        seq = model.find("Initials::Sequence")
        firsts = [m for m in seq.members if isinstance(m, M.InitialNode)]
        assert [f.target for f in firsts] == ["step1"]
        succession = next(m for m in seq.members if isinstance(m, M.Succession))
        assert succession.source == "step1" and succession.target == "step2"


class TestMetaclassificationExpressions:
    def test_expression_forms(self):
        model = longeron.loads(META_EXPRS_SOURCE)
        pkg = model.find("MetaExprs")
        texts = {
            m.name: m.value.expr.to_text()
            for m in pkg.members
            if isinstance(m, M.Usage) and m.value is not None
        }
        assert texts["isMeta"] == "Widget.metadata @@ Safety"
        assert texts["castMeta"] == "Widget.metadata meta Safety"
        assert texts["everything"] == "all Widget"


class TestInterfaceBodyDefinitions:
    def test_nested_definition_and_end(self):
        model = longeron.loads(IFACE_DEFS_SOURCE)
        plug = model.find("IfaceDefs::Plug")
        inner = plug.member_named("Inner")
        assert isinstance(inner, M.Definition) and inner.kind == "part"
        end = plug.member_named("a")
        assert end.is_end and end.types == ["Inner"]


class TestBehaviorBodyConstraints:
    def test_constraints_inside_action_def(self):
        model = longeron.loads(BEHAVIOR_CONSTRAINTS_SOURCE)
        guarded = model.find("BehaviorConstraints::Guarded")
        constraints = [
            m for m in guarded.members if isinstance(m, M.Usage) and m.kind == "constraint"
        ]
        assert constraints[0].name == "c1"
        assert constraints[0].result.to_text() == "x > 0.0"
        assert constraints[1].constraint_kind == "assert"
        assert constraints[1].result.to_text() == "x < 100.0"


class TestAnnotationElements:
    def test_alias_comment_doc_rep_dependency(self):
        model = longeron.loads(ANNOTATIONS_SOURCE)
        pkg = model.find("Annotations")
        alias = next(m for m in pkg.members if isinstance(m, M.Alias))
        assert alias.name == "TheThing" and alias.target == "Thing"
        comments = [m for m in pkg.members if isinstance(m, M.Comment)]
        assert comments[0].name == "note1"
        assert comments[0].about == ["Thing"] and comments[0].locale == "en"
        assert "a note about Thing" in comments[0].text
        assert comments[1].name is None and "anonymous" in comments[1].text
        doc = next(m for m in pkg.members if isinstance(m, M.Documentation))
        assert doc.name == "intro" and doc.locale == "en"
        rep = next(m for m in pkg.members if isinstance(m, M.TextualRepresentation))
        assert rep.language == "text" and "opaque body" in rep.body
        dep = next(m for m in pkg.members if isinstance(m, M.Dependency))
        assert dep.name == "Uses"
        assert dep.clients == ["Consumer"] and dep.suppliers == ["Thing"]


class TestControlNodes:
    def test_nodes_and_successions(self):
        model = longeron.loads(CONTROL_NODES_SOURCE)
        act = model.find("ControlNodes::Branchy")
        nodes = {m.name: m.kind for m in act.members if isinstance(m, M.ControlNode)}
        assert nodes == {"d1": "decision", "m1": "merge", "f1": "fork", "j1": "join"}
        successions = [m for m in act.members if isinstance(m, M.Succession)]
        guarded = next(s for s in successions if s.guard is not None)
        assert guarded.source == "a1" and guarded.target == "a2"
        assert guarded.guard.to_text() == "x > 0.0"
        named = next(s for s in successions if s.name)
        assert named.name == "s1" and (named.source, named.target) == ("a1", "a2")


class TestTargetTransitions:
    def test_trigger_guard_effect_in_target_position(self):
        model = longeron.loads(TARGET_TRANSITIONS_SOURCE)
        power = model.find("TargetTransitions::Power")
        transitions = [m for m in power.members if isinstance(m, M.TransitionUsage)]
        entry = transitions[0]
        assert entry.source == M.ENTRY_SOURCE and entry.target == "off"
        accepting = next(t for t in transitions if t.trigger is not None)
        assert (accepting.source, accepting.target) == ("off", "on")
        assert accepting.trigger.payload_types == ["TurnOn"]
        effecting = next(t for t in transitions if t.effect is not None)
        assert (effecting.source, effecting.target) == ("on", "off")
        assert effecting.guard is not None and effecting.guard.to_text() == "true"
        assert isinstance(effecting.effect, M.SendAction)


class TestStateActions:
    def test_entry_do_exit_bodies(self):
        model = longeron.loads(STATE_ACTIONS_SOURCE)
        machine = model.find("StateActions::Machine")
        actions = {a.kind: a for a in machine.members if isinstance(a, M.StateAction)}
        assert isinstance(actions["entry"].action, M.AssignmentAction)
        assert isinstance(actions["do"].action, M.SendAction)
        assert isinstance(actions["exit"].action, M.PerformAction)
        assert actions["exit"].action.target == "cleanup"
        working = machine.member_named("working")
        inner = next(a for a in working.members if isinstance(a, M.StateAction))
        assert inner.action.action is not None  # inline 'entry action step;'
        assert inner.action.action.name == "step"


class TestExpressionForms:
    def test_values_evaluate(self):
        model = longeron.loads(EXPR_FORMS_SOURCE)
        interp = longeron.Interpreter(model)

        def ev(name):
            return interp.evaluate(name, context="ExprForms")

        made = ev("made")
        assert isinstance(made, longeron.Instance) and made.slots["x"] == 1.0
        assert ev("total") == 3.0  # ->reduce with a *named* builtin function
        assert ev("plussed") == 3.0  # user calc invoked with named arguments
        assert ev("second") == 20.0
        assert ev("qty") == pytest.approx(9.81)
        assert ev("escaped") == 'line\nbreak "quoted"'
        assert ev("singleton") == [5]
        assert ev("casted") == 2
        assert ev("picked") == [2, 4]
        assert ev("doubled") == [2, 4, 6]
        assert ev("filtered") == [2, 3]

    def test_reduce_with_user_function_is_rejected(self):
        # pins the current contract: ->reduce only takes builtin functions;
        # a user-defined calc raises instead of silently mis-evaluating
        model = longeron.loads(EXPR_FORMS_SOURCE)
        interp = longeron.Interpreter(model)
        with pytest.raises(longeron.EvaluationError, match="->reduce Plus is not supported"):
            interp.evaluate("(1.0, 2.0)->reduce Plus", context="ExprForms")


# -- exporter projections over the grammar corpus ------------------------------


@pytest.mark.parametrize(
    "source",
    [s for s in GRAMMAR_COVERAGE_SOURCES if s is not CASES_SOURCE],
)
def test_kerml_projection_parses(source):
    model = longeron.loads(source)
    text = longeron.to_kerml(model)
    result = longeron.parse_kerml_text(text)
    assert result.language == "kerml"


def test_rdf_projection_of_annotations():
    rdflib = pytest.importorskip("rdflib")
    from longeron import rdf

    model = longeron.loads(ANNOTATIONS_SOURCE)
    graph = rdf.to_graph(model)
    ns = rdflib.Namespace(rdf.VOCABULARY)
    thing = rdflib.URIRef(rdf.ELEMENT_BASE + "Annotations/Thing")
    consumer = rdflib.URIRef(rdf.ELEMENT_BASE + "Annotations/Consumer")
    alias = rdflib.URIRef(rdf.ELEMENT_BASE + "Annotations/TheThing")
    assert (alias, ns.aliasFor, thing) in graph
    # 'comment about Thing' annotates its *target*, not the package
    comments = list(graph.objects(thing, rdflib.RDFS.comment))
    assert any("a note about Thing" in str(c) for c in comments)
    deps = list(graph.subjects(ns.client, consumer))
    assert len(deps) == 1
    assert (deps[0], ns.supplier, thing) in graph


def test_ecore_projection_of_annotations():
    pytest.importorskip("pyecore")
    from longeron import ecore

    model = longeron.loads(ANNOTATIONS_SOURCE)
    result = ecore.to_spec(model)
    by_class: dict[str, list] = {}
    for instance in result.all_instances():
        by_class.setdefault(instance.eClass.name, []).append(instance)
    assert "Comment" in by_class
    assert any("a note about Thing" in (c.body or "") for c in by_class["Comment"])
    reps = by_class["TextualRepresentation"]
    assert reps[0].language == "text"
    assert "Dependency" in by_class


# -- documented src bugs found while building this corpus ----------------------
# (fixed in 0.7.1: these formerly-skipped tests now pin the corrected behavior)


def test_bare_individual_usage_round_trip():
    source = """
    package Bare {
        part def Car;
        individual def Vin123 :> Car;
        individual car1 : Vin123;
        snapshot carNow : Vin123;
        timeslice carTrip : Vin123;
    }
    """
    model1 = longeron.loads(source)
    text = longeron.to_sysml(model1)
    model2 = longeron.loads(text, source_name="<reprint>")
    d1, d2 = longeron.to_dict(model1), longeron.to_dict(model2)
    d1.pop("source_name", None)
    d2.pop("source_name", None)
    assert d1 == d2


def test_variant_reference_with_specialization_round_trip():
    source = """
    package V {
        part def Wheel;
        part def SteelWheel :> Wheel;
        part steel : SteelWheel;
        variation part choices : Wheel {
            variant steel : SteelWheel;
        }
    }
    """
    model1 = longeron.loads(source)
    assert model1.find("V::choices").members[0].types == ["SteelWheel"]
    text = longeron.to_sysml(model1)
    model2 = longeron.loads(text, source_name="<reprint>")
    assert model2.find("V::choices").members[0].types == ["SteelWheel"]


def test_state_entry_inline_action_body_round_trip():
    source = """
    package S {
        state def Machine {
            state working {
                entry action step { in n : Real; }
            }
        }
    }
    """
    model1 = longeron.loads(source)
    text = longeron.to_sysml(model1)
    model2 = longeron.loads(text, source_name="<reprint>")
    d1, d2 = longeron.to_dict(model1), longeron.to_dict(model2)
    d1.pop("source_name", None)
    d2.pop("source_name", None)
    assert d1 == d2


def test_kerml_projection_of_case_result_expression_parses():
    model = longeron.loads(CASES_SOURCE)
    text = longeron.to_kerml(model)
    longeron.parse_kerml_text(text)
    # the case's result expression survives as an owned expression feature
    assert "expr { thing == thing }" in text


class TestExtendedDefinitions:
    def test_prefixes_metadata_and_membership_import(self):
        model = longeron.loads(EXTENDED_DEFS_SOURCE)
        pkg = model.find("ExtendedDefs")
        abstract_tag = pkg.find("AbstractTag")
        assert abstract_tag.kind == "metadata" and abstract_tag.is_abstract
        zork = pkg.find("Zork")
        assert zork.kind == "extended"
        assert zork.is_abstract and zork.metadata == ["Tag"]
        level = pkg.find("Level")
        docs = [m for m in level.members if isinstance(m, M.Documentation)]
        assert "severity levels" in docs[0].text
        assert [m.name for m in level.members if isinstance(m, M.Usage)] == ["low", "high"]
        member_import = next(m for m in pkg.members if isinstance(m, M.Import))
        assert member_import.target == "ExtendedDefs::singleThing"
        assert not member_import.is_namespace


class TestStateAndActionFlow:
    def test_guarded_entry_and_named_transition(self):
        model = longeron.loads(STATE_FLOW_SOURCE)
        power = model.find("StateFlow::Power")
        transitions = [m for m in power.members if isinstance(m, M.TransitionUsage)]
        entry = transitions[0]
        assert entry.source == M.ENTRY_SOURCE and entry.target == "off"
        assert entry.guard is not None and entry.guard.to_text() == "ready"
        named = next(t for t in transitions if t.name)
        assert named.name == "t1"
        assert (named.source, named.target) == ("off", "on")
        assert named.trigger is not None

    def test_then_else_and_send_via(self):
        model = longeron.loads(STATE_FLOW_SOURCE)
        flow = model.find("StateFlow::Flow")
        successions = [m for m in flow.members if isinstance(m, M.Succession)]
        assert (successions[0].source, successions[0].target) == ("a1", "a2")
        default = next(s for s in successions if s.is_else)
        assert default.target == "a3"
        send = next(m for m in flow.members if isinstance(m, M.SendAction))
        assert send.via is not None and send.to is not None


class TestInterfaceRequirementViewBodies:
    def test_interface_occurrence_and_flow_members(self):
        model = longeron.loads(IFACE_REQ_VIEW_SOURCE)
        bus = model.find("IfaceReqView::Bus")
        relay = bus.member_named("relay")
        assert relay.kind == "part"
        flow = next(m for m in bus.members if isinstance(m, M.FlowUsage))
        assert (flow.source, flow.target_end) == ("left", "relay")

    def test_requirement_bare_usage_and_stakeholder(self):
        model = longeron.loads(IFACE_REQ_VIEW_SOURCE)
        spec = model.find("IfaceReqView::Spec")
        val = spec.member_named("val")
        assert val.value.expr.to_text() == "2.0"
        stakeholder = next(
            m for m in spec.members if isinstance(m, M.Usage) and m.kind == "stakeholder"
        )
        assert stakeholder.name == "owner"

    def test_view_body_satisfy(self):
        model = longeron.loads(IFACE_REQ_VIEW_SOURCE)
        view = model.find("IfaceReqView::v1")
        satisfies = [m for m in view.members if isinstance(m, M.SatisfyUsage)]
        assert satisfies[0].subsets == ["Spec"]


class TestLibraryAndReferenceFlags:
    def test_standard_library_package_and_ref_forms(self):
        model = longeron.loads(LIBRARY_FLAGS_SOURCE)
        pkg = model.find("LibraryFlags")
        assert pkg.is_library and pkg.is_standard
        count = pkg.member_named("count")
        assert count.value.is_default and count.value.is_initial
        rack = pkg.member_named("rack")
        assert rack.multiplicity.is_ordered and rack.multiplicity.is_nonunique
        observer = pkg.member_named("observer")
        assert observer.is_ref and observer.references == "rack"
        spare = pkg.member_named("spareBox")
        assert spare.is_ref and spare.kind == "part"
        cool = model.find("LibraryFlags::Box").members[-1]
        assert cool.is_negated and cool.constraint_kind == "assert"


class TestConnectionsAndAcceptKinds:
    def test_nary_connection_with_named_ends(self):
        model = longeron.loads(CONNECT_ACCEPT_SOURCE)
        tri = model.find("ConnectAccept::tri")
        assert isinstance(tri, M.ConnectionUsage)
        assert [(e.name, e.target) for e in tri.ends] == [
            ("pa", "a"),
            ("pb", "b"),
            ("pc", "c"),
        ]
        bind = next(
            m for m in model.find("ConnectAccept").members if isinstance(m, M.BindingConnector)
        )
        assert bind.name == "namedBind"
        assert (bind.source_end.target, bind.target_end.target) == ("a", "b")

    def test_timed_and_conditional_accepts(self):
        model = longeron.loads(CONNECT_ACCEPT_SOURCE)
        watch = model.find("ConnectAccept::Watch")
        accepts = [m for m in watch.members if isinstance(m, M.AcceptAction)]
        kinds = [(a.trigger_kind, a.trigger.to_text() if a.trigger else None) for a in accepts]
        assert kinds == [("at", "5.0"), ("after", "1.0"), ("when", "limit > 2.0")]
        assert accepts[1].via is not None and accepts[1].via.to_text() == "a"

    def test_if_else_loop_and_terminate(self):
        model = longeron.loads(CONNECT_ACCEPT_SOURCE)
        watch = model.find("ConnectAccept::Watch")
        if_action = next(m for m in watch.members if isinstance(m, M.IfAction))
        assert if_action.else_body  # both arms present
        loop = next(m for m in watch.members if isinstance(m, M.WhileLoop))
        assert loop.until is not None and loop.until.to_text() == "limit > 2.0"
        terminate = next(m for m in watch.members if isinstance(m, M.TerminateAction))
        assert terminate.target is not None and terminate.target.to_text() == "a"

    def test_transition_effect_performs_a_reference(self):
        model = longeron.loads(CONNECT_ACCEPT_SOURCE)
        guarded = model.find("ConnectAccept::Guarded")
        full = next(
            t for t in guarded.members if isinstance(t, M.TransitionUsage) and t.source == "off"
        )
        assert isinstance(t := full.effect, M.PerformAction) and t.target == "doReset"
