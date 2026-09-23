"""Projects created in the interface, and the profile that picks a project's
element types and relations (Light, Full, Custom)."""

from __future__ import annotations

import json

import pytest

from setm.api.routes import Request, dispatch
from setm.cli import main
from setm.config import Settings
from setm.errors import ConflictError, OntologyError, ValidationError
from setm.model import GraphDocument, Node, ProjectInfo
from setm.serialize.tabular import document_to_tables, tables_to_document
from setm.storage.registry import open_storage
from setm.workspace import Workspace, effective_ontology, normalise_profile

LIGHT_TYPES = {"Objective", "Requirement", "Risk", "Activity", "Deliverable", "Person", "WorkPackage", "Milestone"}


# --------------------------------------------------------------------------- #
# The ontology side: presets and restriction
# --------------------------------------------------------------------------- #


def test_light_preset_is_declared_in_the_ontology(ontology):
    nodes, edges = ontology.resolve_profile({"preset": "light"})
    assert nodes == LIGHT_TYPES
    # Every relation of the Light set joins two Light types, and none is missed.
    restricted = ontology.restricted(nodes, edges)
    assert set(restricted.edge_types) == edges
    for name, spec in ontology.edge_types.items():
        joins_light = ontology._ends_available(spec, nodes)
        assert (name in edges) == joins_light, name


def test_full_preset_and_no_profile_mean_everything(ontology):
    assert ontology.resolve_profile({"preset": "full"}) is None
    assert ontology.resolve_profile({}) is None
    assert ontology.resolve_profile(None) is None


def test_unknown_names_are_rejected_when_strict_and_skipped_when_not(ontology):
    with pytest.raises(OntologyError, match="Wormhole"):
        ontology.resolve_profile({"node_types": ["Activity", "Wormhole"]})
    with pytest.raises(OntologyError, match="unknown profile|Unknown profile"):
        ontology.resolve_profile({"preset": "gigantic"})
    nodes, _ = ontology.resolve_profile({"node_types": ["Activity", "Wormhole"]}, strict=False)
    assert nodes == {"Activity"}


def test_restricted_keeps_ancestors_prunes_ends_and_drops_open_edges(ontology):
    restricted = ontology.restricted({"Activity", "Tool"}, {"USES_TOOL", "SUPPORTS", "DEPENDS_ON"})
    # Thing is the abstract ancestor every type extends: kept, not offered.
    assert set(restricted.node_types) == {"Activity", "Tool", "Thing"}
    assert [t.name for t in restricted.concrete_node_types()] == ["Activity", "Tool"]
    assert "USES_TOOL" in restricted.edge_types
    # SUPPORTS needs an Objective at the far end: an empty range would mean
    # "anything", so the relation is dropped rather than widened.
    assert "SUPPORTS" not in restricted.edge_types
    # DEPENDS_ON keeps only the ends that survive.
    assert restricted.edge_types["DEPENDS_ON"].range == ["Activity"]
    assert "Deliverable" in ontology.edge_types["DEPENDS_ON"].range  # the original is untouched
    # Trace paths through a dropped relation go with it.
    assert all(
        step.lstrip("~") in restricted.edge_types for chain in restricted.trace_paths.values() for step in chain
    )
    assert "activity_to_tools" in restricted.trace_paths
    assert "activity_to_objective" not in restricted.trace_paths


def test_restricted_ontology_validates_writes(ontology, empty_store):
    from setm.graph.store import GraphStore

    store = GraphStore(GraphDocument(), ontology.restricted(LIGHT_TYPES, set()))
    store.add_node("Activity", {"name": "Plan"})
    with pytest.raises(OntologyError, match="Unknown node type 'Tool'"):
        store.add_node("Tool", {"name": "CAD"})


def test_normalise_profile(ontology):
    assert normalise_profile(ontology, {"preset": "full"}) == {"preset": "full"}
    assert normalise_profile(ontology, None) == {"preset": "full"}
    light = normalise_profile(ontology, {"preset": "light"})
    assert light["preset"] == "light" and set(light["node_types"]) == LIGHT_TYPES and light["edge_types"]
    custom = normalise_profile(ontology, {"node_types": ["Activity", "Tool"]})
    # Relations not listed: every one whose two ends are selected.
    assert custom == {
        "preset": "custom",
        "node_types": ["Activity", "Tool"],
        "edge_types": ["DEPENDS_ON", "EXCHANGES_DATA_WITH", "USES_TOOL"],
    }
    with pytest.raises(ValidationError, match="at least one"):
        normalise_profile(ontology, {"preset": "custom", "node_types": []})


def test_effective_ontology_never_hides_data(ontology):
    document = GraphDocument(
        project=ProjectInfo(profile={"preset": "light", "node_types": ["Activity"], "edge_types": []}),
        nodes=[Node(id="t1", type="Tool", properties={"name": "CAD"})],
    )
    effective = effective_ontology(ontology, document)
    assert "Activity" in effective.node_types and "Tool" in effective.node_types  # widened by the data


# --------------------------------------------------------------------------- #
# The profile travels with the project, through every kind of storage
# --------------------------------------------------------------------------- #


def _profiled_document(ontology):
    return GraphDocument(project=ProjectInfo(name="P", profile=normalise_profile(ontology, {"preset": "light"})))


@pytest.mark.parametrize("scheme,filename", [("json", "p.json"), ("sqlite", "p.db"), ("rdf", "p.ttl")])
def test_profile_round_trips_through_file_backends(tmp_path, ontology, scheme, filename):
    document = _profiled_document(ontology)
    backend = open_storage(f"{scheme}:{tmp_path / filename}")
    backend.bind_ontology(ontology)
    backend.save(document)
    assert backend.load().project.profile == document.project.profile


def test_profile_round_trips_through_spreadsheet_tables(ontology):
    document = _profiled_document(ontology)
    assert tables_to_document(document_to_tables(document, ontology), ontology).project.profile == document.project.profile


def test_documents_without_a_profile_still_load(ontology):
    assert GraphDocument.from_dict({"project": {"name": "Old"}}).project.profile == {}


# --------------------------------------------------------------------------- #
# Workspace and API
# --------------------------------------------------------------------------- #


@pytest.fixture
def ws(tmp_path):
    settings = Settings(
        storage=f"json:{tmp_path / 'start.json'}",
        projects_dir=str(tmp_path / "projects"),
        config_path=str(tmp_path / "setm.toml"),
    )
    workspace = Workspace.open(settings)
    workspace.store.add_node("Person", {"name": "Ada"})
    workspace.save()
    return workspace


def call(workspace, method, path, body=None):
    response = dispatch(workspace, Request(method=method, path=path, body=body, headers={}))
    return response.status, response.body


def test_configuration_describes_presets_catalogue_and_usage(ws):
    status, body = call(ws, "GET", "/api/project/configuration")
    assert status == 200
    assert body["profile"] == {"preset": "full"}
    assert {p["name"] for p in body["presets"]} >= {"light", "full"}
    person = next(t for t in body["catalogue"]["node_types"] if t["name"] == "Person")
    assert person["in_use"] == 1 and person["category"] == "Who"
    assert len(body["catalogue"]["node_types"]) == 16 and len(body["catalogue"]["edge_types"]) == 30


def test_customising_restricts_the_project_and_refuses_in_use_types(ws):
    status, body = call(ws, "PUT", "/api/project/configuration", {"preset": "custom", "node_types": ["Activity"]})
    assert status == 409
    assert "Person" in body["error"]["message"]

    status, body = call(ws, "PUT", "/api/project/configuration", {"preset": "light"})
    assert status == 200 and body["profile"]["preset"] == "light"
    assert set(call(ws, "GET", "/api/ontology")[1]["node_types"]) == LIGHT_TYPES | {"Thing"}
    status, body = call(ws, "POST", "/api/nodes", {"type": "Tool", "properties": {"name": "CAD"}})
    assert status == 400

    # Saved with the project: a fresh workspace on the same file is still Light.
    reopened = Workspace.open(ws.settings)
    assert set(t.name for t in reopened.ontology.concrete_node_types()) == LIGHT_TYPES


def test_create_list_and_switch_projects(ws, tmp_path):
    status, body = call(ws, "POST", "/api/projects", {"name": "Cabin Retrofit B", "preset": "light", "programme": "RENEW"})
    assert status == 201
    created = body["created"]["storage"]
    assert created.endswith("projects/cabin-retrofit-b.json")
    assert ws.settings.storage == created and ws.store.node_count == 0
    assert ws.store.project.profile["preset"] == "light"

    # Same name again: a new file, never an overwrite.
    status, body = call(ws, "POST", "/api/projects", {"name": "Cabin Retrofit B", "open": False})
    assert body["created"]["storage"].endswith("cabin-retrofit-b-2.json")

    listing = call(ws, "GET", "/api/projects")[1]["projects"]
    names = [p["name"] for p in listing]
    assert names[0] == "Cabin Retrofit B" and listing[0]["current"]
    # The project we came from is still reachable, although it lives elsewhere.
    original = next(p for p in listing if p["storage"].endswith("start.json"))
    assert original["elements"] == 1

    status, body = call(ws, "POST", "/api/projects/open", {"storage": original["storage"]})
    assert status == 200 and ws.store.node_count == 1
    # "Open next time" was recorded in the settings file.
    assert original["storage"] in (tmp_path / "setm.toml").read_text()


def test_only_listed_projects_can_be_opened(ws):
    status, _ = call(ws, "POST", "/api/projects/open", {"storage": "json:/etc/passwd"})
    assert status == 404


def test_project_names_cannot_escape_the_projects_folder(ws, tmp_path):
    status, body = call(ws, "POST", "/api/projects", {"name": "../../etc/evil", "open": False})
    assert status == 201
    created = body["created"]["storage"].split(":", 1)[1]
    assert created.startswith(str(tmp_path / "projects"))
    assert "/../" not in created


def test_switching_with_unsaved_work_needs_force(ws):
    call(ws, "POST", "/api/projects", {"name": "Other", "open": False})
    ws.settings.autosave = False
    ws.store.add_node("Person", {"name": "Unsaved"})
    other = next(p for p in call(ws, "GET", "/api/projects")[1]["projects"] if p["name"] == "Other")
    status, body = call(ws, "POST", "/api/projects/open", {"storage": other["storage"]})
    assert status == 409 and ws.store.node_count == 2
    status, _ = call(ws, "POST", "/api/projects/open", {"storage": other["storage"], "force": True})
    assert status == 200 and ws.store.node_count == 0


@pytest.mark.parametrize("body,fragment", [
    ({"name": ""}, "name"),
    ({"name": "X", "format": "exe"}, "format"),
    ({"name": "X", "node_types": ["Wormhole"]}, "Wormhole"),
])
def test_bad_create_requests_are_refused(ws, body, fragment):
    status, response = call(ws, "POST", "/api/projects", body)
    assert status >= 400 and fragment in response["error"]["message"]


def test_sqlite_projects(ws):
    status, body = call(ws, "POST", "/api/projects", {"name": "Rig", "format": "sqlite", "preset": "full"})
    assert status == 201 and body["created"]["storage"].startswith("sqlite:")
    assert ws.backend.scheme == "sqlite" and ws.store.project.profile == {"preset": "full"}


def test_cli_init_with_a_profile(tmp_path):
    target = tmp_path / "light.json"
    assert main(["init", f"json:{target}", "--name", "Light probe", "--profile", "light"]) == 0
    profile = json.loads(target.read_text())["project"]["profile"]
    assert profile["preset"] == "light" and set(profile["node_types"]) == LIGHT_TYPES


def test_set_profile_directly_reports_what_is_in_use(ws):
    with pytest.raises(ConflictError) as info:
        ws.set_profile({"preset": "custom", "node_types": ["Activity"]})
    assert info.value.details["in_use"]["node_types"] == {"Person": 1}
