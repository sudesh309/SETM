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

//: Weight is intensity, not alarm. Deliberately not the good/watch/poor
//: traffic light, which appears on the same page and means something else.
const WEIGHT_COLOURS = { high: '#4f46e5', medium: '#818cf8', low: '#94a3b8' };

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

// ------------------------------------------------------------------- tools
export function renderTools(container, tools, onOpen) {
  container.replaceChildren(
    pageHead(
      'Engineering tool chain',
      'Tools are elements in the graph, not a free-text field, so the chain can be traced the same way '
      + 'activities are: who administers each tool, what depends on it, whether its qualification is '
      + 'settled, and where data is re-keyed by hand between one tool and the next.',
    ),
  );

  if (!tools.length) {
    container.append(h('div', { class: 'card' }, [
      h('p', { class: 'muted', text: 'No tools recorded yet. Add a Tool element and link activities to it with "uses tool".' }),
    ]));
    return;
  }

  // Manual hand-overs first: they are where the model and the analysis drift apart.
  const manual = [];
  for (const tool of tools) {
    for (const hop of tool.feeds || []) {
      if (!hop.automated) manual.push({ from: tool.label, ...hop });
    }
  }
  if (manual.length) {
    const warning = h('div', { class: 'card' });
    warning.append(h('div', { class: 'card-head' }, [
      h('h3', { text: 'Manual hand-overs' }),
      h('span', { class: 'muted', text: `${manual.length} link${manual.length === 1 ? '' : 's'} in the chain are not automated` }),
    ]));
    const chain = h('div', { class: 'chain' });
    for (const hop of manual) {
      chain.append(h('div', { class: 'chain-row' }, [
        h('strong', { text: hop.from }),
        h('span', { class: 'chain-arrow', text: '→' }),
        h('strong', { text: hop.tool }),
        h('span', { class: 'muted', text: hop.format || 'format not recorded' }),
        h('span', { class: 'chain-manual', text: 'manual' }),
      ]));
    }
    warning.append(chain);
    container.append(warning);
  }

  const grid = h('div', { class: 'grid grid-two' });
  for (const tool of tools) {
    const card = h('div', { class: 'card' });
    card.append(h('div', { class: 'card-head' }, [
      h('h3', { text: tool.label }),
      h('span', { class: 'tag', text: formatValue(tool.tool_type) }),
      h('span', { class: `badge ${tool.weight}`, text: tool.weight }),
    ]));
    card.append(h('div', { class: 'muted', style: 'font-size:12px;margin-bottom:8px' }, [
      [tool.vendor, tool.version].filter(Boolean).join(' · ') || 'vendor not recorded',
    ]));

    const facts = h('dl', { class: 'prop-grid' });
    const rows = [
      ['Used by', `${tool.activity_count} activit${tool.activity_count === 1 ? 'y' : 'ies'}`],
      ['Administered by', (tool.administrators || []).join(', ') || '— nobody named'],
      ['Realises method', (tool.methods || []).join(', ') || '—'],
      ['Licences', tool.licence_count === null || tool.licence_count === undefined
        ? formatValue(tool.licence_model)
        : `${tool.licence_count} · ${formatValue(tool.licence_model)}`],
    ];
    for (const [key, value] of rows) facts.append(h('dt', { text: key }), h('dd', { text: value }));
    facts.append(
      h('dt', { text: 'Qualification' }),
      h('dd', {}, [
        h('span', { class: `badge ${tool.qualification_status}`, style: 'margin-left:0', text: formatValue(tool.qualification_status) }),
      ]),
    );
    card.append(facts);

    const hops = tool.feeds || [];
    if (hops.length) {
      card.append(h('div', { class: 'section-title', text: 'Feeds' }));
      const chain = h('div', { class: 'chain' });
      for (const hop of hops) {
        chain.append(h('div', { class: 'chain-row' }, [
          h('span', { class: 'chain-arrow', text: '→' }),
          h('span', { text: hop.tool }),
          h('span', { class: 'muted', text: hop.format || '' }),
          h('span', { class: hop.automated ? 'chain-auto' : 'chain-manual', text: hop.automated ? 'automated' : 'manual' }),
        ]));
      }
      card.append(chain);
    }

    if (tool.activities.length) {
      const list = h('ul', { style: 'margin:10px 0 0;padding-left:17px;font-size:12.5px' });
      for (const activity of tool.activities) {
        list.append(h('li', { style: 'cursor:pointer;margin-bottom:2px', text: activity.label, onClick: () => onOpen(activity.id) }));
      }
      card.append(h('div', { class: 'section-title', text: 'Activities' }), list);
    }
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

  const weights = report.breakdowns?.by_weight;
  if (weights) {
    const card = h('div', { class: 'card' });
    card.append(h('div', { class: 'card-head' }, [
      h('h3', { text: 'Weight distribution' }),
      h('span', { class: 'muted', text: 'what the programme says matters' }),
    ]));
    for (const [label, counts] of [['Elements', weights.elements], ['Relations', weights.relations]]) {
      const total = Object.values(counts).reduce((sum, n) => sum + n, 0) || 1;
      card.append(h('div', { class: 'muted', style: 'font-size:12px;margin:8px 0 4px', text: label }));
      card.append(h('div', { class: 'stack-bar' }, ['high', 'medium', 'low'].map((weight) =>
        h('span', {
          style: `width:${(100 * (counts[weight] || 0)) / total}%;background:${WEIGHT_COLOURS[weight]}`,
          title: `${weight}: ${counts[weight] || 0}`,
        }))));
      card.append(h('div', { class: 'legend-row' }, ['high', 'medium', 'low'].map((weight) =>
        h('span', {}, [
          h('i', { class: 'status-dot', style: `background:${WEIGHT_COLOURS[weight]}` }),
          `${weight} ${counts[weight] || 0}`,
        ]))));
    }
    container.append(card);
  }

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
          const weight = gap.properties?.weight;
          list.append(h('li', { onClick: () => onOpen(gap.id) }, [
            gap.label,
            h('span', { class: 'muted', style: 'font-size:11px', text: ` ${gap.type}` }),
            weight && weight !== 'high' ? h('span', { class: `badge ${weight}`, text: weight }) : null,
          ]));
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

// ---------------------------------------------------------------- settings
// Generated from the field metadata the API sends, the same way element forms
// are generated from the ontology: adding a setting in config.py makes a row
// appear here with no change to this file.

const SOURCE_EXPLANATION = {
  default: 'the built-in default',
  file: 'the config file',
  environment: 'an environment variable',
  argument: 'a command-line flag',
  ui: 'edited here, not yet saved to the file',
};

export function renderSettings(container, data, actions, initialStatus = '') {
  const draft = structuredClone(data.values);
  container.replaceChildren();

  const page = h('div', { class: 'settings-page' });
  page.append(
    h('div', { class: 'page-head' }, [
      h('h1', { text: 'Settings' }),
      h('p', {}, [
        'Everything the tool reads at startup. A value can come from four places — the built-in '
        + 'default, the config file, an environment variable, or a command-line flag — and the tag '
        + 'beside each field says which one won.',
      ]),
    ]),
  );

  const configCard = h('div', { class: 'card' });
  configCard.append(h('div', { class: 'card-head' }, [
    h('h3', { text: 'Config file' }),
    h('span', { class: 'tag', text: data.config_exists ? 'exists' : 'not written yet' }),
  ]));
  configCard.append(h('div', { class: 'mono muted', text: data.config_path }));
  configCard.append(h('p', { class: 'setting-help' }, [
    'Saving writes this file so the settings survive a restart. Credentials are left out unless '
    + 'you tick the box below — a token in a file outlives the session that needed it.',
  ]));
  if (data.shadowed_by_environment.length) {
    configCard.append(h('div', { class: 'setting-warn' }, [
      `Set in the environment and therefore not changeable here for the next start: `
      + data.shadowed_by_environment.join(', ')
      + '. Unset the variable, or change it where it is set.',
    ]));
  }
  page.append(configCard);

  // One card per group, in the order the API listed them.
  const groups = [];
  for (const field of data.fields) {
    let group = groups.find((g) => g.name === field.group);
    if (!group) groups.push((group = { name: field.group, fields: [] }));
    group.fields.push(field);
  }

  const inputs = new Map();
  for (const group of groups) {
    const card = h('div', { class: 'card' });
    card.append(h('div', { class: 'card-head' }, [h('h3', { text: group.name })]));

    for (const field of group.fields) {
      if (field.type === 'number_map') {
        card.append(kpiTargets(field, data, draft));
        continue;
      }
      const control = settingControl(field, draft, data);
      inputs.set(field.name, control);
      card.append(settingRow(field, data, control));
    }

    if (group.name === 'Storage') card.append(storageProbe(draft, actions));
    page.append(card);
  }

  // -- actions
  const persist = h('input', { type: 'checkbox', id: 'persist-settings', checked: true });
  const secrets = h('input', { type: 'checkbox', id: 'persist-secrets' });
  // Carried across the re-render a save triggers, so the confirmation survives it.
  const status = h('span', { class: 'settings-status', text: initialStatus });

  const save = h('button', {
    class: 'btn btn-primary',
    text: 'Save settings',
    onClick: async () => {
      save.disabled = true;
      status.textContent = 'Saving…';
      try {
        const result = await actions.onSave({
          values: draft,
          persist: persist.checked,
          include_secrets: secrets.checked,
        });
        const message = describeResult(result);
        status.textContent = message;
        if (result.needs_reopen.length) await actions.onOfferReopen(result);
        else await actions.onReload(message);
      } catch (error) {
        status.textContent = error.message;
      } finally {
        save.disabled = false;
      }
    },
  });

  page.append(h('div', { class: 'settings-actions' }, [
    save,
    h('label', { class: 'inline', style: 'margin:0' }, [persist, h('span', { text: 'Write to the config file' })]),
    h('label', { class: 'inline', style: 'margin:0' }, [secrets, h('span', { text: 'Include credentials' })]),
    h('span', { class: 'spacer' }),
    status,
  ]));

  container.append(page);
}

function describeResult(result) {
  if (!result.changed.length) return 'No changes to save.';
  const parts = [`Updated ${result.changed.join(', ')}`];
  if (result.saved_to) parts.push(`written to ${result.saved_to}`);
  if (result.needs_restart.length) parts.push(`restart to apply ${result.needs_restart.join(', ')}`);
  return `${parts.join(' · ')}.`;
}

function settingRow(field, data, control) {
  const source = data.sources[field.name] || 'default';
  const meta = h('div', { class: 'setting-meta' }, [
    h('span', { class: `tag-source ${source}`, title: `Set by ${SOURCE_EXPLANATION[source]}`, text: source }),
    field.restart_required ? h('span', { class: 'tag-source', text: 'restart' }) : null,
    field.reopens_workspace ? h('span', { class: 'tag-source', text: 'reopens project' }) : null,
    field.secret ? h('span', { class: 'tag-source', text: 'secret' }) : null,
  ]);

  const shadowed = data.shadowed_by_environment.includes(field.name) && source !== 'environment';
  return h('div', { class: 'setting-row' }, [
    h('div', { class: 'setting-label' }, [
      h('strong', { text: field.label }),
      meta,
      field.env_var ? h('div', { class: 'setting-help mono', text: field.env_var }) : null,
    ]),
    h('div', { class: 'setting-control' }, [
      control,
      field.description ? h('div', { class: 'setting-help', text: field.description }) : null,
      shadowed
        ? h('div', { class: 'setting-warn', text: `${field.env_var} is set, and will override this on the next start.` })
        : null,
    ]),
  ]);
}

function settingControl(field, draft, data) {
  const value = draft[field.name];

  if (field.type === 'boolean') {
    const input = h('input', { type: 'checkbox', checked: value === true });
    input.addEventListener('change', () => { draft[field.name] = input.checked; });
    return h('label', { class: 'inline', style: 'margin:0' }, [
      input, h('span', { text: value === true ? 'on' : 'off' }),
    ]);
  }

  if (field.type === 'list') {
    const input = h('textarea', { placeholder: field.placeholder, text: (value || []).join('\n') });
    input.addEventListener('input', () => {
      draft[field.name] = input.value.split('\n').map((v) => v.trim()).filter(Boolean);
    });
    return input;
  }

  if (field.type === 'mapping') {
    const input = h('textarea', {
      placeholder: `${field.placeholder}=main`,
      text: Object.entries(value || {}).map(([k, v]) => `${k}=${v}`).join('\n'),
    });
    input.addEventListener('input', () => {
      const next = {};
      for (const line of input.value.split('\n')) {
        const [key, ...rest] = line.split('=');
        if (key.trim() && rest.length) next[key.trim()] = rest.join('=').trim();
      }
      draft[field.name] = next;
    });
    return input;
  }

  const input = h('input', {
    // A secret arrives as a placeholder, never as its real value; typing over
    // it sets a new one, leaving it alone keeps what the server already has.
    type: field.secret ? 'password' : field.type === 'integer' ? 'number' : 'text',
    value: value ?? '',
    placeholder: field.placeholder || String(data.defaults[field.name] ?? ''),
  });
  input.addEventListener('input', () => {
    draft[field.name] = field.type === 'integer' ? Number(input.value) : input.value;
  });
  return input;
}

function kpiTargets(field, data, draft) {
  const wrapper = h('div', { style: 'padding:6px 0' });
  wrapper.append(h('p', { class: 'setting-help', style: 'margin-bottom:10px', text: field.description }));
  const grid = h('div', { class: 'kpi-target-grid' });

  for (const kpi of data.kpi_catalogue) {
    const current = (draft.kpi_targets || {})[kpi.id];
    const input = h('input', {
      type: 'number', step: 'any', min: '0',
      value: current ?? '',
      placeholder: String(kpi.default_target),
      title: `Default ${kpi.default_target}${kpi.unit}`,
    });
    input.addEventListener('input', () => {
      const targets = { ...(draft.kpi_targets || {}) };
      if (input.value === '') delete targets[kpi.id];
      else targets[kpi.id] = Number(input.value);
      draft.kpi_targets = targets;
    });
    grid.append(h('div', { class: 'kpi-target' }, [
      h('label', { text: kpi.name }),
      input,
      h('span', { class: 'unit', text: kpi.unit }),
    ]));
  }
  wrapper.append(grid);
  return wrapper;
}

function storageProbe(draft, actions) {
  const result = h('div');
  const button = h('button', {
    class: 'btn',
    text: 'Test connection',
    onClick: async () => {
      button.disabled = true;
      result.replaceChildren(h('div', { class: 'setting-help', text: 'Probing…' }));
      try {
        const probe = await actions.onTestStorage({
          storage: draft.storage,
          storage_options: draft.storage_options,
        });
        const card = h('div', { class: `probe ${probe.ok ? 'ok' : 'bad'}` });
        card.append(h('div', {}, [h('strong', { text: probe.hint })]));
        card.append(h('div', { class: 'mono muted', style: 'margin-top:4px', text: probe.target }));
        if (probe.error) card.append(h('div', { style: 'margin-top:4px', text: probe.error.message }));
        else if (probe.health?.error) card.append(h('div', { style: 'margin-top:4px', text: probe.health.error }));
        result.replaceChildren(card);
      } catch (error) {
        result.replaceChildren(h('div', { class: 'probe bad', text: error.message }));
      } finally {
        button.disabled = false;
      }
    },
  });
  return h('div', { style: 'padding-top:12px' }, [
    button,
    h('span', { class: 'setting-help', style: 'margin-left:10px', text: 'Checks the target is reachable without switching to it.' }),
    result,
  ]);
}
