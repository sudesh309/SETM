"""The modification-programme worked example builds a valid, fully traced graph."""

from __future__ import annotations

from setm.graph.query import orphans
from setm.kpi.metrics import compute_kpis


def test_builds_without_orphans(modification_store):
    assert modification_store.node_count > 0
    assert orphans(modification_store) == []


def test_uses_assumption_and_parameter(modification_store):
    assert modification_store.nodes_of_type("Assumption")
    assert modification_store.nodes_of_type("Parameter")


def test_parameter_link_connects_parameters_only(modification_store):
    edges = modification_store.edges_of_type("PARAMETER_LINK")
    assert edges
    for edge in edges:
        assert modification_store.node(edge.source).type == "Parameter"
        assert modification_store.node(edge.target).type == "Parameter"


def test_assumptions_underlie_something(modification_store):
    edges = modification_store.edges_of_type("UNDERLIES")
    assert edges
    for edge in edges:
        assert modification_store.node(edge.source).type == "Assumption"


def test_architecture_baseline_deliverables_apply_to_the_system_tree(modification_store):
    baseline = {n.id for n in modification_store.nodes_of_type("Deliverable") if n.id in ("del.oad", "del.opd", "del.osd")}
    assert baseline == {"del.oad", "del.opd", "del.osd"}
    applies_to = [e for e in modification_store.edges_of_type("APPLIES_TO") if e.source in baseline]
    assert applies_to

    part_of = modification_store.edges_of_type("PART_OF")
    assert len(part_of) >= 8  # a real tree, not a flat list


def test_kpi_report_computes_without_raising(modification_store):
    report = compute_kpis(modification_store)
    assert report["health_score"]["value"] is not None
