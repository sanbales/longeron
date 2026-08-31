// Longeron extension library -- NOT part of the OMG standard library.
//
// The surfaces design (docs/design/surfaces.md) grounds dashboards in the
// standard Views vocabulary: a view usage selects content with `expose`
// and names its presentation with `render`.  The standard ships four
// rendering usages (tree, interconnection, table, text); longeron's
// panels need names for the house widgets.  This library is that one
// extension: rendering usages, one per panel-able widgets-catalog entry,
// bound to their builders by the Python registry in
// longeron.analysis.surfaces (the mapping-table precedent of
// longeron.views.VIEW_DEFINITIONS).
library package LongeronSurfaces {
    doc /* Longeron extension: renderings naming the house widgets.  Each
           rendering usage names one longeron.widgets catalog entry (or an
           engine-built panel) through the surface engine's registry;
           the library is longeron-authored and deliberately not labeled
           standard. */

    private import Views::*;

    rendering def PanelRendering :> GraphicalRendering {
        doc /* The base definition of every longeron panel rendering. */
    }

    rendering asStructureDiagram : PanelRendering;  // widgets.structure_diagram
    rendering asStateDiagram : PanelRendering;      // widgets.state_diagram
    rendering asActionDiagram : PanelRendering;     // widgets.action_diagram
    rendering asMeshViewer : PanelRendering;        // widgets.mesh_viewer over scene_for(subject)
    rendering asScoreboard : PanelRendering;        // widgets.scoreboard
    rendering asWhatIfCard : PanelRendering;        // engine-built: sliders + readout per analysis case
    rendering asSizingCards : PanelRendering;       // engine-built: the OpenMDAO strip (phase 2)
    rendering asVerdictCards : PanelRendering;      // engine-built: VerdictKind rows per verification case
    rendering asMissionGlobe : PanelRendering;      // widgets.mission_viewer (phase 2)
    rendering asReplayPlayer : PanelRendering;      // widgets.replay_widget (phase 2)
}
