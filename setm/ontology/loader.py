"""Load, merge and resolve ontology files.

An ontology file is YAML (when PyYAML is installed) or JSON. The loader

* expands ``$ref`` style reuse through ``property_sets``,
* flattens ``extends`` inheritance so every node type carries its full property
  set at runtime,
* checks that every ``domain``/``range`` reference names a declared node type,
* supports layering: a project may ship a small overlay that adds types or
  properties on top of the shipped aerospace ontology.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..errors import DependencyMissing, OntologyError
from .schema import EdgeTypeSpec, NodeTypeSpec, Ontology, PropertySpec

#: Directory holding the ontologies that ship with SETM.
BUILTIN_DIR = Path(__file__).resolve().parents[2] / "ontologies"
DEFAULT_ONTOLOGY = "aerospace-se-core"


def _read_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            raise DependencyMissing("PyYAML", "yaml", f"Reading the YAML ontology {path.name}") from None
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise OntologyError(f"Ontology file {path} must contain a mapping at the top level")
    return data


def resolve_ontology_path(ref: str | os.PathLike[str]) -> Path:
    """Accept a path, or the bare name of a built-in ontology."""
    candidate = Path(ref)
    if candidate.exists():
        return candidate
    for suffix in (".yaml", ".yml", ".json"):
        builtin = BUILTIN_DIR / f"{candidate.name}{suffix}"
        if builtin.exists():
            return builtin
    available = sorted({p.stem for p in BUILTIN_DIR.glob("*.*")}) if BUILTIN_DIR.exists() else []
    raise OntologyError(
        f"Ontology '{ref}' not found. Built-in ontologies: {', '.join(available) or 'none'}"
    )


def load_ontology(ref: str | os.PathLike[str] = DEFAULT_ONTOLOGY, *, overlays: list[str] | None = None) -> Ontology:
    """Load an ontology and apply optional overlay files on top of it."""
    path = resolve_ontology_path(ref)
    raw = _read_structured(path)

    # 'extends_ontology' lets a project ontology build on a shipped one.
    base_ref = raw.get("extends_ontology")
    merged: dict[str, Any]
    if base_ref:
        base_path = resolve_ontology_path(base_ref)
        merged = _deep_merge(_read_structured(base_path), raw)
    else:
        merged = raw

    for overlay in overlays or []:
        merged = _deep_merge(merged, _read_structured(resolve_ontology_path(overlay)))

    ontology = build_ontology(merged)
    ontology.source_path = str(path)
    return ontology


def build_ontology(raw: dict[str, Any]) -> Ontology:
    """Turn a raw mapping into a validated, inheritance-flattened Ontology."""
    meta = raw.get("ontology") or {}
    property_sets = {
        name: {pname: PropertySpec.from_dict(pname, pdata) for pname, pdata in (props or {}).items()}
        for name, props in (raw.get("property_sets") or {}).items()
    }

    node_types: dict[str, NodeTypeSpec] = {}
    for name, data in (raw.get("node_types") or {}).items():
        data = dict(data or {})
        spec = NodeTypeSpec.from_dict(name, data)
        for set_name in data.get("include_properties") or []:
            if set_name not in property_sets:
                raise OntologyError(f"Node type '{name}' includes unknown property set '{set_name}'")
            for pname, pspec in property_sets[set_name].items():
                spec.properties.setdefault(pname, pspec)
        node_types[name] = spec

    edge_types: dict[str, EdgeTypeSpec] = {}
    for name, data in (raw.get("edge_types") or {}).items():
        data = dict(data or {})
        spec = EdgeTypeSpec.from_dict(name, data)
        for set_name in data.get("include_properties") or []:
            if set_name not in property_sets:
                raise OntologyError(f"Edge type '{name}' includes unknown property set '{set_name}'")
            for pname, pspec in property_sets[set_name].items():
                spec.properties.setdefault(pname, pspec)
        edge_types[name] = spec

    _flatten_inheritance(node_types)
    _check_references(node_types, edge_types)

    trace_paths = {}
    for name, chain in (raw.get("trace_paths") or {}).items():
        if not isinstance(chain, list):
            raise OntologyError(f"trace_path '{name}' must be a list of edge type names")
        unknown = [step for step in chain if step.lstrip("~") not in edge_types]
        if unknown:
            raise OntologyError(f"trace_path '{name}' refers to unknown edge types: {', '.join(unknown)}")
        trace_paths[name] = [str(step) for step in chain]

    return Ontology(
        id=str(meta.get("id") or "custom"),
        version=str(meta.get("version") or "0.1.0"),
        title=str(meta.get("title") or meta.get("id") or "Custom ontology"),
        description=str(meta.get("description") or ""),
        namespace=str(meta.get("namespace") or "https://setm.dev/ontology#"),
        prefixes=dict(meta.get("prefixes") or {}),
        node_types=node_types,
        edge_types=edge_types,
        trace_paths=trace_paths,
        roles={str(k): str(v) for k, v in (raw.get("roles") or {}).items()},
    )


def _flatten_inheritance(node_types: dict[str, NodeTypeSpec]) -> None:
    """Copy parent properties down into children, detecting cycles."""
    resolved: set[str] = set()

    def resolve(name: str, stack: tuple[str, ...]) -> None:
        if name in resolved:
            return
        if name in stack:
            raise OntologyError(f"Inheritance cycle in node types: {' -> '.join(stack + (name,))}")
        spec = node_types[name]
        parent_name = spec.extends
        if parent_name:
            if parent_name not in node_types:
                raise OntologyError(f"Node type '{name}' extends unknown type '{parent_name}'")
            resolve(parent_name, stack + (name,))
            parent = node_types[parent_name]
            for pname, pspec in parent.properties.items():
                spec.properties.setdefault(pname, pspec)
            if spec.category == "General":
                spec.category = parent.category
        resolved.add(name)

    for type_name in list(node_types):
        resolve(type_name, ())


def _check_references(node_types: dict[str, NodeTypeSpec], edge_types: dict[str, EdgeTypeSpec]) -> None:
    for spec in edge_types.values():
        for role, names in (("domain", spec.domain), ("range", spec.range)):
            for name in names:
                if name != "*" and name not in node_types:
                    raise OntologyError(
                        f"Edge type '{spec.name}' declares {role} '{name}', which is not a node type"
                    )


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge; overlay wins for scalars, lists are replaced."""
    out = dict(base)
    for key, value in overlay.items():
        if key == "extends_ontology":
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def dump_ontology(ontology: Ontology, path: os.PathLike[str] | str) -> None:
    """Write a resolved ontology back out as JSON (used by ``setm ontology sync``)."""
    Path(path).write_text(json.dumps(_as_source(ontology), indent=2) + "\n", encoding="utf-8")


def _as_source(ontology: Ontology) -> dict[str, Any]:
    """Serialise in the authoring format, not the runtime format."""
    return {
        "ontology": {
            "id": ontology.id,
            "version": ontology.version,
            "title": ontology.title,
            "description": ontology.description,
            "namespace": ontology.namespace,
            "prefixes": ontology.prefixes,
        },
        "node_types": {
            name: {k: v for k, v in spec.to_dict().items() if k != "name"}
            for name, spec in ontology.node_types.items()
        },
        "edge_types": {
            name: {k: v for k, v in spec.to_dict().items() if k != "name"}
            for name, spec in ontology.edge_types.items()
        },
        "trace_paths": ontology.trace_paths,
        "roles": ontology.roles,
    }
