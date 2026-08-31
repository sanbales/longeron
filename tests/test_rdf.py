"""RDF projection: vocabulary, literals, serializations, SPARQL (needs rdflib)."""

from pathlib import Path

import pytest

import longeron

rdflib = pytest.importorskip("rdflib")

from longeron import rdf  # noqa: E402  (import after the rdflib guard)

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def model():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


@pytest.fixture(scope="module")
def graph(model):
    return rdf.to_graph(model)


SYSML = rdflib.Namespace(rdf.VOCABULARY)


def element(qname: str):
    return rdflib.URIRef(rdf.ELEMENT_BASE + "/".join(qname.split("::")))


def test_element_types_follow_the_api_metaclasses(graph):
    assert (element("ScoutMissions"), rdflib.RDF.type, SYSML.Package) in graph
    assert (element("DeepScout::Airframe"), rdflib.RDF.type, SYSML.PartDefinition) in graph
    assert (
        element("DeepScout::Propulsion::HoverPower"),
        rdflib.RDF.type,
        SYSML.CalculationDefinition,
    ) in graph
    assert (element("ScoutSizing::IsrStation"), rdflib.RDF.type, SYSML.RequirementDefinition) in (
        graph
    )


def test_names_and_membership(graph):
    boxquad = element("Rotorcraft::BoxQuad")
    assert (boxquad, SYSML.name, rdflib.Literal("BoxQuad")) in graph
    assert (boxquad, SYSML.qualifiedName, rdflib.Literal("Rotorcraft::BoxQuad")) in graph
    assert (element("Rotorcraft"), SYSML.ownedMember, boxquad) in graph


def test_specialization_edges_resolve(graph):
    assert (
        element("Rotorcraft::BoxQuad"),
        SYSML.specializes,
        element("DeepScout::Airframe"),
    ) in graph


def test_attribute_values_are_typed_literals(graph):
    mass = element("Rotorcraft::BoxQuad::mass")
    values = list(graph.objects(mass, SYSML.value))
    assert values == [rdflib.Literal(0.78)]
    assert values[0].datatype == rdflib.XSD.double
    count = element("Rotorcraft::BoxQuad::motorCount")
    (literal,) = graph.objects(count, SYSML.value)
    assert literal.toPython() == 4 and literal.datatype == rdflib.XSD.integer


def test_expression_values_carry_rendered_text(graph):
    drag = element("Rotorcraft::BoxQuad::dragArea")
    (text,) = graph.objects(drag, SYSML.valueExpression)
    assert "BluffFrameDrag" in str(text)


def test_docs_become_rdfs_comments(graph):
    (comment,) = graph.objects(element("DeepScout::Propulsion::HoverPower"), rdflib.RDFS.comment)
    assert "Momentum-theory hover power" in str(comment)


def test_requirement_text_and_constraints_preserved(graph):
    requirement = element("ScoutSizing::IsrStation")
    (comment,) = graph.objects(requirement, rdflib.RDFS.comment)
    assert "90 minutes" in str(comment)
    floor = element("ScoutSizing::IsrStation::stationFloor")
    assert (floor, SYSML.constraintKind, rdflib.Literal("require")) in graph
    (expr,) = graph.objects(floor, SYSML.expression)
    assert "uav.stationMinutes >= 90.0" in str(expr)


def test_anonymous_elements_become_blank_nodes(graph):
    """The unnamed ``assume constraint`` in IsrStation has no IRI-worthy
    name; it must still be present as a blank node member."""

    members = list(graph.objects(element("ScoutSizing::IsrStation"), SYSML.ownedMember))
    anonymous = [m for m in members if isinstance(m, rdflib.BNode)]
    assert anonymous, "expected a blank node for the anonymous assume constraint"
    (assume,) = [
        m for m in anonymous if (m, SYSML.constraintKind, rdflib.Literal("assume")) in graph
    ]
    assert (assume, rdflib.RDF.type, SYSML.ConstraintUsage) in graph


def test_unresolved_references_are_minted_from_their_text(graph):
    """``Real`` is a standard-library name the model does not define; the
    typing edge must survive as an IRI minted from the reference text."""

    mass = element("DeepScout::Airframe::mass")
    assert (mass, SYSML.definedBy, rdflib.URIRef(rdf.ELEMENT_BASE + "Real")) in graph


def test_sparql_part_defs_specializing_airframe_by_mass(model):
    rows = rdf.sparql(
        model,
        """
        SELECT ?name ?mass WHERE {
            ?def a sysml:PartDefinition ; sysml:specializes ?super ;
                 sysml:name ?name ; sysml:ownedMember ?attr .
            ?super sysml:name "Airframe" .
            ?attr sysml:name "mass" ; sysml:value ?mass .
            FILTER(?mass < 1.0)
        } ORDER BY ?mass
        """,
    )
    assert [(str(r.name), r.mass.toPython()) for r in rows] == [
        ("OpenTri", 0.62),
        ("BoxQuad", 0.78),
        ("TeardropQuad", 0.98),
    ]


def test_sparql_requirement_subject_types(graph):
    rows = rdf.sparql(
        graph,
        """
        SELECT ?req ?subjectType WHERE {
            ?r a sysml:RequirementDefinition ; sysml:qualifiedName ?req ;
               sysml:ownedMember ?s .
            ?s sysml:kind "subject" ; sysml:definedBy ?t .
            ?t sysml:qualifiedName ?subjectType .
        } ORDER BY ?req
        """,
    )
    pairs = [(str(r.req), str(r.subjectType)) for r in rows]
    assert ("ScoutSizing::IsrStation", "ScoutSizing::IsrPrime") in pairs
    assert (
        "ScoutMissions::MissionRequirements::IsrTasking",
        "ScoutMissions::IsrUav",
    ) in pairs
    assert ("DeepScout::FlightEnvelope", "DeepScout::MultiRotor") in pairs
    assert len(pairs) == 6


def test_sparql_variation_points_and_variants(graph):
    rows = list(
        rdf.sparql(
            graph,
            """
            SELECT ?point ?variant ?target WHERE {
                ?p sysml:isVariation true ; sysml:name ?point ; sysml:ownedMember ?v .
                ?v sysml:isVariant true ; sysml:name ?variant ; sysml:definedBy ?t .
                ?t sysml:name ?target .
            } ORDER BY ?point ?variant
            """,
        )
    )
    assert len(rows) == 42  # the crossed catalog (10+4+4+5+3+3+2) + the sizing quad (3+3+3+2)
    assert (str(rows[0].point), str(rows[0].variant), str(rows[0].target)) == (
        "AirframeChoice",
        "boxQuad",
        "BoxQuad",
    )


def test_turtle_serialization(graph, tmp_path):
    target = tmp_path / "model.ttl"
    text = rdf.to_turtle(graph, target)
    assert "@prefix sysml:" in text
    assert target.read_text(encoding="utf-8") == text
    reparsed = rdflib.Graph()
    reparsed.parse(data=text, format="turtle")
    assert len(reparsed) == len(graph)


def test_jsonld_serialization(graph):
    import json

    data = json.loads(rdf.to_jsonld(graph))
    assert "@context" in data


def test_graph_is_reproducible(model):
    first, second = rdf.to_graph(model), rdf.to_graph(model)
    assert len(first) == len(second)
    assert first.isomorphic(second)


def test_evaluated_values():
    model = longeron.loads(
        """
        package P {
            part def V {
                attribute a : Real = 2.0;
                attribute b : Real = a * 3.0;
            }
        }
        """
    )
    graph = rdf.to_graph(model, evaluated=True)
    b = rdflib.URIRef(rdf.ELEMENT_BASE + "P/V/b")
    assert list(graph.objects(b, SYSML.evaluatedValue)) == [rdflib.Literal(6.0)]
    # off by default
    assert not list(rdf.to_graph(model).objects(b, SYSML.evaluatedValue))


def test_custom_element_base():
    model = longeron.loads("package P { part def X; }")
    graph = rdf.to_graph(model, base="urn:demo:")
    assert (rdflib.URIRef("urn:demo:P/X"), rdflib.RDF.type, SYSML.PartDefinition) in graph


def test_names_needing_quotes_are_percent_encoded():
    model = longeron.loads("package 'My Pkg' { part def 'X Y'; }")
    graph = rdf.to_graph(model)
    subject = rdflib.URIRef(rdf.ELEMENT_BASE + "My%20Pkg/X%20Y")
    assert (subject, rdflib.RDF.type, SYSML.PartDefinition) in graph
