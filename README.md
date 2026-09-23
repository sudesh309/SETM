# SETM — Systems Engineering Traceability Manager

A standalone tool for **chief engineers, work package leaders and systems
engineers** to plan, link and visualise the systems engineering work on an
aerospace programme.

It answers, for every piece of SE work, the five questions a chief engineer
actually asks at a review:

| Question | Recorded as |
|---|---|
| **Who** is doing it | `Person —is responsible for→ Activity`, plus accountable and consulted |
| **When** will it land | `Activity —delivers at→ Milestone` — **programme gates, never dates** |
| **Why** does it exist | `Activity —supports→ Objective`, `mitigates→ Risk`, `verifies→ Requirement` |
| **How** is it done | `Activity —implements process→ SE process`, `governed by→ Business process`, `uses method→ Method`, `uses tool→ Tool` |
| **What** does it produce | `Activity —produces→ Deliverable`, `applies to→ System element` |

Every element and every relation also carries a **weight** — low, medium or
high, defaulting to high — so the graph can say what actually matters, not just
what exists.

Because those links are a graph and not a spreadsheet column, the tool can tell
you what a schedule slip actually breaks, which objectives nobody is working
towards, which engineer is carrying four commitments into the same gate, and
which unqualified tool is producing certification evidence.

## Why milestones instead of dates

Dates in an SE plan are stale the week after they are written, and re-baselining
a date-driven plan is most of the reason these plans get abandoned. SETM records
commitment to a **gate** (SRR, PDR, CDR, TRR, QR …). When the programme schedule
moves, the plan is still correct — only the gate's date changed, and that lives
in the scheduling tool where it belongs.

---

## Quick start

Clone the repo, then install it in place (still no required dependencies --
this only registers the `setm` command):

```bash
git clone <this repo>
cd SETM                   # the folder containing pyproject.toml, NOT the setm/ subfolder
pip install -e .          # core: standard library only
pip install -e '.[all]'   # optional: YAML ontologies, Google, rdflib, ASGI

setm demo                 # build the worked example
setm serve --open
```

Then open <http://127.0.0.1:8765>. It lands on **Overview** — health score, what is below
target, gate readiness and the top risks on one screen — with the working views along the top and
Ontology / System / Settings behind the gear.

**Windows note:** if `setm` isn't found after install, use `python -m setm` in
its place -- but do this *after* `pip install -e .`, not instead of it. Without
an install, `python -m setm ...` only works when your current directory is
the repo root (the one with `pyproject.toml`), and on a case-insensitive
filesystem it is easy to `cd` one folder too far, into `setm/` itself, where
`No module named setm` is the result. Installing removes that trap entirely:
both `setm` and `python -m setm` then work from anywhere.

**Pulled a change but don't see it?** Run `setm info` and check the `code` line at the top: it
should point at this checkout. If it points into a `site-packages` copy instead, `setm info` says
so directly -- `git pull` in a checkout never reaches an installed copy elsewhere. Reinstall with
`pip install -e .` from the checkout, then hard-refresh the browser tab (the app is served fresh
per request, but the browser may still be holding an old cached copy of the JS).

The demo is a Phase B satellite payload programme: 4 objectives, 5 gates,
4 work packages, 13 activities, a 7-tool engineering chain, requirements, risks
and processes, all linked.

A second worked example ships too: a complex in-service aircraft modification
programme (obsolescence redesign and a performance retrofit, sharing an
architecture baseline of OAD/OPD/OSD deliverables and a real system-element
breakdown). Build it with:

```bash
setm demo --example modification --force        # replaces the demo above, so `setm serve` shows it
setm demo --example modification json:./data/modification.json   # or keep both side by side
```

`--force` is needed because `setm demo` above already wrote the default project file, and
`setm demo` never overwrites one silently. Without it you get
`already holds data. Re-run with --force to overwrite.` — that is the guard talking, not a
missing flag.

You can also import the ready-made file directly:

```bash
setm import examples/modification-programme.json
```

or load it without leaving the browser: open **Settings** in the running app and use the
"Worked examples" card. The "Load a project file" card beside it opens any JSON graph SETM has
exported, replacing the current project or merging into it.

### Where the graph lives

The default is a **local JSON file** — no credentials, no network, no setup, so
the tool works the moment it is unpacked. Everything else is one flag away, and
`setm convert` moves a graph between any two backends.

When the project is real, move it to **GitLab**, where each save becomes a
reviewable commit under the configuration management the organisation already
runs:

```bash
export SETM_GITLAB_TOKEN=glpat-...             # scope: api
setm init  gitlab:my-group/my-project --name "HALO-2"
setm serve gitlab:my-group/my-project
```

The project may be left out entirely — SETM resolves it from
`SETM_GITLAB_PROJECT`, or from the `origin` remote of the checkout you are
standing in, so `setm serve gitlab:` inside a repository usually just works.
Concurrent edits are safe: a save carries the commit the graph was read at, so
GitLab rejects a write that would clobber a colleague's, and SETM tells you to
reload rather than silently winning.

## What you get

**Graph view** — the whole project as a navigable network. Filter by element
type or by which *question* a relation answers; select an element to see its
traceability grouped by who / when / why / how / what, plus the gaps the
ontology says it is missing.

**Milestones** — what each gate is waiting on, with readiness and status mix.

**Workload** — who owns what, split by the gate they owe it to.

**Tools** — the engineering tool chain: who administers each tool, what depends
on it, whether its qualification is settled, and every hop where data is re-keyed
by hand between one tool and the next.

**KPIs** — measured from the graph, so they cannot drift from the plan
(details below).

**Ontology** — browse the vocabulary, reload it after an edit, export it as OWL.

**System** — storage health, validation, and live application performance.

**Settings** — every setting the tool reads at startup, editable in the browser
and written back to `setm.toml`. See below.

**Reports** — any element exports as a self-contained web page (for a review
pack), Markdown (for a minute or a merge request) or JSON. It carries the
properties, the traceability grouped by question, the gaps the ontology expects
filled, the impact and the provenance.

## Command line

Everything the interface does is scriptable, which is the point of
`setm validate` and `setm kpi --fail-under` as CI gates.

```bash
setm serve json:./data/project.json     # web interface
setm init  sqlite:./data/project.db --name "HALO-2" --chief-engineer "A. Okonkwo"
setm info                               # storage, ontology and graph status
setm validate                           # conformance check; non-zero exit on failure
setm kpi --fail-under 70                # CI quality gate
setm kpi --section workload --json
setm kpi --section tool_usage           # the tool chain, licences, qualification
setm report act.mtf --format html --out review.html   # one-element report
setm export --format ttl --out project.ttl
setm export --format csv --out ./csv    # one file per element type
setm import ./from-another-tool.json --merge
setm convert json:./p.json rdf:./p.ttl  # any backend to any backend
setm ontology show | check | export | sync
setm config show | set autosave=false actor=a.okonkwo | path
```

---

## Storage backends

The graph is the same document everywhere; the backend only decides where it
lives. Pick one with a URI:

| URI | Notes |
|---|---|
| `json:./data/project.json` | **the default.** Local file, atomic writes with rolling backups; nothing to configure |
| `gitlab:group/project?path=se/graph.json&branch=main` | the one to move to for a real programme. Every save is a commit: review, blame, rollback, and a compare-and-swap that refuses to clobber a colleague |
| `sqlite:./data/project.db` | single file, plus an append-only change log |
| `rdf:./data/project.ttl` | Turtle/OWL; add `?sparql=<endpoint>` to push to a triple store |
| `gsheet:<spreadsheet-id>` | one worksheet per element type — engineers edit it in the browser |
| `gdrive:<file-id>` or `gdrive:folder/<id>/graph.json` | Drive keeps its own version history |
| `https://host/api/graph` | any service that can `GET` and `PUT` the JSON document |
| `memory:` | throwaway, for tests |

A bare path works too — `setm serve ./project.ttl` infers the backend from the
extension.

Switching is one flag: `--storage sqlite:./data/project.db` once a JSON file
feels small, `--storage gsheet:<id>` when a work package leader wants to
bulk-edit in a browser, `--storage gitlab:my-group/my-project` when the graph
needs an audit trail. A bare `gitlab:` resolves its project from
`SETM_GITLAB_PROJECT` or the surrounding checkout's `origin` remote.
`setm convert` moves an existing graph between any two of them, losslessly.

Credentials are never stored in the graph:

```bash
export SETM_GITLAB_TOKEN=glpat-...            # or --storage-option token=...
export GOOGLE_APPLICATION_CREDENTIALS=./sa.json
```

Adding a backend is one file implementing `load()` and `save()` — see
`setm/storage/base.py`.

## The ontology is a separate file

`ontologies/aerospace-se-core.yaml` — not the application code — defines what a
project may contain: the element types, their properties, the legal relations
and their cardinality. A methods-and-tools team owns it. Edit it, hit **Reload
from disk**, and the forms, the validation, the RDF export and the KPIs all
follow immediately.

```yaml
node_types:
  Activity:
    extends: Thing
    category: What
    color: "#2563eb"
    properties:
      rationale:
        type: text
        label: Rationale (why this work exists)
        group: Rationale
      effort_days: { type: number, minimum: 0 }

edge_types:
  DELIVERS_AT:
    label: delivers at
    question: when          # drives the traceability panel and the KPI engine
    domain: [Activity, Deliverable]
    range:  [Milestone]
    cardinality: many_to_one
```

Three things make this work without code changes:

- **`question`** on each relation is what groups the inspector panel and tells
  the completeness check which links an element is missing.
- **`roles`** maps semantic names (`activity`, `milestone`, `responsible`) onto
  your type names, so the generic KPI engine finds your concepts even if you
  rename everything. A role that is absent just makes its KPI report
  `available: false` rather than failing.
- **`trace_paths`** are named chains the UI offers as one-click questions;
  `~` walks a step backwards:
  `milestone_to_owners: [~DELIVERS_AT, ~RESPONSIBLE_FOR]`.

Tailor per programme without forking the core file — see
`ontologies/example-programme-overlay.yaml`:

```bash
setm serve json:./data/p.json --ontology ./ontologies/example-programme-overlay.yaml
```

The ontology also exports as OWL, so the vocabulary can be handed to Protégé, a
SHACL validator or a triple store:

```bash
setm ontology export --out aerospace-se-core.ttl
```

## Settings

Everything the tool reads at startup is editable on the **Settings** page and, if
you ask it to, written back to `setm.toml` so it survives a restart. The form is
generated from field metadata in `setm/config.py`, the same way element forms are
generated from the ontology: add a setting there and a row appears.

A value can come from four places — the built-in default, the config file, a
`SETM_*` environment variable, or a command-line flag — and the page tags each
field with **which layer won**. That matters more than it sounds: editing a field
that an environment variable is shadowing would otherwise look like it worked and
silently revert on the next start, so the page says so instead.

Three kinds of change behave differently, and the page is explicit about which
is which:

- **Immediate** — autosave, strict validation, default author, KPI targets.
- **Reopens the project** — storage target, backend options, ontology, overlays.
  These rebuild the workspace, so SETM asks first, and refuses to discard unsaved
  work unless you tell it to.
- **Needs a restart** — bind address and port, which are read when the server
  starts.

**Credentials are handled carefully.** A token is never sent to the browser: the
page receives a placeholder, and sending it back unchanged leaves the stored
value alone, so a form that never saw the secret cannot erase it. Saving to the
config file leaves credentials out unless you explicitly tick the box — a token
written to a file outlives the session that needed it, and the environment is the
better home for one.

**Test connection** probes a candidate backend without switching to it, and says
whether a project is already stored there, so you can confirm a GitLab project,
branch and token are right before pointing the live workspace at them.

The same settings are reachable from the CLI:

```bash
setm config show                                 # values, with where each came from
setm config set autosave=false actor=a.okonkwo   # writes setm.toml
setm config path
```

## Weight

Every element and every relation carries `weight`: `low`, `medium` or `high`,
**defaulting to high**. The default is deliberate — nothing should quietly
become unimportant; an engineer has to decide something is low weight.

Weight is not decoration. It:

- **thickens the relation** in the graph, so the load-bearing links stand out;
- **filters** the view — hide low and medium to see only what the programme
  said matters;
- **orders every gap list**, so a red KPI leads with the heaviest offenders;
- drives its own KPI, **high-weight activities fully traced**, which is the one
  most worth putting on a gate slide: it is a gap the programme itself called
  important.

It reaches all 27 relation types through `default_properties` in the ontology,
since relations have no inheritance of their own:

```yaml
default_properties:
  node_types: [weighting]
  edge_types: [weighting]
```

A type that wants different levels simply declares `weight` itself and wins.

## Tools

Tools are elements, not a free-text field. A `Tool` records its vendor,
version, licence model and seat count, and — the part an authority asks about —
its **qualification status**. It links into the graph like anything else:

```
Activity     —uses tool→            Tool
Method       —is implemented by→    Tool
Person       —administers→          Tool
Tool         —exchanges data with→  Tool   (format, and whether it is automated)
```

That last relation is the tool chain, and drawing it explicitly is the point:
every hop is a place data is transformed, and every *manual* hop is a place the
model and the analysis drift apart. SETM counts them
(`manual_tool_handovers`) and the Tools page lists them first.

## KPIs

Two separate things, both live.

**Project KPIs** (`/api/kpi`, the KPIs page) are queries over the graph, so
they measure the plan rather than a status report about the plan. Each carries a
target, a good/watch/poor band, and the specific elements responsible — click a
red number to get the list:

`objective_coverage`, `activity_ownership`, `milestone_anchoring`,
`process_linkage`, `process_utilisation`, `verification_coverage`,
`tool_linkage`, `tool_qualification`, `manual_tool_handovers`,
`high_weight_traceability`, `traceability_completeness`, `orphan_rate`,
`dependency_cycles` — plus per-gate readiness, per-person workload,
per-work-package health, the tool chain and the weight distribution. The overall
health score is the mean attainment of every measurable KPI against its target.
Targets are programme-specific, so every one of them is editable on the Settings
page and applies to the dashboard, the API and the `--fail-under` CI gate alike.

**Application performance** (`/api/kpi/app`, the System page) is measured inside
the server: request and storage latency with p50/p95/p99, error rates, graph
size, memory and thread count. The same numbers are exposed for scraping:

```bash
curl localhost:8765/metrics     # Prometheus text format
```

## HTTP API

`GET /api/routes` lists everything. The essentials:

```
GET    /api/graph?type=Activity&q=thermal
POST   /api/nodes                      PATCH/DELETE /api/nodes/{id}
POST   /api/edges                      PATCH/DELETE /api/edges/{id}
GET    /api/edges/allowed?source_type=Activity     # what the ontology permits
GET    /api/nodes/{id}/trace           # who/when/why/how/what + gaps
GET    /api/nodes/{id}/context?depth=2
GET    /api/nodes/{id}/impact?direction=out
GET    /api/nodes/{id}/report?format=html|md|json[&download=1]
GET    /api/paths?source=…&target=…
GET    /api/kpi  |  /api/kpi/app  |  /api/validate  |  /metrics
GET    /api/settings                   PATCH /api/settings
POST   /api/settings/test-storage      POST  /api/settings/reopen
GET    /api/export?format=json|ttl|owl|csv         POST /api/import
```

Errors are typed JSON (`validation_error`, `conflict`, `not_found`, …) with the
offending property named. Set `api_token` to require `X-SETM-Token`; pass
`X-SETM-User` to record who made a change.

---

## Architecture

Layered, each depending only on the one below, which is why a backend or a KPI
is a small isolated change:

```
setm/web/          vanilla JS: canvas graph, ontology-driven forms, dashboards
setm/api/          route table (routes.py) + stdlib server (server.py) + ASGI (asgi.py)
setm/config.py     settings, their provenance, and the settings-page metadata
setm/workspace.py  ties ontology + storage + graph together; autosave
setm/report.py     single-element reports as HTML, Markdown or JSON
setm/kpi/          project KPIs (metrics.py) and app telemetry (telemetry.py)
setm/graph/        indexed store (store.py), traversal (query.py), accel hook (_fastpath.py)
setm/storage/      pluggable backends behind one ABC + a URI registry
setm/serialize/    Turtle/OWL reader+writer, spreadsheet tables
setm/ontology/     schema, loader (inheritance, overlays), validator
setm/model.py      Node, Edge, GraphDocument — plain dataclasses
```

Deliberate choices worth knowing about:

- **Zero required dependencies.** The server is `http.server`, the Turtle
  reader/writer is hand-written, the front end has no build step and no CDN. It
  installs on a locked-down engineering workstation and runs offline. Optional
  extras (FastAPI, rdflib, google-auth, PyYAML) are imported lazily and fail
  with an instruction rather than a traceback.
- **Route handlers are pure functions** of `(workspace, request)`, so the stdlib
  server and the FastAPI adapter serve the identical route table.
- **Validation happens on write**, in the store, not in the UI — the CLI, the
  API and an import all get the same guarantees.
- **Every element carries provenance** (created/updated by whom, revision,
  source) and writes take an optional `expected_revision` for optimistic
  locking.

## Performance and scale

The graph is held in memory and indexed; reads are dict lookups, and a write is
O(degree) plus validation. Measured on a synthetic programme of **5,377 elements
and 26,666 relations** (single CPython process, no Rust extension):

| Operation | Time |
|---|---|
| Trace one activity (who/when/why/how/what + gaps) | 0.08 ms |
| Neighbourhood, depth 2 | 4.4 ms |
| Cycle detection over the dependency network | 14 ms |
| Full graph read (what the UI loads) | 46 ms |
| Whole-graph conformance validation | 0.4 s |
| Full KPI report (13 KPIs + 6 breakdowns) | 0.5 s |
| Bulk import, every edge validated | 26 µs/edge |

Repulsion in the browser layout uses spatial binning rather than all-pairs, and
labels are placed greedily with collision rejection, so a dense graph stays
legible. Two costs are pinned by tests rather than left to drift. Cardinality is
enforced against the two endpoints' own indices rather than by rescanning the
edge type — the difference between 0.7 s and 15 s on that import. And
traceability completeness, which four KPIs need, is computed once per activity
and shared, which is why adding the tool and weight KPIs made the report
*faster* rather than twice as slow.

For a much larger programme:

- `rust/setm_core` is an optional PyO3 extension for breadth-first traversal.
  `setm/graph/_fastpath.py` uses it if importable and falls back to Python
  otherwise; the System page reports which is live. Build it only if traversal
  shows up in the latency figures — see that crate's README.
- `setm.api.asgi` runs under uvicorn/gunicorn for TLS and process management.
  **One writer process**: the graph is per-process in-memory state, so multiple
  writable workers would diverge. Threads handle concurrency fine. Read-only
  replicas can be scaled freely.

## Testing

```bash
pip install -e '.[dev]'
pytest                      # 250 tests
```

Covering ontology inheritance and validation, graph mutation and traversal,
lossless round-trips through every file backend and exchange format, the full
API surface, KPI computation, the CLI, and the HTTP server end to end.

## Repository layout

```
setm/                  application
ontologies/            aerospace-se-core.yaml + example programme overlay
rust/setm_core/        optional traversal accelerator
tests/                 test suite
setm.toml.example      configuration template
```

## Configuration

Lowest priority first: defaults → `setm.toml` → `SETM_*` environment variables →
command-line flags. Edit it on the Settings page, with `setm config set`, or by
copying `setm.toml.example` to `setm.toml` and editing it by hand.

## Status

Working MVP. A local JSON file out of the box; GitLab when the graph needs
the organisation's configuration management behind it.

Sensible next steps: multi-user write concurrency beyond the compare-and-swap
GitLab gives (the in-memory graph is still single-writer), a diff view between
two commits of the graph, and importers for DOORS/Jama and SysML v2 — the
`Tool` type now gives those importers somewhere to record which tool the data
came from.
