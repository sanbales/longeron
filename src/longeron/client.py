"""Typed client for OMG Systems Modeling API servers.

:class:`Client` talks to any server exposing the pilot-implementation REST
resource model (projects -> commits -> paginated elements) -- including
``longeron serve`` (:mod:`longeron.server`) and the OMG pilot servers.  It
ports the good bones of pymbe's ``APIClient`` (Link-header pagination,
project/commit browsing, the POST ``identity``/``payload`` change form)
without the traitlets/ipywidgets machinery::

    from longeron.client import Client

    with Client("http://localhost:9000") as client:
        project = client.list_projects()[0]["@id"]
        model = client.fetch_model(project)            # working tree
        old = client.fetch_model(project, commit=sha)  # any git commit

``fetch_model`` rebuilds a :class:`longeron.model.Model` from the flat API
records via :func:`longeron.api.model_from_api_records` -- the derived
``source``/``target`` endpoint arrays every pilot-style server serializes
make the records navigable, so structure, ownership, typing, and
specialization all come back.  ``push_commit`` sends changes the other way.

Requires the ``client`` extra (httpx): ``pip install 'longeron[client]'``.
Pure Python; works identically on Windows and POSIX.
"""

from __future__ import annotations

from typing import Any, cast

from . import model as M
from .api import model_from_api_records
from .errors import MissingExtraError, SysMLError


class Client:
    """A synchronous Systems Modeling API client.

    ``base_url`` names the server (default the pilot-conventional
    ``http://localhost:9000``).  Pass ``http`` to supply a pre-configured
    ``httpx.Client``-compatible object instead -- e.g. a Starlette
    ``TestClient`` wrapping an app in-process, which is how longeron's own
    test suite exercises client and server together without a network.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:9000",
        *,
        page_size: int = 2000,
        timeout: float = 30.0,
        http: Any = None,
    ):
        if http is None:
            try:
                import httpx
            except ImportError as err:  # pragma: no cover - exercised without extra
                raise MissingExtraError("the API client", "httpx", "client") from err
            http = httpx.Client(base_url=base_url, timeout=timeout, follow_redirects=True)
        self._http = http
        self.page_size = page_size

    # -- lifecycle --------------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- plumbing ---------------------------------------------------------------

    @staticmethod
    def _checked(response: Any) -> Any:
        if response.status_code >= 400:
            detail = ""
            try:
                detail = response.json().get("detail", "")
            except Exception:
                detail = response.text[:200]
            raise SysMLError(
                f"{response.request.method} {response.request.url} -> "
                f"{response.status_code}: {detail}"
            )
        return response.json()

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._checked(self._http.get(path, params=params))

    def _get_records(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", self._get_json(path, params))

    def _paged(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """GET a paginated collection, following ``Link: rel="next"``."""

        results: list[dict[str, Any]] = []
        response = self._http.get(path, params=params)
        while True:
            data = self._checked(response)
            if not isinstance(data, list):
                raise SysMLError(f"expected a collection from {path!r}, got {type(data).__name__}")
            results.extend(data)
            next_link = response.links.get("next")
            if not next_link:
                return results
            response = self._http.get(next_link["url"])

    def _project_id(self, project: str | dict[str, Any]) -> str:
        """Accept a project record, ``@id``, or (pilot-style) name prefix."""

        if isinstance(project, dict):
            return str(project["@id"])
        records = self.list_projects()
        for record in records:
            if record.get("@id") == project:
                return project
        for record in records:
            name = str(record.get("name", ""))
            if name == project or name.startswith(f"{project} "):
                return str(record["@id"])
        raise SysMLError(f"no project {project!r} on this server")

    # -- REST resources -----------------------------------------------------------

    def list_projects(self) -> list[dict[str, Any]]:
        return self._get_records("projects")

    def list_commits(self, project: str | dict[str, Any]) -> list[dict[str, Any]]:
        return self._get_records(f"projects/{self._project_id(project)}/commits")

    def list_elements(
        self, project: str | dict[str, Any], commit: str | None = None
    ) -> list[dict[str, Any]]:
        """All element records at a commit (default: the working tree /
        head), transparently following pagination."""

        project_id = self._project_id(project)
        commit_id = commit or "working"
        return self._paged(
            f"projects/{project_id}/commits/{commit_id}/elements",
            params={"page[size]": self.page_size},
        )

    def element(
        self, project: str | dict[str, Any], element_id: str, commit: str | None = None
    ) -> dict[str, Any]:
        project_id = self._project_id(project)
        commit_id = commit or "working"
        return cast(
            "dict[str, Any]",
            self._get_json(f"projects/{project_id}/commits/{commit_id}/elements/{element_id}"),
        )

    # -- model level ----------------------------------------------------------------

    def fetch_model(self, project: str | dict[str, Any], commit: str | None = None) -> M.Model:
        """Download and rebuild the model at a commit (default: working
        tree).  See :func:`longeron.api.model_from_api_records` for the
        structural fidelity contract."""

        project_id = self._project_id(project)
        commit_id = commit or "working"
        model = model_from_api_records(self.list_elements(project_id, commit_id))
        model.source_name = f"projects/{project_id}/commits/{commit_id}"
        return model

    def push_commit(
        self,
        project: str | dict[str, Any],
        changes: M.Model | list[dict[str, Any]],
        *,
        description: str = "",
    ) -> dict[str, Any]:
        """POST a commit.  ``changes`` is either a list of change entries
        (pilot ``{"identity": {"@id": ...}, "payload": {...}|null}`` form,
        or flat records, which are wrapped) or a whole
        :class:`~longeron.model.Model`, which is projected to API records
        first (that projection needs pyecore: ``longeron[ecore]``).

        Against ``longeron serve``, the server *materializes* the commit by
        rewriting the affected ``.sysml`` files in its working tree -- it
        never runs ``git commit`` (tools must not auto-commit user repos);
        the response's ``written`` field lists the files to review.
        """

        if isinstance(changes, M.Model):
            try:
                from .api import to_api_records
            except Exception as err:  # pragma: no cover - import is cheap
                raise MissingExtraError("pushing a Model", "pyecore", "ecore") from err
            try:
                records = to_api_records(changes)
            except SysMLError:
                raise
            except Exception as err:
                raise SysMLError(
                    "projecting the model to API records failed (is pyecore "
                    f"installed? pip install 'longeron[ecore]'): {err}"
                ) from err
            change = [{"identity": {"@id": r["@id"]}, "payload": r} for r in records]
        else:
            change = [self._as_change(entry) for entry in changes]
        response = self._http.post(
            f"projects/{self._project_id(project)}/commits",
            json={"@type": "Commit", "description": description, "change": change},
        )
        return cast("dict[str, Any]", self._checked(response))

    @staticmethod
    def _as_change(entry: dict[str, Any]) -> dict[str, Any]:
        if "identity" in entry:
            return {"identity": entry["identity"], "payload": entry.get("payload")}
        if "@id" in entry:
            return {"identity": {"@id": entry["@id"]}, "payload": entry}
        raise SysMLError(f"change entry has no identity: {entry!r}")

    # -- longeron extension endpoints (/x/) -------------------------------------------

    def validate(
        self, commit: str | None = None, *, strict_imports: bool = False
    ) -> dict[str, Any]:
        """``POST /x/validate`` (longeron servers only).

        ``strict_imports`` is forwarded to the server, mirroring
        :func:`longeron.validation.validate`: additionally warn for bare
        standard-library names that resolve only through the implicit
        library-visibility hop.
        """

        return cast(
            "dict[str, Any]",
            self._checked(
                self._http.post(
                    "x/validate", json={"commit": commit, "strict_imports": strict_imports}
                )
            ),
        )

    def instantiate(self, qname: str, commit: str | None = None, **bindings: Any) -> dict[str, Any]:
        """``POST /x/instantiate/{qname}`` (longeron servers only)."""

        return cast(
            "dict[str, Any]",
            self._checked(
                self._http.post(
                    f"x/instantiate/{qname}", json={"commit": commit, "bindings": bindings}
                )
            ),
        )

    def simulate(
        self,
        qname: str,
        events: list[Any] | None = None,
        inputs: dict[str, Any] | None = None,
        commit: str | None = None,
    ) -> dict[str, Any]:
        """``POST /x/simulate/{qname}`` (longeron servers only)."""

        return cast(
            "dict[str, Any]",
            self._checked(
                self._http.post(
                    f"x/simulate/{qname}",
                    json={"commit": commit, "events": events or [], "inputs": inputs or {}},
                )
            ),
        )

    def interpret(
        self,
        qname: str,
        strategy: str = "nominal",
        seed: int | None = None,
        commit: str | None = None,
        bindings: dict[str, Any] | None = None,
        selection: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """``POST /x/interpret/{qname}`` (longeron servers only): an M0
        interpretation of the population under ``qname`` -- the JSON shape
        of :meth:`longeron.m0.Interpretation.to_dict`."""

        return cast(
            "dict[str, Any]",
            self._checked(
                self._http.post(
                    f"x/interpret/{qname}",
                    json={
                        "commit": commit,
                        "strategy": strategy,
                        "seed": seed,
                        "bindings": bindings,
                        "selection": selection,
                    },
                )
            ),
        )

    def render_svg(self, qname: str, commit: str | None = None) -> bytes:
        """``GET /x/render/{qname}.svg`` (longeron servers only)."""

        params = {"commit": commit} if commit else None
        response = self._http.get(f"x/render/{qname}.svg", params=params)
        if response.status_code >= 400:
            self._checked(response)
        return cast(bytes, response.content)
