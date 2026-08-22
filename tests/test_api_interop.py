"""Self-interop loop: longeron Client <-> longeron server, no network.

The FastAPI app serves a temp git repo; the longeron Client talks to it
through an in-process Starlette TestClient transport.  This is the round
trip the API layer exists for: fetch models at git commits, push a commit
back, and exercise the /x/ extension endpoints.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

pytest.importorskip("pyecore")
pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from starlette.testclient import TestClient  # noqa: E402 (needs fastapi)

from longeron.client import Client  # noqa: E402
from longeron.errors import SysMLError  # noqa: E402
from longeron.server import create_app  # noqa: E402

if shutil.which("git") is None:  # pragma: no cover - git-less machines
    pytest.skip("git executable not available", allow_module_level=True)

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

package Controls {
    state def Power {
        entry; then off;
        state off;
        state on;
        transition first off accept turnOn then on;
        transition first on accept turnOff then off;
    }
}
"""


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, env=_GIT_ENV, capture_output=True, check=True)


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("LONGERON_CACHE_DIR", str(tmp_path / "cache"))
    root = tmp_path / "modelrepo"
    root.mkdir()
    git(root, "init", "-q")
    (root / "vehicle.sysml").write_text(V1, encoding="utf-8")
    git(root, "add", "vehicle.sysml")
    git(root, "commit", "-q", "-m", "c1: Car")
    (root / "vehicle.sysml").write_text(V2, encoding="utf-8")
    git(root, "add", "vehicle.sysml")
    git(root, "commit", "-q", "-m", "c2: Truck, fleetCar, Power")
    return root


@pytest.fixture
def client(repo) -> Client:
    return Client(http=TestClient(create_app(repo)))


def project_id(client: Client) -> str:
    return client.list_projects()[0]["@id"]


class TestResources:
    def test_project_listing(self, client):
        projects = client.list_projects()
        assert len(projects) == 1
        assert projects[0]["name"].startswith("modelrepo ")

    def test_project_resolves_by_name_prefix(self, client):
        assert client._project_id("modelrepo") == project_id(client)

    def test_commits_listing(self, client):
        commits = client.list_commits(project_id(client))
        assert [c["description"] for c in commits] == [
            "c1: Car",
            "c2: Truck, fleetCar, Power",
            "uncommitted working tree",
        ]

    def test_single_element_fetch_matches_listing(self, client):
        pid = project_id(client)
        record = next(r for r in client.list_elements(pid) if r.get("declaredName") == "Garage")
        assert client.element(pid, record["@id"]) == record

    def test_unknown_project_and_commit_404(self, client):
        with pytest.raises(SysMLError, match="no project"):
            client.list_commits("no-such-project")
        with pytest.raises(SysMLError, match="404"):
            client.list_elements(project_id(client), commit="deadbeef")
        assert client._http.get("projects/no-such/commits").status_code == 404

    def test_pagination_via_link_header(self, client, repo):
        small = Client(http=TestClient(create_app(repo)), page_size=4)
        pid = project_id(client)
        assert [r["@id"] for r in small.list_elements(pid)] == [
            r["@id"] for r in client.list_elements(pid)
        ]

    def test_roots_endpoint_returns_the_root_namespace(self, client):
        pid = project_id(client)
        roots = client._http.get(f"projects/{pid}/commits/working/roots").json()
        assert [r["@type"] for r in roots] == ["Namespace"]


class TestFetchModel:
    def test_models_differ_across_commits(self, client):
        pid = project_id(client)
        first, second = (c["@id"] for c in client.list_commits(pid)[:2])
        m1 = client.fetch_model(pid, commit=first)
        m2 = client.fetch_model(pid, commit=second)
        garage1 = m1.find("Garage")
        garage2 = m2.find("Garage")
        assert [e.name for e in garage1.members] == ["Car"]
        assert [e.name for e in garage2.members] == ["Car", "Truck", "fleetCar"]
        truck = garage2.member_named("Truck")
        assert truck.supers == ["Garage::Car"]
        assert garage2.member_named("fleetCar").types == ["Garage::Car"]

    def test_default_commit_is_working_tree(self, client, repo):
        (repo / "vehicle.sysml").write_text(
            V2 + "package Dirty { part def New; }\n", encoding="utf-8"
        )
        model = client.fetch_model(project_id(client))
        assert model.find("Dirty::New") is not None


class TestPushCommit:
    def test_change_records_round_trip(self, client, repo):
        pid = project_id(client)
        garage = next(r for r in client.list_elements(pid) if r.get("declaredName") == "Garage")
        bus_id, membership_id = str(uuid.uuid4()), str(uuid.uuid4())
        result = client.push_commit(
            pid,
            [
                {
                    "identity": {"@id": bus_id},
                    "payload": {"@type": "PartDefinition", "declaredName": "Bus"},
                },
                {
                    "identity": {"@id": membership_id},
                    "payload": {
                        "@type": "OwningMembership",
                        "owningRelatedElement": {"@id": garage["@id"]},
                        "ownedRelatedElement": [{"@id": bus_id}],
                    },
                },
            ],
            description="add Bus",
        )
        assert result["written"] == ["vehicle.sysml"]
        # server wrote .sysml text; the git history is untouched (the user
        # commits: tools must not auto-commit user repositories)
        assert "part def Bus;" in (repo / "vehicle.sysml").read_text(encoding="utf-8")
        assert len(client.list_commits(pid)) == 3  # 2 git commits + working
        # re-fetch shows the pushed element
        assert client.fetch_model(pid).find("Garage::Bus") is not None

    def test_push_whole_model_round_trip(self, client):
        import longeron.model as M

        pid = project_id(client)
        model = client.fetch_model(pid)
        model.find("Garage").add(M.Definition(kind="part", name="Van"))
        client.push_commit(pid, model, description="add Van via model push")
        assert client.fetch_model(pid).find("Garage::Van") is not None

    def test_delete_round_trip(self, client):
        pid = project_id(client)
        truck = next(r for r in client.list_elements(pid) if r.get("declaredName") == "Truck")
        client.push_commit(pid, [{"identity": {"@id": truck["@id"]}, "payload": None}])
        assert client.fetch_model(pid).find("Garage::Truck") is None

    def test_bad_change_records_400(self, client):
        with pytest.raises(SysMLError, match="400"):
            client.push_commit(
                project_id(client),
                [{"identity": {"@id": str(uuid.uuid4())}, "payload": None}],
            )


class TestExtensions:
    def test_validate_finds_seeded_typo(self, client, repo):
        (repo / "broken.sysml").write_text(
            "package Broken { part def Bad :> NoSuchThing; }\n", encoding="utf-8"
        )
        report = client.validate()
        codes = {d["code"] for d in report["diagnostics"]}
        assert "unresolved-reference" in codes
        elements = {d["element"] for d in report["diagnostics"]}
        assert "Broken::Bad" in elements

    def test_validate_clean_at_committed_ref(self, client):
        first = client.list_commits(project_id(client))[0]["@id"]
        report = client.validate(commit=first)
        assert report["errors"] == 0

    def test_instantiate(self, client):
        result = client.instantiate("Garage::Car")
        assert result["instance"]["@type"] == "Garage::Car"
        assert "checks" in result

    def test_instantiate_unknown_qname_404(self, client):
        with pytest.raises(SysMLError, match="404"):
            client.instantiate("Garage::Nope")

    def test_simulate_returns_trace(self, client):
        result = client.simulate("Controls::Power", events=["turnOn", "turnOff", "turnOn"])
        assert result["final_state"] == "on"
        assert len(result["trace"]) >= 3
        assert result["ignored_events"] == []

    def test_render_returns_svg_bytes(self, client):
        pytest.importorskip("ipyelk")
        if shutil.which("node") is None:
            pytest.skip("node executable not available")
        payload = client.render_svg("Garage")
        assert payload.startswith(b"<svg")

    def test_render_unknown_qname_404(self, client):
        pytest.importorskip("ipyelk")
        with pytest.raises(SysMLError, match="404"):
            client.render_svg("Garage::Nope")
