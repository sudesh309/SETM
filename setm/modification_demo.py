"""A second worked example: an in-service aircraft modification programme.

``setm demo --example modification`` builds this graph. Where ``demo.py`` shows a
new-development programme (build something that doesn't exist yet), this one shows
the other common shape of aerospace SE work: a **complex modification** on an
in-service commercial aircraft, driven by two concurrent workstreams that keep
tripping over each other - obsolescence (parts going out of production, needing
requalification) and performance (a fuel-burn improvement retrofit) - governed by
a shared architecture baseline (OAD/OPD/OSD) that both trace back to.

Aircraft, programme and organisation are entirely fictional; no real manufacturer,
airline or aircraft family is referenced anywhere.
"""

from __future__ import annotations

from typing import Any

from .graph.store import GraphStore
from .model import GraphDocument, ProjectInfo
from .ontology.schema import Ontology

PROJECT = ProjectInfo(
    id="voyager-renew",
    name="Voyager LR Modification Programme 'RENEW'",
    programme="Voyager LR In-Service Support",
    phase="D",
    description=(
        "Mid-life modification programme for the in-service Voyager LR fleet: retire "
        "diminishing-manufacturing-source (DMSMS) obsolescence in the avionics suite and "
        "deliver a fuel-burn performance improvement retrofit, both governed by a shared "
        "aircraft architecture baseline."
    ),
    chief_engineer="D. Hale",
)

PEOPLE: list[tuple[str, str, str, str]] = [
    ("per.hale", "D. Hale", "chief_engineer", "Systems Engineering"),
    ("per.osei", "K. Osei", "systems_engineer", "Systems Engineering"),
    ("per.bianchi", "L. Bianchi", "work_package_leader", "Avionics & Systems"),
    ("per.farrow", "R. Farrow", "work_package_leader", "Aerodynamics & Propulsion"),
    ("per.nakamura", "S. Nakamura", "verification_engineer", "Certification"),
    ("per.reyes", "A. Reyes", "quality_engineer", "Product Assurance"),
    ("per.voss", "T. Voss", "domain_specialist", "Weight Engineering"),
]

MILESTONES: list[tuple[str, str, str, int, str]] = [
    ("ms.sdr", "Feasibility & Concept Review", "SDR", 10, "Modification concept and architecture baseline agreed."),
    ("ms.pdr", "Preliminary Design Review", "PDR", 20, "Kit design and interfaces frozen, budgets closed."),
    ("ms.cdr", "Critical Design Review", "CDR", 30, "Detailed design complete and verifiable."),
    ("ms.trr", "Ground Test Readiness Review", "TRR", 40, "Requalified LRU and performance kit ready for combined ground test."),
    ("ms.frr", "Fleet Retrofit Readiness Review", "FRR", 50, "Certification evidence complete; fleet embodiment can start."),
]

OBJECTIVES: list[tuple[str, str, str, str, str]] = [
    (
        "obj.dmsms",
        "Retire all identified DMSMS obsolescence risk items",
        "operability",
        "must",
        "Every avionics LRU on the obsolescence watch list has a qualified replacement or a documented last-time-buy by FRR.",
    ),
    (
        "obj.fuelburn",
        "Achieve a fuel-burn reduction at the typical mission profile",
        "performance",
        "must",
        "Flight-test-correlated analysis demonstrates at least 1.5% fuel-burn reduction relative to the pre-modification baseline.",
    ),
    (
        "obj.cost",
        "Keep retrofit-kit non-recurring cost within budget",
        "cost",
        "should",
        "Non-recurring cost within 10% of the approved budget at CDR.",
    ),
    (
        "obj.cert",
        "Certify the modification for fleet-wide retrofit",
        "certification",
        "must",
        "Certification compliance data package accepted by FRR with no open findings.",
    ),
]

SEPROCESSES: list[tuple[str, str, str, str, str]] = [
    ("proc.arch", "Architecture definition", "ARP4754A", "5.3", "technical"),
    ("proc.reqmgmt", "Requirements management", "ARP4754A", "5.2", "technical"),
    ("proc.analysis", "System analysis", "ARP4754A", "5.4", "technical"),
    ("proc.verification", "Verification", "ARP4754A", "6", "technical"),
    ("proc.safety", "Safety assessment", "internal", "PASS-4", "technical_management"),
]

BUSINESS_PROCESSES: list[tuple[str, str, str, str]] = [
    ("bp.reviewgate", "Design review gate procedure", "Chief Engineer Office", "QMS-ENG-014"),
    ("bp.config", "Configuration and change control", "Programme Office", "QMS-CM-003"),
]

TOOLS: list[dict[str, Any]] = [
    {
        "id": "tool.doors",
        "name": "DOORS Next",
        "tool_type": "requirements_management",
        "vendor": "IBM",
        "version": "7.0.2",
        "licence_model": "site_licence",
        "licence_count": 30,
        "qualification_status": "not_required",
        "output_formats": ["ReqIF", "CSV"],
        "admin": "per.osei",
    },
    {
        "id": "tool.catia",
        "name": "CATIA V6",
        "tool_type": "architecture_modelling",
        "vendor": "Dassault Systemes",
        "version": "V6R2023",
        "licence_model": "commercial_floating",
        "licence_count": 15,
        "qualification_status": "not_required",
        "output_formats": ["CATPart", "STEP"],
        "admin": "per.bianchi",
    },
    {
        "id": "tool.matlab",
        "name": "MATLAB / Simulink",
        "tool_type": "analysis",
        "vendor": "MathWorks",
        "version": "R2023b",
        "licence_model": "commercial_floating",
        "licence_count": 20,
        "qualification_status": "not_required",
        "output_formats": ["CSV", "MAT"],
        "admin": "per.farrow",
    },
    {
        "id": "tool.gitlab",
        "name": "GitLab",
        "tool_type": "configuration_management",
        "vendor": "GitLab Inc.",
        "version": "16.x",
        "licence_model": "site_licence",
        "qualification_status": "not_required",
        "output_formats": ["JSON", "Turtle"],
        "admin": "per.osei",
        "weight": "medium",
    },
]

#: Tool chain: which tool hands data to which, and whether the hop is automated.
TOOL_CHAIN: list[tuple[str, str, str, bool]] = [
    ("tool.doors", "tool.catia", "ReqIF", True),
    ("tool.catia", "tool.matlab", "STEP", False),
    ("tool.matlab", "tool.gitlab", "CSV", True),
]

METHOD_TOOLS: list[tuple[str, str]] = [
    ("mth.interface", "tool.catia"),
    ("mth.perf", "tool.matlab"),
]

METHODS: list[tuple[str, str, str, str]] = [
    ("mth.interface", "Interface control analysis", "ICD comparison against the architecture baseline", "CATIA"),
    ("mth.perf", "Performance substantiation analysis", "CFD and flight-test correlation", "MATLAB, Simulink"),
    ("mth.weight", "Weight and balance analysis", "Mass properties tracking against the kit budget", "spreadsheet-based W&B tool"),
]

WORK_PACKAGES: list[tuple[str, str, str, str, float]] = [
    ("wp.avionics", "WP1000 Avionics & Systems Obsolescence Redesign", "1000", "per.bianchi", 210),
    ("wp.perf", "WP2000 Aerodynamic & Propulsion Performance Improvement", "2000", "per.farrow", 260),
    ("wp.weight", "WP3000 Cabin & Structure Weight Reduction", "3000", "per.voss", 120),
    ("wp.cert", "WP4000 Certification & Compliance", "4000", "per.nakamura", 150),
]

#: A genuine PART_OF tree, not a flat list - the "architecture concepts" emphasis.
# id, name, element_level, pbs_code, parent (None for the root)
SYSTEM_ELEMENTS: list[tuple[str, str, str, str, str | None]] = [
    ("sys.aircraft", "Voyager LR airframe", "system_of_systems", "AC", None),
    ("sys.avionics", "Avionics & systems", "system", "AC-10", "sys.aircraft"),
    ("sys.propulsion", "Propulsion system", "system", "AC-20", "sys.aircraft"),
    ("sys.structure", "Airframe & structure", "system", "AC-30", "sys.aircraft"),
    ("sys.cabin", "Cabin systems", "system", "AC-40", "sys.aircraft"),
    ("sys.iface", "Avionics-to-cabin data interface", "interface", "AC-IF-01", "sys.aircraft"),
    ("sys.fmc", "Flight-management LRU", "equipment", "AC-10-01", "sys.avionics"),
    ("sys.nacelle", "Engine nacelle / performance-improvement kit", "equipment", "AC-20-01", "sys.propulsion"),
    ("sys.wingtip", "Wingtip device", "subsystem", "AC-30-01", "sys.structure"),
    ("sys.galley", "Cabin galley assembly", "equipment", "AC-40-01", "sys.cabin"),
]

REQUIREMENTS: list[tuple[str, str, str, str, str, str]] = [
    (
        "req.dmsms", "VOY-REQ-0010",
        "The replacement flight-management LRU shall be form-fit-function equivalent to the obsolete unit.",
        "subsystem", "inspection", "sys.fmc",
    ),
    (
        "req.fuelburn", "VOY-REQ-0020",
        "The modified aircraft shall demonstrate a fuel-burn reduction of at least 1.5% relative to the "
        "pre-modification baseline at the typical mission profile.",
        "system", "test", "sys.propulsion",
    ),
    (
        "req.weight", "VOY-REQ-0030",
        "The retrofit kit installed weight shall not exceed the structural weight budget allocated to the "
        "cabin modification.",
        "subsystem", "inspection", "sys.structure",
    ),
    (
        "req.iface", "VOY-REQ-0040",
        "The modification shall preserve the existing avionics-to-cabin data interface without requiring "
        "new wiring runs.",
        "interface", "demonstration", "sys.iface",
    ),
]

RISKS: list[tuple[str, str, int, int]] = [
    ("risk.supplier", "Sole-source replacement LRU supplier lead time exceeds the programme schedule", 3, 4),
    ("risk.requal", "Requalification test campaign slips past CDR", 3, 3),
    ("risk.weightgrowth", "Weight growth in the retrofit kit erodes the fuel-burn benefit", 2, 4),
]

# id, name, confidence, validation method, what it underlies
ASSUMPTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "asm.formfit",
        "The replacement flight-management LRU is form-fit-function equivalent to the obsolete unit",
        "medium",
        "Confirm via interface control document review at PDR",
        "risk.requal",
    ),
    (
        "asm.pipdata",
        "The engine performance-improvement kit's certified data package is reusable fleet-wide without "
        "aircraft-specific re-substantiation",
        "high",
        "Cross-check against the kit supplier's service bulletin once issued",
        "obj.fuelburn",
    ),
    (
        "asm.wiring",
        "Existing wiring and connectors support the replacement LRU without rerouting",
        "low",
        "Physical inspection during the first aircraft induction",
        "req.iface",
    ),
]

# id, name, parameter_type, value, unit, which element it characterises
PARAMETERS: list[tuple[str, str, str, str, str, str]] = [
    ("par.fuelburn", "Fuel burn reduction", "performance", "1.8", "%", "obj.fuelburn"),
    ("par.weightbudget", "Retrofit kit structural weight budget", "performance", "45", "kg", "wp.weight"),
    ("par.dmsms_index", "Open DMSMS risk items", "business", "12", "items", "wp.avionics"),
    ("par.nrc", "Non-recurring cost", "cost", "4.2", "$M", "obj.cost"),
]

# Parameter-to-parameter links only, independent of the elements they characterise.
PARAMETER_LINKS: list[tuple[str, str]] = [
    ("par.weightbudget", "par.fuelburn"),
    ("par.nrc", "par.dmsms_index"),
]

# id, name, type, work package, responsible, milestone, objectives, process,
# business process, methods, tools, weight, status, effort, progress, rationale
ACTIVITIES: list[dict[str, Any]] = [
    {
        "id": "act.archbaseline",
        "name": "Establish and baseline the aircraft architecture description (OAD, OPD, OSD)",
        "type": "architecture_definition",
        "wp": "wp.avionics",
        "who": "per.osei",
        "when": "ms.sdr",
        "why": ["obj.dmsms", "obj.fuelburn", "obj.cert"],
        "process": "proc.arch",
        "business": "bp.reviewgate",
        "methods": ["mth.interface"],
        "tools": ["tool.catia"],
        "weight": "high",
        "status": "done",
        "effort": 40,
        "progress": 100,
        "rationale": "The OAD/OPD/OSD baseline is what every obsolescence and performance activity traces back to; "
                     "nothing downstream can be judged against a moving architecture.",
    },
    {
        "id": "act.dmsms_survey",
        "name": "Survey and prioritise DMSMS obsolescence items across the avionics suite",
        "type": "analysis",
        "wp": "wp.avionics",
        "who": "per.bianchi",
        "when": "ms.sdr",
        "why": ["obj.dmsms"],
        "process": "proc.analysis",
        "business": "bp.config",
        "methods": [],
        "tools": ["tool.doors"],
        "weight": "high",
        "status": "done",
        "effort": 30,
        "progress": 100,
        "rationale": "Prioritises which obsolete parts actually threaten production continuity before design "
                     "effort is committed to any of them.",
    },
    {
        "id": "act.lru_redesign",
        "name": "Design the replacement flight-management LRU",
        "type": "architecture_definition",
        "wp": "wp.avionics",
        "who": "per.bianchi",
        "when": "ms.pdr",
        "why": ["obj.dmsms"],
        "process": "proc.arch",
        "business": "bp.reviewgate",
        "methods": ["mth.interface"],
        "tools": ["tool.catia"],
        "weight": "high",
        "status": "in_progress",
        "effort": 70,
        "progress": 55,
        "rationale": "The replacement LRU has to fit the existing bay and interface without triggering a "
                     "wiring change - the assumption the whole obsolescence workstream rests on.",
    },
    {
        "id": "act.iface_analysis",
        "name": "Re-verify the avionics-to-cabin interface with the replacement LRU installed",
        "type": "interface_definition",
        "wp": "wp.avionics",
        "who": "per.osei",
        "when": "ms.pdr",
        "why": ["obj.dmsms", "obj.cert"],
        "process": "proc.arch",
        "business": "bp.reviewgate",
        "methods": ["mth.interface"],
        "tools": ["tool.catia"],
        "weight": "medium",
        "status": "in_review",
        "effort": 25,
        "progress": 80,
        "rationale": "Confirms the OSD's data interface still holds once the replacement unit is installed.",
    },
    {
        "id": "act.perf_trade",
        "name": "Trade study: engine performance-improvement kit configuration",
        "type": "trade_study",
        "wp": "wp.perf",
        "who": "per.farrow",
        "when": "ms.pdr",
        "why": ["obj.fuelburn"],
        "process": "proc.analysis",
        "business": "bp.reviewgate",
        "methods": ["mth.perf"],
        "tools": ["tool.matlab"],
        "weight": "high",
        "status": "in_review",
        "effort": 45,
        "progress": 85,
        "rationale": "Weighs nacelle/kit options against fuel-burn benefit and installation complexity before "
                     "the design is frozen.",
    },
    {
        "id": "act.perf_analysis",
        "name": "Fuel-burn performance substantiation analysis",
        "type": "analysis",
        "wp": "wp.perf",
        "who": "per.farrow",
        "when": "ms.cdr",
        "why": ["obj.fuelburn"],
        "process": "proc.analysis",
        "business": "bp.reviewgate",
        "methods": ["mth.perf"],
        "tools": ["tool.matlab"],
        "weight": "high",
        "status": "in_progress",
        "effort": 60,
        "progress": 40,
        "rationale": "Primary evidence the stated fuel-burn objective is achievable before the kit design closes.",
    },
    {
        "id": "act.weight_track",
        "name": "Maintain the retrofit-kit structural weight budget",
        "type": "analysis",
        "wp": "wp.weight",
        "who": "per.voss",
        "when": "ms.pdr",
        "why": ["obj.fuelburn", "obj.cost"],
        "process": "proc.analysis",
        "business": "bp.config",
        "methods": ["mth.weight"],
        "tools": ["tool.matlab"],
        "weight": "high",
        "status": "in_progress",
        "effort": 30,
        "progress": 60,
        "rationale": "Weight growth in the kit directly erodes the fuel-burn benefit the programme is "
                     "committed to.",
    },
    {
        "id": "act.cabin_redesign",
        "name": "Redesign the cabin galley assembly for weight reduction",
        "type": "architecture_definition",
        "wp": "wp.weight",
        "who": "per.voss",
        "when": "ms.cdr",
        "why": ["obj.fuelburn"],
        "process": "proc.arch",
        "business": "bp.reviewgate",
        "methods": ["mth.weight"],
        "tools": ["tool.catia"],
        "weight": "medium",
        "status": "not_started",
        "effort": 50,
        "progress": 0,
        "rationale": "The galley assembly is the single largest weight-reduction item in the kit.",
    },
    {
        "id": "act.certbasis",
        "name": "Agree the certification basis items affected by the modification",
        "type": "coordination",
        "wp": "wp.cert",
        "who": "per.nakamura",
        "when": "ms.pdr",
        "why": ["obj.cert"],
        "process": "proc.reqmgmt",
        "business": "bp.reviewgate",
        "methods": [],
        "tools": ["tool.doors"],
        "weight": "high",
        "status": "in_progress",
        "effort": 35,
        "progress": 50,
        "rationale": "Agrees which existing certification basis items are affected before the design commits.",
    },
    {
        "id": "act.vplan",
        "name": "Build the modification verification plan and matrix",
        "type": "verification",
        "wp": "wp.cert",
        "who": "per.nakamura",
        "when": "ms.cdr",
        "why": ["obj.cert"],
        "process": "proc.verification",
        "business": "bp.reviewgate",
        "methods": [],
        "tools": ["tool.doors"],
        "weight": "high",
        "status": "not_started",
        "effort": 40,
        "progress": 0,
        "rationale": "Every requirement needs an assigned verification method before ground test is defined.",
    },
    {
        "id": "act.fmeca",
        "name": "Modification FMECA and critical items list",
        "type": "analysis",
        "wp": "wp.cert",
        "who": "per.reyes",
        "when": "ms.cdr",
        "why": ["obj.cert"],
        "process": "proc.safety",
        "business": "bp.reviewgate",
        "methods": [],
        "tools": ["tool.matlab"],
        "weight": "medium",
        "status": "not_started",
        "effort": 35,
        "progress": 0,
        "rationale": "Safety assessment evidence required before ground test readiness.",
    },
    {
        "id": "act.groundtest",
        "name": "Combined ground test: requalified LRU and performance kit",
        "type": "integration",
        "wp": "wp.cert",
        "who": "per.nakamura",
        "when": "ms.trr",
        "why": ["obj.cert", "obj.fuelburn"],
        "process": "proc.verification",
        "business": "bp.reviewgate",
        "methods": [],
        "tools": [],
        "weight": "high",
        "status": "not_started",
        "effort": 60,
        "progress": 0,
        "rationale": "The first point where the requalified LRU and the performance kit are proven together, "
                     "not just as independent workstreams.",
    },
]

# id, name, deliverable_type, producer activity, milestone
DELIVERABLES: list[tuple[str, str, str, str, str]] = [
    ("del.oad", "Overall Aircraft Design (OAD) baseline", "architecture_model", "act.archbaseline", "ms.sdr"),
    ("del.opd", "Outline Performance Diagram (OPD)", "architecture_model", "act.archbaseline", "ms.sdr"),
    ("del.osd", "Outline Systems Diagram (OSD)", "architecture_model", "act.archbaseline", "ms.sdr"),
    ("del.dmsms_report", "DMSMS obsolescence impact assessment", "analysis_report", "act.dmsms_survey", "ms.sdr"),
    ("del.perf_report", "Performance substantiation report", "analysis_report", "act.perf_analysis", "ms.cdr"),
    ("del.certdata", "Certification compliance data package", "certification_evidence", "act.vplan", "ms.trr"),
    ("del.wnb", "Weight & balance report", "analysis_report", "act.weight_track", "ms.cdr"),
]

#: Which architecture-baseline deliverable applies to which part of the system tree.
BASELINE_APPLIES_TO: list[tuple[str, str]] = [
    ("del.oad", "sys.aircraft"),
    ("del.opd", "sys.propulsion"),
    ("del.osd", "sys.avionics"),
    ("del.osd", "sys.iface"),
]

#: Cross-workstream dependencies - what makes this one complex programme rather
#: than two independent ones.
DEPENDENCIES: list[tuple[str, str]] = [
    ("act.groundtest", "act.lru_redesign"),
    ("act.groundtest", "act.perf_analysis"),
    ("act.iface_analysis", "act.lru_redesign"),
    ("act.cabin_redesign", "act.weight_track"),
]


def build_modification_demo(ontology: Ontology) -> GraphDocument:
    """Construct the modification-programme example through the normal validated write path."""
    store = GraphStore(GraphDocument(project=PROJECT), ontology)
    actor = "demo"

    def node(node_id: str, type_name: str, **properties: Any) -> None:
        store.add_node(type_name, properties, node_id=node_id, actor=actor, source="demo")

    def link(edge_type: str, source: str, target: str, **properties: Any) -> None:
        store.add_edge(edge_type, source, target, properties, actor=actor, source_system="demo")

    for node_id, name, role, organisation in PEOPLE:
        node(node_id, "Person", name=name, role=role, organisation=organisation)

    previous_milestone = ""
    for node_id, name, gate, sequence, criteria in MILESTONES:
        node(node_id, "Milestone", name=name, gate=gate, sequence=sequence, gate_criteria=criteria, phase="D")
        if previous_milestone:
            link("PRECEDES", previous_milestone, node_id)
        previous_milestone = node_id

    for node_id, name, objective_type, priority, criterion in OBJECTIVES:
        node(
            node_id,
            "Objective",
            name=name,
            objective_type=objective_type,
            priority=priority,
            success_criterion=criterion,
            weight="high" if priority == "must" else "medium",
        )

    for node_id, name, standard, clause, group in SEPROCESSES:
        node(node_id, "SEProcess", name=name, standard=standard, clause=clause, process_group=group)

    for node_id, name, owner, reference in BUSINESS_PROCESSES:
        node(node_id, "BusinessProcess", process_owner=owner, qms_reference=reference, name=name)

    for node_id, name, technique, tooling in METHODS:
        node(node_id, "Method", name=name, technique=technique, tooling=tooling)

    for tool in TOOLS:
        properties = {k: v for k, v in tool.items() if k not in ("id", "admin")}
        node(tool["id"], "Tool", status="in_progress", **properties)
        link("ADMINISTERS", tool["admin"], tool["id"])
    for method_id, tool_id in METHOD_TOOLS:
        link("IMPLEMENTED_BY_TOOL", method_id, tool_id)
    for source, target, fmt, automated in TOOL_CHAIN:
        link("EXCHANGES_DATA_WITH", source, target, exchange_format=fmt, automated=automated)

    for node_id, name, wbs, leader, budget in WORK_PACKAGES:
        node(node_id, "WorkPackage", name=name, wbs_code=wbs, budget_days=budget, status="in_progress")
        link("LED_BY", node_id, leader)
    link("SUPPORTS", "wp.avionics", "obj.dmsms", contribution="primary")
    link("SUPPORTS", "wp.perf", "obj.fuelburn", contribution="primary")
    link("SUPPORTS", "wp.weight", "obj.fuelburn", contribution="contributing")
    link("SUPPORTS", "wp.cert", "obj.cert", contribution="primary")
    for wp_id, *_ in WORK_PACKAGES:
        link("SUPPORTS", wp_id, "obj.cost", contribution="enabling")

    for node_id, name, level, pbs, parent in SYSTEM_ELEMENTS:
        node(node_id, "SystemElement", name=name, element_level=level, pbs_code=pbs)
    for node_id, *_rest, parent in SYSTEM_ELEMENTS:
        if parent:
            link("PART_OF", node_id, parent)

    for node_id, requirement_id, statement, level, method, element in REQUIREMENTS:
        node(
            node_id,
            "Requirement",
            name=statement[:70],
            requirement_id=requirement_id,
            statement=statement,
            level=level,
            verification_method=method,
            status="in_review",
            maturity="reviewed",
        )
        link("ALLOCATED_TO", node_id, element)
    link("DERIVED_FROM", "req.dmsms", "obj.dmsms")
    link("DERIVED_FROM", "req.fuelburn", "obj.fuelburn")
    link("DERIVED_FROM", "req.weight", "obj.fuelburn")
    link("DERIVED_FROM", "req.iface", "obj.cert")
    link("SATISFIES", "sys.fmc", "req.dmsms")

    for node_id, name, likelihood, severity in RISKS:
        node(node_id, "Risk", name=name, likelihood=likelihood, severity=severity, risk_status="mitigating")

    for node_id, name, confidence, validation_method, underlies in ASSUMPTIONS:
        node(node_id, "Assumption", name=name, confidence=confidence, validation_method=validation_method)
        link("UNDERLIES", node_id, underlies)

    for node_id, name, parameter_type, value, unit, carrier in PARAMETERS:
        node(node_id, "Parameter", name=name, parameter_type=parameter_type, value=value, unit=unit)
        link("HAS_PARAMETER", carrier, node_id)
    for source, target in PARAMETER_LINKS:
        link("PARAMETER_LINK", source, target)

    for activity in ACTIVITIES:
        node(
            activity["id"],
            "Activity",
            name=activity["name"],
            activity_type=activity["type"],
            status=activity["status"],
            progress_percent=activity["progress"],
            effort_days=activity["effort"],
            rationale=activity["rationale"],
            maturity="draft" if activity["status"] == "in_progress" else "concept",
            weight=activity.get("weight", "high"),
        )
        link("CONTAINS", activity["wp"], activity["id"])
        link("RESPONSIBLE_FOR", activity["who"], activity["id"])
        link("DELIVERS_AT", activity["id"], activity["when"], commitment="committed")
        for objective in activity["why"]:
            link("SUPPORTS", activity["id"], objective, contribution="primary")
        link("IMPLEMENTS_PROCESS", activity["id"], activity["process"])
        link("GOVERNED_BY", activity["id"], activity["business"])
        for method in activity["methods"]:
            link("USES_METHOD", activity["id"], method)
        for index, tool_id in enumerate(activity.get("tools") or []):
            link("USES_TOOL", activity["id"], tool_id, usage="primary" if index == 0 else "supporting")
        link("ACCOUNTABLE_FOR", "per.hale", activity["id"])

    for node_id, name, deliverable_type, producer, milestone in DELIVERABLES:
        node(node_id, "Deliverable", name=name, deliverable_type=deliverable_type, status="not_started")
        link("PRODUCES", producer, node_id)
        link("DELIVERS_AT", node_id, milestone, commitment="committed")
    for deliverable_id, element_id in BASELINE_APPLIES_TO:
        link("APPLIES_TO", deliverable_id, element_id)

    for source, target in DEPENDENCIES:
        link("DEPENDS_ON", source, target, dependency_type="finish_to_start")

    link("MITIGATES", "act.lru_redesign", "risk.supplier")
    link("MITIGATES", "act.dmsms_survey", "risk.requal")
    link("MITIGATES", "act.weight_track", "risk.weightgrowth")
    link("VERIFIES", "act.iface_analysis", "req.iface")
    link("VERIFIES", "act.perf_analysis", "req.fuelburn")
    link("VERIFIES", "act.lru_redesign", "req.dmsms")
    link("VERIFIES", "act.cabin_redesign", "req.weight")

    document = store.snapshot()
    document.revision = 1
    return document
