"""RDF / Turtle / OWL backend.

Writes the project graph as Turtle using :mod:`setm.serialize.rdfmap`. Works with
no third-party packages; if rdflib happens to be installed it is used for
*parsing*, so Turtle produced by other tools also loads.

Set ``?sparql=<endpoint>`` on the URI to additionally POST the serialised graph
to a SPARQL 1.1 Graph Store endpoint (Fuseki, GraphDB, Blazegraph).
"""

from __future__ import annotations

from typing import Any

from ..errors import StorageError
from ..model import GraphDocument
from ..ontology.loader import load_ontology
from ..serialize.rdfmap import DEFAULT_DATA_NS, document_to_turtle, turtle_to_document
from .base import FileBackendMixin, SaveResult, StorageBackend
from .registry import register


class RdfBackend(FileBackendMixin, StorageBackend):
    scheme = "rdf"
    capabilities = {"read", "write", "atomic"}

    def __init__(self, target: str, options: dict[str, Any] | None = None) -> None:
        super().__init__(target, options)
        self.ontology: Any = None
        self.data_namespace = str(self.options.get("namespace") or DEFAULT_DATA_NS)

    def _ontology(self) -> Any:
        if self.ontology is None:
            # Standalone use (e.g. `setm convert`) without a bound workspace.
            self.ontology = load_ontology(self.options.get("ontology", "aerospace-se-core"))
        return self.ontology

    def load(self) -> GraphDocument:
        path = self.path
        if not path.exists():
            return GraphDocument()
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return GraphDocument()
        try:
            return turtle_to_document(text, self._ontology())
        except Exception as exc:
            raise StorageError(f"Could not parse {path} as Turtle: {exc}") from None

    def save(self, document: GraphDocument, *, message: str = "", actor: str = "setm") -> SaveResult:
        self.require_writable()
        text = document_to_turtle(document, self._ontology(), data_ns=self.data_namespace)
        self._write_atomic(text)
        endpoint = self.options.get("sparql")
        if endpoint:
            self._push_to_sparql(str(endpoint), text)
        return SaveResult(revision=document.revision, message=message or "saved", location=str(self.path))

    def _push_to_sparql(self, endpoint: str, text: str) -> None:
        import urllib.request

        request = urllib.request.Request(
            endpoint,
            data=text.encode("utf-8"),
            method="PUT",
            headers={"Content-Type": "text/turtle"},
        )
        try:
            with urllib.request.urlopen(request, timeout=float(self.options.get("timeout", 30))) as response:
                if response.status >= 300:
                    raise StorageError(f"SPARQL endpoint returned HTTP {response.status}")
        except OSError as exc:
            raise StorageError(f"Could not reach SPARQL endpoint {endpoint}: {exc}") from None

    def describe(self) -> dict[str, Any]:
        info = super().describe()
        info.update({"format": "turtle", "namespace": self.data_namespace, "sparql": self.options.get("sparql", "")})
        return info


register("rdf", RdfBackend)
register("turtle", RdfBackend)
register("owl", RdfBackend)
