"""Traversal and traceability queries.

Nothing here hardcodes aerospace vocabulary. The "who / when / why / how / what"
grouping that the UI shows is driven by the ``question`` attribute each edge type
declares in the ontology, so a project that renames its relations still gets a
correct traceability panel.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Iterable

from ..model import Edge, Node
from ._fastpath import reachable_set
from .store import GraphStore

QUESTION_ORDER = ["who", "when", "why", "how", "what", "where", "other"]


def _node_brief(store: GraphStore, node: Node) -> dict[str, Any]:
    spec = store.ontology.node_types.get(node.type)
    return {
        "id": node.id,
        "type": node.type,
        "type_label": spec.label if spec else node.type,
        "label": node.label,
        "color": spec.color if spec else "#6b7fd7",
        "properties": node.properties,
    }


def _edge_brief(store: GraphStore, edge: Edge) -> dict[str, Any]:
    spec = store.ontology.edge_types.get(edge.type)
    return {
        "id": edge.id,
        "type": edge.type,
        "label": spec.label if spec else edge.type,
        "question": spec.question if spec else "",
        "source": edge.source,
        "target": edge.target,
        "properties": edge.properties,
    }


def subgraph(store: GraphStore, node_ids: Iterable[str]) -> dict[str, Any]:
    """Induced subgraph: the named nodes plus every edge between them."""
    ids = {i for i in node_ids if store.has_node(i)}
    nodes = [store.node(i) for i in ids]
    edges = [e for e in store.edges() if e.source in ids and e.target in ids]
    return {
        "nodes": [_node_brief(store, n) for n in nodes],
        "edges": [_edge_brief(store, e) for e in edges],
    }


def neighbourhood(
    store: GraphStore,
    node_id: str,
    *,
    depth: int = 1,
    direction: str = "both",
    edge_types: Iterable[str] | None = None,
    node_types: Iterable[str] | None = None,
    limit: int = 2000,
) -> dict[str, Any]:
    """Breadth-first context around a node, capped at ``limit`` nodes."""
    store.node(node_id)  # existence check
    allowed_edges = set(edge_types) if edge_types else None
    allowed_nodes = set(node_types) if node_types else None

    distances: dict[str, int] = {node_id: 0}
    queue: deque[str] = deque([node_id])
    truncated = False
    while queue:
        current = queue.popleft()
        current_depth = distances[current]
        if current_depth >= depth:
            continue
        step: list[Edge] = []
        if direction in ("out", "both"):
            step += store.out_edges(current, allowed_edges)
        if direction in ("in", "both"):
            step += store.in_edges(current, allowed_edges)
        for edge in step:
            other = edge.target if edge.source == current else edge.source
            if other in distances:
                continue
            if allowed_nodes and store.node(other).type not in allowed_nodes:
                continue
            if len(distances) >= limit:
                truncated = True
                queue.clear()
                break
            distances[other] = current_depth + 1
            queue.append(other)

    result = subgraph(store, distances)
    for node in result["nodes"]:
        node["distance"] = distances.get(node["id"], 0)
    result["root"] = node_id
    result["truncated"] = truncated
    return result


def trace(store: GraphStore, node_id: str, *, depth: int = 2) -> dict[str, Any]:
    """Full traceability record for one element.

    Groups direct relations by the management question the ontology says each
    edge answers, then reports the upstream and downstream closure so a chief
    engineer can see both rationale and consequence.
    """
    node = store.node(node_id)
    groups: dict[str, list[dict[str, Any]]] = {q: [] for q in QUESTION_ORDER}

    for edge in store.out_edges(node_id):
        spec = store.ontology.edge_types.get(edge.type)
        question = (spec.question if spec else "") or "other"
        groups.setdefault(question, []).append(
            {
                "direction": "outgoing",
                "relation": edge.type,
                "relation_label": spec.label if spec else edge.type,
                "edge_id": edge.id,
                "edge_properties": edge.properties,
                "node": _node_brief(store, store.node(edge.target)),
            }
        )
    for edge in store.in_edges(node_id):
        spec = store.ontology.edge_types.get(edge.type)
        question = (spec.question if spec else "") or "other"
        groups.setdefault(question, []).append(
            {
                "direction": "incoming",
                "relation": edge.type,
                "relation_label": spec.inverse_label or (f"is {spec.label} of" if spec else edge.type),
                "edge_id": edge.id,
                "edge_properties": edge.properties,
                "node": _node_brief(store, store.node(edge.source)),
            }
        )

    upstream = reachable_set(store, node_id, direction="in", max_depth=depth)
    downstream = reachable_set(store, node_id, direction="out", max_depth=depth)
    upstream.discard(node_id)
    downstream.discard(node_id)

    return {
        "node": _node_brief(store, node),
        "provenance": node.provenance.to_dict(),
        "questions": {q: items for q, items in groups.items() if items},
        "upstream": [_node_brief(store, store.node(i)) for i in sorted(upstream)],
        "downstream": [_node_brief(store, store.node(i)) for i in sorted(downstream)],
        "completeness": completeness(store, node_id),
    }


def completeness(store: GraphStore, node_id: str) -> dict[str, Any]:
    """Which management questions this element can and cannot answer.

    ``expected`` comes from the ontology, in both directions: an edge type whose
    domain accepts this node type (it could link outwards) and one whose range
    accepts it (something could link in). The second half matters because the
    most important question of all -- *who* owns an activity -- is recorded as
    an incoming ``Person -> Activity`` relation, so an outgoing-only check would
    call an unowned activity complete.
    """
    node = store.node(node_id)
    ontology = store.ontology
    expected: dict[str, set[str]] = {}
    directions: dict[str, str] = {}
    for spec in ontology.edge_types.values():
        if not spec.question:
            continue
        if ontology._type_matches(node.type, spec.domain):
            expected.setdefault(spec.question, set()).add(spec.name)
            directions[spec.name] = "out"
        elif ontology._type_matches(node.type, spec.range):
            expected.setdefault(spec.question, set()).add(spec.name)
            directions[spec.name] = "in"

    present = {e.type for e in store.out_edges(node_id)} | {
        e.type for e in store.in_edges(node_id) if directions.get(e.type) == "in"
    }
    answered = {q: sorted(types & present) for q, types in expected.items()}
    missing = {q: sorted(types) for q, types in expected.items() if not (types & present)}
    total = len(expected) or 1
    return {
        "answered": {q: v for q, v in answered.items() if v},
        "missing": missing,
        "score": round((total - len(missing)) / total, 3),
    }


def paths(
    store: GraphStore,
    source: str,
    target: str,
    *,
    max_depth: int = 6,
    max_paths: int = 25,
    directed: bool = True,
) -> list[dict[str, Any]]:
    """Enumerate distinct paths between two elements, shortest first."""
    store.node(source)
    store.node(target)
    found: list[dict[str, Any]] = []
    queue: deque[tuple[str, list[Edge], set[str]]] = deque([(source, [], {source})])

    while queue and len(found) < max_paths:
        current, trail, visited = queue.popleft()
        if len(trail) >= max_depth:
            continue
        step = list(store.out_edges(current))
        if not directed:
            step += list(store.in_edges(current))
        for edge in step:
            other = edge.target if edge.source == current else edge.source
            if other in visited:
                continue
            new_trail = trail + [edge]
            if other == target:
                found.append(
                    {
                        "length": len(new_trail),
                        "edges": [_edge_brief(store, e) for e in new_trail],
                        "nodes": [_node_brief(store, store.node(i)) for i in _path_nodes(source, new_trail)],
                    }
                )
                if len(found) >= max_paths:
                    break
                continue
            queue.append((other, new_trail, visited | {other}))
    return found


def _path_nodes(source: str, trail: list[Edge]) -> list[str]:
    nodes = [source]
    current = source
    for edge in trail:
        current = edge.target if edge.source == current else edge.source
        nodes.append(current)
    return nodes


def impact(store: GraphStore, node_id: str, *, direction: str = "out", max_depth: int = 8) -> dict[str, Any]:
    """What is affected if this element changes (or what it depends on)."""
    reached = reachable_set(store, node_id, direction=direction, max_depth=max_depth)
    reached.discard(node_id)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for element_id in sorted(reached):
        node = store.node(element_id)
        by_type.setdefault(node.type, []).append(_node_brief(store, node))
    return {
        "root": _node_brief(store, store.node(node_id)),
        "direction": direction,
        "total": len(reached),
        "by_type": by_type,
    }


def orphans(store: GraphStore) -> list[dict[str, Any]]:
    """Elements with no relations at all -- usually an import or authoring gap."""
    return [_node_brief(store, n) for n in store.nodes() if store.degree(n.id) == 0]


def cycles(store: GraphStore, edge_types: Iterable[str] | None = None, *, limit: int = 20) -> list[list[str]]:
    """Detect directed cycles, e.g. circular activity dependencies."""
    allowed = set(edge_types) if edge_types else None
    colour: dict[str, int] = {}
    found: list[list[str]] = []

    def visit(start: str) -> None:
        stack: list[tuple[str, list[Edge]]] = [(start, list(store.out_edges(start, allowed)))]
        trail: list[str] = [start]
        colour[start] = 1
        while stack:
            if len(found) >= limit:
                return
            current, pending = stack[-1]
            if not pending:
                colour[current] = 2
                stack.pop()
                trail.pop()
                continue
            edge = pending.pop()
            nxt = edge.target
            state = colour.get(nxt, 0)
            if state == 1:
                cycle = trail[trail.index(nxt) :] + [nxt] if nxt in trail else [nxt, current]
                found.append(cycle)
            elif state == 0:
                colour[nxt] = 1
                trail.append(nxt)
                stack.append((nxt, list(store.out_edges(nxt, allowed))))

    for node in store.nodes():
        if colour.get(node.id, 0) == 0:
            visit(node.id)
    return found


def group_by_property(store: GraphStore, type_name: str, property_name: str) -> dict[str, list[dict[str, Any]]]:
    """Bucket nodes of a type by one property -- the basis of the board views."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for node in store.nodes_of_type(type_name):
        key = str(node.properties.get(property_name) or "(unset)")
        buckets.setdefault(key, []).append(_node_brief(store, node))
    return buckets


def related_through(store: GraphStore, node_id: str, chain: list[str]) -> list[dict[str, Any]]:
    """Follow a declared trace path. A ``~`` prefix walks that step backwards."""
    frontier = {node_id}
    for step in chain:
        backwards = step.startswith("~")
        edge_type = step.lstrip("~")
        nxt: set[str] = set()
        for element_id in frontier:
            edges = store.in_edges(element_id, [edge_type]) if backwards else store.out_edges(element_id, [edge_type])
            for edge in edges:
                nxt.add(edge.source if backwards else edge.target)
        frontier = nxt
        if not frontier:
            break
    return [_node_brief(store, store.node(i)) for i in sorted(frontier)]
