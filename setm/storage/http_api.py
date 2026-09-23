"""Generic HTTP backend -- point SETM at any server that speaks the JSON document.

The contract is deliberately tiny, so wiring SETM to an in-house PLM/ALM service
is a two-endpoint job:

* ``GET  <url>``  -> the graph document as JSON
* ``PUT  <url>``  -> accepts the same JSON, returns anything

Auth: ``?token=...`` (sent as ``Authorization: Bearer``) or ``?header=Name:Value``
repeated as needed; ``SETM_HTTP_TOKEN`` is honoured too.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..errors import StorageError
from ..model import GraphDocument
from .base import SaveResult, StorageBackend, credentialed_opener
from .registry import register


class HttpBackend(StorageBackend):
    scheme = "http"
    capabilities = {"read", "write", "remote"}

    def __init__(self, target: str, options: dict[str, Any] | None = None) -> None:
        super().__init__(target, options)
        self.url = target
        self.timeout = float(self.options.get("timeout", 30))
        if str(self.options.get("readonly", "")).lower() in ("1", "true", "yes"):
            self.capabilities = {"read", "remote"}

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        token = self.options.get("token") or os.environ.get("SETM_HTTP_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        raw = self.options.get("header")
        for item in raw if isinstance(raw, list) else ([raw] if raw else []):
            name, _, value = str(item).partition(":")
            if name and value:
                headers[name.strip()] = value.strip()
        return headers

    def _call(self, method: str, body: bytes | None = None) -> Any:
        headers = self._headers()
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.url, data=body, method=method, headers=headers)
        try:
            with credentialed_opener().open(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload) if payload.strip() else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and method == "GET":
                return None
            raise StorageError(f"{method} {self.url} failed with HTTP {exc.code}", status_code=exc.code) from None
        except urllib.error.URLError as exc:
            raise StorageError(f"Could not reach {self.url}: {exc.reason}") from None

    def load(self) -> GraphDocument:
        payload = self._call("GET")
        if not payload:
            return GraphDocument()
        return GraphDocument.from_dict(payload)

    def save(self, document: GraphDocument, *, message: str = "", actor: str = "setm") -> SaveResult:
        self.require_writable()
        body = json.dumps({**document.to_dict(), "commit_message": message, "actor": actor}).encode("utf-8")
        self._call(str(self.options.get("method") or "PUT"), body)
        return SaveResult(revision=document.revision, message=message or "saved", location=self.url)

    def health(self) -> dict[str, Any]:
        try:
            self._call("GET")
            return {"backend": self.scheme, "target": self.url, "status": "ok"}
        except StorageError as exc:
            return {"backend": self.scheme, "target": self.url, "status": "error", "error": exc.message}


register("http", HttpBackend)
register("https", HttpBackend)
