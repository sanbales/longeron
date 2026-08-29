# RDF graph in 3D

Requires the `rdf` extra for the projection and the `viz` extra for the
widget (`pip install "longeron[rdf,viz]"`).

Every payload ships two deterministic embeddings of the same view: the
force layout and a layered hierarchy. The in-scene slider morphs
between them in the browser, with no kernel round trip. The panel
searches qualified names, budgets the billboard labels, and toggles
namespaces and edge families with pills. Select a node and press `f`
to isolate its k-hop neighborhood. The in-scene breadcrumb chip steps
back out. `widget.export_html(path)` writes the current view as a
self-contained page that opens without a kernel.

```{eval-rst}
.. automodule:: longeron.widgets.graph3d
```
