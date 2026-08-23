"""Adversarial-review LOW fixes: U4 (parse errors), U6 (client.validate),
V3 (single-source palette)."""

from __future__ import annotations

import pytest

import longeron
from longeron.errors import ParseError


class TestHumanizedParseErrors:
    """U4: ANTLR token soup is translated at the parser boundary."""

    def test_small_expected_set_is_listed(self):
        with pytest.raises(ParseError) as exc:
            longeron.parse_sysml_text("package P { part def }")
        issue = exc.value.issues[0]
        assert issue.message == "unexpected '}' (expected '{' or ';')"

    def test_expression_position_soup_becomes_expected_an_expression(self):
        with pytest.raises(ParseError) as exc:
            longeron.parse_sysml_text("package P { part def V { attribute mass = ; } }")
        issue = exc.value.issues[0]
        assert issue.message == "unexpected ';' (expected an expression)"

    def test_large_keyword_set_is_capped(self):
        with pytest.raises(ParseError) as exc:
            longeron.parse_sysml_text("package P { part x : = 5; }")
        issue = exc.value.issues[0]
        assert issue.message == "unexpected ':' (expected 'default', ':=', '{' \u2026 (2 more))"

    def test_eof_reads_as_end_of_input(self):
        with pytest.raises(ParseError) as exc:
            longeron.parse_sysml_text("package P { part def A")
        assert exc.value.issues[0].message.startswith("unexpected end of input")

    def test_raw_antlr_message_is_preserved(self):
        with pytest.raises(ParseError) as exc:
            longeron.parse_sysml_text("package P { part def V { attribute mass = ; } }")
        issue = exc.value.issues[0]
        assert issue.raw_message is not None
        assert issue.raw_message.startswith("mismatched input ';' expecting {")
        assert "DECIMAL_VALUE" in issue.raw_message  # the verbatim soup

    def test_error_echoes_source_line_with_caret(self):
        text = "package P {\n  part def V {\n    attribute mass = ;\n  }\n}"
        with pytest.raises(ParseError) as exc:
            longeron.parse_sysml_text(text)
        rendered = str(exc.value)
        assert "syntax error(s)" in rendered  # CLI contract unchanged
        assert "    |     attribute mass = ;" in rendered
        caret_line = rendered.splitlines()[-1]
        assert caret_line.strip("| ") == "^"
        # the caret sits under the offending column (after the '| ' gutter)
        issue = exc.value.issues[0]
        assert caret_line.index("^") == caret_line.index("|") + 2 + issue.column

    def test_lexer_errors_pass_through_untouched(self):
        with pytest.raises(ParseError) as exc:
            longeron.parse_sysml_text("!!!")
        assert exc.value.issues[0].message.startswith("token recognition error")


class TestPaletteSingleSource:
    """V3: SYSML_STYLE and the replay CSS are derived from render's palette."""

    def test_browser_node_and_edge_styles_derive_from_render(self):
        pytest.importorskip("ipyelk")
        from longeron import diagrams, render

        for css, style in render._NODE_STYLES.items():
            assert diagrams.SYSML_STYLE[f" .{css} > rect"] == style
        for css, style in render._EDGE_STYLES.items():
            assert diagrams.SYSML_STYLE[f" .{css} > path"] == style
            expected_arrow = {"stroke": style["stroke"]}
            if render._EDGE_ENDS.get(css) == "hollow":
                # the specialization family (subclassification, feature
                # typing) gets HOLLOW triangle heads: white fill occludes
                # the line, the outline takes the edge color -- derived
                # from the same _EDGE_ENDS table the headless markers use
                expected_arrow["fill"] = "#ffffff"
            assert diagrams.SYSML_STYLE[f" .{css} > .elkarrow"] == expected_arrow
        for css, style in render._LABEL_STYLES.items():
            derived = diagrams.SYSML_STYLE[f" .{css} > text"]
            assert derived["fill"] == style["fill"]
            assert derived["font-size"] == f"{style['font-size']}px"
        guarded = diagrams.SYSML_STYLE[" .sysml-edge-guarded > path"]
        assert guarded == {"stroke-dasharray": render._GUARDED_DASHARRAY}

    def test_every_edge_kind_declares_an_arrowhead_form(self):
        """V3 companion: _EDGE_ENDS is the single source for arrowhead
        forms, so every styled edge kind must declare one (and only known
        forms), keeping the browser symbols and headless markers aligned."""

        from longeron import render

        assert set(render._EDGE_ENDS) == set(render._EDGE_STYLES)
        assert set(render._EDGE_ENDS.values()) <= {"hollow", "open", "none"}

    def test_replay_css_marker_reference_matches_fired_stroke(self):
        from longeron import render, replay

        assert f"stroke: {render._FIRED_STROKE};" in replay._CSS
        assert f"marker-end: url(#{render._arrow_id(render._FIRED_STROKE)});" in replay._CSS
        # ... and the headless SVG defs actually define that marker
        assert f'id="{render._arrow_id(render._FIRED_STROKE)}"' in render._arrow_defs()

    def test_replay_branch_highlight_uses_the_usage_green(self):
        from longeron import render, replay

        assert render._NODE_STYLES["sysml-usage"]["stroke"] in replay._CSS


class TestClientValidateStrictImports:
    """U6: Client.validate can express the server's strict_imports knob."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        pytest.importorskip("pyecore")
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        import shutil

        if shutil.which("git") is None:  # pragma: no cover - git-less machines
            pytest.skip("git executable not available")
        from starlette.testclient import TestClient

        from longeron.client import Client
        from longeron.server import create_app

        monkeypatch.setenv("LONGERON_CACHE_DIR", str(tmp_path / "cache"))
        root = tmp_path / "modelrepo"
        root.mkdir()
        # `Real` resolves only through the implicit stdlib hop -- visible
        # to validate(strict_imports=True), silent otherwise
        (root / "m.sysml").write_text(
            "package M { part def P { attribute mass : Real; } }", encoding="utf-8"
        )
        return Client(http=TestClient(create_app(root)))

    def test_default_stays_lenient(self, client):
        report = client.validate()
        assert report["errors"] == 0
        rules = {d.get("code") for d in report["diagnostics"]}
        assert "stdlib-implicit-name" not in rules

    def test_strict_imports_reaches_the_server(self, client):
        report = client.validate(strict_imports=True)
        rules = {d.get("code") for d in report["diagnostics"]}
        assert "stdlib-implicit-name" in rules
