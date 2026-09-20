"""Exception hierarchy for SETM.

Every error carries a machine readable ``code`` so the HTTP layer can map it to a
status without a chain of ``isinstance`` checks.
"""

from __future__ import annotations

from typing import Any


class SetmError(Exception):
    """Base class for everything SETM raises on purpose."""

    code = "setm_error"
    status = 500

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class OntologyError(SetmError):
    code = "ontology_error"
    status = 400


class ValidationError(SetmError):
    """A node/edge does not conform to the ontology."""

    code = "validation_error"
    status = 422

    def __init__(self, message: str, issues: list[dict[str, Any]] | None = None, **details: Any):
        super().__init__(message, **details)
        self.issues = issues or []

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["issues"] = self.issues
        return payload


class NotFoundError(SetmError):
    code = "not_found"
    status = 404


class ConflictError(SetmError):
    """Optimistic concurrency failure or duplicate identifier."""

    code = "conflict"
    status = 409


class StorageError(SetmError):
    code = "storage_error"
    status = 502


class ConfigError(SetmError):
    code = "config_error"
    status = 400


class DependencyMissing(SetmError):
    """An optional backend was selected but its third-party package is absent."""

    code = "dependency_missing"
    status = 503

    def __init__(self, package: str, extra: str, purpose: str) -> None:
        super().__init__(
            f"{purpose} needs the '{package}' package. Install it with: pip install 'setm[{extra}]'",
            package=package,
            extra=extra,
        )
