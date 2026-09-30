"""Two ontologies: the master, and each project's own copy -- and comparing
and merging between them, in both directions."""

from __future__ import annotations

import json

import pytest

from setm.api.routes import Request, dispatch
from setm.config import Settings
from setm.errors import ConflictError, ValidationError
from setm.model import Edge, GraphDocument, Node, ProjectInfo
from setm.ontology import project as po
from setm.ontology.compare import compare, plan_merge
from setm.ontology.loader import ontology_to_source
from setm.ontology.master import bump_version, load_master, save_master
from setm.serialize.tabular import document_to_tables, tables_to_document
from setm.storage.registry import open_storage
from setm.workspace import Workspace, project_ontology_for

LIGHT = {"Objective", "Requirement", "Risk", "Activity", "Deliverable", "Person", "WorkPackage", "Milestone"}


@pytest.fixture
def settings(tmp_path):
    return Settings(
        storage=f"json:{tmp_path / 'p.json'}",
        projects_dir=str(tmp_path / "projects"),
        master_ontology=str(tmp_path / "ontologies" / "master.json"),
    )


@pytest.fixture
def light_ws(settings):
    """An open project using the Light element types, plus one of its own."""
    ws = Workspace.open(settings)
    nodes, edges = ws.master.resolve_profile({"preset": "light"})
    ws.change_project_ontology(po.from_selection(ws.master, nodes, edges))
    source, _ = po.upsert_element_type(
        ws.project_source,
        {"label": "Test rig", "category": "What", "properties": [{"label": "Rig class", "type": "enum", "values": "A,B"}]},
        master=ws.master,
    )
    ws.change_project_ontology(source)
    source, _ = po.upsert_relation(
        ws.project_source, {"label": "tested on", "domain": ["Activity"], "range": ["TestRig"], "question": "how"},
        master=ws.master,
    )
    ws.change_project_ontology(source)
    return ws


def call(workspace, method, path, body=None):
    response = dispatch(workspace, Request(method=method, path=path, body=body, headers={}))
    return response.status, response.body


# --------------------------------------------------------------------------- #
# The master
# --------------------------------------------------------------------------- #


def test_master_starts_as_the_shipped_template_and_is_seeded_on_first_write(settings, tmp_path):
    master = load_master(settings)
    assert master.id == "aerospace-se-core" and not (tmp_path / "ontologies" / "master.json").exists()
    saved = save_master(settings, ontology_to_source(master))
    path = tmp_path / "ontologies" / "master.json"
    assert path.is_file() and saved.version == bump_version(master.version)
    assert json.loads(path.read_text())["ontology"]["version"] == saved.version
    assert load_master(settings).version == saved.version  # the file wins from now on
    assert not list(path.parent.glob(".master-*"))  # no temp files left behind


def test_a_broken_master_is_never_written(settings, tmp_path):
    source = ontology_to_source(load_master(settings))
    source["edge_types"]["SUPPORTS"]["domain"] = ["NoSuchType"]
    with pytest.raises(Exception):
        save_master(settings, source)
    assert not (tmp_path / "ontologies" / "master.json").exists()


@pytest.mark.parametrize("given,expected", [("1.1.0", "1.1.1"), ("2", "3"), ("draft", "draft.1"), ("", "1.0.0.1")])
def test_bump_version(given, expected):
    assert bump_version(given) == expected


# --------------------------------------------------------------------------- #
# The project's copy
# --------------------------------------------------------------------------- #


def test_legacy_documents_get_a_copy_restricted_by_their_profile(ontology):
    document = GraphDocument(project=ProjectInfo(profile={"preset": "light"}))
    project = project_ontology_for(ontology, document)
    assert {t.name for t in project.concrete_node_types()} == LIGHT
    assert document.ontology  # kept on the document, so the next save stores it


def test_data_is_never_hidden_by_its_own_ontology(ontology):
    source = po.from_selection(ontology, {"Activity"}, set())
    document = GraphDocument(
        nodes=[Node(id="t1", type="Tool", properties={"name": "CAD"}), Node(id="a1", type="Activity", properties={"name": "A"})],
        edges=[Edge(id="e1", type="USES_TOOL", source="a1", target="t1")],
        ontology=source,
    )
    project = project_ontology_for(ontology, document)
    assert "Tool" in project.node_types and "USES_TOOL" in project.edge_types


def _document_with_own_type(ontology):
    source = po.from_selection(ontology, LIGHT, None)
    source, _ = po.upsert_element_type(source, {"label": "Test rig"}, master=ontology)
    return GraphDocument(
        project=ProjectInfo(name="P"),
        nodes=[Node(id="rig1", type="TestRig", properties={"name": "Rig 1"})],
        ontology=source,
    )


@pytest.mark.parametrize("scheme,filename", [("json", "p.json"), ("sqlite", "p.db"), ("rdf", "p.ttl")])
def test_project_ontology_and_its_own_types_survive_every_file_backend(tmp_path, ontology, scheme, filename):
    document = _document_with_own_type(ontology)
    backend = open_storage(f"{scheme}:{tmp_path / filename}")
    backend.bind_ontology(ontology)  # bound to the master, which has never heard of TestRig
    backend.save(document)
    loaded = backend.load()
    assert "TestRig" in loaded.ontology["node_types"]
    assert [n.type for n in loaded.nodes] == ["TestRig"]


def test_project_ontology_survives_spreadsheet_tables_in_chunks(ontology):
    document = _document_with_own_type(ontology)
    tables = document_to_tables(document, ontology)
    assert "TestRig" in tables  # its own sheet, although the master lacks the type
    assert len(tables["_Ontology"]["rows"]) >= 1 and all(len(r[0]) <= 40_000 for r in tables["_Ontology"]["rows"])
    loaded = tables_to_document(tables, ontology)
    assert loaded.ontology == json.loads(json.dumps(document.ontology))
    assert [n.type for n in loaded.nodes] == ["TestRig"]


def test_identifiers_are_derived_from_labels():
    assert po.type_identifier("test rig") == "TestRig"
    assert po.relation_identifier("tested on") == "TESTED_ON"
    assert po.type_identifier("3D model") == "T3DModel"


def test_new_types_inherit_what_every_element_and_relation_carries(light_ws):
    rig = light_ws.ontology.node_types["TestRig"]
    assert {"name", "description", "weight", "rig_class"} <= set(rig.properties)
    assert rig.properties["rig_class"].values == ["A", "B"]
    assert "weight" in light_ws.ontology.edge_types["TESTED_ON"].properties


def test_changes_that_would_strand_data_are_refused(light_ws):
    light_ws.store.add_node("TestRig", {"name": "Rig 1", "rig_class": "A"})
    with pytest.raises(ConflictError, match="invalid"):
        light_ws.change_project_ontology(po.remove(light_ws.project_source, "element_type", "TestRig"))
    source, _ = po.upsert_element_type(
        light_ws.project_source,
        {"properties": [{"name": "rig_class", "label": "Rig class", "type": "enum", "values": "C"}]},
        existing="TestRig",
    )
    with pytest.raises(ConflictError):
        light_ws.change_project_ontology(source)
    assert "TestRig" in light_ws.ontology.node_types  # nothing changed


def test_removing_a_type_takes_its_relations_with_it(light_ws):
    source = po.remove(light_ws.project_source, "element_type", "TestRig")
    assert "TestRig" not in source["node_types"] and "TESTED_ON" not in source["edge_types"]


@pytest.mark.parametrize("data,message", [
    ({"label": ""}, "needs a name"),
    ({"label": "Rig", "category": "Sideways"}, "Category"),
    ({"label": "Rig", "properties": [{"label": "Kind", "type": "enum"}]}, "choices"),
    ({"label": "Rig", "properties": [{"label": "Kind", "type": "blob"}]}, "unknown type"),
])
def test_bad_element_types_are_refused(ontology, data, message):
    with pytest.raises(ValidationError, match=message):
        po.upsert_element_type(po.from_selection(ontology, LIGHT, None), data, master=ontology)


def test_a_relation_needs_both_ends(ontology):
    with pytest.raises(ValidationError, match="to"):
        po.upsert_relation(po.from_selection(ontology, LIGHT, None), {"label": "x", "domain": ["Activity"]})


# --------------------------------------------------------------------------- #
# Compare
# --------------------------------------------------------------------------- #


def _status(items, name):
    return next(i["status"] for i in items if i["name"] == name)


def test_compare_reports_every_status(light_ws):
    items = light_ws.compare_ontologies()["items"]
    assert _status(items, "TestRig") == "project_only"
    assert _status(items, "TESTED_ON") == "project_only"
    assert _status(items, "Tool") == "master_only"
    assert _status(items, "Activity") == "same"
    # A Light project's DEPENDS_ON is cut down to its types: not a difference.
    assert _status(items, "DEPENDS_ON") == "same"


def test_compare_reports_property_level_differences(light_ws):
    source, _ = po.upsert_element_type(
        light_ws.project_source,
        {"label": "Risk (programme)", "properties": [{"label": "Owner team", "type": "string"}]},
        existing="Risk",
    )
    light_ws.change_project_ontology(source)
    risk = next(i for i in light_ws.compare_ontologies()["items"] if i["name"] == "Risk")
    assert risk["status"] == "differs"
    assert {"field": "label", "project": "Risk (programme)", "master": "Risk"} in risk["changes"]
    assert {"property": "owner_team", "change": "only_in_project"} in risk["property_changes"]


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #


def test_merging_a_relation_to_the_master_brings_its_types(light_ws, tmp_path):
    preview = light_ws.merge_ontology("to_master", [{"kind": "relation", "name": "TESTED_ON"}], dry_run=True)
    assert preview["applied"] is False
    assert preview["dependencies"] == [{"kind": "element_type", "name": "TestRig"}]
    assert "TestRig" not in light_ws.master.node_types  # a preview changes nothing

    result = light_ws.merge_ontology("to_master", [{"kind": "relation", "name": "TESTED_ON"}])
    assert result["applied"] and "TestRig" in light_ws.master.node_types
    saved = json.loads((tmp_path / "ontologies" / "master.json").read_text())
    assert "TESTED_ON" in saved["edge_types"] and saved["ontology"]["version"] == result["master_version"]
    assert light_ws.compare_ontologies()["summary"]["project_only"] == 0


def test_merging_to_the_master_keeps_what_other_projects_rely_on(light_ws):
    source, _ = po.upsert_element_type(
        light_ws.project_source, {"properties": [{"label": "Owner team", "type": "string"}]}, existing="Risk"
    )
    light_ws.change_project_ontology(source)
    light_ws.merge_ontology("to_master", [{"kind": "element_type", "name": "Risk"}])
    master_risk = light_ws.master.node_types["Risk"]
    assert "owner_team" in master_risk.properties and "likelihood" in master_risk.properties


def test_merging_from_the_master_prunes_relation_ends(light_ws):
    result = light_ws.merge_ontology("to_project", [{"kind": "relation", "name": "USES_TOOL"}])
    assert result["dependencies"] == [{"kind": "element_type", "name": "Tool"}]
    assert "Tool" in light_ws.ontology.node_types
    assert light_ws.ontology.edge_types["USES_TOOL"].domain == ["Activity"]
    # HAS_PARAMETER: only the ends the project has, plus Parameter brought in for the empty end.
    light_ws.merge_ontology("to_project", [{"kind": "relation", "name": "HAS_PARAMETER"}])
    domain = light_ws.ontology.edge_types["HAS_PARAMETER"].domain
    assert "SystemElement" not in domain and "Activity" in domain


def test_merging_from_the_master_keeps_project_properties_in_use(light_ws):
    source, _ = po.upsert_element_type(
        light_ws.project_source, {"properties": [{"label": "Owner team", "type": "string"}]}, existing="Risk"
    )
    light_ws.change_project_ontology(source)
    light_ws.store.add_node("Risk", {"name": "R1", "owner_team": "Structures"})
    result = light_ws.merge_ontology("to_project", [{"kind": "element_type", "name": "Risk"}])
    assert "owner_team" in light_ws.ontology.node_types["Risk"].properties
    assert result["applied"] is False or any("owner_team" in note for note in result["notes"])


def test_plan_merge_rejects_unknown_directions_and_kinds(ontology):
    source = ontology_to_source(ontology)
    with pytest.raises(ValidationError):
        plan_merge("sideways", [], source, source)
    with pytest.raises(ValidationError):
        plan_merge("to_master", [{"kind": "colour", "name": "x"}], source, source)


def test_compare_of_identical_sources_is_all_same(ontology):
    source = ontology_to_source(ontology)
    assert {i["status"] for i in compare(source, source)} == {"same"}


# --------------------------------------------------------------------------- #
# The API, end to end
# --------------------------------------------------------------------------- #


def test_api_add_edit_remove_and_merge(settings):
    ws = Workspace.open(settings)
    status, body = call(ws, "POST", "/api/project/ontology/element-types", {"label": "Test rig", "category": "What"})
    assert status == 201 and body["name"] == "TestRig"
    status, body = call(ws, "POST", "/api/project/ontology/relations",
                        {"label": "tested on", "domain": ["Activity"], "range": ["TestRig"], "question": "how"})
    assert status == 201 and body["name"] == "TESTED_ON"
    status, body = call(ws, "PUT", "/api/project/ontology/element-types/TestRig", {"description": "A bench"})
    assert status == 200 and body["ontology"]["node_types"]["TestRig"]["description"] == "A bench"

    status, body = call(ws, "GET", "/api/ontologies/compare")
    assert status == 200 and body["summary"]["project_only"] == 2
    status, body = call(ws, "POST", "/api/ontologies/merge",
                        {"direction": "to_master", "items": [{"kind": "relation", "name": "TESTED_ON"}]})
    assert status == 200 and body["applied"] and body["compare"]["summary"]["project_only"] == 0
    assert call(ws, "GET", "/api/ontologies")[1]["master"]["saved"] is True

    ws.store.add_node("TestRig", {"name": "Rig 1"})
    status, body = call(ws, "DELETE", "/api/project/ontology/element-types/TestRig")
    assert status == 409 and body["error"]["details"]["issues"]
    status, _ = call(ws, "POST", "/api/ontologies/merge", {"direction": "to_master", "items": []})
    assert status == 422


def test_the_ontology_the_page_works_from_is_the_projects(settings):
    ws = Workspace.open(settings)
    call(ws, "POST", "/api/project/ontology/element-types", {"label": "Test rig"})
    assert "TestRig" in call(ws, "GET", "/api/ontology")[1]["node_types"]
    assert "TestRig" not in call(ws, "GET", "/api/ontologies/master")[1]["node_types"]
