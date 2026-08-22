"""Git-backed project store tests (no HTTP layer; see test_api_interop.py).

The store maps the OMG Systems Modeling API resource model onto a git
repository: commits are ``git log`` entries touching the served ``.sysml``
sources, elements are parsed from ``git show`` blobs at that ref, and the
uncommitted working tree is the ``working`` pseudo-commit.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from longeron.errors import SysMLError
from longeron.server import WORKING_COMMIT_ID, GitProjectStore, _refspec

if shutil.which("git") is None:  # pragma: no cover - git-less machines
    pytest.skip("git executable not available", allow_module_level=True)

#: hermetic git: no user/system config, fixed identity
_GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "tester",
    "GIT_AUTHOR_EMAIL": "tester@example.com",
    "GIT_COMMITTER_NAME": "tester",
    "GIT_COMMITTER_EMAIL": "tester@example.com",
}

V1 = """package Garage {
    part def Car {
        attribute wheels;
    }
}
"""

V2 = """package Garage {
    part def Car {
        attribute wheels;
    }
    part def Truck :> Car;
    part fleetCar : Car;
}
"""


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, env=_GIT_ENV, capture_output=True, text=True, check=True
    )
    return result.stdout


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    """A git repo with two commits of vehicle.sysml (V1 then V2)."""

    monkeypatch.setenv("LONGERON_CACHE_DIR", str(tmp_path / "cache"))
    root = tmp_path / "modelrepo"
    root.mkdir()
    git(root, "init", "-q")
    (root / "vehicle.sysml").write_text(V1, encoding="utf-8")
    git(root, "add", "vehicle.sysml")
    git(root, "commit", "-q", "-m", "c1: Car")
    (root / "vehicle.sysml").write_text(V2, encoding="utf-8")
    git(root, "add", "vehicle.sysml")
    git(root, "commit", "-q", "-m", "c2: Truck and fleetCar")
    return root


class TestRefspecPortability:
    """`git show REF:path` tree paths must use '/' on every OS."""

    def test_nested_posix_path(self):
        assert _refspec("abc123", PurePosixPath("nested/dir/m.sysml")) == (
            "abc123:nested/dir/m.sysml"
        )

    def test_nested_path_composes_with_forward_slashes_even_on_windows(self):
        # PureWindowsPath simulates os.sep == '\\': the refspec must still
        # come out with forward slashes (git rejects backslash tree paths)
        assert _refspec("abc123", PureWindowsPath("nested\\dir\\m.sysml")) == (
            "abc123:nested/dir/m.sysml"
        )

    def test_plain_string(self):
        assert _refspec("abc123", "vehicle.sysml") == "abc123:vehicle.sysml"


class TestCommits:
    def test_git_commits_oldest_first_with_previous_chain(self, repo):
        store = GitProjectStore(repo)
        commits = store.git_commits()
        assert [c["description"] for c in commits] == ["c1: Car", "c2: Truck and fleetCar"]
        assert commits[0]["previousCommit"] is None
        assert commits[1]["previousCommit"] == {"@id": commits[0]["@id"]}

    def test_commits_end_with_working_pseudo_commit(self, repo):
        store = GitProjectStore(repo)
        commits = store.commits()
        assert commits[-1]["@id"] == WORKING_COMMIT_ID
        assert commits[-1]["previousCommit"] == {"@id": commits[-2]["@id"]}

    def test_only_commits_touching_served_sysml_sources(self, repo):
        (repo / "README.md").write_text("docs only\n", encoding="utf-8")
        git(repo, "add", "README.md")
        git(repo, "commit", "-q", "-m", "c3: docs")
        assert len(GitProjectStore(repo).git_commits()) == 2

    def test_subdirectory_scope(self, repo):
        sub = repo / "models"
        sub.mkdir()
        (sub / "extra.sysml").write_text("package Extra;\n", encoding="utf-8")
        git(repo, "add", "models/extra.sysml")
        git(repo, "commit", "-q", "-m", "c3: subdir model")
        store = GitProjectStore(sub)
        assert [c["description"] for c in store.git_commits()] == ["c3: subdir model"]
        assert [e.name for e in store.model_at(WORKING_COMMIT_ID).members] == ["Extra"]

    def test_resolve_commit_rejects_unknown(self, repo):
        with pytest.raises(SysMLError, match="unknown commit"):
            GitProjectStore(repo).resolve_commit("not-a-ref")

    def test_project_record_pilot_style_name(self, repo):
        record = GitProjectStore(repo).project_record()
        assert record["@type"] == "Project"
        assert record["name"].startswith("modelrepo ")
        assert len(record["name"].split()) == 1 + 6  # name + 6-token timestamp


class TestModelAtRef:
    def test_models_differ_between_commits(self, repo):
        store = GitProjectStore(repo)
        first, second = (c["@id"] for c in store.git_commits())
        m1 = store.model_at(first)
        m2 = store.model_at(second)
        assert [e.name for e in m1.members[0].members] == ["Car"]
        assert [e.name for e in m2.members[0].members] == ["Car", "Truck", "fleetCar"]

    def test_working_tree_reflects_uncommitted_edits(self, repo):
        (repo / "vehicle.sysml").write_text(
            V2 + "package Dirty { part def New; }\n", encoding="utf-8"
        )
        model = GitProjectStore(repo).model_at(WORKING_COMMIT_ID)
        assert [e.name for e in model.members] == ["Garage", "Dirty"]

    def test_historic_refs_are_memoized(self, repo):
        store = GitProjectStore(repo)
        sha = store.git_commits()[0]["@id"]
        assert store.model_at(sha) is store.model_at(sha)

    def test_short_ref_resolves(self, repo):
        store = GitProjectStore(repo)
        sha = store.git_commits()[0]["@id"]
        assert store.model_at(sha[:8]) is store.model_at(sha)

    def test_directory_without_git_serves_working_only(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LONGERON_CACHE_DIR", str(tmp_path / "cache"))
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "m.sysml").write_text("package Solo { part def One; }\n", encoding="utf-8")
        store = GitProjectStore(plain)
        assert store.git_commits() == []
        assert [c["@id"] for c in store.commits()] == [WORKING_COMMIT_ID]
        assert store.model_at(WORKING_COMMIT_ID).members[0].name == "Solo"
        with pytest.raises(SysMLError, match="unknown commit"):
            store.model_at("deadbeef")


class TestRecordsAt:
    def test_records_have_ids_and_types(self, repo):
        pytest.importorskip("pyecore")
        records = GitProjectStore(repo).records_at(WORKING_COMMIT_ID)
        assert all("@id" in r and "@type" in r for r in records)
        assert any(r.get("declaredName") == "Garage" for r in records)

    def test_records_memoized_per_immutable_ref(self, repo):
        pytest.importorskip("pyecore")
        store = GitProjectStore(repo)
        sha = store.git_commits()[-1]["@id"]
        assert store.records_at(sha) is store.records_at(sha)


class TestApplyCommit:
    """POSTed commits are materialized as .sysml text, never git-committed."""

    @staticmethod
    def _store(repo) -> GitProjectStore:
        pytest.importorskip("pyecore")
        return GitProjectStore(repo)

    @staticmethod
    def _garage_id(store: GitProjectStore) -> str:
        records = store.records_at(WORKING_COMMIT_ID)
        return next(r["@id"] for r in records if r.get("declaredName") == "Garage")

    def test_add_element_writes_sysml_and_leaves_git_alone(self, repo):
        store = self._store(repo)
        bus_id, membership_id = str(uuid.uuid4()), str(uuid.uuid4())
        result = store.apply_commit(
            {
                "description": "add Bus",
                "change": [
                    {
                        "identity": {"@id": bus_id},
                        "payload": {"@type": "PartDefinition", "declaredName": "Bus"},
                    },
                    {
                        "identity": {"@id": membership_id},
                        "payload": {
                            "@type": "OwningMembership",
                            "owningRelatedElement": {"@id": self._garage_id(store)},
                            "ownedRelatedElement": [{"@id": bus_id}],
                        },
                    },
                ],
            }
        )
        assert result["written"] == ["vehicle.sysml"]
        text = (repo / "vehicle.sysml").read_text(encoding="utf-8")
        assert "part def Bus;" in text
        assert "part def Truck :> Car;" in text  # untouched content survives
        assert len(store.git_commits()) == 2  # materialized, NOT committed
        assert git(repo, "status", "--porcelain").strip().startswith("M")

    def test_update_renames_element(self, repo):
        store = self._store(repo)
        records = store.records_at(WORKING_COMMIT_ID)
        car = next(r for r in records if r.get("declaredName") == "Car")
        store.apply_commit(
            [{"identity": {"@id": car["@id"]}, "payload": {**car, "declaredName": "Sedan"}}]
        )
        text = (repo / "vehicle.sysml").read_text(encoding="utf-8")
        assert "part def Sedan" in text and "part def Car" not in text

    def test_delete_element(self, repo):
        store = self._store(repo)
        records = store.records_at(WORKING_COMMIT_ID)
        truck = next(r for r in records if r.get("declaredName") == "Truck")
        store.apply_commit([{"identity": {"@id": truck["@id"]}, "payload": None}])
        assert "Truck" not in (repo / "vehicle.sysml").read_text(encoding="utf-8")

    def test_new_top_level_package_goes_to_new_file(self, repo):
        store = self._store(repo)
        pkg_id = str(uuid.uuid4())
        result = store.apply_commit(
            [
                {
                    "identity": {"@id": pkg_id},
                    "payload": {"@type": "Package", "declaredName": "Fleet"},
                }
            ]
        )
        assert result["written"] == ["Fleet.sysml"]
        assert (repo / "Fleet.sysml").read_text(encoding="utf-8") == "package Fleet;\n"

    def test_unknown_delete_target_is_rejected(self, repo):
        store = self._store(repo)
        with pytest.raises(SysMLError, match="cannot delete"):
            store.apply_commit([{"identity": {"@id": str(uuid.uuid4())}, "payload": None}])

    def test_empty_change_list_is_rejected(self, repo):
        with pytest.raises(SysMLError, match="no change records"):
            self._store(repo).apply_commit({"change": []})


class TestStoreEdges:
    def test_nonexistent_path_is_rejected(self, tmp_path):
        with pytest.raises(SysMLError, match="does not exist"):
            GitProjectStore(tmp_path / "missing.sysml")

    def test_single_file_store_serves_historic_commits(self, repo):
        store = GitProjectStore(repo / "vehicle.sysml")
        first = store.commits()[0]
        records = store.records_at(first["@id"])
        assert any(r.get("declaredName") == "Car" for r in records)
        assert not any(r.get("declaredName") == "Truck" for r in records)  # V1 only
