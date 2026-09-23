"""HTTP route table.

Handlers are plain functions of ``(workspace, request) -> Response``. They know
nothing about sockets, which is why the same table is served both by the stdlib
server in :mod:`setm.api.server` and by the optional ASGI adapter in
:mod:`setm.api.asgi`.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..config import FIELDS_BY_NAME, SECRET_PLACEHOLDER
from ..errors import ConfigError, NotFoundError, SetmError, ValidationError
from ..examples import EXAMPLES
from ..graph import query
from ..graph._fastpath import degree_centrality
from ..kpi.metrics import KPI_CATALOGUE, compute_kpis
from ..kpi.telemetry import telemetry
from ..model import GraphDocument
from ..report import FORMATS as REPORT_FORMATS, build_report, render, safe_filename
from ..ontology.loader import _as_source
from ..serialize.rdfmap import document_to_turtle, ontology_to_owl, turtle_to_document
from ..serialize.tabular import document_to_tables, tables_to_csv
from ..workspace import Workspace
from .security import check_remote_target, require_token

logger = logging.getLogger("setm.api")


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]] = field(default_factory=dict)
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)

    def get(self, name: str, default: str = "") -> str:
        values = self.query.get(name)
        return values[0] if values else default

    def get_int(self, name: str, default: int) -> int:
        try:
            return int(self.get(name, str(default)))
        except ValueError:
            raise ValidationError(f"Query parameter '{name}' must be a whole number") from None

    def get_bool(self, name: str, default: bool = False) -> bool:
        raw = self.get(name, "")
        return default if raw == "" else raw.lower() in ("1", "true", "yes", "on")

    def get_list(self, name: str) -> list[str]:
        values: list[str] = []
        for item in self.query.get(name, []):
            values += [v for v in item.split(",") if v]
        return values

    def json_body(self) -> dict[str, Any]:
        if self.body is None:
            return {}
        if isinstance(self.body, dict):
            return self.body
        raise ValidationError("Expected a JSON object in the request body")

    @property
    def actor(self) -> str:
        return self.headers.get("x-setm-user") or self.get("actor") or ""


@dataclass
class Response:
    status: int = 200
    body: Any = None
    content_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)

    def rendered(self) -> bytes:
        if self.body is None:
            return b""
        if isinstance(self.body, bytes):
            return self.body
        if self.content_type == "application/json":
            return json.dumps(self.body, ensure_ascii=False, default=str).encode("utf-8")
        return str(self.body).encode("utf-8")


Handler = Callable[[Workspace, Request], Response]


class Router:
    def __init__(self) -> None:
        self._routes: list[tuple[str, re.Pattern[str], Handler, str]] = []

    def add(self, method: str, pattern: str, handler: Handler, name: str = "") -> None:
        regex = re.compile(
            "^" + re.sub(r"\{(\w+)\}", lambda m: f"(?P<{m.group(1)}>[^/]+)", pattern) + "$"
        )
        self._routes.append((method.upper(), regex, handler, name or handler.__name__))

    def route(self, method: str, pattern: str, name: str = "") -> Callable[[Handler], Handler]:
        def decorator(handler: Handler) -> Handler:
            self.add(method, pattern, handler, name)
            return handler

        return decorator

    def resolve(self, method: str, path: str) -> tuple[Handler, dict[str, str], str] | None:
        allowed: set[str] = set()
        for route_method, regex, handler, name in self._routes:
            match = regex.match(path)
            if not match:
                continue
            if route_method != method.upper():
                allowed.add(route_method)
                continue
            return handler, {k: _unquote(v) for k, v in match.groupdict().items()}, name
        if allowed:
            raise NotFoundError(f"{method} is not allowed on {path}; try {', '.join(sorted(allowed))}")
        return None

    def describe(self) -> list[dict[str, str]]:
        return [
            {"method": method, "path": regex.pattern[1:-1], "name": name}
            for method, regex, _, name in self._routes
        ]


def _unquote(value: str) -> str:
    from urllib.parse import unquote

    return unquote(value)


router = Router()


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #


@router.route("GET", "/api/health")
def health(workspace: Workspace, request: Request) -> Response:
    return Response(body=workspace.health())


@router.route("GET", "/api/routes")
def routes(workspace: Workspace, request: Request) -> Response:
    return Response(body={"routes": router.describe()})


@router.route("GET", "/api/ontology")
def get_ontology(workspace: Workspace, request: Request) -> Response:
    return Response(body=workspace.ontology.to_dict())


@router.route("POST", "/api/ontology/reload")
def reload_ontology(workspace: Workspace, request: Request) -> Response:
    ontology = workspace.reload_ontology()
    return Response(body={"reloaded": True, "ontology": ontology.to_dict()})


@router.route("GET", "/api/ontology/export")
def export_ontology(workspace: Workspace, request: Request) -> Response:
    fmt = request.get("format", "owl").lower()
    if fmt in ("owl", "ttl", "turtle", "rdf"):
        return Response(
            body=ontology_to_owl(workspace.ontology),
            content_type="text/turtle",
            headers={"Content-Disposition": f'attachment; filename="{workspace.ontology.id}.ttl"'},
        )
    if fmt == "json":
        return Response(body=_as_source(workspace.ontology))
    raise ValidationError(f"Unsupported ontology export format '{fmt}' (use owl or json)")


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


@router.route("GET", "/api/settings")
def get_settings(workspace: Workspace, request: Request) -> Response:
    """Everything the settings page renders from: fields, values and provenance.

    Secrets are never included -- see Settings.redacted().
    """
    from ..kpi.metrics import DEFAULT_TARGETS
    from ..storage.registry import describe_all

    described = workspace.settings.describe()
    described["backends"] = describe_all()
    described["kpi_catalogue"] = [
        {"id": kpi_id, "name": name, "default_target": DEFAULT_TARGETS[kpi_id], "unit": unit}
        for kpi_id, name, unit in _kpi_target_catalogue()
    ]
    described["restart_required_note"] = (
        "Bind address and port are read when the server starts. Save them, then restart."
    )
    return Response(body=described)


def _kpi_target_catalogue() -> list[tuple[str, str, str]]:
    """The KPIs whose target a programme can set, with a readable name."""
    return [
        ("objective_coverage", "Objectives covered by activities", "%"),
        ("activity_ownership", "Activities with a named owner", "%"),
        ("milestone_anchoring", "Activities anchored to a milestone", "%"),
        ("process_linkage", "Activities linked to an SE process", "%"),
        ("process_utilisation", "Declared processes in use", "%"),
        ("verification_coverage", "Requirements with a verification activity", "%"),
        ("tool_linkage", "Activities linked to a tool", "%"),
        ("tool_qualification", "Tools in use with qualification settled", "%"),
        ("manual_tool_handovers", "Manual hand-overs in the tool chain", ""),
        ("high_weight_traceability", "High-weight activities fully traced", "%"),
        ("traceability_completeness", "Traceability completeness", "%"),
        ("orphan_rate", "Disconnected elements", "%"),
        ("dependency_cycles", "Circular dependencies", ""),
    ]


@router.route("PATCH", "/api/settings")
def patch_settings(workspace: Workspace, request: Request) -> Response:
    """Update settings, optionally persisting them to setm.toml.

    Fields that need the workspace rebuilt (storage, ontology, overlays) are
    applied but not acted on here: the response says so, and the page calls
    /api/settings/reopen once the user has decided what to do about unsaved work.
    """
    body = request.json_body()
    settings = workspace.settings
    values = body.get("values") or {}
    if "storage" in values or "storage_options" in values:
        # Vet the resulting target on a copy, so a refused one changes nothing.
        candidate = copy.deepcopy(settings)
        candidate.apply_update(values)
        check_remote_target(candidate.storage, candidate.storage_options, settings)
    changed = settings.apply_update(values)
    workspace.apply_settings(changed)

    needs_reopen = sorted(
        name for name in changed if FIELDS_BY_NAME[name].reopens_workspace
    )
    needs_restart = sorted(
        name for name in changed if FIELDS_BY_NAME[name].restart_required
    )

    saved_to = ""
    if body.get("persist"):
        path = settings.save_file(include_secrets=bool(body.get("include_secrets")))
        saved_to = str(path.resolve())

    telemetry.increment("settings.updated")
    return Response(
        body={
            "changed": changed,
            "needs_reopen": needs_reopen,
            "needs_restart": needs_restart,
            "unsaved_changes": workspace.store.dirty,
            "saved_to": saved_to,
            "shadowed_by_environment": settings.shadowed_by_environment(),
            "settings": settings.describe(),
        }
    )


@router.route("POST", "/api/settings/reopen")
def reopen_workspace(workspace: Workspace, request: Request) -> Response:
    """Rebuild the workspace against the current settings."""
    body = request.json_body()
    settings = workspace.settings
    if "ui" in (settings.source_of("storage"), settings.source_of("storage_options")):
        check_remote_target(settings.storage, settings.storage_options, settings)
    return Response(body=workspace.reconfigure(force=bool(body.get("force"))))


@router.route("POST", "/api/settings/test-storage")
def test_storage(workspace: Workspace, request: Request) -> Response:
    """Probe a candidate backend without switching to it.

    Lets someone confirm a GitLab project, branch and token are right before
    pointing the live workspace at them.
    """
    from ..storage.registry import open_storage

    body = request.json_body()
    uri = str(body.get("storage") or workspace.settings.storage)
    options = dict(workspace.settings.storage_options)
    for key, value in (body.get("storage_options") or {}).items():
        if value == SECRET_PLACEHOLDER:
            continue  # keep the stored credential
        if value in (None, ""):
            options.pop(key, None)
        else:
            options[key] = value

    try:
        check_remote_target(uri, options, workspace.settings)
        backend = open_storage(uri, **options)
        backend.bind_ontology(workspace.ontology)
        with telemetry.track("storage.probe", backend=backend.scheme):
            health = backend.health()
            exists = backend.exists()
    except SetmError as exc:
        return Response(body={"ok": False, "error": exc.to_dict(), "target": uri})

    ok = health.get("status") == "ok"
    return Response(
        body={
            "ok": ok,
            "target": uri,
            "describe": backend.describe(),
            "health": health,
            "has_existing_project": exists,
            "hint": (
                "Reachable, and a project is already stored there -- opening it will load that graph."
                if ok and exists
                else "Reachable, and empty -- opening it will start a new project."
                if ok
                else "Not reachable with these settings."
            ),
        }
    )


@router.route("GET", "/api/project")
def get_project(workspace: Workspace, request: Request) -> Response:
    return Response(body=workspace.store.project.to_dict())


@router.route("PATCH", "/api/project")
def patch_project(workspace: Workspace, request: Request) -> Response:
    project = workspace.store.update_project(request.json_body())
    workspace.autosave("update project header", request.actor or workspace.settings.actor)
    return Response(body=project.to_dict())


# --------------------------------------------------------------------------- #
# Graph reads
# --------------------------------------------------------------------------- #


@router.route("GET", "/api/graph")
def get_graph(workspace: Workspace, request: Request) -> Response:
    store = workspace.store
    node_types = request.get_list("type")
    edge_types = request.get_list("edge_type")
    text = request.get("q")
    limit = request.get_int("limit", 5000)

    with telemetry.track("graph.read"), store.reading():
        matched = store.find_nodes(types=node_types or None, text=text)
        payload = query.subgraph(store, (n.id for n in matched[:limit]), edge_types=edge_types or None)
        payload.update(
            {
                "project": store.project.to_dict(),
                "revision": store.revision,
                "truncated": len(matched) > limit,
                "counts": {"nodes": len(payload["nodes"]), "edges": len(payload["edges"])},
            }
        )
    return Response(body=payload)


@router.route("GET", "/api/nodes")
def list_nodes(workspace: Workspace, request: Request) -> Response:
    store = workspace.store
    nodes = store.find_nodes(types=request.get_list("type") or None, text=request.get("q"))
    nodes.sort(key=lambda n: (n.type, n.label))
    offset = request.get_int("offset", 0)
    limit = request.get_int("limit", 200)
    return Response(
        body={
            "total": len(nodes),
            "offset": offset,
            "limit": limit,
            "nodes": [n.to_dict() for n in nodes[offset : offset + limit]],
        }
    )


@router.route("POST", "/api/nodes")
def create_node(workspace: Workspace, request: Request) -> Response:
    body = request.json_body()
    if "type" not in body:
        raise ValidationError("A node needs a 'type'")
    node = workspace.store.add_node(
        str(body["type"]),
        body.get("properties") or {},
        node_id=body.get("id"),
        actor=request.actor or workspace.settings.actor,
        source=body.get("source", "ui"),
    )
    workspace.autosave(f"add {node.type} {node.label}", request.actor or workspace.settings.actor)
    telemetry.increment("graph.nodes_created", type=node.type)
    return Response(status=201, body=node.to_dict())


@router.route("GET", "/api/nodes/{node_id}")
def get_node(workspace: Workspace, request: Request) -> Response:
    node = workspace.store.node(request.params["node_id"])
    return Response(
        body={
            **node.to_dict(),
            "relations": {
                "outgoing": [e.to_dict() for e in workspace.store.out_edges(node.id)],
                "incoming": [e.to_dict() for e in workspace.store.in_edges(node.id)],
            },
        }
    )


@router.route("PATCH", "/api/nodes/{node_id}")
def patch_node(workspace: Workspace, request: Request) -> Response:
    body = request.json_body()
    node_id = request.params["node_id"]
    if "type" in body and body["type"] != workspace.store.node(node_id).type:
        workspace.store.retype_node(node_id, str(body["type"]), actor=request.actor or workspace.settings.actor)
    node = workspace.store.update_node(
        node_id,
        body.get("properties") or {},
        actor=request.actor or workspace.settings.actor,
        expected_revision=body.get("expected_revision"),
        replace=bool(body.get("replace")),
    )
    workspace.autosave(f"update {node.type} {node.label}", request.actor or workspace.settings.actor)
    return Response(body=node.to_dict())


@router.route("DELETE", "/api/nodes/{node_id}")
def delete_node(workspace: Workspace, request: Request) -> Response:
    result = workspace.store.delete_node(request.params["node_id"], cascade=request.get_bool("cascade", True))
    workspace.autosave(f"delete {request.params['node_id']}", request.actor or workspace.settings.actor)
    telemetry.increment("graph.nodes_deleted")
    return Response(body=result)


@router.route("GET", "/api/nodes/{node_id}/trace")
def trace_node(workspace: Workspace, request: Request) -> Response:
    with telemetry.track("graph.trace"):
        return Response(body=query.trace(workspace.store, request.params["node_id"], depth=request.get_int("depth", 2)))


@router.route("GET", "/api/nodes/{node_id}/context")
def node_context(workspace: Workspace, request: Request) -> Response:
    with telemetry.track("graph.context"):
        return Response(
            body=query.neighbourhood(
                workspace.store,
                request.params["node_id"],
                depth=request.get_int("depth", 1),
                direction=request.get("direction", "both"),
                edge_types=request.get_list("edge_type") or None,
                node_types=request.get_list("type") or None,
                limit=request.get_int("limit", 2000),
            )
        )


@router.route("GET", "/api/nodes/{node_id}/report")
def node_report(workspace: Workspace, request: Request) -> Response:
    """A self-contained report for one element, for a review pack or a minute."""
    fmt = request.get("format", "html").lower()
    if fmt not in REPORT_FORMATS:
        raise ValidationError(f"Unsupported report format '{fmt}' (use {', '.join(REPORT_FORMATS)})")
    with telemetry.track("report.build", format=fmt):
        report = build_report(workspace.store, request.params["node_id"], depth=request.get_int("depth", 2))
        body = render(report, fmt)

    if fmt == "json":
        return Response(body=body)
    content_type = "text/html; charset=utf-8" if fmt == "html" else "text/markdown; charset=utf-8"
    headers = {}
    # Inline by default so the browser previews it; ?download=1 saves a file.
    if request.get_bool("download", False):
        headers["Content-Disposition"] = f'attachment; filename="{safe_filename(report, fmt)}"'
    return Response(body=body, content_type=content_type, headers=headers)


@router.route("GET", "/api/nodes/{node_id}/impact")
def node_impact(workspace: Workspace, request: Request) -> Response:
    with telemetry.track("graph.impact"):
        return Response(
            body=query.impact(
                workspace.store,
                request.params["node_id"],
                direction=request.get("direction", "out"),
                max_depth=request.get_int("depth", 8),
            )
        )


# --------------------------------------------------------------------------- #
# Edges
# --------------------------------------------------------------------------- #


@router.route("GET", "/api/edges")
def list_edges(workspace: Workspace, request: Request) -> Response:
    types = set(request.get_list("type"))
    node_id = request.get("node")
    store = workspace.store
    edges = store.incident_edges(node_id) if node_id else store.edges()
    if types:
        edges = [e for e in edges if e.type in types]
    return Response(body={"total": len(edges), "edges": [e.to_dict() for e in edges]})


@router.route("GET", "/api/edges/allowed")
def allowed_edges(workspace: Workspace, request: Request) -> Response:
    """Which relations the ontology permits -- drives the UI's relation picker."""
    ontology = workspace.ontology
    source_type = request.get("source_type")
    target_type = request.get("target_type")
    if source_type and target_type:
        specs = ontology.edges_allowed_between(source_type, target_type)
    elif source_type:
        specs = ontology.edges_from(source_type)
    else:
        specs = list(ontology.edge_types.values())
    return Response(
        body={
            "edge_types": [
                {
                    **spec.to_dict(),
                    "valid_targets": sorted(
                        t.name
                        for t in ontology.concrete_node_types()
                        if ontology._type_matches(t.name, spec.range)
                    ),
                }
                for spec in specs
            ]
        }
    )


@router.route("POST", "/api/edges")
def create_edge(workspace: Workspace, request: Request) -> Response:
    body = request.json_body()
    missing = [k for k in ("type", "source", "target") if not body.get(k)]
    if missing:
        raise ValidationError(f"A relation needs {', '.join(missing)}")
    edge = workspace.store.add_edge(
        str(body["type"]),
        str(body["source"]),
        str(body["target"]),
        body.get("properties") or {},
        edge_id=body.get("id"),
        actor=request.actor or workspace.settings.actor,
        source_system=body.get("source_system", "ui"),
    )
    workspace.autosave(f"link {edge.source} -{edge.type}-> {edge.target}", request.actor or workspace.settings.actor)
    telemetry.increment("graph.edges_created", type=edge.type)
    return Response(status=201, body=edge.to_dict())


@router.route("GET", "/api/edges/{edge_id}")
def get_edge(workspace: Workspace, request: Request) -> Response:
    return Response(body=workspace.store.edge(request.params["edge_id"]).to_dict())


@router.route("PATCH", "/api/edges/{edge_id}")
def patch_edge(workspace: Workspace, request: Request) -> Response:
    body = request.json_body()
    edge = workspace.store.update_edge(
        request.params["edge_id"],
        body.get("properties") or {},
        actor=request.actor or workspace.settings.actor,
        expected_revision=body.get("expected_revision"),
    )
    workspace.autosave(f"update relation {edge.id}", request.actor or workspace.settings.actor)
    return Response(body=edge.to_dict())


@router.route("DELETE", "/api/edges/{edge_id}")
def delete_edge(workspace: Workspace, request: Request) -> Response:
    result = workspace.store.delete_edge(request.params["edge_id"])
    workspace.autosave(f"delete relation {request.params['edge_id']}", request.actor or workspace.settings.actor)
    telemetry.increment("graph.edges_deleted")
    return Response(body=result)


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #


@router.route("GET", "/api/paths")
def find_paths(workspace: Workspace, request: Request) -> Response:
    source, target = request.get("source"), request.get("target")
    if not source or not target:
        raise ValidationError("Provide both 'source' and 'target'")
    with telemetry.track("graph.paths"):
        found = query.paths(
            workspace.store,
            source,
            target,
            max_depth=request.get_int("max_depth", 6),
            directed=request.get_bool("directed", True),
        )
    return Response(body={"count": len(found), "paths": found})


@router.route("GET", "/api/views/board")
def board_view(workspace: Workspace, request: Request) -> Response:
    """Group nodes of one type by a property -- the milestone/status boards."""
    ontology = workspace.ontology
    type_name = request.get("type") or ontology.node_role("activity")
    group_by = request.get("group_by") or ontology.role("status_property", "status")
    if not type_name:
        raise ValidationError("Provide 'type' (the ontology declares no 'activity' role)")
    return Response(
        body={
            "type": type_name,
            "group_by": group_by,
            "columns": query.group_by_property(workspace.store, type_name, group_by),
        }
    )


@router.route("GET", "/api/views/trace-path/{name}")
def trace_path_view(workspace: Workspace, request: Request) -> Response:
    chain = workspace.ontology.trace_paths.get(request.params["name"])
    if chain is None:
        raise NotFoundError(
            f"No trace path '{request.params['name']}'. "
            f"Declared: {', '.join(sorted(workspace.ontology.trace_paths)) or 'none'}"
        )
    node_id = request.get("node")
    if not node_id:
        raise ValidationError("Provide 'node' as the starting element")
    return Response(
        body={
            "name": request.params["name"],
            "chain": chain,
            "results": query.related_through(workspace.store, node_id, chain),
        }
    )


@router.route("GET", "/api/validate")
def validate(workspace: Workspace, request: Request) -> Response:
    return Response(body=workspace.validate(strict=request.get_bool("strict", workspace.settings.strict)))


@router.route("GET", "/api/kpi")
def kpi(workspace: Workspace, request: Request) -> Response:
    section = request.get("section", "report")
    if section not in KPI_CATALOGUE:
        raise ValidationError(f"Unknown KPI section '{section}'. Try: {', '.join(KPI_CATALOGUE)}")
    store = workspace.store
    # One lock across the whole computation, so every KPI reads the same revision.
    with telemetry.track("kpi.compute", section=section), store.reading():
        if section == "report":
            body = compute_kpis(store, targets=workspace.settings.kpi_targets or None)
        else:
            body = KPI_CATALOGUE[section](store)
    return Response(body=body if isinstance(body, dict) else {"section": section, "items": body})


@router.route("GET", "/api/kpi/app")
def kpi_app(workspace: Workspace, request: Request) -> Response:
    """Application performance KPIs, as opposed to project KPIs."""
    snapshot = telemetry.snapshot()
    snapshot["graph"] = workspace.store.stats()
    snapshot["hotspots"] = [
        {"id": node_id, "degree": degree} for node_id, degree in degree_centrality(workspace.store, top=10)
    ]
    return Response(body=snapshot)


@router.route("GET", "/metrics")
def prometheus_metrics(workspace: Workspace, request: Request) -> Response:
    return Response(body=telemetry.prometheus(), content_type="text/plain; version=0.0.4")


# --------------------------------------------------------------------------- #
# Persistence and exchange
# --------------------------------------------------------------------------- #


@router.route("POST", "/api/save")
def save(workspace: Workspace, request: Request) -> Response:
    body = request.json_body()
    result = workspace.save(
        message=str(body.get("message") or ""),
        actor=request.actor or workspace.settings.actor,
        force=bool(body.get("force")),
    )
    return Response(body=result.to_dict())


@router.route("POST", "/api/reload")
def reload(workspace: Workspace, request: Request) -> Response:
    workspace.reload()
    return Response(body={"reloaded": True, "graph": workspace.store.stats()})


@router.route("GET", "/api/export")
def export(workspace: Workspace, request: Request) -> Response:
    fmt = request.get("format", "json").lower()
    document = workspace.store.snapshot()
    stem = (document.project.id or "project").replace(" ", "_")
    if fmt == "json":
        return Response(
            body=document.to_dict(),
            headers={"Content-Disposition": f'attachment; filename="{stem}.json"'},
        )
    if fmt in ("ttl", "turtle", "rdf"):
        return Response(
            body=document_to_turtle(document, workspace.ontology),
            content_type="text/turtle",
            headers={"Content-Disposition": f'attachment; filename="{stem}.ttl"'},
        )
    if fmt == "owl":
        return Response(body=ontology_to_owl(workspace.ontology), content_type="text/turtle")
    if fmt == "csv":
        tables = tables_to_csv(document_to_tables(document, workspace.ontology))
        sheet = request.get("sheet")
        if sheet:
            if sheet not in tables:
                raise NotFoundError(f"No table '{sheet}'. Available: {', '.join(sorted(tables))}")
            return Response(
                body=tables[sheet],
                content_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{stem}_{sheet}.csv"'},
            )
        return Response(body={"tables": tables})
    raise ValidationError(f"Unsupported export format '{fmt}' (json, ttl, owl, csv)")


@router.route("POST", "/api/import")
def import_graph(workspace: Workspace, request: Request) -> Response:
    body = request.json_body()
    merge = bool(body.get("merge"))
    if "turtle" in body:
        document = turtle_to_document(str(body["turtle"]), workspace.ontology)
    elif "document" in body:
        document = GraphDocument.from_dict(body["document"])
    else:
        raise ValidationError("Send either 'document' (JSON graph) or 'turtle' (Turtle text)")
    result = workspace.import_document(document, merge=merge, actor=request.actor or workspace.settings.actor)
    workspace.autosave("import graph", request.actor or workspace.settings.actor)
    return Response(body={**result, "validation": workspace.validate()})


@router.route("GET", "/api/examples")
def list_examples(workspace: Workspace, request: Request) -> Response:
    """The worked examples that ship with SETM, for the Settings page's loader."""
    return Response(body={"examples": [
        {"name": name, "label": spec["label"], "description": spec["description"]}
        for name, spec in EXAMPLES.items()
    ]})


@router.route("POST", "/api/examples/load")
def load_example(workspace: Workspace, request: Request) -> Response:
    """Replace the current graph with a freshly-built worked example."""
    body = request.json_body()
    name = str(body.get("name") or "")
    if name not in EXAMPLES:
        raise ValidationError(f"Unknown example '{name}'. Try: {', '.join(EXAMPLES)}")
    document = EXAMPLES[name]["build"](workspace.ontology)
    result = workspace.import_document(document, merge=False, actor=request.actor or workspace.settings.actor)
    workspace.autosave(f"load example: {name}", request.actor or workspace.settings.actor)
    return Response(body={**result, "validation": workspace.validate()})


def error_response(exc: Exception) -> Response:
    if isinstance(exc, SetmError):
        telemetry.increment("http.errors", code=exc.code)
        return Response(status=exc.status, body={"error": exc.to_dict()})
    telemetry.increment("http.errors", code="internal")
    # The detail goes to the server log, not to the client: an exception message
    # can carry file paths, configuration and fragments of stored data.
    logger.exception("Unhandled error while serving a request")
    return Response(
        status=500,
        body={"error": {"code": "internal_error", "message": "Internal error -- see the server log for details"}},
    )


def dispatch(workspace: Workspace, request: Request) -> Response:
    """Resolve and run a route, converting SETM errors into JSON responses."""
    try:
        resolved = router.resolve(request.method, request.path)
        if resolved is None:
            raise NotFoundError(f"No API route for {request.method} {request.path}")
        handler, params, name = resolved
        request.params = params
        with telemetry.track("http.request", route=name):
            telemetry.increment("http.requests", route=name)
            return handler(workspace, request)
    except Exception as exc:  # converted, never propagated to the socket layer
        return error_response(exc)


def known_paths() -> Iterable[str]:
    return sorted({route["path"] for route in router.describe()})


__all__ = ["Request", "Response", "Router", "dispatch", "router", "require_token", "ConfigError"]
