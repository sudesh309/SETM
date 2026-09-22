"""Graph store mutations and traversal."""

from __future__ import annotations

import pytest

from setm.errors import ConflictError, NotFoundError, ValidationError
from setm.graph import query


def add_activity(store, name="Do the thing", node_id=None):
    return store.add_node("Activity", {"name": name}, node_id=node_id, actor="tester")


def test_add_and_fetch(empty_store):
    node = add_activity(empty_store, node_id="a1")
    assert empty_store.node("a1") is node
    assert empty_store.node_count == 1
    assert node.provenance.created_by == "tester"


def test_duplicate_id_is_rejected(empty_store):
    add_activity(empty_store, node_id="a1")
    with pytest.raises(ConflictError):
        add_activity(empty_store, node_id="a1")


def test_missing_node_raises(empty_store):
    with pytest.raises(NotFoundError):
        empty_store.node("nope")


def test_update_bumps_revision_and_merges(empty_store):
    node = add_activity(empty_store, node_id="a1")
    empty_store.update_node("a1", {"status": "in_progress"}, actor="tester")
    assert node.properties["name"] == "Do the thing"
    assert node.properties["status"] == "in_progress"
    assert node.provenance.revision == 2


def test_update_with_stale_revision_conflicts(empty_store):
    add_activity(empty_store, node_id="a1")
    empty_store.update_node("a1", {"status": "in_progress"})
    with pytest.raises(ConflictError, match="changed since"):
        empty_store.update_node("a1", {"status": "done"}, expected_revision=1)


def test_null_clears_a_property(empty_store):
    add_activity(empty_store, node_id="a1")
    empty_store.update_node("a1", {"notes": "temporary"})
    empty_store.update_node("a1", {"notes": None})
    assert "notes" not in empty_store.node("a1").properties


def test_cardinality_one_owner_per_activity(empty_store):
    empty_store.add_node("Person", {"name": "A"}, node_id="p1")
    empty_store.add_node("Person", {"name": "B"}, node_id="p2")
    add_activity(empty_store, node_id="a1")
    empty_store.add_edge("RESPONSIBLE_FOR", "p1", "a1")
    with pytest.raises(ValidationError, match="one_to_many"):
        empty_store.add_edge("RESPONSIBLE_FOR", "p2", "a1")


def test_parameter_link_only_connects_parameters(empty_store):
    empty_store.add_node("Parameter", {"name": "GSD"}, node_id="par1")
    empty_store.add_node("Parameter", {"name": "Mass budget"}, node_id="par2")
    empty_store.add_edge("PARAMETER_LINK", "par1", "par2")  # does not raise

    add_activity(empty_store, node_id="a1")
    with pytest.raises(ValidationError, match="cannot start"):
        empty_store.add_edge("PARAMETER_LINK", "a1", "par2")


def test_duplicate_relation_is_rejected(empty_store):
    empty_store.add_node("Person", {"name": "A"}, node_id="p1")
    add_activity(empty_store, node_id="a1")
    empty_store.add_edge("RESPONSIBLE_FOR", "p1", "a1")
    with pytest.raises(ConflictError, match="already links"):
        empty_store.add_edge("RESPONSIBLE_FOR", "p1", "a1")


def test_self_relation_is_rejected(empty_store):
    add_activity(empty_store, node_id="a1")
    with pytest.raises(ValidationError, match="cannot be related to itself"):
        empty_store.add_edge("DEPENDS_ON", "a1", "a1")


def test_delete_cascades_relations(empty_store):
    empty_store.add_node("Person", {"name": "A"}, node_id="p1")
    add_activity(empty_store, node_id="a1")
    empty_store.add_edge("RESPONSIBLE_FOR", "p1", "a1")
    result = empty_store.delete_node("a1")
    assert len(result["deleted_edges"]) == 1
    assert empty_store.edge_count == 0
    assert empty_store.node_count == 1


def test_delete_without_cascade_refuses_when_linked(empty_store):
    empty_store.add_node("Person", {"name": "A"}, node_id="p1")
    add_activity(empty_store, node_id="a1")
    empty_store.add_edge("RESPONSIBLE_FOR", "p1", "a1")
    with pytest.raises(ConflictError, match="still has"):
        empty_store.delete_node("a1", cascade=False)


def test_retype_refuses_when_it_would_break_a_relation(empty_store):
    empty_store.add_node("Person", {"name": "A"}, node_id="p1")
    add_activity(empty_store, node_id="a1")
    empty_store.add_edge("RESPONSIBLE_FOR", "p1", "a1")
    with pytest.raises(ValidationError, match="would become invalid"):
        empty_store.retype_node("a1", "Milestone")


def test_retype_succeeds_when_relations_still_fit(empty_store):
    add_activity(empty_store, node_id="a1")
    empty_store.retype_node("a1", "Deliverable")
    assert empty_store.node("a1").type == "Deliverable"
    assert empty_store.nodes_of_type("Activity") == []


def test_dangling_edges_are_dropped_on_load(ontology):
    from setm.graph.store import GraphStore
    from setm.model import Edge, GraphDocument, Node

    document = GraphDocument(
        nodes=[Node(id="a", type="Activity", properties={"name": "A"})],
        edges=[Edge(id="e", type="DEPENDS_ON", source="a", target="ghost")],
    )
    store = GraphStore(document, ontology)
    assert store.edge_count == 0


def test_subtype_search_includes_children(demo_store):
    # Everything concrete extends Thing in the shipped ontology.
    assert len(demo_store.nodes_of_type("Thing")) == demo_store.node_count


# -- traversal --------------------------------------------------------------

def test_neighbourhood_respects_depth(demo_store):
    near = query.neighbourhood(demo_store, "act.mtf", depth=1)
    far = query.neighbourhood(demo_store, "act.mtf", depth=2)
    assert len(near["nodes"]) < len(far["nodes"])
    assert near["root"] == "act.mtf"


def test_neighbourhood_limit_flags_truncation(demo_store):
    result = query.neighbourhood(demo_store, "act.mtf", depth=4, limit=5)
    assert result["truncated"] is True
    assert len(result["nodes"]) <= 5


def test_trace_groups_by_question(demo_store):
    trace = query.trace(demo_store, "act.mtf")
    assert set(trace["questions"]) >= {"who", "when", "why", "how", "what"}
    assert trace["completeness"]["score"] == 1.0


def test_completeness_flags_a_missing_owner(demo_store):
    demo_store.add_node("Activity", {"name": "Orphan work"}, node_id="act.orphan")
    result = query.completeness(demo_store, "act.orphan")
    assert "who" in result["missing"]
    assert "RESPONSIBLE_FOR" in result["missing"]["who"]
    assert result["score"] == 0.0


def test_paths_finds_person_to_objective(demo_store):
    found = query.paths(demo_store, "per.laurent", "obj.gsd", max_depth=4)
    assert found
    assert found[0]["nodes"][0]["id"] == "per.laurent"
    assert found[0]["nodes"][-1]["id"] == "obj.gsd"
    assert found[0]["length"] <= found[-1]["length"]


def test_impact_is_directional(demo_store):
    downstream = query.impact(demo_store, "act.arch", direction="out")
    upstream = query.impact(demo_store, "act.arch", direction="in")
    assert downstream["total"] > 0
    assert upstream["total"] > 0
    assert downstream["by_type"] != upstream["by_type"]


def test_cycles_are_detected(empty_store):
    for name in "abc":
        add_activity(empty_store, node_id=f"act.{name}")
    empty_store.add_edge("DEPENDS_ON", "act.a", "act.b")
    empty_store.add_edge("DEPENDS_ON", "act.b", "act.c")
    empty_store.add_edge("DEPENDS_ON", "act.c", "act.a")
    found = query.cycles(empty_store, ["DEPENDS_ON"])
    assert found and len(found[0]) >= 3


def test_demo_has_no_dependency_cycles(demo_store):
    assert query.cycles(demo_store, ["DEPENDS_ON"]) == []


def test_orphans_are_reported(empty_store):
    add_activity(empty_store, node_id="lonely")
    assert [o["id"] for o in query.orphans(empty_store)] == ["lonely"]


def test_related_through_walks_a_declared_chain(demo_store):
    owners = query.related_through(demo_store, "ms.pdr", ["~DELIVERS_AT", "~RESPONSIBLE_FOR"])
    assert {o["id"] for o in owners} >= {"per.mehta", "per.laurent"}


def test_related_through_backwards_step_differs_from_forwards(demo_store):
    forwards = query.related_through(demo_store, "act.mtf", ["DELIVERS_AT"])
    backwards = query.related_through(demo_store, "ms.pdr", ["~DELIVERS_AT"])
    assert [n["id"] for n in forwards] == ["ms.pdr"]
    assert "act.mtf" in {n["id"] for n in backwards}


def test_group_by_property_buckets_activities(demo_store):
    buckets = query.group_by_property(demo_store, "Activity", "status")
    assert "in_progress" in buckets
    assert sum(len(v) for v in buckets.values()) == len(demo_store.nodes_of_type("Activity"))


def test_cardinality_check_does_not_rescan_the_whole_edge_type(empty_store, monkeypatch):
    """Guards the bulk-import path against going quadratic again.

    The store must hand the cardinality check only the edges incident on the new
    edge's own endpoints. Asserting on the *size of that candidate set* is exact
    and machine-independent, unlike a wall-clock budget.
    """
    from setm.graph import store as store_module

    inspected: list[int] = []
    original = store_module.cardinality_conflict

    def counting(ontology, candidate, existing):
        existing = list(existing)
        inspected.append(len(existing))
        return original(ontology, candidate, existing)

    monkeypatch.setattr(store_module, "cardinality_conflict", counting)

    # One milestone with many activities delivering at it: DELIVERS_AT is
    # many_to_one, so a naive implementation would scan every prior edge.
    empty_store.add_node("Milestone", {"name": "PDR"}, node_id="ms")
    for index in range(300):
        empty_store.add_node("Activity", {"name": f"A{index}"}, node_id=f"a{index}")
        empty_store.add_edge("DELIVERS_AT", f"a{index}", "ms")

    assert len(inspected) == 300
    # Each activity has at most one outgoing DELIVERS_AT, so the candidate set
    # never grows with the number of edges already on the milestone.
    assert max(inspected) <= 1


def test_cardinality_still_enforced_at_scale(empty_store):
    empty_store.add_node("Person", {"name": "Owner"}, node_id="p1")
    empty_store.add_node("Person", {"name": "Other"}, node_id="p2")
    for index in range(200):
        empty_store.add_node("Activity", {"name": f"A{index}"}, node_id=f"a{index}")
        empty_store.add_edge("RESPONSIBLE_FOR", "p1", f"a{index}")

    with pytest.raises(ValidationError, match="one_to_many"):
        empty_store.add_edge("RESPONSIBLE_FOR", "p2", "a150")
    assert empty_store.edge_count == 200
