"""Google Drive backend: the graph as a single JSON (or Turtle) file on Drive.

Two target forms::

    gdrive:<file-id>                       # update an existing file in place
    gdrive:folder/<folder-id>/graph.json   # create-or-update by name in a folder

Drive keeps its own revision history, so this backend advertises ``history``:
previous versions stay recoverable from the Drive UI even though SETM itself
always writes the whole file.
"""

from __future__ import annotations

import json
from typing import Any

from ..errors import ConfigError, StorageError
from ..model import GraphDocument
from ..ontology.loader import load_ontology
from .base import SaveResult, StorageBackend
from .google_common import GoogleClient
from .registry import register

DRIVE_API = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"


class GDriveBackend(StorageBackend):
    scheme = "gdrive"
    capabilities = {"read", "write", "remote", "history"}

    def __init__(self, target: str, options: dict[str, Any] | None = None) -> None:
        super().__init__(target, options)
        self.client = GoogleClient(self.options)
        self.ontology: Any = None
        self.folder_id = ""
        self.file_name = ""
        self.file_id = ""

        cleaned = target.strip().strip("/")
        if cleaned.startswith("folder/"):
            parts = cleaned.split("/", 2)
            if len(parts) < 3:
                raise ConfigError("Use gdrive:folder/<folder-id>/<file-name>")
            self.folder_id, self.file_name = parts[1], parts[2]
        else:
            self.file_id = cleaned
        self.format = str(self.options.get("format") or ("ttl" if (self.file_name or "").endswith(".ttl") else "json"))

    def _ontology(self) -> Any:
        if self.ontology is None:
            self.ontology = load_ontology(self.options.get("ontology", "aerospace-se-core"))
        return self.ontology

    def _resolve_file_id(self) -> str:
        if self.file_id:
            return self.file_id
        query = f"name = '{self.file_name}' and '{self.folder_id}' in parents and trashed = false"
        response = self.client.request("GET", DRIVE_API, params={"q": query, "fields": "files(id,name)"})
        files = response.get("files", [])
        if files:
            self.file_id = files[0]["id"]
        return self.file_id

    def load(self) -> GraphDocument:
        file_id = self._resolve_file_id()
        if not file_id:
            return GraphDocument()
        text = self._download(file_id)
        if not text.strip():
            return GraphDocument()
        if self.format == "ttl":
            from ..serialize.rdfmap import turtle_to_document

            return turtle_to_document(text, self._ontology())
        return GraphDocument.from_dict(json.loads(text))

    def _download(self, file_id: str) -> str:
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            f"{DRIVE_API}/{file_id}?alt=media",
            headers={"Authorization": f"Bearer {self.client.access_token()}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.client.timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise StorageError(f"Drive download failed with HTTP {exc.code}") from None

    def save(self, document: GraphDocument, *, message: str = "", actor: str = "setm") -> SaveResult:
        self.require_writable()
        if self.format == "ttl":
            from ..serialize.rdfmap import document_to_turtle

            payload = document_to_turtle(document, self._ontology())
            mime = "text/turtle"
        else:
            payload = json.dumps(document.to_dict(), indent=2, ensure_ascii=False)
            mime = "application/json"

        file_id = self._resolve_file_id()
        if file_id:
            self.client.request(
                "PATCH",
                f"{DRIVE_UPLOAD}/{file_id}",
                params={"uploadType": "media"},
                raw_body=payload.encode("utf-8"),
                content_type=mime,
            )
        else:
            if not self.folder_id:
                raise ConfigError("No file id and no folder given: use gdrive:folder/<folder-id>/<file-name>")
            created = self._create_multipart(payload, mime)
            file_id = self.file_id = created["id"]

        return SaveResult(
            revision=document.revision,
            message=message or "saved",
            location=f"https://drive.google.com/file/d/{file_id}",
            version_id=file_id,
        )

    def _create_multipart(self, payload: str, mime: str) -> dict[str, Any]:
        boundary = "setm-boundary-8f2c1e"
        metadata = {"name": self.file_name, "parents": [self.folder_id], "mimeType": mime}
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n"
            f"--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
            f"{payload}\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        return self.client.request(
            "POST",
            DRIVE_UPLOAD,
            params={"uploadType": "multipart", "fields": "id,name"},
            raw_body=body,
            content_type=f"multipart/related; boundary={boundary}",
        )

    def health(self) -> dict[str, Any]:
        auth = self.client.health()
        if auth["status"] != "ok":
            return {"backend": self.scheme, "target": self.target, **auth}
        try:
            file_id = self._resolve_file_id()
            if not file_id:
                return {"backend": self.scheme, "target": self.target, "status": "ok", "exists": False}
            meta = self.client.request(
                "GET", f"{DRIVE_API}/{file_id}", params={"fields": "id,name,size,modifiedTime"}
            )
            return {"backend": self.scheme, "target": self.target, "status": "ok", "exists": True, **meta}
        except StorageError as exc:
            return {"backend": self.scheme, "target": self.target, "status": "error", "error": exc.message}


register("gdrive", GDriveBackend)
register("drive", GDriveBackend)
