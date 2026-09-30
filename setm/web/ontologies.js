// Ontologies: the project's own ontology, the master, and comparing and merging
// between them.
//
// A project keeps its own copy of the element types and relations it uses,
// taken from the master when it was created, plus any it added itself. The
// master only changes when something is copied into it ("Copy to master"), and
// the project only takes master changes when asked ("Copy to project").

import { h } from './forms.js';
import { pageHead } from './views.js';

export const CATEGORIES = ['Why', 'What', 'How', 'Who', 'When'];
const QUESTIONS = ['who', 'when', 'why', 'how', 'what', 'where'];
const CARDINALITIES = [
  ['many_to_many', 'Many to many'],
  ['many_to_one', 'Many to one'],
  ['one_to_many', 'One to many'],
  ['one_to_one', 'One to one'],
];
const DATATYPES = [
  ['string', 'Text'], ['text', 'Long text'], ['number', 'Number'], ['integer', 'Whole number'],
  ['boolean', 'Yes / no'], ['enum', 'Choice from a list'], ['date', 'Date'], ['url', 'Link'],
];
const STATUS_LABEL = {
  same: 'from master',
  project_only: 'project only',
  master_only: 'master only',
  differs: 'changed',
};

// --------------------------------------------------------------------------- //
// Forms: a new (or changed) element type, a new (or changed) relation
// --------------------------------------------------------------------------- //

function field(label, control, help) {
  return h('div', { class: 'form-field' }, [
    h('label', { text: label }),
    control,
    help ? h('div', { class: 'help', text: help }) : null,
  ]);
}

function select(name, options, value) {
  return h('select', { name }, options.map(([v, label]) => h('option', { value: v, text: label, selected: v === value })));
}

/** Rows of new properties: label, type, required, and the choices for a list. */
function propertyRows() {
  const rows = h('div', { class: 'prop-rows' });
  const add = () => {
    const values = h('input', { type: 'text', name: 'values', placeholder: 'choices, comma separated', class: 'invisible' });
    const type = select('type', DATATYPES, 'string');
    type.addEventListener('change', () => values.classList.toggle('invisible', type.value !== 'enum'));
    const row = h('div', { class: 'prop-row' }, [
      h('input', { type: 'text', name: 'label', placeholder: 'Property name, e.g. Location' }),
      type,
      h('label', { class: 'inline' }, [h('input', { type: 'checkbox', name: 'required' }), ' required']),
      values,
      h('button', { class: 'btn btn-icon', type: 'button', text: '×', title: 'Remove', onClick: () => row.remove() }),
    ]);
    rows.append(row);
  };
  const element = h('div', {}, [
    rows,
    h('button', { class: 'btn btn-small', type: 'button', text: '+ Property', onClick: add }),
  ]);
  return {
    element,
    read: () => [...rows.querySelectorAll('.prop-row')].map((row) => ({
      label: row.querySelector('[name="label"]').value.trim(),
      type: row.querySelector('[name="type"]').value,
      required: row.querySelector('[name="required"]').checked,
      values: row.querySelector('[name="values"]').value,
    })).filter((p) => p.label),
  };
}

/** The form for an element type. ``existing`` (a spec) edits one. */
export function elementTypeForm(existing = null) {
  const label = h('input', { type: 'text', name: 'label', value: existing?.label || '', placeholder: 'e.g. Test rig' });
  const category = select('category', CATEGORIES.map((c) => [c, c]), existing?.category || 'What');
  const colour = h('input', { type: 'color', name: 'color', value: existing?.color || '#0ea5e9' });
  const description = h('textarea', { name: 'description', rows: 2 }, [existing?.description || '']);
  const properties = propertyRows();
  const current = existing
    ? Object.values(existing.properties || {}).map((p) => p.label).join(', ')
    : 'Name, description and weight come with every element type.';
  const element = h('div', { class: 'type-form' }, [
    h('div', { class: 'np-grid' }, [
      field('Name', label),
      field('Answers the question', category, 'Which column of the Dashboard it appears in.'),
    ]),
    h('div', { class: 'np-grid' }, [field('Colour', colour), field('Description', description)]),
    field(existing ? 'Add properties' : 'Properties', properties.element, existing ? `Has: ${current}` : current),
  ]);
  return {
    element,
    read: () => ({
      label: label.value.trim(),
      category: category.value,
      color: colour.value,
      description: description.value.trim(),
      properties: properties.read(),
    }),
  };
}

/** The form for a relation between element types. ``types`` are {name, label}. */
export function relationForm(types, existing = null) {
  const label = h('input', { type: 'text', name: 'label', value: existing?.label || '', placeholder: 'e.g. tested on' });
  const checklist = (name, chosen) => h('div', { class: 'check-grid', 'data-end': name }, types.map((t) => h('label', { class: 'inline' }, [
    h('input', { type: 'checkbox', name, value: t.name, checked: (chosen || []).includes(t.name) }),
    ` ${t.label}`,
  ])));
  const from = checklist('domain', existing?.domain);
  const to = checklist('range', existing?.range);
  const question = select('question', [['', '—'], ...QUESTIONS.map((q) => [q, q])], existing?.question || 'what');
  const cardinality = select('cardinality', CARDINALITIES, existing?.cardinality || 'many_to_many');
  const inverse = h('input', { type: 'text', name: 'inverse_label', value: existing?.inverse_label || '', placeholder: 'e.g. is the rig for' });
  const description = h('textarea', { name: 'description', rows: 2 }, [existing?.description || '']);
  const element = h('div', { class: 'type-form' }, [
    h('div', { class: 'np-grid' }, [field('Name', label), field('Read backwards', inverse)]),
    field('From', from, 'Which element types this relation can start from.'),
    field('To', to, 'Which element types it can point to.'),
    h('div', { class: 'np-grid' }, [
      field('Answers the question', question, 'Groups it in an element\'s traceability: who, when, why, how, what.'),
      field('How many', cardinality),
    ]),
    field('Description', description),
  ]);
  const ticked = (box) => [...box.querySelectorAll('input:checked')].map((i) => i.value);
  return {
    element,
    read: () => ({
      label: label.value.trim(),
      inverse_label: inverse.value.trim(),
      domain: ticked(from),
      range: ticked(to),
      question: question.value,
      cardinality: cardinality.value,
      description: description.value.trim(),
    }),
  };
}

// --------------------------------------------------------------------------- //
// The page
// --------------------------------------------------------------------------- //

/**
 * @param data     {summary, project (ontology), compare}
 * @param actions  {tab, onTab(tab), loadMaster(), onAddType(), onAddRelation(), onEditType(name),
 *                  onEditRelation(name), onRemove(kind, name), onAddFromMaster(), onMerge(direction, items),
 *                  onReloadMaster(), downloadLink(href, text)}
 */
export async function renderOntologies(container, data, actions) {
  const tab = actions.tab || 'project';
  const tabs = h('div', { class: 'seg-group onto-tabs' }, [
    ['project', 'Project ontology'], ['master', 'Master ontology'], ['compare', 'Compare & merge'],
  ].map(([name, label]) => h('button', {
    class: `seg${tab === name ? ' on' : ''}`, 'data-tab': name, text: label, onClick: () => actions.onTab(name),
  })));
  const summary = data.summary;
  const counts = data.compare.summary;
  container.replaceChildren(
    pageHead('Ontologies', 'Two vocabularies. The master is the organisation\'s, shared by every project. '
      + 'This project keeps its own copy of what it uses, plus anything it added -- and the two are kept '
      + 'in step only when you choose to, by comparing and copying either way.'),
    h('div', { class: 'onto-summary' }, [
      summaryCard('This project', `${summary.project.element_types} element types · ${summary.project.relations} relations`,
        summary.project.derived_from ? `copied from master v${summary.project.derived_from.version}` : 'its own copy'),
      summaryCard('Master', `${summary.master.element_types} element types · ${summary.master.relations} relations`,
        `v${summary.master.version} · ${summary.master.saved ? summary.master.path : 'not changed yet (the shipped ontology)'}`),
      summaryCard('Differences', `${counts.project_only} project only · ${counts.differs} changed`,
        `${counts.master_only} more in the master`, counts.project_only + counts.differs ? 'attention' : ''),
    ]),
    tabs,
  );
  if (tab === 'project') container.append(projectTab(data, actions));
  else if (tab === 'master') container.append(await masterTab(actions));
  else container.append(compareTab(data, actions));
}

function summaryCard(title, main, sub, tone = '') {
  return h('div', { class: `card onto-card ${tone}` }, [
    h('div', { class: 'muted', text: title }),
    h('div', { class: 'onto-card-main', text: main }),
    h('div', { class: 'muted onto-card-sub', text: sub }),
  ]);
}

function statusBadge(status) {
  return h('span', { class: `status-badge st-${status}`, text: STATUS_LABEL[status] || status });
}

function projectTab(data, actions) {
  const ontology = data.project;
  const statusOf = new Map(data.compare.items.map((i) => [`${i.kind}:${i.name}`, i.status]));
  const wrap = h('div');
  wrap.append(h('div', { class: 'toolbar' }, [
    h('button', { class: 'btn btn-primary', id: 'btn-add-type', text: '+ Element type', onClick: actions.onAddType }),
    h('button', { class: 'btn btn-primary', id: 'btn-add-relation', text: '+ Relation', onClick: actions.onAddRelation }),
    h('button', { class: 'btn', id: 'btn-add-from-master', text: 'Add from master…', onClick: actions.onAddFromMaster }),
    h('span', { class: 'spacer' }),
    actions.downloadLink('/api/ontology/export?format=json', 'Download JSON'),
  ]));

  const types = Object.values(ontology.node_types).filter((t) => !t.abstract);
  const typeTable = h('table', { class: 'data onto-table' }, [
    h('thead', {}, [h('tr', {}, ['Element type', 'Question', 'Properties', 'Status', ''].map((t) => h('th', { text: t })))]),
  ]);
  const typeBody = h('tbody');
  types.sort((a, b) => CATEGORIES.indexOf(a.category) - CATEGORIES.indexOf(b.category) || a.label.localeCompare(b.label));
  for (const spec of types) {
    typeBody.append(h('tr', { 'data-type': spec.name }, [
      h('td', {}, [h('i', { class: 'status-dot', style: `background:${spec.color}` }), spec.label,
        h('div', { class: 'muted mono', text: spec.name })]),
      h('td', { text: spec.category }),
      h('td', { class: 'muted', text: Object.keys(spec.properties || {}).length }),
      h('td', {}, [statusBadge(statusOf.get(`element_type:${spec.name}`) || 'same')]),
      h('td', { class: 'row-actions' }, [
        h('button', { class: 'btn btn-small', text: 'Edit', onClick: () => actions.onEditType(spec.name) }),
        h('button', { class: 'btn btn-small btn-danger', text: 'Remove', onClick: () => actions.onRemove('element-types', spec.name, spec.label) }),
      ]),
    ]));
  }
  typeTable.append(typeBody);
  wrap.append(h('div', { class: 'card' }, [h('div', { class: 'card-head' }, [h('h3', { text: `Element types (${types.length})` })]), typeTable]));

  const relations = Object.values(ontology.edge_types);
  const label = (name) => ontology.node_types[name]?.label || name;
  const relTable = h('table', { class: 'data onto-table' }, [
    h('thead', {}, [h('tr', {}, ['Relation', 'From → to', 'Question', 'Status', ''].map((t) => h('th', { text: t })))]),
  ]);
  const relBody = h('tbody');
  for (const spec of relations.sort((a, b) => a.label.localeCompare(b.label))) {
    relBody.append(h('tr', { 'data-relation': spec.name }, [
      h('td', {}, [spec.label, h('div', { class: 'muted mono', text: spec.name })]),
      h('td', { class: 'muted', text: `${spec.domain.map(label).join(', ') || 'any'} → ${spec.range.map(label).join(', ') || 'any'}` }),
      h('td', { text: spec.question || '—' }),
      h('td', {}, [statusBadge(statusOf.get(`relation:${spec.name}`) || 'same')]),
      h('td', { class: 'row-actions' }, [
        h('button', { class: 'btn btn-small', text: 'Edit', onClick: () => actions.onEditRelation(spec.name) }),
        h('button', { class: 'btn btn-small btn-danger', text: 'Remove', onClick: () => actions.onRemove('relations', spec.name, spec.label) }),
      ]),
    ]));
  }
  relTable.append(relBody);
  wrap.append(h('div', { class: 'card' }, [h('div', { class: 'card-head' }, [h('h3', { text: `Relations (${relations.length})` })]), relTable]));
  return wrap;
}

async function masterTab(actions) {
  const master = await actions.loadMaster();
  const wrap = h('div');
  const summary = master.summary;
  wrap.append(h('div', { class: 'card' }, [
    h('div', { class: 'card-head' }, [
      h('h3', { text: `${master.title} v${master.version}` }),
      h('div', { style: 'display:flex;gap:8px' }, [
        h('button', { class: 'btn', id: 'btn-reload-master', text: 'Reload from file', onClick: actions.onReloadMaster }),
        actions.downloadLink('/api/ontology/export?format=json&which=master', 'Download master (JSON)'),
      ]),
    ]),
    h('p', { class: 'muted', text: summary.saved
      ? `Kept in ${summary.path}. Copy element types and relations here from a project on the Compare & merge tab.`
      : `Not changed yet: this is the shipped ontology (${summary.template}). The first time you copy something to the master, it is saved to ${summary.path}.` }),
  ]));
  const types = Object.values(master.node_types).filter((t) => !t.abstract);
  const byCategory = new Map(CATEGORIES.map((c) => [c, []]));
  for (const spec of types) {
    if (!byCategory.has(spec.category)) byCategory.set(spec.category, []);
    byCategory.get(spec.category).push(spec);
  }
  const grid = h('div', { class: 'master-grid' });
  for (const [category, specs] of byCategory) {
    if (!specs.length) continue;
    grid.append(h('div', { class: 'card' }, [
      h('div', { class: 'card-head' }, [h('h3', { text: `${category} (${specs.length})` })]),
      ...specs.map((spec) => h('div', { class: 'master-type', title: spec.description || '' }, [
        h('i', { class: 'status-dot', style: `background:${spec.color}` }), spec.label,
      ])),
    ]));
  }
  wrap.append(grid);
  const rels = Object.values(master.edge_types);
  wrap.append(h('div', { class: 'card' }, [
    h('div', { class: 'card-head' }, [h('h3', { text: `Relations (${rels.length})` })]),
    h('div', { class: 'master-rels' }, rels.map((spec) => h('div', { class: 'master-type' }, [
      h('strong', { text: spec.label }),
      h('span', { class: 'muted', text: ` ${spec.domain.join(', ')} → ${spec.range.join(', ')}` }),
    ]))),
  ]));
  return wrap;
}

function describeChanges(item) {
  const lines = [];
  for (const change of item.changes || []) {
    if (change.field === 'domain' || change.field === 'range') {
      const side = change.field === 'domain' ? 'from' : 'to';
      lines.push(change.project_adds?.length
        ? `project adds "${side}": ${change.project_adds.join(', ')}`
        : `"${side}" differs`);
    } else {
      lines.push(`${change.field}: project "${formatShort(change.project)}", master "${formatShort(change.master)}"`);
    }
  }
  for (const p of item.property_changes || []) {
    if (p.change === 'only_in_project') lines.push(`+ property ${p.property} (project only)`);
    else if (p.change === 'only_in_master') lines.push(`property ${p.property} only in master`);
    else lines.push(`property ${p.property} differs (${p.fields.join(', ')})`);
  }
  return lines;
}

function formatShort(value) {
  const text = Array.isArray(value) ? value.join(', ') : String(value ?? '');
  return text.length > 40 ? `${text.slice(0, 40)}…` : text;
}

function compareTab(data, actions) {
  const wrap = h('div');
  const showAll = actions.compareShowAll;
  const items = data.compare.items.filter((i) => !i.abstract && (showAll || i.status !== 'same'));
  const selected = new Set();
  const toMaster = h('button', { class: 'btn btn-primary', id: 'btn-to-master', text: 'Copy selected to master →', disabled: true });
  const toProject = h('button', { class: 'btn btn-primary', id: 'btn-to-project', text: '← Copy selected to project', disabled: true });
  const hint = h('span', { class: 'muted', text: 'Tick what to copy. Anything a relation needs comes with it.' });
  const refreshButtons = () => {
    const chosen = items.filter((i) => selected.has(`${i.kind}:${i.name}`));
    toMaster.disabled = !chosen.length || chosen.some((i) => i.status === 'master_only');
    toProject.disabled = !chosen.length || chosen.some((i) => i.status === 'project_only');
    hint.textContent = !chosen.length ? 'Tick what to copy. Anything a relation needs comes with it.'
      : toMaster.disabled && toProject.disabled ? 'Pick items going the same way: project-only ones go to the master, master-only ones to the project.'
        : `${chosen.length} selected.`;
  };
  const pick = () => items.filter((i) => selected.has(`${i.kind}:${i.name}`)).map((i) => ({ kind: i.kind, name: i.name }));
  toMaster.addEventListener('click', () => actions.onMerge('to_master', pick()));
  toProject.addEventListener('click', () => actions.onMerge('to_project', pick()));

  wrap.append(h('div', { class: 'toolbar' }, [
    toProject, toMaster, hint, h('span', { class: 'spacer' }),
    h('label', { class: 'inline' }, [
      h('input', { type: 'checkbox', id: 'compare-show-all', checked: showAll, onChange: (e) => actions.onCompareShowAll(e.target.checked) }),
      ' Show identical ones too',
    ]),
  ]));

  if (!items.length) {
    wrap.append(h('div', { class: 'card empty-state' }, [
      h('h3', { text: 'The project and the master agree' }),
      h('p', { text: 'Nothing this project added or changed is missing from the master.' }),
    ]));
    return wrap;
  }
  const table = h('table', { class: 'data onto-table compare-table' }, [
    h('thead', {}, [h('tr', {}, ['', 'Kind', 'Name', 'Where', 'What differs'].map((t) => h('th', { text: t })))]),
  ]);
  const body = h('tbody');
  const order = { project_only: 0, differs: 1, master_only: 2, same: 3 };
  items.sort((a, b) => order[a.status] - order[b.status] || a.kind.localeCompare(b.kind) || a.label.localeCompare(b.label));
  for (const item of items) {
    const key = `${item.kind}:${item.name}`;
    const box = h('input', {
      type: 'checkbox', 'data-key': key, disabled: item.status === 'same',
      onChange: (e) => { if (e.target.checked) selected.add(key); else selected.delete(key); refreshButtons(); },
    });
    const changes = describeChanges(item);
    body.append(h('tr', { 'data-key': key, class: `row-${item.status}` }, [
      h('td', {}, [box]),
      h('td', { class: 'muted', text: item.kind === 'relation' ? 'Relation' : 'Element type' }),
      h('td', {}, [item.label, h('div', { class: 'muted mono', text: item.name })]),
      h('td', {}, [statusBadge(item.status)]),
      h('td', { class: 'muted' }, changes.length ? [h('ul', { class: 'change-list' }, changes.map((c) => h('li', { text: c })))]
        : [item.kind === 'relation' ? `${item.domain.join(', ')} → ${item.range.join(', ')}` : item.category || '']),
    ]));
  }
  table.append(body);
  wrap.append(h('div', { class: 'card' }, [table]));
  return wrap;
}
