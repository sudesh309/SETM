"""Systems-engineering KPIs computed from the graph.

The engine is ontology-driven: it finds the "activity", "objective" and
"milestone" concepts through the ``roles`` map the ontology declares, so a
programme that renames its vocabulary keeps working without code changes. Any
role that is absent simply makes the dependent KPI report ``available: false``
instead of throwing.

Every KPI carries ``value``, ``target`` and a ``band`` (good / watch / poor) so
the dashboard can colour it, and ``detail`` naming the offending elements, so a
chief engineer can go from a red number to the specific gap in one click.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from ..graph.query import completeness, cycles, orphans
from ..graph.store import GraphStore

#: KPI direction: is a higher number better?
_BANDS = {
    "higher_better": lambda value, target: "good" if value >= target else ("watch" if value >= target * 0.75 else "poor"),
    "lower_better": lambda value, target: "good" if value <= target else ("watch" if value <= target * 1.5 else "poor"),
}


def _kpi(
    kpi_id: str,
    name: str,
    value: float | None,
    *,
    unit: str = "%",
    target: float | None = None,
    direction: str = "higher_better",
    detail: Any = None,
    description: str = "",
    available: bool = True,
) -> dict[str, Any]:
    band = "unknown"
    if available and value is not None and target is not None:
        band = _BANDS[direction](value, target)
    return {
        "id": kpi_id,
        "name": name,
        "value": None if value is None else round(value, 2),
        "unit": unit,
        "target": target,
        "direction": direction,
        "band": band,
        "description": description,
        "detail": detail if detail is not None else {},
        "available": available,
    }


def _percentage(part: int, whole: int) -> float:
    return 100.0 * part / whole if whole else 0.0


#: High first: a gap list should lead with what the programme said matters most.
WEIGHT_ORDER = {"high": 0, "medium": 1, "low": 2}
DEFAULT_WEIGHT = "high"


def element_weight(ontology: Any, element: Any) -> str:
    """The weight of a node or edge, falling back to the ontology's default."""
    prop = ontology.role("weight_property", "weight")
    value = element.properties.get(prop)
    return str(value) if value in WEIGHT_ORDER else DEFAULT_WEIGHT


def _by_weight(ontology: Any, nodes: list[Any]) -> list[Any]:
    return sorted(nodes, key=lambda n: (WEIGHT_ORDER[element_weight(ontology, n)], n.label))


def weight_breakdown(store: GraphStore) -> dict[str, dict[str, int]]:
    """How the graph is distributed across low/medium/high, for elements and relations."""
    ontology = store.ontology
    nodes: dict[str, int] = {}
    edges: dict[str, int] = {}
    for node in store.nodes():
        key = element_weight(ontology, node)
        nodes[key] = nodes.get(key, 0) + 1
    for edge in store.edges():
        key = element_weight(ontology, edge)
        edges[key] = edges.get(key, 0) + 1
    order = list(WEIGHT_ORDER)
    return {
        "elements": {k: nodes.get(k, 0) for k in order},
        "relations": {k: edges.get(k, 0) for k in order},
    }


def compute_kpis(store: GraphStore, *, targets: dict[str, float] | None = None) -> dict[str, Any]:
    """Full KPI report: coverage, traceability, ownership, milestone readiness."""
    ontology = store.ontology
    targets = {**DEFAULT_TARGETS, **(targets or {})}
    kpis: list[dict[str, Any]] = []

    activity_type = ontology.node_role("activity")
    objective_type = ontology.node_role("objective")
    milestone_type = ontology.node_role("milestone")
    person_type = ontology.node_role("person")
    work_package_type = ontology.node_role("work_package")
    process_type = ontology.node_role("se_process")
    requirement_type = ontology.node_role("requirement")

    supports = ontology.edge_role("supports_objective")
    responsible = ontology.edge_role("responsible")
    delivers_at = ontology.edge_role("delivers_at")
    implements_process = ontology.edge_role("implements_process")
    verifies = ontology.edge_role("verifies")
    contains = ontology.edge_role("contains")
    status_property = ontology.role("status_property", "status")

    activities = store.nodes_of_type(activity_type) if activity_type else []
    # Completeness is the most expensive thing here and three KPIs plus the
    # work-package breakdown need it, so it is computed once and shared.
    completeness_by_id = {a.id: completeness(store, a.id) for a in activities}

    # -- 1. Why: objectives actually supported by work ----------------------
    if objective_type and supports:
        objectives = store.nodes_of_type(objective_type)
        unsupported = [o for o in objectives if not store.in_edges(o.id, [supports])]
        kpis.append(
            _kpi(
                "objective_coverage",
                "Objectives covered by activities",
                _percentage(len(objectives) - len(unsupported), len(objectives)),
                target=targets["objective_coverage"],
                description="Share of project objectives with at least one activity declared to support them.",
                detail={"total": len(objectives), "uncovered": [_ref(o, ("weight",)) for o in _by_weight(ontology, unsupported)]},
            )
        )
    else:
        kpis.append(_kpi("objective_coverage", "Objectives covered by activities", None, available=False))

    # -- 2. Who: every activity has a responsible engineer ------------------
    if activities and responsible:
        unassigned = [a for a in activities if not store.in_edges(a.id, [responsible])]
        kpis.append(
            _kpi(
                "activity_ownership",
                "Activities with a named owner",
                _percentage(len(activities) - len(unassigned), len(activities)),
                target=targets["activity_ownership"],
                description="Share of activities with a responsible engineer assigned.",
                detail={"total": len(activities), "unassigned": [_ref(a, ("weight",)) for a in _by_weight(ontology, unassigned)]},
            )
        )
    else:
        kpis.append(_kpi("activity_ownership", "Activities with a named owner", None, available=False))

    # -- 3. When: every activity lands on a milestone -----------------------
    if activities and delivers_at:
        unscheduled = [a for a in activities if not store.out_edges(a.id, [delivers_at])]
        kpis.append(
            _kpi(
                "milestone_anchoring",
                "Activities anchored to a milestone",
                _percentage(len(activities) - len(unscheduled), len(activities)),
                target=targets["milestone_anchoring"],
                description="Share of activities whose delivery point is tied to a programme milestone.",
                detail={"total": len(activities), "unanchored": [_ref(a, ("weight",)) for a in _by_weight(ontology, unscheduled)]},
            )
        )
    else:
        kpis.append(_kpi("milestone_anchoring", "Activities anchored to a milestone", None, available=False))

    # -- 4. How: process discipline -----------------------------------------
    if activities and implements_process:
        without_process = [a for a in activities if not store.out_edges(a.id, [implements_process])]
        kpis.append(
            _kpi(
                "process_linkage",
                "Activities linked to an SE process",
                _percentage(len(activities) - len(without_process), len(activities)),
                target=targets["process_linkage"],
                description="Share of activities traced to a declared systems-engineering process.",
                detail={"total": len(activities), "unlinked": [_ref(a, ("weight",)) for a in _by_weight(ontology, without_process)]},
            )
        )
        if process_type:
            processes = store.nodes_of_type(process_type)
            unused = [p for p in processes if not store.in_edges(p.id, [implements_process])]
            kpis.append(
                _kpi(
                    "process_utilisation",
                    "Declared processes in use",
                    _percentage(len(processes) - len(unused), len(processes)),
                    target=targets["process_utilisation"],
                    description="Processes the project claims to follow that have at least one activity behind them.",
                    detail={"total": len(processes), "unused": [_ref(p, ("weight",)) for p in _by_weight(ontology, unused)]},
                )
            )
    else:
        kpis.append(_kpi("process_linkage", "Activities linked to an SE process", None, available=False))

    # -- 5. Verification coverage -------------------------------------------
    if requirement_type and verifies:
        requirements = store.nodes_of_type(requirement_type)
        unverified = [r for r in requirements if not store.in_edges(r.id, [verifies])]
        kpis.append(
            _kpi(
                "verification_coverage",
                "Requirements with a verification activity",
                _percentage(len(requirements) - len(unverified), len(requirements)),
                target=targets["verification_coverage"],
                description="Share of requirements that some activity is committed to verifying.",
                detail={"total": len(requirements), "unverified": [_ref(r, ("weight",)) for r in _by_weight(ontology, unverified)[:100]]},
            )
        )

    # -- 6. Tools: the engineering chain ------------------------------------
    tool_type = ontology.node_role("tool")
    uses_tool = ontology.edge_role("uses_tool")
    if activities and tool_type and uses_tool:
        without_tool = [a for a in activities if not store.out_edges(a.id, [uses_tool])]
        kpis.append(
            _kpi(
                "tool_linkage",
                "Activities linked to a tool",
                _percentage(len(activities) - len(without_tool), len(activities)),
                target=targets["tool_linkage"],
                description="Share of activities that name the tool the work is actually done in.",
                detail={
                    "total": len(activities),
                    "unlinked": [_ref(a, ("weight",)) for a in _by_weight(ontology, without_tool)],
                },
            )
        )

        tools_in_use = [t for t in store.nodes_of_type(tool_type) if store.in_edges(t.id, [uses_tool])]
        cleared = {"qualified", "not_required", "waived"}
        outstanding = [
            t for t in tools_in_use if str(t.properties.get("qualification_status") or "") not in cleared
        ]
        kpis.append(
            _kpi(
                "tool_qualification",
                "Tools in use with qualification settled",
                _percentage(len(tools_in_use) - len(outstanding), len(tools_in_use)),
                target=targets["tool_qualification"],
                description=(
                    "Tools an activity depends on whose qualification is decided - qualified, "
                    "waived, or explicitly not required. An open question here becomes a finding "
                    "when the authority asks how the evidence was produced."
                ),
                detail={
                    "total": len(tools_in_use),
                    "unlinked": [_ref(t, ("weight", "qualification_status")) for t in _by_weight(ontology, outstanding)],
                },
            )
        )

        exchanges = ontology.edge_role("exchanges_data")
        if exchanges:
            hops = store.edges_of_type(exchanges)
            manual = [h for h in hops if not h.properties.get("automated")]
            kpis.append(
                _kpi(
                    "manual_tool_handovers",
                    "Manual hand-overs in the tool chain",
                    float(len(manual)),
                    unit="",
                    target=targets["manual_tool_handovers"],
                    direction="lower_better",
                    description=(
                        "Tool-to-tool links that are not automated. Every one is a place data is "
                        "re-keyed, and re-keying is where the model and the analysis drift apart."
                    ),
                    detail={
                        "total": len(hops),
                        "handovers": [
                            {
                                "edge_id": h.id,
                                "from": store.node(h.source).label,
                                "to": store.node(h.target).label,
                                "format": h.properties.get("exchange_format", ""),
                            }
                            for h in manual
                        ],
                    },
                )
            )

    # -- 7. Weight: are the elements that matter actually traced? -----------
    if activities:
        heavy = [a for a in activities if element_weight(ontology, a) == "high"]
        if heavy:
            incomplete = [a for a in heavy if completeness_by_id[a.id]["score"] < 1.0]
            kpis.append(
                _kpi(
                    "high_weight_traceability",
                    "High-weight activities fully traced",
                    _percentage(len(heavy) - len(incomplete), len(heavy)),
                    target=targets["high_weight_traceability"],
                    description=(
                        "Of the activities the programme marked high weight, the share that can "
                        "answer every who/when/why/how question. Weight is what makes an average "
                        "actionable: a gap here is one the programme itself called important."
                    ),
                    detail={
                        "total": len(heavy),
                        "unlinked": [
                            {**_ref(a, ("weight",)), "missing": sorted(completeness_by_id[a.id]["missing"])}
                            for a in _by_weight(ontology, incomplete)
                        ],
                    },
                )
            )

    # -- 8. Overall traceability completeness -------------------------------
    if activities:
        scores = [completeness_by_id[a.id]["score"] for a in activities]
        kpis.append(
            _kpi(
                "traceability_completeness",
                "Traceability completeness",
                100.0 * sum(scores) / len(scores),
                target=targets["traceability_completeness"],
                description="Average share of the who/when/why/how questions each activity can answer.",
                detail={"activities_scored": len(scores)},
            )
        )

    # -- 9. Hygiene: orphans and circular dependencies ----------------------
    orphan_list = orphans(store)
    kpis.append(
        _kpi(
            "orphan_rate",
            "Disconnected elements",
            _percentage(len(orphan_list), store.node_count),
            target=targets["orphan_rate"],
            direction="lower_better",
            description="Elements with no relation at all - usually an import gap or an abandoned draft.",
            detail={"count": len(orphan_list), "elements": orphan_list[:50]},
        )
    )
    dependency_edge = ontology.edge_role("depends_on")
    found_cycles = cycles(store, [dependency_edge] if dependency_edge else None, limit=10)
    kpis.append(
        _kpi(
            "dependency_cycles",
            "Circular dependencies",
            float(len(found_cycles)),
            unit="",
            target=targets["dependency_cycles"],
            direction="lower_better",
            description="Loops in the activity dependency network, which make a plan unschedulable.",
            detail={"cycles": found_cycles},
        )
    )

    report: dict[str, Any] = {
        "project": store.project.to_dict(),
        "generated_from_revision": store.revision,
        "kpis": kpis,
        "health_score": _health_score(kpis),
        "breakdowns": {
            "by_milestone": milestone_load(store),
            # Bounded here rather than in workload(): a report is a summary,
            # whereas the workload board has to list everyone to stay editable.
            "by_person": workload(store, top=50),
            "by_work_package": work_package_health(store, completeness_by_id=completeness_by_id),
            "by_status": status_breakdown(store, activity_type, status_property),
            "by_type": store.stats()["nodes_by_type"],
            "by_weight": weight_breakdown(store),
            "by_tool": tool_usage(store),
        },
    }
    # Unused-variable guards for roles reported only in breakdowns.
    report["roles_resolved"] = {
        "activity": activity_type,
        "objective": objective_type,
        "milestone": milestone_type,
        "person": person_type,
        "work_package": work_package_type,
        "requirement": requirement_type,
        "contains": contains,
    }
    return report


#: Properties carried on board rows so the UI can show status without extra calls.
_BOARD_PROPERTIES = (
    "status", "activity_type", "deliverable_type", "maturity", "progress_percent", "weight",
)

DEFAULT_TARGETS: dict[str, float] = {
    "objective_coverage": 100.0,
    "activity_ownership": 95.0,
    "milestone_anchoring": 90.0,
    "process_linkage": 80.0,
    "process_utilisation": 70.0,
    "verification_coverage": 90.0,
    "traceability_completeness": 80.0,
    "tool_linkage": 80.0,
    "tool_qualification": 100.0,
    "manual_tool_handovers": 0.0,
    "high_weight_traceability": 95.0,
    "orphan_rate": 5.0,
    "dependency_cycles": 0.0,
}


def _ref(node: Any, include: Iterable[str] = ()) -> dict[str, Any]:
    """A compact element reference for KPI payloads.

    ``include`` names properties worth carrying so a board can render a status
    column without a second request per row.
    """
    ref = {"id": node.id, "type": node.type, "label": node.label}
    carried = {name: node.properties.get(name) for name in include if node.properties.get(name) is not None}
    if carried:
        ref["properties"] = carried
    return ref


def _health_score(kpis: list[dict[str, Any]]) -> dict[str, Any]:
    """Composite score: the mean of each available KPI's attainment against target."""
    scored = []
    for kpi in kpis:
        if not kpi["available"] or kpi["value"] is None or kpi["target"] is None:
            continue
        if kpi["direction"] == "higher_better":
            attainment = kpi["value"] / kpi["target"] if kpi["target"] else 1.0
        else:
            headroom = max(kpi["target"], 1.0)
            attainment = max(0.0, 1.0 - (kpi["value"] - kpi["target"]) / headroom) if kpi["value"] > kpi["target"] else 1.0
        scored.append(min(1.0, attainment))
    if not scored:
        return {"value": None, "band": "unknown", "contributing_kpis": 0}
    value = round(100.0 * sum(scored) / len(scored), 1)
    return {
        "value": value,
        "band": "good" if value >= 85 else ("watch" if value >= 65 else "poor"),
        "contributing_kpis": len(scored),
    }


def milestone_load(store: GraphStore) -> list[dict[str, Any]]:
    """Activities due at each milestone, with their status mix.

    This is the "when" view: SETM tracks commitment to programme gates, not dates.
    """
    ontology = store.ontology
    milestone_type = ontology.node_role("milestone")
    delivers_at = ontology.edge_role("delivers_at")
    status_property = ontology.role("status_property", "status")
    done_values = {v.strip().lower() for v in ontology.role("done_status_values", "done,completed,closed").split(",")}
    if not milestone_type or not delivers_at:
        return []

    activity_type = ontology.node_role("activity")
    deliverable_type = ontology.node_role("deliverable")
    milestones = store.nodes_of_type(milestone_type)
    milestones.sort(key=lambda n: (_as_int(n.properties.get(ontology.role("sequence_property", "sequence"))), n.label))

    out = []
    for milestone in milestones:
        committed = [store.node(e.source) for e in store.in_edges(milestone.id, [delivers_at])]
        activities = [n for n in committed if n.type == activity_type] if activity_type else committed
        deliverables = [n for n in committed if n.type == deliverable_type] if deliverable_type else []
        statuses: dict[str, int] = {}
        for item in committed:
            key = str(item.properties.get(status_property) or "unset")
            statuses[key] = statuses.get(key, 0) + 1
        # Readiness is judged on activities: deliverables follow from them.
        done = sum(
            1 for a in activities if str(a.properties.get(status_property) or "").lower() in done_values
        )
        out.append(
            {
                "id": milestone.id,
                "label": milestone.label,
                "gate": milestone.properties.get(ontology.role("gate_property", "gate"), ""),
                "sequence": _as_int(milestone.properties.get(ontology.role("sequence_property", "sequence"))),
                "activity_count": len(activities),
                "deliverable_count": len(deliverables),
                "status_mix": statuses,
                "readiness_percent": round(_percentage(done, len(activities)), 1),
                "activities": [_ref(a, _BOARD_PROPERTIES) for a in activities],
                "deliverables": [_ref(d, _BOARD_PROPERTIES) for d in deliverables],
            }
        )
    return out


def workload(store: GraphStore, *, top: int | None = None) -> list[dict[str, Any]]:
    """Who is carrying what: activity count per person, by milestone.

    Uncapped by default, like the other board sections: the workload page is
    where a person is edited or removed, so truncating it would put everyone
    past the cut-off out of reach. ``top`` is for callers that want a bounded
    payload -- the KPI report does.
    """
    ontology = store.ontology
    person_type = ontology.node_role("person")
    responsible = ontology.edge_role("responsible")
    delivers_at = ontology.edge_role("delivers_at")
    if not person_type or not responsible:
        return []

    out = []
    for person in store.nodes_of_type(person_type):
        owned = [store.node(e.target) for e in store.out_edges(person.id, [responsible])]
        per_milestone: dict[str, int] = {}
        if delivers_at:
            for activity in owned:
                for edge in store.out_edges(activity.id, [delivers_at]):
                    label = store.node(edge.target).label
                    per_milestone[label] = per_milestone.get(label, 0) + 1
        out.append(
            {
                "id": person.id,
                "label": person.label,
                "role": person.properties.get("role", ""),
                "organisation": person.properties.get("organisation", ""),
                "activity_count": len(owned),
                "by_milestone": per_milestone,
                "activities": [_ref(a, _BOARD_PROPERTIES) for a in owned],
            }
        )
    out.sort(key=lambda item: -item["activity_count"])
    return out[:top] if top else out


def work_package_health(
    store: GraphStore, *, completeness_by_id: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Per work package: how much is done, and how well it is traced.

    ``completeness_by_id`` lets the full report reuse scores it already
    computed; called on its own the function works them out itself.
    """
    ontology = store.ontology
    scores_for = completeness_by_id if completeness_by_id is not None else {}
    work_package_type = ontology.node_role("work_package")
    contains = ontology.edge_role("contains")
    status_property = ontology.role("status_property", "status")
    done_values = {v.strip().lower() for v in ontology.role("done_status_values", "done,completed,closed").split(",")}
    if not work_package_type or not contains:
        return []

    out = []
    for package in store.nodes_of_type(work_package_type):
        activities = [store.node(e.target) for e in store.out_edges(package.id, [contains])]
        done = [
            a for a in activities if str(a.properties.get(status_property) or "").lower() in done_values
        ]
        scores = [
            (scores_for.get(a.id) or completeness(store, a.id))["score"] for a in activities
        ]
        leader = ""
        led_by = ontology.edge_role("led_by")
        if led_by:
            leaders = store.out_edges(package.id, [led_by])
            leader = store.node(leaders[0].target).label if leaders else ""
        out.append(
            {
                "id": package.id,
                "label": package.label,
                "wbs": package.properties.get(ontology.role("wbs_property", "wbs_code"), ""),
                "leader": leader,
                "activity_count": len(activities),
                "completed": len(done),
                "completion_percent": round(_percentage(len(done), len(activities)), 1),
                "traceability_percent": round(100.0 * sum(scores) / len(scores), 1) if scores else 0.0,
            }
        )
    out.sort(key=lambda item: item["label"])
    return out


def tool_usage(store: GraphStore) -> list[dict[str, Any]]:
    """Each tool with who administers it, what depends on it and where it feeds."""
    ontology = store.ontology
    tool_type = ontology.node_role("tool")
    uses_tool = ontology.edge_role("uses_tool")
    administers = ontology.edge_role("administers")
    exchanges = ontology.edge_role("exchanges_data")
    implemented_by = ontology.edge_role("implemented_by_tool")
    if not tool_type:
        return []

    out = []
    for tool in store.nodes_of_type(tool_type):
        activities = [store.node(e.source) for e in store.in_edges(tool.id, [uses_tool])] if uses_tool else []
        admins = [store.node(e.source).label for e in store.in_edges(tool.id, [administers])] if administers else []
        methods = [store.node(e.source).label for e in store.in_edges(tool.id, [implemented_by])] if implemented_by else []
        downstream, upstream = [], []
        if exchanges:
            downstream = [
                {
                    "tool": store.node(e.target).label,
                    "format": e.properties.get("exchange_format", ""),
                    "automated": bool(e.properties.get("automated")),
                }
                for e in store.out_edges(tool.id, [exchanges])
            ]
            upstream = [store.node(e.source).label for e in store.in_edges(tool.id, [exchanges])]
        out.append(
            {
                "id": tool.id,
                "label": tool.label,
                "tool_type": tool.properties.get("tool_type", ""),
                "vendor": tool.properties.get("vendor", ""),
                "version": tool.properties.get("version", ""),
                "licence_model": tool.properties.get("licence_model", ""),
                "licence_count": tool.properties.get("licence_count"),
                "qualification_status": tool.properties.get("qualification_status", ""),
                "weight": element_weight(ontology, tool),
                "activity_count": len(activities),
                "activities": [_ref(a, _BOARD_PROPERTIES) for a in activities],
                "administrators": admins,
                "methods": methods,
                "feeds": downstream,
                "fed_by": upstream,
            }
        )
    out.sort(key=lambda item: -item["activity_count"])
    return out


def status_breakdown(store: GraphStore, type_name: str, status_property: str) -> dict[str, int]:
    if not type_name:
        return {}
    counts: dict[str, int] = {}
    for node in store.nodes_of_type(type_name):
        key = str(node.properties.get(status_property) or "unset")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 9999


#: Exposed so the API can list what is computable without running the whole report.
KPI_CATALOGUE: dict[str, Callable[..., Any]] = {
    "report": compute_kpis,
    "milestone_load": milestone_load,
    "workload": workload,
    "work_package_health": work_package_health,
    "tool_usage": tool_usage,
}
