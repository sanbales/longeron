"""Browser-truth: the two-subject surfaces proof, rendered.

The kernel-side tests (tests/test_analysis_surfaces.py) prove the
derivation: mined slider bounds, applicability, explicit couplings, the
wiring map.  What only a browser can prove is that the ONE declaration
renders as a real surface for two different subjects on one page -- the
what-if sliders, the verdict card, and the HONEST ABSENCE card with its
stated reason all visible -- and that a kernel-side slider move repaints
the rendered verdict.

Each stage saves a PNG under ``build/evidence/``.
"""

from __future__ import annotations

from typing import Any

import pytest

from .conftest import REPO

pytestmark = pytest.mark.browser

NOTEBOOK = "surfaces_scenario.ipynb"
EVIDENCE = REPO / "build" / "evidence"


def test_one_declaration_serves_two_subjects(lab: Any) -> None:
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    # the surface is plain ipywidgets (no elk/sprotty cells), so the settle
    # gate is: nothing busy, then the sliders exist in the DOM
    lab.wait_settled(timeout=240)
    lab.page.wait_for_selector(".widget-hslider", timeout=120_000)
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    # -- kernel truth: both derivations came from the same declaration ------
    state = lab.run_cell_json(2)
    assert state["quad"]["subject"] == "Rotorcraft::QuadCopter"
    assert state["hexa"]["subject"] == "Rotorcraft::HexaCopter"
    for craft in ("quad", "hexa"):
        panels = state[craft]["panels"]
        assert not panels["cameraPane"]["absent"]
        assert panels["cameraPane"]["ranges"]["elevation"] == [-90.0, 90.0]
        assert panels["cameraPane"]["ranges"]["azimuth"] == [-180.0, 180.0]
        assert panels["installationPane"]["verdict"] == "pass"
        assert panels["loiterPane"]["absent"]
        assert "ScoutSizing::IsrPrime" in panels["loiterPane"]["reason"]

    # -- rendered truth: sliders, verdicts, and the absence cards -----------
    page = lab.page
    assert page.locator(".widget-hslider").count() >= 4  # 2 camera sliders x 2
    assert page.locator("text=not derived for this subject").count() >= 2
    assert page.locator("text=LoiterWhatIf applies to ScoutSizing::IsrPrime").count() >= 2
    assert page.locator("text=PASS").count() >= 2
    page.screenshot(path=str(EVIDENCE / "surfaces_two_subjects.png"), full_page=True)

    # -- the coupling, watched from the browser: kernel slider move ->
    #    occlusion re-measure -> explicit binding -> the card flips to FAIL --
    driven = lab.run_cell_json(3)
    assert driven["verdict"] == "fail"
    assert driven["occluded"] > 0.0
    # exact-text match scoped to the surface: bare text=FAIL is
    # case-insensitive-substring and matches unrelated sidebar session
    # labels (e.g. 'layout-failure-scenario...')
    page.wait_for_selector('.jp-OutputArea :text-is("FAIL")', timeout=30_000)
    page.screenshot(path=str(EVIDENCE / "surfaces_quad_verdict_fail.png"), full_page=True)

    # -- and back: the declared defaults restore the clean verdict ----------
    restored = lab.run_cell_json(4)
    assert restored["verdict"] == "pass"
    assert restored["occluded"] == 0.0

    lab.assert_no_errors()
