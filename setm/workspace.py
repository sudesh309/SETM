"""The object that ties ontology, storage and graph together.

One :class:`Workspace` == one open project. The API layer, the CLI and the tests
all drive this same object, so behaviour cannot drift between them.
"""

from __future__ import annotations

import itertools
import logging
import threading
from typing import Any

from .config import Settings
from .errors import ConflictError, OntologyError, StorageError, ValidationError
from .graph.store import GraphStore
from .kpi.telemetry import telemetry
from .model import GraphDocument
from .ontology import project as project_ontology
from .ontology.compare import compare as compare_ontologies, plan_merge, summary as compare_summary
from .ontology.loader import build_ontology, ontology_to_source
from .ontology.master import load_master, master_path, master_saved, save_master
from .ontology.schema import Ontology
from .ontology.validate import validate_document
from .storage.base import SaveResult, StorageBackend
from .storage.registry import load_builtin_backends, open_storage

logger = logging.getLogger("setm.workspace")
_blank_ids = itertools.count(1)


def project_ontology_for(master: Ontology, document: GraphDocument) -> Ontology:
    """The ontology a project works with: its own copy, from its document.

    A document written before projects had their own ontology gets one now:
    the master, restricted to its profile if it has one. Either way, any type
    the data uses that the copy lacks is brought in from the master, so data
    is never hidden by its own vocabulary. The result is kept on the document,
    so the next save stores it.
    """
    source = document.ontology
    if not source:
        selection = master.resolve_profile(document.project.profile, strict=False)
        nodes, edges = selection if selection else (None, None)
        source = project_ontology.from_selection(master, nodes, edges)
    source = project_ontology.with_types_in_use(
        source, master, {n.type for n in document.nodes}, {e.type for e in document.edges}
    )
    try:
        ontology = build_ontology(source)
    except OntologyError as exc:
        # A damaged copy must not lock the project out: fall back to the master.
        logger.warning("Project ontology is invalid (%s); using a copy of the master", exc)
        source = project_ontology.from_selection(master, None, None)
        ontology = build_ontology(source)
    document.ontology = source
    ontology.source_path = "(project)"
    return ontology


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
        master: Ontology | None = None,
        *,
        is_open: bool = True,
    ) -> None:
        self.store = store
        self.backend = backend
        self.settings = settings
        #: The master ontology (see setm.ontology.master). The store works with
        #: the project's own copy (see project_ontology_for).
        self.master = master or store.ontology
        #: False on the start page, before any project has been opened.
        self.is_open = is_open
        self._save_lock = threading.Lock()
        self.last_save: SaveResult | None = None
        self._refresh_gauges()

    # -- construction -------------------------------------------------------
    @classmethod
    def open(cls, settings: Settings | None = None, **overrides: Any) -> "Workspace":
        settings = settings or Settings.load(**overrides)
        load_builtin_backends()

        with telemetry.track("ontology.load"):
            master = load_master(settings)

        backend = open_storage(settings.storage, **settings.storage_options)
        backend.bind_ontology(master)

        with telemetry.track("storage.load", backend=backend.scheme):
            document = backend.load()

        if not document.nodes and not document.edges:
            document.ontology_id = master.id
            document.ontology_version = master.version

        store = GraphStore(document, project_ontology_for(master, document), strict=settings.strict)
        telemetry.increment("workspace.opened")
        return cls(store, backend, settings, master)

    @classmethod
    def blank(cls, settings: Settings | None = None, **overrides: Any) -> "Workspace":
        """A workspace with no project open -- what the start page shows.

        Everything that needs a project answers "no project is open" until one
        is created, opened or loaded (see setm.projects).
        """
        settings = settings or Settings.load(**overrides)
        load_builtin_backends()
        with telemetry.track("ontology.load"):
            master = load_master(settings)
        backend = open_storage(f"memory:__no-project-{next(_blank_ids)}")
        store = GraphStore(GraphDocument(ontology_id=master.id, ontology_version=master.version), master)
        return cls(store, backend, settings, master, is_open=False)

    # -- persistence --------------------------------------------------------
    @property
    def ontology(self) -> Ontology:
        """The ontology the open project works with: its own copy."""
        return self.store.ontology

    @property
    def base_ontology(self) -> Ontology:
        """The master; kept under its earlier name for callers that use it."""
        return self.master

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
                ontology = load_master(self.settings)

            backend = open_storage(self.settings.storage, **self.settings.storage_options)
            backend.bind_ontology(ontology)
            with telemetry.track("storage.load", backend=backend.scheme):
                document = backend.load()

            if not document.nodes and not document.edges:
                document.ontology_id = ontology.id
                document.ontology_version = ontology.version

            self.backend = backend
            self.master = ontology
            self.store = self._build_store(document)
            self.is_open = True
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
        """Re-read the master from its file.

        The open project keeps its own copy: a master change reaches it only by
        comparing and merging (see merge_ontology).
        """
        with self._save_lock:
            self.master = load_master(self.settings)
            self.backend.bind_ontology(self.master)
            telemetry.increment("ontology.reloads")
            return self.master

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
        return GraphStore(document, project_ontology_for(self.master, document), strict=self.settings.strict)

    def require_open(self) -> None:
        if not self.is_open:
            raise ConflictError("No project is open. Create, open or load one first.", no_project=True)

    # -- the project's own ontology -----------------------------------------
    def types_in_use(self) -> tuple[dict[str, int], dict[str, int]]:
        """How many elements and relations of each type the graph holds."""
        stats = self.store.stats()
        return dict(stats["nodes_by_type"]), dict(stats["edges_by_type"])

    def properties_in_use(self) -> dict[str, set[str]]:
        """Per element type, the properties its elements actually carry."""
        used: dict[str, set[str]] = {}
        for node in self.store.nodes():
            used.setdefault(node.type, set()).update(k for k, v in node.properties.items() if v not in (None, "", []))
        return used

    @property
    def project_source(self) -> dict[str, Any]:
        return self.store.ontology_source

    def change_project_ontology(self, source: dict[str, Any]) -> Ontology:
        """Replace the project's ontology, if the graph stays as valid as it was.

        The change is built, then the whole graph is re-validated against it.
        Anything that would newly fail -- an element whose type was removed, a
        value outside a changed list of choices -- refuses the change and says
        which elements are affected, so nothing is ever stranded.
        """
        self.require_open()
        ontology = project_ontology.build(source)
        with self._save_lock:
            with self.store.reading():
                document = self.store.snapshot()
                before = {(e["element"], e["message"]) for e in validate_document(self.ontology, document)["errors"]}
                report = validate_document(ontology, document)
                broken = [e for e in report["errors"] if (e["element"], e["message"]) not in before]
                if broken:
                    raise ConflictError(
                        f"This change would leave {len(broken)} element(s) of this project invalid "
                        f"-- for example {broken[0]['element']}: {broken[0]['message']}. "
                        "Change or delete those elements first.",
                        issues=broken[:20],
                    )
                document.ontology = source
                document.revision += 1
                ontology.source_path = "(project)"
                self.store = GraphStore(document, ontology, strict=self.settings.strict)
            self.store.dirty = True
            telemetry.increment("ontology.project_changed")
            self._refresh_gauges()
            return ontology

    def _canonical_project_source(self) -> dict[str, Any]:
        """The project source in the same normal form as the master's.

        Hand-added types are written tersely; passing both sides through the
        loader means a comparison sees meaning, not formatting.
        """
        canonical = ontology_to_source(self.ontology)
        canonical["ontology"] = {**(self.project_source.get("ontology") or {}), **canonical["ontology"]}
        canonical.pop("profiles", None)
        return canonical

    def compare_ontologies(self) -> dict[str, Any]:
        items = compare_ontologies(self._canonical_project_source(), ontology_to_source(self.master))
        return {"items": items, "summary": compare_summary(items)}

    def merge_ontology(self, direction: str, items: list[dict[str, Any]], *, dry_run: bool = False) -> dict[str, Any]:
        """Copy element types and relations between the project and the master."""
        self.require_open()
        plan = plan_merge(
            direction,
            items,
            self._canonical_project_source(),
            ontology_to_source(self.master),
            in_use_properties=self.properties_in_use(),
        )
        # Build it either way: a preview that could not be applied is no preview.
        build_ontology(plan["source"])
        result = {k: v for k, v in plan.items() if k != "source"}
        if dry_run or not (plan["copied"] or plan["dependencies"]):
            return {**result, "applied": False}
        if direction == "to_master":
            with self._save_lock:
                self.master = save_master(self.settings, plan["source"])
                self.backend.bind_ontology(self.master)
            telemetry.increment("ontology.master_merged")
        else:
            self.change_project_ontology(plan["source"])
        return {**result, "applied": True, "master_version": self.master.version}

    def describe_ontologies(self) -> dict[str, Any]:
        project = self.ontology
        return {
            "master": {
                "id": self.master.id,
                "title": self.master.title,
                "version": self.master.version,
                "path": str(master_path(self.settings)),
                "saved": master_saved(self.settings),
                "template": self.settings.ontology,
                "element_types": len(self.master.concrete_node_types()),
                "relations": len(self.master.edge_types),
            },
            "project": {
                "open": self.is_open,
                "title": project.title,
                "derived_from": (self.project_source.get("ontology") or {}).get("derived_from"),
                "element_types": len(project.concrete_node_types()),
                "relations": len(project.edge_types),
            },
        }

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
            "project_open": self.is_open,
            "graph": self.store.stats(),
            "storage": {**self.backend.describe(), "health": backend_health},
            "master": {"id": self.master.id, "version": self.master.version, "saved": master_saved(self.settings)},
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
