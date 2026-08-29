"""The widget layer: longeron's interactive front-ends, in one place.

This package has three jobs.  It is the shared toolkit for widget
authors (the anywidget conventions the house front-ends follow: baked
JSON traitlets, kernel-side computation, on-demand rendering).  It is
the mandatory home for every new widget.  And it will grow into the
catalog of the house widgets -- today those still live where they grew
up (:mod:`longeron.replay`, :mod:`longeron.explorer`, the
:mod:`longeron.analysis` viewers); re-exports arrive in a follow-up.

Current residents:

* :mod:`longeron.widgets.graph3d` -- the RDF projection as an
  interactive 3D force-directed graph (``rdf`` + ``viz`` extras).
"""

__all__ = ["graph3d"]
