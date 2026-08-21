"""Coverage tests for constructs added in the full-coverage pass:
interfaces, views, flows, allocations, metadata, satisfy/verify/frame,
filtered imports.  All of them must build (no Unsupported) and round-trip.
"""

import pytest

import sysml2
from sysml2 import model as M

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


@pytest.mark.parametrize("source", FULL_COVERAGE_SOURCES)
def test_no_unsupported(source):
    model = sysml2.loads(source)
    leftovers = [e for e in model.iter_tree() if isinstance(e, M.Unsupported)]
    assert not leftovers, f"unsupported: {[u.rule for u in leftovers]}"


@pytest.mark.parametrize("source", FULL_COVERAGE_SOURCES)
def test_round_trip(source):
    model1 = sysml2.loads(source)
    text = sysml2.to_sysml(model1)
    model2 = sysml2.loads(text, source_name="<reprint>")
    d1, d2 = sysml2.to_dict(model1), sysml2.to_dict(model2)
    d1.pop("source_name", None)
    d2.pop("source_name", None)
    assert d1 == d2, f"round-trip mismatch for:\n{text}"


def test_interface_structure():
    model = sysml2.loads(FULL_COVERAGE_SOURCES[0])
    i1 = model.find("Interfaces::sys::i1")
    assert isinstance(i1, M.InterfaceUsage)
    assert i1.types == ["Plug"]
    assert [e.target for e in i1.ends] == ["a", "b"]


def test_flow_structure():
    model = sysml2.loads(FULL_COVERAGE_SOURCES[2])
    sys_part = model.find("Flows::sys")
    flows = [m for m in sys_part.members if isinstance(m, M.FlowUsage)]
    assert flows[0].payload == "fluid : Water"
    assert flows[0].source == "pump.outlet"
    assert flows[0].target_end == "tank.inlet"
    assert flows[2].is_succession
    assert flows[3].kind == "message"


def test_metadata_structure():
    model = sysml2.loads(FULL_COVERAGE_SOURCES[4])
    pkg = model.find("Meta")
    annotations = [m for m in pkg.members if isinstance(m, M.MetadataUsage)]
    assert annotations[0].typed_by == "Safety"
    values = [m for m in annotations[0].members if isinstance(m, M.MetadataValue)]
    assert values[0].redefines == "level"
    assert values[0].value.expr.to_text() == "3"
    critical = pkg.find("Critical")
    assert critical.metadata == ["Safety"]


def test_satisfy_structure():
    model = sysml2.loads(FULL_COVERAGE_SOURCES[5])
    system = model.find("Reqs::system")
    satisfies = [m for m in system.members if isinstance(m, M.SatisfyUsage)]
    assert satisfies[0].subsets == ["R1"]
    assert satisfies[0].by == "system"
    assert satisfies[1].is_assert
    assert satisfies[2].is_negated


def test_filtered_import():
    model = sysml2.loads(FULL_COVERAGE_SOURCES[6])
    imports = [m for m in model.find("Filtered").members if isinstance(m, M.Import)]
    assert imports[0].filters and imports[0].filters[0].to_text() == "@Safety"
    assert imports[1].is_recursive


def test_filtered_expose():
    # regression: 'expose X::**[@F];' crashed the builder (filterPackage
    # alternative was only handled for regular imports)
    model = sysml2.loads(FULL_COVERAGE_SOURCES[1])
    view = model.find("Views::myView")
    exposes = [m for m in view.members if isinstance(m, M.Expose)]
    assert exposes[0].is_namespace and not exposes[0].filters
    assert exposes[2].is_recursive and not exposes[2].is_namespace
    assert exposes[2].target == "Deep"
    assert exposes[2].filters[0].to_text() == "@Safety"
