"""Backend registry and storage-URI parsing.

A storage target is written as ``scheme:target?opt=value``:

==============================================  ==============================
``json:./data/project.json``                    local JSON file
``sqlite:./data/project.db``                    local SQLite database
``rdf:./data/project.ttl``                      Turtle / OWL file
``gsheet:<spreadsheet-id>``                     Google Sheets workbook
``gdrive:<file-id>`` / ``gdrive:folder/<id>``   JSON file on Google Drive
``gitlab:group/project?path=se/graph.json``     versioned file in a GitLab repo
``http://host/api/graph``                       any HTTP service speaking JSON
``memory:``                                     throwaway, for tests and demos
==============================================  ==============================

A bare path is accepted too and resolved from its extension, so
``setm serve ./project.ttl`` does the expected thing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlsplit

from ..errors import ConfigError
from .base import StorageBackend

_REGISTRY: dict[str, Callable[..., StorageBackend]] = {}
_EXTENSIONS = {
    ".json": "json",
    ".ttl": "rdf",
    ".turtle": "rdf",
    ".owl": "rdf",
    ".rdf": "rdf",
    ".db": "sqlite",
    ".sqlite": "sqlite",
    ".sqlite3": "sqlite",
}


def register(scheme: str, factory: Callable[..., StorageBackend]) -> None:
    _REGISTRY[scheme] = factory


def available_schemes() -> list[str]:
    return sorted(_REGISTRY)


def parse_uri(uri: str) -> tuple[str, str, dict[str, Any]]:
    """Split a storage URI into ``(scheme, target, options)``."""
    uri = (uri or "").strip()
    if not uri:
        raise ConfigError("Empty storage target")

    if uri.startswith(("http://", "https://")):
        split = urlsplit(uri)
        return "http", uri.split("?")[0], dict(parse_qsl(split.query))

    scheme, separator, remainder = uri.partition(":")
    if not separator or (len(scheme) == 1 and remainder[:1] in ("\\", "/")):  # Windows drive letter
        suffix = Path(uri).suffix.lower()
        if suffix not in _EXTENSIONS:
            raise ConfigError(
                f"Cannot infer a backend from '{uri}'. Use an explicit scheme "
                f"({', '.join(available_schemes())}) or a known extension "
                f"({', '.join(sorted(_EXTENSIONS))})."
            )
        return _EXTENSIONS[suffix], uri, {}

    target, _, query = remainder.partition("?")
    if target.startswith("//"):
        target = target[2:]
    return scheme.lower(), target, dict(parse_qsl(query))


def open_storage(uri: str, **overrides: Any) -> StorageBackend:
    """Create the backend named by ``uri``. Extra kwargs override URI options."""
    scheme, target, options = parse_uri(uri)
    options.update({k: v for k, v in overrides.items() if v is not None})
    factory = _REGISTRY.get(scheme)
    if factory is None:
        raise ConfigError(
            f"Unknown storage backend '{scheme}'. Available: {', '.join(available_schemes())}"
        )
    return factory(target, options)


def load_builtin_backends() -> None:
    """Import the shipped backends. Optional dependencies fail lazily, at use."""
    from . import gdrive, gitlab, http_api, local_json, memory, rdf_store, sqlite_store  # noqa: F401


def describe_all() -> list[dict[str, Any]]:
    """Metadata for the UI's backend picker."""
    out: list[dict[str, Any]] = []
    for scheme in available_schemes():
        out.append({"scheme": scheme, "example": _EXAMPLES.get(scheme, f"{scheme}:...")})
    return out


_EXAMPLES: dict[str, str] = {
    "json": "json:./data/project.json",
    "sqlite": "sqlite:./data/project.db",
    "rdf": "rdf:./data/project.ttl",
    "gsheet": "gsheet:1AbC...xyz",
    "gdrive": "gdrive:1AbC...xyz",
    "gitlab": "gitlab:my-group/my-project?path=se/graph.json&branch=main",
    "http": "https://host/api/graph",
    "memory": "memory:",
}


def extensions() -> Iterable[str]:
    return sorted(_EXTENSIONS)
