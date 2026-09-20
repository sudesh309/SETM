"""Runtime settings, and the metadata the settings page is generated from.

Resolution order, lowest priority first: built-in defaults, a ``setm.toml`` in
the working directory, ``SETM_*`` environment variables, then command-line flags.
Every value remembers which layer set it, so the settings page can show *why* a
field holds what it holds -- and warn when a value edited in the UI will be
overridden by an environment variable on the next start.

As with the ontology, the settings form is generated from :data:`FIELD_SPECS`
rather than hand-written, so adding a setting here makes it appear in the
interface.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_FILE = "setm.toml"

#: Where a value came from. Ordered weakest to strongest.
SOURCES = ("default", "file", "environment", "argument", "ui")


@dataclass(frozen=True)
class FieldSpec:
    """Everything the settings page needs in order to render one field."""

    name: str
    label: str
    datatype: str  # string | integer | boolean | list | mapping | number_map
    group: str
    description: str = ""
    placeholder: str = ""
    #: Takes effect only when the server is restarted.
    restart_required: bool = False
    #: Never returned by the API; write-only.
    secret: bool = False
    #: Changing it re-opens the workspace, so it goes through its own endpoint.
    reopens_workspace: bool = False
    env_var: str = ""


FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "storage", "Storage target", "string", "Storage",
        "Where the graph is read from and written to. A local JSON file by default; "
        "switch to GitLab when each save should be a reviewable commit.",
        placeholder="json:./data/project.json",
        reopens_workspace=True, env_var="SETM_STORAGE",
    ),
    FieldSpec(
        "storage_options", "Backend options", "mapping", "Storage",
        "Extra options for the backend: branch, path, token, credentials. "
        "Credentials are better supplied through the environment than stored here.",
        placeholder="branch", reopens_workspace=True, secret=True,
    ),
    FieldSpec(
        "ontology", "Ontology", "string", "Ontology",
        "Path to an ontology file, or the name of one shipped in ontologies/.",
        placeholder="aerospace-se-core", reopens_workspace=True, env_var="SETM_ONTOLOGY",
    ),
    FieldSpec(
        "overlays", "Overlays", "list", "Ontology",
        "Extra ontology files layered on top, for per-programme tailoring. "
        "One path per line.",
        placeholder="./ontologies/my-programme-overlay.yaml", reopens_workspace=True,
    ),
    FieldSpec(
        "strict", "Strict validation", "boolean", "Ontology",
        "Reject any property the ontology does not declare. Recommended once the "
        "vocabulary has settled; leave off while importing legacy data.",
        env_var="SETM_STRICT",
    ),
    FieldSpec(
        "autosave", "Autosave", "boolean", "Behaviour",
        "Write to storage after every change. On a versioned backend that means a "
        "commit per change: turn it off to save once, deliberately.",
        env_var="SETM_AUTOSAVE",
    ),
    FieldSpec(
        "actor", "Default author", "string", "Behaviour",
        "Recorded as the author of a change when the client does not send one.",
        placeholder="your.name", env_var="SETM_ACTOR",
    ),
    FieldSpec(
        "kpi_targets", "KPI targets", "number_map", "KPI targets",
        "The target each KPI is measured against. Blank means the built-in default.",
    ),
    FieldSpec(
        "api_token", "API token", "string", "Access",
        "When set, every API request must carry it in the X-SETM-Token header. "
        "Leave empty for an unauthenticated server on 127.0.0.1.",
        secret=True, env_var="SETM_API_TOKEN",
    ),
    FieldSpec(
        "host", "Bind address", "string", "Access",
        "127.0.0.1 keeps the server on this machine. Binding wider exposes the "
        "graph to the network: set an API token if you do.",
        restart_required=True, env_var="SETM_HOST",
    ),
    FieldSpec(
        "port", "Port", "integer", "Access",
        "", restart_required=True, env_var="SETM_PORT",
    ),
)

FIELDS_BY_NAME = {spec.name: spec for spec in FIELD_SPECS}
SECRET_FIELDS = frozenset(spec.name for spec in FIELD_SPECS if spec.secret)
#: Returned in place of a secret, and ignored if it comes back unchanged.
SECRET_PLACEHOLDER = "********"


@dataclass
class Settings:
    #: Storage URI (see setm.storage.registry). A local JSON file is the
    #: default: it needs no credentials, no network and no prior setup, so the
    #: tool works the moment it is unpacked. Every other backend is one flag
    #: away -- ``--storage gitlab:my-group/my-project`` for a programme that
    #: wants each save to be a reviewable commit, ``sqlite:``, ``rdf:``,
    #: ``gsheet:`` and the rest likewise.
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
    #: Per-KPI target overrides; anything absent falls back to the built-in.
    kpi_targets: dict[str, float] = field(default_factory=dict)
    open_browser: bool = False

    #: Which layer last set each field, and the config file in play.
    sources: dict[str, str] = field(default_factory=dict)
    config_path: str = DEFAULT_CONFIG_FILE

    @classmethod
    def load(cls, config_path: str | os.PathLike[str] | None = None, **overrides: Any) -> "Settings":
        settings = cls()
        settings.config_path = str(config_path or DEFAULT_CONFIG_FILE)
        settings._apply_file(Path(settings.config_path))
        settings._apply_env()
        settings._apply(overrides, source="argument")
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
        self._apply(data.get("setm", data), source="file")

    def _apply_env(self) -> None:
        found = {
            spec.name: os.environ[spec.env_var]
            for spec in FIELD_SPECS
            if spec.env_var and spec.env_var in os.environ
        }
        self._apply(found, source="environment")

    def _apply(self, values: dict[str, Any], source: str = "argument") -> None:
        for key, value in (values or {}).items():
            if value is None or key in ("sources", "config_path") or not hasattr(self, key):
                continue
            setattr(self, key, self._coerce(key, value))
            self.sources[key] = source

    def _coerce(self, key: str, value: Any) -> Any:
        current = getattr(self, key)
        if isinstance(current, bool):
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "on")
        if isinstance(current, int) and not isinstance(current, bool):
            return int(value)
        if isinstance(current, list):
            if isinstance(value, str):
                return [v.strip() for v in value.replace("\n", ",").split(",") if v.strip()]
            return [str(v) for v in value]
        if isinstance(current, dict):
            if isinstance(value, str):
                pairs = (p for p in value.replace("\n", ",").split(",") if "=" in p)
                value = {k.strip(): v.strip() for k, v in (p.split("=", 1) for p in pairs)}
            if key == "kpi_targets":
                return {str(k): float(v) for k, v in dict(value).items() if v not in (None, "")}
            return dict(value)
        return value

    def source_of(self, name: str) -> str:
        return self.sources.get(name, "default")

    # -- output -------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Non-sensitive summary, used by /api/health and `setm info`."""
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
            "kpi_targets": dict(self.kpi_targets),
        }

    def redacted(self) -> dict[str, Any]:
        """Every field, with secrets replaced by a placeholder.

        A secret is never sent to the browser. The placeholder tells the page
        that a value exists, so it can show "set" rather than "empty", and the
        page sends it back unchanged when the user did not retype it.
        """
        out: dict[str, Any] = {}
        for spec in FIELD_SPECS:
            value = getattr(self, spec.name)
            if not spec.secret:
                out[spec.name] = value
            elif spec.name == "storage_options":
                # The keys are useful (branch, path); only values may be secret.
                out[spec.name] = {
                    key: (SECRET_PLACEHOLDER if _looks_secret(key) else val)
                    for key, val in value.items()
                }
            else:
                out[spec.name] = SECRET_PLACEHOLDER if value else ""
        return out

    def apply_update(self, values: dict[str, Any]) -> list[str]:
        """Apply a settings change from the UI. Returns the names that changed.

        A secret that comes back as the placeholder is left alone, so a page
        that never saw the real value cannot accidentally erase it.
        """
        changed: list[str] = []
        for key, value in (values or {}).items():
            spec = FIELDS_BY_NAME.get(key)
            if spec is None:
                continue
            if spec.secret and value == SECRET_PLACEHOLDER:
                continue
            if spec.name == "storage_options" and isinstance(value, dict):
                merged = dict(getattr(self, key))
                for option_key, option_value in value.items():
                    if option_value == SECRET_PLACEHOLDER:
                        continue  # a credential the page never saw
                    if option_value in (None, ""):
                        merged.pop(option_key, None)
                    else:
                        merged[option_key] = option_value
                value = merged
            coerced = self._coerce(key, value)
            if coerced != getattr(self, key):
                setattr(self, key, coerced)
                self.sources[key] = "ui"
                changed.append(key)
        return changed

    def shadowed_by_environment(self) -> list[str]:
        """Fields whose env var will win over anything saved to the file."""
        return [s.name for s in FIELD_SPECS if s.env_var and s.env_var in os.environ]

    # -- persistence --------------------------------------------------------
    def save_file(self, path: str | os.PathLike[str] | None = None, *, include_secrets: bool = False) -> Path:
        """Write the settings to ``setm.toml`` so they survive a restart.

        Credentials are left out unless explicitly asked for: a token written to
        a file outlives the session that needed it, and the environment is the
        better home for one.
        """
        target = Path(path or self.config_path)
        lines = [
            "# Written by SETM's settings page. Values here are overridden by",
            "# SETM_* environment variables and by command-line flags.",
            "",
            "[setm]",
        ]
        for spec in FIELD_SPECS:
            value = getattr(self, spec.name)
            if spec.secret and not include_secrets:
                if spec.name == "storage_options":
                    value = {k: v for k, v in value.items() if not _looks_secret(k)}
                else:
                    continue
            if value in ("", [], {}):
                continue
            lines.append(f"{spec.name} = {_toml_value(value)}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.config_path = str(target)
        return target

    def describe(self) -> dict[str, Any]:
        """Field metadata plus current values -- what the page renders from."""
        defaults = Settings()
        return {
            "config_path": str(Path(self.config_path).resolve()),
            "config_exists": Path(self.config_path).exists(),
            "values": self.redacted(),
            "defaults": {s.name: getattr(defaults, s.name) for s in FIELD_SPECS},
            "sources": {s.name: self.source_of(s.name) for s in FIELD_SPECS},
            "shadowed_by_environment": self.shadowed_by_environment(),
            "fields": [
                {
                    "name": s.name,
                    "label": s.label,
                    "type": s.datatype,
                    "group": s.group,
                    "description": s.description,
                    "placeholder": s.placeholder,
                    "restart_required": s.restart_required,
                    "secret": s.secret,
                    "reopens_workspace": s.reopens_workspace,
                    "env_var": s.env_var,
                }
                for s in FIELD_SPECS
            ],
        }


_SECRET_HINTS = ("token", "secret", "password", "credential", "key")


def _looks_secret(option_name: str) -> bool:
    lowered = option_name.lower()
    return any(hint in lowered for hint in _SECRET_HINTS)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        inner = ", ".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items())
        return "{" + inner + "}"
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_key(key: str) -> str:
    return key if key.replace("_", "").replace("-", "").isalnum() else f'"{key}"'


def settings_field_names() -> list[str]:
    return [f.name for f in fields(Settings) if f.name not in ("sources", "config_path")]
