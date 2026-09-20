"""Hot-path traversals, with an optional Rust implementation.

The pure-Python versions below are the reference implementation and are what the
MVP runs. If the companion crate in ``rust/setm_core`` has been built and
installed (``pip install setuptools-rust maturin && maturin develop`` inside that
directory), the same functions are served by compiled code instead -- same
signatures, same results, roughly an order of magnitude faster on graphs with
>100k edges.

Keeping the switch in one module means no caller needs to know which is active;
``ACCELERATED`` is reported through the KPI endpoint so operators can see it.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:  # pragma: no cover
    from .store import GraphStore

try:  # pragma: no cover - exercised only when the extension is installed
    import setm_core as _rust  # type: ignore

    ACCELERATED = True
    BACKEND = f"rust:setm_core {getattr(_rust, '__version__', 'unknown')}"
except ImportError:
    _rust = None
    ACCELERATED = False
    BACKEND = "python"


def _adjacency(store: "GraphStore", direction: str, edge_types: Iterable[str] | None) -> dict[str, list[str]]:
    allowed = set(edge_types) if edge_types else None
    adjacency: dict[str, list[str]] = {}
    for edge in store.edges():
        if allowed and edge.type not in allowed:
            continue
        if direction in ("out", "both"):
            adjacency.setdefault(edge.source, []).append(edge.target)
        if direction in ("in", "both"):
            adjacency.setdefault(edge.target, []).append(edge.source)
    return adjacency


def reachable_set(
    store: "GraphStore",
    start: str,
    *,
    direction: str = "out",
    max_depth: int = 8,
    edge_types: Iterable[str] | None = None,
) -> set[str]:
    """Every node reachable from ``start`` within ``max_depth`` hops."""
    if _rust is not None:  # pragma: no cover
        adjacency = _adjacency(store, direction, edge_types)
        return set(_rust.reachable(adjacency, start, max_depth))

    seen = {start}
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        edges = []
        if direction in ("out", "both"):
            edges += store.out_edges(current, edge_types)
        if direction in ("in", "both"):
            edges += store.in_edges(current, edge_types)
        for edge in edges:
            nxt = edge.target if edge.source == current else edge.source
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, depth + 1))
    return seen


def shortest_distances(
    store: "GraphStore",
    start: str,
    *,
    direction: str = "both",
    edge_types: Iterable[str] | None = None,
) -> dict[str, int]:
    """Hop count from ``start`` to every reachable node."""
    if _rust is not None:  # pragma: no cover
        adjacency = _adjacency(store, direction, edge_types)
        return dict(_rust.distances(adjacency, start))

    distances = {start: 0}
    queue: deque[str] = deque([start])
    while queue:
        current = queue.popleft()
        edges = []
        if direction in ("out", "both"):
            edges += store.out_edges(current, edge_types)
        if direction in ("in", "both"):
            edges += store.in_edges(current, edge_types)
        for edge in edges:
            nxt = edge.target if edge.source == current else edge.source
            if nxt not in distances:
                distances[nxt] = distances[current] + 1
                queue.append(nxt)
    return distances


def degree_centrality(store: "GraphStore", *, top: int = 20) -> list[tuple[str, int]]:
    """Most connected elements -- the coordination hot spots in a project."""
    scored = [(node.id, store.degree(node.id)) for node in store.nodes()]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:top]


def describe() -> dict[str, object]:
    return {"accelerated": ACCELERATED, "backend": BACKEND}
