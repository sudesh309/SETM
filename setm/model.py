"""Core data model: nodes, edges and the document that holds them.

Deliberately plain dataclasses with dict/JSON round-tripping. No pydantic, no ORM
-- every storage backend and the HTTP layer speak this one shape.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from .errors import ValidationError

SCHEMA_VERSION = "1.0"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")


def utc_now() -> str:
    """Timestamp used for every ``created_at``/``updated_at`` in the system."""
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def check_id(value: str, kind: str = "element") -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ValidationError(
            f"Invalid {kind} id {value!r}: use letters, digits, '.', ':', '_' or '-' (max 128 chars)"
        )
    return value


@dataclass
class Provenance:
    """Who touched an element, when, and where it came from.

    ``revision`` increments on every write and is what optimistic locking compares.
    """

    created_at: str = field(default_factory=utc_now)
    created_by: str = "unknown"
    updated_at: str = field(default_factory=utc_now)
    updated_by: str = "unknown"
    revision: int = 1
    source: str = "manual"

    def touch(self, actor: str, source: str | None = None) -> None:
        self.updated_at = utc_now()
        self.updated_by = actor
        self.revision += 1
        if source:
            self.source = source

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "created_by": self.created_by,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
            "revision": self.revision,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Provenance":
        data = data or {}
        now = utc_now()
        return cls(
            created_at=str(data.get("created_at") or now),
            created_by=str(data.get("created_by") or "unknown"),
            updated_at=str(data.get("updated_at") or data.get("created_at") or now),
            updated_by=str(data.get("updated_by") or data.get("created_by") or "unknown"),
            revision=int(data.get("revision") or 1),
            source=str(data.get("source") or "manual"),
        )


@dataclass
class Node:
    id: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        check_id(self.id, "node")

    @property
    def label(self) -> str:
        for key in ("name", "title", "label", "text"):
            value = self.properties.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return self.id

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "properties": dict(self.properties),
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Node":
        if "id" not in data or "type" not in data:
            raise ValidationError("Node requires 'id' and 'type'", issues=[{"element": data}])
        return cls(
            id=str(data["id"]),
            type=str(data["type"]),
            properties=dict(data.get("properties") or {}),
            provenance=Provenance.from_dict(data.get("provenance")),
        )


@dataclass
class Edge:
    id: str
    type: str
    source: str
    target: str
    properties: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        check_id(self.id, "edge")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "target": self.target,
            "properties": dict(self.properties),
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Edge":
        missing = [k for k in ("id", "type", "source", "target") if k not in data]
        if missing:
            raise ValidationError(f"Edge is missing {', '.join(missing)}", issues=[{"element": data}])
        return cls(
            id=str(data["id"]),
            type=str(data["type"]),
            source=str(data["source"]),
            target=str(data["target"]),
            properties=dict(data.get("properties") or {}),
            provenance=Provenance.from_dict(data.get("provenance")),
        )


@dataclass
class ProjectInfo:
    """Header describing the engineering project the graph belongs to."""

    id: str = "project"
    name: str = "Untitled project"
    programme: str = ""
    phase: str = ""
    description: str = ""
    chief_engineer: str = ""
    #: Which element types and relations this project uses, e.g.
    #: {"preset": "light", "node_types": [...], "edge_types": [...]}. Empty means
    #: the whole ontology. See Ontology.resolve_profile().
    profile: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "programme": self.programme,
            "phase": self.phase,
            "description": self.description,
            "chief_engineer": self.chief_engineer,
            "profile": dict(self.profile),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ProjectInfo":
        data = data or {}
        return cls(
            id=str(data.get("id") or "project"),
            name=str(data.get("name") or "Untitled project"),
            programme=str(data.get("programme") or ""),
            phase=str(data.get("phase") or ""),
            description=str(data.get("description") or ""),
            chief_engineer=str(data.get("chief_engineer") or ""),
            profile=coerce_profile(data.get("profile")),
        )


def coerce_profile(value: Any) -> dict[str, Any]:
    """A profile from a document: a mapping, or JSON text from a flat backend."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


@dataclass
class GraphDocument:
    """The complete serialisable payload a storage backend reads and writes."""

    project: ProjectInfo = field(default_factory=ProjectInfo)
    ontology_id: str = "aerospace-se-core"
    ontology_version: str = "1.0.0"
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    revision: int = 0
    updated_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project": self.project.to_dict(),
            "ontology_id": self.ontology_id,
            "ontology_version": self.ontology_version,
            "revision": self.revision,
            "updated_at": self.updated_at,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphDocument":
        if not isinstance(data, dict):
            raise ValidationError("Graph document must be a JSON object")
        return cls(
            project=ProjectInfo.from_dict(data.get("project")),
            ontology_id=str(data.get("ontology_id") or "aerospace-se-core"),
            ontology_version=str(data.get("ontology_version") or "1.0.0"),
            nodes=[Node.from_dict(n) for n in data.get("nodes") or []],
            edges=[Edge.from_dict(e) for e in data.get("edges") or []],
            revision=int(data.get("revision") or 0),
            updated_at=str(data.get("updated_at") or utc_now()),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )

    def elements(self) -> Iterator[Node | Edge]:
        yield from self.nodes
        yield from self.edges


def coerce_nodes(items: Iterable[dict[str, Any] | Node]) -> list[Node]:
    return [i if isinstance(i, Node) else Node.from_dict(i) for i in items]


def coerce_edges(items: Iterable[dict[str, Any] | Edge]) -> list[Edge]:
    return [i if isinstance(i, Edge) else Edge.from_dict(i) for i in items]
