"""Google Sheets backend.

The workbook *is* the database: one worksheet per node type, one ``_Relations``
worksheet, one ``_Project`` worksheet (see :mod:`setm.serialize.tabular`). That
means a work-package leader can fix a typo in the browser and the change is live
in SETM on the next load, which is usually the reason a team asks for Sheets in
the first place.

Usage::

    setm serve gsheet:1AbCdEf...  --storage-option credentials=./sa.json

Concurrency note: Sheets has no compare-and-swap, so SETM re-reads the revision
cell before writing and refuses to clobber a newer one unless ``force=true``.
"""

from __future__ import annotations

from typing import Any

from ..errors import ConflictError, StorageError
from ..model import GraphDocument
from ..ontology.loader import load_ontology
from ..serialize.tabular import PROJECT_SHEET, document_to_tables, tables_to_document
from .base import SaveResult, StorageBackend
from .google_common import GoogleClient
from .registry import register

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"


class GSheetBackend(StorageBackend):
    scheme = "gsheet"
    capabilities = {"read", "write", "remote"}

    def __init__(self, target: str, options: dict[str, Any] | None = None) -> None:
        super().__init__(target, options)
        self.spreadsheet_id = target.strip().strip("/").split("/")[-1]
        self.client = GoogleClient(self.options)
        self.ontology: Any = None

    def _ontology(self) -> Any:
        if self.ontology is None:
            self.ontology = load_ontology(self.options.get("ontology", "aerospace-se-core"))
        return self.ontology

    # -- sheet primitives ---------------------------------------------------
    def _metadata(self) -> dict[str, Any]:
        return self.client.request(
            "GET", f"{SHEETS_API}/{self.spreadsheet_id}", params={"fields": "properties.title,sheets.properties"}
        )

    def _sheet_titles(self) -> list[str]:
        meta = self._metadata()
        return [s["properties"]["title"] for s in meta.get("sheets", [])]

    def _read_all(self, titles: list[str]) -> dict[str, list[list[str]]]:
        if not titles:
            return {}
        response = self.client.request(
            "GET",
            f"{SHEETS_API}/{self.spreadsheet_id}/values:batchGet",
            params={"ranges": [f"'{t}'" for t in titles], "majorDimension": "ROWS"},
        )
        out: dict[str, list[list[str]]] = {}
        for title, block in zip(titles, response.get("valueRanges", [])):
            out[title] = [[str(cell) for cell in row] for row in block.get("values", [])]
        return out

    # -- backend API --------------------------------------------------------
    def load(self) -> GraphDocument:
        titles = self._sheet_titles()
        values = self._read_all(titles)
        tables = {
            title: {"header": rows[0] if rows else [], "rows": rows[1:] if len(rows) > 1 else []}
            for title, rows in values.items()
        }
        if not tables:
            return GraphDocument()
        return tables_to_document(tables, self._ontology())

    def save(self, document: GraphDocument, *, message: str = "", actor: str = "setm") -> SaveResult:
        self.require_writable()
        force = str(self.options.get("force", "")).lower() in ("1", "true", "yes")
        if not force:
            self._guard_against_clobber(document.revision)

        tables = document_to_tables(document, self._ontology())
        existing = set(self._sheet_titles())

        missing = [title for title in tables if title not in existing]
        if missing:
            self.client.request(
                "POST",
                f"{SHEETS_API}/{self.spreadsheet_id}:batchUpdate",
                body={"requests": [{"addSheet": {"properties": {"title": title}}} for title in missing]},
            )
            existing |= set(missing)

        # Clear worksheets that used to hold elements but are now empty.
        stale = [t for t in existing if (t in tables) or (t in self._managed_titles(existing))]
        self.client.request(
            "POST",
            f"{SHEETS_API}/{self.spreadsheet_id}/values:batchClear",
            body={"ranges": [f"'{t}'" for t in stale]},
        )
        self.client.request(
            "POST",
            f"{SHEETS_API}/{self.spreadsheet_id}/values:batchUpdate",
            body={
                "valueInputOption": "RAW",
                "data": [
                    {"range": f"'{title}'!A1", "majorDimension": "ROWS", "values": [table["header"], *table["rows"]]}
                    for title, table in tables.items()
                ],
            },
        )
        return SaveResult(
            revision=document.revision,
            message=message or "saved",
            location=f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}",
        )

    def _managed_titles(self, existing: set[str]) -> set[str]:
        """Worksheets SETM owns -- node types plus its two underscore sheets."""
        ontology = self._ontology()
        return {t for t in existing if t in ontology.node_types or t.startswith("_")}

    def _guard_against_clobber(self, outgoing_revision: int) -> None:
        try:
            response = self.client.request(
                "GET",
                f"{SHEETS_API}/{self.spreadsheet_id}/values/'{PROJECT_SHEET}'!A1:B20",
            )
        except StorageError:
            return  # first write: the sheet does not exist yet
        for row in response.get("values", []):
            if row and row[0] == "revision":
                try:
                    stored = int(row[1])
                except (IndexError, ValueError):
                    return
                if stored > outgoing_revision:
                    raise ConflictError(
                        f"The spreadsheet is at revision {stored}, newer than yours ({outgoing_revision}). "
                        "Reload before saving, or pass force=true.",
                        stored_revision=stored,
                    )
                return

    def health(self) -> dict[str, Any]:
        auth = self.client.health()
        if auth["status"] != "ok":
            return {"backend": self.scheme, "target": self.spreadsheet_id, **auth}
        try:
            meta = self._metadata()
            return {
                "backend": self.scheme,
                "target": self.spreadsheet_id,
                "status": "ok",
                "title": meta.get("properties", {}).get("title", ""),
                "worksheets": len(meta.get("sheets", [])),
            }
        except StorageError as exc:
            return {"backend": self.scheme, "target": self.spreadsheet_id, "status": "error", "error": exc.message}

    def describe(self) -> dict[str, Any]:
        info = super().describe()
        info["url"] = f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}"
        return info


register("gsheet", GSheetBackend)
register("sheets", GSheetBackend)
