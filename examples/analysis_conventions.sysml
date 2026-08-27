// Conventions shared by the OpenMDAO analysis bridge (longeron.analysis.mdao).
//
// Like the @ExternalAnalysis metadata convention shipped with
// examples/uav_missions.sysml, these are MODEL-side counterparts of
// Python-side analysis machinery -- convention packages over stdlib
// additions until the shapes settle (the ratified mdao-objects design,
// open question 4).
package AnalysisConventions {
    doc /* Model-side conventions for object-valued analysis I/O. */

    item def FileArtifact {
        doc /* A file crossing the analysis boundary: a path plus content
               identity.  The Python counterpart is
               longeron.analysis.mdao.FileArtifact -- it flows between
               OpenMDAO components as a tiny discrete value while the
               bytes stay on disk, and its sha256 is the caching
               identity (same recipe, same hash: skip the external run).
               Type analysis flows by it so the wiring derivation
               (derive_flows) can check the handoff:

                   flow of FileArtifact from writer.artifact to solver.geometry;

               mediaType maps to the dataclass's media_type ('to_json'
               key 'media_type'). */

        attribute path : String;
        attribute sha256 : String;
        attribute mediaType : String;
    }
}
