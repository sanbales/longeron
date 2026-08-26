"""Scenario 6: universal fit -- a PLAIN inline diagram self-fits.

The maintainer repro (NB10 cell 5): a diagram displayed beside a 3D
viewer in an HBox, squeezed to 55% of the cell, rendered CROPPED -- the
kernel's first-layout auto-fit was dropped while the sprotty view was
still constructing, and nothing ever re-fit it.  The fix lifted the
explorer's fit sentinel into the diagram BUILDER (``diagrams._finish``):
every built widget carries the sentinel inside its own DOM, so plain
``display(widget)`` -- zero consumer wiring -- gets fitted on first
reveal and re-fitted on container resizes, always respecting the user's
pan/zoom latch.

Three phases against the ``hbox_fit_scenario`` notebook:

1. first render: the wide state machine lands FITTED to its narrow
   column (scale < 1: unambiguously the auto-fit's doing), and the
   kernel-side sentinel counters prove the ``fresh`` report arrived;
2. container resize (a viewport shrink narrows the cell): a debounced
   ``resized`` report re-fits the diagram to the NEW box;
3. the user latch: after a pan, another resize must NOT re-frame the
   viewport (the transform stays exactly the panned one and the kernel
   sees no further ``resized`` report).
"""

import pytest

pytestmark = pytest.mark.browser

NOTEBOOK = "hbox_fit_scenario.ipynb"

#: the ONE diagram widget's framing, browser-truth: the widget's root box
#: carries the ``lgx-diagram`` class (the sentinel's own DOM handle), the
#: sprotty host div inside it is the viewport, and the root <g> transform
#: off the identity is the auto-fit's browser-visible effect
_DIAGRAM_JS = r"""() => {
    const hosts = [...document.querySelectorAll(
        '.lgx-diagram div.sprotty[id^="sprotty"]',
    )].filter((div) => div.getBoundingClientRect().width > 0);
    if (hosts.length !== 1) return { hosts: hosts.length };
    const div = hosts[0];
    const g = div.querySelector('svg.sprotty-graph > g');
    if (!g) return { hosts: 1, rendered: false };
    const view = div.getBoundingClientRect();
    const content = g.getBoundingClientRect();
    const transform = g.getAttribute('transform') || '';
    const zoom = /scale\(([\d.eE+-]+)/.exec(transform);
    return {
        hosts: 1,
        rendered: content.width > 0,
        transform,
        fitted: transform !== '' && transform !== 'scale(1) translate(0,0)'
            && transform !== 'translate(0, 0) scale(1)',
        scale: zoom ? Number(zoom[1]) : 1,
        viewWidth: view.width,
        viewX: view.x,
        viewY: view.y,
        overflowX: Math.max(0, view.left - content.left, content.right - view.right),
        overflowY: Math.max(0, view.top - content.top, content.bottom - view.bottom),
    };
}"""

#: sub-pixel slack for getBoundingClientRect rounding
OVERFLOW_TOLERANCE_PX = 1.5


def _diagram(page) -> dict:
    state = page.evaluate(_DIAGRAM_JS)
    return dict(state) if state else {}


def _fits_box(state: dict) -> bool:
    return bool(
        state.get("rendered")
        and state.get("fitted")
        and state.get("overflowX", 1e9) <= OVERFLOW_TOLERANCE_PX
        and state.get("overflowY", 1e9) <= OVERFLOW_TOLERANCE_PX
    )


def test_inline_hbox_diagram_self_fits_and_honors_the_latch(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(min_widgets=1, min_fitted=1, timeout=180)
    page = lab.page

    # -- 1. first render: fitted to the narrow column, not cropped ----------
    lab.wait_until(
        lambda s: _fits_box(_diagram(page)),
        timeout=120,
        label="inline HBox diagram fitted within its own box",
    )
    first = _diagram(page)
    # the wide machine only fits its 55% column scaled DOWN: scale < 1
    # means the fit really answered THIS box (identity would crop)
    assert first["scale"] < 1, first
    counters = lab.run_cell_json(index=-1)
    assert counters["fresh"] >= 1, counters  # the sentinel's view report arrived
    assert counters["fit_count"] >= 1, counters
    assert counters["fit_stamp"] == counters["fit_count"], counters  # latch cleared per fit

    # -- 2. container resize: the sentinel re-fits to the NEW box -----------
    page.set_viewport_size({"width": 950, "height": 1100})
    lab.wait_until(
        lambda s: (lambda d: _fits_box(d) and d.get("viewWidth", 1e9) < first["viewWidth"] - 50)(
            _diagram(page)
        ),
        timeout=60,
        label="diagram re-fitted after the container narrowed",
    )
    resized = lab.run_cell_json(index=-1)
    assert resized["resized"] >= 1, resized  # the debounced resize report arrived

    # -- 3. the user's viewport is theirs: pan, then resize -> NO re-fit ----
    # re-running the checker scrolled the notebook to the last cell; bring
    # the diagram back into the visual viewport so the drag actually lands
    page.evaluate("() => document.querySelector('.lgx-diagram').scrollIntoView({block: 'center'})")
    page.wait_for_timeout(500)
    state = _diagram(page)
    x, y = state["viewX"] + 40, state["viewY"] + 40
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 90, y + 45, steps=5)
    page.mouse.up()
    panned = _diagram(page)["transform"]
    page.set_viewport_size({"width": 1500, "height": 1100})
    page.wait_for_timeout(2500)  # well past the sentinel's 200ms debounce
    after = lab.run_cell_json(index=-1)
    assert after["resized"] == resized["resized"], after  # latch held: no report
    assert _diagram(page)["transform"] == panned  # viewport untouched

    lab.assert_no_errors()
