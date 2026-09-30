"""Projects: the start page, creating (empty, from an example, from a file),
opening and switching -- and the Light / Full / Custom presets a new project
chooses its element types and relations from."""

from __future__ import annotations

import json

import pytest

from setm.api.routes import Request, dispatch
from setm.cli import main
from setm.config import Settings
from setm.errors import OntologyError, ValidationError
from setm.model import GraphDocument
from setm.workspace import Workspace, normalise_profile

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


# --------------------------------------------------------------------------- #
# The start page: nothing open until the user chooses
# --------------------------------------------------------------------------- #


@pytest.fixture
def settings(tmp_path):
    return Settings(
        storage=f"json:{tmp_path / 'configured.json'}",
        projects_dir=str(tmp_path / "projects"),
        master_ontology=str(tmp_path / "master.json"),
        config_path=str(tmp_path / "setm.toml"),
    )


@pytest.fixture
def blank(settings):
    return Workspace.blank(settings)


def call(workspace, method, path, body=None):
    response = dispatch(workspace, Request(method=method, path=path, body=body, headers={}))
    return response.status, response.body


def test_blank_workspace_has_no_project(blank):
    status, body = call(blank, "GET", "/api/health")
    assert status == 200 and body["project_open"] is False
    for method, path in [("GET", "/api/graph"), ("POST", "/api/nodes"), ("GET", "/api/kpi"), ("POST", "/api/save")]:
        status, body = call(blank, method, path, {"type": "Person", "properties": {"name": "x"}})
        assert status == 409 and "No project is open" in body["error"]["message"], path
    # What the start page needs still works.
    assert call(blank, "GET", "/api/projects")[0] == 200
    assert call(blank, "GET", "/api/ontologies")[0] == 200
    assert call(blank, "GET", "/api/examples")[0] == 200
    assert call(blank, "GET", "/api/ontologies/catalogue")[0] == 200


def test_create_a_light_project_with_additions_from_the_start_page(blank):
    status, body = call(blank, "POST", "/api/projects", {
        "name": "Cabin Retrofit B",
        "programme": "RENEW",
        "preset": "light",
        "additions": {
            "element_types": [{"label": "Test rig", "category": "What",
                               "properties": [{"label": "Rig class", "type": "enum", "values": "A, B"}]}],
            "relations": [{"label": "tested on", "domain": ["Activity"], "range": ["TestRig"], "question": "how"}],
        },
    })
    assert status == 201, body
    assert blank.is_open and blank.store.project.name == "Cabin Retrofit B"
    concrete = {t.name for t in blank.ontology.concrete_node_types()}
    assert concrete == LIGHT_TYPES | {"TestRig"}
    assert blank.ontology.edge_types["TESTED_ON"].range == ["TestRig"]
    assert blank.store.project.profile == {"preset": "custom"}  # Light, plus its own
    # Now the project routes work.
    assert call(blank, "POST", "/api/nodes", {"type": "TestRig", "properties": {"name": "Rig 1", "rig_class": "A"}})[0] == 201
    assert call(blank, "POST", "/api/nodes", {"type": "Tool", "properties": {"name": "CAD"}})[0] == 400


def test_a_new_project_never_uses_a_master_name_for_its_own_type(blank):
    status, body = call(blank, "POST", "/api/projects", {
        "name": "X", "preset": "light", "additions": {"element_types": [{"label": "Tool"}]},
    })
    assert status == 409 and "from the master" in body["error"]["message"]
    assert not blank.is_open


def test_load_an_example_as_a_new_project(blank):
    status, body = call(blank, "POST", "/api/examples/load", {"name": "payload"})
    assert status == 200 and body["nodes"] == 86
    assert blank.is_open and "projects" in blank.settings.storage
    # Loading the other one does not overwrite the first: both are listed.
    call(blank, "POST", "/api/examples/load", {"name": "modification"})
    names = [p["name"] for p in call(blank, "GET", "/api/projects")[1]["projects"]]
    assert len([n for n in names if n]) >= 2 and names[0].startswith("Voyager")


def test_import_a_file_as_a_new_project(blank, demo_document, tmp_path):
    status, body = call(blank, "POST", "/api/projects", {"name": "Imported", "document": demo_document.to_dict()})
    assert status == 201 and blank.store.node_count == 86
    # A project file without an ontology of its own gets a full copy of the master.
    assert len(blank.ontology.concrete_node_types()) == 16


def test_configured_project_is_listed_but_not_opened(settings, demo_document):
    from setm.storage.registry import open_storage

    open_storage(settings.storage).save(demo_document)
    workspace = Workspace.blank(settings)
    projects = call(workspace, "GET", "/api/projects")[1]["projects"]
    assert [p["name"] for p in projects] == [demo_document.project.name]
    assert not projects[0]["current"] and not workspace.is_open
    status, _ = call(workspace, "POST", "/api/projects/open", {"storage": settings.storage})
    assert status == 200 and workspace.is_open and workspace.store.node_count == 86


def test_switching_projects_and_the_way_back(blank):
    call(blank, "POST", "/api/projects", {"name": "First", "preset": "light"})
    first = blank.settings.storage
    call(blank, "POST", "/api/projects", {"name": "Second", "preset": "full"})
    listing = call(blank, "GET", "/api/projects")[1]["projects"]
    assert listing[0]["name"] == "Second" and listing[0]["current"]
    status, _ = call(blank, "POST", "/api/projects/open", {"storage": first})
    assert status == 200 and blank.store.project.name == "First"
    # Most recently opened first.
    assert [p["name"] for p in call(blank, "GET", "/api/projects")[1]["projects"]][:2] == ["First", "Second"]


def test_only_listed_projects_can_be_opened(blank):
    assert call(blank, "POST", "/api/projects/open", {"storage": "json:/etc/passwd"})[0] == 404


def test_project_names_cannot_escape_the_projects_folder(blank, tmp_path):
    status, body = call(blank, "POST", "/api/projects", {"name": "../../etc/evil", "open": False})
    assert status == 201
    created = body["created"]["storage"].split(":", 1)[1]
    assert created.startswith(str(tmp_path)) and "/../" not in created


def test_switching_with_unsaved_work_needs_force(blank):
    call(blank, "POST", "/api/projects", {"name": "Other", "open": False})
    call(blank, "POST", "/api/projects", {"name": "Here"})
    blank.settings.autosave = False
    blank.store.add_node("Person", {"name": "Unsaved"})
    other = next(p for p in call(blank, "GET", "/api/projects")[1]["projects"] if p["name"] == "Other")
    status, _ = call(blank, "POST", "/api/projects/open", {"storage": other["storage"]})
    assert status == 409 and blank.store.node_count == 1
    status, _ = call(blank, "POST", "/api/projects/open", {"storage": other["storage"], "force": True})
    assert status == 200 and blank.store.node_count == 0


@pytest.mark.parametrize("body,fragment", [
    ({"name": ""}, "name"),
    ({"name": "X", "format": "exe"}, "format"),
    ({"name": "X", "node_types": ["Wormhole"]}, "Wormhole"),
    ({"name": "X", "example": "nope"}, "nope"),
])
def test_bad_create_requests_are_refused(blank, body, fragment):
    status, response = call(blank, "POST", "/api/projects", body)
    assert status >= 400 and fragment in response["error"]["message"]
    assert not blank.is_open


def test_sqlite_projects(blank):
    status, body = call(blank, "POST", "/api/projects", {"name": "Rig", "format": "sqlite", "preset": "full"})
    assert status == 201 and body["created"]["storage"].startswith("sqlite:")
    assert blank.backend.scheme == "sqlite"


def test_cli_init_with_a_profile(tmp_path):
    target = tmp_path / "light.json"
    assert main(["init", f"json:{target}", "--name", "Light probe", "--profile", "light"]) == 0
    saved = json.loads(target.read_text())
    assert saved["project"]["profile"] == {"preset": "light"}
    assert set(saved["ontology"]["node_types"]) == LIGHT_TYPES | {"Thing"}


def test_serve_without_a_target_starts_blank(monkeypatch):
    from setm import cli

    captured = {}
    monkeypatch.setattr("setm.api.server.serve", lambda workspace, settings: captured.setdefault("ws", workspace))
    cli.main(["serve"])
    assert captured["ws"].is_open is False
