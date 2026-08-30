"""Evidence-linked models (longeron.evidence): the provenance toolchain.

These tests pin the layer-2 contract of ``docs/design/provenance.md``:
``attach`` verifies the quote against the document and refuses honestly
(nothing mutates, the tracker stays silent), ``verify`` returns the full
verdict matrix (intact / drifted / lost / unreachable) on generated
fixture documents -- including an in-test, owned PDF -- ``coverage``
counts stated values without inflation, citations survive the JSON
round-trip, the lint seam grows ``evidence-drift`` (default) and
``unevidenced-value`` (opt-in) without touching citation-free models,
and the CLI's ``evidence init`` / ``evidence verify`` behave as the CLI
guide documents them.
"""

import sys
from pathlib import Path

import pytest

import longeron
from longeron import edit, evidence
from longeron.cli import main
from longeron.errors import EditError, MissingExtraError
from longeron.validation import validate

MODEL = """
package P {
    part def Motor {
        attribute mass : Real = 0.055;
        attribute kv : Real = 935.0;
        attribute doubled : Real = mass * 2.0;
    }
}
"""

SPEC = "Motor MT2213-935KV\nWeight: 55 g\nKV: 935 rpm/V\n"


@pytest.fixture
def workspace(tmp_path):
    """A model file with a spec document beside it; returns (model, tmp_path)."""

    (tmp_path / "spec.txt").write_text(SPEC)
    (tmp_path / "m.sysml").write_text(MODEL)
    return longeron.load(tmp_path / "m.sysml", cache=False), tmp_path


def make_pdf(text: str) -> bytes:
    """A minimal single-page PDF whose content stream shows ``text``."""

    def esc(line: str) -> str:
        return line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    lines = text.splitlines() or [""]
    shows = " T* ".join(f"({esc(line)}) Tj" for line in lines)
    stream = f"BT /F1 12 Tf 72 720 Td 14 TL {shows} ET".encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


# ---------------------------------------------------------------------------
# attach
# ---------------------------------------------------------------------------


class TestAttach:
    def test_writes_the_citation_and_records_it(self, workspace):
        model, _ = workspace
        tracker = edit.track(model)
        usage = evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g")
        assert usage.typed_by == "Evidence::SourceEvidence"
        [citation] = evidence.citations(model)
        assert citation.qname == "P::Motor::mass"
        assert citation.document == "spec.txt"
        assert citation.quote == "Weight: 55 g"
        assert len(citation.sha256) == 64
        assert citation.retrieved  # defaults to today's ISO date
        assert [c.op for c in tracker.changes] == ["add_metadata"]
        # the export stays parseable and at a fixpoint
        assert longeron.to_sysml(longeron.loads(longeron.to_sysml(model))) == longeron.to_sysml(
            model
        )

    def test_missing_quote_refuses_and_mutates_nothing(self, workspace):
        model, _ = workspace
        tracker = edit.track(model)
        before = longeron.to_sysml(model)
        with pytest.raises(EditError) as err:
            evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 58 g")
        assert "spec.txt" in str(err.value)
        assert "Weight: 55 g" in str(err.value)  # the closest match, named
        assert longeron.to_sysml(model) == before
        assert not tracker.changes

    def test_unreadable_document_refuses(self, workspace):
        model, _ = workspace
        with pytest.raises(EditError, match="cannot be read"):
            evidence.attach(model, "P::Motor::mass", "ghost.txt", "Weight: 55 g")

    def test_contradicting_sha256_refuses(self, workspace):
        model, _ = workspace
        with pytest.raises(EditError, match="does not match"):
            evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g", sha256="0" * 64)

    def test_quote_matching_survives_rewrapping(self, workspace):
        model, _ = workspace
        evidence.attach(model, "P::Motor::mass", "spec.txt", "55 g\nKV:  935")
        assert evidence.citations(model)

    def test_verify_false_authors_offline(self, workspace):
        model, _ = workspace
        evidence.attach(model, "P::Motor::mass", "ghost.txt", "unchecked", verify=False)
        [citation] = evidence.citations(model)
        assert citation.sha256 is None and citation.retrieved is None

    def test_page_and_bbox_are_optional_locators(self, workspace):
        model, _ = workspace
        evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g", page=2, bbox="1,2,3,4")
        [citation] = evidence.citations(model)
        assert citation.page == 2.0 and citation.bbox == "1,2,3,4"

    def test_citations_survive_the_json_round_trip(self, workspace):
        model, _ = workspace
        evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g")
        restored = longeron.from_json(longeron.to_json(model))
        assert longeron.to_sysml(restored) == longeron.to_sysml(model)
        restored.source_name = model.source_name  # JSON carries no source path
        assert [v.status for v in evidence.verify(restored)] == ["intact"]


# ---------------------------------------------------------------------------
# the verdict matrix
# ---------------------------------------------------------------------------


class TestVerdicts:
    def test_intact(self, workspace):
        model, _ = workspace
        evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g")
        [verdict] = evidence.verify(model)
        assert verdict.status == "intact"

    def test_drifted_on_hash_mismatch(self, workspace):
        model, tmp = workspace
        evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g")
        (tmp / "spec.txt").write_text(SPEC + "revision B\n")
        [verdict] = evidence.verify(model)
        assert verdict.status == "drifted"
        assert "sha256" in verdict.detail

    def test_lost_on_intact_hash_without_the_quote(self, workspace):
        model, tmp = workspace
        digest = evidence._sha256(tmp / "spec.txt")
        evidence.attach(
            model, "P::Motor::mass", "spec.txt", "Weight: 58 g", sha256=digest, verify=False
        )
        [verdict] = evidence.verify(model)
        assert verdict.status == "lost"

    def test_unreachable_on_missing_document(self, workspace):
        model, tmp = workspace
        evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g")
        (tmp / "spec.txt").unlink()
        [verdict] = evidence.verify(model)
        assert verdict.status == "unreachable"

    def test_pdf_document_verifies(self, workspace):
        model, tmp = workspace
        (tmp / "spec.pdf").write_bytes(make_pdf(SPEC))
        evidence.attach(model, "P::Motor::kv", "spec.pdf", "KV: 935 rpm/V")
        assert [v.status for v in evidence.verify(model)] == ["intact"]

    def test_url_documents_verify_through_the_cache(self, workspace, monkeypatch, tmp_path):
        model, _ = workspace
        monkeypatch.setenv("LONGERON_CACHE_DIR", str(tmp_path / "cache"))
        url = "https://example.invalid/spec.txt"
        # offline and uncached: honestly unreachable, attach refuses
        with pytest.raises(EditError, match="cannot be read"):
            evidence.attach(model, "P::Motor::mass", url, "Weight: 55 g")
        # seed the cache as a successful fetch would
        cached = evidence.cache_dir() / "seeded"
        cached.parent.mkdir(parents=True)
        cached.write_text(SPEC)
        monkeypatch.setattr(evidence, "_cached_fetch", lambda u, fetch=True: cached)
        evidence.attach(model, "P::Motor::mass", url, "Weight: 55 g")
        assert [v.status for v in evidence.verify(model)] == ["intact"]
        # fetch=False consults the cache only
        monkeypatch.setattr(
            evidence, "_cached_fetch", lambda u, fetch=True: cached if not fetch else None
        )
        assert [v.status for v in evidence.verify(model, fetch=False)] == ["intact"]


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------


class TestCoverage:
    def test_counts_stated_values_never_inflated(self, workspace):
        model, _ = workspace
        report = evidence.coverage(model)
        # mass and kv are stated; doubled is derived and does not count
        assert {fact.qname for fact in report.facts} == {"P::Motor::mass", "P::Motor::kv"}
        assert (report.cited, report.total) == (0, 2)
        evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g")
        report = evidence.coverage(model)
        assert (report.cited, report.total) == (1, 2)

    def test_report_prints_as_a_table(self, workspace):
        model, _ = workspace
        evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g")
        text = str(evidence.coverage(model))
        assert "P::Motor::mass" in text and "spec.txt" in text
        assert "1 of 2 stated value(s) cited" in text

    def test_quantity_and_negative_values_are_stated(self):
        model = longeron.loads(
            "package P { part def D { attribute m : Real = 0.5 [SI::kg];"
            " attribute t : Real = -40.0; } }"
        )
        assert evidence.coverage(model).total == 2


# ---------------------------------------------------------------------------
# the lint seam
# ---------------------------------------------------------------------------


class TestLint:
    def test_drift_warns_by_default(self, workspace):
        model, tmp = workspace
        evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g")
        (tmp / "spec.txt").write_text("revision B\n")
        codes = [d.code for d in validate(model)]
        assert codes.count("evidence-drift") == 1

    def test_lost_quote_warns_too(self, workspace):
        model, tmp = workspace
        digest = evidence._sha256(tmp / "spec.txt")
        evidence.attach(
            model, "P::Motor::mass", "spec.txt", "Weight: 58 g", sha256=digest, verify=False
        )
        [diagnostic] = [d for d in validate(model) if d.code == "evidence-drift"]
        assert diagnostic.severity == "warning"
        assert "Weight: 58 g" in diagnostic.message

    def test_intact_and_unreachable_citations_stay_silent(self, workspace):
        model, tmp = workspace
        evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g")
        assert [d.code for d in validate(model)] == []
        (tmp / "spec.txt").unlink()  # unreachable: the lint cannot judge
        assert [d.code for d in validate(model)] == []

    def test_citation_free_models_are_untouched(self, workspace):
        model, _ = workspace
        for diagnostic in validate(model) + validate(model, evidence_coverage=False):
            assert diagnostic.code not in ("evidence-drift", "unevidenced-value")

    def test_unevidenced_value_is_opt_in(self, workspace):
        model, _ = workspace
        evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g")
        assert "unevidenced-value" not in [d.code for d in validate(model)]
        diagnostics = [
            d for d in validate(model, evidence_coverage=True) if d.code == ("unevidenced-value")
        ]
        assert [d.element for d in diagnostics] == ["P::Motor::kv"]  # cited + derived stay silent


# ---------------------------------------------------------------------------
# the edit seam
# ---------------------------------------------------------------------------


class TestAddMetadata:
    def test_appends_and_round_trips(self):
        model = longeron.loads("package P { part def D; }")
        edit.add_metadata(model, "P::D", "Safety", {"level": 3, "audited": True})
        text = longeron.to_sysml(model)
        assert "@Safety" in text and "level = 3;" in text
        assert longeron.to_sysml(longeron.loads(text)) == text

    def test_refuses_non_literal_values_and_blank_types(self):
        model = longeron.loads("package P { part def D; }")
        tracker = edit.track(model)
        with pytest.raises(EditError, match="literal"):
            edit.add_metadata(model, "P::D", "Safety", {"level": [1]})
        with pytest.raises(EditError, match="non-empty"):
            edit.add_metadata(model, "P::D", "  ")
        assert not tracker.changes


# ---------------------------------------------------------------------------
# the CLI
# ---------------------------------------------------------------------------


class TestCli:
    def _cited_workspace(self, tmp_path) -> Path:
        (tmp_path / "spec.txt").write_text(SPEC)
        (tmp_path / "m.sysml").write_text(MODEL)
        model = longeron.load(tmp_path / "m.sysml", cache=False)
        evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g")
        path = tmp_path / "cited.sysml"
        path.write_text(longeron.to_sysml(model))
        return path

    def test_verify_exits_zero_when_intact(self, tmp_path, capsys):
        path = self._cited_workspace(tmp_path)
        assert main(["evidence", "verify", "--no-cache", str(path)]) == 0
        out = capsys.readouterr().out
        assert "intact" in out and "1 citation(s): 0 drifted or lost" in out

    def test_verify_exit_code_counts_drifted_and_lost(self, tmp_path, capsys):
        path = self._cited_workspace(tmp_path)
        (tmp_path / "spec.txt").write_text("revision B\n")
        assert main(["evidence", "verify", "--no-cache", str(path)]) == 1
        assert "drifted" in capsys.readouterr().out

    def test_init_writes_the_lfs_stanza_idempotently(self, tmp_path, capsys):
        (tmp_path / ".gitattributes").write_text("*.png binary\n")
        assert main(["evidence", "init", str(tmp_path)]) == 0
        first = (tmp_path / ".gitattributes").read_text()
        assert first.startswith("*.png binary\n")  # existing content preserved
        assert "evidence/** filter=lfs diff=lfs merge=lfs -text" in first
        assert main(["evidence", "init", str(tmp_path)]) == 0
        assert (tmp_path / ".gitattributes").read_text() == first

    def test_lint_grows_the_evidence_coverage_flag(self, tmp_path, capsys):
        (tmp_path / "m.sysml").write_text(MODEL)
        assert main(["lint", "--no-cache", str(tmp_path / "m.sysml")]) == 0
        assert "0 warning(s)" in capsys.readouterr().out
        assert main(["lint", "--no-cache", "--evidence-coverage", str(tmp_path / "m.sysml")]) == 0
        assert "unevidenced-value" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# extras gating
# ---------------------------------------------------------------------------


class TestExtrasGating:
    def test_pdf_extraction_without_the_extra_names_the_install(
        self, workspace, monkeypatch, tmp_path
    ):
        model, tmp = workspace
        (tmp / "spec.pdf").write_bytes(make_pdf(SPEC))
        monkeypatch.setitem(sys.modules, "pypdf", None)  # import raises ImportError
        monkeypatch.setitem(sys.modules, "pdfminer.high_level", None)
        monkeypatch.setitem(sys.modules, "pdfminer", None)
        with pytest.raises(MissingExtraError) as err:
            evidence.attach(model, "P::Motor::mass", "spec.pdf", "Weight: 55 g")
        assert 'pip install "longeron[evidence]"' in str(err.value)

    def test_text_documents_need_no_extra(self, workspace, monkeypatch):
        model, _ = workspace
        monkeypatch.setitem(sys.modules, "pypdf", None)
        evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g")
        assert [v.status for v in evidence.verify(model)] == ["intact"]


# ---------------------------------------------------------------------------
# the shipped vocabulary
# ---------------------------------------------------------------------------


EXAMPLES = Path(__file__).parent.parent / "examples"


class TestVocabulary:
    def test_evidence_sysml_parses_lints_and_round_trips(self):
        model = longeron.load(EXAMPLES / "evidence.sysml", cache=False)
        assert validate(model) == []
        restored = longeron.from_json(longeron.to_json(model))
        assert longeron.to_sysml(restored) == longeron.to_sysml(model)

    def test_deepscout_citations_resolve_against_the_vocabulary(self):
        # the first customer: real manufacturer-page citations (URL + sha256 +
        # quote, storage pattern 2 -- nothing committed), and the vocabulary
        # package resolves every citation's metadata typing when loaded along
        model = longeron.load_many(
            [*sorted((EXAMPLES / "deepscout").glob("*.sysml")), EXAMPLES / "evidence.sysml"],
            cache=False,
        )
        deepscout_citations = evidence.citations(model)
        assert len(deepscout_citations) >= 1
        for citation in deepscout_citations:
            assert citation.document.startswith("https://")
            assert citation.quote and citation.sha256 and citation.retrieved
        from longeron.interpreter import Resolver

        resolver = Resolver(model)
        for citation in deepscout_citations:
            assert citation.usage is not None
            target = resolver.resolve(citation.usage.typed_by, citation.element)
            assert target.qualified_name == "Evidence::SourceEvidence"
        assert validate(model) == []


class TestFindCitations:
    def test_root_narrows_the_walk(self, workspace):
        model, _ = workspace
        evidence.attach(model, "P::Motor::mass", "spec.txt", "Weight: 55 g")
        assert evidence.citations(model, "P::Motor") != []
        assert evidence.citations(model, "P::Motor::kv") == []
        with pytest.raises(EditError):
            evidence.citations(model, "P::Ghost")

    def test_library_packages_are_context_not_subjects(self):
        model = longeron.loads(
            "library package L { part def D { attribute m : Real = 1.0"
            ' { @Evidence::SourceEvidence { document = "x"; quote = "q"; } } } }'
        )
        assert evidence.citations(model) == []
        assert evidence.coverage(model).total == 0
