"""Projects: create, list and open them from the interface.

A project is one storage target -- by default a JSON file in the projects
directory (the ``projects_dir`` setting) -- holding the graph and, in its header,
the project's profile: which element types and relations it uses. Creating a
project from the interface only ever writes inside that directory, under a name
derived from the project name, so a browser can never choose a path.

Opening a project is ``Workspace.reconfigure`` against a new storage target,
which keeps its guarantee: unsaved work is never discarded silently.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import ConflictError, NotFoundError, SetmError, ValidationError
from .model import GraphDocument, ProjectInfo
from .storage.registry import open_storage
from .workspace import Workspace, normalise_profile

#: Storage formats a project can be created in from the interface.
FORMATS = {"json": ".json", "sqlite": ".db"}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").lower()).strip("-")[:60].strip("-")
    return slug or "project"


def projects_dir(workspace: Workspace) -> Path:
    return Path(workspace.settings.projects_dir or "./data/projects")


def _uri(fmt: str, path: Path) -> str:
    return f"{fmt}:{path.as_posix()}"


def _storage_path(uri: str) -> Path | None:
    """The local file behind a json:/sqlite: storage URI, if it is one."""
    scheme, _, rest = uri.partition(":")
    if scheme in FORMATS and rest:
        return Path(rest.split("?", 1)[0])
    return None


def _same_file(a: Path | None, b: Path | None) -> bool:
    if a is None or b is None:
        return False
    try:
        return a.resolve() == b.resolve()
    except OSError:  # pragma: no cover
        return False


def _inside(directory: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _summary(uri: str, document: GraphDocument, *, current: bool) -> dict[str, Any]:
    project = document.project
    profile = project.profile or {}
    return {
        "id": uri,
        "storage": uri,
        "name": project.name,
        "programme": project.programme,
        "phase": project.phase,
        "preset": profile.get("preset") or "full",
        "node_types": len(profile["node_types"]) if "node_types" in profile else None,
        "elements": len(document.nodes),
        "relations": len(document.edges),
        "current": current,
    }


#: Remembers local projects opened from elsewhere (the default data/project.json,
#: say), so switching away from one never loses the way back to it.
RECENT_FILE = ".recent.json"
MAX_RECENT = 20


def _recent(directory: Path) -> list[str]:
    try:
        data = json.loads((directory / RECENT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(u) for u in data if isinstance(u, str)] if isinstance(data, list) else []


def _remember(directory: Path, uri: str) -> None:
    if _storage_path(uri) is None:
        return  # only local files: listing a remote project would mean a network call
    recent = [uri] + [u for u in _recent(directory) if u != uri]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / RECENT_FILE).write_text(json.dumps(recent[:MAX_RECENT], indent=2) + "\n", encoding="utf-8")


def _load_summary(workspace: Workspace, uri: str, label: str) -> dict[str, Any]:
    try:
        backend = open_storage(uri)
        backend.bind_ontology(workspace.base_ontology)
        return _summary(uri, backend.load(), current=False)
    except SetmError as exc:
        return {"id": uri, "storage": uri, "name": label, "error": exc.message, "current": False}
    except Exception as exc:  # a stray or corrupt file must not break the list
        return {"id": uri, "storage": uri, "name": label, "error": str(exc), "current": False}


def list_projects(workspace: Workspace) -> list[dict[str, Any]]:
    """Every project the start page offers, most recently opened first.

    The open project (from memory, with unsaved edits), those in the projects
    folder, recently opened local projects, and the configured storage target
    if its file exists -- so the project `setm demo` writes is always there.
    """
    current_uri = workspace.settings.storage if workspace.is_open else ""
    current_path = _storage_path(current_uri) if current_uri else None
    directory = projects_dir(workspace)
    recent = _recent(directory)
    seen: list[Path] = [current_path] if current_path else []
    found: list[dict[str, Any]] = []
    if workspace.is_open:
        found.append({**_summary(current_uri, workspace.store.snapshot(), current=True), "recent": 0})

    candidates: list[tuple[str, Path]] = []
    for uri in recent:
        path = _storage_path(uri)
        if path is not None and path.is_file():
            candidates.append((uri, path))
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            fmt = next((f for f, ext in FORMATS.items() if path.suffix == ext), None)
            if fmt is not None and path.is_file() and not path.name.startswith("."):
                candidates.append((_uri(fmt, path), path))
    configured = _storage_path(workspace.settings.storage)
    if configured is not None and configured.is_file():
        candidates.append((workspace.settings.storage, configured))

    for uri, path in candidates:
        if any(_same_file(path, other) for other in seen):
            continue
        seen.append(path)
        summary = _load_summary(workspace, uri, path.stem)
        summary["recent"] = recent.index(uri) + 1 if uri in recent else None
        found.append(summary)
    return found


def _allowed_targets(workspace: Workspace) -> set[str]:
    return {p["storage"] for p in list_projects(workspace) if not p.get("error")}


def _project_document(
    workspace: Workspace,
    *,
    selection: dict[str, Any] | None,
    additions: dict[str, Any] | None,
    document: GraphDocument | None,
    example: str | None,
) -> tuple[GraphDocument, str]:
    """The starting document and its preset label: empty, imported or an example."""
    from .examples import EXAMPLES
    from .ontology import project as project_ontology

    master = workspace.master
    if example:
        if example not in EXAMPLES:
            raise ValidationError(f"Unknown example '{example}'. Try: {', '.join(EXAMPLES)}")
        document = EXAMPLES[example]["build"](master)
    document = document or GraphDocument()

    preset = "full"
    if document.ontology and not selection and not additions:
        source = document.ontology  # an imported project brings its own
        preset = (document.project.profile or {}).get("preset") or "custom"
    else:
        profile = normalise_profile(master, selection or {"preset": "full"})
        preset = profile["preset"]
        if "node_types" in profile:
            source = project_ontology.from_selection(master, set(profile["node_types"]), set(profile["edge_types"]))
        else:
            source = project_ontology.from_selection(master, None, None)
        for data in (additions or {}).get("element_types") or []:
            source, _ = project_ontology.upsert_element_type(source, data, master=master)
        for data in (additions or {}).get("relations") or []:
            source, _ = project_ontology.upsert_relation(source, data, master=master)
        if additions and (additions.get("element_types") or additions.get("relations")):
            preset = "custom"
    project_ontology.build(source)  # refuse a broken ontology before anything is written
    document.ontology = source
    return document, preset


def create_project(
    workspace: Workspace,
    *,
    name: str,
    programme: str = "",
    phase: str = "",
    description: str = "",
    chief_engineer: str = "",
    profile: dict[str, Any] | None = None,
    additions: dict[str, Any] | None = None,
    document: GraphDocument | None = None,
    example: str | None = None,
    fmt: str = "json",
    actor: str = "",
) -> dict[str, Any]:
    """Create a project in the projects folder. Does not open it.

    It starts empty, from a worked example, or from an imported document, and
    gets its own ontology: the master element types and relations chosen
    (``profile``, as the Light/Full/Custom picker sends it) plus any
    ``additions`` -- new element types and relations only this project has.
    """
    if fmt not in FORMATS:
        raise ValidationError(f"Unknown storage format '{fmt}'. Choose one of: {', '.join(FORMATS)}")
    document, preset = _project_document(
        workspace, selection=profile, additions=additions, document=document, example=example
    )
    name = (name or "").strip() or (document.project.name if (example or document.nodes) else "")
    if not name:
        raise ValidationError("A project needs a name")

    directory = projects_dir(workspace)
    directory.mkdir(parents=True, exist_ok=True)
    slug = slugify(name)
    candidate = directory / f"{slug}{FORMATS[fmt]}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{slug}-{counter}{FORMATS[fmt]}"
        counter += 1
    if not _inside(directory, candidate):  # pragma: no cover - slugify already prevents it
        raise ValidationError("Refusing to create a project outside the projects directory")

    master = workspace.master
    header = document.project
    document.project = ProjectInfo(
        id=candidate.stem,
        name=name[:200],
        programme=str(programme or header.programme)[:200],
        phase=str(phase or header.phase)[:60],
        description=str(description or header.description)[:4000],
        chief_engineer=str(chief_engineer or header.chief_engineer)[:200],
        profile={"preset": preset},
    )
    document.ontology_id = master.id
    document.ontology_version = master.version
    uri = _uri(fmt, candidate)
    backend = open_storage(uri)
    backend.bind_ontology(master)
    backend.save(document, message="create project", actor=actor or workspace.settings.actor)
    return _summary(uri, document, current=False)


def open_project(workspace: Workspace, storage: str, *, force: bool = False) -> dict[str, Any]:
    """Switch the workspace to a project the list offers.

    The browser picks from the list; it never supplies a path.
    """
    if workspace.is_open and storage == workspace.settings.storage:
        return {"opened": storage, "unchanged": True}
    if storage not in _allowed_targets(workspace):
        raise NotFoundError("No such project in the projects list")
    if workspace.is_open and workspace.store.dirty and not force:
        raise ConflictError(
            "There are unsaved changes in the open project. Save them first, or "
            "re-send with force to discard them.",
            unsaved=True,
        )
    previous = workspace.settings.storage
    was_open = workspace.is_open
    workspace.settings.storage = storage
    workspace.settings.sources["storage"] = "ui"
    try:
        result = workspace.reconfigure(force=True)
    except Exception:
        workspace.settings.storage = previous
        raise
    if was_open:
        _remember(projects_dir(workspace), previous)  # the way back, even to a CLI-opened project
    _remember(projects_dir(workspace), storage)
    return {"opened": storage, **result}
