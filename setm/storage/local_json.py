"""JSON file backend -- the default, and the format every other backend mirrors."""

from __future__ import annotations

import json
from typing import Any

from ..errors import StorageError
from ..model import GraphDocument
from .base import FileBackendMixin, SaveResult, StorageBackend
from .registry import register


class JsonBackend(FileBackendMixin, StorageBackend):
    scheme = "json"
    capabilities = {"read", "write", "atomic"}

    def load(self) -> GraphDocument:
        path = self.path
        if not path.exists():
            return GraphDocument()
        try:
            raw = json.loads(path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise StorageError(f"{path} is not valid JSON: {exc}") from None
        return GraphDocument.from_dict(raw)

    def save(self, document: GraphDocument, *, message: str = "", actor: str = "setm") -> SaveResult:
        self.require_writable()
        indent = None if str(self.options.get("compact", "")).lower() in ("1", "true", "yes") else 2
        self._write_atomic(json.dumps(document.to_dict(), indent=indent, ensure_ascii=False) + "\n")
        return SaveResult(
            revision=document.revision,
            message=message or "saved",
            location=str(self.path),
        )

    def describe(self) -> dict[str, Any]:
        info = super().describe()
        info["format"] = "json"
        return info


register("json", JsonBackend)
register("file", JsonBackend)
