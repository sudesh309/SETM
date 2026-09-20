"""Graph <-> spreadsheet mapping.

Engineers review and bulk-edit this kind of data in a spreadsheet, so the layout
is designed to be read by a human, not just a parser:

* one worksheet per node type, columns named after the ontology's properties,
* one ``_Relations`` worksheet holding every edge,
* one ``_Project`` worksheet holding the header fields,
* provenance columns prefixed with ``_`` so they are easy to ignore or hide.

The same tables drive the Google Sheets backend and CSV import/export.
"""

from __future__ import annotations

import json
from typing import Any

from ..model import Edge, GraphDocument, Node, ProjectInfo, Provenance
from ..ontology.schema import Ontology, PropertySpec

PROVENANCE_COLUMNS = ["_created_at", "_created_by", "_updated_at", "_updated_by", "_revision", "_source"]
RELATIONS_SHEET = "_Relations"
PROJECT_SHEET = "_Project"

Table = dict[str, Any]  # {"header": [str], "rows": [[str]]}


def _format(value: Any, spec: PropertySpec | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _provenance_row(provenance: Provenance) -> list[str]:
    return [
        provenance.created_at,
        provenance.created_by,
        provenance.updated_at,
        provenance.updated_by,
        str(provenance.revision),
        provenance.source,
    ]


def _provenance_from_row(row: dict[str, str]) -> Provenance:
    return Provenance.from_dict(
        {
            "created_at": row.get("_created_at") or None,
            "created_by": row.get("_created_by") or None,
            "updated_at": row.get("_updated_at") or None,
            "updated_by": row.get("_updated_by") or None,
            "revision": int(row.get("_revision") or 1),
            "source": row.get("_source") or "sheet",
        }
    )


def document_to_tables(document: GraphDocument, ontology: Ontology) -> dict[str, Table]:
    tables: dict[str, Table] = {
        PROJECT_SHEET: {
            "header": ["key", "value"],
            "rows": [
                ["id", document.project.id],
                ["name", document.project.name],
                ["programme", document.project.programme],
                ["phase", document.project.phase],
                ["description", document.project.description],
                ["chief_engineer", document.project.chief_engineer],
                ["ontology_id", document.ontology_id],
                ["ontology_version", document.ontology_version],
                ["revision", str(document.revision)],
                ["updated_at", document.updated_at],
            ],
        }
    }

    by_type: dict[str, list[Node]] = {}
    for node in document.nodes:
        by_type.setdefault(node.type, []).append(node)

    for type_name, nodes in sorted(by_type.items()):
        spec = ontology.node_types.get(type_name)
        declared = list(spec.properties) if spec else []
        extra = sorted({k for n in nodes for k in n.properties if k not in declared})
        columns = declared + extra
        header = ["id"] + columns + PROVENANCE_COLUMNS
        rows = []
        for node in nodes:
            property_specs = spec.properties if spec else {}
            rows.append(
                [node.id]
                + [_format(node.properties.get(c), property_specs.get(c)) for c in columns]
                + _provenance_row(node.provenance)
            )
        tables[type_name] = {"header": header, "rows": rows}

    edge_columns = sorted({k for e in document.edges for k in e.properties})
    tables[RELATIONS_SHEET] = {
        "header": ["id", "type", "source", "target"] + edge_columns + PROVENANCE_COLUMNS,
        "rows": [
            [edge.id, edge.type, edge.source, edge.target]
            + [_format(edge.properties.get(c), None) for c in edge_columns]
            + _provenance_row(edge.provenance)
            for edge in document.edges
        ],
    }
    return tables


def tables_to_document(tables: dict[str, Table], ontology: Ontology) -> GraphDocument:
    document = GraphDocument(nodes=[], edges=[])

    project_table = tables.get(PROJECT_SHEET)
    if project_table:
        values = {str(row[0]): (row[1] if len(row) > 1 else "") for row in project_table["rows"] if row}
        document.project = ProjectInfo.from_dict(values)
        document.ontology_id = values.get("ontology_id") or document.ontology_id
        document.ontology_version = values.get("ontology_version") or document.ontology_version
        try:
            document.revision = int(values.get("revision") or 0)
        except ValueError:
            document.revision = 0

    for sheet_name, table in tables.items():
        if sheet_name in (PROJECT_SHEET, RELATIONS_SHEET):
            continue
        if sheet_name not in ontology.node_types:
            continue  # a worksheet the user added for their own notes
        for row in _as_dicts(table):
            node_id = (row.get("id") or "").strip()
            if not node_id:
                continue
            document.nodes.append(
                Node(
                    id=node_id,
                    type=sheet_name,
                    properties=_properties_from_row(row, ontology.node_types[sheet_name].properties),
                    provenance=_provenance_from_row(row),
                )
            )

    relations = tables.get(RELATIONS_SHEET)
    if relations:
        for row in _as_dicts(relations):
            edge_id = (row.get("id") or "").strip()
            if not edge_id or not row.get("source") or not row.get("target"):
                continue
            edge_type = (row.get("type") or "").strip()
            specs = ontology.edge_types[edge_type].properties if edge_type in ontology.edge_types else {}
            document.edges.append(
                Edge(
                    id=edge_id,
                    type=edge_type,
                    source=row["source"].strip(),
                    target=row["target"].strip(),
                    properties=_properties_from_row(row, specs, skip={"type", "source", "target"}),
                    provenance=_provenance_from_row(row),
                )
            )
    return document


def _as_dicts(table: Table) -> list[dict[str, str]]:
    header = [str(h).strip() for h in table.get("header") or []]
    out = []
    for row in table.get("rows") or []:
        padded = list(row) + [""] * (len(header) - len(row))
        out.append({header[i]: str(padded[i]) if padded[i] is not None else "" for i in range(len(header))})
    return out


def _properties_from_row(
    row: dict[str, str], specs: dict[str, PropertySpec], skip: set[str] | None = None
) -> dict[str, Any]:
    skip = (skip or set()) | {"id"}
    out: dict[str, Any] = {}
    for key, value in row.items():
        if key in skip or key.startswith("_") or value in (None, ""):
            continue
        spec = specs.get(key)
        if spec and spec.datatype == "list":
            out[key] = [v.strip() for v in str(value).split(",") if v.strip()]
        else:
            out[key] = value
    return out


def tables_to_csv(tables: dict[str, Table]) -> dict[str, str]:
    """Render each table as CSV text, keyed by sheet name."""
    import csv
    import io

    out: dict[str, str] = {}
    for name, table in tables.items():
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(table["header"])
        writer.writerows(table["rows"])
        out[name] = buffer.getvalue()
    return out


def csv_to_table(text: str) -> Table:
    import csv
    import io

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return {"header": [], "rows": []}
    return {"header": rows[0], "rows": rows[1:]}
