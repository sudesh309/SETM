"""Single-element report generation."""

from __future__ import annotations

import pytest

from setm.report import FORMATS, build_report, render, render_html, render_markdown, safe_filename


@pytest.fixture
def report(demo_store):
    return build_report(demo_store, "act.mtf")


def test_report_carries_the_element_and_its_context(report):
    assert report["element"]["id"] == "act.mtf"
    assert report["element"]["type_label"] == "SE activity"
    assert report["element"]["weight"] == "high"
    assert report["project"]["name"] == "HALO-1 Optical Payload"
    assert set(report["questions"]) >= {"who", "when", "why", "how", "what"}
    assert report["impact"]["downstream"]


def test_report_lists_declared_properties_with_their_labels(report):
    labels = {p["label"] for p in report["properties"]}
    assert "Rationale (why this work exists)" in labels
    assert "Estimated effort (person-days)" in labels
    groups = {p["group"] for p in report["properties"]}
    assert "Rationale" in groups and "Progress" in groups


def test_report_flags_properties_the_ontology_no_longer_declares(demo_store):
    demo_store.node("act.mtf").properties["legacy_field"] = "from an old import"
    report = build_report(demo_store, "act.mtf")
    undeclared = [p for p in report["properties"] if p["group"] == "Undeclared"]
    assert [p["name"] for p in undeclared] == ["legacy_field"]
    assert "not in ontology" in undeclared[0]["label"]


def test_default_relation_weight_is_not_annotated(report):
    """Every relation is high weight by default; printing it on each line is noise."""
    for items in report["questions"].values():
        for item in items:
            assert "weight" not in item["edge_properties"]


def test_non_default_relation_weight_is_kept(demo_store):
    edge = next(e for e in demo_store.out_edges("act.mtf") if e.type == "USES_TOOL")
    demo_store.update_edge(edge.id, {"weight": "low"})
    report = build_report(demo_store, "act.mtf")
    weights = [
        item["edge_properties"].get("weight")
        for item in report["questions"]["how"]
        if item["edge_id"] == edge.id
    ]
    assert weights == ["low"]


def test_markdown_has_every_section(report):
    text = render_markdown(report)
    for heading in ("# End-to-end MTF", "## Properties", "## Traceability", "## Traceability gaps", "## Impact", "## Provenance"):
        assert heading in text
    assert "| Property | Value |" in text
    assert "**is carried out by** C. Laurent" in text


def test_markdown_reports_a_clean_element_as_having_no_gaps(report):
    assert "answers every question the ontology expects" in render_markdown(report)


def test_markdown_lists_the_gaps_when_there_are_any(demo_store):
    demo_store.add_node("Activity", {"name": "Unplanned rework"}, node_id="act.rogue")
    text = render_markdown(build_report(demo_store, "act.rogue"))
    assert "Completeness **0%**" in text
    assert "- **who**: ACCOUNTABLE_FOR" in text
    assert "RESPONSIBLE_FOR" in text
    assert "USES_TOOL" in text  # the tool question is part of "how" now


def test_html_is_self_contained(report):
    page = render_html(report)
    assert page.startswith("<!DOCTYPE html>")
    assert "<style>" in page
    # No external requests: a report must open from a file share or an e-mail.
    assert "http://" not in page.replace("http://www.w3.org", "")
    assert "<script" not in page.lower()


def test_html_escapes_content(demo_store):
    """A label is user input and lands in a document other people open."""
    demo_store.update_node("act.mtf", {"name": '<script>alert("x")</script> & "quoted"'})
    page = render_html(build_report(demo_store, "act.mtf"))
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    assert "&amp;" in page


def test_render_dispatches_on_format(report):
    assert render(report, "md").startswith("# ")
    assert render(report, "html").startswith("<!DOCTYPE")
    assert render(report, "json") is report
    with pytest.raises(ValueError, match="Unsupported report format"):
        render(report, "docx")


def test_every_declared_format_renders(report):
    for fmt in FORMATS:
        assert render(report, fmt)


def test_filename_is_safe_and_recognisable(report):
    assert safe_filename(report, "html") == "End-to-end-MTF-and-radiometric-performance-analysis.html"


@pytest.mark.parametrize("label", ["../../etc/passwd", "  .hidden  ", "a/b\\c:d", "..", ""])
def test_filename_is_never_a_path_or_a_dotfile(demo_store, label):
    demo_store.update_node("act.mtf", {"name": label or "x"})
    name = safe_filename(build_report(demo_store, "act.mtf"), "md")
    assert "/" not in name and "\\" not in name
    assert not name.startswith(".")
    assert ".." not in name
    assert name.endswith(".md")


def test_report_depth_controls_the_impact_list(demo_store):
    shallow = build_report(demo_store, "act.mtf", depth=1)
    deep = build_report(demo_store, "act.mtf", depth=3)
    assert len(deep["impact"]["downstream"]) > len(shallow["impact"]["downstream"])


def test_report_works_for_every_element_type(demo_store):
    """No type should blow up the renderer -- a report is often the first thing tried."""
    seen = set()
    for node in demo_store.nodes():
        if node.type in seen:
            continue
        seen.add(node.type)
        report = build_report(demo_store, node.id)
        assert render_markdown(report)
        assert render_html(report)
    assert len(seen) >= 10
