"""Scenario 6: no compartment label may overflow its node -- any direction.

The maintainer repro: the drone model's structure diagram, QuadCopter --
an EXPANDED compound node (children AND wide attribute rows) -- toggled
top-down via the toolbar.  elkjs 0.9.3 sizes compound nodes under a
vertical flow in its internal horizontal coordinates, so the widest row
inflated the HEIGHT while the width collapsed to children + padding and
the ``totalMass`` row ran past the node border.  The fix
(``toolbar._fit_compound_labels``) pins compound widths through the
(swapped) ``elk.nodeSize.minimum``; this test is the browser-truth
tripwire for the whole overflow class -- every node, every label kind,
both directions.

The second maintainer repro rides the same scenario: ``Hauler`` mirrors
UavMissions' ``LogisticsUav`` (an expanded compound with an ABSURDLY wide
calculation row) -- under the un-fixed top-down flow its rows poked far
left of the collapsed box, a glob of text over the package's top-left
corner.  With the default ``max_label_width`` cap the row must draw
END-ellipsized, its node capped near 480px, and the FULL text must ride
the label's svg ``<title>`` (the native hover tooltip).
"""

import pytest

pytestmark = pytest.mark.browser

NOTEBOOK = "label_fit_scenario.ipynb"

#: containment tolerance, in DIAGRAM px (the acceptance contract: no
#: compartment label may overflow its node on any side).  The vertical
#: tolerance is looser: a text client-rect spans the font's full ascent +
#: descent, which pokes a few px past the 15px row boxes ELK reserves.
TOLERANCE = 2.0
VERTICAL_TOLERANCE = 5.0

#: the default diagrams._MAX_LABEL_WIDTH row cap plus the node's side
#: padding and the fit's 20px allowance -- the Hauler box must stay near it
MAX_CAPPED_NODE_WIDTH = 480.0 + 40.0

#: for every node-owned INSIDE label: how far the text's client-rect pokes
#: past its owning node's rect (negative = safely inside).  A label's
#: owning node group is the nearest ancestor <g> holding the node's mark
#: (rect/polygon/ellipse, class .elknode); labels reached through an
#: .elkedge group are edge labels -- a different placement contract.
#: OUTSIDE node labels (package tabs, glyph captions below markers) are
#: excluded by the vertical-center test.  The display string is the text
#: node children only (a truncated label also carries a <title> child --
#: the hover tooltip -- which textContent would include).  Distances are
#: divided by the viewport zoom so assertions read in diagram coordinates.
_OVERFLOW_JS = """() => {
  const svg = document.querySelector('.sprotty svg.sprotty-graph');
  const transform = svg.querySelector(':scope > g').getAttribute('transform') || '';
  const zoom = +(transform.match(/scale\\(([\\d.]+)\\)/) || [0, 1])[1];
  const labels = [];
  for (const text of svg.querySelectorAll('text.elklabel')) {
    let el = text.parentElement, mark = null, viaEdge = false;
    while (el && el !== svg) {
      if (el.classList.contains('elkedge')) { viaEdge = true; break; }
      if (el.tagName === 'g') {
        mark = [...el.children].find(
          (c) => c.classList && c.classList.contains('elknode'));
        if (mark) break;
      }
      el = el.parentElement;
    }
    if (!mark || viaEdge) continue;
    const tb = text.getBoundingClientRect();
    const nb = mark.getBoundingClientRect();
    const centerY = (tb.top + tb.bottom) / 2;
    if (centerY < nb.top || centerY > nb.bottom) continue;  // OUTSIDE label
    const display = [...text.childNodes]
      .filter((n) => n.nodeType === Node.TEXT_NODE)
      .map((n) => n.data).join('');
    const title = text.querySelector('title');
    labels.push({
      text: display.slice(0, 60),
      truncated: display.endsWith('\\u2026'),
      tooltip: title ? title.textContent : null,
      nodeWidth: nb.width / zoom,
      overRight: (tb.right - nb.right) / zoom,
      overLeft: (nb.left - tb.left) / zoom,
      overTop: (nb.top - tb.top) / zoom,
      overBottom: (tb.bottom - nb.bottom) / zoom,
    });
  }
  return labels;
}"""

_SIDES = {
    "overRight": TOLERANCE,
    "overLeft": TOLERANCE,
    "overTop": VERTICAL_TOLERANCE,
    "overBottom": VERTICAL_TOLERANCE,
}


def _assert_labels_fit(page, phase: str) -> list[dict]:
    labels = page.evaluate(_OVERFLOW_JS)
    assert labels, f"{phase}: the probe found no node-owned labels"
    overflowing = [
        label for label in labels if any(label[side] > limit for side, limit in _SIDES.items())
    ]
    assert overflowing == [], f"{phase}: labels overflow their node: {overflowing}"
    return labels


def _assert_capped_row(labels: list[dict], phase: str) -> None:
    """The absurd Hauler calculation row: ellipsized, capped, full text on
    the hover <title> -- in every direction."""

    row = next((label for label in labels if label["text"].startswith("outboundPowerW")), None)
    assert row is not None, f"{phase}: the Hauler calculation row was not probed"
    assert row["truncated"], f"{phase}: expected an ellipsized row: {row}"
    assert row["nodeWidth"] <= MAX_CAPPED_NODE_WIDTH + TOLERANCE, f"{phase}: {row}"
    tooltip = row["tooltip"] or ""
    assert tooltip.startswith("outboundPowerW : Real = basePowerW"), f"{phase}: {row}"
    assert tooltip.rstrip().endswith("/ missionSec"), f"{phase}: {row}"


def test_compartment_rows_fit_their_node_in_both_directions(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(min_widgets=1, min_fitted=1, timeout=180)
    page = lab.page

    labels = _assert_labels_fit(page, "left-to-right")
    # the QuadCopter compartment (5 rows + stereotype + title), the Hauler
    # box and the part defs must all be probed, or the tripwire proves
    # nothing
    assert len(labels) >= 20, f"expected the full drone structure probed, got {len(labels)}"
    _assert_capped_row(labels, "left-to-right")

    # -- toggle top-down via the toolbar (the maintainer repro) ---------------
    page.hover(".jp-ElkApp")  # the toolbar is hover-revealed
    page.click("button[title^='Layout direction:']")
    lab.wait_settled(min_widgets=1, timeout=120)
    checker = lab.run_cell_json(index=-1)
    assert checker["direction"] == "DOWN", checker

    labels = _assert_labels_fit(page, "top-down")
    _assert_capped_row(labels, "top-down")

    # -- and back: the fit options must restore losslessly --------------------
    page.hover(".jp-ElkApp")
    page.click("button[title^='Layout direction:']")
    lab.wait_settled(min_widgets=1, timeout=120)
    _assert_labels_fit(page, "left-to-right again")

    lab.assert_no_errors()
