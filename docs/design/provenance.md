# Design: data provenance — evidence-linked models

> Status: adopted 2026-08-28. All five decisions are settled (the
> Decisions section at the end); layers 1-2 are an 0.12 arc.

Goal: evidence-linked models. A spec-sheet PDF is stored under
version control (LFS where appropriate), its text is extracted (OCR
for scans), and regions of the document are linked to the
requirement or value they justify -- real provenance for the numbers
a model states.

The thesis fits longeron's spine exactly: the model is the source of
truth, and a value without evidence is a claim without a citation.
The real-parts arc makes this urgent — the model now states nominal
manufacturer figures, and each one has a datasheet somewhere.

## What longeron already has

- **`FileArtifact`** (`examples/analysis_conventions.sysml` + the
  mdao-objects landing): path + sha256 at external-file boundaries.
  Provenance is the same shape pointed the other way.
- **Metadata machinery**: `metadata def` / `@` usages parse, build,
  and survive JSON. The model can carry structured annotations today.
- **The selection seam**: explorer/inspector selection is the natural
  "link this element" gesture; the inspector already grew rows this
  release (Unit, relationships) — an Evidence row is the same move.
- **The knowledge graph (T8/NB08)**: SPARQL over the RDF projection.
  Evidence metadata projects like everything else: "which
  requirements cite document X?" becomes a query.
- **`longeron lint`**: severity plumbing + `--strict` for coverage
  gates.

## The design, smallest honest slice first

### Layer 1 — the vocabulary (a shipped library package)

`evidence.sysml` (alongside `analysis_conventions.sysml`):

```sysml
metadata def SourceEvidence {
    doc /* A citation from a model element to a region of a source
           document. quote is the extracted text (the anchor that
           survives re-rendering); page/bbox locate it visually. */
    attribute document : String;      // repo-relative path or URL
    attribute sha256 : String;        // pins the exact document
    attribute page : Real;
    attribute quote : String;         // extracted text snippet
    attribute bbox : String;          // optional "x0,y0,x1,y1"
    attribute retrieved : String;     // ISO date
}
```

Usage, on the real-parts model:

```sysml
attribute mass : Real = 0.058 [SI::kg] {
    @SourceEvidence {
        document = "https://sunnyskyusa.com/products/x2212";
        sha256 = "9f2c...";
        quote = "Weight: 58 g";
        retrieved = "2026-08-28";
    }
}
```

In-model, standard SysML v2, JSON-portable, RDF-projectable. No
sidecar file format to invent or maintain.

### Layer 2 — the toolchain (`longeron.evidence`)

- `attach(model, element, document, quote=..., page=...)` — computes
  the sha256, extracts/verifies the quote against the document text,
  writes the metadata usage (through `edit`, so the Tracker records
  it and refusal semantics apply: a quote that does NOT appear in the
  document refuses).
- `verify(model)` — re-hashes every cited document, re-finds every
  quote. Three verdicts per citation: intact / document drifted
  (hash mismatch) / quote lost (hash ok, text gone). Returns a
  report; lint grows `evidence-drift` (warning) and
  `unevidenced-value` (off by default; a strict-mode candidate).
- `coverage(model)` — the honest metric: which leaf values,
  requirement thresholds, and constraint constants carry evidence;
  rendered like the conformance buckets (counted, never inflated).
- Text extraction: `pypdf`/`pdfminer.six` (BSD/MIT) behind an
  `[evidence]` extra. **Not PyMuPDF — AGPL.** OCR (scanned docs) via
  optional `pytesseract`, a second-tier extra, never required for
  born-digital PDFs.

### Layer 3 — the surfaces

- **Inspector**: an Evidence row per cited fact — quote + document +
  intact/drifted chip; click opens the document in JupyterLab's
  built-in PDF viewer at the cited page. No custom viewer in v1.
- **Knowledge graph**: evidence triples ride the RDF projection; T8
  gains the provenance query as a worked example.
- **Scoreboard/verify** (later): a value's evidence status could
  qualify its verdict ("passes, but the threshold is uncited").

### Layer 4 — the viewer (explicitly v2)

Region-select over rendered pages (the ipypdf gesture) is the right
long-term UX, wired to the selection seam: select an element in the
explorer, select a region in the viewer, click link. Build it as an
in-house anywidget over pdf.js (Apache-2.0, vendorable like ipyelk)
only after layers 1–3 prove the data model. ipypdf itself: right
instinct, wrong dependency — thin maintenance, its own node-tree data
model, and we would fight it at the selection seam.

## Storage: LFS and the copyright line

Two patterns, both documented, chosen per document:

1. **Owned/redistributable documents** (internal specs, test
   reports, standards the org licenses): committed under
   `evidence/` via **git LFS**. `longeron evidence init` writes the
   `.gitattributes` stanza (`evidence/**/*.pdf filter=lfs ...`) so
   the pollution never starts. Lint idea: warn when a tracked PDF
   over ~1 MB is NOT an LFS pointer (`evidence-not-lfs`).
2. **Third-party datasheets** (the manufacturer PDFs): **do not
   commit** — redistribution is usually not licensed. Cite by URL +
   sha256 + quote. The hash still pins the exact version; the quote
   still anchors the fact; drift is still detectable by anyone who
   fetches the document. A local cache dir (gitignored) keeps
   verification fast.

longeron's own repo commits no manufacturer PDFs either way; the
real-parts model cites by URL+hash+quote (pattern 2) — which is also
the immediate first customer for the whole design.

## Decisions

All five were adopted on 2026-08-28.

1. **In-model `SourceEvidence` metadata, not a sidecar index**:
   portable, standard, RDF-projectable. A gitignored cache is
   allowed for extraction speed, never authoritative.
2. **Quote-primary anchoring** (it survives re-rendering and OCR
   variance), with bbox optional for the future viewer. `attach()`
   refuses a quote it cannot find in the document.
3. **The PDF stack is license-clean**: `pypdf` + `pdfminer.six`
   behind `[evidence]`; pdf.js vendored only when layer 4 happens;
   PyMuPDF never ships (AGPL); OCR is an optional second tier.
4. **Coverage enforcement**: `evidence-drift` always warns;
   `unevidenced-value` exists but is opt-in (a posture flag, like
   `--strict`), because most models legitimately carry derived and
   assumed values. `coverage()` reports honestly either way.
5. **Timing**: layers 1-2 land as an 0.12 arc right after the
   curriculum rebuild, with the real-parts model as first customer.
   Layer 3 rides the next inspector touch. Layer 4 is its own later
   arc.
