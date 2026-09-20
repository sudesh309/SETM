"""API routes, exercised through dispatch() so no socket is needed."""

from __future__ import annotations

import json

import pytest

from setm.api.routes import Request, dispatch, require_token


def call(workspace, method, path, body=None, **query):
    request = Request(
        method=method,
        path=path,
        query={k: [str(v)] for k, v in query.items()},
        body=body,
        headers={"x-setm-user": "tester"},
    )
    return dispatch(workspace, request)


def test_health_reports_storage_and_ontology(workspace):
    response = call(workspace, "GET", "/api/health")
    assert response.status == 200
    assert response.body["storage"]["scheme"] == "memory"
    assert response.body["ontology"]["id"] == "aerospace-se-core"


def test_unknown_route_is_404(workspace):
    assert call(workspace, "GET", "/api/nope").status == 404


def test_wrong_method_reports_what_is_allowed(workspace):
    response = call(workspace, "DELETE", "/api/health")
    assert response.status == 404
    assert "GET" in response.body["error"]["message"]


def test_create_read_update_delete_node(workspace):
    created = call(workspace, "POST", "/api/nodes", {"type": "Activity", "properties": {"name": "Write the plan"}})
    assert created.status == 201
    node_id = created.body["id"]
    assert created.body["provenance"]["created_by"] == "tester"

    fetched = call(workspace, "GET", f"/api/nodes/{node_id}")
    assert fetched.body["properties"]["name"] == "Write the plan"

    updated = call(workspace, "PATCH", f"/api/nodes/{node_id}", {"properties": {"status": "in_progress"}})
    assert updated.body["properties"]["status"] == "in_progress"

    deleted = call(workspace, "DELETE", f"/api/nodes/{node_id}")
    assert deleted.body["deleted_node"] == node_id
    assert call(workspace, "GET", f"/api/nodes/{node_id}").status == 404


def test_validation_error_becomes_422(workspace):
    response = call(workspace, "POST", "/api/nodes", {"type": "Activity", "properties": {}})
    assert response.status == 422
    assert response.body["error"]["code"] == "validation_error"
    assert response.body["error"]["issues"]


def test_unknown_type_is_rejected(workspace):
    response = call(workspace, "POST", "/api/nodes", {"type": "Wormhole", "properties": {"name": "x"}})
    assert response.status == 400
    assert "Unknown node type" in response.body["error"]["message"]


def test_node_without_type_is_rejected(workspace):
    assert call(workspace, "POST", "/api/nodes", {"properties": {"name": "x"}}).status == 422


def test_edge_creation_and_constraints(workspace):
    person = call(workspace, "POST", "/api/nodes", {"type": "Person", "properties": {"name": "Ada"}}).body
    activity = call(workspace, "POST", "/api/nodes", {"type": "Activity", "properties": {"name": "Task"}}).body

    ok = call(workspace, "POST", "/api/edges", {"type": "RESPONSIBLE_FOR", "source": person["id"], "target": activity["id"]})
    assert ok.status == 201

    reversed_edge = call(
        workspace, "POST", "/api/edges",
        {"type": "RESPONSIBLE_FOR", "source": activity["id"], "target": person["id"]},
    )
    assert reversed_edge.status == 422
    assert "cannot start at" in reversed_edge.body["error"]["message"]


def test_edge_to_missing_node_is_404(workspace):
    activity = call(workspace, "POST", "/api/nodes", {"type": "Activity", "properties": {"name": "T"}}).body
    response = call(workspace, "POST", "/api/edges", {"type": "DEPENDS_ON", "source": activity["id"], "target": "ghost"})
    assert response.status == 404


def test_allowed_edges_is_filtered_by_source_type(workspace):
    response = call(workspace, "GET", "/api/edges/allowed", source_type="Activity")
    names = {e["name"] for e in response.body["edge_types"]}
    assert "DELIVERS_AT" in names
    assert "RESPONSIBLE_FOR" not in names  # that starts at a Person
    delivers = next(e for e in response.body["edge_types"] if e["name"] == "DELIVERS_AT")
    assert delivers["valid_targets"] == ["Milestone"]


def test_trace_and_context(demo_workspace):
    trace = call(demo_workspace, "GET", "/api/nodes/act.mtf/trace")
    assert trace.status == 200
    assert "who" in trace.body["questions"]

    context = call(demo_workspace, "GET", "/api/nodes/act.mtf/context", depth=1)
    assert context.body["root"] == "act.mtf"
    assert len(context.body["nodes"]) > 1


def test_paths_requires_both_endpoints(demo_workspace):
    assert call(demo_workspace, "GET", "/api/paths", source="act.mtf").status == 422
    found = call(demo_workspace, "GET", "/api/paths", source="per.laurent", target="obj.gsd")
    assert found.body["count"] > 0


def test_board_view_groups_by_status(demo_workspace):
    response = call(demo_workspace, "GET", "/api/views/board", type="Activity", group_by="status")
    assert "in_progress" in response.body["columns"]


def test_trace_path_view(demo_workspace):
    response = call(demo_workspace, "GET", "/api/views/trace-path/milestone_to_owners", node="ms.pdr")
    assert response.status == 200
    assert response.body["results"]
    assert call(demo_workspace, "GET", "/api/views/trace-path/nonsense", node="ms.pdr").status == 404


def test_kpi_report_and_sections(demo_workspace):
    report = call(demo_workspace, "GET", "/api/kpi")
    assert report.body["health_score"]["value"] is not None
    assert {k["id"] for k in report.body["kpis"]} >= {"objective_coverage", "activity_ownership"}

    milestones = call(demo_workspace, "GET", "/api/kpi", section="milestone_load")
    assert milestones.body["items"][0]["gate"] == "SRR"

    assert call(demo_workspace, "GET", "/api/kpi", section="nonsense").status == 422


def test_app_kpi_and_prometheus(demo_workspace):
    call(demo_workspace, "GET", "/api/health")
    app_kpi = call(demo_workspace, "GET", "/api/kpi/app")
    assert app_kpi.body["summary"]["requests_total"] > 0
    assert "operations" in app_kpi.body

    metrics = call(demo_workspace, "GET", "/metrics")
    assert metrics.content_type.startswith("text/plain")
    assert "setm_http_requests" in metrics.body


def test_validate_endpoint(demo_workspace):
    response = call(demo_workspace, "GET", "/api/validate")
    assert response.body["valid"] is True
    assert response.body["node_count"] > 0


def test_export_formats(demo_workspace):
    assert call(demo_workspace, "GET", "/api/export", format="json").body["nodes"]
    turtle = call(demo_workspace, "GET", "/api/export", format="ttl")
    assert turtle.content_type == "text/turtle"
    assert "@prefix" in turtle.body
    csv = call(demo_workspace, "GET", "/api/export", format="csv")
    assert "Activity" in csv.body["tables"]
    assert call(demo_workspace, "GET", "/api/export", format="xlsx").status == 422


def test_import_replaces_graph(workspace, demo_document):
    response = call(workspace, "POST", "/api/import", {"document": demo_document.to_dict()})
    assert response.status == 200
    assert response.body["nodes"] == len(demo_document.nodes)
    assert response.body["validation"]["valid"] is True


def test_import_accepts_turtle(workspace, demo_document, ontology):
    from setm.serialize.rdfmap import document_to_turtle

    response = call(workspace, "POST", "/api/import", {"turtle": document_to_turtle(demo_document, ontology)})
    assert response.body["nodes"] == len(demo_document.nodes)


def test_import_without_payload_is_rejected(workspace):
    assert call(workspace, "POST", "/api/import", {}).status == 422


def test_project_patch(workspace):
    response = call(workspace, "PATCH", "/api/project", {"name": "Skylark", "chief_engineer": "R. Mehta"})
    assert response.body["name"] == "Skylark"
    assert call(workspace, "GET", "/api/project").body["chief_engineer"] == "R. Mehta"


def test_save_and_reload_cycle(workspace):
    call(workspace, "POST", "/api/nodes", {"type": "Activity", "properties": {"name": "Persisted"}})
    saved = call(workspace, "POST", "/api/save", {"message": "test save"})
    assert saved.body["ok"] is True
    reloaded = call(workspace, "POST", "/api/reload", {})
    assert reloaded.body["graph"]["nodes"] == 1


def test_ontology_export(workspace):
    owl = call(workspace, "GET", "/api/ontology/export", format="owl")
    assert owl.content_type == "text/turtle"
    assert call(workspace, "GET", "/api/ontology/export", format="json").body["node_types"]
    assert call(workspace, "GET", "/api/ontology/export", format="pdf").status == 422


def test_token_guard():
    request = Request(method="GET", path="/api/health", headers={})
    assert require_token(request, "") is None
    assert require_token(request, "secret").status == 401
    allowed = Request(method="GET", path="/api/health", headers={"x-setm-token": "secret"})
    assert require_token(allowed, "secret") is None


def test_response_serialises_json():
    from setm.api.routes import Response

    assert json.loads(Response(body={"a": 1}).rendered()) == {"a": 1}
