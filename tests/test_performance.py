"""The performance restructuring: cached type reasoning, index-driven queries and
thread-safe reads. Each optimisation is checked against the straightforward
computation it replaced, so "faster" can never quietly become "different"."""

from __future__ import annotations

import sys
import threading

from setm.graph import query
from setm.kpi.metrics import compute_kpis


def _uncached_expectations(ontology, type_name):
    """The expectation map computed plainly, with no cache involved at all."""
    expected, directions = {}, {}
    for spec in ontology.edge_types.values():
        if not spec.question:
            continue

        def matches(allowed):
            return not allowed or any(a == "*" or ontology._walk_is_a(type_name, a) for a in allowed)

        if matches(spec.domain):
            expected.setdefault(spec.question, set()).add(spec.name)
            directions[spec.name] = "out"
        elif matches(spec.range):
            expected.setdefault(spec.question, set()).add(spec.name)
            directions[spec.name] = "in"
    return expected, directions


def test_cached_expectations_match_a_plain_walk(ontology):
    for type_name in ontology.node_types:
        cached = ontology.expectations_for(type_name)
        expected, directions = _uncached_expectations(ontology, type_name)
        assert {q: set(v) for q, v in cached.by_question.items()} == expected
        assert cached.directions == directions


def test_is_a_cache_agrees_with_the_walk_and_can_be_cleared(ontology):
    names = list(ontology.node_types) + ["NotAType"]
    for a in names:
        for b in names:
            assert ontology.is_a(a, b) == ontology._walk_is_a(a, b)
    ontology.invalidate_caches()
    assert not ontology._is_a_cache and not ontology._expectation_cache


def test_edges_among_matches_brute_force_on_both_routes(modification_store):
    store = modification_store
    all_ids = [n.id for n in store.nodes()]
    for ids in (set(all_ids[:5]), set(all_ids)):  # the per-node route and the full scan
        brute = {e.id for e in store.edges() if e.source in ids and e.target in ids}
        assert {e.id for e in store.edges_among(ids)} == brute


def test_subgraph_keeps_the_given_node_order(modification_store):
    ids = [n.id for n in modification_store.nodes()][:12][::-1]
    assert [n["id"] for n in query.subgraph(modification_store, ids)["nodes"]] == ids


def test_has_edge_and_edge_types_at_agree_with_edge_lists(modification_store):
    store = modification_store
    for node in store.nodes():
        out_types = {e.type for e in store.out_edges(node.id)}
        in_types = {e.type for e in store.in_edges(node.id)}
        assert store.edge_types_at(node.id) == out_types
        assert store.edge_types_at(node.id, direction="in") == in_types
        for edge_type in store.ontology.edge_types:
            assert store.has_edge(node.id, edge_type) == (edge_type in out_types)
            assert store.has_edge(node.id, edge_type, direction="in") == (edge_type in in_types)


def test_text_search_sees_edits(empty_store):
    node = empty_store.add_node("Person", {"name": "Grace"})
    assert empty_store.find_nodes(text="grace")  # builds the cached haystack
    empty_store.update_node(node.id, {"name": "Ada"})
    assert not empty_store.find_nodes(text="grace")
    assert empty_store.find_nodes(text="ada")


def test_reads_while_writing_never_raise(modification_store):
    """Reads used to iterate live indices unlocked; under the threaded server a
    concurrent write could raise "changed size during iteration"."""
    store = modification_store
    errors: list[BaseException] = []
    stop = threading.Event()

    def writer():
        made: list[str] = []
        try:
            # A sliding window of live nodes: the node dict's keys change on
            # every step, which is what an unlocked iteration trips over.
            for i in range(1500):
                made.append(store.add_node("Person", {"name": f"Temp {i}"}).id)
                if len(made) > 50:
                    store.delete_node(made.pop(0))
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)
        finally:
            stop.set()

    def reader():
        try:
            while not stop.is_set():
                store.find_nodes(text="temp")
                store.nodes_of_type("Person")
                query.subgraph(store, [n.id for n in store.nodes()])
                with store.reading():
                    compute_kpis(store)
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(3)]
    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # switch threads constantly, so the race shows up reliably
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
    finally:
        sys.setswitchinterval(previous)
    assert not errors, errors
