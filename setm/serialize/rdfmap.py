"""Map between SETM's graph model and RDF triples.

Three directions are supported:

``ontology_to_triples``
    Emits the ontology as OWL: node types become ``owl:Class``, edge types become
    ``owl:ObjectProperty`` with domain/range, properties become
    ``owl:DatatypeProperty``. This is the artefact you hand to a semantic-web
    toolchain (Protege, a triple store, a SHACL validator).

``document_to_triples`` / ``triples_to_document``
    Instance data. Every edge is written twice: once as a direct triple so
    ordinary SPARQL works, and once as a reified ``setm:Relation`` so edge ids
    and edge properties survive a round trip.
"""

from __future__ import annotations

from typing import Any, Sequence
from urllib.parse import quote, unquote

from ..model import Edge, GraphDocument, Node, ProjectInfo, Provenance
from ..ontology.schema import Ontology, PropertySpec
from .turtle import (
    DCTERMS,
    OWL,
    RDF,
    RDFS,
    XSD,
    Term,
    Triple,
    group_by_subject,
    iri,
    lit,
    literal_value,
    parse_turtle,
    serialize_triples,
)

SETM_NS = "https://setm.dev/schema#"
DEFAULT_DATA_NS = "https://setm.dev/data#"

_XSD_FOR_DATATYPE = {
    "string": XSD + "string",
    "text": XSD + "string",
    "identifier": XSD + "string",
    "url": XSD + "anyURI",
    "enum": XSD + "string",
    "integer": XSD + "integer",
    "number": XSD + "double",
    "boolean": XSD + "boolean",
    "date": XSD + "date",
    "list": XSD + "string",
}


def _class_iri(ontology: Ontology, type_name: str) -> str:
    return ontology.namespace + type_name


def _property_iri(ontology: Ontology, name: str) -> str:
    return ontology.namespace + name


def _node_iri(data_ns: str, node_id: str) -> str:
    return data_ns + quote(node_id, safe="")


def _edge_iri(data_ns: str, edge_id: str) -> str:
    return f"{data_ns}rel-{quote(edge_id, safe='')}"


def _prefixes(ontology: Ontology, data_ns: str) -> dict[str, str]:
    prefixes = {"setm": SETM_NS, "onto": ontology.namespace, "data": data_ns}
    prefixes.update(ontology.prefixes)
    return prefixes


# --------------------------------------------------------------------------- #
# Ontology -> OWL
# --------------------------------------------------------------------------- #


def ontology_to_triples(ontology: Ontology) -> list[Triple]:
    triples: list[Triple] = []
    onto_iri = ontology.namespace.rstrip("#/")
    triples += [
        (iri(onto_iri), iri(RDF + "type"), iri(OWL + "Ontology")),
        (iri(onto_iri), iri(DCTERMS + "identifier"), lit(ontology.id)),
        (iri(onto_iri), iri(OWL + "versionInfo"), lit(ontology.version)),
    ]
    if ontology.title:
        triples.append((iri(onto_iri), iri(RDFS + "label"), lit(ontology.title)))
    if ontology.description:
        triples.append((iri(onto_iri), iri(RDFS + "comment"), lit(ontology.description)))

    # Which classes use each datatype property, so we can set rdfs:domain safely.
    usage: dict[str, set[str]] = {}
    datatypes: dict[str, PropertySpec] = {}
    for node_type in ontology.node_types.values():
        for spec in node_type.properties.values():
            usage.setdefault(spec.name, set()).add(node_type.name)
            datatypes.setdefault(spec.name, spec)

    for node_type in ontology.node_types.values():
        subject = iri(_class_iri(ontology, node_type.name))
        triples.append((subject, iri(RDF + "type"), iri(OWL + "Class")))
        triples.append((subject, iri(RDFS + "label"), lit(node_type.label)))
        if node_type.description:
            triples.append((subject, iri(RDFS + "comment"), lit(node_type.description)))
        if node_type.extends:
            triples.append((subject, iri(RDFS + "subClassOf"), iri(_class_iri(ontology, node_type.extends))))
        triples.append((subject, iri(SETM_NS + "category"), lit(node_type.category)))
        triples.append((subject, iri(SETM_NS + "color"), lit(node_type.color)))

    for name, spec in sorted(datatypes.items()):
        subject = iri(_property_iri(ontology, name))
        triples.append((subject, iri(RDF + "type"), iri(OWL + "DatatypeProperty")))
        triples.append((subject, iri(RDFS + "label"), lit(spec.label)))
        triples.append((subject, iri(RDFS + "range"), iri(_XSD_FOR_DATATYPE.get(spec.datatype, XSD + "string"))))
        owners = usage.get(name, set())
        if len(owners) == 1:  # a shared property gets no domain: it would read as an intersection
            triples.append((subject, iri(RDFS + "domain"), iri(_class_iri(ontology, next(iter(owners))))))
        if spec.datatype == "enum":
            triples.append((subject, iri(SETM_NS + "enumValues"), lit(", ".join(spec.values))))

    for edge_type in ontology.edge_types.values():
        subject = iri(_property_iri(ontology, edge_type.name))
        triples.append((subject, iri(RDF + "type"), iri(OWL + "ObjectProperty")))
        triples.append((subject, iri(RDFS + "label"), lit(edge_type.label)))
        if edge_type.description:
            triples.append((subject, iri(RDFS + "comment"), lit(edge_type.description)))
        if len(edge_type.domain) == 1:
            triples.append((subject, iri(RDFS + "domain"), iri(_class_iri(ontology, edge_type.domain[0]))))
        if len(edge_type.range) == 1:
            triples.append((subject, iri(RDFS + "range"), iri(_class_iri(ontology, edge_type.range[0]))))
        if edge_type.cardinality in ("many_to_one", "one_to_one"):
            triples.append((subject, iri(RDF + "type"), iri(OWL + "FunctionalProperty")))
        if edge_type.cardinality in ("one_to_many", "one_to_one"):
            triples.append((subject, iri(RDF + "type"), iri(OWL + "InverseFunctionalProperty")))
        if edge_type.question:
            triples.append((subject, iri(SETM_NS + "answersQuestion"), lit(edge_type.question)))
    return triples


def ontology_to_owl(ontology: Ontology) -> str:
    return serialize_triples(
        ontology_to_triples(ontology),
        _prefixes(ontology, DEFAULT_DATA_NS),
        header=f"OWL export of ontology '{ontology.id}' v{ontology.version} - generated by SETM",
    )


# --------------------------------------------------------------------------- #
# Instance data
# --------------------------------------------------------------------------- #


def _property_terms(ontology: Ontology, specs: dict[str, PropertySpec], properties: dict[str, Any]) -> list[tuple[Term, Term]]:
    out: list[tuple[Term, Term]] = []
    for key, value in properties.items():
        if value is None:
            continue
        predicate = iri(_property_iri(ontology, key))
        spec = specs.get(key)
        if isinstance(value, list):
            for item in value:
                out.append((predicate, lit(item)))
        elif spec and spec.datatype in ("integer", "number", "boolean"):
            out.append((predicate, lit(value)))
        else:
            out.append((predicate, lit(value, _XSD_FOR_DATATYPE.get(spec.datatype) if spec else None)))
    return out


def _provenance_terms(prov: Provenance) -> list[tuple[Term, Term]]:
    return [
        (iri(DCTERMS + "created"), lit(prov.created_at, XSD + "dateTime")),
        (iri(DCTERMS + "creator"), lit(prov.created_by)),
        (iri(DCTERMS + "modified"), lit(prov.updated_at, XSD + "dateTime")),
        (iri(SETM_NS + "modifiedBy"), lit(prov.updated_by)),
        (iri(SETM_NS + "revision"), lit(prov.revision)),
        (iri(SETM_NS + "source"), lit(prov.source)),
    ]


def document_to_triples(doc: GraphDocument, ontology: Ontology, *, data_ns: str = DEFAULT_DATA_NS) -> list[Triple]:
    triples: list[Triple] = []
    project = iri(data_ns + quote(doc.project.id, safe=""))
    triples += [
        (project, iri(RDF + "type"), iri(SETM_NS + "Project")),
        (project, iri(RDFS + "label"), lit(doc.project.name)),
        (project, iri(SETM_NS + "programme"), lit(doc.project.programme)),
        (project, iri(SETM_NS + "phase"), lit(doc.project.phase)),
        (project, iri(SETM_NS + "chiefEngineer"), lit(doc.project.chief_engineer)),
        (project, iri(SETM_NS + "ontologyId"), lit(doc.ontology_id)),
        (project, iri(SETM_NS + "ontologyVersion"), lit(doc.ontology_version)),
        (project, iri(SETM_NS + "revision"), lit(doc.revision)),
    ]
    if doc.project.description:
        triples.append((project, iri(RDFS + "comment"), lit(doc.project.description)))

    for node in doc.nodes:
        subject = iri(_node_iri(data_ns, node.id))
        specs = ontology.node_types[node.type].properties if node.type in ontology.node_types else {}
        triples.append((subject, iri(RDF + "type"), iri(_class_iri(ontology, node.type))))
        triples.append((subject, iri(SETM_NS + "localId"), lit(node.id)))
        triples.append((subject, iri(RDFS + "label"), lit(node.label)))
        triples.append((subject, iri(SETM_NS + "partOfProject"), project))
        for predicate, obj in _property_terms(ontology, specs, node.properties):
            triples.append((subject, predicate, obj))
        for predicate, obj in _provenance_terms(node.provenance):
            triples.append((subject, predicate, obj))

    for edge in doc.edges:
        source = iri(_node_iri(data_ns, edge.source))
        target = iri(_node_iri(data_ns, edge.target))
        predicate = iri(_property_iri(ontology, edge.type))
        triples.append((source, predicate, target))

        # Reification keeps the edge id and any edge properties round-trippable.
        statement = iri(_edge_iri(data_ns, edge.id))
        specs = ontology.edge_types[edge.type].properties if edge.type in ontology.edge_types else {}
        triples += [
            (statement, iri(RDF + "type"), iri(SETM_NS + "Relation")),
            (statement, iri(RDF + "subject"), source),
            (statement, iri(RDF + "predicate"), predicate),
            (statement, iri(RDF + "object"), target),
            (statement, iri(SETM_NS + "localId"), lit(edge.id)),
        ]
        for prop_predicate, obj in _property_terms(ontology, specs, edge.properties):
            triples.append((statement, prop_predicate, obj))
        for prov_predicate, obj in _provenance_terms(edge.provenance):
            triples.append((statement, prov_predicate, obj))
    return triples


def document_to_turtle(doc: GraphDocument, ontology: Ontology, *, data_ns: str = DEFAULT_DATA_NS) -> str:
    return serialize_triples(
        document_to_triples(doc, ontology, data_ns=data_ns),
        _prefixes(ontology, data_ns),
        header=(
            f"SETM project graph '{doc.project.name}' (revision {doc.revision})\n"
            f"ontology: {doc.ontology_id} v{doc.ontology_version}"
        ),
    )


def _collect_provenance(pairs: dict[str, list[Any]]) -> Provenance:
    def first(key: str, default: Any) -> Any:
        values = pairs.get(key)
        return values[0] if values else default

    return Provenance.from_dict(
        {
            "created_at": first(DCTERMS + "created", None),
            "created_by": first(DCTERMS + "creator", None),
            "updated_at": first(DCTERMS + "modified", None),
            "updated_by": first(SETM_NS + "modifiedBy", None),
            "revision": first(SETM_NS + "revision", 1),
            "source": first(SETM_NS + "source", "rdf"),
        }
    )


_SKIP_PREDICATES = {
    RDF + "type",
    RDF + "subject",
    RDF + "predicate",
    RDF + "object",
    RDFS + "label",
    SETM_NS + "localId",
    SETM_NS + "partOfProject",
    SETM_NS + "modifiedBy",
    SETM_NS + "revision",
    SETM_NS + "source",
    DCTERMS + "created",
    DCTERMS + "creator",
    DCTERMS + "modified",
}


def triples_to_document(triples: Sequence[Triple], ontology: Ontology) -> GraphDocument:
    """Rebuild a graph document from triples produced by ``document_to_triples``."""
    grouped = group_by_subject(triples)
    class_to_type = {_class_iri(ontology, name): name for name in ontology.node_types}
    iri_to_edge_type = {_property_iri(ontology, name): name for name in ontology.edge_types}

    doc = GraphDocument(nodes=[], edges=[])
    iri_to_local: dict[str, str] = {}

    for subject_iri, pairs in grouped.items():
        values: dict[str, list[Any]] = {}
        for predicate, obj in pairs:
            values.setdefault(predicate, []).append(obj)
        types = [t[1] for t in values.get(RDF + "type", []) if t[0] == "iri"]

        if SETM_NS + "Project" in types:
            doc.project = ProjectInfo(
                id=unquote(subject_iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]),
                name=str(literal_value(values.get(RDFS + "label", [lit("Untitled project")])[0])),
                programme=str(literal_value(values.get(SETM_NS + "programme", [lit("")])[0])),
                phase=str(literal_value(values.get(SETM_NS + "phase", [lit("")])[0])),
                description=str(literal_value(values.get(RDFS + "comment", [lit("")])[0])),
                chief_engineer=str(literal_value(values.get(SETM_NS + "chiefEngineer", [lit("")])[0])),
            )
            if SETM_NS + "ontologyId" in values:
                doc.ontology_id = str(literal_value(values[SETM_NS + "ontologyId"][0]))
            if SETM_NS + "ontologyVersion" in values:
                doc.ontology_version = str(literal_value(values[SETM_NS + "ontologyVersion"][0]))
            if SETM_NS + "revision" in values:
                doc.revision = int(literal_value(values[SETM_NS + "revision"][0]))  # type: ignore[arg-type]
            continue

        node_type = next((class_to_type[t] for t in types if t in class_to_type), None)
        if node_type is None:
            continue
        local_id = str(literal_value(values.get(SETM_NS + "localId", [lit(unquote(subject_iri.rsplit("#", 1)[-1]))])[0]))
        iri_to_local[subject_iri] = local_id
        doc.nodes.append(
            Node(
                id=local_id,
                type=node_type,
                properties=_properties_from(values, ontology, node_type, is_edge=False),
                provenance=_collect_provenance({k: [literal_value(v) for v in vs] for k, vs in values.items()}),
            )
        )

    for subject_iri, pairs in grouped.items():
        values: dict[str, list[Any]] = {}
        for predicate, obj in pairs:
            values.setdefault(predicate, []).append(obj)
        if SETM_NS + "Relation" not in [t[1] for t in values.get(RDF + "type", []) if t[0] == "iri"]:
            continue
        predicate_iri = values[RDF + "predicate"][0][1]
        edge_type = iri_to_edge_type.get(predicate_iri)
        if edge_type is None:
            continue
        source_iri = values[RDF + "subject"][0][1]
        target_iri = values[RDF + "object"][0][1]
        doc.edges.append(
            Edge(
                id=str(literal_value(values.get(SETM_NS + "localId", [lit(subject_iri.rsplit("rel-", 1)[-1])])[0])),
                type=edge_type,
                source=iri_to_local.get(source_iri, unquote(source_iri.rsplit("#", 1)[-1])),
                target=iri_to_local.get(target_iri, unquote(target_iri.rsplit("#", 1)[-1])),
                properties=_properties_from(values, ontology, edge_type, is_edge=True),
                provenance=_collect_provenance({k: [literal_value(v) for v in vs] for k, vs in values.items()}),
            )
        )
    return doc


def _properties_from(
    values: dict[str, list[Term]], ontology: Ontology, type_name: str, *, is_edge: bool
) -> dict[str, Any]:
    specs = (ontology.edge_types if is_edge else ontology.node_types)[type_name].properties
    out: dict[str, Any] = {}
    for predicate, terms in values.items():
        if predicate in _SKIP_PREDICATES or not predicate.startswith(ontology.namespace):
            continue
        name = predicate[len(ontology.namespace) :]
        spec = specs.get(name)
        decoded = [literal_value(t) for t in terms if t[0] == "lit"]
        if not decoded:
            continue
        out[name] = decoded if (spec and spec.datatype == "list") or len(decoded) > 1 else decoded[0]
    return out


def turtle_to_document(text: str, ontology: Ontology) -> GraphDocument:
    """Parse Turtle into a document, preferring rdflib when it is installed."""
    try:  # rdflib handles Turtle features our parser intentionally omits
        import rdflib  # type: ignore

        graph = rdflib.Graph()
        graph.parse(data=text, format="turtle")
        triples: list[Triple] = []
        for subject, predicate, obj in graph:
            subject_term = iri(str(subject))
            predicate_term = iri(str(predicate))
            if isinstance(obj, rdflib.Literal):
                object_term: Term = (
                    "lit",
                    str(obj),
                    str(obj.datatype) if obj.datatype else None,
                    str(obj.language) if obj.language else None,
                )
            else:
                object_term = iri(str(obj))
            triples.append((subject_term, predicate_term, object_term))
    except ImportError:
        triples, _ = parse_turtle(text)
    return triples_to_document(triples, ontology)
