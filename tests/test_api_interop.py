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
from longeron.server import WORKING_COMMIT_ID, GitProjectStore, create_app  # noqa: E402

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
        part rims : Parts::Wheel [4];
        part spares : Parts::Wheel [0..2];
    }
}

package Parts {
    part def Wheel;
}
"""

V2 = """package Garage {
    part def Car {
        attribute wheels;
        part rims : Parts::Wheel [4];
        part spares : Parts::Wheel [0..2];
    }
    part def Truck :> Car;
    part fleetCar : Car;
}

package Parts {
    part def Wheel;
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

    def test_no_next_link_on_the_exact_final_page(self, client):
        # the last page must not advertise a next page, even when page[size]
        # exactly divides the element count (a spurious link costs every
        # conforming client one extra round trip for an empty page)
        pid = project_id(client)
        http = client._http
        everything = http.get(f"projects/{pid}/commits/working/elements").json()
        n = len(everything)
        assert n > 1
        whole = http.get(f"projects/{pid}/commits/working/elements", params={"page[size]": n})
        assert whole.json() == everything
        assert "link" not in whole.headers  # one exact page: no next
        # walk single-element pages: every page but the last links onward
        resp = http.get(f"projects/{pid}/commits/working/elements", params={"page[size]": 1})
        for i in range(n):
            assert [r["@id"] for r in resp.json()] == [everything[i]["@id"]]
            if i < n - 1:
                assert "link" in resp.headers
                next_url = resp.headers["link"].split("<", 1)[1].split(">", 1)[0]
                resp = http.get(next_url)
            else:
                assert "link" not in resp.headers  # final page ends the walk

    def test_roots_endpoint_returns_the_root_namespace(self, client):
        pid = project_id(client)
        roots = client._http.get(f"projects/{pid}/commits/working/roots").json()
        assert [r["@type"] for r in roots] == ["Namespace"]

    def test_get_single_commit_record(self, client):
        pid = project_id(client)
        commits = client.list_commits(pid)
        got = client._http.get(f"projects/{pid}/commits/{commits[0]['@id']}")
        assert got.status_code == 200
        assert got.json() == commits[0]
        assert client._http.get(f"projects/{pid}/commits/deadbeef").status_code == 404

    def test_commit_not_touching_the_project_404s(self, client, repo):
        # a real git commit that touches no .sysml file resolves as a ref
        # but is not a commit *of this project*
        (repo / "README.md").write_text("docs only\n", encoding="utf-8")
        git(repo, "add", "README.md")
        git(repo, "commit", "-q", "-m", "docs: readme")
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            env=_GIT_ENV,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        pid = project_id(client)
        resp = client._http.get(f"projects/{pid}/commits/{sha}")
        assert resp.status_code == 404
        assert "does not touch" in resp.json()["detail"]

    def test_unknown_page_cursor_404s(self, client):
        pid = project_id(client)
        resp = client._http.get(
            f"projects/{pid}/commits/working/elements",
            params={"page[size]": 2, "page[after]": "not-an-id"},
        )
        assert resp.status_code == 404


class TestWorkingTreeMemo:
    """The working-tree projection is memoized behind a stat fingerprint:
    a paginated listing projects the model once, edits invalidate."""

    def test_paginated_listing_loads_the_working_tree_once(self, repo, monkeypatch):
        import longeron.server as server_module

        calls = {"load": 0}
        real_load = server_module.load

        def counting_load(path, **kwargs):
            calls["load"] += 1
            return real_load(path, **kwargs)

        monkeypatch.setattr(server_module, "load", counting_load)
        small = Client(http=TestClient(create_app(repo)), page_size=4)
        records = small.list_elements(small.list_projects()[0]["@id"])
        assert len(records) > 4  # the listing really spanned several pages
        assert calls["load"] == 1  # ...but the projection was built once

    def test_working_records_memoized_until_the_tree_changes(self, repo):
        store = GitProjectStore(repo)
        first = store.records_at(WORKING_COMMIT_ID)
        assert store.records_at(WORKING_COMMIT_ID) is first  # memo hit
        (repo / "vehicle.sysml").write_text(
            V2 + "package Dirty { part def New; }\n", encoding="utf-8"
        )
        second = store.records_at(WORKING_COMMIT_ID)
        assert second is not first  # the edit invalidated the memo
        assert any(r.get("declaredName") == "Dirty" for r in second)

    def test_single_file_working_tree_uses_the_content_cache(self, repo, monkeypatch):
        from longeron import workspace

        GitProjectStore(repo / "vehicle.sysml").model_at(WORKING_COMMIT_ID)
        builds = {"count": 0}
        real_build = workspace.build_model

        def counting_build(parse_result):
            builds["count"] += 1
            return real_build(parse_result)

        monkeypatch.setattr(workspace, "build_model", counting_build)
        # a fresh store has a cold memo: the parse must come from the
        # content-addressed cache, exactly like a historic blob would
        fresh = GitProjectStore(repo / "vehicle.sysml").model_at(WORKING_COMMIT_ID)
        assert builds["count"] == 0
        assert fresh.find("Garage::Car") is not None


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

    def test_relationship_delete_removes_the_specialization(self, client):
        pid = project_id(client)
        rel = next(r for r in client.list_elements(pid) if r["@type"] == "Subclassification")
        client.push_commit(pid, [{"identity": {"@id": rel["@id"]}, "payload": None}])
        truck = client.fetch_model(pid).find("Garage::Truck")
        assert truck is not None  # the element survives...
        assert truck.supers == []  # ...only the specialization is gone

    def test_relationship_retarget_repoints_the_typing(self, client):
        pid = project_id(client)
        records = client.list_elements(pid)
        fleet_id = next(r["@id"] for r in records if r.get("declaredName") == "fleetCar")
        typing = next(
            r
            for r in records
            if r["@type"] == "FeatureTyping" and r["typedFeature"]["@id"] == fleet_id
        )
        garage = next(r for r in records if r.get("declaredName") == "Garage")
        bus_id, mem_id = str(uuid.uuid4()), str(uuid.uuid4())
        client.push_commit(
            pid,
            [
                {
                    "identity": {"@id": bus_id},
                    "payload": {"@type": "PartDefinition", "declaredName": "Bus"},
                },
                {
                    "identity": {"@id": mem_id},
                    "payload": {
                        "@type": "OwningMembership",
                        "owningRelatedElement": {"@id": garage["@id"]},
                        "ownedRelatedElement": [{"@id": bus_id}],
                    },
                },
                {
                    "identity": {"@id": typing["@id"]},
                    "payload": {
                        "@type": "FeatureTyping",
                        "typedFeature": typing["typedFeature"],
                        "type": {"@id": bus_id},
                    },
                },
            ],
            description="retarget fleetCar to Bus",
        )
        fleet = client.fetch_model(pid).find("Garage::fleetCar")
        assert fleet.types == ["Garage::Bus"]  # retargeted in the same commit as the add


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

    def test_interpret_nominal_population(self, client):
        result = client.interpret("Garage::Car")
        assert result["source"] == "Garage::Car"
        assert result["strategy"] == "nominal"
        assert result["seed"] is None
        assert result["gaps"] == []
        assert result["root"]["@id"] == "Garage::Car#0"
        assert result["root"]["@type"] == "Garage::Car"
        assert [r["@type"] for r in result["root"]["rims"]] == ["Parts::Wheel"] * 4
        assert result["root"]["spares"] == []  # nominal takes the lower bound

    def test_interpret_random_seed_is_deterministic_over_http(self, client):
        first = client.interpret("Garage::Car", strategy="random", seed=7)
        second = client.interpret("Garage::Car", strategy="random", seed=7)
        assert first == second
        assert first["strategy"] == "random"
        assert first["seed"] == 7
        assert 0 <= len(first["root"]["spares"]) <= 2

    def test_interpret_unknown_qname_404(self, client):
        with pytest.raises(SysMLError, match="404"):
            client.interpret("Garage::Nope")

    def test_interpret_bad_strategy_400(self, client):
        with pytest.raises(SysMLError, match=r"400.+strategy"):
            client.interpret("Garage::Car", strategy="bogus")

    def test_interpret_bad_body_types_400(self, client):
        with pytest.raises(SysMLError, match=r"400.+'bindings' must be an object"):
            client.interpret("Garage::Car", bindings=["nope"])
        with pytest.raises(SysMLError, match=r"400.+'selection' must be an object"):
            client.interpret("Garage::Car", selection="nope")
        with pytest.raises(SysMLError, match=r"400.+'seed' must be an integer"):
            client.interpret("Garage::Car", strategy="random", seed="nope")

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


class TestCommitBodyForms:
    """_normalize_changes: flat record form, dict body, and rejects."""

    def test_flat_record_form_updates_in_place(self, client, repo):
        pid = project_id(client)
        car = next(r for r in client.list_elements(pid) if r.get("declaredName") == "Car")
        resp = client._http.post(f"projects/{pid}/commits", json=[{**car, "declaredName": "Sedan"}])
        assert resp.status_code == 201
        assert resp.json()["written"] == ["vehicle.sysml"]
        assert "part def Sedan" in (repo / "vehicle.sysml").read_text(encoding="utf-8")

    def test_dict_body_description_is_recorded(self, client):
        pid = project_id(client)
        garage = next(r for r in client.list_elements(pid) if r.get("declaredName") == "Garage")
        bus_id = str(uuid.uuid4())
        resp = client._http.post(
            f"projects/{pid}/commits",
            json={
                "description": "add a bus",
                "change": [
                    {
                        "identity": {"@id": bus_id},
                        "payload": {"@type": "PartDefinition", "declaredName": "Bus"},
                    },
                    {
                        "identity": {"@id": str(uuid.uuid4())},
                        "payload": {
                            "@type": "OwningMembership",
                            "owningRelatedElement": {"@id": garage["@id"]},
                            "ownedRelatedElement": [{"@id": bus_id}],
                        },
                    },
                ],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["description"] == "add a bus"

    def test_malformed_bodies_400(self, client):
        pid = project_id(client)
        cases = {
            "must be a change list": {"change": "nope"},
            "malformed change entry": [42],
            "change entry has no identity": [{"payload": {}}],
        }
        for fragment, body in cases.items():
            resp = client._http.post(f"projects/{pid}/commits", json=body)
            assert resp.status_code == 400
            assert fragment in resp.json()["detail"]

    def test_deleting_the_root_namespace_400s(self, client):
        pid = project_id(client)
        root = client._http.get(f"projects/{pid}/commits/working/roots").json()[0]
        resp = client._http.post(
            f"projects/{pid}/commits",
            json=[{"identity": {"@id": root["@id"]}, "payload": None}],
        )
        assert resp.status_code == 400
        assert "not an element or typing/specialization record" in resp.json()["detail"]


class TestExtensionBodyValidation:
    def test_unknown_element_id_404s(self, client):
        pid = project_id(client)
        resp = client._http.get(f"projects/{pid}/commits/working/elements/nope")
        assert resp.status_code == 404

    def test_non_object_extension_body_400s(self, client):
        resp = client._http.post(
            "x/instantiate/Garage::Car",
            content=b"[1, 2]",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400
        assert "body must be a JSON object" in resp.json()["detail"]

    def test_invalid_json_extension_body_400s(self, client):
        resp = client._http.post(
            "x/instantiate/Garage::Car",
            content=b"{bad",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400
        assert "invalid JSON body" in resp.json()["detail"]

    def test_instantiate_rejects_non_object_bindings(self, client):
        resp = client._http.post("x/instantiate/Garage::Car", json={"bindings": [1]})
        assert resp.status_code == 400
        assert "'bindings' must be an object" in resp.json()["detail"]

    def test_interpret_rejects_non_string_strategy(self, client):
        resp = client._http.post("x/interpret/Garage::Car", json={"strategy": 42})
        assert resp.status_code == 400
        assert "'strategy' must be a string" in resp.json()["detail"]


class TestClientPlumbing:
    def test_context_manager_closes_the_transport(self, repo):
        closed = {}
        http = TestClient(create_app(repo))
        original_close = http.close

        def tracking_close():
            closed["yes"] = True
            original_close()

        http.close = tracking_close
        with Client(http=http) as ctx_client:
            assert ctx_client.list_projects()
        assert closed == {"yes": True}

    def test_project_id_accepts_a_record(self, client):
        record = client.list_projects()[0]
        assert client._project_id(record) == record["@id"]

    def test_paged_rejects_non_collections(self, client):
        pid = project_id(client)
        with pytest.raises(SysMLError, match="expected a collection"):
            client._paged(f"projects/{pid}/commits/working", {})

    def test_error_detail_falls_back_to_text_for_non_json(self, client):
        class FakeRequest:
            method = "GET"
            url = "http://testserver/boom"

        class FakeResponse:
            status_code = 500
            request = FakeRequest()

            def json(self):
                raise ValueError("not json")

            text = "<html>internal error</html>"

        with pytest.raises(SysMLError, match="internal error"):
            Client._checked(FakeResponse())

    def test_push_commit_accepts_flat_records(self, client):
        pid = project_id(client)
        car = next(r for r in client.list_elements(pid) if r.get("declaredName") == "Car")
        client.push_commit(pid, [{**car, "declaredName": "Coupe"}])
        assert client.fetch_model(pid).find("Garage::Coupe") is not None

    def test_change_entry_without_identity_is_rejected(self):
        with pytest.raises(SysMLError, match="change entry has no identity"):
            Client._as_change({"payload": {}})
