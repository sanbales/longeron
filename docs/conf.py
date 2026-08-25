"""Sphinx configuration for the longeron documentation site.

Build with ``pixi run docs`` (or ``make docs`` from a venv with the
``[docs]`` extra installed): ``sphinx-build -W -b html docs build/docs``.

The tutorial pages are the committed notebooks from ``notebooks/``
(symlinked into ``docs/tutorials/``), which are stored output-free by repo
convention; myst-nb executes them during the build to produce the outputs.
Execution therefore needs the ``dev`` extras (solvers, ipykernel) plus node
on ``PATH`` for headless diagram rendering -- the pixi ``docs`` environment
provides all of it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# autodoc imports longeron straight from the checkout
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "docs" / "_ext"))

import longeron  # noqa: E402  (needs the path insertion above)

project = "longeron"
author = "sanbales"
copyright = "2025, sanbales"
version = longeron.__version__
release = version

extensions = [
    "myst_nb",  # MyST markdown + executed notebooks (bundles myst_parser)
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx_autodoc_typehints",
    "sphinx_copybutton",
    "sphinx_design",
    "widget_snapshots",  # docs/_ext: captured PNGs replace live widget outputs
]

exclude_patterns = [
    "_build",
    "examples",  # symlink to ../examples so notebook data paths resolve
    "**.ipynb_checkpoints",
]

# -- MyST ------------------------------------------------------------------

myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3

# -- myst-nb: execute the tutorial notebooks at build time ------------------

nb_execution_mode = "cache"  # re-run only when a notebook changes
nb_execution_timeout = 600  # mirrors tests/test_notebooks.py
nb_execution_raise_on_error = True
nb_output_stderr = "remove"  # solver / widget chatter is not content
# Interactive widgets (ipyelk diagrams, anywidget viewers) cannot run on a
# static site.  Captured PNG snapshots stand in for them: the
# widget_snapshots extension (docs/_ext/) replaces manifest-listed widget
# outputs with images from docs/_static/widget-snapshots/ (regenerate with
# `pixi run capture-widgets`).  For widget outputs WITHOUT a snapshot
# (a freshly added cell before re-capture), dropping the widget-view
# mime type below makes the text/plain repr render as the placeholder.
nb_mime_priority_overrides = [
    ("html", "application/vnd.jupyter.widget-view+json", None),
]
suppress_warnings = ["mystnb.unknown_mime_type"]

# -- autodoc ---------------------------------------------------------------

autodoc_member_order = "bysource"
autodoc_default_options = {
    "members": True,
    "show-inheritance": True,
}
autosummary_generate = False  # reference pages are hand-curated
always_document_param_types = False
typehints_defaults = "comma"

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# -- HTML ------------------------------------------------------------------

html_theme = "furo"
html_static_path = ["_static"]  # widget snapshots (PNGs, manifest, CSS)
html_title = f"longeron {release}"
html_theme_options = {
    "source_repository": "https://github.com/sanbales/longeron",
    "source_branch": "main",
    "source_directory": "docs/",
}

copybutton_exclude = ".linenos, .gp, .go"


def _patch_geometry_docstring(app, what, name, obj, options, lines):
    """Make the geometry module docstring's mesh-dict example a literal block.

    The docstring introduces an indented example with ``paints:`` (single
    colon), which docutils misreads as a definition list. The source fix is
    one character, but ``src/longeron`` belongs to the code owners -- patch it
    at build time instead (a no-op once the docstring is fixed upstream).
    """

    if name == "longeron.analysis.geometry" and what == "module":
        for index, line in enumerate(lines):
            if line.endswith("paints:"):
                lines[index] = line + ":"


def setup(app):
    from sysml_lexer import SysMLLexer

    app.add_lexer("sysml", SysMLLexer)
    app.connect("autodoc-process-docstring", _patch_geometry_docstring)
