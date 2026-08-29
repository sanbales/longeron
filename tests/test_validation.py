"""Validation tests: longeron.validate / longeron lint."""

from pathlib import Path

import longeron


def diags(source, code=None):
    result = longeron.validate(longeron.loads(source))
    if code is not None:
        return [d for d in result if d.code == code]
    return result


class TestCleanModels:
    def test_valid_model_no_diagnostics(self, vehicle_model):
        assert longeron.validate(vehicle_model) == []

    def test_library_packages_are_not_subjects(self):
        # library packages are resolution context only: internal problems
        # (here a duplicate name) are not reported against the model
        assert (
            diags("""
            standard library package Lib { part def X; part def X; }
            package P { part def V; }
        """)
            == []
        )

    def test_builtin_types_resolve_against_stdlib(self):
        # no import anywhere: Real/Integer/String resolve through the
        # standard-library fallback (implicit library visibility)
        assert (
            diags("""
            package P {
                part def V { attribute m : Real = 1.0;
                             attribute n : Integer; attribute s : String; }
            }
        """)
            == []
        )

    def test_builtin_functions_resolve(self):
        assert (
            diags("""
            package P { calc def C { in x : Real;
                                     return : Real = sqrt(abs(x)); } }
        """)
            == []
        )

    def test_resolvable_units_are_silent(self):
        assert (
            diags("""
            package P { part def V { attribute d : Real = 10.0 [SI::m];
                                     attribute e : Real = 2.0 [kg]; } }
        """)
            == []
        )


class TestStdlibResolution:
    """Stage C: names really resolve against the vendored stdlib."""

    def test_qualified_stdlib_reference(self):
        assert (
            diags("""
            package P { part def V { attribute s : ScalarValues::Real; } }
        """)
            == []
        )

    def test_stdlib_typo_warns(self):
        found = diags("package P { part def W { attribute bad : Reall; } }", "unresolved-reference")
        assert len(found) == 1
        assert "Reall" in found[0].message

    def test_stdlib_disabled_restores_old_warnings(self):
        model = longeron.loads("package P { part def V { attribute m : Real; } }")
        assert longeron.validate(model) == []
        found = [
            d for d in longeron.validate(model, stdlib=False) if d.code == "unresolved-reference"
        ]
        assert len(found) == 1


class TestImpliedSpecializations:
    """Stage C: plain defs/usages imply standard-library bases."""

    @staticmethod
    def resolver(model):
        from longeron.interpreter import Resolver
        from longeron.stdlib import standard_library_model

        return Resolver(model, library=standard_library_model())

    def test_part_def_implies_parts_part(self):
        model = longeron.loads("package P { part def V; part v : V; }")
        resolver = self.resolver(model)
        v = resolver.resolve("P::V", model)
        assert [g.qualified_name for g in resolver.implied_generals(v)] == ["Parts::Part"]
        # an explicit type suppresses the implied base
        assert resolver.implied_generals(resolver.resolve("P::v", model)) == []

    def test_bare_part_usage_implies_parts(self):
        model = longeron.loads("package P { part v; }")
        resolver = self.resolver(model)
        usage = resolver.resolve("P::v", model)
        assert [g.qualified_name for g in resolver.implied_generals(usage)] == ["Parts::parts"]

    def test_explicit_supers_suppress_implied(self):
        model = longeron.loads("package P { part def A; part def B :> A; }")
        resolver = self.resolver(model)
        assert resolver.implied_generals(resolver.resolve("P::B", model)) == []

    def test_action_inherits_start_done_when_implied(self):
        model = longeron.loads("package P { action def A { action s1; } }")
        resolver = self.resolver(model)
        target = resolver.resolve("P::A", model)
        names = {m.name for m in resolver.members_of(target, implied=True)}
        assert {"start", "done"} <= names
        # default (implied=False) stays library-free
        plain = {m.name for m in resolver.members_of(target)}
        assert "start" not in plain

    def test_instantiation_unchanged_by_implied_bases(self):
        interp = longeron.Interpreter(
            longeron.loads("package P { part def V { attribute m : Real = 1.0; } }")
        )
        assert set(interp.instantiate("P::V").slots) == {"m"}


class TestUnresolvedReferences:
    def test_unresolved_type(self):
        found = diags("package P { part v : NoSuchDef; }", "unresolved-reference")
        assert len(found) == 1
        assert "NoSuchDef" in found[0].message
        assert found[0].severity == "warning"

    def test_unresolved_specialization(self):
        found = diags("package P { part def V :> Ghost; }", "unresolved-reference")
        assert len(found) == 1

    def test_unresolved_import(self):
        found = diags("package P { private import Nowhere::*; }", "unresolved-reference")
        assert len(found) == 1

    def test_unresolved_alias(self):
        found = diags("package P { alias G for Ghost; }", "unresolved-reference")
        assert len(found) == 1

    def test_unresolved_connector_end(self):
        found = diags(
            """
            package P { part sys { part a; connect a to ghost; } }
        """,
            "unresolved-reference",
        )
        assert len(found) == 1

    def test_resolved_through_import(self):
        assert (
            diags(
                """
            package Lib { part def Widget; }
            package P {
                private import Lib::*;
                part w : Widget;
            }
        """,
                "unresolved-reference",
            )
            == []
        )

    def test_dotted_reference(self):
        assert (
            diags(
                """
            package P {
                part def E { attribute p : Real = 1.0; }
                part sys { part e : E; connect e.p to e; }
            }
        """,
                "unresolved-reference",
            )
            == []
        )


class TestUnresolvedExpressionNames:
    def test_typo_in_expression(self):
        found = diags(
            """
            package P { part def V { attribute a : Real = 1.0;
                                     attribute b : Real = aa + 1.0; } }
        """,
            "unresolved-name",
        )
        assert len(found) == 1
        assert "'aa'" in found[0].message

    def test_sibling_attribute_ok(self):
        assert (
            diags(
                """
            package P { part def V { attribute a : Real = 1.0;
                                     attribute b : Real = a + 1.0; } }
        """,
                "unresolved-name",
            )
            == []
        )

    def test_for_loop_var_bound(self):
        assert (
            diags(
                """
            package P { action def A { out t : Integer;
                for i in 1..3 { assign t := t + i; } } }
        """,
                "unresolved-name",
            )
            == []
        )

    def test_accept_payload_bound(self):
        assert (
            diags(
                """
            package P {
                item def Sig;
                action def A { accept s : Sig; send s; }
            }
        """,
                "unresolved-name",
            )
            == []
        )

    def test_body_expr_params_bound(self):
        assert (
            diags(
                """
            package P { calc def C {
                return : Real = (1, 2, 3)->select { in x; x > 1 }->size();
            } }
        """,
                "unresolved-name",
            )
            == []
        )

    def test_transition_payload_bound(self):
        assert (
            diags(
                """
            package P {
                item def Temp;
                state def S {
                    entry; then a;
                    state a;
                    transition first a accept t : Temp if t == t then a;
                }
            }
        """,
                "unresolved-name",
            )
            == []
        )

    def test_guard_typo_flagged(self):
        found = diags(
            """
            package P { state def S {
                entry; then a;
                state a;
                transition first a accept go if ghostVar then a;
            } }
        """,
            "unresolved-name",
        )
        assert len(found) == 1


class TestDanglingExposes:
    """dangling-expose: an expose whose target no longer resolves (the
    view-persistence design's finding 5)."""

    def test_dangling_expose_warns(self):
        found = diags("package P { part a; view v { expose P::gone; } }", "dangling-expose")
        assert len(found) == 1
        assert found[0].severity == "warning"
        assert "P::gone" in found[0].message
        # the subject is the owning view usage (the expose is anonymous)
        assert found[0].element == "P::v"

    def test_resolving_exposes_stay_silent(self):
        assert (
            diags(
                """
            package P {
                part a;
                view v {
                    expose P::a;
                    expose P::*;
                    expose P::**[not @SysML::ConnectionUsage];
                }
            }
        """,
                "dangling-expose",
            )
            == []
        )

    def test_saved_view_shape_is_clean(self):
        # the exact text save_view writes (design doc example)
        assert (
            diags(
                """
            package Rig {
                part def Axle { part hub : Hub [2]; }
                part def Hub;
                part axle : Axle;
                view 'axle structure' : StandardViewDefinitions::InterconnectionView {
                    expose Rig::**;
                    render Views::asInterconnectionDiagram;
                }
            }
        """
            )
            == []
        )

    def test_location_points_at_the_expose(self):
        source = "package P {\n    part a;\n    view v {\n        expose P::gone;\n    }\n}\n"
        model = longeron.loads(source, source_name="views.sysml")
        found = [d for d in longeron.validate(model) if d.code == "dangling-expose"]
        assert len(found) == 1
        location = found[0].location
        assert location is not None
        assert (location.source_name, location.line) == ("views.sysml", 4)

    def test_lint_cli_reports_dangling_exposes(self, tmp_path, capsys):
        from longeron.cli import main

        target = tmp_path / "views.sysml"
        target.write_text("package P { part a; view v { expose P::gone; } }")
        assert main(["lint", str(target), "--no-cache"]) == 0  # warning, not error
        out = capsys.readouterr().out
        assert "dangling-expose" in out
        assert main(["lint", str(target), "--no-cache", "--strict"]) == 1


class TestDanglingFlows:
    """dangling-flow: a flow/message end that does not resolve (the
    mdao-objects design's finding 4 -- ends are verbatim strings the
    model layer never resolves)."""

    PLANT = """
        package P {
            item def Fuel;
            item def Diesel :> Fuel;
            item def Water;
            part def Tank { out item fuelOut : Fuel; }
            part def Engine { in item fuelIn : Fuel; }
            part def Plant {
                part tank : Tank;
                part engine : Engine;
                %s
            }
        }
    """

    def flow_diags(self, member, code="dangling-flow"):
        return diags(self.PLANT % member, code)

    def test_resolving_ends_stay_silent(self):
        assert self.flow_diags("flow of Fuel from tank.fuelOut to engine.fuelIn;") == []

    def test_dangling_source_warns(self):
        found = self.flow_diags("flow from tank.nope to engine.fuelIn;")
        assert len(found) == 1
        assert found[0].severity == "warning"
        assert "flow source 'tank.nope' does not resolve" in found[0].message
        # the subject is the owning part def (the flow is anonymous)
        assert found[0].element == "P::Plant"

    def test_dangling_target_warns(self):
        found = self.flow_diags("flow from tank.fuelOut to engine.gone;")
        assert len(found) == 1
        assert "flow target 'engine.gone' does not resolve" in found[0].message

    def test_both_ends_dangle(self):
        found = self.flow_diags("flow from tank.nope to engine.gone;")
        assert len(found) == 2

    def test_named_flow_is_the_subject(self):
        found = self.flow_diags("flow f from tank.nope to engine.fuelIn;")
        assert [d.element for d in found] == ["P::Plant::f"]

    def test_message_ends_checked(self):
        found = self.flow_diags("message of Fuel from tank.nope to engine.fuelIn;")
        assert len(found) == 1
        assert "message source 'tank.nope' does not resolve" in found[0].message

    def test_action_scoped_flow_resolves(self):
        assert (
            diags(
                """
            package Q {
                item def Part1;
                action def Move {
                    action a1 { out item y : Part1; }
                    action a2 { in item x : Part1; }
                    flow of Part1 from a1.y to a2.x;
                }
            }
        """,
                "dangling-flow",
            )
            == []
        )

    def test_location_points_at_the_flow(self):
        source = self.PLANT % "flow from tank.nope to engine.fuelIn;"
        model = longeron.loads(source, source_name="plant.sysml")
        found = [d for d in longeron.validate(model) if d.code == "dangling-flow"]
        assert len(found) == 1
        location = found[0].location
        assert location is not None
        assert location.source_name == "plant.sysml"


class TestFlowPayloadMismatch:
    """flow-payload-mismatch: declared payload typing unrelated (by the
    specialization walk, either direction) to the target end's declared
    typing.  Typing absent on either side stays silent -- no guessing."""

    PLANT = TestDanglingFlows.PLANT

    def flow_diags(self, member, code="flow-payload-mismatch"):
        return diags(self.PLANT % member, code)

    def test_conforming_subtype_payload_is_silent(self):
        assert self.flow_diags("flow of Diesel from tank.fuelOut to engine.fuelIn;") == []

    def test_exact_type_is_silent(self):
        assert self.flow_diags("flow of Fuel from tank.fuelOut to engine.fuelIn;") == []

    def test_supertype_payload_is_silent(self):
        # a Fuel-typed payload may hold a Diesel at runtime: related types
        # never warn, only provably unrelated ones
        found = diags(
            """
            package P {
                item def Fuel;
                item def Diesel :> Fuel;
                part def Tank { out item fuelOut : Fuel; }
                part def Engine { in item dieselIn : Diesel; }
                part def Plant {
                    part tank : Tank;
                    part engine : Engine;
                    flow of Fuel from tank.fuelOut to engine.dieselIn;
                }
            }
        """,
            "flow-payload-mismatch",
        )
        assert found == []

    def test_unrelated_payload_warns(self):
        found = self.flow_diags("flow of Water from tank.fuelOut to engine.fuelIn;")
        assert len(found) == 1
        assert found[0].severity == "warning"
        assert (
            "payload 'Water' is incompatible with flow target "
            "'engine.fuelIn' (accepts 'Fuel')" in found[0].message
        )

    def test_named_payload_typing_is_checked(self):
        found = self.flow_diags("flow of x : Water from tank.fuelOut to engine.fuelIn;")
        assert len(found) == 1
        assert "'x : Water'" in found[0].message

    def test_untyped_target_is_silent(self):
        found = diags(
            """
            package P {
                item def Water;
                part def Tank { out item out1 : Water; }
                part def Plant {
                    part tank : Tank;
                    part sink;
                    flow of Water from tank.out1 to sink;
                }
            }
        """,
            "flow-payload-mismatch",
        )
        assert found == []

    def test_untyped_payload_is_silent(self):
        # 'flow from a to b' declares no payload; 'flow of x from a to b'
        # names a payload feature with no typing -- neither can conflict
        assert self.flow_diags("flow from tank.fuelOut to engine.fuelIn;") == []
        assert self.flow_diags("flow of x from tank.fuelOut to engine.fuelIn;") == []

    def test_unresolved_payload_is_silent(self):
        assert self.flow_diags("flow of Bogus from tank.fuelOut to engine.fuelIn;") == []

    def test_message_payload_checked_against_accept_typing(self):
        source = """
            package Q {
                item def Ping;
                item def Pong;
                action def Exchange {
                    action sender { out item p : Ping; }
                    action receiveIt accept hit : Pong;
                    message of %s from sender.p to receiveIt;
                }
            }
        """
        found = diags(source % "Ping", "flow-payload-mismatch")
        assert len(found) == 1
        assert (
            "payload 'Ping' is incompatible with message target "
            "'receiveIt' (accepts 'Pong')" in found[0].message
        )
        assert diags(source % "Pong", "flow-payload-mismatch") == []

    def test_lint_cli_reports_flow_diagnostics(self, tmp_path, capsys):
        from longeron.cli import main

        target = tmp_path / "plant.sysml"
        target.write_text(
            self.PLANT
            % (
                "flow of Water from tank.fuelOut to engine.fuelIn;"
                "flow from tank.nope to engine.fuelIn;"
            )
        )
        assert main(["lint", str(target), "--no-cache"]) == 0  # warnings, not errors
        out = capsys.readouterr().out
        assert "flow-payload-mismatch" in out
        assert "dangling-flow" in out
        assert main(["lint", str(target), "--no-cache", "--strict"]) == 1


class TestStructuralErrors:
    def test_duplicate_names(self):
        found = diags(
            """
            package P { part def X; part def X; }
        """,
            "duplicate-name",
        )
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_specialization_cycle(self):
        found = diags(
            """
            package P { part def A :> B; part def B :> A; }
        """,
            "specialization-cycle",
        )
        assert len(found) == 2  # reported for both participants

    def test_self_specialization(self):
        found = diags("package P { part def A :> A; }", "specialization-cycle")
        assert len(found) == 1

    def test_transition_to_unknown_state(self):
        found = diags(
            """
            package P { state def S {
                entry; then a;
                state a;
                transition first a accept go then ghost;
            } }
        """,
            "unknown-state",
        )
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_missing_entry_transition(self):
        found = diags("package P { state def S { state a; state b; } }", "no-entry-transition")
        assert len(found) == 1

    def test_calc_without_result(self):
        found = diags("package P { calc def C { in x : Real; } }", "calc-without-result")
        assert len(found) == 1

    def test_redefinition_is_not_a_cycle(self):
        # ':>> x' resolves to the same-named inherited feature; the name
        # shadowing must not be reported as a specialization cycle (L4)
        assert (
            diags("""
            package P {
                part def A { attribute x : Real; }
                part def B :> A { attribute x : Real :>> x; }
            }
        """)
            == []
        )

    def test_self_redefinition_is_not_a_cycle(self):
        assert diags("package P { part def C { attribute mass : Real :>> mass; } }") == []


class TestKindNesting:
    """Composite occurrence features where the metamodel demands
    referential ones (validateAttributeDefinitionFeatures /
    validateAttributeUsageFeatures / the pilot's port-composite rule)."""

    def test_state_in_attribute_def(self):
        found = diags("package P { attribute def A { state s; } }", "attribute-composite-feature")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_part_in_attribute_usage(self):
        found = diags("package P { attribute a : Real { part p; } }", "attribute-composite-feature")
        assert len(found) == 1

    def test_item_in_attribute_def_is_tolerated(self):
        # the spec rule text covers items too, but the spec's own corpus
        # nests composite items in attribute defs ('attribute def Show {
        # item picture : Picture; }'), so items stay unjudged
        src = "package P { item def Picture; attribute def Show { item p : Picture; } }"
        assert diags(src, "attribute-composite-feature") == []

    def test_composite_part_in_port_def(self):
        found = diags(
            "package P { part def D; port def Q { part p : D; } }", "port-composite-usage"
        )
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_ref_part_in_port_def_is_fine(self):
        assert diags("package P { part def D; port def Q { ref part p : D; } }") == []

    def test_directed_items_in_port_def_are_fine(self):
        # 'out item fuelSupply : Fuel;' is the spec's own port idiom
        src = """package P { item def Fuel;
                   port def FuelPort { out item supply : Fuel; in item ret : Fuel; } }"""
        assert diags(src, "port-composite-usage") == []


class TestKindTyping:
    """usage-type and friends: a declared type that resolves to a
    definition of a conflicting kind is a structural error; unresolved
    types stay [unresolved-reference] warnings."""

    def test_attribute_typed_by_part_def(self):
        found = diags("package P { part def D; attribute a : D; }", "usage-type")
        assert len(found) == 1
        assert found[0].severity == "error"
        assert "attribute" in found[0].message

    def test_part_typed_by_attribute_def(self):
        found = diags("package P { attribute def A; part p : A; }", "usage-type")
        assert len(found) == 1

    def test_action_typed_by_part_def(self):
        found = diags("package P { part def D; action a : D; }", "usage-type")
        assert len(found) == 1

    def test_usage_typed_by_package(self):
        found = diags("package P { part p : P; }", "usage-type")
        assert len(found) == 1
        assert "package" in found[0].message

    def test_legitimate_typings_are_silent(self):
        src = """package P { part def D; attribute def A; action def B;
                   part p : D; attribute a : A; action b : B; }"""
        assert diags(src, "usage-type") == []

    def test_library_typed_kinds_are_not_judged(self):
        # the vendored KerML libraries project 'datatype' onto the item
        # kind (Collections::Set et al.); library kinds are bottom, so
        # the corpus idiom 'attribute c : Set' stays silent
        assert diags("package P { attribute c : Collections::Set; }", "usage-type") == []

    def test_two_individual_definitions(self):
        src = (
            "package P { individual part def I1; individual part def I2; "
            "individual part p : I1, I2; }"
        )
        found = diags(src, "individual-definition")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_enum_attribute_with_two_types(self):
        found = diags("package P { enum def E { a; } attribute e : E, E; }", "enum-attribute-type")
        assert len(found) == 1

    def test_single_enum_typing_is_fine(self):
        assert diags("package P { enum def E { a; } attribute e : E; }") == []

    def test_metadata_prefix_must_be_metadata_def(self):
        found = diags("package P { part def Meta; #Meta part p; }", "metadata-usage-type")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_metadata_prefix_of_metadata_def_is_fine(self):
        src = "package P { metadata def Safety; #Safety part p; }"
        assert diags(src, "metadata-usage-type") == []

    def test_unresolved_metadata_prefix_stays_silent(self):
        # user-defined keywords may live in files that were not loaded
        assert diags("package P { #ghost part p; }", "metadata-usage-type") == []


class TestSpecializationKinds:
    """Cross-family definition specializations (KerML: a DataType may not
    specialize a Class; Behaviors and Structures do not mix)."""

    def test_attribute_def_specializes_part_def(self):
        found = diags("package P { part def D; attribute def A :> D; }", "datatype-specialization")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_action_def_specializes_part_def(self):
        found = diags("package P { part def D; action def A :> D; }", "behavior-specialization")
        assert len(found) == 1

    def test_part_def_specializes_action_def(self):
        found = diags("package P { action def B; part def D :> B; }", "structure-specialization")
        assert len(found) == 1

    def test_within_family_specializations_are_silent(self):
        src = """package P { part def D; part def D2 :> D;
                   action def B; state def S :> B;
                   attribute def A; attribute def A2 :> A; }"""
        assert diags(src) == []

    def test_library_supers_are_not_judged(self):
        # Collections::Array is a KerML datatype the vendored library
        # projects onto the item kind; library kinds are bottom
        src = "package P { attribute def C :> Collections::Array; }"
        assert diags(src, "datatype-specialization") == []


class TestRedefinitionFeaturing:
    def test_sibling_redefinition(self):
        found = diags(
            "package P { part def A { attribute x : Real; attribute y :>> x; } }",
            "redefinition-featuring-types",
        )
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_package_level_redefinition(self):
        found = diags(
            "package P { attribute x : Real; attribute y :>> x; }",
            "redefinition-featuring-types",
        )
        assert len(found) == 1
        assert "package-level" in found[0].message

    def test_inherited_redefinition_is_fine(self):
        src = """package P { part def A { attribute x : Real; }
                   part def B :> A { attribute x : Real :>> x; } }"""
        assert diags(src, "redefinition-featuring-types") == []


class TestVariationMembership:
    def test_variant_outside_variation(self):
        found = diags("package P { part def D { variant part v; } }", "variant-membership")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_non_variant_in_variation(self):
        found = diags(
            "package P { variation part def V { part notvariant; } }", "variation-membership"
        )
        assert len(found) == 1

    def test_proper_variation_is_silent(self):
        src = """package P { part def D;
                   variation part def V { variant part a : D; variant part b : D; } }"""
        assert diags(src) == []


class TestMemberCounts:
    def test_two_subjects(self):
        src = "package P { part def D; requirement def R { subject s1 : D; subject s2 : D; } }"
        found = diags(src, "only-one-subject")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_two_returns(self):
        src = "package P { calc def C { return : Real = 1.0; return : Real = 2.0; } }"
        found = diags(src, "only-one-return-parameter")
        assert len(found) == 1

    def test_two_entry_actions(self):
        src = "state def S { entry; then a; entry; then b; state a; state b; }"
        found = diags(src, "state-subaction-kind")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_one_of_each_state_subaction_is_fine(self):
        src = """package P { action def Go;
                   state def S { entry; then a; state a { do Go; exit Go; } } }"""
        assert diags(src, "state-subaction-kind") == []

    def test_one_subject_one_return_are_fine(self):
        src = """package P { part def D;
                   requirement def R { subject s : D; }
                   calc def C { return : Real = 1.0; } }"""
        assert diags(src) == []


class TestConnectorEndKinds:
    def test_connector_end_is_a_definition(self):
        src = "package P { part def D1; part def Asm { part a : D1; connect a to D1; } }"
        found = diags(src, "connector-end-not-feature")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_binding_end_is_a_definition(self):
        src = "package P { part def D; part def Asm { attribute a : Real; bind a = D; } }"
        found = diags(src, "connector-end-not-feature")
        assert len(found) == 1

    def test_interface_def_end_not_a_port(self):
        src = "package P { part def W; interface def I { end w1 : W; end w2 : W; } }"
        found = diags(src, "interface-end-not-port")
        assert len(found) == 2
        assert found[0].severity == "error"

    def test_interface_usage_ends_not_ports(self):
        src = (
            "package P { interface def I; part def Asm { part a; part b; "
            "interface i : I connect a to b; } }"
        )
        found = diags(src, "interface-end-not-port")
        assert len(found) == 2

    def test_proper_interface_is_silent(self):
        src = """package P { port def Q;
                   interface def I { end p1 : Q; end p2 : Q; }
                   part def Asm { part a { port pa : Q; } part b { port pb : ~Q; }
                                  interface i : I connect a.pa to b.pb; } }"""
        assert diags(src) == []


class TestExhibitAndPerformKinds:
    def test_exhibit_of_a_non_state(self):
        found = diags("package P { part def D { part a; exhibit a; } }", "exhibit-state-reference")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_exhibit_of_a_state_is_fine(self):
        assert diags("package P { part def D { state s; exhibit s; } }") == []

    def test_perform_of_a_non_action(self):
        src = "package P { attribute b : Real; part def D { perform b; } }"
        found = diags(src, "perform-action-reference")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_perform_of_unresolved_target_warns(self):
        found = diags("package P { part def D { perform ghost; } }", "unresolved-reference")
        assert len(found) == 1
        assert found[0].severity == "warning"

    def test_perform_of_inline_declared_action_is_fine(self):
        # 'perform action X;' hides X's name from the resolver (it lives
        # on the wrapped usage); the reference must not warn
        src = """package P { part def V {
                   perform action providePower;
                   exhibit state states { state on { do providePower; } } } }"""
        assert diags(src, "unresolved-reference") == []

    def test_perform_chain_with_live_head_is_not_judged(self):
        # a chained target may reach its action through featuring
        # semantics the model does not carry: bottom, no judgment
        src = """package P { part def E { action go; } part def D {
                   part e : E; perform e.missing; } }"""
        assert diags(src, "unresolved-reference") == []


class TestMultiplicityBounds:
    def test_real_bound(self):
        found = diags("package P { part def D; part p : D[1.5]; }", "multiplicity-bound-type")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_string_bound(self):
        found = diags('package P { part def D; part p : D["two"]; }', "multiplicity-bound-type")
        assert len(found) == 1

    def test_lower_exceeds_upper(self):
        found = diags("package P { part def D; part p : D[2..1]; }", "multiplicity-bound-order")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_three_to_one(self):
        # conformance decision 3 (docs/design/conformance.md): [3..1] is
        # an error, deliberately stricter than the pilot
        found = diags("package P { part def D; part p : D[3..1]; }", "multiplicity-bound-order")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_ordered_and_equal_bounds_are_fine(self):
        src = """package P { part def D;
                   part p : D[1..3]; part q : D[3..3]; }"""
        assert diags(src) == []

    def test_named_bounds_are_not_order_checked(self):
        # only literal integer pairs are decidable; a named (expression)
        # bound is never judged for order
        src = """package P { part def D; attribute n : Natural;
                   part p : D[n..1]; part q : D[3..n]; }"""
        assert diags(src, "multiplicity-bound-order") == []

    def test_unresolved_name_bound_warns(self):
        found = diags("package P { part def D; part p : D[n]; }", "unresolved-reference")
        assert len(found) == 1
        assert found[0].severity == "warning"
        assert "multiplicity bound" in found[0].message

    def test_natural_star_and_named_bounds_are_fine(self):
        src = """package P { part def D; attribute n : Natural;
                   part p : D[*]; part q : D[0..5]; part r : D[n]; }"""
        assert diags(src) == []


class TestSubsetsNonFeature:
    def test_subsetting_a_package(self):
        found = diags("package P { part def D; part p subsets P; }", "subsets-non-feature")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_subsetting_a_definition(self):
        found = diags(
            "package P { part def D; part a : D; part p subsets D; }", "subsets-non-feature"
        )
        assert len(found) == 1

    def test_subsetting_a_feature_is_fine(self):
        assert diags("package P { part def D; part a : D; part p subsets a; }") == []


class TestSendPayload:
    def test_bare_send_errors(self):
        found = diags("package P { action def A { send; } }", "send-payload")
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_send_with_payload_is_fine(self):
        src = """package P { attribute def Sig;
                   action def A { action t { send Sig() to t; } } }"""
        assert diags(src, "send-payload") == []

    def test_named_or_routed_sends_are_not_judged(self):
        # the pilot's own ActionTest declares 'action snd send { in :>>
        # payload = s; }' and 'action snd2 send via ... to ...;' -- the
        # payload binds elsewhere, so only the anonymous unrouted form errs
        src = """package P { action def A { action a1;
                   action snd send { }
                   action snd2 send via a1 to a1; } }"""
        assert diags(src, "send-payload") == []


class TestDanglingSuccessions:
    def test_ghost_succession_end(self):
        src = "package P { action def A { action a1; first a1 then ghost; } }"
        found = diags(src, "dangling-succession")
        assert len(found) == 1
        assert found[0].severity == "warning"

    def test_implied_start_done_are_fine(self):
        src = "package P { action def A { action s1; first start then s1; first s1 then done; } }"
        assert diags(src, "dangling-succession") == []

    def test_use_case_lifecycle_is_not_judged(self):
        # 'use case' has no implied-specialization mapping, so its
        # inherited start/done are unknowable here: bottom, no judgment
        src = "package P { use case def U { action s1; first start then s1; } }"
        assert diags(src, "dangling-succession") == []

    def test_explicitly_specialized_owner_is_not_judged(self):
        # explicit supers suppress the implied base and may inherit steps
        src = """package P { action def Base;
                   action def A :> Base { first start then missing; } }"""
        assert diags(src, "dangling-succession") == []

    def test_terminate_owner_is_not_judged(self):
        # 'action stop terminate;' loses its declared name in the model
        # layer, so member lookups in that body are unreliable
        src = """package P { action def A { action go;
                   first go then stop;
                   action stop terminate; } }"""
        assert diags(src, "dangling-succession") == []


class TestQualifiedChainResolution:
    def test_qualified_reference_to_nothing(self):
        src = "package P { part def D { attribute m : Real; } attribute t = P::D::nope; }"
        found = diags(src, "unresolved-name")
        assert len(found) == 1
        assert found[0].severity == "warning"
        assert "nope" in found[0].message

    def test_undefined_enum_literal(self):
        src = "package P { enum def E { a; b; } attribute e : E = E::c; }"
        found = diags(src, "unresolved-name")
        assert len(found) == 1

    def test_valid_qualified_references_are_fine(self):
        src = """package P { enum def E { a; b; } part def D { attribute m : Real; }
                   attribute e : E = E::a; attribute t = P::D::m; }"""
        assert diags(src, "unresolved-name") == []

    def test_usage_head_chains_are_not_judged(self):
        # a usage's member closure (featuring contexts, variant configs,
        # subject redefinitions) is richer than the model's static
        # members -- pinned as the KNOWN GAP 'feature-chain-to-nothing'
        src = "package P { part def D { attribute m : Real; } part d : D; attribute t = d.nope; }"
        assert diags(src, "unresolved-name") == []

    def test_implicit_result_member_is_not_judged(self):
        # calcs and cases carry an implicit 'result' parameter the model
        # layer does not reify
        src = "package P { calc def M { return : Real = 1.0; } attribute t = M.result; }"
        assert diags(src, "unresolved-name") == []


class TestDiagnosticLocations:
    """Diagnostics carry the subject element's file:line:column (U3)."""

    def test_location_points_at_the_declaration(self):
        source = (
            "package Demo {\n"
            "    part def Wheel;\n"
            "    part def Vehicle {\n"
            "        attribute mass : Reall;\n"
            "    }\n"
            "}\n"
        )
        model = longeron.loads(source, source_name="demo.sysml")
        found = [d for d in longeron.validate(model) if d.code == "unresolved-reference"]
        assert len(found) == 1
        location = found[0].location
        assert location is not None
        assert (location.source_name, location.line, location.column) == ("demo.sysml", 4, 9)
        assert str(found[0]).startswith("demo.sysml:4:9: warning[unresolved-reference]")

    def test_duplicate_name_reports_the_second_declaration(self):
        source = "package P {\n    part def X;\n    part def X;\n}\n"
        model = longeron.loads(source, source_name="dup.sysml")
        found = [d for d in longeron.validate(model) if d.code == "duplicate-name"]
        assert [(d.location.source_name, d.location.line) for d in found] == [("dup.sysml", 3)]

    def test_programmatic_elements_have_no_location(self):
        from longeron import model as M

        model = M.Model()
        pkg = M.Package(name="P")
        pkg.add(M.Usage(kind="part", name="v", types=["Ghost"]))
        model.add(pkg)
        found = longeron.validate(model)
        assert len(found) == 1
        assert found[0].location is None
        assert str(found[0]).startswith("warning[unresolved-reference]")

    def test_locations_survive_in_directory_models(self, tmp_path):
        (tmp_path / "a.sysml").write_text("package A {\n    part x : Ghost;\n}\n")
        (tmp_path / "b.sysml").write_text("package B {\n\n    part y : Spook;\n}\n")
        model = longeron.load_dir(tmp_path, cache=False)
        found = longeron.validate(model)
        places = sorted((Path(d.location.source_name).name, d.location.line) for d in found)
        assert places == [("a.sysml", 2), ("b.sysml", 3)]


class TestStrictImports:
    """validate(strict_imports=True): flag bare stdlib names that resolve
    only through the implicit library-visibility hop."""

    BARE = "package P { part def A { attribute x : Real; } }"

    def strict(self, source):
        return [
            d
            for d in longeron.validate(longeron.loads(source), strict_imports=True)
            if d.code == "stdlib-implicit-name"
        ]

    def test_bare_stdlib_name_flagged(self):
        found = self.strict(self.BARE)
        assert [d.severity for d in found] == ["warning"]
        assert "stdlib name 'Real' used without import" in found[0].message
        assert found[0].element == "P::A::x"

    def test_default_is_off(self):
        assert diags(self.BARE, "stdlib-implicit-name") == []

    def test_qualified_name_silent(self):
        assert (
            self.strict("""
            package P { part def A { attribute x : ScalarValues::Real; } }
        """)
            == []
        )

    def test_namespace_import_silences(self):
        assert (
            self.strict("""
            package P {
                public import ScalarValues::*;
                part def A { attribute x : Real; }
            }
        """)
            == []
        )

    def test_membership_import_silences(self):
        assert (
            self.strict("""
            package P {
                import ScalarValues::Real;
                part def A { attribute x : Real; }
            }
        """)
            == []
        )

    def test_expression_head_flagged(self):
        found = self.strict("package P { part def A { attribute lo = parts; } }")
        assert [d.message for d in found] == ["stdlib name 'parts' used without import"]

    def test_user_names_never_flagged(self):
        assert (
            self.strict("""
            package P {
                part def Engine;
                part def Car { part e : Engine; }
            }
        """)
            == []
        )


class TestCLI:
    def test_lint_clean(self, tmp_path, capsys):
        from longeron.cli import main

        path = tmp_path / "ok.sysml"
        path.write_text("package P { part def V { attribute m : Real; } }")
        assert main(["lint", str(path)]) == 0
        assert "0 error(s), 0 warning(s)" in capsys.readouterr().out

    def test_lint_warnings_pass_by_default(self, tmp_path, capsys):
        from longeron.cli import main

        path = tmp_path / "warn.sysml"
        path.write_text("package P { part v : Ghost; }")
        assert main(["lint", str(path)]) == 0
        out = capsys.readouterr().out
        assert "warning[unresolved-reference]" in out

    def test_lint_no_stdlib_flag(self, tmp_path, capsys):
        from longeron.cli import main

        path = tmp_path / "m.sysml"
        path.write_text("package P { part def V { attribute m : Real; } }")
        assert main(["lint", str(path)]) == 0
        assert "0 error(s), 0 warning(s)" in capsys.readouterr().out
        assert main(["lint", "--no-stdlib", str(path)]) == 0
        assert "warning[unresolved-reference]" in capsys.readouterr().out

    def test_lint_stdlib_flag_stays_clean(self, tmp_path, capsys):
        # regression: --stdlib merges the library into the model, which used
        # to flood lint with hundreds of diagnostics about library internals
        from longeron.cli import main

        path = tmp_path / "m.sysml"
        path.write_text("package P { part def V { attribute m : Real; } }")
        assert main(["lint", "--stdlib", str(path)]) == 0
        assert "0 error(s), 0 warning(s)" in capsys.readouterr().out

    def test_lint_strict_fails_on_warnings(self, tmp_path):
        from longeron.cli import main

        path = tmp_path / "warn.sysml"
        path.write_text("package P { part v : Ghost; }")
        assert main(["lint", str(path), "--strict"]) == 1

    def test_lint_errors_fail(self, tmp_path):
        from longeron.cli import main

        path = tmp_path / "bad.sysml"
        path.write_text("package P { part def X; part def X; }")
        assert main(["lint", str(path)]) == 1

    def test_lint_strict_imports_flag(self, tmp_path, capsys):
        from longeron.cli import main

        path = tmp_path / "m.sysml"
        path.write_text("package P { part def V { attribute m : Real; } }")
        assert main(["lint", "--strict-imports", str(path)]) == 0
        out = capsys.readouterr().out
        assert "warning[stdlib-implicit-name]" in out
        assert "used without import" in out
        # stdlib-implicit-name reports a *successful* (implicit) resolution,
        # not a resolution failure: --strict does not promote it, and the
        # exit code stays 0
        assert main(["lint", "--strict-imports", "--strict", str(path)]) == 0


class TestStrictMode:
    """validate(strict=True): the ratified open questions 1 and 4
    (docs/design/conformance.md).  Exactly the resolution-failure codes
    (RESOLUTION_CODES) promote to errors, and a bare 'import' warns."""

    def test_resolution_codes_are_the_documented_set(self):
        from longeron.validation import RESOLUTION_CODES

        assert RESOLUTION_CODES == {
            "unresolved-reference",
            "unresolved-name",
            "unresolved-unit",
            "dangling-expose",
            "dangling-flow",
            "dangling-succession",
        }

    def test_unresolved_reference_promotes(self):
        model = longeron.loads("package P { part v : Ghost; }")
        (default,) = longeron.validate(model)
        assert (default.code, default.severity) == ("unresolved-reference", "warning")
        (strict,) = longeron.validate(model, strict=True)
        assert (strict.code, strict.severity) == ("unresolved-reference", "error")

    def test_only_resolution_codes_promote(self):
        # one resolution warning, two non-resolution warnings, one error:
        # strict flips exactly the resolution warning and adds nothing else
        src = """package P {
            part def X; part def X;
            part v : Ghost;
            calc hollow { }
            state def S { state a; }
        }"""
        model = longeron.loads(src)
        default = {(d.code, d.severity) for d in longeron.validate(model)}
        strict = {(d.code, d.severity) for d in longeron.validate(model, strict=True)}
        assert ("unresolved-reference", "warning") in default
        assert ("unresolved-reference", "error") in strict
        unchanged = {
            ("duplicate-name", "error"),
            ("calc-without-result", "warning"),
            ("no-entry-transition", "warning"),
        }
        assert unchanged <= default and unchanged <= strict
        assert strict - {("unresolved-reference", "error")} == default - {
            ("unresolved-reference", "warning")
        }

    def test_stdlib_implicit_name_is_not_promoted(self):
        # fires on a successful implicit resolution: not a resolution failure
        model = longeron.loads("package P { part def V { attribute m : Real; } }")
        found = [
            d
            for d in longeron.validate(model, strict=True, strict_imports=True)
            if d.code == "stdlib-implicit-name"
        ]
        assert len(found) == 1
        assert found[0].severity == "warning"

    def test_bare_import_warns_under_strict_only(self):
        src = "package Q { part def D; } package P { import Q::*; }"
        model = longeron.loads(src)
        assert longeron.validate(model) == []  # default mode stays quiet
        (found,) = longeron.validate(model, strict=True)
        assert (found.code, found.severity) == ("bare-import", "warning")
        assert "visibility prefix" in found.message

    def test_prefixed_imports_stay_silent_under_strict(self):
        src = """package Q { part def D; }
                 package P { private import Q::*; public import Q::D; }"""
        model = longeron.loads(src)
        assert longeron.validate(model, strict=True) == []

    def test_lint_strict_flag_wires_through(self, tmp_path, capsys):
        from longeron.cli import main

        path = tmp_path / "warn.sysml"
        path.write_text("package P { part v : Ghost; }")
        assert main(["lint", str(path)]) == 0
        assert "warning[unresolved-reference]" in capsys.readouterr().out
        assert main(["lint", str(path), "--strict"]) == 1
        assert "error[unresolved-reference]" in capsys.readouterr().out

    def test_lint_strict_bare_import_warns_but_passes(self, tmp_path, capsys):
        from longeron.cli import main

        path = tmp_path / "bare.sysml"
        path.write_text("package Q { part def D; } package P { import Q::*; }")
        assert main(["lint", str(path), "--strict"]) == 0  # a warning, not an error
        assert "warning[bare-import]" in capsys.readouterr().out


def test_diagnostics_sorted_errors_first():
    result = diags("""
        package P {
            part def X; part def X;
            part v : Ghost;
        }
    """)
    severities = [d.severity for d in result]
    assert severities == sorted(severities, key=("error", "warning").index)
    assert severities[0] == "error"


def test_drone_example_is_clean():
    model = longeron.load("examples/deepscout")
    assert [d for d in longeron.validate(model) if d.severity == "error"] == []


class TestReferencePositions:
    """check_target walks every reference-bearing position: dependencies,
    references/crosses, binding ends, satisfy-by, and loop expressions."""

    def test_dangling_references_in_every_position(self):
        result = longeron.validate(
            longeron.loads(
                """
                package P {
                    part def Thing;
                    part a; part b;
                    dependency D from NoClient to NoSupplier;
                    ref watcher ::> NoRefTarget;
                    ref crosser => NoCrossTarget;
                    binding bind NoLeft = NoRight;
                    requirement def R1 { require constraint { true } }
                    part sys {
                        satisfy R1 by NoSubject;
                    }
                    calc def Quiet { in x : Real; }
                    calc quietRef : Quiet;
                    action def Loopy {
                        while NoCondition {
                            assign x := 1.0;
                        }
                        loop {
                            assign x := 2.0;
                        } until NoUntil;
                    }
                }
                """
            )
        )
        found = {(d.code, d.message) for d in result}
        assert found == {
            ("unresolved-reference", "dependency 'NoClient' does not resolve"),
            ("unresolved-reference", "dependency 'NoSupplier' does not resolve"),
            ("unresolved-reference", "references 'NoRefTarget' does not resolve"),
            ("unresolved-reference", "crosses 'NoCrossTarget' does not resolve"),
            ("unresolved-reference", "binds 'NoLeft' does not resolve"),
            ("unresolved-reference", "binds 'NoRight' does not resolve"),
            ("unresolved-reference", "satisfied by 'NoSubject' does not resolve"),
            ("unresolved-name", "expression name 'NoCondition' does not resolve"),
            ("unresolved-name", "expression name 'NoUntil' does not resolve"),
            ("calc-without-result", "calculation has no result expression"),
        }
        # the typed calc usage delegates its result: only the def is flagged
        assert [d.element for d in result if d.code == "calc-without-result"] == ["P::Quiet"]


class TestDimensionalLint:
    """The units design's five diagnostics (docs/design/units.md)."""

    def test_kg_plus_min_flags_the_motivating_bug(self):
        # the interpreter evaluates this to 35.0 without comment; the
        # lint exists because of this exact observation
        found = diags(
            """
            package P {
                part def Drone {
                    attribute mass = 5.0 [SI::kg];
                    attribute flightTime = 30.0 [SI::min];
                    attribute nonsense = mass + flightTime;
                }
            }
            """,
            "dimension-mismatch",
        )
        assert len(found) == 1
        assert found[0].severity == "warning"
        assert found[0].element == "P::Drone::nonsense"
        assert "'kg'" in found[0].message and "'min'" in found[0].message

    def test_comparison_across_dimensions_warns(self):
        found = diags(
            """
            package P {
                part def V {
                    attribute mass = 5.0 [kg];
                    attribute wingSpan = 2.0 [m];
                    assert constraint fits { mass < wingSpan }
                }
            }
            """,
            "dimension-mismatch",
        )
        assert len(found) == 1
        assert "'<'" in found[0].message

    def test_same_dimension_addition_is_silent(self):
        assert (
            diags("""
            package P { part def V {
                attribute a = 1.0 [SI::m];
                attribute b = 2.0 [m];
                attribute c = a + b;
            } }
        """)
            == []
        )

    def test_unknown_dimensions_are_bottom_and_propagate_silently(self):
        # bare literals and unitless attributes never conflict
        assert (
            diags("""
            package P { part def V {
                attribute mass = 5.0 [kg];
                attribute margin = 100.0;
                attribute padded = mass + margin;
                attribute doubled = 2.0 * mass;
                attribute total = padded + doubled;
            } }
        """)
            == []
        )

    def test_dimension_flows_through_products_and_powers(self):
        found = diags(
            """
            package P {
                part def V {
                    attribute speed = 10.0 [SI::'m/s'];
                    attribute duration = 5.0 [s];
                    attribute distance = speed * duration;
                    attribute area = 4.0 ['m²'];
                    attribute bogus = distance + area;
                }
            }
            """,
            "dimension-mismatch",
        )
        assert len(found) == 1
        assert found[0].element == "P::V::bogus"

    def test_quantity_subsetting_types_the_attribute(self):
        # `:> ISQ::mass` carries the M vector with no value annotation
        found = diags(
            """
            package P {
                part def V {
                    attribute mass :> ISQ::mass;
                    attribute clock :> ISQ::duration;
                    attribute odd = mass + clock;
                }
            }
            """,
            "dimension-mismatch",
        )
        assert len(found) == 1

    def test_scale_mismatch_is_an_error(self):
        # the ratified dBW + W ruling: cross-scale linear arithmetic is
        # never meaningful, so this outranks the dimensional heuristic
        found = diags(
            """
            package P {
                part def RF {
                    attribute gain = 20.0 [dB];
                    attribute ratio = 5.0 [one];
                    attribute bad = gain + ratio;
                }
            }
            """,
            "scale-mismatch",
        )
        assert len(found) == 1
        assert found[0].severity == "error"
        assert "log" in found[0].message and "linear" in found[0].message

    def test_celsius_plus_kelvin_is_a_scale_error(self):
        # the ruling's second half: °C is offset where K is linear
        found = diags(
            """
            package P {
                part def Thermal {
                    attribute cabin = 25.0 ['°C'];
                    attribute ambient = 298.15 [K];
                    attribute wrong = cabin + ambient;
                }
            }
            """,
            "scale-mismatch",
        )
        assert len(found) == 1
        assert found[0].severity == "error"

    def test_unresolved_unit_warns(self):
        found = diags(
            "package P { part def V { attribute d : Real = 10.0 [furlongs]; } }",
            "unresolved-unit",
        )
        assert len(found) == 1
        assert found[0].severity == "warning"
        assert "furlongs" in found[0].message

    def test_unresolved_unit_in_qualified_form(self):
        found = diags(
            "package P { part def V { attribute d = 1.0 [SI::bogusUnit]; } }",
            "unresolved-unit",
        )
        assert len(found) == 1
        assert "SI::bogusUnit" in found[0].message

    def test_bare_units_do_not_trip_strict_imports(self):
        # bare [kg] is the measurement library's own idiom
        model = longeron.loads("package P { part def V { attribute m = 1.0 [kg]; } }")
        found = [
            d
            for d in longeron.validate(model, strict_imports=True)
            if d.code == "stdlib-implicit-name"
        ]
        assert found == []

    def test_mixed_units_warns_without_the_extra(self, monkeypatch):
        from longeron import units as units_module

        monkeypatch.setattr(units_module, "units_extra_available", lambda: False)
        found = diags(
            """
            package P {
                part def V {
                    attribute a = 1.0 [SI::m];
                    attribute b = 2.0 [mm];
                    attribute c = a + b;
                }
            }
            """,
            "mixed-units",
        )
        assert len(found) == 1
        assert found[0].severity == "warning"
        assert "'m'" in found[0].message and "'mm'" in found[0].message

    def test_mixed_units_gates_off_with_the_extra(self, monkeypatch):
        # the ratified kg + lbm ruling: with [units] installed the
        # declaration boundary normalizes, so the warning is moot
        from longeron import units as units_module

        monkeypatch.setattr(units_module, "units_extra_available", lambda: True)
        assert (
            diags("""
            package P { part def V {
                attribute a = 1.0 [SI::m];
                attribute b = 2.0 [mm];
                attribute c = a + b;
            } }
        """)
            == []
        )

    def test_anchor_dimension_mismatch(self, monkeypatch):
        from longeron import units as units_module

        monkeypatch.setattr(units_module, "units_extra_available", lambda: False)
        found = diags(
            """
            package P {
                part def UAV { attribute flightTime = 0.5 [h]; }
                requirement endurance {
                    attribute shape : String = "larger-is-better";
                    attribute ramp0 : Real = 15.0 [SI::min];
                    attribute ramp1 : Real = 45.0 [SI::kg];
                    attribute measure : Real = UAV::flightTime;
                }
            }
            """,
            "anchor-dimension-mismatch",
        )
        assert len(found) == 2  # ramp0: same dim, different unit; ramp1: wrong dim
        by_element = {d.element: d.message for d in found}
        assert "different units" in by_element["P::endurance::ramp0"]
        assert "disagrees dimensionally" in by_element["P::endurance::ramp1"]

    def test_unitless_scoreboard_convention_stays_silent(self):
        # the drone example's shape: plain Real anchors, no annotations
        assert (
            diags("""
            package P {
                part def V { attribute occludedFraction : Real; }
                requirement r {
                    attribute shape : String = "smaller-is-better";
                    attribute ramp0 : Real = 0.001;
                    attribute ramp1 : Real = 0.05;
                    attribute measure : Real = V::occludedFraction;
                    attribute unit : String = "fraction";
                }
            }
        """)
            == []
        )

    def test_redefinition_chains_inherit_dimensions(self):
        found = diags(
            """
            package P {
                part def Machine { attribute mass = 100.0 [kg]; }
                part def Vehicle :> Machine {
                    attribute mass :>> Machine::mass = 1200.0;
                    attribute clock = 3.0 [s];
                    attribute odd = mass + clock;
                }
            }
            """,
            "dimension-mismatch",
        )
        assert len(found) == 1

    def test_annotation_on_expression_overrides_operands(self):
        # `3 * x [m / s]` -- the spec's own derived-unit expression shape
        found = diags(
            """
            package P {
                part def V {
                    attribute x = 2.0;
                    attribute speed = 3 * x [m / s];
                    attribute mass = 5.0 [kg];
                    attribute odd = speed + mass;
                }
            }
            """,
            "dimension-mismatch",
        )
        assert len(found) == 1

    def test_library_models_are_never_subjects(self):
        # a merged-in standard library must not be re-linted
        model = longeron.loads("package P { part def V { attribute m = 1.0 [kg]; } }")
        longeron.add_standard_library(model)
        assert longeron.validate(model) == []
