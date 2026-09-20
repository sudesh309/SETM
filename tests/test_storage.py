"""Storage backends and the exchange formats they rely on."""

from __future__ import annotations

import json

import pytest

from setm.errors import ConfigError
from setm.model import GraphDocument
from setm.serialize.rdfmap import document_to_turtle, ontology_to_owl, turtle_to_document
from setm.serialize.tabular import document_to_tables, tables_to_document
from setm.serialize.turtle import parse_turtle, serialize_triples
from setm.storage.registry import open_storage, parse_uri


def normalise(document: GraphDocument):
    """Compare content, ignoring element order."""
    return (
        document.project.to_dict(),
        sorted((n.id, n.type, tuple(sorted((k, str(v)) for k, v in n.properties.items()))) for n in document.nodes),
        sorted(
            (e.id, e.type, e.source, e.target, tuple(sorted((k, str(v)) for k, v in e.properties.items())))
            for e in document.edges
        ),
    )


# -- URI parsing ------------------------------------------------------------

@pytest.mark.parametrize(
    "uri,scheme,target",
    [
        ("json:./x.json", "json", "./x.json"),
        ("sqlite:/tmp/x.db", "sqlite", "/tmp/x.db"),
        ("rdf:./x.ttl", "rdf", "./x.ttl"),
        ("./project.json", "json", "./project.json"),
        ("./project.ttl", "rdf", "./project.ttl"),
        ("gsheet:abc123", "gsheet", "abc123"),
        ("https://host/api/graph", "http", "https://host/api/graph"),
    ],
)
def test_uri_parsing(uri, scheme, target):
    parsed_scheme, parsed_target, _ = parse_uri(uri)
    assert (parsed_scheme, parsed_target) == (scheme, target)


def test_uri_options_are_parsed():
    scheme, target, options = parse_uri("gitlab:group/proj?path=se/graph.json&branch=dev")
    assert scheme == "gitlab"
    assert target == "group/proj"
    assert options == {"path": "se/graph.json", "branch": "dev"}


def test_unknown_extension_is_rejected():
    with pytest.raises(ConfigError, match="Cannot infer"):
        parse_uri("./notes.txt")


def test_unknown_scheme_is_rejected():
    with pytest.raises(ConfigError, match="Unknown storage backend"):
        open_storage("quantum:whatever")


# -- file backends ----------------------------------------------------------

def test_json_round_trip(tmp_path, demo_document, ontology):
    backend = open_storage(f"json:{tmp_path / 'p.json'}")
    backend.bind_ontology(ontology)
    backend.save(demo_document, message="first")
    assert normalise(backend.load()) == normalise(demo_document)


def test_json_backend_returns_empty_document_when_absent(tmp_path, ontology):
    backend = open_storage(f"json:{tmp_path / 'missing.json'}")
    document = backend.load()
    assert document.nodes == [] and document.edges == []


def test_json_write_is_atomic_and_keeps_backups(tmp_path, demo_document, ontology):
    path = tmp_path / "p.json"
    backend = open_storage(f"json:{path}")
    backend.bind_ontology(ontology)
    backend.save(demo_document)
    backend.save(demo_document)
    assert path.with_suffix(".json.bak1").exists()
    # No temporary files left behind.
    assert not list(tmp_path.glob(".*tmp"))


def test_sqlite_round_trip_and_history(tmp_path, demo_document, ontology):
    backend = open_storage(f"sqlite:{tmp_path / 'p.db'}")
    backend.bind_ontology(ontology)
    backend.save(demo_document, message="first", actor="tester")
    backend.save(demo_document, message="second", actor="tester")
    assert normalise(backend.load()) == normalise(demo_document)
    history = backend.history()
    assert [row["message"] for row in history][:2] == ["second", "first"]
    assert backend.health()["status"] == "ok"


def test_rdf_round_trip(tmp_path, demo_document, ontology):
    backend = open_storage(f"rdf:{tmp_path / 'p.ttl'}")
    backend.bind_ontology(ontology)
    backend.save(demo_document)
    assert normalise(backend.load()) == normalise(demo_document)


def test_memory_backend_is_isolated_per_target(demo_document):
    first = open_storage("memory:one")
    second = open_storage("memory:two")
    first.save(demo_document)
    assert second.load().nodes == []


def test_backend_describe_reports_capabilities(tmp_path):
    assert open_storage(f"sqlite:{tmp_path / 'p.db'}").describe()["versioned"] is True
    assert open_storage(f"json:{tmp_path / 'p.json'}").describe()["versioned"] is False
    assert open_storage(f"json:{tmp_path / 'p.json'}").describe()["writable"] is True


def test_http_backend_can_be_opened_read_only():
    backend = open_storage("https://example.invalid/graph?readonly=true")
    assert backend.writable is False


# -- turtle -----------------------------------------------------------------

def test_turtle_writer_and_parser_round_trip():
    from setm.serialize.turtle import iri, lit

    triples = [
        (iri("https://x/a"), iri("https://x/p"), lit("a string with \"quotes\" and \n newline")),
        (iri("https://x/a"), iri("https://x/n"), lit(42)),
        (iri("https://x/a"), iri("https://x/f"), lit(1.5)),
        (iri("https://x/a"), iri("https://x/b"), lit(True)),
        (iri("https://x/a"), iri("https://x/link"), iri("https://x/c")),
    ]
    text = serialize_triples(triples, {"x": "https://x/"})
    parsed, _ = parse_turtle(text)
    assert sorted(map(str, parsed)) == sorted(map(str, triples))


def test_turtle_parser_handles_comments_and_language_tags():
    text = """
    @prefix ex: <https://ex/> .
    # a comment
    ex:a ex:label "hello"@en ;
         ex:other "plain" .
    """
    triples, prefixes = parse_turtle(text)
    assert prefixes["ex"] == "https://ex/"
    assert any(t[2][3] == "en" for t in triples)


def test_document_turtle_round_trip_preserves_edge_properties(demo_document, ontology):
    text = document_to_turtle(demo_document, ontology)
    restored = turtle_to_document(text, ontology)
    assert normalise(restored) == normalise(demo_document)
    commitment = next(e for e in restored.edges if e.type == "DELIVERS_AT")
    assert commitment.properties["commitment"] == "committed"


def test_owl_export_declares_classes_and_properties(ontology):
    owl = ontology_to_owl(ontology)
    assert "owl:Class" in owl
    assert "owl:ObjectProperty" in owl
    assert "onto:Activity" in owl
    # many_to_one relations should be functional
    assert "owl:FunctionalProperty" in owl


# -- spreadsheet tables -----------------------------------------------------

def test_tabular_round_trip(demo_document, ontology):
    tables = document_to_tables(demo_document, ontology)
    assert "_Relations" in tables and "_Project" in tables and "Activity" in tables
    restored = tables_to_document(tables, ontology)
    assert normalise(restored) == normalise(demo_document)


def test_tabular_headers_use_ontology_property_order(demo_document, ontology):
    tables = document_to_tables(demo_document, ontology)
    header = tables["Activity"]["header"]
    assert header[0] == "id"
    assert "rationale" in header
    assert header[-1] == "_source"


def test_tabular_ignores_user_added_worksheets(demo_document, ontology):
    tables = document_to_tables(demo_document, ontology)
    tables["My notes"] = {"header": ["a"], "rows": [["b"]]}
    restored = tables_to_document(tables, ontology)
    assert normalise(restored) == normalise(demo_document)


def test_json_document_survives_a_full_serialise_cycle(demo_document):
    restored = GraphDocument.from_dict(json.loads(json.dumps(demo_document.to_dict())))
    assert normalise(restored) == normalise(demo_document)


# -- defaults ---------------------------------------------------------------

def test_a_local_json_file_is_the_default_storage():
    """The tool must work with no credentials, no network and no setup."""
    from setm.config import Settings

    scheme, target, _ = parse_uri(Settings().storage)
    assert scheme == "json"
    assert target.endswith(".json")


def test_every_backend_is_reachable_by_uri():
    from setm.storage.registry import available_schemes

    assert {"json", "sqlite", "rdf", "gitlab", "gsheet", "gdrive", "http", "memory"} <= set(available_schemes())


# -- GitLab -----------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("git@gitlab.com:my-group/my-project.git", ("https://gitlab.com", "my-group/my-project")),
        ("https://gitlab.example.com/a/b/c.git", ("https://gitlab.example.com", "a/b/c")),
        ("https://user@gitlab.com/g/p", ("https://gitlab.com", "g/p")),
        ("ssh://weird", None),
        ("https://gitlab.com/no-group", None),
        ("", None),
    ],
)
def test_git_remote_parsing(url, expected):
    from setm.storage.gitlab import parse_git_remote

    assert parse_git_remote(url) == expected


def test_gitlab_resolves_the_project_from_the_environment(monkeypatch):
    monkeypatch.setenv("SETM_GITLAB_PROJECT", "env-group/env-project")
    backend = open_storage("gitlab:?path=se/graph.json")
    assert backend.project == "env-group/env-project"
    assert backend.describe()["target"] == "env-group/env-project"


def test_gitlab_falls_back_to_the_surrounding_checkout(monkeypatch, tmp_path):
    monkeypatch.delenv("SETM_GITLAB_PROJECT", raising=False)
    repo = tmp_path / "repo" / "nested"
    (repo / ".." / ".git").resolve().mkdir(parents=True)
    (tmp_path / "repo" / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = git@gitlab.internal:programme/payload.git\n'
    )
    repo.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(repo)

    backend = open_storage("gitlab:")
    assert backend.project == "programme/payload"
    assert backend.host == "https://gitlab.internal"


def test_gitlab_without_a_project_explains_how_to_set_one(monkeypatch, tmp_path):
    monkeypatch.delenv("SETM_GITLAB_PROJECT", raising=False)
    monkeypatch.chdir(tmp_path)  # no repository here
    with pytest.raises(ConfigError) as exc:
        open_storage("gitlab:")
    assert "SETM_GITLAB_PROJECT" in exc.value.message
    assert "gitlab:my-group/my-project" in exc.value.message


def test_gitlab_requires_a_token_before_touching_the_network(monkeypatch):
    monkeypatch.delenv("SETM_GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    backend = open_storage("gitlab:group/project")
    with pytest.raises(ConfigError, match="No GitLab token"):
        backend.load()


def test_gitlab_describes_itself_as_versioned():
    info = open_storage("gitlab:group/project?branch=dev&path=x/y.ttl").describe()
    assert info["versioned"] is True
    assert info["branch"] == "dev"
    assert info["format"] == "ttl"  # inferred from the path


def test_gsheet_backend_is_registered_and_constructible():
    """It is listed in the docs and the URI table, so it must actually load."""
    backend = open_storage("gsheet:1AbCdEfGhIjKlMnOpQrStUvWxYz")
    info = backend.describe()
    assert info["scheme"] == "gsheet"
    assert info["writable"] is True
    assert info["url"].endswith("1AbCdEfGhIjKlMnOpQrStUvWxYz")


def test_gsheet_reports_unconfigured_rather_than_crashing(monkeypatch):
    monkeypatch.delenv("SETM_GOOGLE_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    health = open_storage("gsheet:abc").health()
    assert health["status"] in ("unconfigured", "error")
