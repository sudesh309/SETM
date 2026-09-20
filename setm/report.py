"""Single-element reports.

A chief engineer reviewing one activity, work package or milestone needs to take
something into the room that is not a live web page: a self-contained page for a
review pack, or Markdown to paste into a minute. This module renders exactly
what the inspector shows -- properties, traceability grouped by question, the
gaps the ontology says are missing, impact and provenance -- into a document.

Nothing here hardcodes vocabulary: the sections come from the ontology, so a
tailored ontology produces a tailored report.
"""

from __future__ import annotations

import html
from typing import Any

from .graph import query
from .graph.store import GraphStore
from .kpi.metrics import element_weight
from .model import utc_now

FORMATS = ("md", "html", "json")

#: Relations at this weight are not annotated: it is the ontology default.
DEFAULT_RELATION_WEIGHT = "high"

#: Report sections follow the order a reviewer reads them in.
QUESTION_TITLES = {
    "who": "Who — responsibility and ownership",
    "when": "When — delivery commitment and sequence",
    "why": "Why — rationale, objectives, risks and requirements",
    "how": "How — process, method and tooling",
    "what": "What — products and the system it applies to",
    "where": "Where",
    "other": "Other relations",
}


def build_report(store: GraphStore, node_id: str, *, depth: int = 2) -> dict[str, Any]:
    """Assemble the report payload for one element."""
    node = store.node(node_id)
    ontology = store.ontology
    spec = ontology.node_types.get(node.type)
    trace = query.trace(store, node_id, depth=depth)

    properties = []
    for property_spec in (spec.properties.values() if spec else []):
        value = node.properties.get(property_spec.name)
        if value in (None, "", []):
            continue
        properties.append(
            {
                "name": property_spec.name,
                "label": property_spec.label,
                "group": property_spec.group,
                "value": value,
                "unit": property_spec.unit,
            }
        )
    # Anything the ontology no longer declares is still shown, flagged, rather
    # than silently dropped from a document someone will sign.
    undeclared = [k for k in node.properties if not spec or k not in spec.properties]
    for key in sorted(undeclared):
        properties.append(
            {
                "name": key,
                "label": f"{key} (not in ontology)",
                "group": "Undeclared",
                "value": node.properties[key],
                "unit": "",
            }
        )

    # A relation at the default weight says nothing, and repeating it on every
    # line buries the edge properties that do carry information.
    weight_property = ontology.role("weight_property", "weight")
    questions: dict[str, list[dict[str, Any]]] = {}
    for question, items in trace["questions"].items():
        rendered_items = []
        for item in items:
            edge_properties = dict(item["edge_properties"])
            if edge_properties.get(weight_property) == DEFAULT_RELATION_WEIGHT:
                edge_properties.pop(weight_property)
            rendered_items.append({**item, "edge_properties": edge_properties})
        questions[question] = rendered_items

    completeness = trace["completeness"]
    return {
        "generated_at": utc_now(),
        "project": store.project.to_dict(),
        "ontology": {"id": ontology.id, "version": ontology.version},
        "element": {
            "id": node.id,
            "type": node.type,
            "type_label": spec.label if spec else node.type,
            "type_description": spec.description if spec else "",
            "label": node.label,
            "weight": element_weight(ontology, node),
            "colour": spec.color if spec else "#6b7fd7",
        },
        "properties": properties,
        "questions": questions,
        "completeness": completeness,
        "impact": {
            "downstream": trace["downstream"],
            "upstream": trace["upstream"],
            "depth": depth,
        },
        "provenance": trace["provenance"],
    }


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, str):
        return value.replace("_", " ")
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    element = report["element"]
    lines: list[str] = [
        f"# {element['label']}",
        "",
        f"**{element['type_label']}** · `{element['id']}` · weight **{element['weight']}**",
        "",
        f"{report['project']['name']}"
        + (f" — {report['project']['programme']}" if report["project"]["programme"] else "")
        + (f" (phase {report['project']['phase']})" if report["project"]["phase"] else ""),
        "",
        f"Generated {report['generated_at']} from ontology "
        f"{report['ontology']['id']} v{report['ontology']['version']}.",
        "",
    ]

    if element["type_description"]:
        lines += ["> " + element["type_description"].strip().replace("\n", " "), ""]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in report["properties"]:
        grouped.setdefault(item["group"], []).append(item)
    if grouped:
        lines += ["## Properties", ""]
        for group, items in grouped.items():
            lines += [f"**{group}**", "", "| Property | Value |", "| --- | --- |"]
            for item in items:
                unit = f" {item['unit']}" if item["unit"] else ""
                lines.append(f"| {item['label']} | {_format_value(item['value'])}{unit} |")
            lines.append("")

    lines += ["## Traceability", ""]
    if not report["questions"]:
        lines += ["_This element has no relations._", ""]
    for question, title in QUESTION_TITLES.items():
        items = report["questions"].get(question)
        if not items:
            continue
        lines += [f"### {title}", ""]
        for item in items:
            node = item["node"]
            extra = ""
            if item["edge_properties"]:
                extra = " (" + ", ".join(
                    f"{k}: {_format_value(v)}" for k, v in item["edge_properties"].items()
                ) + ")"
            lines.append(f"- **{item['relation_label']}** {node['label']} — _{node['type_label']}_{extra}")
        lines.append("")

    missing = report["completeness"]["missing"]
    lines += ["## Traceability gaps", ""]
    if missing:
        lines.append(
            f"Completeness **{round(report['completeness']['score'] * 100)}%**. "
            "The ontology expects these links and does not find them:"
        )
        lines.append("")
        for question, relations in missing.items():
            lines.append(f"- **{question}**: {', '.join(relations)}")
    else:
        lines.append("None. This element answers every question the ontology expects of its type.")
    lines.append("")

    impact = report["impact"]
    lines += [
        "## Impact",
        "",
        f"Within {impact['depth']} hops, **{len(impact['downstream'])}** element(s) depend on this one "
        f"and it draws on **{len(impact['upstream'])}** upstream element(s).",
        "",
    ]
    for heading, items in (("Depends on this element", impact["downstream"]), ("This element depends on", impact["upstream"])):
        if not items:
            continue
        lines += [f"**{heading}**", ""]
        for item in items:
            lines.append(f"- {item['label']} — _{item['type_label']}_")
        lines.append("")

    provenance = report["provenance"]
    lines += [
        "## Provenance",
        "",
        "| | |",
        "| --- | --- |",
        f"| Created | {provenance['created_at']} by {provenance['created_by']} |",
        f"| Last updated | {provenance['updated_at']} by {provenance['updated_by']} |",
        f"| Revision | {provenance['revision']} |",
        f"| Source | {provenance['source']} |",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #

#: Weight reads as intensity, not as a good/bad signal.
_WEIGHT_COLOURS = {"high": "#4f46e5", "medium": "#818cf8", "low": "#94a3b8"}

_HTML_STYLE = """
:root { --ink:#16202f; --dim:#52637d; --faint:#8493a9; --line:#dde3ee; --accent:#2563eb; }
* { box-sizing:border-box; }
body { margin:0; padding:40px 48px 64px; background:#fff; color:var(--ink);
       font:14px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; max-width:940px; }
h1 { margin:0 0 6px; font-size:26px; line-height:1.25; }
h2 { margin:34px 0 12px; font-size:15px; text-transform:uppercase; letter-spacing:.07em;
     color:var(--faint); border-bottom:1px solid var(--line); padding-bottom:6px; }
h3 { margin:20px 0 8px; font-size:14px; color:var(--ink); }
p { margin:0 0 10px; }
.subtitle { color:var(--dim); font-size:13px; margin-bottom:4px; }
.chip { display:inline-block; font-size:11px; letter-spacing:.05em; text-transform:uppercase;
        border:1px solid var(--line); border-radius:4px; padding:2px 8px; margin-right:6px; }
.chip.weight { color:#fff; border:none; }
.meta { color:var(--faint); font-size:12px; margin-top:10px; }
.lead { color:var(--dim); border-left:3px solid var(--line); padding-left:12px; margin:14px 0; }
table { width:100%; border-collapse:collapse; margin:8px 0 18px; font-size:13px; }
th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.05em;
     color:var(--faint); padding:6px 10px; border-bottom:1px solid var(--line); }
td { padding:6px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
td.key { color:var(--dim); width:34%; }
ul { margin:6px 0 16px; padding-left:20px; }
li { margin-bottom:4px; }
.verb { color:var(--faint); }
.type { color:var(--faint); font-style:italic; font-size:12px; }
.gap { background:#fff7ed; border:1px solid #fed7aa; border-radius:6px; padding:12px 14px; }
.ok { background:#f0fdf4; border:1px solid #bbf7d0; border-radius:6px; padding:12px 14px; }
.cols { display:flex; gap:28px; flex-wrap:wrap; }
.cols > div { flex:1 1 300px; min-width:0; }
footer { margin-top:40px; padding-top:12px; border-top:1px solid var(--line);
         color:var(--faint); font-size:11px; }
@media print { body { padding:0; max-width:none; } h2 { break-after:avoid; } ul,table { break-inside:avoid; } }
"""


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def render_html(report: dict[str, Any]) -> str:
    element = report["element"]
    project = report["project"]
    parts: list[str] = []

    header = [project["name"]]
    if project["programme"]:
        header.append(project["programme"])
    if project["phase"]:
        header.append(f"phase {project['phase']}")

    parts.append(f'<p class="subtitle">{_e(" · ".join(header))}</p>')
    parts.append(f"<h1>{_e(element['label'])}</h1>")
    parts.append(
        '<p>'
        f'<span class="chip" style="border-color:{_e(element["colour"])};color:{_e(element["colour"])}">'
        f'{_e(element["type_label"])}</span>'
        f'<span class="chip weight" style="background:{_WEIGHT_COLOURS.get(element["weight"], "#94a3b8")}">'
        f'weight {_e(element["weight"])}</span>'
        f'<code>{_e(element["id"])}</code></p>'
    )
    if element["type_description"]:
        parts.append(f'<p class="lead">{_e(" ".join(element["type_description"].split()))}</p>')

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in report["properties"]:
        grouped.setdefault(item["group"], []).append(item)
    if grouped:
        parts.append("<h2>Properties</h2>")
        for group, items in grouped.items():
            parts.append(f"<h3>{_e(group)}</h3><table>")
            for item in items:
                unit = f" {item['unit']}" if item["unit"] else ""
                parts.append(
                    f'<tr><td class="key">{_e(item["label"])}</td>'
                    f"<td>{_e(_format_value(item['value']))}{_e(unit)}</td></tr>"
                )
            parts.append("</table>")

    parts.append("<h2>Traceability</h2>")
    if not report["questions"]:
        parts.append("<p>This element has no relations.</p>")
    for question, title in QUESTION_TITLES.items():
        items = report["questions"].get(question)
        if not items:
            continue
        parts.append(f"<h3>{_e(title)}</h3><ul>")
        for item in items:
            node = item["node"]
            extra = ""
            if item["edge_properties"]:
                rendered = ", ".join(f"{k}: {_format_value(v)}" for k, v in item["edge_properties"].items())
                extra = f' <span class="type">({_e(rendered)})</span>'
            parts.append(
                f'<li><span class="verb">{_e(item["relation_label"])}</span> '
                f'<strong>{_e(node["label"])}</strong> '
                f'<span class="type">{_e(node["type_label"])}</span>{extra}</li>'
            )
        parts.append("</ul>")

    missing = report["completeness"]["missing"]
    parts.append("<h2>Traceability gaps</h2>")
    if missing:
        rows = "".join(
            f"<li><strong>{_e(question)}</strong>: {_e(', '.join(relations))}</li>"
            for question, relations in missing.items()
        )
        parts.append(
            f'<div class="gap"><p>Completeness '
            f'<strong>{round(report["completeness"]["score"] * 100)}%</strong>. '
            f"The ontology expects these links and does not find them:</p><ul>{rows}</ul></div>"
        )
    else:
        parts.append(
            '<div class="ok">None. This element answers every question the ontology '
            "expects of its type.</div>"
        )

    impact = report["impact"]
    parts.append("<h2>Impact</h2>")
    parts.append(
        f"<p>Within {impact['depth']} hops, <strong>{len(impact['downstream'])}</strong> element(s) "
        f"depend on this one and it draws on <strong>{len(impact['upstream'])}</strong> "
        "upstream element(s).</p>"
    )
    parts.append('<div class="cols">')
    for heading, items in (
        ("Depends on this element", impact["downstream"]),
        ("This element depends on", impact["upstream"]),
    ):
        listed = "".join(
            f'<li>{_e(i["label"])} <span class="type">{_e(i["type_label"])}</span></li>' for i in items
        )
        parts.append(f"<div><h3>{_e(heading)}</h3><ul>{listed or '<li>None</li>'}</ul></div>")
    parts.append("</div>")

    provenance = report["provenance"]
    parts.append("<h2>Provenance</h2><table>")
    for key, value in (
        ("Created", f"{provenance['created_at']} by {provenance['created_by']}"),
        ("Last updated", f"{provenance['updated_at']} by {provenance['updated_by']}"),
        ("Revision", provenance["revision"]),
        ("Source", provenance["source"]),
    ):
        parts.append(f'<tr><td class="key">{_e(key)}</td><td>{_e(value)}</td></tr>')
    parts.append("</table>")

    parts.append(
        f"<footer>Generated {_e(report['generated_at'])} by SETM from ontology "
        f"{_e(report['ontology']['id'])} v{_e(report['ontology']['version'])}. "
        "Reflects the graph at the moment of export.</footer>"
    )

    return (
        "<!DOCTYPE html>\n"
        f'<html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(element['label'])} — {_e(project['name'])}</title>"
        f"<style>{_HTML_STYLE}</style></head><body>\n"
        + "\n".join(parts)
        + "\n</body></html>\n"
    )


def render(report: dict[str, Any], fmt: str = "md") -> str | dict[str, Any]:
    if fmt == "md":
        return render_markdown(report)
    if fmt == "html":
        return render_html(report)
    if fmt == "json":
        return report
    raise ValueError(f"Unsupported report format '{fmt}' (use {', '.join(FORMATS)})")


def safe_filename(report: dict[str, Any], extension: str) -> str:
    """A filename a reviewer can recognise in a downloads folder."""
    import re

    # Labels are free text and end up as a filename on someone's machine, so
    # strip anything that is a path separator or would make a hidden file.
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", report["element"]["label"]).strip("-. ")[:70]
    stem = re.sub(r"\.{2,}", ".", stem)
    return f"{stem or report['element']['id']}.{extension}"
