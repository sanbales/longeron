"""Adversarial-review LOW fixes: U4 (parse errors), U6 (client.validate),
V3 (single-source palette)."""

from __future__ import annotations

from pathlib import Path

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

        selected = "var(--jp-elk-color-selected)"
        for css, style in render._NODE_STYLES.items():
            attrs = {key: value for key, value in style.items() if key != "shape"}
            shape = style.get("shape")
            if shape is None:
                assert diagrams.SYSML_STYLE[f" .{css} > rect"] == attrs
            elif shape == "diamond":
                derived = diagrams.SYSML_STYLE[f" .{css} > polygon"]
                assert derived["fill"] == attrs["fill"]
                assert derived["stroke"] == attrs["stroke"]
            elif shape == "note":  # comment/doc notes: folded-corner path + crease
                derived = diagrams.SYSML_STYLE[f" .{css} > path"]
                assert derived["fill"] == attrs["fill"]
                assert derived["stroke"] == attrs["stroke"]
            elif shape == "actor":  # stick figure: head circle + limbs path
                figure = diagrams.SYSML_STYLE[f" .{css} .glyph-actor"]
                assert figure["stroke"] == attrs["stroke"]
                head = diagrams.SYSML_STYLE[f" .{css} .glyph-actor-head"]
                assert head["fill"] == attrs["fill"]
                # the figure is the node BODY: selection recolors AND
                # thickens it on the same theme variables as the rects
                state = diagrams.SYSML_STYLE[f" .{css} > .elknode.selected .glyph-actor"]
                assert state["stroke"] == selected
                assert state["stroke-width"] == "var(--jp-elk-stroke-width-selected)"
            else:  # bullseye / circle-x: circle ring + inner glyph
                assert shape in ("bullseye", "circle-x")
                ring = diagrams.SYSML_STYLE[f" .{css} .glyph-ring"]
                assert ring["stroke"] == attrs["stroke"]
                # selection recolors the ring stroke, never its fill
                assert (
                    diagrams.SYSML_STYLE[f" .{css} > .elknode.selected .glyph-ring"]["stroke"]
                    == selected
                )
        for css, style in render._EDGE_STYLES.items():
            assert diagrams.SYSML_STYLE[f" .{css} > path"] == style
            derived = diagrams.SYSML_STYLE[f" .{css} > .elkarrow"]
            assert derived["stroke"] == style["stroke"]
            end_form = render._EDGE_ENDS.get(css, "")
            start_form = render._EDGE_STARTS.get(css)
            if end_form.startswith("hollow"):
                # the specialization family gets HOLLOW closed-triangle
                # heads: white fill occludes the line, the outline takes
                # the edge color -- derived from the same _EDGE_ENDS table
                # the headless markers use
                assert derived["fill"] == "#ffffff"
                if end_form != "hollow":
                    # adorned heads: filled dots/tick draw with currentColor
                    assert derived["color"] == style["stroke"]
            if end_form == "filled":
                # port-attached flow arrowheads: FILLED family, fill bound
                # to the stroke, selection flips both (contract rule 3)
                assert derived["fill"] == style["stroke"]
                selected_arrow = diagrams.SYSML_STYLE[f" .elkedge.{css}.selected > .elkarrow"]
                assert selected_arrow["fill"] == selected
            if start_form == "filled-diamond":
                # filled family: fill is BOUND to the stroke, and selection
                # flips both together (contract rule 3)
                assert derived["fill"] == style["stroke"]
                selected_arrow = diagrams.SYSML_STYLE[f" .elkedge.{css}.selected > .elkarrow"]
                assert selected_arrow["fill"] == selected
            elif start_form in ("hollow-diamond", "circle", "circle-plus"):
                # hollow family (referential diamonds, membership circles):
                # white bodies forever; the circle-plus cross strokes are
                # self-painted currentColor, bound to the edge stroke
                assert derived["fill"] == "#ffffff"
                assert derived["color"] == style["stroke"]
        for css, style in render._LABEL_STYLES.items():
            derived = diagrams.SYSML_STYLE[f" .{css} > text"]
            assert derived["fill"] == style["fill"]
            assert derived["font-size"] == f"{style['font-size']}px"
        guarded = diagrams.SYSML_STYLE[" .sysml-edge-guarded > path"]
        assert guarded == {"stroke-dasharray": render._GUARDED_DASHARRAY}

    def test_every_edge_kind_declares_an_arrowhead_form(self):
        """V3 companion: _EDGE_ENDS / _EDGE_STARTS are the single source for
        endpoint glyph forms, so every styled edge kind must declare an end
        form (and only known forms), and every start glyph must belong to a
        styled kind -- keeping the browser symbols and headless markers
        aligned."""

        from longeron import render

        assert set(render._EDGE_ENDS) == set(render._EDGE_STYLES)
        assert set(render._EDGE_ENDS.values()) <= {
            "hollow",
            "hollow-colon",
            "hollow-tick",
            "hollow-dcolon",
            "open",
            "none",
            "pin-arrow",  # flow target-input pin + filled arrowhead (E16)
            "filled",  # filled arrowhead alone: flows attached to drawn ports
            "ball-notch",  # portion-membership ball at the whole end
        }
        assert set(render._EDGE_STARTS) <= set(render._EDGE_STYLES)
        assert set(render._EDGE_STARTS.values()) <= {
            "filled-diamond",
            "hollow-diamond",
            "pin",  # flow source-output pin (E16)
            "circle",  # alias/unowned-membership circle (E18)
            "circle-plus",  # owned-membership circled plus at the owning end (E18)
        }
        # a start glyph and a hollow end on one kind would fight over the
        # single .elkarrow fill rule -- the palette forbids the combination.
        # The flow pins are exempt: both pin symbols are self-painted raw
        # SVG (explicit white body + currentColor), so no fill rule applies.
        for css, form in render._EDGE_STARTS.items():
            if form == "pin":
                assert render._EDGE_ENDS[css] == "pin-arrow"
            else:
                assert render._EDGE_ENDS[css] == "none"

    def test_arrowheads_share_the_slender_spec_proportions(self):
        """Item 9: every head keeps ~2:1 length:half-width (the spec's
        slender ~27-degree heads, never 45 degrees) -- single-sourced
        constants that BOTH pipelines derive from."""

        from longeron import render

        for length, half in (
            (render._HEAD_LENGTH, render._HEAD_HALF),
            (render._V_LENGTH, render._V_HALF),
            (render._FLOW_HEAD_LENGTH, render._FLOW_HEAD_HALF),
        ):
            assert 2.0 <= length / half <= 2.5
        # headless markers derive from the constants
        defs = render._arrow_defs()
        v = render._V_LENGTH, render._V_HALF
        assert f'd="M 0 1 L {v[0]:g} {v[1] + 1:g} L 0 {2 * v[1] + 1:g}"' in defs
        tri = render._HEAD_LENGTH, render._HEAD_HALF
        assert f"L {1 + tri[0]:g} {tri[1] + 1:g} L 1 {2 * tri[1] + 1:g} z" in defs

    def test_browser_symbols_mirror_the_marker_geometry(self):
        """Item 9 (browser side): the EndpointSymbol paths derive from the
        SAME slenderness constants as the headless markers -- the vendored
        45-degree StraightArrow is out."""

        pytest.importorskip("ipyelk")
        from longeron import diagrams, render

        library = diagrams._symbols().library
        tri = library["generalization"].element.properties.shape.use
        assert f"{render._HEAD_LENGTH},{-render._HEAD_HALF}" in tri  # 'M10.0,-5.0...'
        v = library["arrow"].element.properties.shape.use
        assert f"{render._V_LENGTH},{-render._V_HALF}" in v
        # the adorned triangle SVG shares the geometry too
        adorned = diagrams._specialization_svg("colon")
        assert f"M {render._HEAD_LENGTH:g},{-render._HEAD_HALF:g} L 0,0" in adorned

    def test_browser_symbols_cover_every_declared_form(self):
        """Every end/start form maps to a registered browser symbol, so the
        two pipelines cannot drift (the symbol id doubles as the .elkarrow
        CSS hook)."""

        pytest.importorskip("ipyelk")
        from longeron import diagrams, render

        library = diagrams._symbols().library
        for form in set(render._EDGE_ENDS.values()) - {"none"}:
            assert diagrams._END_SYMBOLS[form] in library
        for form in set(render._EDGE_STARTS.values()):
            assert diagrams._START_SYMBOLS[form] in library
        for badge in ("accept-badge", "send-badge"):
            assert badge in library

    def test_node_glyph_classes_are_styled(self):
        """Every glyph node family declares a node style (the headless
        drawer and the derived browser CSS both key off it)."""

        from longeron import render

        for css in render._GLYPH_NODE_CLASSES:
            assert css in render._NODE_STYLES
        assert render._NODE_STYLES["sysml-ctrl-diamond"]["shape"] == "diamond"
        assert render._NODE_STYLES["sysml-final"]["shape"] == "bullseye"
        assert render._NODE_STYLES["sysml-terminate"]["shape"] == "circle-x"
        assert "shape" not in render._NODE_STYLES["sysml-ctrl-bar"]  # a rect
        # the n-ary dependency junction is a filled dot in the family hue
        assert render._NODE_STYLES["sysml-junction"]["fill"] == "#a85c78"
        # the n-ary CONNECTION junction stays in the connector-family gray
        assert render._NODE_STYLES["sysml-connjunction"]["fill"] == "#555555"
        # swim lanes carry a dashed boundary in BOTH pipelines (the style
        # table's dasharray reaches the headless rect and the browser CSS)
        assert render._NODE_STYLES["sysml-lane"]["stroke-dasharray"] == "4 3"

    def test_port_styles_derive_from_node_palette(self):
        """Item 11: ports (and ipyelk's collapse stubs -- 'slack' ports)
        take the OWNING node kind's stroke color with a white body; stroke
        widths stay pinned and selection recolors the fill (rule 4)."""

        pytest.importorskip("ipyelk")
        from longeron import diagrams, render

        selected = "var(--jp-elk-color-selected)"
        pinned = "var(--jp-elk-stroke-width)"
        assert diagrams.SYSML_STYLE[" .elkport"]["fill"] == "#ffffff"
        assert diagrams.SYSML_STYLE[" .elkport"]["stroke-width"] == pinned
        assert diagrams.SYSML_STYLE[" .elkport.selected"]["stroke-width"] == pinned
        # direction arrows (currentColor geometry inside the square)
        # recolor to white against the selection fill; the FILLED proxy
        # dot follows the selection color instead (rule 3)
        assert diagrams.SYSML_STYLE[" .elkport.selected"]["color"] == "#ffffff"
        assert diagrams.SYSML_STYLE[" .elkport.port-proxy.selected"]["color"] == selected
        assert diagrams.SYSML_STYLE[" .elkport.mouseover"]["stroke-width"] == pinned
        for css, style in render._NODE_STYLES.items():
            assert diagrams.SYSML_STYLE[f" .{css} .elkport"]["stroke"] == style["stroke"]
            # currentColor binds the direction glyph to the node stroke
            assert diagrams.SYSML_STYLE[f" .{css} .elkport"]["color"] == style["stroke"]
            derived = diagrams.SYSML_STYLE[f" .{css} .elkport.selected"]
            assert derived["fill"] == selected
            assert derived["stroke-width"] == pinned
        # the package folder tab: explicit paints ride the symbol geometry
        # (<use> shadow content -- the theme's .elklabel rule would
        # otherwise win), with the outline in currentColor BOUND to the
        # package stroke here, so selection recolors the tab with the box;
        # the outline WIDTH binds through the adornment contract's custom
        # property (which inherits into the shadow) to the SAME theme
        # width variables as the rect, so the folder thickens as one
        # silhouette in every state (see test_diagrams's adornment tests)
        assert diagrams.SYSML_STYLE[" .package-tab"] == {
            "color": render._NODE_STYLES["sysml-package"]["stroke"],
        }
        assert diagrams.SYSML_STYLE[" .sysml-adornment"] == {
            "--lgn-adorn-stroke-width": "var(--jp-elk-stroke-width)",
        }
        selected_adorn = diagrams.SYSML_STYLE[" .elklabel.sysml-adornment.selected"]
        assert selected_adorn == {
            "color": selected,
            "--lgn-adorn-stroke-width": "var(--jp-elk-stroke-width-selected)",
        }

    def test_label_kinds_keep_their_measured_font_sizes_in_the_browser(self):
        """Item 12: the blanket 11px !important label rule (needed against
        theme fonts) must not inflate the 10px/9px label kinds the boxes
        were measured for -- per-kind higher-specificity rules restate the
        measured sizes, and selection still recolors."""

        pytest.importorskip("ipyelk")
        from longeron import diagrams, render

        assert diagrams.SYSML_STYLE[" text.elklabel"]["font-size"] == "11px !important"
        for css, style in render._LABEL_STYLES.items():
            derived = diagrams.SYSML_STYLE[f" text.elklabel.{css}"]
            assert derived["font-size"] == f"{style['font-size']}px !important"
            assert derived["fill"] == style["fill"]
            selected = diagrams.SYSML_STYLE[f" text.elklabel.{css}.selected"]
            assert selected["fill"] == "var(--jp-elk-color-selected)"

    def test_edge_end_clearance_covers_every_glyph_reach(self):
        """Nit 5 single-source: the layout clearance both pipelines restate
        per hierarchy level must cover the longest endpoint glyph, so no
        orthogonal bend can ever fall under a head (or leave shaft
        adornments floating off a turned line)."""

        from longeron import render

        worst_head = render._HEAD_LENGTH + max(render._ADORN_TAIL.values())
        assert render._EDGE_END_CLEARANCE >= worst_head
        assert render._EDGE_END_CLEARANCE >= render._DIAMOND_LENGTH
        assert render._EDGE_END_CLEARANCE >= render._PIN_SIZE + render._FLOW_HEAD_LENGTH
        assert render._EDGE_END_CLEARANCE >= 2 * render._CIRCLE_RADIUS
        assert render._EDGE_END_CLEARANCE >= render._V_LENGTH
        pytest.importorskip("ipyelk")
        from longeron import diagrams

        assert diagrams._ROOT_LAYOUT["elk.layered.spacing.edgeNodeBetweenLayers"] == (
            f"{render._EDGE_END_CLEARANCE:g}"
        )

    def test_replay_css_marker_reference_matches_fired_stroke(self):
        from longeron import render, replay

        assert f"stroke: {render._FIRED_STROKE};" in replay._CSS
        assert f"marker-end: url(#{render._arrow_id(render._FIRED_STROKE)});" in replay._CSS
        # ... and the headless SVG defs actually define that marker
        assert f'id="{render._arrow_id(render._FIRED_STROKE)}"' in render._arrow_defs()

    def test_replay_branch_highlight_uses_the_usage_green(self):
        from longeron import render, replay

        assert render._NODE_STYLES["sysml-usage"]["stroke"] in replay._CSS


class TestLabextensionServingSync:
    """The 'rebuilt the TS but the fix didn't take' footgun: JupyterLab
    serves the COPY of the vendored jupyter-elk labextension that pixi
    made inside each env at install time, not vendor/ipyelk itself.  The
    `sync-labextension` task (a `lab` dependency, mirrored in the
    Makefile) rsyncs the vendor build over every served copy, warning
    when one was stale."""

    ROOT = Path(__file__).resolve().parent.parent
    VENDOR = ROOT / "vendor/ipyelk/src/_d/share/jupyter/labextensions/@jupyrdf/jupyter-elk"

    def test_pixi_lab_depends_on_the_sync_task(self):
        import re

        # plain-text asserts: tomllib is stdlib only from python 3.11, and
        # this test runs on the full version matrix
        text = (self.ROOT / "pyproject.toml").read_text(encoding="utf-8")
        sync = re.search(r"\[tool\.pixi\.tasks\.sync-labextension\]\n(.*?)(?:\n\[|\Z)", text, re.S)
        block = sync.group(1) if sync else text  # inline-table form falls back
        # vendor build -> every served env copy, loudly when one was stale
        assert "vendor/ipyelk/src/_d/share/jupyter/labextensions" in block
        assert ".pixi/envs/*/share/jupyter/labextensions" in block
        assert "rsync" in block and "--delete" in block
        assert "STALE" in block  # the warning that makes the footgun visible
        lab = re.search(r"^lab\s*=\s*\{.*?\}\s*$", text, re.M | re.S)
        assert lab is not None and "sync-labextension" in lab.group(0)

    def test_makefile_mirrors_the_task(self):
        makefile = (self.ROOT / "Makefile").read_text(encoding="utf-8")
        assert "sync-labextension:" in makefile
        assert "vendor/ipyelk/src/_d/share/jupyter/labextensions" in makefile
        assert "rsync" in makefile and "STALE" in makefile

    def test_vendor_build_carries_the_tangent_fix(self):
        """Item-5 re-verification: the SHIPPED vendored bundle (the one
        the sync task serves) really contains the compiled arc-length
        tangent fix -- routeEndAngle/coveredRoutePoints survive in the
        elkdisplay chunk's source map names."""

        maps = sorted(self.VENDOR.glob("static/elkdisplay.*.js.map"))
        assert maps, "the vendored labextension build is missing"
        text = maps[-1].read_text(encoding="utf-8")
        assert "routeEndAngle" in text and "coveredRoutePoints" in text


class TestVendoredHoverAttribution:
    """Hover parity direction (b): hovering a node's LABEL (the package
    folder tab, a badge, the title text) must highlight the owning node.
    ipyelk's DragAwareHoverMouseListener sent HoverFeedbackAction with the
    RAW event target's id -- for labels that is the label element, which
    has no hoverFeedbackFeature, so sprotty's HoverFeedbackCommand
    silently dropped the action (maintainer repro: hovering the tab gave
    no feedback at all).  The vendored listener now resolves the nearest
    HOVERABLE ancestor -- exactly how sprotty core's HoverMouseListener
    and ipyelk's own select tool attribute their targets -- so hover and
    selection agree on what a shape is.  (Source-level guard; the shipped
    bundle picks the fix up at the next vendor rebuild + sync.)"""

    LISTENER = (
        Path(__file__).resolve().parent.parent
        / "vendor/ipyelk/js/tools/draw-aware-mouse-listener.ts"
    )

    def test_hover_feedback_targets_the_nearest_hoverable_ancestor(self):
        source = self.LISTENER.read_text(encoding="utf-8")
        # both directions of the hover pair resolve through the feature
        # walk; neither ships the raw target id any more
        assert source.count("findParentByFeature(target, isHoverable)") == 2
        assert "mouseoverElement: hoverTarget.id" in source
        assert "mouseoverElement: target.id" not in source


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
