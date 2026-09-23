"""The object that ties ontology, storage and graph together.

One :class:`Workspace` == one open project. The API layer, the CLI and the tests
all drive this same object, so behaviour cannot drift between them.
"""

from __future__ import annotations

import threading
from typing import Any

from .config import Settings
from .errors import ConflictError, StorageError
from .graph.store import GraphStore
from .kpi.telemetry import telemetry
from .model import GraphDocument
from .ontology.loader import load_ontology
from .ontology.schema import Ontology
from .ontology.validate import validate_document
from .storage.base import SaveResult, StorageBackend
from .storage.registry import load_builtin_backends, open_storage


class Workspace:
    def __init__(
        self,
        store: GraphStore,
        backend: StorageBackend,
        settings: Settings,
    ) -> None:
        self.store = store
        self.backend = backend
        self.settings = settings
        self._save_lock = threading.Lock()
        self.last_save: SaveResult | None = None
        self._refresh_gauges()

    # -- construction -------------------------------------------------------
    @classmethod
    def open(cls, settings: Settings | None = None, **overrides: Any) -> "Workspace":
        settings = settings or Settings.load(**overrides)
        load_builtin_backends()

        with telemetry.track("ontology.load"):
            ontology = load_ontology(settings.ontology, overlays=settings.overlays)

        backend = open_storage(settings.storage, **settings.storage_options)
        backend.bind_ontology(ontology)

        with telemetry.track("storage.load", backend=backend.scheme):
            document = backend.load()

        if not document.nodes and not document.edges:
            document.ontology_id = ontology.id
            document.ontology_version = ontology.version

        store = GraphStore(document, ontology, strict=settings.strict)
        telemetry.increment("workspace.opened")
        return cls(store, backend, settings)

    # -- persistence --------------------------------------------------------
    @property
    def ontology(self) -> Ontology:
        return self.store.ontology

    def save(self, *, message: str = "", actor: str = "", force: bool = False) -> SaveResult:
        """Flush to the backend. A no-op when nothing changed, unless forced."""
        with self._save_lock:
            if not self.store.dirty and not force:
                return self.last_save or SaveResult(ok=True, revision=self.store.revision, message="no changes")
            if not self.backend.writable:
                raise StorageError(f"The {self.backend.scheme} backend is open read-only")
            document = self.store.snapshot()
            with telemetry.track("storage.save", backend=self.backend.scheme):
                result = self.backend.save(document, message=message, actor=actor or self.settings.actor)
            self.store.dirty = False
            self.last_save = result
            telemetry.increment("storage.saves", backend=self.backend.scheme)
            self._refresh_gauges()
            return result

    def autosave(self, message: str, actor: str) -> SaveResult | None:
        if not self.settings.autosave or not self.backend.writable:
            self._refresh_gauges()
            return None
        return self.save(message=message, actor=actor)

    def reload(self) -> GraphStore:
        """Re-read from the backend, discarding unsaved in-memory changes."""
        with self._save_lock:
            with telemetry.track("storage.load", backend=self.backend.scheme):
                document = self.backend.load()
            self.store = GraphStore(document, self.ontology, strict=self.settings.strict)
            telemetry.increment("workspace.reloads")
            self._refresh_gauges()
            return self.store

    def reconfigure(self, *, force: bool = False) -> dict[str, Any]:
        """Re-open the workspace against the current settings.

        Used when the settings page changes the storage target, the ontology or
        the overlays: those cannot be edited in place, the whole workspace has
        to be built again. Unsaved work is never discarded silently -- the
        caller must save first, or pass ``force`` having been told what it costs.
        """
        with self._save_lock:
            if self.store.dirty and not force:
                raise ConflictError(
                    "There are unsaved changes. Save them before switching, or "
                    "re-send with force to discard them.",
                    unsaved=True,
                )

            previous = {"storage": self.backend.describe(), "ontology": self.ontology.id}
            with telemetry.track("ontology.load"):
                ontology = load_ontology(self.settings.ontology, overlays=self.settings.overlays)

            backend = open_storage(self.settings.storage, **self.settings.storage_options)
            backend.bind_ontology(ontology)
            with telemetry.track("storage.load", backend=backend.scheme):
                document = backend.load()

            if not document.nodes and not document.edges:
                document.ontology_id = ontology.id
                document.ontology_version = ontology.version

            self.backend = backend
            self.store = GraphStore(document, ontology, strict=self.settings.strict)
            self.last_save = None
            telemetry.increment("workspace.reconfigured")
            self._refresh_gauges()
            return {
                "previous": previous,
                "storage": self.backend.describe(),
                "ontology": {"id": ontology.id, "version": ontology.version},
                "graph": self.store.stats(),
            }

    def apply_settings(self, changed: list[str]) -> dict[str, Any]:
        """Push a settings change into the live workspace.

        Most settings are read fresh on every use, so only the few the store
        caches need doing anything about here.
        """
        if "strict" in changed:
            self.store.strict = self.settings.strict
        return {"applied": changed}

    def reload_ontology(self) -> Ontology:
        """Pick up edits to the ontology file without losing the loaded graph."""
        with self._save_lock:
            ontology = load_ontology(self.settings.ontology, overlays=self.settings.overlays)
            # Holding the old store still from snapshot to swap means a write
            # landing in between cannot be silently left behind in it.
            with self.store.reading():
                document = self.store.snapshot()
                self.store = GraphStore(document, ontology, strict=self.settings.strict)
            self.backend.bind_ontology(ontology)
            telemetry.increment("ontology.reloads")
            return ontology

    def import_document(self, document: GraphDocument, *, merge: bool = False, actor: str = "import") -> dict[str, Any]:
        """Replace or merge the current graph with an imported document."""
        with self._save_lock:
            if merge:
                with self.store.reading():
                    current = self.store.snapshot()
                known_nodes = {n.id for n in current.nodes}
                known_edges = {e.id for e in current.edges}
                current.nodes += [n for n in document.nodes if n.id not in known_nodes]
                current.edges += [e for e in document.edges if e.id not in known_edges]
                current.revision += 1
                document = current
            self.store = GraphStore(document, self.ontology, strict=self.settings.strict)
            self.store.dirty = True
            telemetry.increment("workspace.imports")
            self._refresh_gauges()
            return {"nodes": self.store.node_count, "edges": self.store.edge_count, "merged": merge}

    # -- reporting ----------------------------------------------------------
    def validate(self, *, strict: bool | None = None) -> dict[str, Any]:
        with telemetry.track("graph.validate"):
            return validate_document(
                self.ontology,
                self.store.snapshot(),
                strict=self.settings.strict if strict is None else strict,
            )

    def health(self) -> dict[str, Any]:
        from .graph._fastpath import describe as fastpath_describe

        try:
            backend_health = self.backend.health()
        except Exception as exc:  # a backend probe must never take the app down
            backend_health = {"backend": self.backend.scheme, "status": "error", "error": str(exc)}
        return {
            "status": "ok",
            "graph": self.store.stats(),
            "storage": {**self.backend.describe(), "health": backend_health},
            "ontology": {
                "id": self.ontology.id,
                "version": self.ontology.version,
                "source": self.ontology.source_path,
                "node_types": len(self.ontology.node_types),
                "edge_types": len(self.ontology.edge_types),
            },
            "settings": self.settings.to_dict(),
            "engine": fastpath_describe(),
            "unsaved_changes": self.store.dirty,
            "last_save": self.last_save.to_dict() if self.last_save else None,
        }

    def _refresh_gauges(self) -> None:
        telemetry.gauge("graph.nodes", self.store.node_count)
        telemetry.gauge("graph.edges", self.store.edge_count)
        telemetry.gauge("graph.revision", self.store.revision)
