"""Render captured widget snapshots in place of live widget-view outputs.

Interactive widgets (ipyelk diagrams, anywidget viewers) cannot run on a
static site.  ``scripts/capture_widget_snapshots.py`` screenshots each
rendered widget output from a real JupyterLab session into
``docs/_static/widget-snapshots/`` (committed PNGs plus a
``manifest.json``); this extension swaps those snapshots into the built
tutorial pages so readers see the real rendered output instead of a
``Diagram(...)`` text placeholder.

Mechanism (why a post-transform, and not the alternatives): myst-nb's
Sphinx renderer emits *every* mime type of an output into the cached
doctree -- one ``container(nb_element="mime_bundle")`` per output, with a
``container(mime_type=...)`` child per representation -- and only selects
which child survives in its ``SelectMimeType`` post-transform at priority
4.  A post-transform at priority 3 can therefore replace whole widget
bundles using only documented docutils tree structure, keyed off the
manifest.  The alternatives lose: myst-nb's mime-render *plugins* are
discovered exclusively through ``importlib.metadata`` entry points, which
would force either packaging/installing a distribution or monkeypatching
``myst_nb.core.render.load_mime_renders``; and materializing executed
notebooks with baked-in PNG outputs into a parallel source dir would fork
the symlinked single source of truth in ``docs/tutorials/``.

Behavior under ``sphinx-build -W``:

* a manifest entry that no longer matches the doctree (cells moved, a
  widget output added/removed) fails the build with a warning that says
  to re-run ``pixi run capture-widgets`` -- snapshots cannot silently go
  stale;
* widget outputs *without* a manifest entry (a freshly
  added cell before re-capture) are untouched and fall back to the
  ``text/plain`` placeholder via the ``nb_mime_priority_overrides`` line
  in ``conf.py``.

HTML-format builders only (the raw ``<img>`` + the flat ``html`` builder
page layout are assumed); other builders keep the text placeholder.  The
manifest is registered as a config value hashed at setup time, so editing
it triggers an environment rebuild on the next build.
"""

from __future__ import annotations

import html
import json
import posixpath
from pathlib import Path
from typing import Any

from docutils import nodes
from sphinx.application import Sphinx
from sphinx.transforms.post_transforms import SphinxPostTransform
from sphinx.util import logging

WIDGET_VIEW_MIMETYPE = "application/vnd.jupyter.widget-view+json"
#: manifest + PNGs, relative to the docs source dir (``html_static_path``
#: copies the whole tree into the built site)
SNAPSHOT_DIR = "_static/widget-snapshots"
CAPTION = "Static snapshot -- run the notebook in JupyterLab (pixi run lab) to interact."

logger = logging.getLogger(__name__)


def _load_manifest(srcdir: Path) -> dict[str, list[dict[str, Any]]]:
    path = srcdir / SNAPSHOT_DIR / "manifest.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["notebooks"]


def _is_widget_bundle(node: nodes.Node) -> bool:
    return (
        isinstance(node, nodes.container)
        and node.get("nb_element") == "mime_bundle"
        and any(
            isinstance(child, nodes.container) and child.get("mime_type") == WIDGET_VIEW_MIMETYPE
            for child in node.children
        )
    )


class WidgetSnapshotTransform(SphinxPostTransform):
    """Replace widget mime bundles with captured ``<img>`` snapshots."""

    default_priority = 3  # must run BEFORE myst-nb's SelectMimeType (4)

    def run(self, **kwargs: Any) -> None:
        if self.app.builder.format != "html":
            return
        stem = self.env.docname.rsplit("/", 1)[-1]
        entries = _load_manifest(Path(self.app.srcdir)).get(stem)
        if not entries:
            return
        by_cell: dict[int, list[dict[str, Any]]] = {}
        for entry in entries:
            by_cell.setdefault(entry["nb_cell_index"], []).append(entry)
        for cell_node in tuple(self.document.findall(nodes.container)):
            if cell_node.get("nb_element") != "cell_code":
                continue
            cell_entries = by_cell.pop(cell_node.get("cell_index"), None)
            if cell_entries is None:
                continue
            bundles = [
                node for node in cell_node.findall(nodes.container) if _is_widget_bundle(node)
            ]
            if len(bundles) != len(cell_entries):
                self._stale(
                    f"cell {cell_node.get('cell_index')} has {len(bundles)} widget "
                    f"output(s) but the manifest records {len(cell_entries)}"
                )
                continue
            for bundle, entry in zip(bundles, cell_entries, strict=True):
                bundle.replace_self(self._snapshot_nodes(entry))
        for cell_index in by_cell:
            self._stale(f"manifest entry for cell {cell_index} matches no code cell")

    def _stale(self, detail: str) -> None:
        logger.warning(
            f"widget snapshots for {self.env.docname} are stale ({detail}); "
            "re-run `pixi run capture-widgets` and commit the refreshed "
            "docs/_static/widget-snapshots/",
            type="widget-snapshots",
            subtype="stale",
            location=self.env.docname,
        )

    def _snapshot_nodes(self, entry: dict[str, Any]) -> nodes.container:
        image = f"{SNAPSHOT_DIR}/{entry['image']}"
        if not (Path(self.app.srcdir) / image).is_file():
            self._stale(f"missing image {image}")
        # the html builder mirrors docnames to pages, so the page-relative
        # path is the srcdir-relative path seen from the docname's dir
        uri = posixpath.relpath(image, posixpath.dirname(self.env.docname))
        alt = html.escape(entry.get("alt", "widget"), quote=True)
        container = nodes.container(classes=["widget-snapshot"])
        container += nodes.raw(
            "",
            f'<img src="{uri}" alt="{alt} (static snapshot of the interactive widget)" '
            'loading="lazy" />',
            format="html",
        )
        container += nodes.paragraph(text=CAPTION, classes=["widget-snapshot-caption"])
        return container


def _manifest_state() -> str:
    """A rebuild fingerprint: the manifest content hash at builder start."""

    import hashlib

    path = Path(__file__).resolve().parents[1] / SNAPSHOT_DIR / "manifest.json"
    if not path.is_file():
        return "absent"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup(app: Sphinx) -> dict[str, Any]:
    # changing the manifest must invalidate cached doctrees ('env' rebuild):
    # the config default is the manifest hash, so a re-capture changes it
    app.add_config_value("widget_snapshots_state", _manifest_state(), "env")
    app.add_post_transform(WidgetSnapshotTransform)
    app.add_css_file("widget-snapshots.css")
    return {"parallel_read_safe": True, "parallel_write_safe": True}
