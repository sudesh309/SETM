"""A worked example project.

``setm demo`` builds this graph so a new user sees the tool doing something real
within seconds rather than staring at an empty canvas. It is a small but
internally consistent slice of a satellite payload programme: objectives,
milestones from SRR to QR, four work packages, and activities that each state
who, when, why, and under which process and method.
"""

from __future__ import annotations

from typing import Any

from .graph.store import GraphStore
from .model import GraphDocument, ProjectInfo
from .ontology.schema import Ontology

PROJECT = ProjectInfo(
    id="halo-payload",
    name="HALO-1 Optical Payload",
    programme="HALO Earth Observation",
    phase="B",
    description=(
        "Phase B systems engineering plan for the HALO-1 high-resolution optical payload: "
        "architecture consolidation, requirements flow-down and the PDR data package."
    ),
    chief_engineer="A. Okonkwo",
)

PEOPLE: list[tuple[str, str, str, str]] = [
    ("per.okonkwo", "A. Okonkwo", "chief_engineer", "Systems Engineering"),
    ("per.mehta", "R. Mehta", "systems_engineer", "Systems Engineering"),
    ("per.laurent", "C. Laurent", "work_package_leader", "Optical Design"),
    ("per.svensson", "E. Svensson", "work_package_leader", "Thermal & Structures"),
    ("per.tanaka", "H. Tanaka", "verification_engineer", "AIV"),
    ("per.dubois", "M. Dubois", "safety_engineer", "Product Assurance"),
    ("per.novak", "P. Novak", "domain_specialist", "Electronics"),
]

MILESTONES: list[tuple[str, str, str, int, str]] = [
    ("ms.srr", "System Requirements Review", "SRR", 10, "Requirements baseline agreed with the customer."),
    ("ms.pdr", "Preliminary Design Review", "PDR", 20, "Architecture frozen, budgets closed, long leads released."),
    ("ms.cdr", "Critical Design Review", "CDR", 30, "Detailed design complete and verifiable."),
    ("ms.trr", "Test Readiness Review", "TRR", 40, "Qualification model and test facility ready."),
    ("ms.qr", "Qualification Review", "QR", 50, "Qualification evidence complete and accepted."),
]

OBJECTIVES: list[tuple[str, str, str, str, str]] = [
    (
        "obj.gsd",
        "Achieve 0.5 m ground sample distance",
        "performance",
        "must",
        "End-to-end imaging chain demonstrates GSD <= 0.5 m at nadir, verified by analysis and test.",
    ),
    (
        "obj.mass",
        "Stay within the 180 kg payload mass allocation",
        "performance",
        "must",
        "Mass budget with 15% margin at PDR, 8% at CDR.",
    ),
    (
        "obj.qualify",
        "Qualify the payload for a 7-year LEO mission",
        "certification",
        "must",
        "Qualification evidence accepted at QR against the agreed environmental specification.",
    ),
    (
        "obj.cost",
        "Deliver Phase B within the agreed SE budget",
        "cost",
        "should",
        "Phase B systems engineering effort within 5% of the 900 person-day budget.",
    ),
]

PROCESSES: list[tuple[str, str, str, str, str]] = [
    ("proc.stakeholder", "Stakeholder needs and requirements definition", "ISO_15288", "6.4.2", "technical"),
    ("proc.sysreq", "System requirements definition", "ISO_15288", "6.4.3", "technical"),
    ("proc.arch", "Architecture definition", "ISO_15288", "6.4.4", "technical"),
    ("proc.design", "Design definition", "ISO_15288", "6.4.5", "technical"),
    ("proc.analysis", "System analysis", "ISO_15288", "6.4.6", "technical"),
    ("proc.verification", "Verification", "ISO_15288", "6.4.9", "technical"),
    ("proc.riskmgmt", "Risk management", "ISO_15288", "6.3.4", "technical_management"),
    ("proc.ecss_reviews", "Project reviews", "ECSS_E_ST_10C", "5.4", "technical_management"),
]

BUSINESS_PROCESSES: list[tuple[str, str, str, str]] = [
    ("bp.reviewgate", "Engineering review gate procedure", "Quality", "QMS-ENG-014"),
    ("bp.config", "Configuration and data management", "Configuration Management", "QMS-CM-003"),
    ("bp.supplier", "Supplier technical oversight", "Procurement", "QMS-SUP-021"),
]

METHODS: list[tuple[str, str, str, str]] = [
    ("mth.mbse", "MBSE architecture modelling", "SysML v2 system model", "Cameo Systems Modeler"),
    ("mth.budget", "Engineering budget accounting", "Mass/power/pointing budget roll-up", "Python, spreadsheet"),
    ("mth.optical", "Optical performance simulation", "Physical-optics MTF simulation", "Zemax, MATLAB"),
    ("mth.thermal", "Thermal analysis", "Reduced-node transient thermal model", "ESATAN-TMS"),
    ("mth.fmeca", "FMECA", "Failure modes, effects and criticality analysis", "Internal FMECA template"),
    ("mth.trade", "Trade study", "Weighted Pugh matrix with sensitivity check", "Internal trade template"),
]

WORK_PACKAGES: list[tuple[str, str, str, str, float]] = [
    ("wp.sys", "WP1000 Payload system engineering", "1000", "per.mehta", 320),
    ("wp.opt", "WP2000 Optical subsystem", "2000", "per.laurent", 260),
    ("wp.tms", "WP3000 Thermal and structure", "3000", "per.svensson", 180),
    ("wp.aiv", "WP4000 Assembly, integration and verification", "4000", "per.tanaka", 140),
]

ELEMENTS: list[tuple[str, str, str, str]] = [
    ("sys.payload", "Optical payload", "system", "PL"),
    ("sys.tele", "Telescope assembly", "subsystem", "PL-10"),
    ("sys.focal", "Focal plane assembly", "subsystem", "PL-20"),
    ("sys.thermal", "Thermal control subsystem", "subsystem", "PL-30"),
    ("sys.electronics", "Payload electronics unit", "subsystem", "PL-40"),
    ("sys.icd_bus", "Payload-to-bus interface", "interface", "PL-IF-01"),
]

REQUIREMENTS: list[tuple[str, str, str, str, str]] = [
    ("req.gsd", "PL-REQ-0010", "The payload shall provide a ground sample distance of 0.5 m or better at nadir.", "system", "test"),
    ("req.mtf", "PL-REQ-0011", "The imaging chain shall achieve an MTF of at least 0.15 at Nyquist.", "system", "analysis"),
    ("req.mass", "PL-REQ-0020", "The payload mass shall not exceed 180 kg.", "system", "inspection"),
    ("req.thermal", "PL-REQ-0030", "The focal plane shall be maintained at 253 K +/- 2 K in imaging mode.", "subsystem", "test"),
    ("req.iface", "PL-REQ-0040", "The payload shall exchange science data over a SpaceWire link per the bus ICD.", "interface", "demonstration"),
]

RISKS: list[tuple[str, str, int, int]] = [
    ("risk.mtf", "Optical MTF shortfall at end of life", 3, 4),
    ("risk.thermal", "Focal plane thermal stability not achievable with passive design", 3, 4),
    ("risk.longlead", "Detector long-lead procurement slips past CDR", 2, 5),
]

# id, name, type, work package, responsible, milestone, objectives, process,
# business process, methods, status, effort, rationale
ACTIVITIES: list[dict[str, Any]] = [
    {
        "id": "act.stakeholder",
        "name": "Consolidate stakeholder needs into payload requirements",
        "type": "requirements_definition",
        "wp": "wp.sys",
        "who": "per.mehta",
        "when": "ms.srr",
        "why": ["obj.gsd", "obj.qualify"],
        "process": "proc.stakeholder",
        "business": "bp.config",
        "methods": ["mth.mbse"],
        "status": "done",
        "effort": 45,
        "progress": 100,
        "rationale": "Without an agreed needs baseline the requirement flow-down cannot be frozen at SRR.",
    },
    {
        "id": "act.sysreq",
        "name": "Derive and baseline payload system requirements",
        "type": "requirements_definition",
        "wp": "wp.sys",
        "who": "per.mehta",
        "when": "ms.srr",
        "why": ["obj.gsd", "obj.mass"],
        "process": "proc.sysreq",
        "business": "bp.config",
        "methods": ["mth.mbse"],
        "status": "done",
        "effort": 60,
        "progress": 100,
        "rationale": "Establishes the verifiable requirement set every downstream design decision is judged against.",
    },
    {
        "id": "act.arch",
        "name": "Define payload architecture and interfaces",
        "type": "architecture_definition",
        "wp": "wp.sys",
        "who": "per.mehta",
        "when": "ms.pdr",
        "why": ["obj.gsd", "obj.mass"],
        "process": "proc.arch",
        "business": "bp.config",
        "methods": ["mth.mbse"],
        "status": "in_progress",
        "effort": 80,
        "progress": 65,
        "rationale": "Fixes the functional and physical decomposition so subsystems can be specified independently.",
    },
    {
        "id": "act.budgets",
        "name": "Maintain mass, power and pointing budgets",
        "type": "analysis",
        "wp": "wp.sys",
        "who": "per.mehta",
        "when": "ms.pdr",
        "why": ["obj.mass"],
        "process": "proc.analysis",
        "business": "bp.config",
        "methods": ["mth.budget"],
        "status": "in_progress",
        "effort": 30,
        "progress": 55,
        "rationale": "The mass allocation is a contractual constraint; margin erosion has to be visible weekly.",
    },
    {
        "id": "act.opttrade",
        "name": "Trade study: telescope configuration",
        "type": "trade_study",
        "wp": "wp.opt",
        "who": "per.laurent",
        "when": "ms.pdr",
        "why": ["obj.gsd", "obj.mass"],
        "process": "proc.arch",
        "business": "bp.reviewgate",
        "methods": ["mth.trade", "mth.optical"],
        "status": "in_review",
        "effort": 40,
        "progress": 85,
        "rationale": "Korsch versus three-mirror anastigmat drives both GSD achievability and the mass budget.",
    },
    {
        "id": "act.mtf",
        "name": "End-to-end MTF and radiometric performance analysis",
        "type": "analysis",
        "wp": "wp.opt",
        "who": "per.laurent",
        "when": "ms.pdr",
        "why": ["obj.gsd"],
        "process": "proc.analysis",
        "business": "bp.reviewgate",
        "methods": ["mth.optical"],
        "status": "in_progress",
        "effort": 55,
        "progress": 40,
        "rationale": "Primary evidence that the 0.5 m GSD objective is achievable before the design is frozen.",
    },
    {
        "id": "act.thermal",
        "name": "Focal plane thermal control analysis",
        "type": "analysis",
        "wp": "wp.tms",
        "who": "per.svensson",
        "when": "ms.pdr",
        "why": ["obj.gsd", "obj.qualify"],
        "process": "proc.analysis",
        "business": "bp.reviewgate",
        "methods": ["mth.thermal"],
        "status": "in_progress",
        "effort": 50,
        "progress": 45,
        "rationale": "Detector noise performance, and therefore image quality, depends on holding 253 K.",
    },
    {
        "id": "act.structure",
        "name": "Preliminary structural sizing and modal analysis",
        "type": "analysis",
        "wp": "wp.tms",
        "who": "per.svensson",
        "when": "ms.pdr",
        "why": ["obj.mass", "obj.qualify"],
        "process": "proc.design",
        "business": "bp.reviewgate",
        "methods": ["mth.budget"],
        "status": "not_started",
        "effort": 35,
        "progress": 0,
        "rationale": "Launch loads and the first mode requirement size the optical bench, which dominates payload mass.",
    },
    {
        "id": "act.icd",
        "name": "Agree payload-to-bus interface control document",
        "type": "interface_definition",
        "wp": "wp.sys",
        "who": "per.novak",
        "when": "ms.pdr",
        "why": ["obj.qualify"],
        "process": "proc.arch",
        "business": "bp.supplier",
        "methods": ["mth.mbse"],
        "status": "in_progress",
        "effort": 25,
        "progress": 30,
        "rationale": "The bus supplier needs a frozen interface to release their long-lead harness design.",
    },
    {
        "id": "act.fmeca",
        "name": "Payload FMECA and critical items list",
        "type": "analysis",
        "wp": "wp.sys",
        "who": "per.dubois",
        "when": "ms.cdr",
        "why": ["obj.qualify"],
        "process": "proc.riskmgmt",
        "business": "bp.reviewgate",
        "methods": ["mth.fmeca"],
        "status": "not_started",
        "effort": 40,
        "progress": 0,
        "rationale": "Product assurance evidence required at CDR and input to the qualification test matrix.",
    },
    {
        "id": "act.vplan",
        "name": "Build the payload verification plan and matrix",
        "type": "verification",
        "wp": "wp.aiv",
        "who": "per.tanaka",
        "when": "ms.cdr",
        "why": ["obj.qualify"],
        "process": "proc.verification",
        "business": "bp.reviewgate",
        "methods": ["mth.mbse"],
        "status": "not_started",
        "effort": 45,
        "progress": 0,
        "rationale": "Every requirement needs an assigned verification method and level before detailed design closes.",
    },
    {
        "id": "act.pdrpack",
        "name": "Assemble and run the PDR data package",
        "type": "review",
        "wp": "wp.sys",
        "who": "per.okonkwo",
        "when": "ms.pdr",
        "why": ["obj.qualify", "obj.cost"],
        "process": "proc.ecss_reviews",
        "business": "bp.reviewgate",
        "methods": [],
        "status": "not_started",
        "effort": 30,
        "progress": 0,
        "rationale": "The gate itself: consolidates every Phase B output into the evidence the customer reviews.",
    },
    {
        "id": "act.qualcampaign",
        "name": "Plan the environmental qualification campaign",
        "type": "qualification",
        "wp": "wp.aiv",
        "who": "per.tanaka",
        "when": "ms.trr",
        "why": ["obj.qualify"],
        "process": "proc.verification",
        "business": "bp.reviewgate",
        "methods": [],
        "status": "not_started",
        "effort": 35,
        "progress": 0,
        "rationale": "Facility slots for thermal-vacuum and vibration must be booked two gates ahead.",
    },
]

DELIVERABLES: list[tuple[str, str, str, str, str]] = [
    ("del.reqspec", "Payload requirements specification", "specification", "act.sysreq", "ms.srr"),
    ("del.archdesc", "Payload architecture description", "architecture_model", "act.arch", "ms.pdr"),
    ("del.trade", "Telescope configuration trade report", "trade_study_report", "act.opttrade", "ms.pdr"),
    ("del.mtf", "Optical performance analysis report", "analysis_report", "act.mtf", "ms.pdr"),
    ("del.thermal", "Thermal analysis report", "analysis_report", "act.thermal", "ms.pdr"),
    ("del.icd", "Payload-to-bus ICD", "icd", "act.icd", "ms.pdr"),
    ("del.vmatrix", "Verification plan and matrix", "test_plan", "act.vplan", "ms.cdr"),
    ("del.pdrpack", "PDR data package", "review_data_package", "act.pdrpack", "ms.pdr"),
]

DEPENDENCIES: list[tuple[str, str]] = [
    ("act.arch", "act.sysreq"),
    ("act.budgets", "act.arch"),
    ("act.mtf", "act.opttrade"),
    ("act.structure", "act.arch"),
    ("act.thermal", "act.arch"),
    ("act.icd", "act.arch"),
    ("act.vplan", "act.sysreq"),
    ("act.fmeca", "act.arch"),
    ("act.pdrpack", "act.mtf"),
    ("act.pdrpack", "act.thermal"),
    ("act.pdrpack", "act.opttrade"),
    ("act.qualcampaign", "act.vplan"),
]


def build_demo(ontology: Ontology) -> GraphDocument:
    """Construct the demo graph through the normal validated write path."""
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
        node(node_id, "Milestone", name=name, gate=gate, sequence=sequence, gate_criteria=criteria, phase="B")
        if previous_milestone:
            link("PRECEDES", previous_milestone, node_id)
        previous_milestone = node_id

    for node_id, name, objective_type, priority, criterion in OBJECTIVES:
        node(node_id, "Objective", name=name, objective_type=objective_type, priority=priority, success_criterion=criterion)

    for node_id, name, standard, clause, group in PROCESSES:
        node(node_id, "SEProcess", name=name, standard=standard, clause=clause, process_group=group)

    for node_id, name, owner, reference in BUSINESS_PROCESSES:
        node(node_id, "BusinessProcess", name=name, process_owner=owner, qms_reference=reference)

    for node_id, name, technique, tooling in METHODS:
        node(node_id, "Method", name=name, technique=technique, tooling=tooling)

    for node_id, name, level, pbs in ELEMENTS:
        node(node_id, "SystemElement", name=name, element_level=level, pbs_code=pbs)
    for child in ("sys.tele", "sys.focal", "sys.thermal", "sys.electronics", "sys.icd_bus"):
        link("PART_OF", child, "sys.payload")

    for node_id, requirement_id, statement, level, method in REQUIREMENTS:
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
    link("DERIVED_FROM", "req.gsd", "obj.gsd")
    link("DERIVED_FROM", "req.mtf", "req.gsd")
    link("DERIVED_FROM", "req.mass", "obj.mass")
    link("ALLOCATED_TO", "req.mtf", "sys.tele")
    link("ALLOCATED_TO", "req.thermal", "sys.thermal")
    link("ALLOCATED_TO", "req.iface", "sys.icd_bus")
    link("SATISFIES", "sys.tele", "req.mtf")

    for node_id, name, likelihood, severity in RISKS:
        node(node_id, "Risk", name=name, likelihood=likelihood, severity=severity, risk_status="mitigating")

    for node_id, name, wbs, leader, budget in WORK_PACKAGES:
        node(node_id, "WorkPackage", name=name, wbs_code=wbs, budget_days=budget, status="in_progress")
        link("LED_BY", node_id, leader)
        link("SUPPORTS", node_id, "obj.cost", contribution="enabling")

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
        link("ACCOUNTABLE_FOR", "per.okonkwo", activity["id"])

    for node_id, name, deliverable_type, producer, milestone in DELIVERABLES:
        node(node_id, "Deliverable", name=name, deliverable_type=deliverable_type, status="not_started")
        link("PRODUCES", producer, node_id)
        link("DELIVERS_AT", node_id, milestone, commitment="committed")

    for source, target in DEPENDENCIES:
        link("DEPENDS_ON", source, target, dependency_type="finish_to_start")

    link("MITIGATES", "act.mtf", "risk.mtf")
    link("MITIGATES", "act.thermal", "risk.thermal")
    link("MITIGATES", "act.icd", "risk.longlead")
    link("VERIFIES", "act.mtf", "req.mtf")
    link("VERIFIES", "act.thermal", "req.thermal")
    link("VERIFIES", "act.vplan", "req.gsd")
    link("VERIFIES", "act.budgets", "req.mass")
    link("APPLIES_TO", "act.mtf", "sys.tele")
    link("APPLIES_TO", "act.thermal", "sys.thermal")
    link("APPLIES_TO", "act.icd", "sys.icd_bus")
    link("PRESCRIBES", "proc.verification", "mth.fmeca")
    link("PRESCRIBES", "bp.reviewgate", "del.pdrpack")
    link("CONSUMES", "act.pdrpack", "del.trade")
    link("CONSUMES", "act.pdrpack", "del.mtf")
    link("CONSUMES", "act.vplan", "del.reqspec")

    document = store.snapshot()
    document.revision = 1
    return document
