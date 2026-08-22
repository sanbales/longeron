# API server & client

The [API server & client guide](../guides/api-server.md) covers the
resource model, the git-backed commit semantics, and the `/x/` extension
endpoints end to end.

## `longeron.server`

Requires the `server` extra (`pip install "longeron[server]"`); the
{class}`~longeron.server.GitProjectStore` itself needs only `git` on
`PATH`.

```{eval-rst}
.. automodule:: longeron.server
```

## `longeron.client`

Requires the `client` extra (`pip install "longeron[client]"`).

```{eval-rst}
.. automodule:: longeron.client
```
