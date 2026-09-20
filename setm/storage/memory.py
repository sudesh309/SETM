"""Volatile backend for tests, demos and `--dry-run` sessions."""

from __future__ import annotations

import copy
from typing import Any

from ..model import GraphDocument
from .base import SaveResult, StorageBackend
from .registry import register

_SHARED: dict[str, dict[str, Any]] = {}


class MemoryBackend(StorageBackend):
    scheme = "memory"
    capabilities = {"read", "write", "atomic"}

    def __init__(self, target: str = "default", options: dict[str, Any] | None = None) -> None:
        super().__init__(target or "default", options)
        _SHARED.setdefault(self.target, GraphDocument().to_dict())

    def load(self) -> GraphDocument:
        return GraphDocument.from_dict(copy.deepcopy(_SHARED[self.target]))

    def save(self, document: GraphDocument, *, message: str = "", actor: str = "setm") -> SaveResult:
        _SHARED[self.target] = copy.deepcopy(document.to_dict())
        return SaveResult(revision=document.revision, message=message or "saved", location=f"memory:{self.target}")

    def health(self) -> dict[str, Any]:
        return {"backend": self.scheme, "target": self.target, "status": "ok", "persistent": False}


def reset(target: str = "default") -> None:
    _SHARED[target] = GraphDocument().to_dict()


register("memory", MemoryBackend)
