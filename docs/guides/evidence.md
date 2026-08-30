# Evidence-linked models

A stated value is a claim. `longeron.evidence` lets the model carry the
citation that backs it: which document, which exact version, which words.
The design is `docs/design/provenance.md`; this guide covers the shipped
layers -- the vocabulary, the toolchain, the lint codes, and the two
storage patterns.

## The vocabulary

A citation is an ordinary metadata annotation, typed by
`Evidence::SourceEvidence` (`examples/evidence.sysml`, a longeron
convention package):

```sysml
attribute mass : Real = 0.015 [SI::kg] {
    @Evidence::SourceEvidence {
        document = "https://www.apcprop.com/product/10x4-5mr/";
        sha256 = "dcb33746a711...";
        quote = "Product Weight 0.53 oz.";
        retrieved = "2026-08-29";
    }
}
```

Because the citation lives in the model, it parses, exports, survives
JSON, and projects to RDF like any other content. There is no sidecar
index to maintain.

The `quote` is the primary anchor: it survives re-rendering and OCR
variance, while page geometry does not. `page` and `bbox` are optional
visual locators. `sha256` pins the exact document version, so anyone who
fetches the document can detect drift. `retrieved` records the ISO date
the document was read.

## Attaching a citation

{func}`~longeron.evidence.attach` writes the annotation through
{mod}`longeron.edit`, so a registered tracker records the change:

```python
import longeron
from longeron import evidence

model = longeron.load("examples/deepscout", cache=False)
evidence.attach(
    model,
    "ScoutParts::F450Kit::Propeller::mass",
    "https://www.apcprop.com/product/10x4-5mr/",
    "Product Weight 0.53 oz.",
)
```

`attach` reads the document, computes its sha256, and extracts its text.
If the text does not contain the quote, `attach` raises
{class}`~longeron.errors.EditError`, names the document, and shows the
closest text it found. A refusal mutates nothing, and the tracker
records nothing. Quote matching normalizes whitespace on both sides and
is otherwise exact.

Documents are repo-relative paths or URLs. A URL document is fetched
once, into a local cache (`~/.cache/longeron/evidence`, honoring
`$LONGERON_CACHE_DIR` and `$XDG_CACHE_HOME`). The cache only speeds
verification up. The sha256 on the citation stays the authority.

PDF text extraction needs the `[evidence]` extra (`pypdf` with a
`pdfminer.six` fallback, both license-clean). HTML documents reduce to
their visible text with the standard library. Plain-text documents need
no extra.

`attach(..., verify=False)` is the escape hatch for offline authoring:
it writes exactly what you pass, without reading the document.
{func}`~longeron.evidence.verify` later reports what such a citation is
worth.

## Verifying citations

{func}`~longeron.evidence.verify` re-checks every citation and returns
one verdict each:

| Verdict | Meaning |
|---|---|
| `intact` | The document hashes to the citation's sha256, and its text still contains the quote. |
| `drifted` | The document reads, but its sha256 changed. |
| `lost` | The sha256 matches (or the citation never pinned one), but the text no longer contains the quote. |
| `unreachable` | The file or URL cannot be read at all. |

From the command line:

```console
$ longeron evidence verify examples/deepscout
status  element                                document                                   detail
------  -------------------------------------  -----------------------------------------  ------
intact  ScoutParts::F450Kit::Propeller::mass   https://www.apcprop.com/product/10x4-5mr/
1 citation(s): 0 drifted or lost
```

The exit code is the count of drifted and lost citations, so a CI step
can gate on it directly. Pass `--no-fetch` to stay offline: URL
documents then verify against the local cache only.

## Coverage

{func}`~longeron.evidence.coverage` reports which stated values carry a
citation. A stated value is an attribute whose value expression is a
literal fact: a number, string, or boolean, optionally with a unit or a
sign. Derived values state no independent fact and are not counted.

```pycon
>>> print(evidence.coverage(model, "ScoutParts::F450Kit::Propeller"))
element                                    value            evidence
-----------------------------------------  ---------------  -----------------------------------------
ScoutParts::F450Kit::Propeller::diameter   0.254 [SI::m]    https://www.apcprop.com/product/10x4-5mr/
...
4 of 5 stated value(s) cited
```

The counts are never inflated: only stated values enter the denominator,
and only citations on those values enter the numerator.

## The lint codes

`evidence-drift` warns, in default mode, when a citation exists but
verification says the document drifted or the quote is lost. The lint
never touches the network: URL documents check against the local cache
only, and a model without citations is not affected at all.

`unevidenced-value` is opt-in (`validate(evidence_coverage=True)` /
`longeron lint --evidence-coverage`): one warning per stated value with
no citation. It is off by default because most models legitimately carry
derived and assumed values. Coverage is a report; absence is not a
defect. The [validation guide](validation.md#the-diagnostic-codes)
documents both codes.

## The two storage patterns

Where the documents live is a copyright decision, made per document:

1. **Owned or redistributable documents** (internal specs, test reports,
   standards your organization licenses): commit them under `evidence/`
   via git LFS. Run `longeron evidence init` once per repository; it
   writes the `.gitattributes` stanza (`evidence/** filter=lfs ...`) so
   the binary pollution never starts.
2. **Third-party documents** (manufacturer datasheets and product
   pages): do not commit them -- redistribution is usually not licensed.
   Cite by URL + sha256 + quote. The hash still pins the exact version,
   the quote still anchors the fact, and drift is still detectable by
   anyone who fetches the document.

The longeron repository itself follows pattern 2: the DeepScout parts
catalog cites manufacturer pages by URL, and no vendor document is
committed.
