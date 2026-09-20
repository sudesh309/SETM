// The non-graph pages: milestone board, workload, KPIs, ontology browser and
// the system/performance page. Each render function takes data and a container
// and returns nothing -- state lives in app.js.

import { h, formatValue } from './forms.js';

const STATUS_COLOURS = {
  done: '#34d399',
  in_progress: '#4d8bf5',
  in_review: '#a78bfa',
  blocked: '#f87171',
  not_started: '#64748b',
  cancelled: '#475569',
  unset: '#475569',
};

function statusColour(status) {
  return STATUS_COLOURS[status] || '#94a3b8';
}

function plural(count, singular, pluralForm) {
  return `${count} ${count === 1 ? singular : pluralForm || `${singular}s`}`;
}

function pageHead(title, description) {
  return h('div', { class: 'page-head' }, [h('h1', { text: title }), h('p', { text: description })]);
}

function bar(percent, band) {
  return h('div', { class: `bar ${band || ''}` }, [h('span', { style: `width:${Math.max(0, Math.min(100, percent))}%` })]);
}

function stackBar(mix) {
  const total = Object.values(mix).reduce((sum, n) => sum + n, 0) || 1;
  const segments = Object.entries(mix).map(([status, count]) =>
    h('span', { style: `width:${(100 * count) / total}%;background:${statusColour(status)}`, title: `${status}: ${count}` }));
  return h('div', {}, [
    h('div', { class: 'stack-bar' }, segments),
    h('div', { class: 'legend-row' }, Object.entries(mix).map(([status, count]) =>
      h('span', {}, [
        h('i', { class: 'status-dot', style: `background:${statusColour(status)}` }),
        `${status.replace(/_/g, ' ')} ${count}`,
      ]))),
  ]);
}

// --------------------------------------------------------------- milestones
export function renderMilestones(container, milestones, onOpen) {
  container.replaceChildren(
    pageHead(
      'Delivery by milestone',
      'What each programme gate is waiting on. SETM anchors commitments to milestones rather than dates, '
      + 'so the plan survives a schedule change: only the gate a piece of work reports to matters.',
    ),
  );

  if (!milestones.length) {
    container.append(h('div', { class: 'card' }, [
      h('p', { class: 'muted', text: 'No milestones defined yet. Add a Milestone element and link activities to it with "delivers at".' }),
    ]));
    return;
  }

  for (const milestone of milestones) {
    const card = h('div', { class: 'card' });
    card.append(h('div', { class: 'card-head' }, [
      h('h3', { text: milestone.label }),
      milestone.gate ? h('span', { class: 'tag', text: milestone.gate }) : null,
      h('span', { class: 'muted', text: `${plural(milestone.activity_count, 'activity', 'activities')} · ${plural(milestone.deliverable_count, 'deliverable')}` }),
    ]));

    if (milestone.activity_count) {
      card.append(h('div', { class: 'muted', style: 'font-size:12px;margin-bottom:6px' },
        [`Readiness ${milestone.readiness_percent}%`]));
      card.append(bar(milestone.readiness_percent,
        milestone.readiness_percent >= 80 ? 'good' : milestone.readiness_percent >= 40 ? 'watch' : 'poor'));
      card.append(h('div', { style: 'margin-top:10px' }, [stackBar(milestone.status_mix)]));

      const table = h('table', { class: 'data', style: 'margin-top:12px' }, [
        h('thead', {}, [h('tr', {}, [h('th', { text: 'Activity' }), h('th', { text: 'Type' }), h('th', { text: 'Status' })])]),
      ]);
      const body = h('tbody');
      for (const item of milestone.activities) {
        body.append(h('tr', { class: 'clickable', onClick: () => onOpen(item.id) }, [
          h('td', { text: item.label }),
          h('td', { class: 'muted', text: formatValue(item.properties?.activity_type) }),
          h('td', {}, [
            h('i', { class: 'status-dot', style: `background:${statusColour(item.properties?.status)}` }),
            formatValue(item.properties?.status),
          ]),
        ]));
      }
      table.append(body);
      card.append(table);
    } else {
      card.append(h('p', { class: 'muted', style: 'font-size:12.5px;margin:0', text: 'Nothing is committed to this gate yet.' }));
    }
    container.append(card);
  }
}

// ------------------------------------------------------------------ people
export function renderWorkload(container, people, onOpen) {
  container.replaceChildren(
    pageHead(
      'Who is doing what',
      'Activity ownership per person, split by the milestone the work reports to. Use it to spot an engineer '
      + 'carrying several commitments into the same gate.',
    ),
  );

  if (!people.length) {
    container.append(h('div', { class: 'card' }, [
      h('p', { class: 'muted', text: 'No ownership recorded. Add Person elements and link them with "is responsible for".' }),
    ]));
    return;
  }

  const maximum = Math.max(...people.map((p) => p.activity_count), 1);
  const grid = h('div', { class: 'grid grid-two' });
  for (const person of people) {
    const card = h('div', { class: 'card' });
    card.append(h('div', { class: 'card-head' }, [
      h('h3', { text: person.label }),
      h('span', { class: 'tag', text: formatValue(person.role) }),
    ]));
    card.append(h('div', { class: 'muted', style: 'font-size:12px;margin-bottom:6px' }, [
      `${person.activity_count} activities · ${person.organisation || 'no organisation recorded'}`,
    ]));
    card.append(bar((100 * person.activity_count) / maximum, person.activity_count > maximum * 0.75 ? 'watch' : 'good'));

    const milestoneEntries = Object.entries(person.by_milestone || {});
    if (milestoneEntries.length) {
      card.append(h('div', { class: 'legend-row' }, milestoneEntries.map(([label, count]) =>
        h('span', { text: `${label}: ${count}` }))));
    }
    const list = h('ul', { style: 'margin:10px 0 0;padding-left:17px;font-size:12.5px' });
    for (const activity of person.activities) {
      list.append(h('li', { class: 'clickable', style: 'cursor:pointer;margin-bottom:2px', text: activity.label, onClick: () => onOpen(activity.id) }));
    }
    card.append(list);
    grid.append(card);
  }
  container.append(grid);
}

// -------------------------------------------------------------------- KPIs
export function renderKpis(container, report, onOpen) {
  container.replaceChildren(
    pageHead(
      'Project KPIs',
      'Measured from the graph itself, not from a separate status report: every number below is a query over '
      + 'the links engineers have actually recorded, so it cannot drift from the plan.',
    ),
  );

  const score = report.health_score || {};
  container.append(h('div', { class: 'score-hero' }, [
    h('div', {}, [
      h('div', { class: `score-number ${score.band || 'unknown'}`, text: score.value === null || score.value === undefined ? '—' : score.value }),
      h('div', { class: 'muted', style: 'font-size:11px;text-align:center', text: 'of 100' }),
    ]),
    h('div', {}, [
      h('h3', { style: 'margin:0 0 4px', text: `Overall traceability health: ${score.band || 'unknown'}` }),
      h('p', { class: 'muted', style: 'margin:0;font-size:12.5px;max-width:62ch;line-height:1.55' }, [
        `Mean attainment across ${score.contributing_kpis || 0} measurable KPIs against their targets. `
        + 'A red KPI below names the specific elements responsible.',
      ]),
    ]),
  ]));

  const grid = h('div', { class: 'grid grid-kpi' });
  for (const kpi of report.kpis || []) {
    const card = h('div', { class: `kpi-card ${kpi.band}` });
    card.append(h('div', { class: 'kpi-name', text: kpi.name }));
    if (!kpi.available) {
      card.append(h('div', { class: 'kpi-value muted', text: 'n/a' }));
      card.append(h('div', { class: 'kpi-desc', text: 'The ontology does not declare the roles this KPI needs.' }));
    } else {
      card.append(h('div', { class: 'kpi-value' }, [
        String(kpi.value),
        kpi.unit ? h('span', { class: 'unit', text: kpi.unit }) : null,
      ]));
      if (kpi.target !== null && kpi.target !== undefined) {
        card.append(h('div', { class: 'kpi-target', text: `target ${kpi.direction === 'lower_better' ? '≤' : '≥'} ${kpi.target}${kpi.unit}` }));
      }
      if (kpi.description) card.append(h('div', { class: 'kpi-desc', text: kpi.description }));
      const gaps = collectGaps(kpi);
      if (gaps.length) {
        const details = h('details', { class: 'kpi-gaps' }, [h('summary', { text: `${gaps.length} to fix` })]);
        const list = h('ul');
        for (const gap of gaps.slice(0, 40)) {
          list.append(h('li', { text: `${gap.label} (${gap.type})`, onClick: () => onOpen(gap.id) }));
        }
        details.append(list);
        card.append(details);
      }
    }
    grid.append(card);
  }
  container.append(grid);

  const packages = report.breakdowns?.by_work_package || [];
  if (packages.length) {
    const card = h('div', { class: 'card', style: 'margin-top:18px' });
    card.append(h('div', { class: 'card-head' }, [h('h3', { text: 'Work package health' })]));
    const table = h('table', { class: 'data' }, [
      h('thead', {}, [h('tr', {}, [
        h('th', { text: 'Work package' }), h('th', { text: 'WBS' }), h('th', { text: 'Leader' }),
        h('th', { text: 'Activities' }), h('th', { text: 'Complete' }), h('th', { text: 'Traceability' }),
      ])]),
    ]);
    const body = h('tbody');
    for (const item of packages) {
      body.append(h('tr', { class: 'clickable', onClick: () => onOpen(item.id) }, [
        h('td', { text: item.label }),
        h('td', { class: 'mono', text: item.wbs || '—' }),
        h('td', { text: item.leader || '—' }),
        h('td', { text: item.activity_count }),
        h('td', { text: `${item.completion_percent}%` }),
        h('td', { text: `${item.traceability_percent}%` }),
      ]));
    }
    table.append(body);
    card.append(table);
    container.append(card);
  }
}

function collectGaps(kpi) {
  const detail = kpi.detail || {};
  for (const key of ['uncovered', 'unassigned', 'unanchored', 'unlinked', 'unused', 'unverified', 'elements']) {
    if (Array.isArray(detail[key])) return detail[key];
  }
  return [];
}

// ---------------------------------------------------------------- ontology
export function renderOntology(container, ontology, onReload) {
  container.replaceChildren(
    pageHead(
      `Ontology: ${ontology.title || ontology.id} v${ontology.version}`,
      'The vocabulary this project is allowed to use. It is a separate file, maintained independently of the '
      + 'application — edit it, reload, and every form, validation rule and KPI follows.',
    ),
  );

  const actions = h('div', { class: 'card' }, [
    h('div', { class: 'card-head' }, [h('h3', { text: 'Source' })]),
    h('div', { class: 'mono muted', text: ontology.source_path || '(built in)' }),
    h('div', { style: 'margin-top:10px;display:flex;gap:8px;flex-wrap:wrap' }, [
      h('button', { class: 'btn', text: 'Reload from disk', onClick: onReload }),
      h('a', { class: 'btn', href: '/api/ontology/export?format=owl', text: 'Download OWL / Turtle' }),
      h('a', { class: 'btn', href: '/api/ontology/export?format=json', text: 'Download JSON' }),
    ]),
  ]);
  container.append(actions);

  const byCategory = new Map();
  for (const spec of Object.values(ontology.node_types)) {
    if (spec.abstract) continue;
    if (!byCategory.has(spec.category)) byCategory.set(spec.category, []);
    byCategory.get(spec.category).push(spec);
  }

  for (const [category, specs] of [...byCategory].sort()) {
    const card = h('div', { class: 'card' });
    card.append(h('div', { class: 'card-head' }, [h('h3', { text: `${category} — element types` })]));
    const table = h('table', { class: 'data' }, [
      h('thead', {}, [h('tr', {}, [
        h('th', { text: 'Type' }), h('th', { text: 'Meaning' }), h('th', { text: 'Properties' }),
      ])]),
    ]);
    const body = h('tbody');
    for (const spec of specs) {
      body.append(h('tr', {}, [
        h('td', {}, [h('i', { class: 'status-dot', style: `background:${spec.color}` }), spec.label]),
        h('td', { class: 'muted', text: spec.description || '' }),
        h('td', { class: 'mono muted', text: Object.keys(spec.properties).join(', ') }),
      ]));
    }
    table.append(body);
    card.append(table);
    container.append(card);
  }

  const relations = h('div', { class: 'card' });
  relations.append(h('div', { class: 'card-head' }, [
    h('h3', { text: 'Relations' }),
    h('span', { class: 'muted', text: 'the "question" column is what drives the traceability panel' }),
  ]));
  const table = h('table', { class: 'data' }, [
    h('thead', {}, [h('tr', {}, [
      h('th', { text: 'Relation' }), h('th', { text: 'From' }), h('th', { text: 'To' }),
      h('th', { text: 'Cardinality' }), h('th', { text: 'Question' }),
    ])]),
  ]);
  const body = h('tbody');
  for (const spec of Object.values(ontology.edge_types)) {
    body.append(h('tr', {}, [
      h('td', {}, [h('i', { class: 'status-dot', style: `background:${spec.color}` }), spec.label]),
      h('td', { class: 'muted', text: spec.domain.join(', ') || 'any' }),
      h('td', { class: 'muted', text: spec.range.join(', ') || 'any' }),
      h('td', { class: 'mono muted', text: spec.cardinality }),
      h('td', { text: spec.question || '—' }),
    ]));
  }
  table.append(body);
  relations.append(table);
  container.append(relations);
}

// ------------------------------------------------------------------ system
export function renderSystem(container, { health, appKpi, validation }, actions) {
  container.replaceChildren(
    pageHead(
      'System status',
      'Storage, ontology and application performance. The latency figures are measured inside this server '
      + 'process and are also exposed at /metrics in Prometheus format.',
    ),
  );

  const storage = health.storage || {};
  const grid = h('div', { class: 'grid grid-two' });

  grid.append(card('Storage', [
    row('Backend', `${storage.scheme}:${storage.target}`),
    row('Status', storage.health?.status || 'unknown'),
    row('Writable', storage.writable ? 'yes' : 'no (read-only)'),
    row('Versioned', storage.versioned ? 'yes — every save is a new version' : 'no'),
    row('Unsaved changes', health.unsaved_changes ? 'yes' : 'no'),
    row('Last save', health.last_save ? `${health.last_save.at} — ${health.last_save.message}` : 'none this session'),
    storage.health?.error ? row('Error', storage.health.error) : null,
  ]));

  grid.append(card('Graph and engine', [
    row('Elements', health.graph.nodes),
    row('Relations', health.graph.edges),
    row('Revision', health.graph.revision),
    row('Traversal engine', health.engine.backend),
    row('Ontology', `${health.ontology.id} v${health.ontology.version}`),
    row('Strict mode', health.settings.strict ? 'on' : 'off'),
    row('Autosave', health.settings.autosave ? 'on' : 'off'),
  ]));

  const summary = appKpi.summary || {};
  grid.append(card('Application performance', [
    row('Uptime', `${Math.round(appKpi.uptime_seconds)} s`),
    row('Requests served', summary.requests_total || 0),
    row('Error rate', `${((summary.error_rate || 0) * 100).toFixed(2)} %`),
    row('Mean latency (last minute)', `${summary.avg_latency_ms_1m || 0} ms`),
    row('Slowest operation', summary.slowest_operation || '—'),
    row('Peak memory', `${appKpi.process?.max_rss_mb ?? '—'} MB`),
    row('Threads', appKpi.process?.threads ?? '—'),
  ]));

  const validationCard = card('Validation', [
    row('Result', validation.valid ? 'all elements conform to the ontology' : `${validation.error_count} problem(s)`),
    row('Checked', `${validation.node_count} elements, ${validation.edge_count} relations`),
  ]);
  if (!validation.valid) {
    const list = h('ul', { style: 'margin:8px 0 0;padding-left:17px;font-size:12.5px;color:var(--poor)' });
    for (const issue of validation.errors.slice(0, 25)) {
      list.append(h('li', { text: `${issue.element}: ${issue.message}` }));
    }
    validationCard.append(list);
  }
  grid.append(validationCard);
  container.append(grid);

  const operations = appKpi.operations || {};
  const opsCard = h('div', { class: 'card' });
  opsCard.append(h('div', { class: 'card-head' }, [h('h3', { text: 'Operation latency' })]));
  const table = h('table', { class: 'data' }, [
    h('thead', {}, [h('tr', {}, [
      h('th', { text: 'Operation' }), h('th', { text: 'Calls' }), h('th', { text: 'Errors' }),
      h('th', { text: 'p50' }), h('th', { text: 'p95' }), h('th', { text: 'p99' }), h('th', { text: 'max' }),
    ])]),
  ]);
  const body = h('tbody');
  for (const [name, stats] of Object.entries(operations)) {
    body.append(h('tr', {}, [
      h('td', { class: 'mono', text: name }),
      h('td', { text: stats.count }),
      h('td', { text: stats.errors }),
      h('td', { text: `${stats.p50_ms} ms` }),
      h('td', { text: `${stats.p95_ms} ms` }),
      h('td', { text: `${stats.p99_ms} ms` }),
      h('td', { text: `${stats.max_ms} ms` }),
    ]));
  }
  table.append(body);
  opsCard.append(table);
  container.append(opsCard);

  const exports = h('div', { class: 'card' });
  exports.append(h('div', { class: 'card-head' }, [h('h3', { text: 'Export and maintenance' })]));
  exports.append(h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' }, [
    h('a', { class: 'btn', href: '/api/export?format=json', text: 'Graph as JSON' }),
    h('a', { class: 'btn', href: '/api/export?format=ttl', text: 'Graph as Turtle/RDF' }),
    h('a', { class: 'btn', href: '/api/export?format=owl', text: 'Ontology as OWL' }),
    h('a', { class: 'btn', href: '/metrics', text: 'Prometheus metrics' }),
    h('button', { class: 'btn', text: 'Reload from storage', onClick: actions.onReloadStorage }),
    h('button', { class: 'btn btn-primary', text: 'Save now', onClick: actions.onSave }),
  ]));
  container.append(exports);
}

function card(title, rows) {
  const element = h('div', { class: 'card' });
  element.append(h('div', { class: 'card-head' }, [h('h3', { text: title })]));
  const list = h('dl', { class: 'prop-grid' });
  for (const row of rows.filter(Boolean)) list.append(...row);
  element.append(list);
  return element;
}

function row(label, value) {
  return [h('dt', { text: label }), h('dd', { text: String(value) })];
}
