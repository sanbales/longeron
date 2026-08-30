// Evidence conventions for provenance-linked models (longeron.evidence).
//
// Like AnalysisConventions (examples/analysis_conventions.sysml), this is
// a MODEL-side counterpart of Python-side machinery -- a longeron-authored
// convention package, not part of the SysML v2 standard library.  The
// Python counterpart is longeron.evidence: attach() writes SourceEvidence
// annotations after it verifies the quote against the document, verify()
// re-checks every citation, and coverage() counts which stated values
// carry one (docs/design/provenance.md).
package Evidence {
    doc /* A longeron extension: the vocabulary for evidence-linked
           models.  A SourceEvidence annotation cites the source
           document that justifies a stated value or requirement
           threshold.  Citations are ordinary metadata usages, so they
           parse, export, survive JSON, and project to RDF like any
           other model content. */

    metadata def SourceEvidence {
        doc /* A citation from a model element to a region of a source
               document.  quote is the extracted text -- the primary
               anchor, because it survives re-rendering and OCR
               variance; page and bbox locate the region visually and
               are optional.  document is a repo-relative path or a
               URL; sha256 pins the exact document version, so drift
               is detectable by anyone who fetches it; retrieved is
               the ISO date the document was read. */

        attribute document : String;
        attribute sha256 : String;
        attribute page : Real;
        attribute quote : String;
        attribute bbox : String;
        attribute retrieved : String;
    }
}
