"""GitLab repository backend.

The graph lives as a file in a Git repository, so every save is a commit: you get
review, blame, branches and rollback from infrastructure the organisation already
runs and already trusts for configuration management. For an aerospace programme
that is often the difference between a tool being usable and being unapprovable.

Target form::

    gitlab:my-group/my-project?path=systems/graph.json&branch=main

This is the backend to choose for a real programme: the graph lands under the
configuration management, access control and audit trail the organisation
already runs and already trusts.

The project may be left out entirely (``gitlab:``) and SETM will resolve it from
``SETM_GITLAB_PROJECT`` or, failing that, from the ``origin`` remote of the
repository you are standing in -- so ``setm serve gitlab:`` inside a checkout
usually just works.

Options: ``host`` (default ``https://gitlab.com``, or the host of the detected
remote), ``token`` (or ``SETM_GITLAB_TOKEN`` / ``GITLAB_TOKEN``), ``path``,
``branch``, ``format`` (``json`` or ``ttl``), ``author_email``, and ``force``
to overwrite a file that changed underneath you.

Concurrency: an update sends the commit id the graph was read at, so GitLab
rejects a write that would clobber someone else's commit. SETM turns that into a
:class:`~setm.errors.ConflictError` telling the user to reload.
"""

from __future__ import annotations

import base64
import configparser
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..errors import ConfigError, ConflictError, StorageError
from ..model import GraphDocument
from ..ontology.loader import load_ontology
from .base import SaveResult, StorageBackend
from .registry import register


def detect_gitlab_remote(start: Path | None = None) -> tuple[str, str] | None:
    """``(host, group/project)`` from the surrounding checkout's origin remote.

    Read straight from ``.git/config`` rather than shelling out to git, so this
    works wherever Python does and cannot be affected by the user's git aliases.
    Returns None when there is no repository, no origin, or origin is not GitLab.
    """
    directory = (start or Path.cwd()).resolve()
    for candidate in [directory, *directory.parents]:
        config_path = candidate / ".git" / "config"
        if not config_path.is_file():
            continue
        parser = configparser.ConfigParser()
        try:
            parser.read(config_path, encoding="utf-8")
            url = parser.get('remote "origin"', "url", fallback="").strip()
        except (configparser.Error, OSError):
            return None
        return parse_git_remote(url)
    return None


def parse_git_remote(url: str) -> tuple[str, str] | None:
    """Split an SSH or HTTPS git URL into ``(host, group/project)``."""
    if not url:
        return None
    url = url.removesuffix(".git")
    if url.startswith(("http://", "https://")):
        split = urllib.parse.urlsplit(url)
        host = f"{split.scheme}://{split.netloc.rsplit('@', 1)[-1]}"
        project = split.path.strip("/")
    elif "@" in url and ":" in url:  # git@gitlab.example.com:group/project
        _, _, remainder = url.partition("@")
        hostname, _, project = remainder.partition(":")
        host = f"https://{hostname}"
        project = project.strip("/")
    else:
        return None
    if not project or "/" not in project:
        return None
    return host, project


class GitLabBackend(StorageBackend):
    scheme = "gitlab"
    capabilities = {"read", "write", "remote", "history"}

    def __init__(self, target: str, options: dict[str, Any] | None = None) -> None:
        super().__init__(target, options)
        detected = None
        self.project = (target or "").strip("/") or str(os.environ.get("SETM_GITLAB_PROJECT") or "").strip("/")
        if not self.project:
            detected = detect_gitlab_remote()
            if detected:
                self.project = detected[1]
        self.host = str(
            self.options.get("host")
            or os.environ.get("SETM_GITLAB_HOST")
            or (detected[0] if detected else "")
            or "https://gitlab.com"
        ).rstrip("/")
        # Report the resolved project, not the blank target the user may have passed.
        self.target = self.project
        self.file_path = str(self.options.get("path") or "setm/graph.json")
        self.branch = str(self.options.get("branch") or "main")
        self.token = str(
            self.options.get("token") or os.environ.get("SETM_GITLAB_TOKEN") or os.environ.get("GITLAB_TOKEN") or ""
        )
        self.format = str(self.options.get("format") or ("ttl" if self.file_path.endswith(".ttl") else "json"))
        self.timeout = float(self.options.get("timeout", 30))
        self.ontology: Any = None
        self._loaded_commit_id = ""
        if not self.project:
            raise ConfigError(
                "No GitLab project given. Name one of:\n"
                "  setm serve gitlab:my-group/my-project?path=systems/graph.json\n"
                "  export SETM_GITLAB_PROJECT=my-group/my-project\n"
                "  or run `setm serve gitlab:` inside a checkout whose 'origin' "
                "remote points at GitLab."
            )

    def _ontology(self) -> Any:
        if self.ontology is None:
            self.ontology = load_ontology(self.options.get("ontology", "aerospace-se-core"))
        return self.ontology

    @property
    def _base(self) -> str:
        return f"{self.host}/api/v4/projects/{urllib.parse.quote(self.project, safe='')}"

    def _request(self, method: str, url: str, body: Any = None) -> Any:
        if not self.token:
            raise ConfigError(
                "No GitLab token. Set SETM_GITLAB_TOKEN or pass --storage-option token=<personal access token> "
                "(scope: api, or read_api for read-only use)."
            )
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"PRIVATE-TOKEN": self.token}
        if data:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload) if payload.strip() else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise StorageError(f"GitLab {method} failed with HTTP {exc.code}: {detail}", status_code=exc.code) from None
        except urllib.error.URLError as exc:
            raise StorageError(f"Could not reach GitLab at {self.host}: {exc.reason}") from None

    def _file_url(self) -> str:
        return f"{self._base}/repository/files/{urllib.parse.quote(self.file_path, safe='')}"

    def load(self) -> GraphDocument:
        response = self._request("GET", f"{self._file_url()}?ref={urllib.parse.quote(self.branch)}")
        if not response:
            self._loaded_commit_id = ""
            return GraphDocument()
        # Remembered so the next save can prove nobody else wrote in between.
        self._loaded_commit_id = str(response.get("last_commit_id") or "")
        text = base64.b64decode(response.get("content", "")).decode("utf-8")
        if not text.strip():
            return GraphDocument()
        if self.format == "ttl":
            from ..serialize.rdfmap import turtle_to_document

            return turtle_to_document(text, self._ontology())
        return GraphDocument.from_dict(json.loads(text))

    def save(self, document: GraphDocument, *, message: str = "", actor: str = "setm") -> SaveResult:
        self.require_writable()
        if self.format == "ttl":
            from ..serialize.rdfmap import document_to_turtle

            payload = document_to_turtle(document, self._ontology())
        else:
            payload = json.dumps(document.to_dict(), indent=2, ensure_ascii=False) + "\n"

        commit_message = message or f"SETM: update {document.project.name} (revision {document.revision})"
        body: dict[str, Any] = {
            "branch": self.branch,
            "content": payload,
            "commit_message": commit_message,
            "encoding": "text",
            "author_name": actor,
        }
        email = self.options.get("author_email")
        if email:
            body["author_email"] = str(email)

        current = self._request("GET", f"{self._file_url()}?ref={urllib.parse.quote(self.branch)}")
        force = str(self.options.get("force", "")).lower() in ("1", "true", "yes")
        if current is not None and self._loaded_commit_id and not force:
            # GitLab rejects the update if the file moved on since we read it,
            # which is what stops two engineers silently overwriting each other.
            body["last_commit_id"] = self._loaded_commit_id

        try:
            result = self._request("PUT" if current is not None else "POST", self._file_url(), body)
        except StorageError as exc:
            if exc.details.get("status_code") == 400 and "last_commit_id" in exc.message:
                raise ConflictError(
                    f"{self.file_path} changed in GitLab since you loaded it. Reload, then save again "
                    "(or pass --storage-option force=true to overwrite their commit).",
                    path=self.file_path,
                    branch=self.branch,
                ) from None
            raise
        if result is None:
            raise StorageError(f"GitLab rejected the write to {self.file_path} on branch {self.branch}")

        commit = self._request("GET", f"{self._base}/repository/commits/{urllib.parse.quote(self.branch)}") or {}
        self._loaded_commit_id = str(commit.get("id") or "")
        return SaveResult(
            revision=document.revision,
            message=commit_message,
            location=f"{self.host}/{self.project}/-/blob/{self.branch}/{self.file_path}",
            version_id=str(commit.get("short_id") or ""),
        )

    def exists(self) -> bool:
        """One metadata request, rather than downloading and parsing the graph."""
        return self._request("GET", f"{self._file_url()}?ref={urllib.parse.quote(self.branch)}") is not None

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        commits = self._request(
            "GET",
            f"{self._base}/repository/commits?path={urllib.parse.quote(self.file_path)}"
            f"&ref_name={urllib.parse.quote(self.branch)}&per_page={limit}",
        )
        return [
            {
                "version_id": c.get("short_id"),
                "at": c.get("committed_date"),
                "actor": c.get("author_name"),
                "message": c.get("title"),
            }
            for c in (commits or [])
        ]

    def health(self) -> dict[str, Any]:
        try:
            project = self._request("GET", self._base)
        except (ConfigError, StorageError) as exc:
            return {"backend": self.scheme, "target": self.project, "status": "error", "error": exc.message}
        if project is None:
            return {
                "backend": self.scheme,
                "target": self.project,
                "status": "error",
                "error": "Project not found, or the token cannot see it",
            }
        return {
            "backend": self.scheme,
            "target": self.project,
            "status": "ok",
            "host": self.host,
            "branch": self.branch,
            "path": self.file_path,
            "web_url": project.get("web_url", ""),
        }

    def describe(self) -> dict[str, Any]:
        info = super().describe()
        info.update({"host": self.host, "branch": self.branch, "path": self.file_path, "format": self.format})
        return info


register("gitlab", GitLabBackend)
