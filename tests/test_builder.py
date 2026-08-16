"""Model builder tests: parse tree -> model elements."""

import sysml2
from sysml2 import model as M


def test_package_structure(vehicle_model):
    pkg = vehicle_model.find("Vehicles")
    assert isinstance(pkg, M.Package)
    assert pkg.doc == "A small demonstration model."


def test_part_definition(vehicle_model):
    vehicle = vehicle_model.find("Vehicles::Vehicle")
    assert isinstance(vehicle, M.Definition)
    assert vehicle.kind == "part"
    assert vehicle.supers == ["Machine"]
    assert vehicle.qualified_name == "Vehicles::Vehicle"


def test_abstract_definition(vehicle_model):
    machine = vehicle_model.find("Vehicles::Machine")
    assert machine.is_abstract


def test_attribute_usage_with_value(vehicle_model):
    mass = vehicle_model.find("Vehicles::Vehicle::mass")
    assert isinstance(mass, M.Usage)
    assert mass.kind == "attribute"
    assert mass.types == ["Real"]
    assert mass.subsets == ["Machine::mass"]
    assert mass.value.expr.to_text() == "1200.0"
    assert not mass.value.is_initial


def test_multiplicity(vehicle_model):
    wheels = vehicle_model.find("Vehicles::Vehicle::wheels")
    assert wheels.multiplicity is not None
    assert wheels.multiplicity.upper.to_text() == "4"
    assert wheels.multiplicity.lower is None


def test_enum_definition(vehicle_model):
    color = vehicle_model.find("Vehicles::Color")
    assert isinstance(color, M.EnumerationDefinition)
    assert [lit.name for lit in color.literals] == ["red", "green", "blue"]


def test_calc_definition(vehicle_model):
    calc = vehicle_model.find("Vehicles::TotalMass")
    assert calc.kind == "calc"
    params = [m for m in calc.members
              if isinstance(m, M.Usage) and m.direction == "in"]
    assert [p.name for p in params] == ["vehicleMass", "cargoMass"]
    ret = [m for m in calc.members
           if isinstance(m, M.Usage) and m.direction == "return"]
    assert ret[0].value.expr.to_text() == "vehicleMass + cargoMass"


def test_assert_constraint(vehicle_model):
    vehicle = vehicle_model.find("Vehicles::Vehicle")
    constraints = [m for m in vehicle.members
                   if isinstance(m, M.Usage) and m.kind == "constraint"]
    assert len(constraints) == 1
    assert constraints[0].constraint_kind == "assert"
    assert constraints[0].result.to_text() == "mass <= maxMass"


def test_requirement_body(vehicle_model):
    req = vehicle_model.find("Vehicles::MassRequirement")
    subjects = [m for m in req.members
                if isinstance(m, M.Usage) and m.kind == "subject"]
    assert subjects[0].name == "vehicle"
    kinds = [m.constraint_kind for m in req.members
             if isinstance(m, M.Usage) and m.kind == "constraint"]
    assert kinds == ["assume", "require"]


def test_action_statements(action_model):
    action = action_model.find("Behaviors::ComputeFuel")
    assigns = [m for m in action.members if isinstance(m, M.AssignmentAction)]
    assert assigns[0].target == "fuelUsed"
    ifs = [m for m in action.members if isinstance(m, M.IfAction)]
    assert ifs[0].condition.to_text() == "fuelUsed > 100.0"


def test_state_machine_structure(state_model):
    sm = state_model.find("Machines::TrafficLight")
    states = [m.name for m in sm.members
              if isinstance(m, M.Usage) and m.kind == "state"]
    assert states == ["red", "green", "yellow"]
    transitions = [m for m in sm.members if isinstance(m, M.TransitionUsage)]
    entry = [t for t in transitions if t.source == M.ENTRY_SOURCE]
    assert entry[0].target == "red"
    triggered = [t for t in transitions if t.trigger is not None]
    assert {(t.source, t.target) for t in triggered} == {
        ("red", "green"), ("green", "yellow"), ("yellow", "red")}


def test_visibility_and_imports():
    model = sysml2.loads("""
        package P {
            private import Other::Thing;
            public import Everything::*;
            protected part def Hidden;
            alias Veh for Hidden;
        }
    """)
    pkg = model.find("P")
    imports = [m for m in pkg.members if isinstance(m, M.Import)]
    assert imports[0].visibility == "private"
    assert not imports[0].is_namespace
    assert imports[1].is_namespace
    hidden = pkg.find("Hidden")
    assert hidden.visibility == "protected"
    alias = next(m for m in pkg.members if isinstance(m, M.Alias))
    assert alias.target == "Hidden"


def test_interfaces_fully_modeled():
    model = sysml2.loads("""
        package P {
            interface def Plug { end p1 : Port1; end p2 : Port2; }
        }
    """)
    plug = model.find("P::Plug")
    assert isinstance(plug, M.Definition) and plug.kind == "interface"
    ends = [m for m in plug.members if isinstance(m, M.Usage) and m.is_end]
    assert [e.name for e in ends] == ["p1", "p2"]
    assert not [e for e in model.iter_tree() if isinstance(e, M.Unsupported)]


def test_connection_usage():
    model = sysml2.loads("""
        package P {
            part def System {
                part a;
                part b;
                connect a to b;
                connection joint connect a to b;
            }
        }
    """)
    system = model.find("P::System")
    conns = [m for m in system.members if isinstance(m, M.ConnectionUsage)]
    assert len(conns) == 2
    assert [e.target for e in conns[0].ends] == ["a", "b"]
    assert conns[1].name == "joint"


def test_quoted_names():
    model = sysml2.loads("package 'My Package' { part def 'Two Words'; }")
    pkg = model.members[0]
    assert pkg.name == "My Package"
    assert pkg.find("Two Words") is not None


def test_programmatic_definition():
    pkg = M.Package(name="Prog")
    part = M.Definition(kind="part", name="Widget")
    part.add(M.Usage(kind="attribute", name="size", types=["Real"],
                     value=M.FeatureValue(sysml2.parse_expression("2 + 3"))))
    pkg.add(part)
    model = M.Model()
    model.add(pkg)
    text = sysml2.to_sysml(model)
    reparsed = sysml2.loads(text)
    size = reparsed.find("Prog::Widget::size")
    assert size.value.expr.to_text() == "2 + 3"
