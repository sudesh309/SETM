"""Validate graph elements against an ontology.

Two entry points:

``validate_node`` / ``validate_edge``
    Called on every write. They *coerce* values where it is unambiguous (the
    string "3" for an integer property, "yes" for a boolean) and raise
    :class:`ValidationError` otherwise.

``validate_document``
    A whole-graph audit used by ``setm validate`` and the ``/api/validate``
    endpoint. It never raises; it returns a report so the UI can show a list.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..errors import ValidationError
from ..model import Edge, GraphDocument, Node
from .schema import EdgeTypeSpec, NodeTypeSpec, Ontology, PropertySpec

_TRUE = {"true", "yes", "y", "1", "on"}
_FALSE = {"false", "no", "n", "0", "off"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].*)?$")


def coerce_value(spec: PropertySpec, value: Any) -> Any:
    """Return ``value`` converted to the property's datatype, or raise."""
    if value is None or value == "":
        return None
    dt = spec.datatype
    try:
        if dt in ("string", "text", "url", "identifier"):
            out: Any = str(value)
        elif dt == "integer":
            out = int(str(value).strip())
        elif dt == "number":
            out = float(str(value).strip())
        elif dt == "boolean":
            if isinstance(value, bool):
                out = value
            else:
                token = str(value).strip().lower()
                if token in _TRUE:
                    out = True
                elif token in _FALSE:
                    out = False
                else:
                    raise ValueError(f"{value!r} is not a boolean")
        elif dt == "enum":
            out = str(value)
            if out not in spec.values:
                raise ValueError(f"{out!r} is not one of: {', '.join(spec.values)}")
        elif dt == "date":
            out = str(value)
            if not _DATE_RE.match(out):
                raise ValueError(f"{out!r} is not an ISO date (YYYY-MM-DD)")
        elif dt == "list":
            if isinstance(value, str):
                items = [v.strip() for v in value.split(",") if v.strip()]
            elif isinstance(value, (list, tuple)):
                items = [str(v) for v in value]
            else:
                raise ValueError("expected a list or a comma separated string")
            out = items
        else:  # pragma: no cover - schema guards this
            out = value
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"Property '{spec.name}' expects {dt}: {exc}",
            issues=[{"property": spec.name, "expected": dt, "value": value}],
        ) from None

    if spec.minimum is not None and isinstance(out, (int, float)) and out < spec.minimum:
        raise ValidationError(f"Property '{spec.name}' must be >= {spec.minimum}")
    if spec.maximum is not None and isinstance(out, (int, float)) and out > spec.maximum:
        raise ValidationError(f"Property '{spec.name}' must be <= {spec.maximum}")
    if spec.pattern and isinstance(out, str) and not re.match(spec.pattern, out):
        raise ValidationError(f"Property '{spec.name}' must match pattern {spec.pattern}")
    return out


def _coerce_properties(
    specs: dict[str, PropertySpec],
    properties: dict[str, Any],
    *,
    owner: str,
    strict: bool,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    unknown = [k for k in properties if k not in specs]
    if unknown and strict:
        raise ValidationError(
            f"{owner} has properties not declared in the ontology: {', '.join(sorted(unknown))}",
            issues=[{"unknown_properties": sorted(unknown)}],
        )
    for key in unknown:  # non-strict mode keeps them so imported data is not lost
        out[key] = properties[key]

    for name, spec in specs.items():
        if name in properties:
            value = coerce_value(spec, properties[name])
        elif spec.default is not None:
            value = spec.default
        else:
            value = None
        if value is None:
            if spec.required:
                raise ValidationError(
                    f"{owner} is missing required property '{spec.name}'",
                    issues=[{"property": spec.name, "required": True}],
                )
            continue
        out[name] = value
    return out


def validate_node(ontology: Ontology, node: Node, *, strict: bool = False) -> Node:
    spec: NodeTypeSpec = ontology.node_type(node.type)
    if spec.abstract:
        raise ValidationError(f"Node type '{spec.name}' is abstract and cannot be instantiated")
    node.properties = _coerce_properties(
        spec.properties, node.properties, owner=f"{node.type} '{node.id}'", strict=strict
    )
    return node


def validate_edge(
    ontology: Ontology,
    edge: Edge,
    source: Node,
    target: Node,
    *,
    strict: bool = False,
) -> Edge:
    spec: EdgeTypeSpec = ontology.edge_type(edge.type)
    if not ontology._type_matches(source.type, spec.domain):
        raise ValidationError(
            f"Edge '{spec.name}' cannot start at a {source.type}; allowed: {', '.join(spec.domain) or 'any'}",
            issues=[{"edge_type": spec.name, "source_type": source.type, "domain": spec.domain}],
        )
    if not ontology._type_matches(target.type, spec.range):
        raise ValidationError(
            f"Edge '{spec.name}' cannot end at a {target.type}; allowed: {', '.join(spec.range) or 'any'}",
            issues=[{"edge_type": spec.name, "target_type": target.type, "range": spec.range}],
        )
    edge.properties = _coerce_properties(
        spec.properties, edge.properties, owner=f"{edge.type} '{edge.id}'", strict=strict
    )
    return edge


def cardinality_limits(ontology: Ontology, edge_type: str) -> tuple[bool, bool]:
    """``(source_must_be_unique, target_must_be_unique)`` for an edge type."""
    cardinality = ontology.edge_type(edge_type).cardinality
    return (
        cardinality in ("one_to_one", "many_to_one"),
        cardinality in ("one_to_one", "one_to_many"),
    )


def cardinality_conflict(
    ontology: Ontology, candidate: Edge, existing: Iterable[Edge]
) -> str | None:
    """Return the id of an edge that blocks ``candidate``, or None.

    ``existing`` should already be narrowed to the edges incident on the
    candidate's endpoints -- the caller has indices, this function does not.
    """
    source_unique, target_unique = cardinality_limits(ontology, candidate.type)
    if not (source_unique or target_unique):
        return None
    for edge in existing:
        if edge.type != candidate.type or edge.id == candidate.id:
            continue
        if source_unique and edge.source == candidate.source:
            return edge.id
        if target_unique and edge.target == candidate.target:
            return edge.id
    return None


def cardinality_error(ontology: Ontology, candidate: Edge, conflicting_id: str) -> ValidationError:
    spec = ontology.edge_type(candidate.type)
    source_unique, _ = cardinality_limits(ontology, candidate.type)
    endpoint = candidate.source if source_unique else candidate.target
    return ValidationError(
        f"'{spec.label}' is {spec.cardinality}: '{endpoint}' already has one "
        f"(edge {conflicting_id})",
        issues=[{"edge_type": spec.name, "conflicting_edge": conflicting_id}],
    )


class CardinalityTracker:
    """Whole-document cardinality check in O(1) per edge.

    ``validate_document`` sees every edge exactly once, so it can remember which
    endpoints are already taken instead of rescanning the edges of each type --
    the difference between linear and quadratic on a large import.
    """

    def __init__(self, ontology: Ontology) -> None:
        self.ontology = ontology
        self._taken_sources: dict[tuple[str, str], str] = {}
        self._taken_targets: dict[tuple[str, str], str] = {}

    def add(self, edge: Edge) -> None:
        """Record ``edge``, raising if it breaks the declared cardinality."""
        source_unique, target_unique = cardinality_limits(self.ontology, edge.type)
        if source_unique:
            key = (edge.type, edge.source)
            clash = self._taken_sources.get(key)
            if clash is not None and clash != edge.id:
                raise cardinality_error(self.ontology, edge, clash)
            self._taken_sources[key] = edge.id
        if target_unique:
            key = (edge.type, edge.target)
            clash = self._taken_targets.get(key)
            if clash is not None and clash != edge.id:
                raise cardinality_error(self.ontology, edge, clash)
            self._taken_targets[key] = edge.id


def validate_document(ontology: Ontology, doc: GraphDocument, *, strict: bool = False) -> dict[str, Any]:
    """Audit a whole graph. Returns a report; never raises."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    by_id: dict[str, Node] = {}

    for node in doc.nodes:
        if node.id in by_id:
            errors.append({"element": node.id, "kind": "node", "message": "Duplicate node id"})
            continue
        by_id[node.id] = node
        try:
            validate_node(ontology, Node.from_dict(node.to_dict()), strict=strict)
        except ValidationError as exc:
            errors.append({"element": node.id, "kind": "node", "message": exc.message})
        except Exception as exc:  # unknown type
            errors.append({"element": node.id, "kind": "node", "message": str(exc)})

    seen_edges: set[str] = set()
    tracker = CardinalityTracker(ontology)
    for edge in doc.edges:
        if edge.id in seen_edges:
            errors.append({"element": edge.id, "kind": "edge", "message": "Duplicate edge id"})
            continue
        seen_edges.add(edge.id)
        source = by_id.get(edge.source)
        target = by_id.get(edge.target)
        if source is None or target is None:
            missing = edge.source if source is None else edge.target
            errors.append(
                {"element": edge.id, "kind": "edge", "message": f"Dangling edge: node '{missing}' does not exist"}
            )
            continue
        try:
            validate_edge(ontology, Edge.from_dict(edge.to_dict()), source, target, strict=strict)
            tracker.add(edge)
        except ValidationError as exc:
            errors.append({"element": edge.id, "kind": "edge", "message": exc.message})
        except Exception as exc:
            errors.append({"element": edge.id, "kind": "edge", "message": str(exc)})

    if doc.ontology_id and doc.ontology_id != ontology.id:
        warnings.append(
            {
                "element": doc.project.id,
                "kind": "document",
                "message": f"Graph was authored against ontology '{doc.ontology_id}', "
                f"validating against '{ontology.id}'",
            }
        )

    return {
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "node_count": len(doc.nodes),
        "edge_count": len(doc.edges),
        "ontology": {"id": ontology.id, "version": ontology.version},
    }
