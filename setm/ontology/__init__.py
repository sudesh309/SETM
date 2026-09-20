"""Ontology loading, validation and RDF/OWL projection."""

from .loader import DEFAULT_ONTOLOGY, build_ontology, dump_ontology, load_ontology, resolve_ontology_path
from .schema import EdgeTypeSpec, NodeTypeSpec, Ontology, PropertySpec
from .validate import validate_document, validate_edge, validate_node

__all__ = [
    "DEFAULT_ONTOLOGY",
    "EdgeTypeSpec",
    "NodeTypeSpec",
    "Ontology",
    "PropertySpec",
    "build_ontology",
    "dump_ontology",
    "load_ontology",
    "resolve_ontology_path",
    "validate_document",
    "validate_edge",
    "validate_node",
]
