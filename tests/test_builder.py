"""Model builder tests: parse tree -> model elements."""

import longeron
from longeron import model as M


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
    params = [m for m in calc.members if isinstance(m, M.Usage) and m.direction == "in"]
    assert [p.name for p in params] == ["vehicleMass", "cargoMass"]
    ret = [m for m in calc.members if isinstance(m, M.Usage) and m.direction == "return"]
    assert ret[0].value.expr.to_text() == "vehicleMass + cargoMass"


def test_assert_constraint(vehicle_model):
    vehicle = vehicle_model.find("Vehicles::Vehicle")
    constraints = [m for m in vehicle.members if isinstance(m, M.Usage) and m.kind == "constraint"]
    assert len(constraints) == 1
    assert constraints[0].constraint_kind == "assert"
    assert constraints[0].result.to_text() == "mass <= maxMass"


def test_requirement_body(vehicle_model):
    req = vehicle_model.find("Vehicles::MassRequirement")
    subjects = [m for m in req.members if isinstance(m, M.Usage) and m.kind == "subject"]
    assert subjects[0].name == "vehicle"
    kinds = [
        m.constraint_kind for m in req.members if isinstance(m, M.Usage) and m.kind == "constraint"
    ]
    assert kinds == ["assume", "require"]


def test_action_statements(action_model):
    action = action_model.find("Behaviors::ComputeFuel")
    assigns = [m for m in action.members if isinstance(m, M.AssignmentAction)]
    assert assigns[0].target == "fuelUsed"
    ifs = [m for m in action.members if isinstance(m, M.IfAction)]
    assert ifs[0].condition.to_text() == "fuelUsed > 100.0"


def test_state_machine_structure(state_model):
    sm = state_model.find("Machines::TrafficLight")
    states = [m.name for m in sm.members if isinstance(m, M.Usage) and m.kind == "state"]
    assert states == ["red", "green", "yellow"]
    transitions = [m for m in sm.members if isinstance(m, M.TransitionUsage)]
    entry = [t for t in transitions if t.source == M.ENTRY_SOURCE]
    assert entry[0].target == "red"
    triggered = [t for t in transitions if t.trigger is not None]
    assert {(t.source, t.target) for t in triggered} == {
        ("red", "green"),
        ("green", "yellow"),
        ("yellow", "red"),
    }


def test_visibility_and_imports():
    model = longeron.loads("""
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
    model = longeron.loads("""
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
    model = longeron.loads("""
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
    assert all(e.multiplicity is None for e in conns[0].ends)
    assert conns[1].name == "joint"


def test_connector_end_cross_multiplicity():
    # the grammar's ownedCrossMultiplicityMember used to be dropped by the
    # builder; connector ends now capture it for end-multiplicity labels
    model = longeron.loads("""
        package P {
            part def System {
                part a;
                part b;
                connect [1] a to [0..4] b;
            }
        }
    """)
    conn = next(m for m in model.find("P::System").members if isinstance(m, M.ConnectionUsage))
    first, second = conn.ends
    assert first.multiplicity is not None
    assert first.multiplicity.lower is None
    assert first.multiplicity.upper.to_text() == "1"
    assert second.multiplicity.lower.to_text() == "0"
    assert second.multiplicity.upper.to_text() == "4"
    # the JSON interchange stays lossless with the new field
    clone = longeron.from_json(longeron.to_json(model))
    assert longeron.to_dict(clone) == longeron.to_dict(model)
    cloned = next(m for m in clone.find("P::System").members if isinstance(m, M.ConnectionUsage))
    assert cloned.ends[1].multiplicity.upper.to_text() == "4"


def test_quoted_names():
    model = longeron.loads("package 'My Package' { part def 'Two Words'; }")
    pkg = model.members[0]
    assert pkg.name == "My Package"
    assert pkg.find("Two Words") is not None


def test_programmatic_definition():
    pkg = M.Package(name="Prog")
    part = M.Definition(kind="part", name="Widget")
    part.add(
        M.Usage(
            kind="attribute",
            name="size",
            types=["Real"],
            value=M.FeatureValue(longeron.parse_expression("2 + 3")),
        )
    )
    pkg.add(part)
    model = M.Model()
    model.add(pkg)
    text = longeron.to_sysml(model)
    reparsed = longeron.loads(text)
    size = reparsed.find("Prog::Widget::size")
    assert size.value.expr.to_text() == "2 + 3"


def test_library_package_standard_flag():
    # regression: 'library package' without 'standard' failed to parse
    model = longeron.loads("library package L { part def X; }")
    assert model.find("L").is_standard is False
    model2 = longeron.loads("standard library package L2 { part def X; }")
    assert model2.find("L2").is_standard is True


def test_named_send_action_keeps_name():
    # regression: the 'action <name> send ...' corpus form dropped the name
    model = longeron.loads(
        "package P { action def A { action publish send new Publish(t) via p; } }"
    )
    sends = [m for m in model.find("P::A").members if isinstance(m, M.SendAction)]
    assert sends[0].name == "publish"
    assert sends[0].via.to_text() == "p"


def test_metadata_prefixed_enum_value():
    # regression: '#Security enum secret : ...' inside an enum body
    model = longeron.loads("""
        package P {
            metadata def Security;
            enum def Level {
                uncl : Level = 0;
                #Security enum secret : Level = 2;
            }
        }
    """)
    literal = model.find("P::Level::secret")
    assert literal.metadata == ["Security"]


def test_flow_usage_carries_ends_and_payload():
    """The diagram contract for flow connections (errata E16): dotted end
    paths and the payload item text live on the FlowUsage."""

    model = longeron.loads("""
        package P {
            item def Item1;
            action def A { in x : Item1; out y : Item1; }
            action a1 : A;
            action a2 : A;
            flow of Item1 from a1.y to a2.x;
        }
    """)
    flow = next(m for m in model.find("P").members if isinstance(m, M.FlowUsage))
    assert flow.kind == "flow"
    assert flow.source == "a1.y"
    assert flow.target_end == "a2.x"
    assert flow.payload == "Item1"


def test_nary_dependency_clients_and_suppliers():
    """The grammar allows comma lists on both sides -- the model keeps the
    full n-ary shape (the diagram draws a junction dot for it)."""

    model = longeron.loads("package P { part a; part b; part s; dependency D from a, b to s; }")
    dep = next(m for m in model.find("P").members if isinstance(m, M.Dependency))
    assert dep.name == "D"
    assert dep.clients == ["a", "b"]
    assert dep.suppliers == ["s"]


def test_satisfy_forms_keep_requirement_and_by():
    """Anonymous shorthand parks the requirement in subsets (a reference
    subsetting) plus `by`; the named longhand uses `references`."""

    model = longeron.loads("""
        package P {
            requirement requirement1;
            part sys;
            satisfy requirement1 by sys;
            part part1 {
                satisfy requirement requirement2 references requirement1;
            }
        }
    """)
    shorthand = next(m for m in model.find("P").members if isinstance(m, M.SatisfyUsage))
    assert shorthand.name is None
    assert shorthand.subsets == ["requirement1"]
    assert shorthand.by == "sys"
    longhand = model.find("P::part1::requirement2")
    assert isinstance(longhand, M.SatisfyUsage)
    assert longhand.references == "requirement1"
    assert longhand.by is None


def test_alias_member_target():
    model = longeron.loads("""
        package Lib { part def Target; }
        package App { alias T for Lib::Target; }
    """)
    alias = next(m for m in model.find("App").members if isinstance(m, M.Alias))
    assert alias.name == "T"
    assert alias.target == "Lib::Target"


def test_portion_usages_keep_kind_and_type():
    model = longeron.loads("""
        package P {
            individual part def Rover;
            individual rover : Rover;
            timeslice t1 : Rover;
            snapshot s1 : Rover;
        }
    """)
    assert model.find("P::Rover").is_individual
    rover = model.find("P::rover")
    assert rover.kind == "individual" and rover.is_individual
    t1 = model.find("P::t1")
    assert t1.kind == "timeslice" and t1.portion_kind == "timeslice"
    s1 = model.find("P::s1")
    assert s1.kind == "snapshot" and s1.portion_kind == "snapshot"
    assert t1.types == ["Rover"]


def test_actor_and_stakeholder_usages():
    model = longeron.loads("""
        package P {
            part def Person;
            use case def Deliver { actor driver : Person; }
            requirement def Comfort { stakeholder owner : Person; }
        }
    """)
    driver = model.find("P::Deliver::driver")
    assert driver.kind == "actor" and driver.types == ["Person"]
    owner = model.find("P::Comfort::owner")
    assert owner.kind == "stakeholder" and owner.types == ["Person"]


def test_connection_def_directed_ends_survive_in_order():
    """The diagram contract for 'connection (with direction indication)'
    (spec printed pp.65-66): the textual notation carries NO direction
    syntax -- the only model signal is the definition's end usages, whose
    names, order, multiplicities and is_end flags must survive."""

    model = longeron.loads("""
        package P {
            part def Part1;
            part def Part2;
            connection def ConnectionDef2 {
                end [1..1] part sourceEnd : Part1;
                end [1..*] part targetEnd : Part2;
            }
        }
    """)
    definition = model.find("P::ConnectionDef2")
    assert isinstance(definition, M.Definition) and definition.kind == "connection"
    ends = [m for m in definition.members if isinstance(m, M.Usage) and m.is_end]
    assert [(e.name, e.types[0]) for e in ends] == [
        ("sourceEnd", "Part1"),
        ("targetEnd", "Part2"),
    ]
    assert ends[0].multiplicity.upper.to_text() == "1"
    assert ends[1].multiplicity.upper.to_text() == "*"
