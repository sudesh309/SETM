"""Compare a project's ontology with the master, and merge either way.

Both sides are in authoring form (see :func:`setm.ontology.loader.ontology_to_source`).
A comparison lists every element type and relation with a status:

``project_only``  added by the project; can be copied to the master
``master_only``   in the master, not used by the project; can be copied in
``differs``       in both, but defined differently; either side can win
``same``          identical where it matters

A project's copy of a relation is cut down to the element types the project
has, so "the master allows more ends" is not reported as a difference: only
ends the project added are.

Merging copies whole definitions, never deletes, and brings what a definition
needs with it: a relation brings its end types, an element type its parent.
Properties are merged, not replaced -- the target keeps properties the source
lacks, because other projects (or the project's own data) may use them.
"""

from __future__ import annotations

import copy
from typing import Any

from ..errors import ValidationError

KINDS = {"element_type": "node_types", "relation": "edge_types"}
DIRECTIONS = ("to_master", "to_project")

#: Fields that describe how a type looks rather than what it means.
_COSMETIC = {"shape", "icon", "style"}


def _ends(spec: dict[str, Any], end: str) -> list[str]:
    return list(spec.get(end) or [])


def _field_changes(kind: str, project: dict[str, Any], master: dict[str, Any], project_types: set[str]) -> list[dict[str, Any]]:
    changes = []
    for field in sorted((set(project) | set(master)) - {"properties"} - _COSMETIC):
        p, m = project.get(field), master.get(field)
        if kind == "relation" and field in ("domain", "range"):
            # The project only ever holds the ends it has types for.
            m_visible = [t for t in _ends(master, field) if t == "*" or t in project_types]
            if sorted(_ends(project, field)) == sorted(m_visible):
                continue
            changes.append({
                "field": field,
                "project": _ends(project, field),
                "master": _ends(master, field),
                "project_adds": sorted(set(_ends(project, field)) - set(_ends(master, field))),
            })
            continue
        if (p or None) != (m or None):
            changes.append({"field": field, "project": p, "master": m})
    return changes


def _property_changes(project: dict[str, Any], master: dict[str, Any]) -> list[dict[str, Any]]:
    pp, mp = project.get("properties") or {}, master.get("properties") or {}
    out = []
    for name in sorted(set(pp) | set(mp)):
        if name not in mp:
            out.append({"property": name, "change": "only_in_project"})
        elif name not in pp:
            out.append({"property": name, "change": "only_in_master"})
        elif pp[name] != mp[name]:
            fields = sorted(k for k in set(pp[name]) | set(mp[name]) if pp[name].get(k) != mp[name].get(k))
            out.append({"property": name, "change": "differs", "fields": fields})
    return out


def compare(project: dict[str, Any], master: dict[str, Any]) -> list[dict[str, Any]]:
    """Every element type and relation of either side, with how they differ."""
    project_types = set(project.get("node_types") or {})
    items: list[dict[str, Any]] = []
    for kind, key in KINDS.items():
        p_all, m_all = project.get(key) or {}, master.get(key) or {}
        names = list(m_all) + [n for n in p_all if n not in m_all]
        for name in names:
            p, m = p_all.get(name), m_all.get(name)
            spec = p or m
            item: dict[str, Any] = {
                "kind": kind,
                "name": name,
                "label": spec.get("label") or name,
                "category": spec.get("category", ""),
                "abstract": bool(spec.get("abstract")),
            }
            if kind == "relation":
                item["domain"], item["range"] = _ends(spec, "domain"), _ends(spec, "range")
            if p is None:
                item["status"] = "master_only"
            elif m is None:
                item["status"] = "project_only"
            else:
                changes = _field_changes(kind, p, m, project_types)
                properties = _property_changes(p, m)
                item["status"] = "differs" if changes or properties else "same"
                item["changes"] = changes
                item["property_changes"] = properties
            items.append(item)
    return items


def summary(items: list[dict[str, Any]]) -> dict[str, int]:
    out = {"project_only": 0, "master_only": 0, "differs": 0, "same": 0}
    for item in items:
        if not item.get("abstract"):
            out[item["status"]] += 1
    return out


def plan_merge(
    direction: str,
    items: list[dict[str, Any]],
    project: dict[str, Any],
    master: dict[str, Any],
    *,
    in_use_properties: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Work out a merge without applying it.

    Returns ``{"source": new target source, "copied": [...], "dependencies":
    [...], "skipped": [...], "notes": [...]}`` where ``copied`` lists what the
    user picked and ``dependencies`` what had to come with it.
    """
    if direction not in DIRECTIONS:
        raise ValidationError(f"direction must be one of {', '.join(DIRECTIONS)}")
    from_src, to_src = (project, master) if direction == "to_master" else (master, project)
    target = copy.deepcopy(to_src)
    target.setdefault("node_types", {})
    target.setdefault("edge_types", {})
    in_use_properties = in_use_properties or {}

    copied: list[dict[str, str]] = []
    dependencies: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    notes: list[str] = []
    done: set[tuple[str, str]] = set()

    def copy_type(name: str, *, dependency: bool) -> None:
        if ("element_type", name) in done:
            return
        spec = (from_src.get("node_types") or {}).get(name)
        if spec is None:
            if name not in target["node_types"]:
                skipped.append({"kind": "element_type", "name": name, "reason": "not defined on the source side"})
            return
        done.add(("element_type", name))
        parent = spec.get("extends")
        if parent and parent not in target["node_types"]:
            copy_type(parent, dependency=True)
        existing = target["node_types"].get(name)
        merged = copy.deepcopy(spec)
        if existing:
            # Keep what the target has that the source lacks.
            kept = {k: v for k, v in (existing.get("properties") or {}).items() if k not in merged.get("properties", {})}
            merged["properties"] = {**kept, **(merged.get("properties") or {})}
            used = in_use_properties.get(name, set())
            if direction == "to_project" and kept and used & set(kept):
                notes.append(f"{name}: kept project properties in use ({', '.join(sorted(used & set(kept)))})")
            if existing == merged:
                return
        target["node_types"][name] = merged
        (dependencies if dependency else copied).append({"kind": "element_type", "name": name})

    def copy_relation(name: str) -> None:
        if ("relation", name) in done:
            return
        spec = (from_src.get("edge_types") or {}).get(name)
        if spec is None:
            skipped.append({"kind": "relation", "name": name, "reason": "not defined on the source side"})
            return
        done.add(("relation", name))
        merged = copy.deepcopy(spec)
        existing = target["edge_types"].get(name) or {}
        for end in ("domain", "range"):
            wanted = _ends(spec, end)
            if direction == "to_master":
                # The master gains the project's ends and keeps its own.
                ends = list(dict.fromkeys(_ends(existing, end) + wanted))
                for type_name in wanted:
                    if type_name != "*" and type_name not in target["node_types"]:
                        copy_type(type_name, dependency=True)
            else:
                # The project takes the master's ends it has types for, keeps
                # ends it added itself, and brings in types for an empty end.
                present = [t for t in wanted if t == "*" or t in target["node_types"]]
                if wanted and not present:
                    for type_name in wanted:
                        copy_type(type_name, dependency=True)
                    present = [t for t in wanted if t in target["node_types"]]
                own = [t for t in _ends(existing, end) if t not in wanted]
                ends = list(dict.fromkeys(present + own))
            merged[end] = ends
        kept = {k: v for k, v in (existing.get("properties") or {}).items() if k not in merged.get("properties", {})}
        merged["properties"] = {**kept, **(merged.get("properties") or {})}
        if existing == merged:
            return
        target["edge_types"][name] = merged
        copied.append({"kind": "relation", "name": name})

    for item in items:
        kind, name = item.get("kind"), str(item.get("name") or "")
        if kind == "element_type":
            copy_type(name, dependency=False)
        elif kind == "relation":
            copy_relation(name)
        else:
            raise ValidationError(f"Unknown kind '{kind}' (use element_type or relation)")

    # Trace paths and roles travel with the relations and types they name.
    if direction == "to_project":
        for path, chain in (master.get("trace_paths") or {}).items():
            if path not in (target.get("trace_paths") or {}) and all(
                s.lstrip("~") in target["edge_types"] for s in chain
            ):
                target.setdefault("trace_paths", {})[path] = list(chain)
        for role, value in (master.get("roles") or {}).items():
            target.setdefault("roles", {}).setdefault(role, value)

    return {
        "direction": direction,
        "source": target,
        "copied": copied,
        "dependencies": dependencies,
        "skipped": skipped,
        "notes": notes,
    }
