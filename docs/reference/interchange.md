# Interchange

## `longeron.export`

```{eval-rst}
.. automodule:: longeron.export
```

## `longeron.importer`

```{eval-rst}
.. automodule:: longeron.importer
```

## `longeron.kerml`

```{eval-rst}
.. automodule:: longeron.kerml
```

## `longeron.ecore`

Requires the `ecore` extra (`pip install "longeron[ecore]"`).

```{eval-rst}
.. automodule:: longeron.ecore
```

## `longeron.api`

Requires the `ecore` extra (`pip install "longeron[ecore]"`).

Relationship records carry the derived `source`/`target` endpoint arrays by
default (`to_api_records(..., derived=True)`): the OMG pilot-implementation
API servers serialize these derived properties, and pilot-ecosystem
consumers (pymbe, for one) use their presence to recognize relationship
records and navigate the model graph — an export without them loads but is
unnavigable. Pass `derived=False` (CLI: `longeron export --format api
--no-derived`) for minimal records restricted to stored features; round
trips are lossless either way.

```{eval-rst}
.. automodule:: longeron.api
```

## `longeron.rdf`

Requires the `rdf` extra (`pip install "longeron[rdf]"`).

```{eval-rst}
.. automodule:: longeron.rdf
```

## `longeron.rag`

No extra required — the retrieval substrate is stdlib only.

```{eval-rst}
.. automodule:: longeron.rag
```
