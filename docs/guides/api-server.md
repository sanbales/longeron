# API server & client

`longeron serve` exposes any workspace as an [OMG Systems Modeling API &
Services](https://www.omg.org/spec/SystemsModelingAPI/) server, and
`longeron.client.Client` consumes any server speaking that resource model
(longeron's own, or the OMG pilot implementation). Together they close the
interchange loop: fetch a model from a server at any point in its history,
work with it as a regular longeron `Model`, and push changes back.

```bash
pip install "longeron[server]"   # fastapi, uvicorn, pyecore
longeron serve path/to/models --port 9000
```

```python
from longeron.client import Client  # pip install "longeron[client]"

client = Client("http://localhost:9000")
project = client.list_projects()[0]
commits = client.list_commits(project)  # oldest -> newest, then "working"
model = client.fetch_model(project)  # the working tree, as a Model
old = client.fetch_model(project, commit=commits[0]["@id"])
```

## Resource model

| Endpoint | Returns |
|---|---|
| `GET /projects` | the served workspace as a single project |
| `GET /projects/{id}` | one project record |
| `GET /projects/{id}/commits` | commit records, oldest first, ending with `working` |
| `POST /projects/{id}/commits` | materialize change records into the working tree |
| `GET /projects/{id}/commits/{id}` | one commit record |
| `GET .../commits/{id}/elements` | flat API-JSON records (paged via `page[size]` / `Link: rel="next"`) |
| `GET .../commits/{id}/elements/{elementId}` | one element record |
| `GET .../commits/{id}/roots` | the root namespace element(s) |

Element records are the same [API JSON](../reference/interchange.md) that
`longeron export --format api` produces, including the derived
`source`/`target` endpoint arrays that pilot-ecosystem consumers (pymbe)
use to recognize and navigate relationships. Pagination follows the pilot
convention (`?page[size]=N`, a `Link` header carrying the `next` URL), so
existing pilot clients paginate unchanged.

## Git-backed commits, honestly

The server does not invent a commit store — the workspace's git repository
*is* the store:

- **project** — the served directory (or single `.sysml` file). The
  project `@id` is a deterministic UUID of its path; the name carries a
  pilot-style timestamp suffix that pilot clients parse.
- **commit** — a git commit that touched the served `.sysml` sources
  (`git log`, oldest first; `@id` is the full git SHA, and any
  rev-parseable ref works in URLs). `previousCommit` chains within this
  filtered history.
- **elements at a commit** — the model parsed from `git show <sha>:<path>`
  blobs at that ref, through the same content-addressed cache the loader
  uses, so revisiting historic refs is fast after the first parse.
- **`working`** — the uncommitted working tree, always the last commit in
  the list. This is the head everything defaults to.

`POST /projects/{id}/commits` accepts pilot-style change records
(`{"identity": {"@id": ...}, "payload": {...} | null}`; the pymbe
write-side format) and **materializes** them: new elements are imported
into the working-tree model and attached where their membership records
say, updates patch names/flags, `null` payloads delete, and only the
`.sysml` files owning affected top-level elements are rewritten (formats
are normalized by the exporter; untouched files are never rewritten). The
response's `written` field lists the files.

The server deliberately **never runs `git commit`**: agents and tools must
not auto-commit user repositories. Review the diff and commit yourself —
that human checkpoint is the point of mapping the API onto git. Renames
pushed through the API do not rewrite textual references elsewhere in the
model; `POST /x/validate` afterwards will flag any reference you broke.

Fidelity contract: API records carry structure — kinds, names, flags,
ownership, typing, specialization — but not expression trees, so pushed
*new* content cannot carry attribute values. Updates and deletes patch the
parsed working-tree model in place, so everything already in your files
(values, calc bodies) survives a push that touches the same file.

## Extension endpoints (`/x/`)

No pilot server executes models; these are **longeron extensions**, thin
wrappers over the validator, interpreter, and renderer, namespaced under
`/x/` so the spec surface above stays exactly what pilot clients expect:

| Endpoint | Wraps | Body (JSON, all fields optional) |
|---|---|---|
| `POST /x/validate` | `longeron.validate()` | `{"commit", "strict_imports"}` |
| `POST /x/instantiate/{qname}` | `Interpreter.instantiate()` + constraint checks | `{"commit", "bindings"}` |
| `POST /x/simulate/{qname}` | `Interpreter.simulate()` | `{"commit", "events", "inputs"}` |
| `GET /x/render/{qname}.svg?commit=` | `longeron.render.to_svg()` | — |

`Client` mirrors them as `validate()`, `instantiate()`, `simulate()`, and
`render_svg()`. Rendering additionally needs the diagram stack (ipyelk +
node); a server without it answers `501`.

## Security

Local-first by design: no authentication, no TLS, and the default bind is
`127.0.0.1`. Anyone who can reach the port can read the models and write
to the working tree. Do not expose the server beyond a trusted network;
put it behind an authenticating reverse proxy if you must share it.

## Platform notes

Server and client are pure Python — FastAPI, uvicorn, and httpx are all
Windows-clean, and file I/O is explicit UTF-8 throughout. The one external
requirement is `git` on `PATH`; without it the workspace still serves,
with `working` as the only commit. Git tree paths in refspecs are composed
with forward slashes on every OS.

## Interoperability

The server was cross-checked against pymbe (the pilot-ecosystem Python
client): its `APIClient` lists the project, selects commits, and downloads
elements into a navigable pymbe `Model` unchanged. The reverse direction —
`Client` against a pilot server — uses only spec resources plus the
pilot's pagination convention.
