"""The compact diagram toolbar and its search-and-highlight tool (headless)."""

import pytest

pytest.importorskip("ipyelk")

import ipywidgets as W
from ipyelk.tools import PipelineProgressBar, ToggleCollapsedTool

import longeron
from longeron import diagrams, toolbar
from longeron.render import _SYNTH_ID_PREFIX
from longeron.toolbar import (
    DIRECTIONS,
    FIT_PADDING,
    ROUTING_STYLES,
    SEARCH_ACTIVE_CSS,
    SEARCH_DIM_CSS,
    SEARCH_HIT_CSS,
    TOOLBAR_STYLE,
    AutoFitTool,
    DiagramSearch,
    DirectionTool,
    EdgeRoutingTool,
    _iter_edges,
    _iter_nodes,
    apply_direction,
    apply_routing,
)

_TYPED_SUBMACHINE = """
package P {
    state def Inner {
        entry; then a;
        state a;
        transition first a accept go then b;
        state b;
    }
    state def Outer {
        entry; then x;
        state x : Inner;
        transition first x accept quit then off;
        state off;
    }
}
"""


@pytest.fixture(scope="module")
def drone_model():
    return longeron.load("examples/drone.sysml")


@pytest.fixture()
def widget(drone_model):
    return diagrams.structure_diagram(drone_model)


def _search(widget) -> DiagramSearch:
    return widget.get_tool(DiagramSearch)


def _classes(element) -> set:
    return set((element.properties.cssClasses or "").split())


def _css_snapshot(root) -> dict:
    snap = {}
    for node in _iter_nodes(root):
        snap[id(node)] = node.properties.cssClasses
        for label in node.labels:
            snap[id(label)] = label.properties.cssClasses
    for edge in _iter_edges(root):
        snap[id(edge)] = edge.properties.cssClasses
    return snap


class TestComposition:
    def test_compact_icon_buttons(self, widget):
        cases = [
            (widget.view.fit_tool.ui, "expand"),
            (widget.view.center_tool.ui, "crosshairs"),
            (widget.get_tool(ToggleCollapsedTool).ui, "sitemap"),
        ]
        for button, icon in cases:
            assert isinstance(button, W.Button)
            assert button.description == ""  # icon-only
            assert button.icon == icon
            assert button.tooltip  # every control explains itself
            assert button.layout.width == "30px"

    def test_single_row_order(self, widget):
        kinds = [type(child).__name__ for child in widget.toolbar.children]
        # styled-widget css carrier, 3 icon buttons + the routing and
        # direction buttons, search box, progress, close
        assert kinds == [
            "HTML",
            "Button",
            "Button",
            "Button",
            "Button",
            "Button",
            "HBox",
            "FloatProgress",
            "Button",
        ]

    def test_every_control_has_a_tooltip(self, widget):
        search = _search(widget)
        box, count, clear = search.ui.children
        controls = [
            widget.view.fit_tool.ui,
            widget.view.center_tool.ui,
            widget.get_tool(ToggleCollapsedTool).ui,
            widget.get_tool(EdgeRoutingTool).ui,
            widget.get_tool(DirectionTool).ui,
            box,
            count,
            clear,
            widget.get_tool(PipelineProgressBar).bar,
            widget.toolbar.close_btn,
        ]
        assert all(control.tooltip for control in controls)

    def test_search_ui_is_compact(self, widget):
        box, _count, clear = _search(widget).ui.children
        assert isinstance(box, W.Text)
        assert box.continuous_update  # live, per keystroke
        assert box.layout.width == "150px"
        assert isinstance(clear, W.Button)
        assert clear.icon == "times"
        assert clear.layout.visibility == "hidden"  # only shown mid-search

    def test_all_views_get_the_toolbar(self, drone_model):
        widgets = [
            diagrams.structure_diagram(drone_model),
            diagrams.state_diagram(drone_model.find("Drone::FlightStates")),
            diagrams.action_diagram(drone_model.find("Drone::PlanBattery")),
            diagrams.diagram(drone_model.find("Drone::FlightStates")),
            diagrams.diagram(drone_model.find("Drone::PlanBattery")),
            diagrams.diagram(drone_model),
        ]
        for built in widgets:
            assert any(isinstance(tool, DiagramSearch) for tool in built.tools)
            assert any(isinstance(tool, EdgeRoutingTool) for tool in built.tools)
            assert any(isinstance(tool, DirectionTool) for tool in built.tools)
            assert any(isinstance(tool, AutoFitTool) for tool in built.tools)
            assert built.view.fit_tool.ui.icon == "expand"

    def test_classic_escape_hatch(self, drone_model):
        classic = diagrams.structure_diagram(drone_model, toolbar=False)
        assert not any(isinstance(tool, DiagramSearch) for tool in classic.tools)
        assert not any(isinstance(tool, EdgeRoutingTool) for tool in classic.tools)
        assert not any(isinstance(tool, DirectionTool) for tool in classic.tools)
        # ... but the one-shot initial fit is not toolbar chrome: every
        # widget starts centered and fitted, stock toolbar or not
        assert any(isinstance(tool, AutoFitTool) for tool in classic.tools)
        assert classic.view.fit_tool.ui.description == "Fit"  # the stock button
        assert not any(key in classic.style for key in TOOLBAR_STYLE)
        state = diagrams.state_diagram(drone_model.find("Drone::FlightStates"), toolbar=False)
        action = diagrams.action_diagram(drone_model.find("Drone::PlanBattery"), toolbar=False)
        for built in (state, action):
            assert not any(isinstance(tool, DiagramSearch) for tool in built.tools)

    def test_upgrade_is_idempotent(self, widget):
        before = list(widget.tools)
        assert toolbar.upgrade_toolbar(widget) is widget
        assert list(widget.tools) == before

    def test_style_rules_merged_and_scoped(self, widget):
        for key, rules in TOOLBAR_STYLE.items():
            assert widget.style[key] == rules
            assert key.startswith(" ")  # namespaced to this widget only
        assert f" .{SEARCH_HIT_CSS} > rect" in widget.style
        assert f" .{SEARCH_DIM_CSS} > rect" in widget.style
        # the base style is untouched by the merge
        assert widget.style[" .sysml-edge-typed > .elkarrow"]["fill"] == "#ffffff"


class TestEdgeRouting:
    """The routing button: cycles ORTHOGONAL -> POLYLINE -> SPLINES and
    re-lays the diagram out through the pipeline; the style persists per
    widget on the tool's trait and lands on every hierarchy level."""

    def _tool(self, widget) -> EdgeRoutingTool:
        return widget.get_tool(EdgeRoutingTool)

    def test_defaults_to_orthogonal(self, widget):
        tool = self._tool(widget)
        assert tool.routing == "ORTHOGONAL"
        assert widget.source.value.layoutOptions["elk.edgeRouting"] == "ORTHOGONAL"

    def test_compact_button(self, widget):
        tool = self._tool(widget)
        assert isinstance(tool.ui, W.Button)
        assert tool.ui.description == ""  # icon-only, like the stock trio
        assert tool.ui.icon == "share-alt"
        assert tool.ui.layout.width == "30px"
        assert "orthogonal" in tool.ui.tooltip and "polyline" in tool.ui.tooltip

    def test_click_cycles_through_all_styles_and_wraps(self, widget):
        tool = self._tool(widget)
        seen = []
        for _ in ROUTING_STYLES:
            tool.ui.click()
            seen.append(tool.routing)
        assert seen == ["POLYLINE", "SPLINES", "ORTHOGONAL"]  # full cycle

    def test_cycling_relays_out_through_the_pipeline(self, widget):
        """The collapse tool's refresh contract: the style lands on the
        source tree (root AND every compound node -- ELK does not inherit
        it through INCLUDE_CHILDREN), the pipe inlet is marked dirty with
        the layout-options flow, and on_done (Diagram.refresh) runs."""

        tool = self._tool(widget)
        refreshes = []
        tool.on_done = lambda: refreshes.append(True)
        tool.ui.click()
        assert tool.routing == "POLYLINE"
        root = widget.source.value
        assert root.layoutOptions["elk.edgeRouting"] == "POLYLINE"
        for node in _iter_nodes(root):
            if node.children:
                assert node.layoutOptions["elk.edgeRouting"] == "POLYLINE"
        assert "node.layoutOptions" in widget.pipe.inlet.flow
        assert refreshes == [True]

    def test_click_merges_with_the_pending_flow(self, widget):
        """Clicking must MERGE its flow with whatever is pending, never
        replace it: the initial ``("new",)`` flow is what wakes ipyelk's
        ValidationPipe (the null-id fixer).  Replacing it while the first
        browser layout was still in flight skipped validation forever --
        the raw tree reached the elkjs worker, whose import failed on
        every retry (JsonImportException) and starved the notebook."""

        assert widget.source.flow == ("new",)  # unconsumed initial flow
        tool = self._tool(widget)
        tool.ui.click()
        assert widget.pipe.inlet.flow == ("new", "node.layoutOptions")
        tool.ui.click()  # merging again adds nothing (ordered de-dupe)
        assert widget.pipe.inlet.flow == ("new", "node.layoutOptions")

    def test_routing_change_drops_stale_routes(self, widget):
        """A routing change invalidates every computed route: elkjs writes
        new routes INTO old section objects without clearing leftover keys
        (an orthogonal re-route keeps stale polyline bendPoints), so
        apply_routing drops sections to keep re-layouts idempotent."""

        from ipyelk.elements.elements import EdgeSection
        from ipyelk.elements.shapes import Point

        root = widget.source.value
        edge = next(_iter_edges(root))
        edge.sections = [
            EdgeSection(
                startPoint=Point(x=0, y=0),
                endPoint=Point(x=10, y=0),
                bendPoints=[Point(x=5, y=5)],
            )
        ]
        self._tool(widget).ui.click()
        assert all(edge.sections is None for edge in _iter_edges(root))

    def test_trait_can_be_set_directly(self, widget):
        tool = self._tool(widget)
        tool.routing = "splines"  # any case; normalized
        assert tool.routing == "SPLINES"
        assert widget.source.value.layoutOptions["elk.edgeRouting"] == "SPLINES"

    def test_unknown_style_rejected(self, widget):
        import traitlets

        tool = self._tool(widget)
        with pytest.raises(traitlets.TraitError, match="routing must be one of"):
            tool.routing = "bezier"
        assert tool.routing == "ORTHOGONAL"  # unchanged

    def test_choice_persists_per_widget(self, drone_model):
        first = diagrams.structure_diagram(drone_model)
        second = diagrams.structure_diagram(drone_model)
        self._tool(first).routing = "polyline"
        assert self._tool(first).routing == "POLYLINE"
        assert self._tool(second).routing == "ORTHOGONAL"  # untouched widget

    def test_constructor_kwarg_seeds_the_trait(self, drone_model):
        built = diagrams.structure_diagram(drone_model, routing="splines")
        assert self._tool(built).routing == "SPLINES"
        assert built.source.value.layoutOptions["elk.edgeRouting"] == "SPLINES"

    def test_apply_routing_helper_validates(self, widget):
        with pytest.raises(ValueError, match="routing must be one of"):
            apply_routing(widget.source.value, "bezier")


class TestDirectionToggle:
    """The orientation button: toggles the layout flow RIGHT (left-to-
    right) <-> DOWN (top-to-bottom) and re-lays the diagram out through
    the pipeline; the direction persists per widget on the tool's trait
    and lands on the ROOT only (elkjs carries elk.direction into nested
    compounds under INCLUDE_CHILDREN -- unlike routing and spacing)."""

    def _tool(self, widget) -> DirectionTool:
        return widget.get_tool(DirectionTool)

    def test_defaults_to_right(self, widget):
        tool = self._tool(widget)
        assert tool.direction == "RIGHT"
        assert widget.source.value.layoutOptions["elk.direction"] == "RIGHT"

    def test_compact_button_shows_the_active_flow(self, widget):
        tool = self._tool(widget)
        assert isinstance(tool.ui, W.Button)
        assert tool.ui.description == ""  # icon-only, like the stock trio
        assert tool.ui.icon == "long-arrow-right"
        assert tool.ui.layout.width == "30px"
        # the tooltip states the CURRENT flow and what a click does next
        assert "left-to-right" in tool.ui.tooltip and "top-to-bottom" in tool.ui.tooltip
        tool.direction = "down"
        assert tool.ui.icon == "long-arrow-down"
        assert tool.ui.tooltip.startswith("Layout direction: top-to-bottom")

    def test_click_toggles_and_wraps(self, widget):
        tool = self._tool(widget)
        seen = []
        for _ in DIRECTIONS:
            tool.ui.click()
            seen.append(tool.direction)
        assert seen == ["DOWN", "RIGHT"]  # a full round trip

    def test_toggling_relays_out_through_the_pipeline(self, widget):
        """The routing tool's refresh contract: the direction lands on the
        source tree, the pipe inlet is marked dirty with the layout-options
        flow, and on_done (Diagram.refresh) runs."""

        tool = self._tool(widget)
        refreshes = []
        tool.on_done = lambda: refreshes.append(True)
        tool.ui.click()
        assert tool.direction == "DOWN"
        root = widget.source.value
        assert root.layoutOptions["elk.direction"] == "DOWN"
        assert "node.layoutOptions" in widget.pipe.inlet.flow
        assert refreshes == [True]

    def test_direction_is_root_only(self, widget):
        """Pin the empirical INCLUDE_CHILDREN finding: elkjs carries
        elk.direction into nested compounds from the root (verified
        against real elkjs in test_render), so -- unlike edge routing --
        the option is NEVER restated per hierarchy level, and the
        SEPARATE_CHILDREN packing grids keep their own wide flow."""

        self._tool(widget).direction = "down"
        root = widget.source.value
        assert root.layoutOptions["elk.direction"] == "DOWN"
        for node in _iter_nodes(root):
            if node is not root:
                assert "elk.direction" not in node.layoutOptions

    def test_click_merges_with_the_pending_flow(self, widget):
        """Same contract as the routing tool: never clobber the pending
        ``("new",)`` flow that wakes ipyelk's ValidationPipe."""

        assert widget.source.flow == ("new",)  # unconsumed initial flow
        tool = self._tool(widget)
        tool.ui.click()
        assert widget.pipe.inlet.flow == ("new", "node.layoutOptions")
        tool.ui.click()  # merging again adds nothing (ordered de-dupe)
        assert widget.pipe.inlet.flow == ("new", "node.layoutOptions")

    def test_direction_change_drops_stale_routes(self, widget):
        """A direction change invalidates every computed route, exactly
        like a routing change (elkjs writes new routes INTO old section
        objects without clearing leftover keys)."""

        from ipyelk.elements.elements import EdgeSection
        from ipyelk.elements.shapes import Point

        root = widget.source.value
        edge = next(_iter_edges(root))
        edge.sections = [
            EdgeSection(
                startPoint=Point(x=0, y=0),
                endPoint=Point(x=10, y=0),
                bendPoints=[Point(x=5, y=5)],
            )
        ]
        self._tool(widget).ui.click()
        assert all(edge.sections is None for edge in _iter_edges(root))

    def test_trait_can_be_set_directly(self, widget):
        tool = self._tool(widget)
        tool.direction = "down"  # any case; normalized
        assert tool.direction == "DOWN"
        assert widget.source.value.layoutOptions["elk.direction"] == "DOWN"

    def test_unknown_direction_rejected(self, widget):
        import traitlets

        tool = self._tool(widget)
        with pytest.raises(traitlets.TraitError, match="direction must be right or down"):
            tool.direction = "diagonal"
        assert tool.direction == "RIGHT"  # unchanged

    def test_choice_persists_per_widget(self, drone_model):
        first = diagrams.structure_diagram(drone_model)
        second = diagrams.structure_diagram(drone_model)
        self._tool(first).direction = "down"
        assert self._tool(first).direction == "DOWN"
        assert self._tool(second).direction == "RIGHT"  # untouched widget

    def test_constructor_kwarg_seeds_the_trait(self, drone_model):
        for built in (
            diagrams.structure_diagram(drone_model, direction="down"),
            diagrams.state_diagram(drone_model.find("Drone::FlightStates"), direction="DOWN"),
            diagrams.action_diagram(drone_model.find("Drone::PlanBattery"), direction="Down"),
        ):
            assert self._tool(built).direction == "DOWN"
            assert built.source.value.layoutOptions["elk.direction"] == "DOWN"

    def test_flip_queues_a_one_shot_refit_but_routing_does_not(self, widget):
        """The flip inverts the aspect ratio, so ONE re-fit is queued for
        the relayout about to land; routing/collapse refreshes keep the
        user's viewport (the auto-fit stays spent)."""

        fit = widget.get_tool(AutoFitTool)
        fit.pending = False  # the initial fit has been consumed
        widget.get_tool(EdgeRoutingTool).ui.click()
        assert fit.pending is False  # routing keeps the viewport
        self._tool(widget).ui.click()
        assert fit.pending is True  # the flip re-centers once

    def test_apply_direction_helper_validates(self, widget):
        with pytest.raises(ValueError, match="direction must be right or down"):
            apply_direction(widget.source.value, "diagonal")


class TestCompoundLabelFit:
    """apply_direction's per-node companion (_fit_compound_labels): elkjs
    0.9.3 sizes EXPANDED compound nodes under a vertical flow in its
    internal horizontal coordinates -- the NODE_LABELS width contribution
    lands on the HEIGHT while the width collapses to children + padding,
    and elk.nodeSize.minimum is applied swapped, as (height, width).  The
    maintainer repro: QuadCopter's totalMass row past the node border
    after a top-down toggle (collapsing the node -- a LEAF, sized after
    the transposition -- made it fit).  So every direction change rewrites
    the compartment-bearing containers: vertical flows drop NODE_LABELS
    and pin the width through the swapped minimum; horizontal flows
    restore the diagrams._NODE_LAYOUT defaults."""

    def _node(self, widget, ident):
        return next(n for n in _iter_nodes(widget.source.value) if n.id == ident)

    def test_down_pins_compound_width_through_the_swapped_minimum(self, widget):
        apply_direction(widget.source.value, "down")
        quad = self._node(widget, "Drone::QuadCopter")
        assert quad.layoutOptions["nodeSize.constraints"] == "PORTS MINIMUM_SIZE"
        # (height, width): the widest pre-sized row + the box's side padding
        widest = max(
            label.properties.shape.width or 0
            for label in quad.labels
            if label.properties.shape is not None
        )
        assert quad.layoutOptions["elk.nodeSize.minimum"] == f"(44, {widest + 16:g})"

    def test_right_restores_the_node_layout_defaults(self, widget):
        root = widget.source.value
        apply_direction(root, "down")
        apply_direction(root, "right")
        quad = self._node(widget, "Drone::QuadCopter")
        assert quad.layoutOptions["nodeSize.constraints"] == "NODE_LABELS PORTS MINIMUM_SIZE"
        assert quad.layoutOptions["elk.nodeSize.minimum"] == "(60, 44)"

    def test_toggling_is_a_lossless_round_trip(self, widget):
        root = widget.source.value
        before = {node.id: dict(node.layoutOptions) for node in _iter_nodes(root) if node.children}
        for direction in ("down", "right", "down", "right"):
            apply_direction(root, direction)
        after = {node.id: dict(node.layoutOptions) for node in _iter_nodes(root) if node.children}
        assert after == before

    def test_leaves_are_never_touched(self, widget):
        apply_direction(widget.source.value, "down")
        battery = self._node(widget, "Drone::Battery")  # rows, but no children
        assert battery.layoutOptions["nodeSize.constraints"] == "NODE_LABELS PORTS MINIMUM_SIZE"
        assert battery.layoutOptions["elk.nodeSize.minimum"] == "(60, 44)"

    def test_pack_grid_compounds_keep_horizontal_defaults(self, widget):
        """SEPARATE_CHILDREN containers are sized by their OWN sub-run,
        which stays at the elkjs default horizontal flow whatever the
        root direction (see test_render's layout-truth twins) -- swapped
        minimums would land on the wrong axis of the wrong run."""

        apply_direction(widget.source.value, "down")
        states = self._node(widget, "Drone::FlightStates")  # inside the pack grid
        assert states.layoutOptions["nodeSize.constraints"] == "NODE_LABELS PORTS MINIMUM_SIZE"
        assert states.layoutOptions["elk.nodeSize.minimum"] == "(60, 44)"

    def test_grid_compound_itself_keeps_horizontal_defaults(self):
        """A compound whose loose children make IT the packing grid: the
        node carries SEPARATE_CHILDREN, so its own sub-run (horizontal)
        sizes it via NODE_LABELS even when the root flows top-down."""

        model = longeron.loads(
            """
            package Fit {
                part def Wide {
                    attribute total : Real = a.mass + b.mass + 4.0 * 0.06;
                    part a;
                    part b;
                }
            }
            """
        )
        built = diagrams.structure_diagram(model)
        apply_direction(built.source.value, "down")
        wide = self._node(built, "Fit::Wide")
        assert wide.layoutOptions["elk.hierarchyHandling"] == "SEPARATE_CHILDREN"
        assert wide.layoutOptions["nodeSize.constraints"] == "NODE_LABELS PORTS MINIMUM_SIZE"
        assert wide.layoutOptions["elk.nodeSize.minimum"] == "(60, 44)"

    def test_fit_constants_mirror_the_node_layout(self):
        """toolbar can't import diagrams (circular), so the fit constants
        restate diagrams._NODE_LAYOUT -- this pin breaks if they drift."""

        minimum = diagrams._NODE_LAYOUT["elk.nodeSize.minimum"].strip("()")
        assert tuple(float(part) for part in minimum.split(",")) == toolbar._NODE_MINIMUM
        padding = dict(
            part.split("=") for part in diagrams._NODE_LAYOUT["elk.padding"].strip("[]").split(",")
        )
        assert float(padding["left"]) + float(padding["right"]) == toolbar._NODE_SIDE_PADDING


class TestAutoFit:
    """The initial fit plus the widget's own fit sentinel: the first
    layout arrival from the browser answers with exactly one
    fit-to-screen request (small padding, zoom capped at 1:1, no
    animation); later relayouts keep the user's viewport unless a re-fit
    was explicitly queued.  The sentinel -- a hidden anywidget the
    builder mounts INSIDE the widget's own DOM -- reports fresh views,
    first reveals, and untouched-viewport resizes, each answered with an
    immediate re-fit that clears the browser-side user latch."""

    @staticmethod
    def _capture(widget) -> list:
        sent: list = []
        widget.view.fit = lambda **kwargs: sent.append(kwargs)
        return sent

    def test_first_layout_arrival_fits_exactly_once(self, widget):
        tool = widget.get_tool(AutoFitTool)
        sent = self._capture(widget)
        assert tool.pending and tool.fit_count == 0  # armed, not fired
        widget.view.source.value = widget.source.value  # first layout lands
        assert tool.fit_count == 1 and not tool.pending
        assert sent == [{"animate": False, "max_zoom": 1.0, "padding": FIT_PADDING}]
        # the margin keeps the diagram off the viewport limits
        assert FIT_PADDING > 0

    def test_subsequent_relayouts_keep_the_viewport(self, widget):
        tool = widget.get_tool(AutoFitTool)
        sent = self._capture(widget)
        widget.view.source.value = widget.source.value
        widget.view.source.value = None  # the browser clearing/replacing
        widget.view.source.value = widget.source.value  # a relayout lands
        assert tool.fit_count == 1 and len(sent) == 1  # once, ever

    def test_request_refit_arms_exactly_one_more(self, widget):
        tool = widget.get_tool(AutoFitTool)
        sent = self._capture(widget)
        widget.view.source.value = widget.source.value
        tool.request_refit()
        assert tool.pending
        widget.view.source.value = None
        widget.view.source.value = widget.source.value
        widget.view.source.value = None
        widget.view.source.value = widget.source.value
        assert tool.fit_count == 2 and len(sent) == 2

    def test_none_arrivals_never_consume_the_fit(self, widget):
        tool = widget.get_tool(AutoFitTool)
        sent = self._capture(widget)
        widget.view.source.value = None
        assert tool.pending and not sent  # still armed for the real tree

    def test_headless_render_is_unaffected(self, drone_model, tmp_path):
        """to_svg never constructs tools or sends fit requests -- the
        headless path only reads the widget's source tree."""

        from longeron import render

        widget = diagrams.structure_diagram(drone_model)
        sent = self._capture(widget)
        render.to_svg(widget, tmp_path / "out.svg")
        assert sent == []

    # -- the fit sentinel: universal fit-on-reveal/resize ------------------

    def test_builder_mounts_the_sentinel_inside_the_widget(self, widget):
        # the sentinel rides INSIDE the widget's own DOM (a hidden child
        # beside the view + toolbar): plain display(widget) gets
        # fit-on-reveal/resize with ZERO consumer wiring
        tool = widget.get_tool(AutoFitTool)
        assert tool.sentinel is not None
        assert tool.sentinel in widget.children
        assert tool.sentinel.layout.display == "none"
        assert (tool.sentinel.fresh, tool.sentinel.resized, tool.sentinel.fit_stamp) == (0, 0, 0)
        # the widget's root node carries the sentinel's DOM handle
        assert "lgx-diagram" in widget._dom_classes

    def test_sentinel_is_not_toolbar_chrome(self, drone_model):
        # toolbar=False keeps the stock ipyelk toolbar but never loses
        # the self-fitting machinery
        classic = diagrams.structure_diagram(drone_model, toolbar=False)
        tool = classic.get_tool(AutoFitTool)
        assert tool.sentinel is not None and tool.sentinel in classic.children
        assert "lgx-diagram" in classic._dom_classes

    def test_fresh_view_report_refits_immediately(self, widget):
        # a new sprotty view materialized with laid-out nodes: the moment
        # a fit is deliverable (the first-layout fit can be dropped while
        # the view is still constructing -- the cropped-diagram bug)
        tool = widget.get_tool(AutoFitTool)
        sent = self._capture(widget)
        before = tool.fit_count
        tool.sentinel.fresh += 1  # what the browser reports
        assert tool.fit_count == before + 1 and len(sent) == 1

    def test_resize_report_refits_immediately(self, widget):
        # a debounced, latch-guarded resize (HBox squeeze, dock drag,
        # reveal of a widget born hidden): re-fit against the new size
        tool = widget.get_tool(AutoFitTool)
        sent = self._capture(widget)
        before = tool.fit_count
        tool.sentinel.resized += 1
        assert tool.fit_count == before + 1 and len(sent) == 1

    def test_every_kernel_fit_clears_the_user_latch(self, widget):
        # fit_stamp is the kernel -> browser latch-clear signal: bumped
        # per auto-fit, whatever triggered it (first layout, sentinel
        # report, an explicit refit_now)
        tool = widget.get_tool(AutoFitTool)
        self._capture(widget)
        assert tool.sentinel.fit_stamp == 0
        widget.view.source.value = widget.source.value  # first layout lands
        assert tool.sentinel.fit_stamp == 1
        tool.refit_now()
        assert tool.sentinel.fit_stamp == 2
        tool.sentinel.resized += 1
        assert tool.sentinel.fit_stamp == 3

    def test_sentinel_reports_are_safe_without_a_view(self, widget):
        # refit_now degrades gracefully when the fit message has nowhere
        # to go (no frontend view yet): never an exception in the
        # sentinel's observer chain
        tool = widget.get_tool(AutoFitTool)
        tool.sentinel.fresh += 1  # must not raise (headless: no view)
        tool.sentinel.resized += 1


class TestSearchMatching:
    def test_title_match_is_case_insensitive(self, widget):
        search = _search(widget)
        search.query = "BATTERY"
        assert search.hit_ids == {
            "Drone::Battery",
            "Drone::PlanBattery",  # title 'PlanBattery' contains 'battery'
            "Drone::MultiRotor::battery",  # the shared pack, on the base
        }
        assert search.match_count == 3

    def test_qualified_name_match(self, widget):
        search = _search(widget)
        search.query = "quadcopter::motors"  # no title contains this
        assert search.hit_ids == {"Drone::QuadCopter::motors"}

    def test_usage_titles_include_their_type(self, widget):
        search = _search(widget)
        search.query = "motor"
        # the def by title, the usages via 'motors : Motor [4]' etc. --
        # the TriCopter split its population into front pair + tail
        assert search.hit_ids == {
            "Drone::Motor",
            "Drone::MotorCurrent",
            "Drone::QuadCopter::motors",
            "Drone::TriCopter::frontMotors",
            "Drone::TriCopter::tailMotor",
        }

    def test_count_is_displayed(self, widget):
        search = _search(widget)
        search.query = "battery"
        assert f">{search.match_count}/{search.total_count}<" in search._count_html.value
        assert search.total_count > search.match_count > 0

    def test_zero_matches_still_reported(self, widget):
        search = _search(widget)
        search.query = "no such thing anywhere"
        assert search.match_count == 0
        assert f">0/{search.total_count}<" in search._count_html.value

    def test_attribute_rows_are_not_titles(self, widget):
        search = _search(widget)
        search.query = "capacity"  # only appears in an attribute compartment
        assert search.match_count == 0

    def test_whitespace_query_is_inactive(self, widget):
        search = _search(widget)
        search.query = "   "
        assert search.match_count == 0
        assert search._count_html.value == ""  # not a zero-match search
        assert not any(
            SEARCH_DIM_CSS in _classes(node) for node in _iter_nodes(widget.source.value)
        )

    def test_expanded_submachine_instance_ids_match(self):
        model = longeron.loads(_TYPED_SUBMACHINE)
        built = diagrams.state_diagram(model.find("P::Outer"))
        search = _search(built)
        search.query = "x::a"  # instance-qualified: unique per expansion site
        assert search.hit_ids == {"P::Outer::x::a"}
        node = next(n for n in _iter_nodes(built.source.value) if n.id == "P::Outer::x::a")
        assert SEARCH_HIT_CSS in _classes(node)

    def test_markers_are_not_searchable(self, drone_model):
        built = diagrams.state_diagram(drone_model.find("Drone::FlightStates"))
        search = _search(built)
        marker_free = {entry.node_id for entry in search._entries}
        markers = [n for n in _iter_nodes(built.source.value) if "sysml-marker" in _classes(n)]
        assert markers
        assert all(n.id not in marker_free for n in markers)


class TestHighlightApplication:
    def test_hits_and_dims_on_nodes_and_labels(self, widget):
        search = _search(widget)
        search.query = "battery"
        for node in _iter_nodes(widget.source.value):
            if not node.id or str(node.id).startswith(_SYNTH_ID_PREFIX):
                continue  # transport-only ids: never searched, never marked
            classes = _classes(node)
            expected = SEARCH_HIT_CSS if node.id in search.hit_ids else SEARCH_DIM_CSS
            other = SEARCH_DIM_CSS if expected == SEARCH_HIT_CSS else SEARCH_HIT_CSS
            assert expected in classes and other not in classes
            for label in node.labels:  # labels carry the state for text css
                assert expected in _classes(label)

    def test_markers_and_packing_groups_untouched(self, drone_model):
        built = diagrams.state_diagram(drone_model.find("Drone::FlightStates"))
        search = _search(built)
        search.query = "idle"
        for node in _iter_nodes(built.source.value):
            if "sysml-marker" in _classes(node) or "sysml-packgroup" in _classes(node):
                assert SEARCH_HIT_CSS not in _classes(node)
                assert SEARCH_DIM_CSS not in _classes(node)

    def test_edges_dim_while_searching(self, widget):
        search = _search(widget)
        search.query = "battery"
        real, packing = [], []
        for edge in _iter_edges(widget.source.value):
            (real if "sysml-edge" in _classes(edge) else packing).append(edge)
        assert real and packing
        assert all(SEARCH_DIM_CSS in _classes(edge) for edge in real)
        # layout-only packing chains are invisible: never touched
        assert all(SEARCH_DIM_CSS not in _classes(edge) for edge in packing)

    def test_clear_restores_exactly(self, widget):
        pristine = _css_snapshot(widget.source.value)
        search = _search(widget)
        search.query = "battery"
        assert _css_snapshot(widget.source.value) != pristine
        search.query = ""
        assert _css_snapshot(widget.source.value) == pristine
        assert search._count_html.value == ""
        assert search._clear_btn.layout.visibility == "hidden"

    def test_clear_button_clears(self, widget):
        search = _search(widget)
        search.query = "battery"
        assert search._clear_btn.layout.visibility == "visible"
        search._clear_btn.click()
        assert search.query == ""
        assert search.match_count == 0

    def test_search_never_fires_on_select(self, widget, drone_model):
        received: list = []
        diagrams.on_select(widget, drone_model, received.extend)
        search = _search(widget)
        search.query = "battery"
        search.query = "rotor"
        search.query = ""
        assert received == []  # the registered callback MUST NOT be called
        assert widget.view.selection.ids == ()

    def test_search_never_marks_the_pipeline_dirty(self, widget):
        flow_before = widget.source.flow
        search = _search(widget)
        search.query = "battery"
        search.query = ""
        assert widget.source.flow == flow_before

    def test_toolbar_pins_while_search_active(self, widget):
        search = _search(widget)
        search.query = "battery"
        assert SEARCH_ACTIVE_CSS in widget.toolbar._dom_classes
        search.query = ""
        assert SEARCH_ACTIVE_CSS not in widget.toolbar._dom_classes
        assert f" .jp-ElkToolbar.{SEARCH_ACTIVE_CSS}" in widget.style

    def test_highlight_survives_view_tree_replacement(self, widget):
        """When the browser hands back a new post-layout tree, an active
        search re-applies to it (and clearing cleans both trees)."""

        from ipyelk.elements import Registry, convert_elkjson
        from ipyelk.elements import index as elk_index

        search = _search(widget)
        search.query = "battery"
        with Registry():
            replacement = convert_elkjson(widget.source.value.dict())
            for element in elk_index.iter_elements(replacement):
                element.id = element.get_id()
        widget.view.source.value = replacement  # what the frontend does

        view_tree = widget.view.source.value
        hit = next(n for n in _iter_nodes(view_tree) if n.id == "Drone::Battery")
        assert SEARCH_HIT_CSS in _classes(hit)
        # markers got uuid ids in the round-trip: still untouched
        for node in _iter_nodes(view_tree):
            if node.id not in {entry.node_id for entry in search._entries}:
                assert SEARCH_HIT_CSS not in _classes(node)
                assert SEARCH_DIM_CSS not in _classes(node)

        search.query = ""
        for tree in (widget.source.value, widget.view.source.value):
            for node in _iter_nodes(tree):
                assert SEARCH_HIT_CSS not in _classes(node)
                assert SEARCH_DIM_CSS not in _classes(node)

    def test_search_after_view_tree_exists_updates_both(self, widget):
        from ipyelk.elements import Registry, convert_elkjson

        with Registry():
            widget.view.source.value = convert_elkjson(widget.source.value.dict())
        search = _search(widget)
        search.query = "motor"
        for tree in (widget.source.value, widget.view.source.value):
            ids = {n.id for n in _iter_nodes(tree) if SEARCH_HIT_CSS in _classes(n)}
            assert ids == {
                "Drone::Motor",
                "Drone::MotorCurrent",
                "Drone::QuadCopter::motors",
                "Drone::TriCopter::frontMotors",
                "Drone::TriCopter::tailMotor",
            }
