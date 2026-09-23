"""Storage backend contract.

A backend does exactly two things: hand back a :class:`GraphDocument` and accept
a new one. Everything else -- validation, indexing, traceability -- happens above
this line, which is why adding a backend is a single small file.

Backends advertise ``capabilities`` so the UI can adapt: a read-only mirror hides
the save button, a versioned backend (GitLab) shows commit messages, a backend
without atomic writes warns about concurrent editors.
"""

from __future__ import annotations

import abc
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import StorageError
from ..model import GraphDocument, utc_now


@dataclass
class SaveResult:
    ok: bool = True
    revision: int = 0
    message: str = ""
    location: str = ""
    version_id: str = ""
    at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "revision": self.revision,
            "message": self.message,
            "location": self.location,
            "version_id": self.version_id,
            "at": self.at,
        }


class StorageBackend(abc.ABC):
    """Base class for every persistence adapter."""

    #: Scheme used in the storage URI, e.g. ``json`` for ``json:./project.json``.
    scheme: str = "abstract"
    #: Subset of {"read", "write", "history", "atomic", "remote"}.
    capabilities: set[str] = {"read"}

    def __init__(self, target: str, options: dict[str, Any] | None = None) -> None:
        self.target = target
        self.options = dict(options or {})

    @abc.abstractmethod
    def load(self) -> GraphDocument:
        """Read the whole graph. Must return an empty document if nothing exists yet."""

    @abc.abstractmethod
    def save(self, document: GraphDocument, *, message: str = "", actor: str = "setm") -> SaveResult:
        """Persist the whole graph."""

    def exists(self) -> bool:
        """Is there already a project at this target?

        ``setm init`` and ``setm demo`` use this rather than "does the graph have
        any elements": an initialised-but-empty project still has a name, a
        programme and a chief engineer, and silently overwriting those is a data
        loss the user never asked for. Backends over a file override this with a
        cheap path check; the rest fall back to reading.
        """
        document = self.load()
        return bool(document.nodes or document.edges or document.revision)

    def bind_ontology(self, ontology: Any) -> None:
        """Hand the backend the active ontology.

        Backends that serialise to a schema-aware format (RDF, spreadsheets) need
        it to lay out columns or mint class IRIs; the rest ignore it. The
        workspace calls this once, straight after construction.
        """
        self.ontology = ontology

    def health(self) -> dict[str, Any]:
        """Cheap reachability probe used by ``/api/health`` and the KPI page."""
        return {"backend": self.scheme, "target": self.target, "status": "unknown"}

    def describe(self) -> dict[str, Any]:
        return {
            "scheme": self.scheme,
            "target": self.target,
            "capabilities": sorted(self.capabilities),
            "writable": "write" in self.capabilities,
            "versioned": "history" in self.capabilities,
        }

    @property
    def writable(self) -> bool:
        return "write" in self.capabilities

    def require_writable(self) -> None:
        if not self.writable:
            raise StorageError(f"The {self.scheme} backend is read-only in this configuration")


class FileBackendMixin:
    """Atomic local-file writes with a rolling backup, shared by file backends."""

    target: str
    options: dict[str, Any]

    @property
    def path(self) -> Path:
        return Path(self.target).expanduser()

    def _write_atomic(self, text: str) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        keep = int(self.options.get("backups", 3))
        if path.exists() and keep:
            self._rotate_backups(path, keep)
        handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_name, path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    @staticmethod
    def _rotate_backups(path: Path, keep: int) -> None:
        for index in range(keep - 1, 0, -1):
            older = path.with_suffix(path.suffix + f".bak{index}")
            newer = path.with_suffix(path.suffix + f".bak{index + 1}")
            if older.exists():
                shutil.copy2(older, newer)
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak1"))

    def exists(self) -> bool:
        return self.path.exists() and self.path.stat().st_size > 0

    def health(self) -> dict[str, Any]:
        path = self.path
        exists = path.exists()
        return {
            "backend": getattr(self, "scheme", "file"),
            "target": str(path),
            "status": "ok" if (exists or path.parent.exists()) else "missing_directory",
            "exists": exists,
            "size_bytes": path.stat().st_size if exists else 0,
            "writable": os.access(path.parent, os.W_OK) if path.parent.exists() else False,
        }


def credentialed_opener() -> Any:
    """A urllib opener that refuses redirects.

    urllib copies request headers onto a redirected request, so a storage server
    that answers ``302 Location: http://elsewhere/`` would receive our
    ``Authorization`` / ``PRIVATE-TOKEN`` header there too.
    """
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
            import urllib.error

            raise urllib.error.HTTPError(
                req.full_url, code, f"refusing to follow a redirect to {newurl} with credentials", headers, fp
            )

    return urllib.request.build_opener(_NoRedirect)
