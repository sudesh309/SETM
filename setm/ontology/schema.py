"""Ontology object model.

The ontology is the single source of truth for *what may exist* in a project
graph: which node types, which edge types, which properties each carries, and
which connections are legal. It is authored as a separate YAML/JSON file so a
methods-and-tools team can maintain it without touching application code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..errors import OntologyError

#: Property datatypes understood by the validator and by the UI form generator.
DATATYPES = {
    "string",
    "text",
    "integer",
    "number",
    "boolean",
    "enum",
    "date",
    "url",
    "identifier",
    "list",
}

CARDINALITIES = {"one_to_one", "one_to_many", "many_to_one", "many_to_many"}

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _require_name(value: str, what: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise OntologyError(f"{what} name {value!r} must be alphanumeric starting with a letter")
    return value


@dataclass
class PropertySpec:
    """One attribute of a node or edge type."""

    name: str
    datatype: str = "string"
    label: str = ""
    description: str = ""
    required: bool = False
    default: Any = None
    values: list[str] = field(default_factory=list)  # for enum
    item_type: str = "string"  # for list
    minimum: float | None = None
    maximum: float | None = None
    pattern: str = ""
    unit: str = ""
    group: str = "General"
    #: Free-form hints for the UI, e.g. {"widget": "textarea", "rows": 6}.
    ui: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_name(self.name, "Property")
        if self.datatype not in DATATYPES:
            raise OntologyError(
                f"Property '{self.name}' has unknown datatype '{self.datatype}'. "
                f"Known: {', '.join(sorted(DATATYPES))}"
            )
        if self.datatype == "enum" and not self.values:
            raise OntologyError(f"Enum property '{self.name}' declares no values")
        if not self.label:
            self.label = self.name.replace("_", " ").capitalize()
        if self.pattern:
            try:
                re.compile(self.pattern)
            except re.error as exc:  # pragma: no cover - defensive
                raise OntologyError(f"Property '{self.name}' has an invalid pattern: {exc}") from exc

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any] | str) -> "PropertySpec":
        if isinstance(data, str):  # shorthand:  status: enum
            data = {"type": data}
        data = dict(data or {})
        return cls(
            name=name,
            datatype=str(data.get("type") or data.get("datatype") or "string"),
            label=str(data.get("label") or ""),
            description=str(data.get("description") or ""),
            required=bool(data.get("required", False)),
            default=data.get("default"),
            values=[str(v) for v in (data.get("values") or data.get("enum") or [])],
            item_type=str(data.get("item_type") or "string"),
            minimum=data.get("minimum"),
            maximum=data.get("maximum"),
            pattern=str(data.get("pattern") or ""),
            unit=str(data.get("unit") or ""),
            group=str(data.get("group") or "General"),
            ui=dict(data.get("ui") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "type": self.datatype,
            "label": self.label,
            "required": self.required,
            "group": self.group,
        }
        for key, value in (
            ("description", self.description),
            ("default", self.default),
            ("values", self.values),
            ("minimum", self.minimum),
            ("maximum", self.maximum),
            ("pattern", self.pattern),
            ("unit", self.unit),
            ("ui", self.ui),
        ):
            if value not in (None, "", [], {}):
                out[key] = value
        if self.datatype == "list":
            out["item_type"] = self.item_type
        return out


@dataclass
class NodeTypeSpec:
    name: str
    label: str = ""
    description: str = ""
    extends: str | None = None
    abstract: bool = False
    color: str = "#6b7fd7"
    shape: str = "round"
    icon: str = ""
    category: str = "General"
    #: Property used as the display label in the UI when 'name' is absent.
    title_property: str = "name"
    properties: dict[str, PropertySpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_name(self.name, "Node type")
        if not self.label:
            self.label = re.sub(r"(?<!^)(?=[A-Z])", " ", self.name)

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "NodeTypeSpec":
        data = dict(data or {})
        props = {
            pname: PropertySpec.from_dict(pname, pdata)
            for pname, pdata in (data.get("properties") or {}).items()
        }
        return cls(
            name=name,
            label=str(data.get("label") or ""),
            description=str(data.get("description") or ""),
            extends=data.get("extends"),
            abstract=bool(data.get("abstract", False)),
            color=str(data.get("color") or "#6b7fd7"),
            shape=str(data.get("shape") or "round"),
            icon=str(data.get("icon") or ""),
            category=str(data.get("category") or "General"),
            title_property=str(data.get("title_property") or "name"),
            properties=props,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "extends": self.extends,
            "abstract": self.abstract,
            "color": self.color,
            "shape": self.shape,
            "icon": self.icon,
            "category": self.category,
            "title_property": self.title_property,
            "properties": {p.name: p.to_dict() for p in self.properties.values()},
        }


@dataclass
class EdgeTypeSpec:
    """A typed, directed relation with domain/range constraints.

    ``question`` records which management question the relation answers -- 'who',
    'when', 'why', 'how', 'what' -- which is what drives the traceability views.
    """

    name: str
    label: str = ""
    description: str = ""
    domain: list[str] = field(default_factory=list)
    range: list[str] = field(default_factory=list)
    cardinality: str = "many_to_many"
    inverse_label: str = ""
    question: str = ""
    color: str = "#8a94a6"
    style: str = "solid"
    properties: dict[str, PropertySpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_name(self.name, "Edge type")
        if self.cardinality not in CARDINALITIES:
            raise OntologyError(
                f"Edge type '{self.name}' has unknown cardinality '{self.cardinality}'. "
                f"Known: {', '.join(sorted(CARDINALITIES))}"
            )
        if not self.label:
            self.label = self.name.replace("_", " ").lower()

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "EdgeTypeSpec":
        data = dict(data or {})
        props = {
            pname: PropertySpec.from_dict(pname, pdata)
            for pname, pdata in (data.get("properties") or {}).items()
        }
        domain = data.get("domain") or []
        rng = data.get("range") or []
        return cls(
            name=name,
            label=str(data.get("label") or ""),
            description=str(data.get("description") or ""),
            domain=[domain] if isinstance(domain, str) else [str(d) for d in domain],
            range=[rng] if isinstance(rng, str) else [str(r) for r in rng],
            cardinality=str(data.get("cardinality") or "many_to_many"),
            inverse_label=str(data.get("inverse_label") or ""),
            question=str(data.get("question") or ""),
            color=str(data.get("color") or "#8a94a6"),
            style=str(data.get("style") or "solid"),
            properties=props,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "domain": list(self.domain),
            "range": list(self.range),
            "cardinality": self.cardinality,
            "inverse_label": self.inverse_label,
            "question": self.question,
            "color": self.color,
            "style": self.style,
            "properties": {p.name: p.to_dict() for p in self.properties.values()},
        }


@dataclass
class Ontology:
    """A resolved ontology: inheritance flattened, references checked."""

    id: str = "custom"
    version: str = "0.1.0"
    title: str = ""
    description: str = ""
    namespace: str = "https://setm.dev/ontology#"
    prefixes: dict[str, str] = field(default_factory=dict)
    node_types: dict[str, NodeTypeSpec] = field(default_factory=dict)
    edge_types: dict[str, EdgeTypeSpec] = field(default_factory=dict)
    #: Optional declarative traceability chains, used by the UI and KPI engine.
    trace_paths: dict[str, list[str]] = field(default_factory=dict)
    #: Semantic role -> type/property name. Lets the generic KPI engine find the
    #: "activity" or "milestone" concept in an ontology that renamed them.
    roles: dict[str, str] = field(default_factory=dict)
    source_path: str = ""

    def role(self, name: str, default: str = "") -> str:
        return self.roles.get(name, default)

    def node_role(self, name: str) -> str:
        """Role lookup that returns '' unless the mapped type actually exists."""
        value = self.roles.get(name, "")
        return value if value in self.node_types else ""

    def edge_role(self, name: str) -> str:
        value = self.roles.get(name, "")
        return value if value in self.edge_types else ""

    # -- lookups -------------------------------------------------------------
    def node_type(self, name: str) -> NodeTypeSpec:
        try:
            return self.node_types[name]
        except KeyError:
            raise OntologyError(
                f"Unknown node type '{name}'. Declared types: {', '.join(sorted(self.node_types))}"
            ) from None

    def edge_type(self, name: str) -> EdgeTypeSpec:
        try:
            return self.edge_types[name]
        except KeyError:
            raise OntologyError(
                f"Unknown edge type '{name}'. Declared types: {', '.join(sorted(self.edge_types))}"
            ) from None

    def concrete_node_types(self) -> list[NodeTypeSpec]:
        return [t for t in self.node_types.values() if not t.abstract]

    def is_a(self, type_name: str, ancestor: str) -> bool:
        """True when ``type_name`` equals or inherits from ``ancestor``."""
        seen: set[str] = set()
        current: str | None = type_name
        while current and current not in seen:
            if current == ancestor:
                return True
            seen.add(current)
            spec = self.node_types.get(current)
            current = spec.extends if spec else None
        return False

    def edges_allowed_between(self, source_type: str, target_type: str) -> list[EdgeTypeSpec]:
        return [
            spec
            for spec in self.edge_types.values()
            if self._type_matches(source_type, spec.domain) and self._type_matches(target_type, spec.range)
        ]

    def edges_from(self, source_type: str) -> list[EdgeTypeSpec]:
        return [s for s in self.edge_types.values() if self._type_matches(source_type, s.domain)]

    def _type_matches(self, type_name: str, allowed: Iterable[str]) -> bool:
        allowed = list(allowed)
        if not allowed:  # unconstrained
            return True
        return any(a == "*" or self.is_a(type_name, a) for a in allowed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "namespace": self.namespace,
            "prefixes": dict(self.prefixes),
            "node_types": {n.name: n.to_dict() for n in self.node_types.values()},
            "edge_types": {e.name: e.to_dict() for e in self.edge_types.values()},
            "trace_paths": {k: list(v) for k, v in self.trace_paths.items()},
            "roles": dict(self.roles),
            "source_path": self.source_path,
        }
