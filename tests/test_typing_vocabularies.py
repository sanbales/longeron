"""The Literal vocabularies and their runtime registries cannot drift.

Every public ``typing.Literal`` alias either DERIVES its runtime table
(``get_args`` -- the ``model.py`` house pattern; those pairs are correct
by construction and asserted here only for documentation) or is
CROSS-ASSERTED against the registry that actually dispatches at runtime
(dict keys, uppercase ELK option tables).  A vocabulary member added to
one side without the other fails here; the signature side is guarded by
the mypy fixtures in ``tests/typing/literal_bite.py``.
"""

from typing import get_args

from longeron import diagrams, toolbar, views
from longeron.analysis import scoreboard, surfaces
from longeron.widgets import app as widgets_app
from longeron.widgets import explorer, mission3d


class TestDerivedTables:
    """Tables built with ``get_args(...)``: the Literal is the authority."""

    def test_collapse_levels_derive_from_the_literal(self):
        assert diagrams._LEVELS == get_args(diagrams.NodeLevel)
        assert diagrams._LEVELS == ("expanded", "partial", "collapsed")

    def test_section_order_derives_from_the_literal(self):
        assert diagrams._SECTION_ORDER == get_args(diagrams.CompartmentSection)
        # the stacking order is load-bearing (spec chapter order): pin the ends
        assert diagrams._SECTION_ORDER[0] == "attributes"
        assert diagrams._SECTION_ORDER[-1] == "views"
        assert len(set(diagrams._SECTION_ORDER)) == len(diagrams._SECTION_ORDER)

    def test_view_kinds_share_one_literal(self):
        assert views.VIEW_KINDS == get_args(views.ViewKind)
        assert explorer.DIAGRAM_KINDS == views.VIEW_KINDS  # one vocabulary, two names

    def test_layout_choices_share_one_literal(self):
        assert explorer._LAYOUTS == get_args(explorer.LayoutChoice)
        assert widgets_app._LAYOUTS == explorer._LAYOUTS  # app.open == explore
        # the resolved pair is the choice set minus the "auto" detector
        assert set(get_args(explorer.ResolvedLayout)) == set(explorer._LAYOUTS) - {"auto"}

    def test_imagery_bases_derive_from_the_literal(self):
        assert mission3d._IMAGERY_BASES == get_args(mission3d.Imagery)


class TestCrossAssertedRegistries:
    """Registries with their own runtime shape: keys must equal the Literal."""

    def test_aggregation_names_match_the_registry(self):
        assert set(get_args(scoreboard.Aggregation)) == set(scoreboard.AGGREGATORS)

    def test_utility_shapes_match_the_registry(self):
        assert set(get_args(scoreboard.UtilityShape)) == set(scoreboard.UTILITY_FUNCTIONS)

    def test_verdict_kinds_match_the_tone_table(self):
        assert set(get_args(surfaces.VerdictKind)) == set(surfaces._VERDICT_TONE)

    def test_routing_matches_the_elk_option_table(self):
        # user-facing lowercase vocabulary <-> uppercase elk.edgeRouting values
        assert get_args(toolbar.EdgeRouting) == tuple(s.lower() for s in toolbar.ROUTING_STYLES)

    def test_directions_match_the_elk_option_table(self):
        assert get_args(toolbar.LayoutDirection) == tuple(s.lower() for s in toolbar.DIRECTIONS)

    def test_compartment_sections_cover_every_row_target(self):
        # every kind the builder rows into a compartment names a real section
        sections = set(get_args(diagrams.CompartmentSection))
        assert set(diagrams._ROW_SECTIONS.values()) <= sections
        assert set(diagrams._CONSTRAINT_SECTIONS.values()) <= sections
        assert set(views.VIEW_DEFINITIONS) == set(get_args(views.ViewKind))
