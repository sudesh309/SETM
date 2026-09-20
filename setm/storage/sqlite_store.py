"""SQLite backend.

Stdlib only, single file, and the only shipped backend that keeps an append-only
change log -- which makes it the sensible default once a project outgrows a JSON
file but is not yet on a shared server.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..model import Edge, GraphDocument, Node, ProjectInfo, Provenance, utc_now
from .base import SaveResult, StorageBackend
from .registry import register

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nodes (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,
    properties TEXT NOT NULL,
    provenance TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,
    source     TEXT NOT NULL,
    target     TEXT NOT NULL,
    properties TEXT NOT NULL,
    provenance TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_type  ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_edges_type  ON edges(type);
CREATE INDEX IF NOT EXISTS idx_edges_src   ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_tgt   ON edges(target);
CREATE TABLE IF NOT EXISTS history (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    actor      TEXT NOT NULL,
    revision   INTEGER NOT NULL,
    message    TEXT NOT NULL,
    node_count INTEGER NOT NULL,
    edge_count INTEGER NOT NULL
);
"""


class SqliteBackend(StorageBackend):
    scheme = "sqlite"
    capabilities = {"read", "write", "atomic", "history"}

    def __init__(self, target: str, options: dict[str, Any] | None = None) -> None:
        super().__init__(target, options)
        self.path = Path(target).expanduser()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(_SCHEMA)
        return connection

    def load(self) -> GraphDocument:
        with self._connect() as connection:
            meta = {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM meta")}
            nodes = [
                Node(
                    id=row["id"],
                    type=row["type"],
                    properties=json.loads(row["properties"]),
                    provenance=Provenance.from_dict(json.loads(row["provenance"])),
                )
                for row in connection.execute("SELECT * FROM nodes")
            ]
            edges = [
                Edge(
                    id=row["id"],
                    type=row["type"],
                    source=row["source"],
                    target=row["target"],
                    properties=json.loads(row["properties"]),
                    provenance=Provenance.from_dict(json.loads(row["provenance"])),
                )
                for row in connection.execute("SELECT * FROM edges")
            ]
        return GraphDocument(
            project=ProjectInfo.from_dict(json.loads(meta.get("project", "{}"))),
            ontology_id=meta.get("ontology_id", "aerospace-se-core"),
            ontology_version=meta.get("ontology_version", "1.0.0"),
            nodes=nodes,
            edges=edges,
            revision=int(meta.get("revision", 0)),
            updated_at=meta.get("updated_at", utc_now()),
        )

    def save(self, document: GraphDocument, *, message: str = "", actor: str = "setm") -> SaveResult:
        self.require_writable()
        with self._connect() as connection:
            connection.execute("BEGIN")
            connection.execute("DELETE FROM nodes")
            connection.execute("DELETE FROM edges")
            connection.executemany(
                "INSERT INTO nodes (id, type, properties, provenance) VALUES (?, ?, ?, ?)",
                [
                    (n.id, n.type, json.dumps(n.properties, ensure_ascii=False), json.dumps(n.provenance.to_dict()))
                    for n in document.nodes
                ],
            )
            connection.executemany(
                "INSERT INTO edges (id, type, source, target, properties, provenance) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        e.id,
                        e.type,
                        e.source,
                        e.target,
                        json.dumps(e.properties, ensure_ascii=False),
                        json.dumps(e.provenance.to_dict()),
                    )
                    for e in document.edges
                ],
            )
            for key, value in (
                ("project", json.dumps(document.project.to_dict())),
                ("ontology_id", document.ontology_id),
                ("ontology_version", document.ontology_version),
                ("revision", str(document.revision)),
                ("updated_at", document.updated_at),
            ):
                connection.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
            connection.execute(
                "INSERT INTO history (at, actor, revision, message, node_count, edge_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (utc_now(), actor, document.revision, message or "saved", len(document.nodes), len(document.edges)),
            )
        return SaveResult(revision=document.revision, message=message or "saved", location=str(self.path))

    def exists(self) -> bool:
        if not self.path.exists():
            return False
        with self._connect() as connection:
            rows = connection.execute("SELECT COUNT(*) AS c FROM meta").fetchone()["c"]
        return bool(rows)

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM history ORDER BY seq DESC LIMIT ?", (limit,)
                )
            ]

    def health(self) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                nodes = connection.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
            return {
                "backend": self.scheme,
                "target": str(self.path),
                "status": "ok",
                "nodes": nodes,
                "size_bytes": self.path.stat().st_size if self.path.exists() else 0,
            }
        except sqlite3.Error as exc:
            return {"backend": self.scheme, "target": str(self.path), "status": "error", "error": str(exc)}


register("sqlite", SqliteBackend)
