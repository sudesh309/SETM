"""Settings: layering, provenance, redaction, persistence and the API."""

from __future__ import annotations

import pytest

from setm.api.routes import Request, dispatch
from setm.config import FIELD_SPECS, FIELDS_BY_NAME, SECRET_PLACEHOLDER, Settings


def call(workspace, method, path, body=None, **query):
    return dispatch(
        workspace,
        Request(
            method=method,
            path=path,
            query={k: [str(v)] for k, v in query.items()},
            body=body,
            headers={"x-setm-user": "tester"},
        ),
    )


# -- field metadata ---------------------------------------------------------

def test_every_field_spec_matches_a_real_setting():
    defaults = Settings()
    for spec in FIELD_SPECS:
        assert hasattr(defaults, spec.name), spec.name
        assert spec.group and spec.label


def test_fields_with_an_env_var_are_actually_read_from_it(monkeypatch):
    for spec in FIELD_SPECS:
        if not spec.env_var or spec.datatype not in ("string", "boolean", "integer"):
            continue
        value = "7788" if spec.datatype == "integer" else ("true" if spec.datatype == "boolean" else "from-env")
        monkeypatch.setenv(spec.env_var, value)
        settings = Settings.load(None)
        assert settings.source_of(spec.name) == "environment", spec.name
        monkeypatch.delenv(spec.env_var)


# -- provenance -------------------------------------------------------------

def test_source_records_which_layer_won(tmp_path, monkeypatch):
    config = tmp_path / "setm.toml"
    config.write_text('[setm]\nactor = "from-file"\nstrict = true\n')
    monkeypatch.setenv("SETM_ACTOR", "from-env")

    settings = Settings.load(config, port=9999)
    assert settings.actor == "from-env"
    assert settings.source_of("actor") == "environment"
    assert settings.source_of("strict") == "file"
    assert settings.source_of("port") == "argument"
    assert settings.source_of("ontology") == "default"


def test_shadowed_by_environment_lists_what_a_saved_file_cannot_change(monkeypatch):
    monkeypatch.setenv("SETM_ACTOR", "from-env")
    assert "actor" in Settings.load(None).shadowed_by_environment()


# -- secrets ----------------------------------------------------------------

def test_secrets_are_never_returned():
    settings = Settings(api_token="hunter2", storage_options={"branch": "main", "token": "glpat-x"})
    redacted = settings.redacted()
    assert redacted["api_token"] == SECRET_PLACEHOLDER
    assert redacted["storage_options"]["token"] == SECRET_PLACEHOLDER
    assert redacted["storage_options"]["branch"] == "main"  # not a credential
    assert "hunter2" not in str(redacted)
    assert "glpat-x" not in str(redacted)


def test_sending_the_placeholder_back_does_not_erase_the_secret():
    settings = Settings(api_token="hunter2", storage_options={"token": "glpat-x", "branch": "main"})
    changed = settings.apply_update(
        {"api_token": SECRET_PLACEHOLDER, "storage_options": settings.redacted()["storage_options"]}
    )
    assert changed == []
    assert settings.api_token == "hunter2"
    assert settings.storage_options["token"] == "glpat-x"


def test_a_real_new_secret_does_replace_it():
    settings = Settings(api_token="old")
    assert settings.apply_update({"api_token": "new"}) == ["api_token"]
    assert settings.api_token == "new"


def test_blanking_a_backend_option_removes_it():
    settings = Settings(storage_options={"branch": "main", "path": "x.json"})
    settings.apply_update({"storage_options": {"branch": "", "path": "x.json"}})
    assert settings.storage_options == {"path": "x.json"}


def test_unknown_keys_are_ignored():
    settings = Settings()
    assert settings.apply_update({"not_a_setting": 1, "__class__": 2}) == []


# -- persistence ------------------------------------------------------------

def test_saved_file_round_trips(tmp_path):
    settings = Settings()
    settings.apply_update({
        "storage": "sqlite:./data/p.db",
        "autosave": False,
        "strict": True,
        "overlays": ["./a.yaml", "./b.yaml"],
        "kpi_targets": {"orphan_rate": 2.5},
        "port": 9001,
    })
    path = settings.save_file(tmp_path / "setm.toml")

    reloaded = Settings.load(path)
    assert reloaded.storage == "sqlite:./data/p.db"
    assert reloaded.autosave is False
    assert reloaded.strict is True
    assert reloaded.overlays == ["./a.yaml", "./b.yaml"]
    assert reloaded.kpi_targets == {"orphan_rate": 2.5}
    assert reloaded.port == 9001
    assert reloaded.source_of("storage") == "file"


def test_credentials_are_left_out_of_the_file_by_default(tmp_path):
    settings = Settings(api_token="hunter2", storage_options={"token": "glpat-x", "branch": "main"})
    text = settings.save_file(tmp_path / "setm.toml").read_text()
    assert "hunter2" not in text
    assert "glpat-x" not in text
    assert "branch" in text  # the non-secret option survives


def test_credentials_are_written_when_explicitly_asked_for(tmp_path):
    settings = Settings(api_token="hunter2")
    text = settings.save_file(tmp_path / "setm.toml", include_secrets=True).read_text()
    assert "hunter2" in text


def test_saved_file_escapes_awkward_values(tmp_path):
    settings = Settings()
    settings.apply_update({"actor": 'a "quoted" \\ name'})
    path = settings.save_file(tmp_path / "setm.toml")
    assert Settings.load(path).actor == 'a "quoted" \\ name'


# -- API --------------------------------------------------------------------

def test_settings_endpoint_describes_the_form(workspace):
    body = call(workspace, "GET", "/api/settings").body
    assert {f["name"] for f in body["fields"]} == {s.name for s in FIELD_SPECS}
    assert body["kpi_catalogue"]
    assert body["backends"]
    assert body["values"]["api_token"] == ""  # unset, not a placeholder


def test_kpi_catalogue_only_names_real_kpis(workspace):
    from setm.kpi.metrics import DEFAULT_TARGETS

    body = call(workspace, "GET", "/api/settings").body
    assert {k["id"] for k in body["kpi_catalogue"]} == set(DEFAULT_TARGETS)


def test_patch_applies_a_runtime_setting(workspace):
    response = call(workspace, "PATCH", "/api/settings", {"values": {"actor": "a.okonkwo", "autosave": False}})
    assert set(response.body["changed"]) == {"actor", "autosave"}
    assert response.body["needs_reopen"] == []
    assert workspace.settings.actor == "a.okonkwo"
    assert workspace.settings.autosave is False


def test_patch_marks_fields_that_need_a_reopen_or_a_restart(workspace):
    response = call(
        workspace, "PATCH", "/api/settings",
        {"values": {"storage": "memory:elsewhere", "port": 9123}},
    )
    assert response.body["needs_reopen"] == ["storage"]
    assert response.body["needs_restart"] == ["port"]
    # Applied to settings, but the live workspace is untouched until reopen.
    assert workspace.backend.target != "elsewhere"


def test_strict_mode_reaches_the_live_store(workspace):
    assert workspace.store.strict is False
    call(workspace, "PATCH", "/api/settings", {"values": {"strict": True}})
    assert workspace.store.strict is True

    response = call(
        workspace, "POST", "/api/nodes",
        {"type": "Activity", "properties": {"name": "x", "invented_property": 1}},
    )
    assert response.status == 422


def test_patch_persists_when_asked(workspace, tmp_path):
    workspace.settings.config_path = str(tmp_path / "setm.toml")
    response = call(workspace, "PATCH", "/api/settings", {"values": {"actor": "r.mehta"}, "persist": True})
    assert response.body["saved_to"].endswith("setm.toml")
    assert 'actor = "r.mehta"' in (tmp_path / "setm.toml").read_text()


def test_patch_does_not_persist_by_default(workspace, tmp_path):
    workspace.settings.config_path = str(tmp_path / "setm.toml")
    response = call(workspace, "PATCH", "/api/settings", {"values": {"actor": "r.mehta"}})
    assert response.body["saved_to"] == ""
    assert not (tmp_path / "setm.toml").exists()


def test_settings_response_never_leaks_a_secret(workspace):
    call(workspace, "PATCH", "/api/settings", {"values": {"api_token": "hunter2"}})
    body = call(workspace, "GET", "/api/settings").body
    assert "hunter2" not in str(body)
    assert body["values"]["api_token"] == SECRET_PLACEHOLDER


def test_kpi_targets_reach_the_report(demo_workspace):
    before = next(
        k for k in call(demo_workspace, "GET", "/api/kpi").body["kpis"]
        if k["id"] == "traceability_completeness"
    )
    assert before["target"] == 80.0

    call(demo_workspace, "PATCH", "/api/settings", {"values": {"kpi_targets": {"traceability_completeness": 99}}})
    after = next(
        k for k in call(demo_workspace, "GET", "/api/kpi").body["kpis"]
        if k["id"] == "traceability_completeness"
    )
    assert after["target"] == 99.0
    assert after["band"] != before["band"]  # a stricter target changes the verdict


# -- reopen -----------------------------------------------------------------

def test_reopen_switches_the_workspace(workspace):
    workspace.store.add_node("Activity", {"name": "In the first project"})
    workspace.save()

    call(workspace, "PATCH", "/api/settings", {"values": {"storage": "memory:second-project"}})
    response = call(workspace, "POST", "/api/settings/reopen", {})
    assert response.status == 200
    assert response.body["graph"]["nodes"] == 0
    assert workspace.backend.target == "second-project"


def test_reopen_refuses_to_discard_unsaved_work(workspace):
    workspace.store.add_node("Activity", {"name": "Unsaved"})
    workspace.store.dirty = True
    call(workspace, "PATCH", "/api/settings", {"values": {"storage": "memory:somewhere-else"}})

    blocked = call(workspace, "POST", "/api/settings/reopen", {})
    assert blocked.status == 409
    assert "unsaved changes" in blocked.body["error"]["message"]

    forced = call(workspace, "POST", "/api/settings/reopen", {"force": True})
    assert forced.status == 200


def test_reopen_reports_a_bad_target_without_breaking_the_session(workspace):
    call(workspace, "PATCH", "/api/settings", {"values": {"storage": "warpdrive:nope"}})
    response = call(workspace, "POST", "/api/settings/reopen", {})
    assert response.status == 400
    # The live workspace is untouched, so the user can correct the value.
    assert call(workspace, "GET", "/api/health").status == 200


# -- storage probe ----------------------------------------------------------

def test_probe_reports_a_reachable_empty_target(workspace, tmp_path):
    response = call(workspace, "POST", "/api/settings/test-storage", {"storage": f"json:{tmp_path / 'new.json'}"})
    assert response.body["ok"] is True
    assert response.body["has_existing_project"] is False
    assert "empty" in response.body["hint"]


def test_probe_notices_an_existing_project(workspace, tmp_path, demo_document, ontology):
    from setm.storage.registry import open_storage

    backend = open_storage(f"json:{tmp_path / 'existing.json'}")
    backend.bind_ontology(ontology)
    backend.save(demo_document)

    response = call(workspace, "POST", "/api/settings/test-storage", {"storage": f"json:{tmp_path / 'existing.json'}"})
    assert response.body["has_existing_project"] is True
    assert "already stored" in response.body["hint"]


def test_probe_reports_an_unknown_backend_as_a_result_not_a_crash(workspace):
    response = call(workspace, "POST", "/api/settings/test-storage", {"storage": "warpdrive:nope"})
    assert response.status == 200
    assert response.body["ok"] is False
    assert "Unknown storage backend" in response.body["error"]["message"]


def test_probe_keeps_a_stored_credential_when_given_the_placeholder(workspace):
    workspace.settings.storage_options = {"token": "glpat-real"}
    response = call(
        workspace, "POST", "/api/settings/test-storage",
        {"storage": "gitlab:group/project", "storage_options": {"token": SECRET_PLACEHOLDER}},
    )
    # It got far enough to talk to GitLab, which means the token survived.
    assert "No GitLab token" not in str(response.body)


def test_probe_does_not_switch_the_live_workspace(workspace, tmp_path):
    before = workspace.backend.target
    call(workspace, "POST", "/api/settings/test-storage", {"storage": f"json:{tmp_path / 'other.json'}"})
    assert workspace.backend.target == before


# -- CLI --------------------------------------------------------------------

def test_config_show_and_set(tmp_path, capsys, monkeypatch):
    from setm.cli import main

    monkeypatch.chdir(tmp_path)
    assert main(["config", "show"]) == 0
    out = capsys.readouterr().out
    assert "Storage" in out and "aerospace-se-core" in out

    assert main(["config", "set", "autosave=false", "actor=a.okonkwo"]) == 0
    capsys.readouterr()
    assert 'actor = "a.okonkwo"' in (tmp_path / "setm.toml").read_text()

    assert main(["config", "show"]) == 0
    assert "[file]" in capsys.readouterr().out


def test_config_set_rejects_an_unknown_key(tmp_path, capsys, monkeypatch):
    from setm.cli import main

    monkeypatch.chdir(tmp_path)
    assert main(["config", "set", "warp_factor=9"]) == 2
    assert "not a KEY=VALUE" in capsys.readouterr().err


def test_config_path(tmp_path, capsys, monkeypatch):
    from setm.cli import main

    monkeypatch.chdir(tmp_path)
    assert main(["config", "path"]) == 0
    assert "setm.toml" in capsys.readouterr().out


@pytest.mark.parametrize("name", [s.name for s in FIELD_SPECS])
def test_every_setting_is_editable_through_the_api(workspace, name):
    """A field on the page must actually be accepted by the PATCH endpoint."""
    spec = FIELDS_BY_NAME[name]
    sample = {
        "string": "sample",
        "integer": 4242,
        "boolean": True,
        "list": ["one"],
        "mapping": {"branch": "dev"},
        "number_map": {"orphan_rate": 1.0},
    }[spec.datatype]
    response = call(workspace, "PATCH", "/api/settings", {"values": {name: sample}})
    assert response.status == 200
    assert name in response.body["changed"] or getattr(workspace.settings, name) == sample
