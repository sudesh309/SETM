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
