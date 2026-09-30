"""A project's own ontology.

Each project keeps a self-contained copy of the vocabulary it uses, in
authoring form (``GraphDocument.ontology``): the master element types and
relations it chose, plus any it added for itself. The copy is what the
project's forms, validation and KPIs work from, and it only changes when the
project changes it -- directly, or by merging from the master.

Edits are made to the source dict, never to a built Ontology, so nothing the
source carries is lost on the way through.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from ..errors import ConflictError, OntologyError, ValidationError
from .loader import build_ontology, ontology_to_source
from .schema import CARDINALITIES, DATATYPES, Ontology

QUESTIONS = ("who", "when", "why", "how", "what", "where", "")
CATEGORIES = ("Why", "What", "How", "Who", "When")


# --------------------------------------------------------------------------- #
# Building a project ontology
# --------------------------------------------------------------------------- #


def from_selection(
    master: Ontology,
    node_types: set[str] | None,
    edge_types: set[str] | None,
    *,
    title: str = "",
) -> dict[str, Any]:
    """A project ontology copied from the chosen part of the master.

    ``None`` for the node types means all of them. Relations default to every
    one whose two ends were chosen.
    """
    if node_types is None:
        chosen = master
    else:
        if edge_types is None:
            edge_types = {
                name for name, spec in master.edge_types.items() if master._ends_available(spec, node_types)
            }
        chosen = master.restricted(node_types, edge_types)
    source = ontology_to_source(chosen)
    source.pop("profiles", None)  # presets belong to the master
    meta = source.setdefault("ontology", {})
    if title:
        meta["title"] = title
    meta["derived_from"] = {"id": master.id, "version": master.version}
    return source


def with_types_in_use(source: dict[str, Any], master: Ontology, node_types: set[str], edge_types: set[str]) -> dict[str, Any]:
    """Add, from the master, any type the data uses that the project lacks.

    Data is never hidden by its own project's vocabulary -- after an import,
    say. Types the master does not know either are left for validation to
    report.
    """
    missing_nodes = {t for t in node_types if t not in source.get("node_types", {}) and t in master.node_types}
    missing_edges = {t for t in edge_types if t not in source.get("edge_types", {}) and t in master.edge_types}
    if not missing_nodes and not missing_edges:
        return source
    from .compare import plan_merge

    items = [{"kind": "element_type", "name": n} for n in sorted(missing_nodes)]
    items += [{"kind": "relation", "name": e} for e in sorted(missing_edges)]
    return plan_merge("to_project", items, source, ontology_to_source(master))["source"]


def build(source: dict[str, Any]) -> Ontology:
    try:
        return build_ontology(source)
    except OntologyError as exc:
        raise ValidationError(f"The project ontology would be invalid: {exc.message}") from None


# --------------------------------------------------------------------------- #
# Editing: add, change and remove element types and relations
# --------------------------------------------------------------------------- #


def type_identifier(label: str) -> str:
    """"Test rig" -> "TestRig"."""
    words = re.findall(r"[A-Za-z0-9]+", label or "")
    ident = "".join(w[:1].upper() + w[1:] for w in words)
    return ident if ident[:1].isalpha() else f"T{ident}"


def relation_identifier(label: str) -> str:
    """"tested on" -> "TESTED_ON"."""
    ident = "_".join(w.upper() for w in re.findall(r"[A-Za-z0-9]+", label or ""))
    return ident if ident[:1].isalpha() else f"R_{ident}"


def _properties(rows: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        label = str(row.get("label") or row.get("name") or "").strip()
        if not label:
            continue
        name = str(row.get("name") or "").strip() or "_".join(re.findall(r"[a-z0-9]+", label.lower()))
        if not name or not name[0].isalpha():
            raise ValidationError(f"Property '{label}' needs a name that starts with a letter")
        datatype = str(row.get("type") or "string")
        if datatype not in DATATYPES:
            raise ValidationError(f"Property '{label}' has an unknown type '{datatype}'")
        spec: dict[str, Any] = {"type": datatype, "label": label, "required": bool(row.get("required"))}
        if datatype == "enum":
            values = row.get("values") or []
            if isinstance(values, str):
                values = [v.strip() for v in values.split(",")]
            values = [str(v).strip() for v in values if str(v).strip()]
            if not values:
                raise ValidationError(f"Property '{label}' is a list of choices but names none")
            spec["values"] = values
        if row.get("unit"):
            spec["unit"] = str(row["unit"])
        spec["group"] = str(row.get("group") or "Details")
        out[name] = spec
    return out


def upsert_element_type(source: dict[str, Any], data: dict[str, Any], *, master: Ontology | None = None,
                        existing: str | None = None) -> tuple[dict[str, Any], str]:
    """Add a new element type, or change one (``existing`` names it)."""
    source = copy.deepcopy(source)
    types = source.setdefault("node_types", {})
    label = str(data.get("label") or "").strip()
    if existing is None:
        if not label:
            raise ValidationError("An element type needs a name")
        name = str(data.get("name") or "").strip() or type_identifier(label)
        if name in types:
            raise ConflictError(f"This project already has an element type '{name}'")
        if master is not None and name in master.node_types:
            raise ConflictError(
                f"The master ontology already defines '{name}'. Add it from the master instead, "
                "so the two stay comparable."
            )
        base = "Thing" if "Thing" in types else None
        spec: dict[str, Any] = {"label": label, "extends": base, "properties": {}}
        # Inherit what every element carries (name, description, weight...).
        if base:
            spec["properties"] = copy.deepcopy(types[base].get("properties", {}))
    else:
        if existing not in types:
            raise ValidationError(f"No element type '{existing}' in this project")
        name = existing
        spec = types[name]
        if label:
            spec["label"] = label
    category = str(data.get("category") or spec.get("category") or "What")
    if category not in CATEGORIES and category != "General":
        raise ValidationError(f"Category must be one of {', '.join(CATEGORIES)}")
    spec["category"] = category
    for key in ("description", "color"):
        if key in data and data[key] is not None:
            spec[key] = str(data[key])
    spec.setdefault("color", "#6b7fd7")
    spec.setdefault("shape", "round")
    spec.setdefault("abstract", False)
    spec.setdefault("title_property", "name")
    spec["properties"] = {**spec.get("properties", {}), **_properties(data.get("properties"))}
    types[name] = spec
    return source, name


def upsert_relation(source: dict[str, Any], data: dict[str, Any], *, master: Ontology | None = None,
                    existing: str | None = None) -> tuple[dict[str, Any], str]:
    """Add a new relation, or change one (``existing`` names it)."""
    source = copy.deepcopy(source)
    relations = source.setdefault("edge_types", {})
    known_types = set(source.get("node_types", {}))
    label = str(data.get("label") or "").strip()
    if existing is None:
        if not label:
            raise ValidationError("A relation needs a name")
        name = str(data.get("name") or "").strip() or relation_identifier(label)
        if name in relations:
            raise ConflictError(f"This project already has a relation '{name}'")
        if master is not None and name in master.edge_types:
            raise ConflictError(f"The master ontology already defines '{name}'. Add it from the master instead.")
        # Every relation carries the properties all relations share (weight, typically).
        shared = _shared_relation_properties(relations)
        spec: dict[str, Any] = {"label": label, "properties": shared, "style": "solid", "color": "#8a94a6"}
    else:
        if existing not in relations:
            raise ValidationError(f"No relation '{existing}' in this project")
        name = existing
        spec = relations[name]
        if label:
            spec["label"] = label
    for end in ("domain", "range"):
        if end in data:
            names = [str(n) for n in data[end] or []]
            unknown = [n for n in names if n not in known_types]
            if unknown:
                raise ValidationError(f"Unknown element types for '{end}': {', '.join(unknown)}")
            if not names:
                raise ValidationError(f"Choose at least one element type for the relation's {'from' if end == 'domain' else 'to'} side")
            spec[end] = names
        elif existing is None:
            raise ValidationError(f"Choose at least one element type for the relation's {'from' if end == 'domain' else 'to'} side")
    question = str(data.get("question", spec.get("question", "")) or "")
    if question not in QUESTIONS:
        raise ValidationError(f"The question must be one of {', '.join(q for q in QUESTIONS if q)}")
    spec["question"] = question
    cardinality = str(data.get("cardinality") or spec.get("cardinality") or "many_to_many")
    if cardinality not in CARDINALITIES:
        raise ValidationError(f"Unknown cardinality '{cardinality}'")
    spec["cardinality"] = cardinality
    for key in ("description", "inverse_label", "color"):
        if key in data and data[key] is not None:
            spec[key] = str(data[key])
    spec["properties"] = {**spec.get("properties", {}), **_properties(data.get("properties"))}
    relations[name] = spec
    return source, name


def _shared_relation_properties(relations: dict[str, Any]) -> dict[str, Any]:
    if not relations:
        return {}
    common = set.intersection(*(set((spec.get("properties") or {}).keys()) for spec in relations.values()))
    first = next(iter(relations.values())).get("properties") or {}
    return {name: copy.deepcopy(first[name]) for name in sorted(common)}


def remove(source: dict[str, Any], kind: str, name: str) -> dict[str, Any]:
    """Remove an element type or relation from the project.

    Removing an element type also takes it off the ends of every relation;
    a relation left with an empty end is removed with it (an empty end would
    mean "anything"). Whether data still uses any of it is checked by the
    workspace, which re-validates the graph before accepting the change.
    """
    source = copy.deepcopy(source)
    if kind == "relation":
        if name not in source.get("edge_types", {}):
            raise ValidationError(f"No relation '{name}' in this project")
        del source["edge_types"][name]
    elif kind == "element_type":
        types = source.get("node_types", {})
        if name not in types:
            raise ValidationError(f"No element type '{name}' in this project")
        children = [t for t, spec in types.items() if spec.get("extends") == name]
        if children:
            raise ConflictError(f"'{name}' is the parent of {', '.join(children)}; remove those first")
        del types[name]
        for rel_name, spec in list(source.get("edge_types", {}).items()):
            for end in ("domain", "range"):
                if name in (spec.get(end) or []):
                    spec[end] = [n for n in spec[end] if n != name]
                    if not spec[end]:
                        del source["edge_types"][rel_name]
                        break
    else:
        raise ValidationError(f"Unknown kind '{kind}'")
    source["trace_paths"] = {
        path: chain
        for path, chain in (source.get("trace_paths") or {}).items()
        if all(step.lstrip("~") in source.get("edge_types", {}) for step in chain)
    }
    return source
