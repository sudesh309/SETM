"""The object that ties ontology, storage and graph together.

One :class:`Workspace` == one open project. The API layer, the CLI and the tests
all drive this same object, so behaviour cannot drift between them.
"""

from __future__ import annotations

import threading
from typing import Any

from .config import Settings
from .errors import ConflictError, StorageError, ValidationError
from .graph.store import GraphStore
from .kpi.telemetry import telemetry
from .model import GraphDocument
from .ontology.loader import load_ontology
from .ontology.schema import Ontology
from .ontology.validate import validate_document
from .storage.base import SaveResult, StorageBackend
from .storage.registry import load_builtin_backends, open_storage


def effective_ontology(base: Ontology, document: GraphDocument) -> Ontology:
    """The ontology a project works with: the base, limited to its profile.

    Widened by whatever the document already contains, so data can never be
    hidden by its own profile -- after an import, say, or an ontology edit.
    """
    selection = base.resolve_profile(document.project.profile, strict=False)
    if selection is None:
        return base
    nodes, edges = selection
    nodes |= {n.type for n in document.nodes if n.type in base.node_types}
    edges |= {e.type for e in document.edges if e.type in base.edge_types}
    return base.restricted(nodes, edges)


def normalise_profile(base: Ontology, profile: dict[str, Any] | None) -> dict[str, Any]:
    """The form a profile is stored in: a preset name plus explicit lists.

    Full is stored without lists, so types added to the ontology later appear.
    Every other preset is stored resolved, so editing the preset in the
    ontology file never changes a project that already exists.
    """
    profile = dict(profile or {})
    preset = str(profile.get("preset") or ("custom" if "node_types" in profile else "full"))
    selection = base.resolve_profile(profile)
    if selection is None:
        return {"preset": "full"}
    nodes, edges = selection
    if not nodes:
        raise ValidationError("A project needs at least one element type")
    return {"preset": preset, "node_types": sorted(nodes), "edge_types": sorted(edges)}


class Workspace:
    def __init__(
        self,
        store: GraphStore,
        backend: StorageBackend,
        settings: Settings,
        base_ontology: Ontology | None = None,
    ) -> None:
        self.store = store
        self.backend = backend
        self.settings = settings
        #: The full ontology as loaded from file. The store works with a copy
        #: restricted to the project's profile (see effective_ontology).
        self.base_ontology = base_ontology or store.ontology
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

        store = GraphStore(document, effective_ontology(ontology, document), strict=settings.strict)
        telemetry.increment("workspace.opened")
        return cls(store, backend, settings, base_ontology=ontology)

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
            self.store = self._build_store(document)
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
            self.base_ontology = ontology
            self.store = self._build_store(document)
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
                self.base_ontology = ontology
                self.store = self._build_store(document)
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
            self.store = self._build_store(document)
            self.store.dirty = True
            telemetry.increment("workspace.imports")
            self._refresh_gauges()
            return {"nodes": self.store.node_count, "edges": self.store.edge_count, "merged": merge}

    def _build_store(self, document: GraphDocument) -> GraphStore:
        return GraphStore(document, effective_ontology(self.base_ontology, document), strict=self.settings.strict)

    # -- project profile ----------------------------------------------------
    def types_in_use(self) -> tuple[dict[str, int], dict[str, int]]:
        """How many elements and relations of each type the graph holds."""
        stats = self.store.stats()
        return dict(stats["nodes_by_type"]), dict(stats["edges_by_type"])

    def set_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        """Change which element types and relations this project uses.

        Anything already in use must stay: switching it off would leave elements
        the project can no longer show, edit or validate.
        """
        stored = normalise_profile(self.base_ontology, profile)
        with self._save_lock:
            nodes_in_use, edges_in_use = self.types_in_use()
            if stored.get("node_types") is not None:
                kept_nodes, kept_edges = set(stored["node_types"]), set(stored["edge_types"])
                # A relation is only really kept if both its ends survive.
                restricted = self.base_ontology.restricted(kept_nodes, kept_edges)
                blocked_nodes = {t: n for t, n in nodes_in_use.items() if t not in restricted.node_types}
                blocked_edges = {t: n for t, n in edges_in_use.items() if t not in restricted.edge_types}
                if blocked_nodes or blocked_edges:
                    described = [f"{t} ({n} in use)" for t, n in {**blocked_nodes, **blocked_edges}.items()]
                    raise ConflictError(
                        "These are in use in this project and cannot be switched off: "
                        + ", ".join(described) + ". Delete or retype those elements first.",
                        in_use={"node_types": blocked_nodes, "edge_types": blocked_edges},
                    )
            with self.store.reading():
                document = self.store.snapshot()
                document.project.profile = stored
                document.revision += 1
                self.store = self._build_store(document)
            self.store.dirty = True
            telemetry.increment("workspace.profile_changed")
            self._refresh_gauges()
            return stored

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
                "profile": self.store.project.profile.get("preset") or "full",
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
