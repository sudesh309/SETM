"""Shared fixtures."""

from __future__ import annotations

import pytest

from setm.config import Settings
from setm.demo import build_demo
from setm.graph.store import GraphStore
from setm.model import GraphDocument
from setm.modification_demo import build_modification_demo
from setm.ontology.loader import load_ontology
from setm.storage import memory
from setm.storage.registry import load_builtin_backends
from setm.workspace import Workspace

load_builtin_backends()


@pytest.fixture(autouse=True)
def _isolated_master_ontology(tmp_path, monkeypatch):
    """Keep every test away from a real data/ontologies/master.json and data/projects.

    The master file's default location is relative to the working directory;
    a test that merges into the master must never write next to the checkout,
    and none may read a master someone saved there.
    """
    from setm import workspace as workspace_module
    from setm.ontology import master

    original = master.master_path

    def isolated(settings):
        path = original(settings)
        return path if path.is_absolute() else tmp_path / "master-ontology" / path.name

    monkeypatch.setattr(master, "master_path", isolated)
    monkeypatch.setattr(workspace_module, "master_path", isolated)

    # Likewise the projects folder: creating or loading a project in a test
    # writes into the test's own directory, never the checkout's data/.
    from setm import projects

    original_dir = projects.projects_dir

    def isolated_dir(workspace):
        path = original_dir(workspace)
        return path if path.is_absolute() else tmp_path / "projects"

    monkeypatch.setattr(projects, "projects_dir", isolated_dir)


@pytest.fixture(scope="session")
def ontology():
    return load_ontology("aerospace-se-core")


@pytest.fixture
def empty_store(ontology):
    return GraphStore(GraphDocument(), ontology)


@pytest.fixture
def demo_document(ontology):
    return build_demo(ontology)


@pytest.fixture
def demo_store(ontology, demo_document):
    return GraphStore(demo_document, ontology)


@pytest.fixture
def modification_document(ontology):
    return build_modification_demo(ontology)


@pytest.fixture
def modification_store(ontology, modification_document):
    return GraphStore(modification_document, ontology)


@pytest.fixture
def workspace(request, ontology):
    """A workspace backed by an isolated in-memory store."""
    target = f"memory:{request.node.name}"
    memory.reset(request.node.name)
    settings = Settings(storage=target, ontology="aerospace-se-core", autosave=True)
    workspace = Workspace.open(settings)
    yield workspace
    memory.reset(request.node.name)


@pytest.fixture
def demo_workspace(request, ontology, demo_document):
    target = f"memory:demo-{request.node.name}"
    memory.reset(f"demo-{request.node.name}")
    settings = Settings(storage=target, ontology="aerospace-se-core")
    workspace = Workspace.open(settings)
    workspace.import_document(demo_document)
    yield workspace
    memory.reset(f"demo-{request.node.name}")
