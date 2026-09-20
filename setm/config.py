"""Runtime settings.

Resolution order, lowest priority first: built-in defaults, a ``setm.toml`` in
the working directory, ``SETM_*`` environment variables, then command-line flags.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_FILE = "setm.toml"


@dataclass
class Settings:
    #: Storage URI, e.g. ``json:./data/project.json`` (see setm.storage.registry).
    storage: str = "json:./data/project.json"
    #: Ontology file path or the name of a built-in ontology.
    ontology: str = "aerospace-se-core"
    #: Extra ontology files layered on top of the main one.
    overlays: list[str] = field(default_factory=list)
    #: Reject properties that the ontology does not declare.
    strict: bool = False
    #: Write to storage after every mutation. Off = explicit save only.
    autosave: bool = True
    host: str = "127.0.0.1"
    port: int = 8765
    #: Extra options handed to the storage backend (token=..., branch=..., ...).
    storage_options: dict[str, Any] = field(default_factory=dict)
    #: Shown as the author of changes when no user is supplied by the client.
    actor: str = "setm-user"
    #: Optional shared secret; when set, the API requires ``X-SETM-Token``.
    api_token: str = ""
    open_browser: bool = False

    @classmethod
    def load(cls, config_path: str | os.PathLike[str] | None = None, **overrides: Any) -> "Settings":
        settings = cls()
        settings._apply_file(Path(config_path) if config_path else Path(DEFAULT_CONFIG_FILE))
        settings._apply_env()
        settings._apply(overrides)
        return settings

    # -- layers -------------------------------------------------------------
    def _apply_file(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            import tomllib
        except ImportError:  # pragma: no cover - Python < 3.11
            return
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        self._apply(data.get("setm", data))

    def _apply_env(self) -> None:
        mapping = {
            "SETM_STORAGE": "storage",
            "SETM_ONTOLOGY": "ontology",
            "SETM_HOST": "host",
            "SETM_PORT": "port",
            "SETM_ACTOR": "actor",
            "SETM_API_TOKEN": "api_token",
            "SETM_STRICT": "strict",
            "SETM_AUTOSAVE": "autosave",
        }
        found = {field_name: os.environ[env] for env, field_name in mapping.items() if env in os.environ}
        self._apply(found)

    def _apply(self, values: dict[str, Any]) -> None:
        for key, value in (values or {}).items():
            if value is None or not hasattr(self, key):
                continue
            current = getattr(self, key)
            if isinstance(current, bool):
                value = str(value).strip().lower() in ("1", "true", "yes", "on") if not isinstance(value, bool) else value
            elif isinstance(current, int) and not isinstance(current, bool):
                value = int(value)
            elif isinstance(current, list) and isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            elif isinstance(current, dict) and isinstance(value, str):
                value = dict(pair.split("=", 1) for pair in value.split(",") if "=" in pair)
            setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "storage": self.storage,
            "ontology": self.ontology,
            "overlays": list(self.overlays),
            "strict": self.strict,
            "autosave": self.autosave,
            "host": self.host,
            "port": self.port,
            "actor": self.actor,
            "auth_required": bool(self.api_token),
        }
