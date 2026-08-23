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

    def test_units_not_flagged(self):
        assert (
            diags("""
            package P { part def V { attribute d : Real = 10.0 [furlongs]; } }
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
        # --strict promotes the warning to a failure
        assert main(["lint", "--strict-imports", "--strict", str(path)]) == 1


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
    model = longeron.load("examples/drone.sysml")
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
