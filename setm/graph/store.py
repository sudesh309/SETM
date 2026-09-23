"""In-memory indexed graph with ontology-checked writes.

The store owns the authoritative copy of the project graph while the process is
running. Every mutation validates against the ontology, bumps provenance, and
marks the store dirty so the persistence layer knows to flush.

Indices are plain dicts of sets: for the graph sizes this tool targets (tens of
thousands of elements) that is comfortably fast, and it keeps the code readable.
See ``setm/graph/_fastpath.py`` for the optional Rust acceleration hook.

Concurrency: the HTTP server answers each request on its own thread, so reads
and writes can overlap. Every method takes the store's re-entrant lock, which
makes each call safe on its own (iterating an index while another thread adds
to it would otherwise raise "changed size during iteration"). A caller that
needs several reads to agree with each other -- a KPI report, a graph payload --
wraps them in ``with store.reading():``.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Iterator

from ..errors import ConflictError, NotFoundError, ValidationError
from ..model import Edge, GraphDocument, Node, new_id, utc_now
from ..ontology.schema import Ontology
from ..ontology.validate import (
    cardinality_conflict,
    cardinality_error,
    cardinality_limits,
    validate_edge,
    validate_node,
)


class GraphStore:
    """Thread-safe, ontology-aware graph container."""

    def __init__(self, document: GraphDocument, ontology: Ontology, *, strict: bool = False) -> None:
        self.ontology = ontology
        self.strict = strict
        self._lock = threading.RLock()
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}
        self._out: dict[str, set[str]] = {}
        self._in: dict[str, set[str]] = {}
        self._nodes_by_type: dict[str, set[str]] = {}
        self._edges_by_type: dict[str, set[str]] = {}
        #: Lower-cased free-text haystack per node, built on first search and
        #: dropped whenever the node changes.
        self._search_text: dict[str, str] = {}
        self.project = document.project
        self.revision = document.revision
        self.ontology_id = document.ontology_id or ontology.id
        self.ontology_version = document.ontology_version or ontology.version
        self.dirty = False
        self._load(document)

    # -- loading ------------------------------------------------------------
    def _load(self, document: GraphDocument) -> None:
        for node in document.nodes:
            self._nodes[node.id] = node
            self._nodes_by_type.setdefault(node.type, set()).add(node.id)
            self._out.setdefault(node.id, set())
            self._in.setdefault(node.id, set())
        for edge in document.edges:
            if edge.source not in self._nodes or edge.target not in self._nodes:
                continue  # dangling edges are reported by `validate`, not loaded
            self._edges[edge.id] = edge
            self._edges_by_type.setdefault(edge.type, set()).add(edge.id)
            self._out[edge.source].add(edge.id)
            self._in[edge.target].add(edge.id)

    # -- reads --------------------------------------------------------------
    @contextmanager
    def reading(self) -> Iterator["GraphStore"]:
        """Hold the store still across several reads, so they see one revision."""
        with self._lock:
            yield self

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def node(self, node_id: str) -> Node:
        try:
            return self._nodes[node_id]
        except KeyError:
            raise NotFoundError(f"No node with id '{node_id}'", node_id=node_id) from None

    def edge(self, edge_id: str) -> Edge:
        try:
            return self._edges[edge_id]
        except KeyError:
            raise NotFoundError(f"No edge with id '{edge_id}'", edge_id=edge_id) from None

    def nodes(self) -> list[Node]:
        with self._lock:
            return list(self._nodes.values())

    def edges(self) -> list[Edge]:
        with self._lock:
            return list(self._edges.values())

    def nodes_of_type(self, type_name: str, *, include_subtypes: bool = True) -> list[Node]:
        with self._lock:
            if not include_subtypes:
                return [self._nodes[i] for i in self._nodes_by_type.get(type_name, ())]
            # is_a is memoised by the ontology, so this is a dict lookup per stored type.
            matching = [t for t in self._nodes_by_type if self.ontology.is_a(t, type_name)]
            return [self._nodes[i] for t in matching for i in self._nodes_by_type[t]]

    def edges_of_type(self, type_name: str) -> list[Edge]:
        with self._lock:
            return [self._edges[i] for i in self._edges_by_type.get(type_name, ())]

    def out_edges(self, node_id: str, types: Iterable[str] | None = None) -> list[Edge]:
        allowed = set(types) if types else None
        with self._lock:
            return [
                self._edges[i]
                for i in self._out.get(node_id, ())
                if allowed is None or self._edges[i].type in allowed
            ]

    def in_edges(self, node_id: str, types: Iterable[str] | None = None) -> list[Edge]:
        allowed = set(types) if types else None
        with self._lock:
            return [
                self._edges[i]
                for i in self._in.get(node_id, ())
                if allowed is None or self._edges[i].type in allowed
            ]

    def has_edge(self, node_id: str, type_name: str, *, direction: str = "out") -> bool:
        """Does the node have at least one ``type_name`` relation in that direction?

        The KPI engine asks this of every activity for several relation types;
        answering it without building a list is most of what makes the report fast.
        """
        index = self._out if direction == "out" else self._in
        with self._lock:
            edges = self._edges
            return any(edges[i].type == type_name for i in index.get(node_id, ()))

    def edge_types_at(self, node_id: str, *, direction: str = "out") -> set[str]:
        """The distinct relation types on one side of a node."""
        index = self._out if direction == "out" else self._in
        with self._lock:
            edges = self._edges
            return {edges[i].type for i in index.get(node_id, ())}

    def adjacency(self, types: Iterable[str] | None = None) -> dict[str, list[Edge]]:
        """Outgoing edges for every node, built under one lock.

        For whole-graph walks (cycle detection) that would otherwise call
        out_edges once per node. Per-node order matches out_edges exactly, so a
        walk visits neighbours in the same order either way.
        """
        allowed = set(types) if types else None
        with self._lock:
            edges = self._edges
            return {
                node_id: [edges[i] for i in ids if allowed is None or edges[i].type in allowed]
                for node_id, ids in self._out.items()
            }

    def incident_edges(self, node_id: str) -> list[Edge]:
        with self._lock:
            ids = self._out.get(node_id, set()) | self._in.get(node_id, set())
            return [self._edges[i] for i in ids]

    def neighbours(self, node_id: str, *, direction: str = "both", types: Iterable[str] | None = None) -> list[Node]:
        found: list[Node] = []
        if direction in ("out", "both"):
            found += [self._nodes[e.target] for e in self.out_edges(node_id, types)]
        if direction in ("in", "both"):
            found += [self._nodes[e.source] for e in self.in_edges(node_id, types)]
        seen: set[str] = set()
        unique = []
        for node in found:
            if node.id not in seen:
                seen.add(node.id)
                unique.append(node)
        return unique

    def degree(self, node_id: str) -> int:
        return len(self._out.get(node_id, ())) + len(self._in.get(node_id, ()))

    def edges_among(self, node_ids: Iterable[str], types: Iterable[str] | None = None) -> list[Edge]:
        """Every edge whose two ends are both in ``node_ids`` (the induced edge set).

        Picks the cheaper route: for a small selection, walk each node's outgoing
        index; for most of the graph, one pass over all edges beats thousands of
        per-node lookups.
        """
        allowed = set(types) if types else None
        ids = node_ids if isinstance(node_ids, (set, frozenset, dict)) else set(node_ids)
        with self._lock:
            if len(ids) * 4 < len(self._nodes):
                candidates = (self._edges[e] for i in ids for e in self._out.get(i, ()))
            else:
                candidates = iter(self._edges.values())
            return [
                e
                for e in candidates
                if e.source in ids and e.target in ids and (allowed is None or e.type in allowed)
            ]

    def iter_nodes(self) -> Iterator[Node]:
        return iter(self.nodes())

    def _haystack(self, node: Node) -> str:
        text = self._search_text.get(node.id)
        if text is None:
            text = self._search_text[node.id] = " ".join(
                [node.id, node.type] + [str(v) for v in node.properties.values() if v is not None]
            ).lower()
        return text

    def find_nodes(
        self,
        *,
        types: Iterable[str] | None = None,
        text: str = "",
        properties: dict[str, Any] | None = None,
        predicate: Callable[[Node], bool] | None = None,
    ) -> list[Node]:
        """Filter nodes by type, free-text, exact property match and/or a callable."""
        type_set = set(types) if types else None
        needle = text.strip().lower()
        with self._lock:
            results = []
            for node in self._nodes.values():  # insertion order keeps results stable
                if type_set and node.type not in type_set:
                    continue
                if properties and any(str(node.properties.get(k, "")) != str(v) for k, v in properties.items()):
                    continue
                if needle and needle not in self._haystack(node):
                    continue
                if predicate and not predicate(node):
                    continue
                results.append(node)
            return results

    # -- writes -------------------------------------------------------------
    def add_node(
        self,
        type_name: str,
        properties: dict[str, Any] | None = None,
        *,
        node_id: str | None = None,
        actor: str = "unknown",
        source: str = "manual",
    ) -> Node:
        with self._lock:
            node = Node(
                id=node_id or new_id(type_name.lower()[:12]),
                type=type_name,
                properties=dict(properties or {}),
            )
            if node.id in self._nodes:
                raise ConflictError(f"A node with id '{node.id}' already exists", node_id=node.id)
            node.provenance.created_by = node.provenance.updated_by = actor
            node.provenance.source = source
            validate_node(self.ontology, node, strict=self.strict)
            self._nodes[node.id] = node
            self._nodes_by_type.setdefault(node.type, set()).add(node.id)
            self._out.setdefault(node.id, set())
            self._in.setdefault(node.id, set())
            self._bump()
            return node

    def update_node(
        self,
        node_id: str,
        properties: dict[str, Any],
        *,
        actor: str = "unknown",
        expected_revision: int | None = None,
        replace: bool = False,
    ) -> Node:
        with self._lock:
            node = self.node(node_id)
            if expected_revision is not None and node.provenance.revision != expected_revision:
                raise ConflictError(
                    f"Node '{node_id}' changed since you loaded it "
                    f"(stored revision {node.provenance.revision}, you sent {expected_revision})",
                    stored_revision=node.provenance.revision,
                )
            candidate = Node(
                id=node.id,
                type=node.type,
                properties=dict(properties) if replace else {**node.properties, **properties},
            )
            # An explicit null clears a property.
            candidate.properties = {k: v for k, v in candidate.properties.items() if v is not None}
            validate_node(self.ontology, candidate, strict=self.strict)
            node.properties = candidate.properties
            node.provenance.touch(actor)
            self._search_text.pop(node_id, None)
            self._bump()
            return node

    def retype_node(self, node_id: str, new_type: str, *, actor: str = "unknown") -> Node:
        """Change a node's type, re-checking every incident edge against the ontology."""
        with self._lock:
            node = self.node(node_id)
            if new_type == node.type:
                return node
            self.ontology.node_type(new_type)
            for edge in self.incident_edges(node_id):
                spec = self.ontology.edge_type(edge.type)
                source_type = new_type if edge.source == node_id else self._nodes[edge.source].type
                target_type = new_type if edge.target == node_id else self._nodes[edge.target].type
                if not self.ontology._type_matches(source_type, spec.domain) or not self.ontology._type_matches(
                    target_type, spec.range
                ):
                    raise ValidationError(
                        f"Cannot retype '{node_id}' to {new_type}: edge {edge.id} ({edge.type}) "
                        "would become invalid"
                    )
            old_type = node.type
            candidate = Node(id=node.id, type=new_type, properties=dict(node.properties))
            validate_node(self.ontology, candidate, strict=False)
            self._nodes_by_type[old_type].discard(node_id)
            node.type = new_type
            node.properties = candidate.properties
            self._nodes_by_type.setdefault(new_type, set()).add(node_id)
            self._search_text.pop(node_id, None)
            node.provenance.touch(actor)
            self._bump()
            return node

    def delete_node(self, node_id: str, *, cascade: bool = True) -> dict[str, Any]:
        with self._lock:
            node = self.node(node_id)
            incident = self.incident_edges(node_id)
            if incident and not cascade:
                raise ConflictError(
                    f"Node '{node_id}' still has {len(incident)} relation(s); "
                    "delete them first or use cascade",
                    edge_count=len(incident),
                )
            for edge in incident:
                self._remove_edge(edge.id)
            self._nodes.pop(node_id)
            self._nodes_by_type.get(node.type, set()).discard(node_id)
            self._out.pop(node_id, None)
            self._in.pop(node_id, None)
            self._search_text.pop(node_id, None)
            self._bump()
            return {"deleted_node": node_id, "deleted_edges": [e.id for e in incident]}

    def add_edge(
        self,
        type_name: str,
        source: str,
        target: str,
        properties: dict[str, Any] | None = None,
        *,
        edge_id: str | None = None,
        actor: str = "unknown",
        source_system: str = "manual",
    ) -> Edge:
        with self._lock:
            source_node = self.node(source)
            target_node = self.node(target)
            if source == target:
                raise ValidationError("An element cannot be related to itself")
            edge = Edge(
                id=edge_id or new_id("rel"),
                type=type_name,
                source=source,
                target=target,
                properties=dict(properties or {}),
            )
            if edge.id in self._edges:
                raise ConflictError(f"An edge with id '{edge.id}' already exists", edge_id=edge.id)
            duplicate = next(
                (e for e in self.out_edges(source, [type_name]) if e.target == target),
                None,
            )
            if duplicate is not None:
                raise ConflictError(
                    f"'{type_name}' already links {source} to {target} (edge {duplicate.id})",
                    edge_id=duplicate.id,
                )
            edge.provenance.created_by = edge.provenance.updated_by = actor
            edge.provenance.source = source_system
            validate_edge(self.ontology, edge, source_node, target_node, strict=self.strict)
            # Only the edges already on this edge's two endpoints can breach its
            # cardinality, and the indices give those directly. Scanning every
            # edge of the type instead would make a bulk import quadratic.
            source_unique, target_unique = cardinality_limits(self.ontology, type_name)
            candidates: list[Edge] = []
            if source_unique:
                candidates += self.out_edges(source, [type_name])
            if target_unique:
                candidates += self.in_edges(target, [type_name])
            conflict = cardinality_conflict(self.ontology, edge, candidates)
            if conflict is not None:
                raise cardinality_error(self.ontology, edge, conflict)
            self._edges[edge.id] = edge
            self._edges_by_type.setdefault(type_name, set()).add(edge.id)
            self._out[source].add(edge.id)
            self._in[target].add(edge.id)
            self._bump()
            return edge

    def update_edge(
        self,
        edge_id: str,
        properties: dict[str, Any],
        *,
        actor: str = "unknown",
        expected_revision: int | None = None,
    ) -> Edge:
        with self._lock:
            edge = self.edge(edge_id)
            if expected_revision is not None and edge.provenance.revision != expected_revision:
                raise ConflictError(
                    f"Edge '{edge_id}' changed since you loaded it",
                    stored_revision=edge.provenance.revision,
                )
            candidate = Edge(
                id=edge.id,
                type=edge.type,
                source=edge.source,
                target=edge.target,
                properties={k: v for k, v in {**edge.properties, **properties}.items() if v is not None},
            )
            validate_edge(self.ontology, candidate, self.node(edge.source), self.node(edge.target), strict=self.strict)
            edge.properties = candidate.properties
            edge.provenance.touch(actor)
            self._bump()
            return edge

    def delete_edge(self, edge_id: str) -> dict[str, Any]:
        with self._lock:
            self.edge(edge_id)
            self._remove_edge(edge_id)
            self._bump()
            return {"deleted_edge": edge_id}

    def _remove_edge(self, edge_id: str) -> None:
        edge = self._edges.pop(edge_id, None)
        if edge is None:
            return
        self._edges_by_type.get(edge.type, set()).discard(edge_id)
        self._out.get(edge.source, set()).discard(edge_id)
        self._in.get(edge.target, set()).discard(edge_id)

    def update_project(self, values: dict[str, Any]) -> Any:
        with self._lock:
            for key in ("name", "programme", "phase", "description", "chief_engineer"):
                if key in values and values[key] is not None:
                    setattr(self.project, key, str(values[key]))
            self._bump()
            return self.project

    def _bump(self) -> None:
        self.revision += 1
        self.dirty = True

    # -- snapshots ----------------------------------------------------------
    def snapshot(self) -> GraphDocument:
        with self._lock:
            return GraphDocument(
                project=self.project,
                ontology_id=self.ontology_id,
                ontology_version=self.ontology_version,
                nodes=list(self._nodes.values()),
                edges=list(self._edges.values()),
                revision=self.revision,
                updated_at=utc_now(),
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "nodes": len(self._nodes),
                "edges": len(self._edges),
                "revision": self.revision,
                "nodes_by_type": {t: len(ids) for t, ids in sorted(self._nodes_by_type.items()) if ids},
                "edges_by_type": {t: len(ids) for t, ids in sorted(self._edges_by_type.items()) if ids},
                "ontology": {"id": self.ontology.id, "version": self.ontology.version},
            }
