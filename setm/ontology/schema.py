"""Ontology object model.

The ontology is the single source of truth for *what may exist* in a project
graph: which node types, which edge types, which properties each carries, and
which connections are legal. It is authored as a separate YAML/JSON file so a
methods-and-tools team can maintain it without touching application code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
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


@dataclass(frozen=True)
class Expectations:
    """The relations an element of one type is expected to have, by question."""

    #: question -> the edge types that would answer it
    by_question: dict[str, frozenset[str]]
    #: edge type -> "out" or "in", the direction it attaches to this type
    directions: dict[str, str]


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
    #: Named project profiles ("light", "full", ...): which element types a
    #: project uses. See resolve_profile() and restricted().
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Memoised type reasoning (see "type reasoning" below). An ontology is
    #: treated as immutable once built -- a reload builds a new object -- so the
    #: caches never need invalidating in normal use; invalidate_caches() exists
    #: for code that edits one in place.
    _is_a_cache: dict[tuple[str, str], bool] = field(default_factory=dict, init=False, repr=False, compare=False)
    _match_cache: dict[tuple[str, tuple[str, ...]], bool] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _expectation_cache: dict[str, "Expectations"] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

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

    # -- type reasoning --------------------------------------------------------
    # Every question of the form "may this type take part in that relation" goes
    # through is_a / _type_matches. They are asked hundreds of thousands of times
    # while computing KPIs over a large graph, always with the same few dozen
    # answers, so each answer is worked out once per ontology.

    def invalidate_caches(self) -> None:
        self._is_a_cache.clear()
        self._match_cache.clear()
        self._expectation_cache.clear()

    def is_a(self, type_name: str, ancestor: str) -> bool:
        """True when ``type_name`` equals or inherits from ``ancestor``."""
        key = (type_name, ancestor)
        cached = self._is_a_cache.get(key)
        if cached is None:
            cached = self._is_a_cache[key] = self._walk_is_a(type_name, ancestor)
        return cached

    def _walk_is_a(self, type_name: str, ancestor: str) -> bool:
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
        key = (type_name, tuple(allowed))
        cached = self._match_cache.get(key)
        if cached is None:
            # Empty means unconstrained.
            cached = not key[1] or any(a == "*" or self.is_a(type_name, a) for a in key[1])
            self._match_cache[key] = cached
        return cached

    def expectations_for(self, type_name: str) -> "Expectations":
        """Which management questions an element of this type is expected to answer.

        An edge type whose domain accepts the type is expected outwards, one whose
        range accepts it inwards -- which is how "who owns this activity", an
        incoming Person -> Activity relation, counts. The answer depends only on
        the type, so it is computed once per type rather than once per element.
        """
        cached = self._expectation_cache.get(type_name)
        if cached is not None:
            return cached
        expected: dict[str, set[str]] = {}
        directions: dict[str, str] = {}
        for spec in self.edge_types.values():
            if not spec.question:
                continue
            if self._type_matches(type_name, spec.domain):
                expected.setdefault(spec.question, set()).add(spec.name)
                directions[spec.name] = "out"
            elif self._type_matches(type_name, spec.range):
                expected.setdefault(spec.question, set()).add(spec.name)
                directions[spec.name] = "in"
        cached = Expectations(
            by_question={q: frozenset(names) for q, names in expected.items()},
            directions=dict(directions),
        )
        self._expectation_cache[type_name] = cached
        return cached

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
            "profiles": {k: dict(v) for k, v in self.profiles.items()},
        }

    # -- project profiles -----------------------------------------------------
    # A project need not use the whole vocabulary. A profile names the element
    # types and relations it does use; the store is then given restricted(...),
    # and every form, picker, validator and KPI follows without knowing why.

    def resolve_profile(
        self, profile: dict[str, Any] | None, *, strict: bool = True
    ) -> tuple[set[str], set[str]] | None:
        """The element types and relations a profile selects, or None for "everything".

        ``strict`` rejects names the ontology does not declare; opening a stored
        project passes ``strict=False`` so an ontology edit cannot lock it out.

        A profile either lists ``node_types`` (and optionally ``edge_types``) or
        names a ``preset`` declared under ``profiles:`` in the ontology file. When
        relations are not listed, every relation whose two ends are selected is
        included.
        """
        profile = dict(profile or {})
        preset = str(profile.get("preset") or "")
        if "node_types" not in profile and preset:
            if preset not in self.profiles:
                raise OntologyError(
                    f"Unknown profile '{preset}'. Declared: {', '.join(sorted(self.profiles)) or 'none'}"
                )
            profile = {**self.profiles[preset], "preset": preset}
        if "node_types" not in profile:
            return None  # full: the whole ontology, including types added later
        nodes = {str(n) for n in profile.get("node_types") or []}
        unknown = sorted(n for n in nodes if n not in self.node_types)
        if unknown and strict:
            raise OntologyError(f"Profile names unknown element types: {', '.join(unknown)}")
        nodes -= set(unknown)  # lenient: a type since removed from the ontology file
        if "edge_types" in profile and profile["edge_types"] is not None:
            edges = {str(e) for e in profile["edge_types"]}
            unknown = sorted(e for e in edges if e not in self.edge_types)
            if unknown and strict:
                raise OntologyError(f"Profile names unknown relations: {', '.join(unknown)}")
            edges -= set(unknown)
        else:
            edges = {name for name, spec in self.edge_types.items() if self._ends_available(spec, nodes)}
        return nodes, edges

    def _ends_available(self, spec: "EdgeTypeSpec", nodes: set[str]) -> bool:
        """Can this relation join two of the given types?"""
        def side(allowed: list[str]) -> bool:
            return not allowed or "*" in allowed or any(
                self.is_a(n, a) for n in nodes for a in allowed
            )
        return side(spec.domain) and side(spec.range)

    def restricted(self, node_types: Iterable[str], edge_types: Iterable[str]) -> "Ontology":
        """A copy limited to the given element types and relations.

        * The ``extends`` ancestors of a kept type are kept too (they are
          abstract, so they add nothing a user can create).
        * A kept relation's domain and range are pruned to kept types. One left
          with an empty end is dropped: an empty list means *unconstrained*, so
          keeping it would widen the rule rather than narrow it.
        * Trace paths through a dropped relation are dropped. Roles are kept;
          a role naming an absent type already resolves to "" and the KPIs that
          need it report themselves unavailable.
        """
        keep: set[str] = set()
        for name in node_types:
            current: str | None = name
            while current and current in self.node_types and current not in keep:
                keep.add(current)
                current = self.node_types[current].extends
        wanted = set(edge_types)
        kept_edges: dict[str, EdgeTypeSpec] = {}
        for name, spec in self.edge_types.items():
            if name not in wanted:
                continue
            domain = [d for d in spec.domain if d == "*" or d in keep]
            rng = [r for r in spec.range if r == "*" or r in keep]
            if (spec.domain and not domain) or (spec.range and not rng):
                continue
            kept_edges[name] = replace(spec, domain=domain, range=rng)
        return Ontology(
            id=self.id,
            version=self.version,
            title=self.title,
            description=self.description,
            namespace=self.namespace,
            prefixes=dict(self.prefixes),
            node_types={n: spec for n, spec in self.node_types.items() if n in keep},
            edge_types=kept_edges,
            trace_paths={
                n: list(chain)
                for n, chain in self.trace_paths.items()
                if all(step.lstrip("~") in kept_edges for step in chain)
            },
            roles=dict(self.roles),
            source_path=self.source_path,
            profiles={k: dict(v) for k, v in self.profiles.items()},
        )
