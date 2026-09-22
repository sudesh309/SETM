"""Ontology loading, inheritance and validation."""

from __future__ import annotations

import pytest

from setm.errors import OntologyError, ValidationError
from setm.model import Edge, Node
from setm.ontology.loader import build_ontology
from setm.ontology.schema import PropertySpec
from setm.ontology.validate import coerce_value, validate_edge, validate_node

MINIMAL = {
    "ontology": {"id": "t", "version": "1", "namespace": "https://example.org/t#"},
    "node_types": {
        "Base": {"abstract": True, "properties": {"name": {"type": "string", "required": True}}},
        "Task": {"extends": "Base", "properties": {"effort": {"type": "number", "minimum": 0}}},
        "Gate": {"extends": "Base"},
    },
    "edge_types": {
        "DUE_AT": {"domain": ["Task"], "range": ["Gate"], "cardinality": "many_to_one", "question": "when"},
    },
}


def test_shipped_ontology_is_consistent(ontology):
    assert ontology.id == "aerospace-se-core"
    assert "Activity" in ontology.node_types
    assert ontology.node_role("activity") == "Activity"
    assert ontology.edge_role("responsible") == "RESPONSIBLE_FOR"
    # Every role must point at something that exists.
    for role, target in ontology.roles.items():
        if role.endswith(("_property", "_values")):
            continue
        assert target in ontology.node_types or target in ontology.edge_types, role


def test_every_edge_domain_and_range_is_declared(ontology):
    for spec in ontology.edge_types.values():
        for name in spec.domain + spec.range:
            assert name in ontology.node_types


def test_assumption_and_parameter_are_first_class_elements(ontology):
    assert ontology.node_role("assumption") == "Assumption"
    assert ontology.node_role("parameter") == "Parameter"
    assert ontology.edge_role("underlies") == "UNDERLIES"
    assert ontology.edge_role("has_parameter") == "HAS_PARAMETER"
    assert ontology.edge_role("parameter_link") == "PARAMETER_LINK"
    # Parameter-to-parameter links only connect parameters, per the ontology's own rule.
    link = ontology.edge_type("PARAMETER_LINK")
    assert link.domain == ["Parameter"]
    assert link.range == ["Parameter"]


def test_status_is_available_on_tasks_risks_assumptions_and_work_packages(ontology):
    for type_name in ("Activity", "Risk", "Assumption", "WorkPackage"):
        assert "status" in ontology.node_types[type_name].properties, type_name


def test_inheritance_is_flattened():
    onto = build_ontology(MINIMAL)
    assert "name" in onto.node_types["Task"].properties
    assert onto.is_a("Task", "Base")
    assert not onto.is_a("Gate", "Task")


def test_inheritance_cycle_is_rejected():
    raw = {**MINIMAL, "node_types": {"A": {"extends": "B"}, "B": {"extends": "A"}}}
    with pytest.raises(OntologyError, match="cycle"):
        build_ontology(raw)


def test_unknown_parent_is_rejected():
    raw = {**MINIMAL, "node_types": {"A": {"extends": "Missing"}}}
    with pytest.raises(OntologyError, match="unknown type"):
        build_ontology(raw)


def test_edge_referring_to_missing_node_type_is_rejected():
    raw = {
        **MINIMAL,
        "edge_types": {"X": {"domain": ["Task"], "range": ["Nope"]}},
    }
    with pytest.raises(OntologyError, match="not a node type"):
        build_ontology(raw)


def test_enum_without_values_is_rejected():
    with pytest.raises(OntologyError, match="no values"):
        PropertySpec.from_dict("status", {"type": "enum"})


def test_property_sets_are_mixed_in():
    raw = {
        **MINIMAL,
        "property_sets": {"audit": {"owner": {"type": "string"}}},
        "node_types": {**MINIMAL["node_types"], "Task": {"extends": "Base", "include_properties": ["audit"]}},
    }
    onto = build_ontology(raw)
    assert "owner" in onto.node_types["Task"].properties


def test_overlay_merge_adds_types(tmp_path):
    import json

    base = tmp_path / "base.json"
    base.write_text(json.dumps(MINIMAL))
    overlay = tmp_path / "overlay.json"
    overlay.write_text(json.dumps({
        "extends_ontology": str(base),
        "node_types": {"Review": {"extends": "Base"}},
    }))

    from setm.ontology.loader import load_ontology

    onto = load_ontology(str(overlay))
    assert "Review" in onto.node_types
    assert "Task" in onto.node_types  # base survived the merge


# -- value coercion ---------------------------------------------------------

@pytest.mark.parametrize(
    "datatype,raw,expected",
    [
        ("integer", "42", 42),
        ("number", "3.5", 3.5),
        ("boolean", "yes", True),
        ("boolean", "FALSE", False),
        ("list", "a, b ,c", ["a", "b", "c"]),
        ("string", 7, "7"),
    ],
)
def test_coercion_accepts_spreadsheet_style_input(datatype, raw, expected):
    spec = PropertySpec(name="p", datatype=datatype)
    assert coerce_value(spec, raw) == expected


def test_coercion_rejects_out_of_range():
    spec = PropertySpec(name="p", datatype="integer", minimum=0, maximum=10)
    with pytest.raises(ValidationError):
        coerce_value(spec, 11)


def test_coercion_rejects_unknown_enum_value():
    spec = PropertySpec(name="status", datatype="enum", values=["a", "b"])
    with pytest.raises(ValidationError, match="not one of"):
        coerce_value(spec, "c")


def test_missing_required_property_is_rejected(ontology):
    node = Node(id="x", type="Activity", properties={})
    with pytest.raises(ValidationError, match="required property 'name'"):
        validate_node(ontology, node)


def test_abstract_type_cannot_be_instantiated(ontology):
    with pytest.raises(ValidationError, match="abstract"):
        validate_node(ontology, Node(id="x", type="Thing", properties={"name": "n"}))


def test_default_values_are_applied(ontology):
    node = validate_node(ontology, Node(id="x", type="Activity", properties={"name": "n"}))
    assert node.properties["status"] == "not_started"


def test_strict_mode_rejects_undeclared_properties(ontology):
    node = Node(id="x", type="Activity", properties={"name": "n", "invented": 1})
    validate_node(ontology, Node.from_dict(node.to_dict()))  # lenient keeps it
    with pytest.raises(ValidationError, match="not declared"):
        validate_node(ontology, node, strict=True)


def test_edge_domain_is_enforced(ontology):
    person = Node(id="p", type="Person", properties={"name": "P"})
    activity = Node(id="a", type="Activity", properties={"name": "A"})
    edge = Edge(id="e", type="RESPONSIBLE_FOR", source="a", target="p")
    with pytest.raises(ValidationError, match="cannot start at"):
        validate_edge(ontology, edge, activity, person)


def test_edge_accepts_subtype_in_domain():
    onto = build_ontology({
        **MINIMAL,
        "node_types": {**MINIMAL["node_types"], "SubTask": {"extends": "Task"}},
        "edge_types": {"DUE_AT": {"domain": ["Task"], "range": ["Gate"]}},
    })
    source = Node(id="s", type="SubTask", properties={"name": "s"})
    target = Node(id="t", type="Gate", properties={"name": "t"})
    validate_edge(onto, Edge(id="e", type="DUE_AT", source="s", target="t"), source, target)


def test_shipped_programme_overlay_extends_the_core():
    """The example overlay must keep working as the core ontology evolves."""
    from setm.ontology.loader import load_ontology

    onto = load_ontology("./ontologies/example-programme-overlay.yaml")
    activity = onto.node_types["Activity"]

    assert "rationale" in activity.properties          # inherited from the core
    assert "itar_relevant" in activity.properties      # added by the overlay
    assert onto.node_types["CertificationItem"].category == "Why"
    assert "SUBSTANTIATES" in onto.edge_types
    # Roles survive the merge, so the KPI engine still resolves.
    assert onto.node_role("activity") == "Activity"
    assert onto.edge_role("responsible") == "RESPONSIBLE_FOR"
    assert "activity_to_certification" in onto.trace_paths


def test_overlay_graph_validates_and_scores(demo_document):
    """A graph authored against the core ontology still validates under an overlay."""
    from setm.graph.store import GraphStore
    from setm.kpi.metrics import compute_kpis
    from setm.ontology.loader import load_ontology
    from setm.ontology.validate import validate_document

    onto = load_ontology("./ontologies/example-programme-overlay.yaml")
    assert validate_document(onto, demo_document)["valid"] is True
    report = compute_kpis(GraphStore(demo_document, onto))
    assert report["health_score"]["value"] is not None


# -- weighting and default properties ---------------------------------------

def test_weight_reaches_every_node_and_edge_type(ontology):
    """`default_properties` is how a cross-cutting attribute covers edge types,
    which have no inheritance of their own."""
    for spec in ontology.node_types.values():
        assert "weight" in spec.properties, spec.name
    for spec in ontology.edge_types.values():
        assert "weight" in spec.properties, spec.name


def test_weight_defaults_to_high(ontology, empty_store):
    node = empty_store.add_node("Activity", {"name": "Unweighted"})
    assert node.properties["weight"] == "high"
    spec = ontology.node_types["Activity"].properties["weight"]
    assert spec.values == ["low", "medium", "high"]


def test_weight_rejects_anything_outside_the_three_levels(empty_store):
    with pytest.raises(ValidationError, match="not one of"):
        empty_store.add_node("Activity", {"name": "x", "weight": "critical"})


def test_relations_carry_weight_too(empty_store):
    empty_store.add_node("Person", {"name": "A"}, node_id="p1")
    empty_store.add_node("Activity", {"name": "T"}, node_id="a1")
    edge = empty_store.add_edge("RESPONSIBLE_FOR", "p1", "a1", {"weight": "low"})
    assert edge.properties["weight"] == "low"
    default_edge = empty_store.add_edge("ACCOUNTABLE_FOR", "p1", "a1")
    assert default_edge.properties["weight"] == "high"


def test_a_type_can_override_the_default_property():
    raw = {
        **MINIMAL,
        "property_sets": {"w": {"weight": {"type": "enum", "values": ["a", "b"], "default": "a"}}},
        "default_properties": {"node_types": ["w"], "edge_types": ["w"]},
        "node_types": {
            **MINIMAL["node_types"],
            "Task": {
                "extends": "Base",
                "properties": {"weight": {"type": "string", "default": "bespoke"}},
            },
        },
    }
    onto = build_ontology(raw)
    assert onto.node_types["Task"].properties["weight"].datatype == "string"
    assert onto.node_types["Gate"].properties["weight"].datatype == "enum"
    assert "weight" in onto.edge_types["DUE_AT"].properties


def test_unknown_default_property_set_is_rejected():
    raw = {**MINIMAL, "default_properties": {"node_types": ["nonexistent"]}}
    with pytest.raises(OntologyError, match="unknown property set"):
        build_ontology(raw)


# -- tools ------------------------------------------------------------------

def test_tool_is_a_first_class_element(ontology):
    tool = ontology.node_types["Tool"]
    assert tool.category == "How"
    assert not tool.abstract
    for name in ("tool_type", "vendor", "version", "qualification_status", "licence_model"):
        assert name in tool.properties


def test_tool_relations_are_declared(ontology):
    assert ontology.edge_role("uses_tool") == "USES_TOOL"
    assert ontology.edge_role("administers") == "ADMINISTERS"
    assert ontology.node_role("tool") == "Tool"
    uses = ontology.edge_types["USES_TOOL"]
    assert uses.domain == ["Activity"] and uses.range == ["Tool"]
    assert uses.question == "how"


def test_activity_may_use_a_tool_but_a_tool_may_not_use_an_activity(empty_store):
    empty_store.add_node("Activity", {"name": "Analysis"}, node_id="a1")
    empty_store.add_node("Tool", {"name": "MATLAB"}, node_id="t1")
    empty_store.add_edge("USES_TOOL", "a1", "t1")
    with pytest.raises(ValidationError, match="cannot start at"):
        empty_store.add_edge("USES_TOOL", "t1", "a1")


def test_tool_chain_links_tools_to_each_other(empty_store):
    empty_store.add_node("Tool", {"name": "DOORS"}, node_id="t1")
    empty_store.add_node("Tool", {"name": "Cameo"}, node_id="t2")
    edge = empty_store.add_edge("EXCHANGES_DATA_WITH", "t1", "t2", {"exchange_format": "ReqIF", "automated": True})
    assert edge.properties["automated"] is True
