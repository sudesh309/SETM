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
    """The open project, those in the projects directory, and recently opened ones."""
    current_uri = workspace.settings.storage
    current_path = _storage_path(current_uri)
    directory = projects_dir(workspace)
    seen: list[Path] = [current_path] if current_path else []
    found: list[dict[str, Any]] = [_summary(current_uri, workspace.store.snapshot(), current=True)]

    candidates: list[tuple[str, Path]] = []
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            fmt = next((f for f, ext in FORMATS.items() if path.suffix == ext), None)
            if fmt is not None and path.is_file() and not path.name.startswith("."):
                candidates.append((_uri(fmt, path), path))
    for uri in _recent(directory):
        path = _storage_path(uri)
        if path is not None and path.is_file():
            candidates.append((uri, path))

    for uri, path in candidates:
        if any(_same_file(path, other) for other in seen):
            continue  # the open project is listed from memory, with unsaved edits
        seen.append(path)
        found.append(_load_summary(workspace, uri, path.stem))
    return found


def _allowed_targets(workspace: Workspace) -> set[str]:
    return {p["storage"] for p in list_projects(workspace) if not p.get("error")}


def create_project(
    workspace: Workspace,
    *,
    name: str,
    programme: str = "",
    phase: str = "",
    description: str = "",
    chief_engineer: str = "",
    profile: dict[str, Any] | None = None,
    fmt: str = "json",
    actor: str = "",
) -> dict[str, Any]:
    """Create an empty project in the projects directory. Does not open it."""
    name = (name or "").strip()
    if not name:
        raise ValidationError("A project needs a name")
    if fmt not in FORMATS:
        raise ValidationError(f"Unknown storage format '{fmt}'. Choose one of: {', '.join(FORMATS)}")
    stored_profile = normalise_profile(workspace.base_ontology, profile)

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

    ontology = workspace.base_ontology
    document = GraphDocument(
        project=ProjectInfo(
            id=candidate.stem,
            name=name[:200],
            programme=str(programme)[:200],
            phase=str(phase)[:60],
            description=str(description)[:4000],
            chief_engineer=str(chief_engineer)[:200],
            profile=stored_profile,
        ),
        ontology_id=ontology.id,
        ontology_version=ontology.version,
    )
    uri = _uri(fmt, candidate)
    backend = open_storage(uri)
    backend.bind_ontology(ontology)
    backend.save(document, message="create project", actor=actor or workspace.settings.actor)
    return _summary(uri, document, current=False)


def open_project(workspace: Workspace, storage: str, *, force: bool = False, remember: bool = True) -> dict[str, Any]:
    """Switch the workspace to another project.

    Only a project the list offers can be opened this way -- the browser picks
    from the list, it never supplies a path.
    """
    if storage == workspace.settings.storage:
        return {"opened": storage, "unchanged": True}
    if storage not in _allowed_targets(workspace):
        raise NotFoundError("No such project in the projects directory")
    if workspace.store.dirty and not force:
        raise ConflictError(
            "There are unsaved changes in the open project. Save them first, or "
            "re-send with force to discard them.",
            unsaved=True,
        )
    previous = workspace.settings.storage
    _remember(projects_dir(workspace), previous)
    workspace.settings.storage = storage
    workspace.settings.sources["storage"] = "ui"
    try:
        result = workspace.reconfigure(force=True)
    except Exception:
        workspace.settings.storage = previous
        raise
    saved_to = ""
    if remember:
        saved_to = str(workspace.settings.save_file().resolve())
    return {"opened": storage, "saved_to": saved_to, **result}
