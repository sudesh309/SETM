"""KPI computation and application telemetry."""

from __future__ import annotations

from setm.kpi.metrics import compute_kpis, milestone_load, work_package_health, workload
from setm.kpi.telemetry import Telemetry


def kpi_by_id(report, kpi_id):
    return next(k for k in report["kpis"] if k["id"] == kpi_id)


def test_demo_project_is_healthy(demo_store):
    report = compute_kpis(demo_store)
    assert report["health_score"]["band"] == "good"
    assert kpi_by_id(report, "objective_coverage")["value"] == 100.0
    assert kpi_by_id(report, "dependency_cycles")["value"] == 0


def test_adding_an_untraced_activity_moves_the_numbers(demo_store):
    before = compute_kpis(demo_store)
    demo_store.add_node("Activity", {"name": "Unplanned rework"}, node_id="act.rogue")
    after = compute_kpis(demo_store)

    assert kpi_by_id(after, "activity_ownership")["value"] < kpi_by_id(before, "activity_ownership")["value"]
    assert kpi_by_id(after, "milestone_anchoring")["value"] < kpi_by_id(before, "milestone_anchoring")["value"]
    gaps = {g["id"] for g in kpi_by_id(after, "activity_ownership")["detail"]["unassigned"]}
    assert "act.rogue" in gaps


def test_orphan_rate_uses_lower_is_better_banding(demo_store):
    demo_store.add_node("Method", {"name": "Unused method"}, node_id="mth.unused")
    report = compute_kpis(demo_store)
    orphan = kpi_by_id(report, "orphan_rate")
    assert orphan["direction"] == "lower_better"
    assert orphan["detail"]["count"] == 1


def test_kpis_report_unavailable_rather_than_failing(ontology):
    """An ontology with no roles must still produce a report."""
    from setm.graph.store import GraphStore
    from setm.model import GraphDocument
    from setm.ontology.loader import build_ontology

    bare = build_ontology({
        "ontology": {"id": "bare", "version": "1", "namespace": "https://b/#"},
        "node_types": {"Item": {"properties": {"name": {"type": "string"}}}},
        "edge_types": {"LINKS": {"domain": ["Item"], "range": ["Item"]}},
    })
    store = GraphStore(GraphDocument(), bare)
    report = compute_kpis(store)
    unavailable = [k for k in report["kpis"] if not k["available"]]
    assert unavailable
    assert report["breakdowns"]["by_milestone"] == []


def test_milestone_load_is_ordered_and_split_by_kind(demo_store):
    load = milestone_load(demo_store)
    assert [m["gate"] for m in load] == ["SRR", "PDR", "CDR", "TRR", "QR"]
    srr = load[0]
    assert srr["readiness_percent"] == 100.0
    assert srr["deliverable_count"] >= 1
    # Readiness counts activities only, so it is not diluted by deliverables.
    assert all(a["type"] == "Activity" for a in srr["activities"])


def test_milestone_rows_carry_status_for_the_board(demo_store):
    pdr = next(m for m in milestone_load(demo_store) if m["gate"] == "PDR")
    assert any(a.get("properties", {}).get("status") for a in pdr["activities"])


def test_workload_is_sorted_by_load(demo_store):
    people = workload(demo_store)
    counts = [p["activity_count"] for p in people]
    assert counts == sorted(counts, reverse=True)
    assert people[0]["by_milestone"]


def test_work_package_health_reports_completion(demo_store):
    packages = work_package_health(demo_store)
    assert packages
    wp1000 = next(p for p in packages if p["wbs"] == "1000")
    assert wp1000["leader"] == "R. Mehta"
    assert 0 <= wp1000["completion_percent"] <= 100
    assert wp1000["activity_count"] > 0


def test_health_score_degrades_with_the_graph(demo_store):
    before = compute_kpis(demo_store)["health_score"]["value"]
    for index in range(6):
        demo_store.add_node("Activity", {"name": f"Untraced {index}"}, node_id=f"act.untraced{index}")
    after = compute_kpis(demo_store)["health_score"]["value"]
    assert after < before


# -- telemetry --------------------------------------------------------------

def test_timer_percentiles():
    telemetry = Telemetry()
    for value in range(1, 101):
        telemetry.observe("op", float(value))
    stats = telemetry.snapshot()["operations"]["op"]
    assert stats["count"] == 100
    assert stats["min_ms"] == 1.0
    assert stats["max_ms"] == 100.0
    assert 45 <= stats["p50_ms"] <= 55
    assert stats["p95_ms"] >= stats["p50_ms"]


def test_track_records_failures():
    telemetry = Telemetry()
    try:
        with telemetry.track("risky"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    stats = telemetry.snapshot()["operations"]["risky"]
    assert stats["errors"] == 1
    assert stats["error_rate"] == 1.0


def test_labels_separate_series():
    telemetry = Telemetry()
    telemetry.increment("http.requests", route="a")
    telemetry.increment("http.requests", route="b")
    telemetry.increment("http.requests", route="a")
    counters = telemetry.snapshot()["counters"]
    assert counters["http.requests[route=a]"] == 2
    assert counters["http.requests[route=b]"] == 1


def test_prometheus_format_is_parseable():
    telemetry = Telemetry()
    telemetry.increment("http.requests", route="health")
    telemetry.gauge("graph.nodes", 42)
    telemetry.observe("http.request", 12.5, route="health")
    text = telemetry.prometheus()
    lines = [line for line in text.splitlines() if line.strip()]
    assert all(len(line.rsplit(" ", 1)) == 2 for line in lines)
    assert 'setm_http_requests{route="health"} 1' in text
    assert "setm_graph_nodes 42.0" in text
    assert "setm_uptime_seconds" in text


def test_reset_clears_everything():
    telemetry = Telemetry()
    telemetry.increment("x")
    telemetry.reset()
    assert telemetry.snapshot()["counters"] == {}


# -- tools ------------------------------------------------------------------

def test_tool_kpis_are_computed(demo_store):
    report = compute_kpis(demo_store)
    linkage = kpi_by_id(report, "tool_linkage")
    assert linkage["available"] and linkage["value"] > 50

    qualification = kpi_by_id(report, "tool_qualification")
    # Two demo tools are mid-qualification, so this must not read as clean.
    assert qualification["value"] < 100
    outstanding = {t["label"] for t in qualification["detail"]["unlinked"]}
    assert "Zemax OpticStudio" in outstanding


def test_manual_tool_handovers_are_counted_and_named(demo_store):
    kpi = kpi_by_id(compute_kpis(demo_store), "manual_tool_handovers")
    assert kpi["direction"] == "lower_better"
    assert kpi["value"] == len(kpi["detail"]["handovers"])
    assert all({"from", "to", "format"} <= set(h) for h in kpi["detail"]["handovers"])


def test_tool_usage_reports_the_chain(demo_store):
    from setm.kpi.metrics import tool_usage

    tools = tool_usage(demo_store)
    assert tools
    assert [t["activity_count"] for t in tools] == sorted([t["activity_count"] for t in tools], reverse=True)
    zemax = next(t for t in tools if t["label"] == "Zemax OpticStudio")
    assert zemax["administrators"] == ["C. Laurent"]
    assert zemax["qualification_status"] == "in_qualification"
    assert any(hop["tool"] == "MATLAB / Simulink" for hop in zemax["feeds"])


def test_adding_an_activity_without_a_tool_moves_tool_linkage(demo_store):
    before = kpi_by_id(compute_kpis(demo_store), "tool_linkage")["value"]
    demo_store.add_node("Activity", {"name": "Toolless work"}, node_id="act.notool")
    after = kpi_by_id(compute_kpis(demo_store), "tool_linkage")
    assert after["value"] < before
    assert "act.notool" in {g["id"] for g in after["detail"]["unlinked"]}


# -- weighting --------------------------------------------------------------

def test_weight_breakdown_covers_elements_and_relations(demo_store):
    from setm.kpi.metrics import weight_breakdown

    breakdown = weight_breakdown(demo_store)
    assert set(breakdown) == {"elements", "relations"}
    assert list(breakdown["elements"]) == ["high", "medium", "low"]
    assert sum(breakdown["elements"].values()) == demo_store.node_count
    assert sum(breakdown["relations"].values()) == demo_store.edge_count


def test_unset_weight_counts_as_high(empty_store):
    from setm.kpi.metrics import element_weight, weight_breakdown

    node = empty_store.add_node("Activity", {"name": "x"})
    node.properties.pop("weight")  # simulate data imported before weighting existed
    assert element_weight(empty_store.ontology, node) == "high"
    assert weight_breakdown(empty_store)["elements"]["high"] == 1


def test_high_weight_traceability_ignores_low_weight_gaps(demo_store):
    before = kpi_by_id(compute_kpis(demo_store), "high_weight_traceability")["value"]
    demo_store.add_node("Activity", {"name": "Minor chore", "weight": "low"}, node_id="act.minor")
    assert kpi_by_id(compute_kpis(demo_store), "high_weight_traceability")["value"] == before

    demo_store.add_node("Activity", {"name": "Major gap", "weight": "high"}, node_id="act.major")
    after = kpi_by_id(compute_kpis(demo_store), "high_weight_traceability")
    assert after["value"] < before
    assert "act.major" in {g["id"] for g in after["detail"]["unlinked"]}
    assert "who" in next(g for g in after["detail"]["unlinked"] if g["id"] == "act.major")["missing"]


def test_gap_lists_lead_with_the_heaviest_elements(demo_store):
    for index, weight in enumerate(["low", "high", "medium"]):
        demo_store.add_node("Activity", {"name": f"Gap {index}", "weight": weight}, node_id=f"act.gap{index}")
    gaps = kpi_by_id(compute_kpis(demo_store), "activity_ownership")["detail"]["unassigned"]
    weights = [g["properties"]["weight"] for g in gaps]
    assert weights == ["high", "medium", "low"]


def test_telemetry_process_stats_survive_a_posix_only_resource_module(monkeypatch):
    """Windows has no `resource` module; telemetry must not depend on it being present.

    setm.kpi.telemetry sets `resource = None` at import time when the import
    fails, so this simulates that state directly rather than re-importing
    the module under a faked builtins.__import__ (which is fragile across
    pytest's own import machinery).
    """
    # setm.kpi's __init__ re-exports a `telemetry` singleton that shadows the
    # submodule of the same name, so `from setm.kpi import telemetry` would
    # hand back that instance rather than the module. Go through importlib
    # (which reads sys.modules directly) to get the actual module instead.
    import importlib

    telemetry_module = importlib.import_module("setm.kpi.telemetry")
    monkeypatch.setattr(telemetry_module, "resource", None)
    stats = telemetry_module.Telemetry().process_stats()
    assert stats["pid"] > 0
    assert isinstance(stats["cpu_user_seconds"], float)
    assert isinstance(stats["cpu_system_seconds"], float)
    # No POSIX resource module and (in this test process) not Windows either,
    # so peak memory is honestly reported as unavailable rather than crashing.
    assert stats["max_rss_mb"] is None or isinstance(stats["max_rss_mb"], float)


def test_cpu_times_uses_the_portable_os_times_call():
    from setm.kpi.telemetry import Telemetry

    user, system = Telemetry._cpu_times()
    assert user >= 0.0
    assert system >= 0.0
