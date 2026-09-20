"""Pluggable persistence backends."""

from .base import SaveResult, StorageBackend
from .registry import available_schemes, load_builtin_backends, open_storage, parse_uri, register

__all__ = [
    "StorageBackend",
    "SaveResult",
    "open_storage",
    "register",
    "parse_uri",
    "available_schemes",
    "load_builtin_backends",
]
