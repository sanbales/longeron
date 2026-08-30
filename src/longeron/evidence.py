"""Evidence-linked models: attach, verify, and count ``SourceEvidence`` citations.

The model-side vocabulary is the ``Evidence::SourceEvidence`` metadata
definition (``examples/evidence.sysml``, a longeron convention package --
design: ``docs/design/provenance.md``): a citation from a model element
to a region of a source document, carried *in the model* as an ordinary
metadata annotation, so it parses, exports, survives JSON, and projects
to RDF like any other content::

    attribute mass : Real = 0.055 [SI::kg] {
        @Evidence::SourceEvidence {
            document = "https://emaxmodel.com/products/mt2213";
            sha256 = "9f2c...";
            quote = "Weight: 55g";
            retrieved = "2026-08-28";
        }
    }

This module is the Python-side toolchain:

- :func:`attach` writes a citation through :mod:`longeron.edit` (the
  tracker records it; a refusal mutates nothing).  It computes the
  document's sha256, extracts its text, and **refuses a quote the
  document does not contain** -- quote-primary anchoring, because the
  quote survives re-rendering while page geometry does not.
- :func:`verify` re-checks every citation and returns one
  :class:`Verdict` each: ``intact``, ``drifted`` (sha256 mismatch),
  ``lost`` (hash intact, text no longer contains the quote), or
  ``unreachable`` (the file or URL cannot be read at all).
- :func:`coverage` is the honest metric: which stated attribute values
  carry a citation, counted and never inflated.

**Documents.**  A ``document`` is a repo-relative path (resolved against
the model's source directory) or an ``http(s)`` URL.  URL documents are
fetched once into a local cache -- ``~/.cache/longeron/evidence``,
honoring ``$LONGERON_CACHE_DIR`` and ``$XDG_CACHE_HOME``, the same
convention as the corpus cache -- which keeps verification fast and is
never authoritative: the hash on the citation is.  Two storage patterns
(the guide, ``docs/guides/evidence.md``): owned documents commit under
``evidence/`` via git LFS (``longeron evidence init`` writes the
``.gitattributes`` stanza); third-party datasheets are cited by URL +
sha256 + quote and never committed.

**Text extraction.**  PDFs extract through ``pypdf``, falling back to
``pdfminer.six`` when pypdf yields nothing -- both license-clean, behind
the ``[evidence]`` extra (:class:`~longeron.errors.MissingExtraError`
without it).  HTML (a fetched product page) is reduced to its visible
text with the standard library's parser, so quotes anchor to what a
reader sees, not to markup.  Everything else reads as UTF-8 text.
Quote matching normalizes whitespace on both sides (PDF extraction
rewraps lines) and is otherwise exact.

``attach(..., verify=False)`` is the documented escape hatch for
offline authoring: it writes the citation without reading the document,
using whatever ``sha256`` you supply (or none).  ``verify`` later
reports honestly what such a citation is worth.
"""

from __future__ import annotations

import dataclasses
import datetime
import difflib
import hashlib
import os
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from . import model as M
from .ast import Literal as LiteralExpr
from .errors import EditError, MissingExtraError, ResolutionError

__all__ = [
    "Citation",
    "CoverageReport",
    "Fact",
    "Verdict",
    "attach",
    "cache_dir",
    "citations",
    "coverage",
    "document_text",
    "init_lfs",
    "verify",
]

#: the vocabulary type every citation is typed by (examples/evidence.sysml)
EVIDENCE_TYPE = "Evidence::SourceEvidence"

#: the ``longeron evidence init`` .gitattributes stanza (storage pattern 1)
LFS_STANZA = (
    "# owned evidence documents ride git LFS (longeron evidence init)\n"
    "evidence/** filter=lfs diff=lfs merge=lfs -text\n"
)


# ---------------------------------------------------------------------------
# citations: finding and reading the metadata
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Citation:
    """One ``SourceEvidence`` annotation, read back from the model."""

    element: M.Element  #: the cited element (the annotation's owner)
    qname: str  #: its qualified name (or best-effort label)
    document: str  #: repo-relative path or URL
    sha256: str | None
    quote: str | None
    page: float | None = None
    bbox: str | None = None
    retrieved: str | None = None
    usage: M.MetadataUsage | None = None  #: the annotation element itself


def _is_citation(usage: M.MetadataUsage) -> bool:
    return usage.typed_by.split("::")[-1] == "SourceEvidence"


def _literal(usage: M.MetadataUsage, key: str) -> Any:
    for member in usage.members:
        if isinstance(member, M.MetadataValue) and member.redefines == key:
            if member.value is not None and isinstance(member.value.expr, LiteralExpr):
                return member.value.expr.value
    return None


def citations(model: M.Model, root: M.Element | str | None = None) -> list[Citation]:
    """Every ``SourceEvidence`` citation under ``root`` (default: the model).

    Elements inside ``library`` packages are skipped, matching
    ``validate``'s posture: a merged-in library is context, not the model
    under inspection.
    """

    start = _root_element(model, root)
    found: list[Citation] = []
    for element in start.iter_tree():
        if _in_library(element):
            continue
        for member in getattr(element, "members", []):
            if isinstance(member, M.MetadataUsage) and _is_citation(member):
                qname = element.qualified_name or element.label
                document = _literal(member, "document")
                found.append(
                    Citation(
                        element=element,
                        qname=qname,
                        document=str(document) if document is not None else "",
                        sha256=_literal(member, "sha256"),
                        quote=_literal(member, "quote"),
                        page=_literal(member, "page"),
                        bbox=_literal(member, "bbox"),
                        retrieved=_literal(member, "retrieved"),
                        usage=member,
                    )
                )
    return found


def _root_element(model: M.Model, root: M.Element | str | None) -> M.Element:
    if root is None:
        return model
    if isinstance(root, M.Element):
        return root
    from .interpreter import Resolver

    try:
        return Resolver(model).resolve(root)
    except ResolutionError as err:
        raise EditError(str(err)) from err


def _in_library(element: M.Element) -> bool:
    node: M.Element | None = element
    while node is not None:
        if isinstance(node, M.Package) and (node.is_library or node.is_standard):
            return True
        node = node.owner
    return False


# ---------------------------------------------------------------------------
# documents: cache, fetch, hash, extract
# ---------------------------------------------------------------------------


def cache_dir() -> Path:
    """The gitignored document cache: ``~/.cache/longeron/evidence``.

    ``$LONGERON_CACHE_DIR`` and ``$XDG_CACHE_HOME`` are honored, the same
    convention as the corpus cache (``scripts/check_corpus.py``).  The
    cache only speeds verification up; the sha256 on each citation stays
    the authority (the ratified design decision 1).
    """

    override = os.environ.get("LONGERON_CACHE_DIR")
    if override:
        return Path(override) / "evidence"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "longeron" / "evidence"


def _is_url(document: str) -> bool:
    return document.startswith(("http://", "https://"))


def _cached_fetch(url: str, *, fetch: bool = True) -> Path | None:
    """The local cache path for ``url``; download it once when allowed.

    Returns ``None`` when the document is not cached and either
    ``fetch=False`` or the download fails -- the caller reports
    ``unreachable``, honestly.
    """

    target = cache_dir() / hashlib.sha256(url.encode()).hexdigest()[:32]
    if target.is_file():
        return target
    if not fetch:
        return None
    request = urllib.request.Request(url, headers={"User-Agent": "longeron-evidence/0.12"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
    except (urllib.error.URLError, OSError, ValueError):
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _local_path(document: str, model: M.Model | None, *, fetch: bool = True) -> Path | None:
    """Resolve a citation document to a readable local file, or ``None``."""

    if _is_url(document):
        return _cached_fetch(document, fetch=fetch)
    path = Path(document)
    if not path.is_absolute() and model is not None and model.source_name:
        anchor = Path(model.source_name)
        base = anchor if anchor.is_dir() else anchor.parent
        candidate = base / path
        if candidate.is_file():
            return candidate
    return path if path.is_file() else None


def document_text(path: str | Path) -> str:
    """Extract the text of a local document.

    ``.pdf`` extracts through ``pypdf``, falling back to ``pdfminer.six``
    when pypdf yields no text (both ship with the ``[evidence]`` extra;
    :class:`~longeron.errors.MissingExtraError` names the install command
    without it).  HTML content -- by suffix or by sniffing the cached
    bytes of a URL document -- is reduced to its visible text (script and
    style content dropped, entities unescaped) with
    :mod:`html.parser`, so quotes anchor to the text a reader sees.
    Every other file reads as UTF-8 text, with undecodable bytes
    replaced.
    """

    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return _pdf_text(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    head = text[:1024].lower()
    if path.suffix.lower() in (".html", ".htm") or "<html" in head or "<!doctype html" in head:
        return _html_text(text)
    return text


def _html_text(markup: str) -> str:
    from html.parser import HTMLParser

    class _Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self._skip = 0

        def handle_starttag(self, tag: str, attrs: Any) -> None:
            if tag in ("script", "style"):
                self._skip += 1

        def handle_endtag(self, tag: str) -> None:
            if tag in ("script", "style") and self._skip:
                self._skip -= 1

        def handle_data(self, data: str) -> None:
            if not self._skip:
                self.parts.append(data)

    parser = _Text()
    parser.feed(markup)
    return " ".join(parser.parts)


def _pdf_text(path: Path) -> str:
    text = ""
    pypdf_error: Exception | None = None
    try:
        import pypdf
    except ImportError as err:
        pypdf_error = err
    else:
        reader = pypdf.PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if text.strip():
        return text
    try:
        from pdfminer.high_level import extract_text
    except ImportError as err:
        if pypdf_error is not None:
            raise MissingExtraError("PDF text extraction", "pypdf", "evidence") from err
        return text  # pypdf ran and found nothing; pdfminer is not there to retry
    return str(extract_text(str(path)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _quote_found(quote: str, text: str) -> bool:
    return _normalize(quote) in _normalize(text)


def _closest_match(quote: str, text: str) -> str | None:
    """The document's closest run of words to ``quote``, when cheap.

    A sliding word window the quote's own length, scored with difflib --
    skipped for very large documents (the refusal stays honest without
    the hint).
    """

    words = _normalize(text).split()
    target = _normalize(quote)
    width = max(len(target.split()), 1)
    if not words or len(words) > 200_000:
        return None
    windows = [" ".join(words[i : i + width]) for i in range(0, len(words) - width + 1)]
    best = difflib.get_close_matches(target, windows, n=1, cutoff=0.5)
    return best[0] if best else None


# ---------------------------------------------------------------------------
# attach
# ---------------------------------------------------------------------------


def attach(
    model: M.Model,
    element_or_qname: M.Element | str,
    document: str,
    quote: str,
    *,
    page: float | None = None,
    bbox: str | None = None,
    retrieved: str | None = None,
    sha256: str | None = None,
    verify: bool = True,
) -> M.MetadataUsage:
    """Cite ``document`` as the evidence for an element; returns the annotation.

    Reads the document (fetching a URL document once, into the cache),
    computes its sha256, extracts its text, and **refuses**
    (:class:`~longeron.errors.EditError`) when the text does not contain
    ``quote`` -- naming the document and, when cheaply computable, the
    closest text it does contain.  An unreadable document refuses too.
    A supplied ``sha256`` that contradicts the computed one refuses --
    the pin must be true.  Nothing mutates on any refusal, and the
    tracker records nothing.

    On success the citation is written through
    :func:`longeron.edit.add_metadata` (so a registered
    :class:`~longeron.edit.Tracker` records it) as an
    ``@Evidence::SourceEvidence`` annotation; ``retrieved`` defaults to
    today's ISO date.

    ``verify=False`` is the escape hatch for offline authoring: the
    document is not read, and the citation stores exactly what you pass
    (including ``sha256=None``).  :func:`verify` later reports what such
    a citation is worth.
    """

    from . import edit

    if verify:
        path = _local_path(document, model, fetch=True)
        if path is None:
            raise EditError(f"evidence document {document!r} cannot be read")
        digest = _sha256(path)
        if sha256 is not None and sha256 != digest:
            raise EditError(
                f"supplied sha256 does not match {document!r} (computed {digest[:12]}...)"
            )
        sha256 = digest
        text = document_text(path)
        if not _quote_found(quote, text):
            closest = _closest_match(quote, text)
            hint = f"; closest match: {closest!r}" if closest else ""
            raise EditError(f"quote {quote!r} does not appear in {document!r}{hint}")
        if retrieved is None:
            retrieved = datetime.date.today().isoformat()

    values: dict[str, Any] = {"document": document}
    if sha256 is not None:
        values["sha256"] = sha256
    if page is not None:
        values["page"] = float(page)
    values["quote"] = quote
    if bbox is not None:
        values["bbox"] = bbox
    if retrieved is not None:
        values["retrieved"] = retrieved
    return edit.add_metadata(model, element_or_qname, EVIDENCE_TYPE, values)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

Status = Literal["intact", "drifted", "lost", "unreachable"]


@dataclasses.dataclass
class Verdict:
    """One citation's verification result."""

    citation: Citation
    status: Status
    detail: str = ""

    def __str__(self) -> str:
        suffix = f" ({self.detail})" if self.detail else ""
        return f"{self.status}: {self.citation.qname} <- {self.citation.document}{suffix}"


def verify(
    model: M.Model, root: M.Element | str | None = None, *, fetch: bool = True
) -> list[Verdict]:
    """Re-check every citation under ``root``; one :class:`Verdict` each.

    - ``intact``: the document hashes to the citation's sha256 and its
      text still contains the quote.
    - ``drifted``: the document reads, but its sha256 changed.
    - ``lost``: the sha256 matches (or the citation never pinned one)
      but the text no longer contains the quote.
    - ``unreachable``: the file or URL cannot be read at all.

    ``fetch=False`` stays offline: URL documents verify against the
    local cache only, and an uncached one is ``unreachable`` (the lint
    seam uses this, so ``longeron lint`` never touches the network).
    """

    verdicts: list[Verdict] = []
    for citation in citations(model, root):
        verdicts.append(_verify_one(citation, model, fetch=fetch))
    return verdicts


def _verify_one(citation: Citation, model: M.Model, *, fetch: bool) -> Verdict:
    path = _local_path(citation.document, model, fetch=fetch)
    if path is None:
        return Verdict(citation, "unreachable", "document cannot be read")
    digest = _sha256(path)
    if citation.sha256 is not None and digest != citation.sha256:
        return Verdict(citation, "drifted", f"sha256 is now {digest[:12]}...")
    if citation.quote is None or not _quote_found(citation.quote, document_text(path)):
        return Verdict(citation, "lost", "text no longer contains the quote")
    return Verdict(citation, "intact")


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Fact:
    """One stated value: a leaf attribute with a literal (non-derived) value."""

    element: M.Element
    qname: str
    value: str
    documents: list[str]  #: cited documents (empty = uncited)

    @property
    def cited(self) -> bool:
        return bool(self.documents)


@dataclasses.dataclass
class CoverageReport:
    """Which stated values carry evidence -- counted, never inflated."""

    facts: list[Fact]

    @property
    def cited(self) -> int:
        return sum(fact.cited for fact in self.facts)

    @property
    def total(self) -> int:
        return len(self.facts)

    def __str__(self) -> str:
        rows = [(fact.qname, fact.value, ", ".join(fact.documents) or "-") for fact in self.facts]
        table = format_table(("element", "value", "evidence"), rows)
        return f"{table}\n{self.cited} of {self.total} stated value(s) cited"


def coverage(model: M.Model, root: M.Element | str | None = None) -> CoverageReport:
    """The honest coverage metric over the stated values under ``root``.

    A *stated value* is an attribute usage whose value expression is a
    literal fact -- a number, string, or boolean, optionally with a unit
    annotation or a sign.  Derived values (expressions over other
    features) state no independent fact and are not counted; constraint
    constants are not counted either (they live inside expressions, not
    on citable elements).  Library-package content is skipped.
    """

    cited_documents: dict[int, list[str]] = {}
    for citation in citations(model, root):
        cited_documents.setdefault(id(citation.element), []).append(citation.document)
    facts: list[Fact] = []
    start = _root_element(model, root)
    for element in start.iter_tree():
        if not isinstance(element, M.Usage) or element.kind != "attribute":
            continue
        if element.value is None or not _is_stated(element.value.expr) or _in_library(element):
            continue
        from .ast import expr_to_text

        facts.append(
            Fact(
                element=element,
                qname=element.qualified_name or element.label,
                value=expr_to_text(element.value.expr),
                documents=cited_documents.get(id(element), []),
            )
        )
    return CoverageReport(facts)


def _is_stated(expr: Any) -> bool:
    from . import ast as A

    if isinstance(expr, A.Literal):
        return True
    if isinstance(expr, A.Unary) and expr.op in {"+", "-"}:
        return _is_stated(expr.operand)
    if isinstance(expr, A.QuantityOp):
        return _is_stated(expr.base)
    return False


# ---------------------------------------------------------------------------
# the CLI's helpers
# ---------------------------------------------------------------------------


def format_table(headers: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> str:
    """A plain fixed-width text table (the CLI's verdict/coverage rendering)."""

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    lines = [
        "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip(),
        "  ".join("-" * w for w in widths),
    ]
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(lines)


def init_lfs(directory: str | Path = ".") -> Path:
    """Write the ``evidence/`` git-LFS stanza into ``<directory>/.gitattributes``.

    Storage pattern 1 of the provenance design: owned, redistributable
    documents commit under ``evidence/`` as LFS objects, so the binary
    pollution never starts.  Idempotent -- an existing stanza is left
    alone; anything else in ``.gitattributes`` is preserved.  Returns the
    ``.gitattributes`` path.
    """

    path = Path(directory) / ".gitattributes"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if "evidence/**" in existing:
        return path
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + LFS_STANZA, encoding="utf-8")
    return path
