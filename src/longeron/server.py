"""Serve a workspace as an OMG Systems Modeling API server (git-backed).

``longeron serve [path]`` (or :func:`serve` / :func:`create_app`) exposes a
directory of ``.sysml`` files -- or a single file -- over the REST resource
model of the OMG *Systems Modeling API & Services* specification, the same
surface the pilot-implementation servers offer and clients like pymbe (and
:mod:`longeron.client`) consume::

    GET  /projects
    GET  /projects/{projectId}
    GET  /projects/{projectId}/commits
    POST /projects/{projectId}/commits
    GET  /projects/{projectId}/commits/{commitId}
    GET  /projects/{projectId}/commits/{commitId}/elements      (paged)
    GET  /projects/{projectId}/commits/{commitId}/elements/{elementId}
    GET  /projects/{projectId}/commits/{commitId}/roots

Storage is git-backed and honest: the served path *is* the project, and an
API commit *is* a git commit that touched the ``.sysml`` sources beneath it
(listed via ``git log``).  Elements at a historic commit are parsed from
``git show <sha>:<path>`` blobs through the content-addressed model cache
(:mod:`longeron.workspace`), so revisiting a ref is as fast as a warm load.
The uncommitted working tree is always exposed as the head pseudo-commit
``working``.  Everything is read-only except ``POST .../commits``, which
accepts pilot-style ``identity``/``payload`` change records and
*materializes* them: the changes are imported onto the working-tree model
and the affected files are rewritten as ``.sysml`` text.  The server never
runs ``git commit`` -- agents and tools must not auto-commit user
repositories; review the diff and commit yourself, which is exactly the
point of the git mapping.

Endpoints under ``/x/`` are **longeron extensions** (no pilot server has
them): ``POST /x/validate``, ``POST /x/instantiate/{qname}``,
``POST /x/simulate/{qname}``, ``POST /x/interpret/{qname}``, and
``GET /x/render/{qname}.svg`` wrap the
validator, interpreter, and headless renderer.

Security: this is a local-first development server -- no authentication, no
TLS -- and it binds to ``127.0.0.1`` by default.  Do not expose it beyond a
trusted network.  Requires the ``server`` extra (FastAPI, uvicorn, pyecore);
the one external tool is ``git`` on ``PATH`` (without it the workspace is
still served, as a single ``working`` commit).
"""

# NOTE: no `from __future__ import annotations` here -- FastAPI resolves
# handler annotations at runtime, and `Request`/`Response` are imported
# lazily inside create_app (so the module works without the extra); with
# postponed annotations those names would not be resolvable.

import hashlib
import json
import re
import subprocess
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Any

from . import model as M
from .builder import build_model
from .ecore import _UUID_NAMESPACE
from .errors import MissingExtraError, ResolutionError, SysMLError
from .parser import parse_sysml_text
from .workspace import _cache_load, _cache_path, _cache_store, load, load_file, merge_models

#: the pseudo-commit id under which the uncommitted working tree is served
WORKING_COMMIT_ID = "working"

#: how many immutable refs keep their merged models/records memoized (FIFO
#: eviction; a long-lived server browsing history must not grow unboundedly)
_MEMO_REFS = 8


def _memoize(memo: dict[str, Any], key: str, value: Any) -> None:
    """Bounded insertion: dicts iterate in insertion order, so dropping the
    first key evicts the oldest entry once ``_MEMO_REFS`` is exceeded."""

    memo[key] = value
    while len(memo) > _MEMO_REFS:
        del memo[next(iter(memo))]


def _refspec(sha: str, relpath: PurePath | str) -> str:
    """``<sha>:<path>`` for ``git show``; tree paths always use forward
    slashes, on every OS (git refuses backslash tree paths on Windows)."""

    return f"{sha}:{PurePath(relpath).as_posix()}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pilot_timestamp(iso: str) -> str:
    """``Mon Jan 05 12:00:00 UTC 2026`` -- the pilot servers suffix project
    names with such a stamp and pymbe parses it back out."""

    # py3.10 fromisoformat rejects a trailing Z (git %cI emits it for UTC)
    moment = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    return moment.strftime("%a %b %d %H:%M:%S UTC %Y")


class GitProjectStore:
    """One served workspace: project/commit/element views over a git repo.

    Usable on its own (no FastAPI needed) -- :func:`create_app` wraps it in
    HTTP routes.  All git access is read-only (``rev-parse``, ``log``,
    ``ls-tree``, ``show``); :meth:`apply_commit` writes ``.sysml`` files to
    the working tree but never touches the git index or history.
    """

    def __init__(self, path: str | Path = "."):
        self.path = Path(path).resolve()
        if not self.path.exists():
            raise SysMLError(f"nothing to serve: {self.path} does not exist")
        base = self.path if self.path.is_dir() else self.path.parent
        self.repo_root = self._git_root(base)
        if self.repo_root is not None and self.path != self.repo_root:
            self.subpath: PurePath | None = PurePath(self.path.relative_to(self.repo_root))
        else:
            self.subpath = None
        self.project_id = str(uuid.uuid5(_UUID_NAMESPACE, f"$project/{self.path.as_posix()}"))
        self._records_memo: dict[str, list[dict[str, Any]]] = {}
        self._models_memo: dict[str, M.Model] = {}
        # working-tree memo, valid while the stat fingerprint matches
        self._working_key: str | None = None
        self._working_model: M.Model | None = None
        self._working_records: list[dict[str, Any]] | None = None

    # -- git plumbing (read-only) ---------------------------------------------

    def _run_git(self, *args: str, check: bool = True) -> str | None:
        if self.repo_root is None:
            return None
        result = subprocess.run(  # explicit arg list; never shell=True
            ["git", "-C", str(self.repo_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            if check:
                raise SysMLError(f"git {args[0]} failed: {result.stderr.strip()}")
            return None
        return result.stdout

    @staticmethod
    def _git_root(base: Path) -> Path | None:
        result = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            return None
        return Path(result.stdout.strip()).resolve()

    def _pathspecs(self) -> list[str]:
        """Limit git history to the ``.sysml`` sources this store serves."""

        if self.subpath is not None and not self.path.is_dir():
            return [self.subpath.as_posix()]
        prefix = f"{self.subpath.as_posix()}/" if self.subpath is not None else ""
        return [f":(glob){prefix}**/*.sysml", f":(glob){prefix}*.sysml"]

    # -- resource model: project & commits --------------------------------------

    def project_record(self) -> dict[str, Any]:
        commits = self.git_commits()
        created = commits[0]["created"] if commits else _now_iso()
        stamped = commits[-1]["created"] if commits else created
        return {
            "@id": self.project_id,
            "@type": "Project",
            # pilot-style name: workspace name + timestamp suffix (pymbe
            # splits the last six tokens back off as the creation date)
            "name": f"{self.path.stem} {_pilot_timestamp(stamped)}",
            "created": created,
            "description": f"git-backed workspace at {self.path}",
        }

    def git_commits(self) -> list[dict[str, Any]]:
        """API commit records for the git commits that touched the served
        ``.sysml`` sources, oldest first.  ``previousCommit`` chains within
        this filtered list (the project's history, not the whole repo's)."""

        out = self._run_git(
            "log", "--reverse", "--format=%H%x1f%cI%x1f%s", "--", *self._pathspecs(), check=False
        )
        commits: list[dict[str, Any]] = []
        previous: str | None = None
        for line in (out or "").splitlines():
            sha, created, subject = line.split("\x1f", 2)
            commits.append(
                {
                    "@id": sha,
                    "@type": "Commit",
                    "created": created,
                    "description": subject,
                    "owningProject": {"@id": self.project_id},
                    "previousCommit": {"@id": previous} if previous else None,
                }
            )
            previous = sha
        return commits

    def commits(self) -> list[dict[str, Any]]:
        """All commits, ending with the ``working`` pseudo-commit for the
        uncommitted working tree (equal to head content when clean)."""

        commits = self.git_commits()
        commits.append(
            {
                "@id": WORKING_COMMIT_ID,
                "@type": "Commit",
                "created": _now_iso(),
                "description": "uncommitted working tree",
                "owningProject": {"@id": self.project_id},
                "previousCommit": {"@id": commits[-1]["@id"]} if commits else None,
            }
        )
        return commits

    def resolve_commit(self, commit_id: str) -> str:
        """Normalize a commit id (``working``, a full sha, or any git rev
        the repo can resolve) or raise :class:`SysMLError`."""

        if commit_id == WORKING_COMMIT_ID:
            return WORKING_COMMIT_ID
        out = self._run_git(
            "rev-parse", "--verify", "--quiet", f"{commit_id}^{{commit}}", check=False
        )
        if out is None or not out.strip():
            raise SysMLError(f"unknown commit {commit_id!r}")
        return out.strip()

    # -- resource model: elements ------------------------------------------------

    def _model_for_text(self, text: str, name: str) -> M.Model:
        """Parse one historic blob through the content-addressed cache."""

        entry = _cache_path(text)
        cached = _cache_load(entry)
        if cached is not None:
            cached.source_name = name
            return cached
        model = build_model(parse_sysml_text(text, name))
        _cache_store(entry, model)
        return model

    def _tree_files(self, sha: str) -> list[PurePath]:
        scope = self.subpath.as_posix() if self.subpath is not None else "."
        out = self._run_git("ls-tree", "-r", "--name-only", "-z", sha, "--", scope) or ""
        files = [PurePath(p) for p in out.split("\0") if p.endswith(".sysml")]
        return sorted(files, key=lambda p: p.as_posix())

    def _working_fingerprint(self) -> str:
        """A cheap fingerprint of the served working-tree sources: paths,
        sizes, and mtimes (content is never read).  Any save, add, or
        delete changes the key, invalidating the working-tree memo."""

        digest = hashlib.sha256()
        for source in self._working_files():
            try:
                stat = source.stat()
            except OSError:  # racing deletion; treat as absent
                continue
            digest.update(
                f"{source.as_posix()}\x00{stat.st_size}\x00{stat.st_mtime_ns}\x00".encode()
            )
        return digest.hexdigest()

    def model_at(self, commit_id: str) -> M.Model:
        """The merged model at a commit; historic refs are parsed from
        ``git show`` blobs and memoized (refs are immutable), the working
        tree is loaded through :func:`longeron.load` and memoized behind a
        stat fingerprint of the served files (edits invalidate)."""

        ref = self.resolve_commit(commit_id)
        if ref == WORKING_COMMIT_ID:
            key = self._working_fingerprint()
            if key != self._working_key or self._working_model is None:
                self._working_model = load(self.path)
                self._working_records = None
                self._working_key = key
            return self._working_model
        if ref in self._models_memo:
            return self._models_memo[ref]
        files = self._tree_files(ref)
        if not files:
            raise SysMLError(f"no .sysml files under {self.path.name} at {ref[:12]}")
        models = []
        for relpath in files:
            text = self._run_git("show", _refspec(ref, relpath))
            models.append(self._model_for_text(text or "", f"{ref[:12]}:{relpath.as_posix()}"))
        merged = merge_models(models, source_name=f"{self.path}@{ref[:12]}")
        _memoize(self._models_memo, ref, merged)
        return merged

    def records_at(self, commit_id: str) -> list[dict[str, Any]]:
        """Flat API records at a commit (memoized: per immutable ref, and
        for the working tree until its stat fingerprint changes -- so a
        paginated listing projects the model once, not once per page)."""

        from .api import to_api_records  # needs pyecore (the server extra)

        ref = self.resolve_commit(commit_id)
        if ref == WORKING_COMMIT_ID:
            model = self.model_at(ref)  # validates/refreshes the memo
            if self._working_records is None:
                self._working_records = to_api_records(model)
            return self._working_records
        if ref in self._records_memo:
            return self._records_memo[ref]
        records = to_api_records(self.model_at(ref))
        _memoize(self._records_memo, ref, records)
        return records

    # -- write side: materializing POSTed commits ---------------------------------

    def _working_files(self) -> list[Path]:
        if self.path.is_file():
            return [self.path]
        return sorted(self.path.glob("**/*.sysml"))

    def _new_file_for(self, element: M.Element) -> Path:
        if self.path.is_file():
            return self.path
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", element.name or "model").strip("_") or "model"
        candidate = self.path / f"{slug}.sysml"
        counter = 1
        while candidate.exists():
            counter += 1
            candidate = self.path / f"{slug}_{counter}.sysml"
        return candidate

    def apply_commit(self, body: Any) -> dict[str, Any]:
        """Materialize a POSTed commit into the working tree.

        The body is a pilot-style commit (``{"change": [{"identity":
        {"@id": ...}, "payload": {...}|null}, ...]}``) or a bare list of
        such entries / flat records.  Semantics per change entry, against
        the element ids of the *working-tree* model:

        * unknown id + payload -- **add**: the new element records (with
          their membership records naming an owner, and any typing /
          specialization relationship records) are imported and attached;
        * known element id + payload -- **update**: name, short name, flag,
          and body fields are patched onto the element;
        * known relationship-record id + payload -- **retarget**: the
          owner's typing/specialization entry is rewritten;
        * payload ``null`` -- **delete** the element (or relationship).

        Only the ``.sysml`` files owning affected top-level elements are
        rewritten (regenerated with :func:`longeron.to_sysml`, which
        normalizes formatting); untouched files are never rewritten.  The
        result is left *uncommitted* on purpose: tools must not auto-commit
        user repositories, so review ``git diff`` and commit yourself.
        """

        from .api import (
            _RELATIONSHIP_ROLES,
            _all_ids,
            _apply_membership_kind,
            _element_from_api_record,
            _first_id,
            to_api_records,
        )
        from .ecore import to_spec
        from .export import to_sysml

        changes, description = _normalize_changes(body)
        if not changes:
            raise SysMLError("commit body carries no change records")

        # snapshot the working tree with per-file attribution
        combined = M.Model(source_name=str(self.path))
        file_of: dict[int, Path] = {}
        for source in self._working_files():
            file_model = load_file(source, cache=True)
            for member in list(file_model.members):
                combined.add(member)
                file_of[id(member)] = source
        spec = to_spec(combined)
        by_element_id: dict[str, M.Element] = {}
        for element in combined.iter_tree():
            instance = (spec.instances or {}).get(id(element))
            if instance is not None:
                by_element_id[instance.elementId] = element
        head_records = {record["@id"]: record for record in to_api_records(spec)}

        affected: set[Path] = set()

        def file_for(element: M.Element) -> Path:
            node = element
            while node.owner is not None and node.owner is not combined:
                node = node.owner
            source = file_of.get(id(node))
            if source is None:
                source = self._new_file_for(node)
                file_of[id(node)] = source
            return source

        def remove_reference(names: list[str], target: M.Element) -> bool:
            keep = [
                entry
                for entry in names
                if entry != _api_reference_name(target)
                and entry.split("::")[-1] != (target.name or target.short_name)
            ]
            if len(keep) == len(names):
                return False
            names[:] = keep
            return True

        new_payloads = {
            change_id: payload
            for change_id, payload in changes
            if payload is not None and change_id not in head_records
        }
        new_elements: dict[str, M.Element] = {}
        for change_id, new_payload in new_payloads.items():
            candidate = _element_from_api_record({**new_payload, "@id": change_id})
            if candidate is not None:
                new_elements[change_id] = candidate

        def resolve(element_id: str | None) -> M.Element | None:
            if element_id is None:
                return None
            return by_element_id.get(element_id) or new_elements.get(element_id)

        # deletes
        for change_id, payload in changes:
            if payload is not None:
                continue
            existing = by_element_id.get(change_id)
            if existing is not None:
                owner = existing.owner
                if not isinstance(owner, M.Namespace):
                    raise SysMLError(f"cannot delete unowned element {change_id}")
                affected.add(file_for(existing))
                owner.members.remove(existing)
                continue
            rel = head_records.get(change_id)
            roles = _RELATIONSHIP_ROLES.get(str(rel.get("@type", ""))) if rel else None
            if rel is None or roles is None:
                raise SysMLError(
                    f"cannot delete {change_id}: not an element or "
                    "typing/specialization record of the working tree"
                )
            source_role, target_role, attribute = roles
            owner_el = by_element_id.get(_first_id(rel, source_role, "source") or "")
            target_el = by_element_id.get(_first_id(rel, target_role, "target") or "")
            names = getattr(owner_el, attribute, None) if owner_el is not None else None
            if owner_el is None or target_el is None or not isinstance(names, list):
                raise SysMLError(f"cannot delete {change_id}: endpoints not found")
            if remove_reference(names, target_el):
                affected.add(file_for(owner_el))

        # updates (existing element or relationship records)
        for change_id, payload in changes:
            if payload is None or change_id in new_payloads:
                continue
            existing = by_element_id.get(change_id)
            if existing is not None:
                if _patch_element(existing, payload):
                    affected.add(file_for(existing))
                continue
            record = head_records[change_id]
            roles = _RELATIONSHIP_ROLES.get(str(record.get("@type", "")))
            if roles is None:
                continue  # membership records need no independent update
            source_role, target_role, attribute = roles
            old_target = by_element_id.get(_first_id(record, target_role, "target") or "")
            new_target = resolve(_first_id(payload, target_role, "target"))
            owner_el = by_element_id.get(_first_id(record, source_role, "source") or "")
            names = getattr(owner_el, attribute, None) if owner_el is not None else None
            if owner_el is None or new_target is None or not isinstance(names, list):
                raise SysMLError(f"cannot retarget {change_id}: endpoints not found")
            if new_target is old_target:
                continue
            if old_target is not None:
                remove_reference(names, old_target)
            name = _api_reference_name(new_target)
            if name and name not in names:
                names.append(name)
            affected.add(file_for(owner_el))

        # adds: attach new elements through their membership records
        attached: set[str] = set()
        for payload in new_payloads.values():
            if not str(payload.get("@type", "")).endswith("Membership"):
                continue
            parent = resolve(
                _first_id(payload, "owningRelatedElement", "membershipOwningNamespace", "source")
            )
            for child_id in _all_ids(payload, "ownedRelatedElement", "target"):
                child = new_elements.get(child_id)
                if child is None:
                    continue
                if parent is None:
                    combined.add(child)
                    file_of[id(child)] = self._new_file_for(child)
                elif isinstance(parent, M.Namespace):
                    parent.add(child)
                else:
                    raise SysMLError(f"cannot own {child_id} under a non-namespace")
                _apply_membership_kind(payload, child)
                attached.add(child_id)
                affected.add(file_for(child))
        for new_id, new_element in new_elements.items():  # membership-less adds
            if new_id not in attached and new_element.owner is None:
                combined.add(new_element)
                file_of[id(new_element)] = self._new_file_for(new_element)
                affected.add(file_for(new_element))
        # new typing/specialization records
        for change_id, payload in new_payloads.items():
            roles = _RELATIONSHIP_ROLES.get(str(payload.get("@type", "")))
            if roles is None or payload.get("isImplied"):
                continue
            source_role, target_role, attribute = roles
            src_el = resolve(_first_id(payload, source_role, "source"))
            tgt_el = resolve(_first_id(payload, target_role, "target"))
            names = getattr(src_el, attribute, None) if src_el is not None else None
            if src_el is None or tgt_el is None or not isinstance(names, list):
                raise SysMLError(f"cannot apply {change_id}: endpoints not found")
            name = _api_reference_name(tgt_el)
            if name and name not in names:
                names.append(name)
                affected.add(file_for(src_el))

        # rewrite exactly the affected files
        written: list[str] = []
        for target_file in sorted(affected):
            members = [m for m in combined.members if file_of.get(id(m)) == target_file]
            text = "\n".join(to_sysml(member).rstrip("\n") for member in members)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(text + "\n" if text else "", encoding="utf-8")
            base = self.path if self.path.is_dir() else self.path.parent
            written.append(target_file.relative_to(base).as_posix())
        self._working_key = None  # the writes invalidate the working-tree memo
        git_commits = self.git_commits()
        return {
            "@id": WORKING_COMMIT_ID,
            "@type": "Commit",
            "created": _now_iso(),
            "description": description or "materialized API commit (uncommitted)",
            "owningProject": {"@id": self.project_id},
            "previousCommit": {"@id": git_commits[-1]["@id"]} if git_commits else None,
            "written": written,
        }


def _api_reference_name(target: M.Element) -> str | None:
    from .api import _reference_name

    return _reference_name(target)


#: API record field -> model dataclass field patched by commit updates
_PATCHABLE_FIELDS = {
    "declaredName": "name",
    "declaredShortName": "short_name",
    "body": "body",
    "language": "language",
    "isStandard": "is_standard",
    "isAbstract": "is_abstract",
    "isVariation": "is_variation",
    "isIndividual": "is_individual",
    "isParallel": "is_parallel",
    "isEnd": "is_end",
    "isDerived": "is_derived",
    "isReadOnly": "is_readonly",
}


def _patch_element(element: M.Element, payload: dict[str, Any]) -> bool:
    changed = False
    for record_field, model_field in _PATCHABLE_FIELDS.items():
        if record_field not in payload or not hasattr(element, model_field):
            continue
        value = payload[record_field]
        if getattr(element, model_field) != value:
            setattr(element, model_field, value)
            changed = True
    return changed


def _normalize_changes(body: Any) -> tuple[list[tuple[str, dict[str, Any] | None]], str]:
    """``(changes, description)`` from a POSTed commit body.  Each change is
    ``(element id, payload record | None)``; ``None`` payload = delete."""

    description = ""
    entries = body
    if isinstance(body, dict):
        description = str(body.get("description") or "")
        entries = body.get("change", [])
    if not isinstance(entries, list):
        raise SysMLError("commit body must be a change list or carry a 'change' list")
    changes: list[tuple[str, dict[str, Any] | None]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise SysMLError(f"malformed change entry: {entry!r}")
        identity = entry.get("identity")
        if isinstance(identity, dict) and "@id" in identity:
            changes.append((identity["@id"], entry.get("payload")))
        elif "@id" in entry:  # flat record form
            changes.append((entry["@id"], entry))
        else:
            raise SysMLError(f"change entry has no identity: {entry!r}")
    return changes, description


# ---------------------------------------------------------------------------
# HTTP layer (FastAPI; imported lazily so the store works without the extra)
# ---------------------------------------------------------------------------


def create_app(path: str | Path = ".") -> Any:
    """A FastAPI app serving ``path`` (requires ``longeron[server]``)."""

    try:
        from fastapi import FastAPI, HTTPException, Query, Request, Response
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise MissingExtraError("the API server", "fastapi", "server") from err

    from . import __version__

    store = GitProjectStore(path)
    app = FastAPI(
        title="longeron Systems Modeling API server",
        version=__version__,
        description=__doc__ or "",
    )
    app.state.store = store

    def check_project(project_id: str) -> None:
        if project_id != store.project_id:
            raise HTTPException(404, f"no project {project_id!r} on this server")

    def records_or_404(commit_id: str) -> list[dict[str, Any]]:
        try:
            return store.records_at(commit_id)
        except SysMLError as err:
            raise HTTPException(404, str(err)) from err

    def model_or_404(commit_id: str) -> M.Model:
        try:
            return store.model_at(commit_id)
        except SysMLError as err:
            raise HTTPException(404, str(err)) from err

    @app.get("/")
    def index() -> dict[str, Any]:
        return {
            "server": "longeron",
            "version": __version__,
            "projects": "/projects",
            "extensions": [
                "/x/validate",
                "/x/instantiate/{qname}",
                "/x/simulate/{qname}",
                "/x/interpret/{qname}",
                "/x/render/{qname}.svg",
            ],
        }

    @app.get("/projects")
    def projects() -> list[dict[str, Any]]:
        return [store.project_record()]

    @app.get("/projects/{project_id}")
    def project(project_id: str) -> dict[str, Any]:
        check_project(project_id)
        return store.project_record()

    @app.get("/projects/{project_id}/commits")
    def commits(project_id: str) -> list[dict[str, Any]]:
        check_project(project_id)
        return store.commits()

    @app.post("/projects/{project_id}/commits", status_code=201)
    async def post_commit(project_id: str, request: Request) -> dict[str, Any]:
        check_project(project_id)
        try:
            return store.apply_commit(await request.json())
        except SysMLError as err:
            raise HTTPException(400, str(err)) from err

    @app.get("/projects/{project_id}/commits/{commit_id}")
    def commit(project_id: str, commit_id: str) -> dict[str, Any]:
        check_project(project_id)
        try:
            ref = store.resolve_commit(commit_id)
        except SysMLError as err:
            raise HTTPException(404, str(err)) from err
        for record in store.commits():
            if record["@id"] == ref:
                return record
        raise HTTPException(404, f"commit {commit_id!r} does not touch this project")

    @app.get("/projects/{project_id}/commits/{commit_id}/elements")
    def elements(
        project_id: str,
        commit_id: str,
        request: Request,
        response: Response,
        page_size: int | None = Query(None, alias="page[size]", ge=1),
        page_after: str | None = Query(None, alias="page[after]"),
    ) -> list[dict[str, Any]]:
        check_project(project_id)
        records = records_or_404(commit_id)
        if page_size is None:
            return records
        start = 0
        if page_after is not None:
            ids = [record["@id"] for record in records]
            if page_after not in ids:
                raise HTTPException(404, f"unknown page cursor {page_after!r}")
            start = ids.index(page_after) + 1
        page = records[start : start + page_size]
        if start + page_size < len(records) and page:
            next_url = request.url.include_query_params(
                **{"page[size]": page_size, "page[after]": page[-1]["@id"]}
            )
            response.headers["Link"] = f'<{next_url}>; rel="next"'
        return page

    @app.get("/projects/{project_id}/commits/{commit_id}/elements/{element_id}")
    def element(project_id: str, commit_id: str, element_id: str) -> dict[str, Any]:
        check_project(project_id)
        for record in records_or_404(commit_id):
            if record["@id"] == element_id:
                return record
        raise HTTPException(404, f"no element {element_id!r} at commit {commit_id!r}")

    @app.get("/projects/{project_id}/commits/{commit_id}/roots")
    def roots(project_id: str, commit_id: str) -> list[dict[str, Any]]:
        check_project(project_id)
        records = records_or_404(commit_id)
        owned = {
            ref["@id"]
            for record in records
            if str(record.get("@type", "")).endswith("Membership")
            for ref in record.get("ownedRelatedElement") or []
        }
        return [
            record
            for record in records
            if record["@id"] not in owned
            and not str(record.get("@type", "")).endswith("Membership")
            and not ("source" in record or "target" in record)  # relationships
        ]

    # -- longeron extensions (/x/): no pilot server has these ---------------------

    async def read_body(request: Request) -> dict[str, Any]:
        raw = await request.body()
        if not raw:
            return {}
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as err:
            raise HTTPException(400, f"invalid JSON body: {err}") from err
        if not isinstance(body, dict):
            raise HTTPException(400, "body must be a JSON object")
        return body

    def resolve_qname(model: M.Model, qname: str) -> M.Element:
        from .interpreter import Resolver

        try:
            return Resolver(model).resolve(qname)
        except ResolutionError as err:
            raise HTTPException(404, str(err)) from err

    @app.post("/x/validate")
    async def x_validate(request: Request) -> dict[str, Any]:
        from .validation import validate

        body = await read_body(request)
        commit_id = str(body.get("commit") or WORKING_COMMIT_ID)
        model = model_or_404(commit_id)
        diagnostics = validate(model, strict_imports=bool(body.get("strict_imports")))
        return {
            "commit": commit_id,
            "errors": sum(d.severity == "error" for d in diagnostics),
            "warnings": sum(d.severity == "warning" for d in diagnostics),
            "diagnostics": [asdict(d) for d in diagnostics],
        }

    @app.post("/x/instantiate/{qname}")
    async def x_instantiate(qname: str, request: Request) -> dict[str, Any]:
        from .interpreter import Interpreter

        body = await read_body(request)
        model = model_or_404(str(body.get("commit") or WORKING_COMMIT_ID))
        interpreter = Interpreter(model)
        resolve_qname(model, qname)  # 404 before evaluation errors
        bindings = body.get("bindings") or {}
        if not isinstance(bindings, dict):
            raise HTTPException(400, "'bindings' must be an object")
        try:
            instance = interpreter.instantiate(qname, **bindings)
            checks = interpreter.check(instance)
        except SysMLError as err:
            raise HTTPException(400, str(err)) from err
        return {"instance": instance.to_dict(), "checks": [asdict(c) for c in checks]}

    @app.post("/x/simulate/{qname}")
    async def x_simulate(qname: str, request: Request) -> dict[str, Any]:
        from .interpreter import Interpreter

        body = await read_body(request)
        model = model_or_404(str(body.get("commit") or WORKING_COMMIT_ID))
        resolve_qname(model, qname)
        try:
            result = Interpreter(model).simulate(
                qname,
                events=body.get("events") or [],
                inputs=body.get("inputs") or {},
            )
        except SysMLError as err:
            raise HTTPException(400, str(err)) from err
        return {
            "final_state": result.final_state,
            "active_states": result.active_states,
            "trace": [str(step) for step in result.trace],
            "ignored_events": result.ignored_events,
            "time": result.time,
        }

    @app.post("/x/interpret/{qname}")
    async def x_interpret(qname: str, request: Request) -> dict[str, Any]:
        from .m0 import interpret

        body = await read_body(request)
        model = model_or_404(str(body.get("commit") or WORKING_COMMIT_ID))
        resolve_qname(model, qname)
        for key in ("bindings", "selection"):
            if body.get(key) is not None and not isinstance(body[key], dict):
                raise HTTPException(400, f"{key!r} must be an object")
        seed = body.get("seed")
        if seed is not None and not isinstance(seed, int):
            raise HTTPException(400, "'seed' must be an integer")
        strategy = body.get("strategy") or "nominal"
        if not isinstance(strategy, str):
            raise HTTPException(400, "'strategy' must be a string")
        try:
            interpretation = interpret(
                model,
                qname,
                strategy=strategy,
                seed=seed,
                bindings=body.get("bindings"),
                selection=body.get("selection"),
            )
        except SysMLError as err:
            raise HTTPException(400, str(err)) from err
        return interpretation.to_dict()

    @app.get("/x/render/{qname}.svg")
    def x_render(qname: str, commit: str | None = None) -> Any:
        model = model_or_404(commit or WORKING_COMMIT_ID)
        element = model if qname in ("", "$root") else resolve_qname(model, qname)
        try:
            from .render import to_svg

            svg = to_svg(element)
        except HTTPException:
            raise
        except Exception as err:  # ipyelk/node unavailable, layout failure
            raise HTTPException(501, f"rendering unavailable on this server: {err}") from err
        return Response(content=svg, media_type="image/svg+xml")

    return app


def serve(path: str | Path = ".", *, host: str = "127.0.0.1", port: int = 9000) -> None:
    """Run the API server (blocking).  ``longeron serve [path] --port N``.

    Binds to ``127.0.0.1`` by default: the server is local-first and does
    no authentication.  Plain ``uvicorn.run`` -- no signal-based reload
    tricks, so this works identically on Windows and POSIX.
    """

    try:
        import uvicorn
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise MissingExtraError("the API server", "uvicorn", "server") from err

    uvicorn.run(create_app(path), host=host, port=port)
