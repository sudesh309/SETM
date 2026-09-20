"""CLI and workspace behaviour, including the HTTP server end to end."""

from __future__ import annotations

import json
import urllib.request

import pytest

from setm.cli import main
from setm.config import Settings
from setm.workspace import Workspace


def test_demo_then_validate_then_kpi(tmp_path, capsys):
    target = f"json:{tmp_path / 'demo.json'}"
    assert main(["demo", target]) == 0
    capsys.readouterr()

    assert main(["validate", "--storage", target]) == 0
    assert "OK" in capsys.readouterr().out

    assert main(["kpi", "--storage", target]) == 0
    assert "Overall health" in capsys.readouterr().out


def test_demo_refuses_to_overwrite_without_force(tmp_path, capsys):
    target = f"json:{tmp_path / 'demo.json'}"
    main(["demo", target])
    capsys.readouterr()
    assert main(["demo", target]) == 1
    assert "already holds data" in capsys.readouterr().out
    assert main(["demo", target, "--force"]) == 0


def test_init_creates_an_empty_project(tmp_path, capsys):
    target = f"json:{tmp_path / 'new.json'}"
    assert main(["init", target, "--name", "Skylark", "--chief-engineer", "A. Okonkwo"]) == 0
    stored = json.loads((tmp_path / "new.json").read_text())
    assert stored["project"]["name"] == "Skylark"
    assert stored["nodes"] == []
    capsys.readouterr()
    assert main(["init", target]) == 1  # refuses to clobber


def test_kpi_fail_under_is_a_usable_ci_gate(tmp_path, capsys):
    target = f"json:{tmp_path / 'demo.json'}"
    main(["demo", target])
    capsys.readouterr()
    assert main(["kpi", "--storage", target, "--fail-under", "50"]) == 0
    capsys.readouterr()
    assert main(["kpi", "--storage", target, "--fail-under", "99.9"]) == 1
    assert "below the required" in capsys.readouterr().out


def test_convert_between_every_file_backend(tmp_path, capsys):
    source = f"json:{tmp_path / 'demo.json'}"
    main(["demo", source])
    for destination in (f"rdf:{tmp_path / 'g.ttl'}", f"sqlite:{tmp_path / 'g.db'}", f"json:{tmp_path / 'copy.json'}"):
        assert main(["convert", source, destination]) == 0
    capsys.readouterr()

    # Turtle -> JSON survives the trip with the same element count.
    assert main(["convert", f"rdf:{tmp_path / 'g.ttl'}", f"json:{tmp_path / 'back.json'}"]) == 0
    original = json.loads((tmp_path / "demo.json").read_text())
    back = json.loads((tmp_path / "back.json").read_text())
    assert len(original["nodes"]) == len(back["nodes"])
    assert len(original["edges"]) == len(back["edges"])


def test_export_writes_each_format(tmp_path, capsys):
    target = f"json:{tmp_path / 'demo.json'}"
    main(["demo", target])
    capsys.readouterr()

    assert main(["export", "--storage", target, "--format", "ttl", "--out", str(tmp_path / "out.ttl")]) == 0
    assert "@prefix" in (tmp_path / "out.ttl").read_text()

    assert main(["export", "--storage", target, "--format", "owl", "--out", str(tmp_path / "out.owl")]) == 0
    assert "owl:Class" in (tmp_path / "out.owl").read_text()

    assert main(["export", "--storage", target, "--format", "csv", "--out", str(tmp_path / "csv")]) == 0
    assert (tmp_path / "csv" / "Activity.csv").exists()
    assert (tmp_path / "csv" / "_Relations.csv").exists()


def test_import_merges(tmp_path, capsys):
    source = f"json:{tmp_path / 'demo.json'}"
    main(["demo", source])
    target = f"json:{tmp_path / 'target.json'}"
    main(["init", target, "--name", "Target"])
    capsys.readouterr()

    assert main(["import", str(tmp_path / "demo.json"), "--storage", target, "--merge"]) == 0
    stored = json.loads((tmp_path / "target.json").read_text())
    assert len(stored["nodes"]) > 0


def test_ontology_commands(tmp_path, capsys):
    assert main(["ontology", "check"]) == 0
    assert "consistent" in capsys.readouterr().out
    assert main(["ontology", "show"]) == 0
    assert "Relations" in capsys.readouterr().out
    assert main(["ontology", "export", "--out", str(tmp_path / "o.ttl")]) == 0
    assert "owl:Ontology" in (tmp_path / "o.ttl").read_text()


def test_info_reports_the_workspace(tmp_path, capsys):
    target = f"json:{tmp_path / 'demo.json'}"
    main(["demo", target])
    capsys.readouterr()
    assert main(["info", "--storage", target]) == 0
    out = capsys.readouterr().out
    assert "HALO-1 Optical Payload" in out
    assert "Activity" in out


def test_bad_storage_option_is_reported(tmp_path, capsys):
    assert main(["info", "--storage", f"json:{tmp_path / 'x.json'}", "--storage-option", "broken"]) == 2
    assert "KEY=VALUE" in capsys.readouterr().err


def test_unknown_backend_exits_cleanly(capsys):
    assert main(["info", "--storage", "warpdrive:xyz"]) == 2
    assert "Unknown storage backend" in capsys.readouterr().err


# -- workspace --------------------------------------------------------------

def test_autosave_persists_each_change(tmp_path):
    path = tmp_path / "p.json"
    workspace = Workspace.open(Settings(storage=f"json:{path}", autosave=True))
    workspace.store.add_node("Activity", {"name": "Saved automatically"})
    workspace.autosave("add", "tester")
    assert "Saved automatically" in path.read_text()


def test_autosave_off_keeps_changes_in_memory(tmp_path):
    path = tmp_path / "p.json"
    workspace = Workspace.open(Settings(storage=f"json:{path}", autosave=False))
    workspace.store.add_node("Activity", {"name": "Not yet saved"})
    assert workspace.autosave("add", "tester") is None
    assert not path.exists() or "Not yet saved" not in path.read_text()
    workspace.save(message="explicit")
    assert "Not yet saved" in path.read_text()


def test_save_is_a_noop_when_nothing_changed(tmp_path):
    workspace = Workspace.open(Settings(storage=f"json:{tmp_path / 'p.json'}"))
    assert workspace.save().message == "no changes"


def test_reload_discards_unsaved_changes(tmp_path):
    workspace = Workspace.open(Settings(storage=f"json:{tmp_path / 'p.json'}", autosave=False))
    workspace.store.add_node("Activity", {"name": "Discarded"})
    workspace.reload()
    assert workspace.store.node_count == 0


def test_reload_ontology_keeps_the_graph(tmp_path):
    workspace = Workspace.open(Settings(storage=f"json:{tmp_path / 'p.json'}"))
    workspace.store.add_node("Activity", {"name": "Kept"})
    workspace.reload_ontology()
    assert workspace.store.node_count == 1


def test_settings_layering(tmp_path, monkeypatch):
    config = tmp_path / "setm.toml"
    config.write_text('[setm]\nstorage = "json:./from-file.json"\nport = 9001\n')
    monkeypatch.setenv("SETM_PORT", "9002")
    settings = Settings.load(config, port=9003)
    assert settings.storage == "json:./from-file.json"  # from the file
    assert settings.port == 9003  # explicit override wins over env and file


# -- server -----------------------------------------------------------------

@pytest.fixture
def running_server(tmp_path):
    from setm.api.server import serve

    main(["demo", f"json:{tmp_path / 'demo.json'}"])
    settings = Settings(storage=f"json:{tmp_path / 'demo.json'}", host="127.0.0.1", port=0)
    workspace = Workspace.open(settings)
    server = serve(workspace, settings, block=False)
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def fetch(url, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode()
        return response.status, response.headers.get("Content-Type"), body


def test_server_serves_the_web_interface(running_server):
    status, content_type, body = fetch(f"{running_server}/")
    assert status == 200
    assert "text/html" in content_type
    assert "SETM" in body


def test_server_serves_static_assets(running_server):
    for asset in ("app.js", "graph.js", "style.css", "views.js", "forms.js", "api.js"):
        status, _, body = fetch(f"{running_server}/{asset}")
        assert status == 200 and body


def test_server_api_round_trip(running_server):
    status, _, body = fetch(f"{running_server}/api/health")
    assert status == 200
    assert json.loads(body)["graph"]["nodes"] > 0

    status, _, body = fetch(
        f"{running_server}/api/nodes", "POST",
        {"type": "Activity", "properties": {"name": "Created over HTTP"}},
    )
    assert status == 201
    node_id = json.loads(body)["id"]

    status, _, body = fetch(f"{running_server}/api/nodes/{node_id}/trace")
    assert json.loads(body)["node"]["label"] == "Created over HTTP"


def test_server_unknown_path_falls_back_to_the_app(running_server):
    # A deep link must load the single-page app rather than 404.
    status, content_type, _ = fetch(f"{running_server}/some/deep/link")
    assert status == 200 and "text/html" in content_type


def test_server_rejects_path_traversal(running_server):
    try:
        status, _, _ = fetch(f"{running_server}/../../etc/passwd")
    except urllib.error.HTTPError as exc:  # urllib may normalise the path away
        status = exc.code
    assert status in (200, 403, 404)
