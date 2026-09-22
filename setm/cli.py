"""Command line interface.

``python -m setm --help`` lists everything. The commands map one-to-one onto
:class:`~setm.workspace.Workspace` methods, so anything the web UI can do is also
scriptable for CI checks -- ``setm validate`` and ``setm kpi --fail-under`` are
designed to run as a pipeline gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import FIELD_SPECS, FIELDS_BY_NAME, SECRET_PLACEHOLDER, Settings
from .errors import SetmError
from .kpi.metrics import compute_kpis
from .model import GraphDocument
from .ontology.loader import _as_source, load_ontology, resolve_ontology_path
from .report import FORMATS as REPORT_FORMATS, build_report, render, safe_filename
from .serialize.rdfmap import document_to_turtle, ontology_to_owl, turtle_to_document
from .serialize.tabular import document_to_tables, tables_to_csv
from .storage.registry import available_schemes, load_builtin_backends, open_storage
from .workspace import Workspace

#: Styling collapses to empty strings when stdout is redirected, so piped output
#: and CI logs stay free of escape sequences.
_STYLED = sys.stdout.isatty() and "NO_COLOR" not in __import__("os").environ
GREEN, YELLOW, RED, DIM, BOLD, RESET = (
    ("\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m") if _STYLED else ("",) * 6
)
_BAND_COLOURS = {"good": GREEN, "watch": YELLOW, "poor": RED, "unknown": DIM}


def _colour(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if _STYLED else text


def _common_options() -> argparse.ArgumentParser:
    """Options accepted both before and after the subcommand."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--storage", help=f"storage URI ({', '.join(available_schemes() or ['json'])})")
    common.add_argument("--ontology", help="ontology file or built-in name (default: aerospace-se-core)")
    common.add_argument("--overlay", action="append", dest="overlays", help="extra ontology file layered on top")
    common.add_argument("--config", help="config file (default: setm.toml)")
    common.add_argument(
        "--storage-option",
        action="append",
        dest="storage_option",
        metavar="KEY=VALUE",
        help="backend option, repeatable (token=..., branch=..., path=...)",
    )
    common.add_argument("--strict", action="store_true", help="reject properties the ontology does not declare")
    common.add_argument("--actor", help="name recorded as the author of changes")
    return common


def build_parser() -> argparse.ArgumentParser:
    # The shared options live on each subparser rather than the top-level parser:
    # argparse lets a subparser's defaults overwrite values already parsed, so
    # declaring them in both places would silently discard `setm --storage X cmd`.
    common = _common_options()
    parser = argparse.ArgumentParser(
        prog="setm",
        description="SETM - plan, link and visualise systems engineering work on an aerospace programme.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  setm demo json:./data/demo.json               build the worked example\n"
            "  setm demo --example modification json:./data/modification.json  build the modification-programme example\n"
            "  setm serve json:./data/demo.json --open       open the web interface\n"
            "  setm validate --storage json:./data/demo.json check the graph against the ontology\n"
            "  setm kpi --fail-under 70                      use as a CI quality gate\n"
            "  setm convert data/demo.json data/demo.ttl     JSON to Turtle/RDF\n"
            "  setm report act.mtf --format html --out act.html   one-element review report\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"setm {__version__}")

    sub = parser.add_subparsers(dest="command", required=True, metavar="command")
    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[common])

    serve = add("serve", "run the web interface")
    serve.add_argument("target", nargs="?", help="storage URI (shorthand for --storage)")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--open", action="store_true", dest="open_browser", help="open a browser window")
    serve.add_argument("--no-autosave", action="store_true", help="keep changes in memory until an explicit save")

    init = add("init", "create an empty project")
    init.add_argument("target", nargs="?", help="storage URI")
    init.add_argument("--name", default="New project")
    init.add_argument("--programme", default="")
    init.add_argument("--chief-engineer", default="")

    demo = add("demo", "create a worked example project")
    demo.add_argument("target", nargs="?", help="storage URI")
    demo.add_argument("--force", action="store_true", help="overwrite an existing graph")
    demo.add_argument(
        "--example",
        default="payload",
        choices=["payload", "modification"],
        help="which worked example to build: 'payload' (new-development satellite payload, default) "
             "or 'modification' (in-service aircraft modification programme)",
    )

    add("info", "show workspace, storage and ontology status")

    validate = add("validate", "check the graph against the ontology")
    validate.add_argument("--json", action="store_true", help="machine readable output")

    kpi = add("kpi", "compute project KPIs")
    kpi.add_argument("--json", action="store_true")
    kpi.add_argument("--section", default="report", help="report | milestone_load | workload | work_package_health")
    kpi.add_argument("--fail-under", type=float, default=None, help="exit non-zero if health score is below this")

    report = add("report", "export a report for one element")
    report.add_argument("element", help="element id, e.g. act.mtf")
    report.add_argument("--format", default="md", choices=list(REPORT_FORMATS))
    report.add_argument("--out", help="output file (default: stdout)")
    report.add_argument("--depth", type=int, default=2, help="how far to follow impact (default 2)")

    export = add("export", "export the graph")
    export.add_argument("--format", default="json", choices=["json", "ttl", "owl", "csv"])
    export.add_argument("--out", help="output file or directory (csv writes one file per table)")

    import_cmd = add("import", "import a graph file")
    import_cmd.add_argument("path")
    import_cmd.add_argument("--merge", action="store_true", help="add to the current graph instead of replacing it")

    convert = add("convert", "convert between storage targets or file formats")
    convert.add_argument("source")
    convert.add_argument("destination")

    config_cmd = add("config", "show or change the stored settings")
    config_cmd.add_argument("action", choices=["show", "set", "path"])
    config_cmd.add_argument("assignments", nargs="*", metavar="KEY=VALUE", help="for `set`, e.g. autosave=false")

    ontology_cmd = add("ontology", "inspect or export the ontology")
    ontology_cmd.add_argument("action", choices=["show", "check", "export", "sync"])
    ontology_cmd.add_argument("--out", help="output file for export/sync")

    return parser


def _settings_from_args(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {}
    for key in ("storage", "ontology", "overlays", "actor", "host", "port", "open_browser"):
        value = getattr(args, key, None)
        if value:
            overrides[key] = value
    if getattr(args, "target", None):
        overrides["storage"] = args.target
    if getattr(args, "strict", False):
        overrides["strict"] = True
    if getattr(args, "no_autosave", False):
        overrides["autosave"] = False
    options = {}
    for item in getattr(args, "storage_option", None) or []:
        key, _, value = item.partition("=")
        if not value:
            raise SetmError(f"--storage-option expects KEY=VALUE, got '{item}'")
        options[key.strip()] = value.strip()
    if options:
        overrides["storage_options"] = options
    return Settings.load(getattr(args, "config", None), **overrides)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_serve(args: argparse.Namespace) -> int:
    from .api.server import serve

    settings = _settings_from_args(args)
    workspace = Workspace.open(settings)
    serve(workspace, settings)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    load_builtin_backends()
    ontology = load_ontology(settings.ontology, overlays=settings.overlays)
    backend = open_storage(settings.storage, **settings.storage_options)
    backend.bind_ontology(ontology)

    if backend.exists():
        print(f"{settings.storage} already holds a project; nothing written.")
        print("Point --storage at a new location, or open the existing one with `setm serve`.")
        return 1

    document = GraphDocument(ontology_id=ontology.id, ontology_version=ontology.version)
    document.project.name = args.name
    document.project.id = args.name.lower().replace(" ", "-")[:60] or "project"
    document.project.programme = args.programme
    document.project.chief_engineer = args.chief_engineer
    result = backend.save(document, message="initialise project", actor=settings.actor)
    print(f"Initialised '{args.name}' at {result.location or settings.storage}")
    print(f"Next: setm serve {settings.storage}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from .demo import build_demo
    from .modification_demo import build_modification_demo

    builders = {"payload": build_demo, "modification": build_modification_demo}
    build = builders[getattr(args, "example", "payload")]

    settings = _settings_from_args(args)
    load_builtin_backends()
    ontology = load_ontology(settings.ontology, overlays=settings.overlays)
    backend = open_storage(settings.storage, **settings.storage_options)
    backend.bind_ontology(ontology)

    if backend.exists() and not args.force:
        print(f"{settings.storage} already holds data. Re-run with --force to overwrite.")
        return 1

    document = build(ontology)
    result = backend.save(document, message="create demo project", actor="demo")
    print(f"Demo project '{document.project.name}' written to {result.location or settings.storage}")
    print(f"  {len(document.nodes)} elements, {len(document.edges)} relations")
    print(f"Next: setm serve {settings.storage}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    workspace = Workspace.open(_settings_from_args(args))
    health = workspace.health()
    print(f"{BOLD}project{RESET}   {workspace.store.project.name} ({workspace.store.project.programme or 'no programme'})")
    print(f"{BOLD}storage{RESET}   {health['storage']['scheme']}:{health['storage']['target']}")
    print(f"          status: {health['storage']['health'].get('status')}   "
          f"writable: {health['storage']['writable']}   versioned: {health['storage']['versioned']}")
    print(f"{BOLD}ontology{RESET}  {health['ontology']['id']} v{health['ontology']['version']}  "
          f"({health['ontology']['node_types']} node types, {health['ontology']['edge_types']} edge types)")
    print(f"          {health['ontology']['source']}")
    print(f"{BOLD}graph{RESET}     {health['graph']['nodes']} elements, {health['graph']['edges']} relations, "
          f"revision {health['graph']['revision']}")
    print(f"{BOLD}engine{RESET}    {health['engine']['backend']}")
    for type_name, count in health["graph"]["nodes_by_type"].items():
        print(f"    {count:>5}  {type_name}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    workspace = Workspace.open(_settings_from_args(args))
    report = workspace.validate()
    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report["valid"] else 1

    if report["valid"]:
        print(_colour(f"OK  {report['node_count']} elements and {report['edge_count']} relations are valid", GREEN))
    else:
        print(_colour(f"{report['error_count']} problem(s) found:", RED))
        for issue in report["errors"]:
            print(f"  [{issue['kind']}] {issue['element']}: {issue['message']}")
    for warning in report["warnings"]:
        print(_colour(f"  warning: {warning['message']}", YELLOW))
    return 0 if report["valid"] else 1


def cmd_kpi(args: argparse.Namespace) -> int:
    from .kpi.metrics import KPI_CATALOGUE

    workspace = Workspace.open(_settings_from_args(args))
    if args.section not in KPI_CATALOGUE:
        print(f"Unknown section '{args.section}'. Try: {', '.join(KPI_CATALOGUE)}")
        return 2
    if args.section == "report":
        result = compute_kpis(workspace.store, targets=workspace.settings.kpi_targets or None)
    else:
        result = KPI_CATALOGUE[args.section](workspace.store)

    if args.json:
        # Same shape the API returns, so a script can use either interchangeably.
        payload = result if isinstance(result, dict) else {"section": args.section, "items": result}
        print(json.dumps(payload, indent=2, default=str))
    elif args.section == "report":
        _print_kpi_report(result)
    else:
        _print_kpi_section(args.section, result)

    if args.fail_under is not None and args.section == "report":
        score = (result.get("health_score") or {}).get("value")
        if score is None:
            print("No health score could be computed.")
            return 2
        if score < args.fail_under:
            print(_colour(f"Health score {score} is below the required {args.fail_under}", RED))
            return 1
    return 0


def _print_kpi_report(report: dict[str, Any]) -> None:
    score = report.get("health_score") or {}
    band = score.get("band", "unknown")
    print(f"\n{BOLD}{report['project']['name']}{RESET}")
    print(f"Overall health  {_colour(str(score.get('value')), _BAND_COLOURS[band])} / 100  ({band})\n")
    print(f"{'KPI':<42}{'value':>9}{'target':>9}   band")
    print("-" * 72)
    for kpi in report["kpis"]:
        if not kpi["available"]:
            print(f"{kpi['name']:<42}{'n/a':>9}{'':>9}   {_colour('not configured', DIM)}")
            continue
        unit = kpi["unit"]
        value = f"{kpi['value']}{unit}"
        target = f"{kpi['target']}{unit}" if kpi["target"] is not None else ""
        print(f"{kpi['name']:<42}{value:>9}{target:>9}   {_colour(kpi['band'], _BAND_COLOURS[kpi['band']])}")

    milestones = report["breakdowns"]["by_milestone"]
    if milestones:
        print(f"\n{BOLD}Delivery by milestone{RESET}")
        for milestone in milestones:
            bar = _bar(milestone["readiness_percent"])
            print(
                f"  {milestone['label'][:32]:<32}"
                f" {milestone['activity_count']:>3} act"
                f" {milestone['deliverable_count']:>3} del  "
                f"{bar} {milestone['readiness_percent']:>5}%"
            )

    people = report["breakdowns"]["by_person"][:8]
    if people:
        print(f"\n{BOLD}Workload{RESET}")
        for person in people:
            print(f"  {person['label'][:24]:<24} {person['role'][:22]:<22} {person['activity_count']:>3} activities")
    print()


def _print_kpi_section(section: str, items: list[dict[str, Any]]) -> None:
    """Readable one-line-per-item output for the list-shaped KPI sections."""
    if not items:
        print(f"No data for '{section}'.")
        return
    print(f"\n{BOLD}{section.replace('_', ' ')}{RESET}  ({len(items)} items)\n")
    for item in items:
        label = str(item.get("label") or item.get("id") or "")
        facts = [
            f"{key.replace('_', ' ')} {value}"
            for key, value in item.items()
            if key not in ("id", "label") and isinstance(value, (str, int, float)) and value not in ("", None)
        ]
        print(f"  {label}")
        if facts:
            print(f"    {DIM}{' · '.join(facts)}{RESET}")
    print()


def _bar(percent: float, width: int = 20) -> str:
    filled = int(round(width * max(0.0, min(100.0, percent)) / 100))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def cmd_report(args: argparse.Namespace) -> int:
    workspace = Workspace.open(_settings_from_args(args))
    report = build_report(workspace.store, args.element, depth=args.depth)
    rendered = render(report, args.format)
    text = json.dumps(rendered, indent=2, default=str) if args.format == "json" else str(rendered)

    out = args.out
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        print(f"Wrote {out}")
    else:
        print(text)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    workspace = Workspace.open(_settings_from_args(args))
    document = workspace.store.snapshot()

    if args.format == "csv":
        tables = tables_to_csv(document_to_tables(document, workspace.ontology))
        if not args.out:
            for name, text in tables.items():
                print(f"# ---- {name} ----")
                print(text)
            return 0
        directory = Path(args.out)
        directory.mkdir(parents=True, exist_ok=True)
        for name, text in tables.items():
            (directory / f"{name}.csv").write_text(text, encoding="utf-8")
        print(f"Wrote {len(tables)} CSV files to {directory}")
        return 0

    if args.format == "json":
        text = json.dumps(document.to_dict(), indent=2, ensure_ascii=False)
    elif args.format == "ttl":
        text = document_to_turtle(document, workspace.ontology)
    else:
        text = ontology_to_owl(workspace.ontology)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    workspace = Workspace.open(_settings_from_args(args))
    path = Path(args.path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".ttl", ".turtle", ".owl", ".rdf"):
        document = turtle_to_document(text, workspace.ontology)
    else:
        document = GraphDocument.from_dict(json.loads(text))

    result = workspace.import_document(document, merge=args.merge)
    report = workspace.validate()
    workspace.save(message=f"import {path.name}")
    print(f"Imported {result['nodes']} elements and {result['edges']} relations "
          f"({'merged' if args.merge else 'replaced'})")
    if not report["valid"]:
        print(_colour(f"  {report['error_count']} validation problem(s) - run `setm validate` for detail", YELLOW))
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    load_builtin_backends()
    ontology = load_ontology(settings.ontology, overlays=settings.overlays)

    source = open_storage(args.source, **settings.storage_options)
    destination = open_storage(args.destination, **settings.storage_options)
    source.bind_ontology(ontology)
    destination.bind_ontology(ontology)

    document = source.load()
    result = destination.save(document, message=f"converted from {args.source}", actor=settings.actor)
    print(f"Converted {len(document.nodes)} elements and {len(document.edges)} relations")
    print(f"  {args.source}  ->  {result.location or args.destination}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)

    if args.action == "path":
        print(Path(settings.config_path).resolve())
        return 0

    if args.action == "set":
        if not args.assignments:
            print("Nothing to set. Example: setm config set autosave=false actor=a.okonkwo")
            return 2
        updates: dict[str, Any] = {}
        for item in args.assignments:
            key, _, value = item.partition("=")
            key = key.strip()
            if not value or key not in FIELDS_BY_NAME:
                print(_colour(f"error: '{item}' is not a KEY=VALUE for a known setting", RED), file=sys.stderr)
                print(f"  known settings: {', '.join(sorted(FIELDS_BY_NAME))}", file=sys.stderr)
                return 2
            updates[key] = value.strip()
        changed = settings.apply_update(updates)
        path = settings.save_file(include_secrets=True)
        print(f"Updated {', '.join(changed) or 'nothing'} in {path.resolve()}")
        if not changed:
            print("  (the values given already match)")
        return 0

    print(f"{BOLD}config{RESET}    {Path(settings.config_path).resolve()}"
          f"{'' if Path(settings.config_path).exists() else '  (not written yet)'}")
    shadowed = settings.shadowed_by_environment()
    values = settings.redacted()
    group = ""
    for spec in FIELD_SPECS:
        if spec.group != group:
            group = spec.group
            print(f"\n{BOLD}{group}{RESET}")
        value = values[spec.name]
        rendered = _render_setting(value)
        source = settings.source_of(spec.name)
        note = "" if source == "default" else f"  [{source}]"
        if spec.name in shadowed and source != "environment":
            note += _colour(f"  (overridden by {spec.env_var} on next start)", YELLOW)
        elif spec.restart_required:
            note += _colour("  (restart to apply)", DIM)
        print(f"  {spec.name:<17} {rendered}{note}")
    print()
    return 0


def _render_setting(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or _colour("(none)", DIM)
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items()) or _colour("(none)", DIM)
    return str(value) if value != "" else _colour("(empty)", DIM)


def cmd_ontology(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    ontology = load_ontology(settings.ontology, overlays=settings.overlays)

    if args.action == "check":
        print(_colour(f"OK  {ontology.id} v{ontology.version} is consistent", GREEN))
        print(f"  {len(ontology.node_types)} node types, {len(ontology.edge_types)} edge types, "
              f"{len(ontology.trace_paths)} trace paths")
        unmapped = [role for role, name in ontology.roles.items() if "_" not in role and not (
            name in ontology.node_types or name in ontology.edge_types)]
        if unmapped:
            print(_colour(f"  warning: roles point at missing types: {', '.join(unmapped)}", YELLOW))
        return 0

    if args.action == "show":
        for category in sorted({t.category for t in ontology.node_types.values()}):
            print(f"\n{BOLD}{category}{RESET}")
            for spec in ontology.node_types.values():
                if spec.category != category or spec.abstract:
                    continue
                print(f"  {spec.name:<18} {spec.label:<26} {len(spec.properties)} properties")
        print(f"\n{BOLD}Relations{RESET}")
        for spec in ontology.edge_types.values():
            domain = "/".join(spec.domain) or "any"
            target = "/".join(spec.range) or "any"
            print(f"  {spec.name:<22} {domain:<28} -> {target:<22} [{spec.question or '-'}]")
        return 0

    text = ontology_to_owl(ontology) if args.action == "export" else json.dumps(_as_source(ontology), indent=2)
    out = args.out
    if args.action == "sync" and not out:
        out = str(resolve_ontology_path(settings.ontology).with_suffix(".json"))
    if out:
        Path(out).write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")
        print(f"Wrote {out}")
    else:
        print(text)
    return 0


COMMANDS = {
    "serve": cmd_serve,
    "init": cmd_init,
    "demo": cmd_demo,
    "info": cmd_info,
    "validate": cmd_validate,
    "kpi": cmd_kpi,
    "report": cmd_report,
    "export": cmd_export,
    "import": cmd_import,
    "convert": cmd_convert,
    "config": cmd_config,
    "ontology": cmd_ontology,
}


def main(argv: list[str] | None = None) -> int:
    load_builtin_backends()
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except SetmError as exc:
        print(_colour(f"error: {exc.message}", RED), file=sys.stderr)
        if exc.details:
            print(f"  {json.dumps(exc.details, default=str)}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # `setm kpi | head` closes the pipe early; exit quietly rather than
        # printing a traceback over the user's terminal.
        try:
            sys.stdout.close()
        finally:
            return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
