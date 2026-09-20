"""Exchange formats: RDF/Turtle/OWL and spreadsheet tables."""

from .rdfmap import document_to_turtle, ontology_to_owl, turtle_to_document
from .tabular import document_to_tables, tables_to_document

__all__ = [
    "document_to_turtle",
    "turtle_to_document",
    "ontology_to_owl",
    "document_to_tables",
    "tables_to_document",
]
