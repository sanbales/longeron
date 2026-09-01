"""3D RDF graph explorer: view extraction, layout, colors, widget seams
(needs rdflib; widget tests additionally need anywidget + numpy).  The
front-end needs a browser -- ESM contracts are asserted textually, the
house pattern of test_analysis_viewer3d."""

import json
from pathlib import Path

import pytest

import longeron

rdflib = pytest.importorskip("rdflib")

from longeron import rdf  # noqa: E402  (import after the rdflib guard)
from longeron.widgets import graph3d  # noqa: E402

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def model():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


@pytest.fixture(scope="module")
def graph(model):
    return rdf.to_graph(model)


@pytest.fixture(scope="module")
def view(graph):
    return graph3d.graph_view(graph)


def node(view, node_id):
    return next(entry for entry in view["nodes"] if entry["id"] == node_id)


class TestGraphView:
    def test_default_view_counts_match_the_projection(self, graph, view):
        """Nodes are the typed subjects; edges the relationship triples
        (both ends typed; the self-loop skip is defensive only -- the
        projection resolves shadowed redefinition targets) -- computed
        independently.
        The counts include the deepscout SourceEvidence citations:
        evidence metadata rides the RDF projection like everything else."""

        sysml = rdflib.Namespace(rdf.VOCABULARY)
        typed = set(graph.subjects(rdflib.RDF.type, None))
        edges = {
            (s, o, family)
            for predicate, family in graph3d._EDGE_FAMILIES.items()
            for s, o in graph.subject_objects(sysml[predicate])
            if s in typed and o in typed and s != o
        }
        assert len(view["nodes"]) == len(typed) == 1569
        assert len(view["edges"]) == len(edges) == 1916

    def test_literals_fold_into_hover_info(self, view):
        mass = node(view, "Rotorcraft::BoxQuad::mass")
        assert "value: 0.78" in mass["info"]
        assert "kind: attribute" in mass["info"]

    def test_kind_colors_speak_the_explorer_chip_language(self, view):
        assert node(view, "Rotorcraft")["color"] == "#6d6d6d"  # package
        assert node(view, "DeepScout::Airframe")["color"] == "#3d6fb4"  # structure
        assert node(view, "DeepScout::Propulsion::HoverPower")["color"] == "#7b4bab"  # behavior
        assert node(view, "Rotorcraft::BoxQuad::mass")["color"] == "#3f7a1f"  # data
        assert node(view, "ScoutSizing::IsrStation")["color"] == "#b0413e"  # requirement

    def test_kind_families_mirror_the_explorer(self):
        explorer = pytest.importorskip("longeron.widgets.explorer")
        assert graph3d._KIND_FAMILIES == explorer._KIND_FAMILIES

    def test_anonymous_elements_get_stable_synthetic_ids(self, view):
        satisfies = [entry for entry in view["nodes"] if entry["kind"] == "satisfy"]
        assert len(satisfies) == 19  # the DeepScout satisfy edges (tutorial 8)
        assert all(entry["id"].startswith("~") for entry in satisfies)
        assert all(entry["family"] == "requirement" for entry in satisfies)
        assert all(entry["ns"] != "(anonymous)" for entry in satisfies)  # ns via owner

    def test_degree_sizes_the_hubs(self, view):
        hub = max(view["nodes"], key=lambda entry: entry["deg"])
        assert hub["id"] == "DeepScout::MultiRotor"
        assert hub["r"] > node(view, "Rotorcraft::BoxQuad::mass")["r"]

    def test_edge_indices_and_families_are_well_formed(self, view):
        count = len(view["nodes"])
        families = [entry["name"] for entry in view["families"]]
        assert families == [
            "membership",
            "specialization",
            "typing",
            "connection",
            "satisfy",
            "reference",
        ]
        for source, target, family in view["edges"]:
            assert 0 <= source < count and 0 <= target < count
            assert 0 <= family < len(families)
        used = {family for _, _, family in view["edges"]}
        assert families.index("membership") in used
        assert families.index("satisfy") in used

    def test_namespace_filter_reduces_the_view(self, graph, view):
        sizing = graph3d.graph_view(graph, namespaces=["ScoutSizing"])
        assert 0 < len(sizing["nodes"]) < len(view["nodes"])
        assert all(entry["ns"] == "ScoutSizing" for entry in sizing["nodes"])
        # the options list stays the full graph's, for stable filter panels
        assert sizing["namespaces"] == view["namespaces"]

    def test_family_filter_with_isolated_pruning(self, graph, view):
        skeleton = graph3d.graph_view(
            graph,
            families=["specialization", "typing", "connection", "satisfy"],
            isolated=False,
        )
        assert 0 < len(skeleton["nodes"]) < len(view["nodes"])
        assert all(entry["deg"] > 0 for entry in skeleton["nodes"])
        kept = {entry["name"] for entry in skeleton["families"]} & {
            skeleton["families"][family]["name"] for _, _, family in skeleton["edges"]
        }
        assert "membership" not in kept

    def test_literal_expansion_is_opt_in(self, graph, view):
        expanded = graph3d.graph_view(graph, literals=True)
        leaves = [entry for entry in expanded["nodes"] if entry["family"] == "literal"]
        assert leaves and len(expanded["nodes"]) == len(view["nodes"]) + len(leaves)
        assert not any(entry["family"] == "literal" for entry in view["nodes"])
        value_family = [entry["name"] for entry in expanded["families"]].index("value")
        assert sum(1 for *_, family in expanded["edges"] if family == value_family) == len(leaves)

    def test_view_is_deterministic(self, graph):
        assert graph3d.graph_view(graph) == graph3d.graph_view(graph)


class TestSpringLayout:
    EDGES = ((0, 1), (1, 2), (2, 0), (2, 3), (4, 4))

    def test_seeded_layout_is_deterministic(self):
        pytest.importorskip("numpy")
        first = graph3d.spring_layout(5, self.EDGES, seed=3)
        again = graph3d.spring_layout(5, self.EDGES, seed=3)
        other = graph3d.spring_layout(5, self.EDGES, seed=4)
        assert first == again
        assert first != other

    def test_layout_shape_and_normalization(self):
        pytest.importorskip("numpy")
        positions = graph3d.spring_layout(5, self.EDGES, radius=10.0)
        assert len(positions) == 5 and all(len(point) == 3 for point in positions)
        # positions round to 3 decimals, hence the small tolerance
        assert max(sum(c * c for c in point) for point in positions) <= 10.001**2

    def test_connected_nodes_sit_closer_than_strangers(self):
        pytest.importorskip("numpy")
        positions = graph3d.spring_layout(4, [(0, 1)], iterations=120)

        def gap(a, b):
            pairs = zip(positions[a], positions[b], strict=True)
            return sum((x - y) ** 2 for x, y in pairs) ** 0.5

        assert gap(0, 1) < min(gap(0, 2), gap(0, 3), gap(1, 2), gap(1, 3))

    def test_empty_graph(self):
        pytest.importorskip("numpy")
        assert graph3d.spring_layout(0, []) == []


class TestDagLayout:
    # a small hierarchy: 0 and 4 are roots; 0 owns 1 and 2; 3 sits
    # below both 1 and 2; 5 only participates via an undirected link
    HIERARCHY = ((0, 1), (0, 2), (1, 3), (2, 3), (4, 1))
    LINKS = ((3, 5), (5, 0))

    def test_roots_share_the_top_layer(self):
        points = graph3d.dag_layout(6, self.HIERARCHY, self.LINKS)
        top = max(point[1] for point in points)
        roots = {index for index, point in enumerate(points) if point[1] == top}
        # 0 and 4 have no incoming hierarchy edge; 5 has none at all
        assert roots == {0, 4, 5}

    def test_layers_are_monotone_along_hierarchy_edges(self):
        points = graph3d.dag_layout(6, self.HIERARCHY, self.LINKS)
        for above, below in self.HIERARCHY:
            assert points[above][1] > points[below][1]

    def test_barycenter_is_deterministic_and_order_free(self):
        forward = graph3d.dag_layout(6, self.HIERARCHY, self.LINKS)
        shuffled = graph3d.dag_layout(
            6, tuple(reversed(self.HIERARCHY)), tuple((b, a) for a, b in self.LINKS)
        )
        assert forward == shuffled
        assert forward == graph3d.dag_layout(6, self.HIERARCHY, self.LINKS)

    def test_layout_fits_the_radius(self):
        points = graph3d.dag_layout(6, self.HIERARCHY, self.LINKS, radius=10.0)
        assert len(points) == 6 and all(len(point) == 3 for point in points)
        assert max(sum(c * c for c in point) for point in points) <= 10.001**2

    def test_empty_graph(self):
        assert graph3d.dag_layout(0, []) == []


@pytest.fixture(scope="module")
def widget(graph):
    pytest.importorskip("anywidget")
    pytest.importorskip("numpy")
    return graph3d.graph_viewer(graph)


class TestGraphViewer:
    def test_payload_matches_the_default_view(self, widget, view):
        payload = json.loads(widget.payload_json)
        assert payload["counts"] == {"nodes": 1569, "edges": 1916}
        assert payload["counts"]["nodes"] == len(view["nodes"])
        assert len(payload["positions"]) == len(payload["nodes"])
        assert payload["notice"] == ""
        assert payload["focus"] is None
        assert widget.counts == payload["counts"]
        assert widget.layout_seconds > 0

    def test_payload_ships_both_embeddings(self, widget):
        """The morph slider's contract: a force embedding and a layered
        one, same length, both 3-vectors, visibly different shapes."""

        payload = json.loads(widget.payload_json)
        assert len(payload["positions_dag"]) == len(payload["positions"])
        assert all(len(point) == 3 for point in payload["positions_dag"])
        assert payload["positions_dag"] != payload["positions"]

    def test_dag_embedding_stacks_the_hierarchy(self, widget):
        """Packages sit above the members they (transitively) own."""

        payload = json.loads(widget.payload_json)
        y = {node["id"]: payload["positions_dag"][i][1] for i, node in enumerate(payload["nodes"])}
        assert y["Rotorcraft"] > y["Rotorcraft::BoxQuad"] > y["Rotorcraft::BoxQuad::mass"]

    def test_options_offer_every_namespace_and_family(self, widget, view):
        options = json.loads(widget.options_json)
        assert options["namespaces"] == view["namespaces"]
        assert [entry["name"] for entry in options["families"]] == [
            entry["name"] for entry in view["families"]
        ]

    def test_filter_recomputes_and_relayouts(self, graph):
        pytest.importorskip("anywidget")
        pytest.importorskip("numpy")
        widget = graph3d.graph_viewer(graph)
        before = json.loads(widget.payload_json)
        counts = widget.filter(namespaces=["ScoutSizing"])
        after = json.loads(widget.payload_json)
        assert 0 < counts["nodes"] < before["counts"]["nodes"]
        assert len(after["positions"]) == counts["nodes"]
        # the browser panel writes the same trait; both paths converge
        assert json.loads(widget.filters_json)["namespaces"] == ["ScoutSizing"]

    def test_selection_contract_fires_callbacks(self, graph):
        pytest.importorskip("anywidget")
        pytest.importorskip("numpy")
        widget = graph3d.graph_viewer(graph)
        seen = []
        widget.on_select(seen.append)
        widget.selected = ["DeepScout::MultiRotor"]
        widget.selected = []
        assert seen == [["DeepScout::MultiRotor"], []]

    def test_node_cap_degrades_with_a_notice(self, graph):
        pytest.importorskip("anywidget")
        pytest.importorskip("numpy")
        widget = graph3d.graph_viewer(graph, node_cap=100)
        payload = json.loads(widget.payload_json)
        assert payload["counts"]["nodes"] == 100
        assert "showing 100 of" in payload["notice"]
        ids = {entry["id"] for entry in payload["nodes"]}
        assert "DeepScout::MultiRotor" in ids  # highest degree survives

    def test_widget_payload_is_deterministic(self, graph):
        pytest.importorskip("anywidget")
        pytest.importorskip("numpy")
        first = graph3d.graph_viewer(graph, seed=11)
        again = graph3d.graph_viewer(graph, seed=11)
        assert first.payload_json == again.payload_json

    def test_esm_contracts(self, widget):
        """The front-end contract, encoded: CDN import with the offline
        fallback, instanced spheres with raycast picking, per-family
        line segments, the pill panel writing filters_json, the morph
        lerp over both embeddings, focus chips writing focus_json, the
        search-to-fly seam, labels, legend, and live theming."""

        for token in (
            graph3d.THREE_URL,
            "offline",
            "InstancedMesh",
            "setColorAt",
            "instanceId",
            "LineSegments",
            "LineDashedMaterial",
            "filters_json",
            "save_changes",
            "change:payload_json",
            "change:selected",
            "--jp-brand-color2",
            "dblclick",
            # the refinement surface
            "positions_dag",
            "setMorph",
            "focus_json",
            "flyTo",
            "lgw-morphbar",
            "lgw-pill",
            "lgw-slider",
            "lgw-search",
            "lgw-legend",
            "lgw-crumb",
            "CanvasTexture",
            "MutationObserver",
            "prefers-color-scheme",
            "standalone",
        ):
            assert token in widget._esm, token

    def test_css_carries_the_shared_chrome(self, widget):
        """The control surface styles come from the lgw-* chrome seed:
        theme tokens, pills, sliders, the veiled panel."""

        from longeron.widgets import _chrome

        assert widget._css.startswith(_chrome.CONTROL_CSS)
        for token in (
            "--jp-layout-color1",
            "backdrop-filter",
            "lgw-pill",
            "lgw-slider",
            "focus-visible",
            "--p",
        ):
            assert token in widget._css, token


class TestFocusMode:
    @pytest.fixture()
    def widget(self, graph):
        pytest.importorskip("anywidget")
        pytest.importorskip("numpy")
        return graph3d.graph_viewer(graph)

    def test_focus_isolates_the_k_hop_neighborhood(self, widget, view):
        counts = widget.focus("DeepScout::MultiRotor", k=1)
        payload = json.loads(widget.payload_json)
        # independent truth: the hub + its direct neighbors in the view
        index = {entry["id"]: i for i, entry in enumerate(view["nodes"])}
        hub = index["DeepScout::MultiRotor"]
        expected = {hub}
        for source, target, _family in view["edges"]:
            if source == hub:
                expected.add(target)
            if target == hub:
                expected.add(source)
        ids = {entry["id"] for entry in payload["nodes"]}
        assert ids == {view["nodes"][i]["id"] for i in expected}
        assert counts["nodes"] == len(expected) < 1569
        assert payload["focus"] == {"id": "DeepScout::MultiRotor", "k": 1, "of": 1569}
        assert len(payload["positions"]) == len(payload["positions_dag"]) == counts["nodes"]

    def test_deeper_focus_reaches_further(self, widget):
        one = widget.focus("DeepScout::MultiRotor", k=1)
        two = widget.focus("DeepScout::MultiRotor", k=2)
        assert one["nodes"] < two["nodes"] < 1569

    def test_unfocus_restores_the_full_view(self, widget):
        widget.focus("DeepScout::MultiRotor", k=1)
        assert widget.unfocus() == {"nodes": 1569, "edges": 1916}
        assert json.loads(widget.payload_json)["focus"] is None

    def test_unknown_target_leaves_the_full_view(self, widget):
        counts = widget.focus("No::Such::Node")
        assert counts["nodes"] == 1569
        assert json.loads(widget.payload_json)["focus"] is None

    def test_focus_trait_is_the_browser_seam(self, widget):
        """The chips write focus_json directly; the observer recomputes
        exactly as the kernel-side focus() call does."""

        widget.focus_json = json.dumps({"id": "DeepScout::MultiRotor", "k": 1})
        via_trait = widget.counts
        widget.unfocus()
        assert via_trait == widget.focus("DeepScout::MultiRotor", k=1)

    def test_focus_leaves_the_selection_contract_alone(self, widget):
        seen = []
        widget.on_select(seen.append)
        widget.selected = ["DeepScout::MultiRotor"]
        widget.focus("DeepScout::MultiRotor", k=1)
        assert widget.selected == ["DeepScout::MultiRotor"]
        assert seen == [["DeepScout::MultiRotor"]]


class TestExportHtml:
    def test_export_writes_a_self_contained_page(self, graph, tmp_path):
        pytest.importorskip("anywidget")
        pytest.importorskip("numpy")
        widget = graph3d.graph_viewer(graph)
        target = widget.export_html(tmp_path / "graph.html")
        assert target == tmp_path / "graph.html"
        page = target.read_text(encoding="utf-8")
        # the payload, the front-end, and the shim are inlined ...
        assert json.dumps(widget.payload_json)[1:-1][:80] in page
        assert "positions_dag" in page and graph3d.THREE_URL in page
        assert "data.standalone = true" in page and "save_changes" in page
        # ... and nothing at view time needs anywidget or a kernel
        assert "anywidget" not in page
        assert "prefers-color-scheme: dark" in page

    def test_export_carries_the_focused_view(self, graph, tmp_path):
        pytest.importorskip("anywidget")
        pytest.importorskip("numpy")
        widget = graph3d.graph_viewer(graph)
        widget.focus("DeepScout::MultiRotor", k=1)
        page = widget.export_html(tmp_path / "hub.html").read_text(encoding="utf-8")
        assert json.dumps(widget.payload_json)[1:-1][:80] in page
        assert widget.counts["nodes"] < 1569
