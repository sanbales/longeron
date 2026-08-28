"""RAG substrate: deterministic chunking, neighborhoods, keyword search.

No third-party dependencies -- :mod:`longeron.rag` is stdlib only.
"""

from pathlib import Path

import pytest

import longeron
from longeron import rag

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def model():
    return longeron.load(EXAMPLES / "uav_missions.sysml", cache=False)


@pytest.fixture(scope="module")
def chunks(model):
    return rag.model_chunks(model)


# -- chunking ----------------------------------------------------------------


def test_chunks_are_deterministic_with_stable_ids(model, chunks):
    again = rag.model_chunks(model)
    assert chunks == again  # byte-identical: embedding caches stay warm
    ids = [chunk["id"] for chunk in chunks]
    assert len(ids) == len(set(ids))
    assert ids[0] == "UavMissions"


def test_every_chunk_reparses_as_sysml(chunks):
    """Chunk text is the exporter's own fragment printing -- each chunk
    must parse standalone (references may dangle; syntax may not)."""

    for chunk in chunks:
        longeron.loads(chunk["text"])  # raises ParseError on bad syntax


def test_oversized_definitions_split_and_still_reparse(model):
    tight = rag.model_chunks(model, max_chars=400)
    assert len(tight) > len(rag.model_chunks(model))
    for chunk in tight:
        longeron.loads(chunk["text"])
    nested = [c for c in tight if c["id"].startswith("UavMissions::MissionUAV::")]
    assert any(c["id"] == "UavMissions::MissionUAV::armWall" for c in nested)


def test_package_chunks_are_shallow(chunks):
    package = next(chunk for chunk in chunks if chunk["id"] == "UavMissions")
    assert package["kind"] == "package"
    assert "Multi-mission UAV catalog" in package["text"]  # its own doc
    assert "part def BoxQuad" not in package["text"]  # members chunk apart
    assert package["doc"] and "Multi-mission" in package["doc"]


def test_chunk_contract_fields(chunks):
    chunk = next(c for c in chunks if c["id"] == "UavMissions::Catalog::AirframeChoice")
    assert chunk["kind"] == "part def"
    assert chunk["context"] == "package UavMissions > package Catalog"
    assert chunk["text"].startswith("variation part def AirframeChoice :> Airframe {")
    assert chunk["refs"] == [
        "UavMissions::Airframe",
        "UavMissions::BoxQuad",
        "UavMissions::TeardropQuad",
        "UavMissions::VtolWing",
        "UavMissions::DartInterceptor",
    ]


def test_refs_canonicalize_and_skip_internal_names(chunks):
    isr = next(c for c in chunks if c["id"] == "UavMissions::IsrUav")
    assert "UavMissions::MissionUAV" in isr["refs"]  # specialization
    assert "UavMissions::Catalog::SensorChoice" in isr["refs"]  # typing
    assert "UavMissions::Propulsion::HoverPower" in isr["refs"]  # calc call
    assert "Real" in isr["refs"]  # unresolved stdlib name stays as written
    # references between IsrUav's own members are internal, not outgoing
    assert not any(ref.startswith("UavMissions::IsrUav::") for ref in isr["refs"])


def test_parameters_never_split_from_their_calc(model):
    tight = rag.model_chunks(model, max_chars=200)
    hover = next(c for c in tight if c["id"] == "UavMissions::Propulsion::HoverPower")
    assert "in massKg" in hover["text"]  # signature stays whole
    assert not any(c["id"].startswith("UavMissions::Propulsion::HoverPower::") for c in tight)


# -- neighborhood -------------------------------------------------------------


def test_neighborhood_pulls_the_semantic_context(model):
    ids = [chunk["id"] for chunk in rag.neighborhood(model, "UavMissions::MissionUAV", hops=1)]
    assert ids[0] == "UavMissions::MissionUAV"  # seed first
    assert "UavMissions::Catalog::MotorChoice" in ids  # its motors
    assert "UavMissions::Catalog::MaterialChoice" in ids  # its materials
    assert "UavMissions::Structures::TubeMass" in ids  # sizing calcs it calls
    assert "UavMissions::IsrUav" in ids  # who specializes it (reverse edge)


def test_neighborhood_of_a_mission_reaches_its_requirement(model):
    ids = [chunk["id"] for chunk in rag.neighborhood(model, "UavMissions::IsrUav", hops=1)]
    assert "UavMissions::MissionRequirements::IsrTasking" in ids  # cites IsrUav
    assert "UavMissions::Catalog::SensorChoice" in ids


def test_neighborhood_hops_expand_monotonically(model):
    one = {c["id"] for c in rag.neighborhood(model, "UavMissions::IsrUav", hops=1)}
    two = {c["id"] for c in rag.neighborhood(model, "UavMissions::IsrUav", hops=2)}
    assert one < two
    # hop 2 reaches the sensor catalog through SensorChoice
    assert "UavMissions::ZenmuseH20" in two


def test_neighborhood_resolves_member_names_to_their_chunk(model):
    """A qname *inside* a chunk (an attribute) seeds its enclosing chunk."""

    chunks = rag.neighborhood(model, "UavMissions::MissionUAV::armWall", hops=0)
    assert [c["id"] for c in chunks] == ["UavMissions::MissionUAV"]


def test_neighborhood_unknown_name_raises(model):
    with pytest.raises(longeron.SysMLError):
        rag.neighborhood(model, "NoSuch::Thing")


# -- search --------------------------------------------------------------------


def test_search_surfaces_the_right_calc_defs(model):
    ids = [hit["chunk"]["id"] for hit in rag.search(model, "station time energy", limit=5)]
    assert ids[0] == "UavMissions::Performance::StationTime"
    ids = [hit["chunk"]["id"] for hit in rag.search(model, "hover power disk", limit=5)]
    assert ids[0] == "UavMissions::Propulsion::HoverPower"


def test_search_is_camelcase_aware(model):
    """'endurance battery' finds the energy ledger even though no element
    is literally named 'battery' + the doc says 'battery joules'."""

    ids = [hit["chunk"]["id"] for hit in rag.search(model, "endurance battery", limit=5)]
    assert "UavMissions::Catalog::BatteryChoice" in ids
    assert "UavMissions::Propulsion::UsableEnergy" in ids


def test_search_scores_sorted_and_positive(model):
    hits = rag.search(model, "spar bending material")
    assert hits, "expected hits"
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(score > 0 for score in scores)
    assert hits[0]["chunk"]["id"] == "UavMissions::MissionUAV"


def test_search_accepts_term_lists_and_chunks(model, chunks):
    from_model = rag.search(model, ["station", "time"], limit=3)
    from_chunks = rag.search(chunks, "station time", limit=3)
    assert [h["chunk"]["id"] for h in from_model] == [h["chunk"]["id"] for h in from_chunks]


def test_search_no_match_is_empty(model):
    assert rag.search(model, "zzzznope") == []
