// Application controller: state, wiring and the inspector.

import { api, download, setToken } from './api.js';
import { MapView } from './map.js';
import { buildPropertyForm, formatValue, h, readPropertyForm } from './forms.js';
import {
  downloadLink, renderKpis, renderMilestones, renderSettings, renderSystem, renderTools, renderWorkload,
} from './views.js';
import { renderOverview, topRisks } from './overview.js';
import { buildProjectWizard, renderHome } from './home.js';
import { elementTypeForm, relationForm, renderOntologies } from './ontologies.js';

const state = {
  ontology: null,
  graph: { nodes: [], edges: [] },
  nodesById: new Map(),
  selectedId: null,
  hiddenNodeTypes: new Set(),
  hiddenEdgeTypes: new Set(),
  hiddenWeights: new Set(),
  search: '',
  view: 'overview',
  dirty: false,
  projectOpen: false,
  ontologyTab: 'project',
  compareShowAll: false,
};

const el = (id) => document.getElementById(id);
let mapView;

/** Views that make sense with no project open. */
const WITHOUT_PROJECT = new Set(['home', 'settings']);

// --------------------------------------------------------------------- init
async function boot() {
  restoreTheme();
  window.addEventListener('setm:error', (event) => toast(event.detail, 'error'));
  wireChrome();
  mapView = new MapView(el('map'), {
    onSelect: (id) => selectNode(id),
    onClear: () => selectNode(null),
  });

  try {
    const health = await refreshHeader();
    if (health.project_open) {
      await loadProject();
      await switchView('overview');
    } else {
      await switchView('home');
    }
  } catch (error) {
    toast(error.message, 'error');
  }
}

/** Read everything the page works from for the open project. */
async function loadProject() {
  state.ontology = await api.ontology();
  await refreshGraph();
  buildFilters();
}

async function refreshHeader() {
  const health = await api.health();
  state.projectOpen = Boolean(health.project_open);
  document.body.classList.toggle('no-project', !state.projectOpen);
  state.serverRevision = health.graph?.revision;
  if (!state.projectOpen) {
    el('project-name').textContent = 'No project open';
    el('project-meta').textContent = 'Create, open or load one';
    setDirty(false);
    return health;
  }
  const project = await api.project();
  el('project-name').textContent = project.name || 'Untitled project';
  el('project-meta').textContent = [
    project.programme,
    project.phase ? `phase ${project.phase}` : '',
    `${health.graph.nodes} elements`,
    `${health.storage.scheme} storage`,
  ].filter(Boolean).join(' · ');
  setDirty(health.unsaved_changes);
  return health;
}

async function refreshGraph() {
  const payload = await api.graph({ limit: 8000 });
  state.graph = payload;
  state.nodesById = new Map(payload.nodes.map((n) => [n.id, n]));
  applyFilters();
  updateStats();
}

// ------------------------------------------------------------------ filters
function buildFilters() {
  const counts = new Map();
  for (const node of state.graph.nodes) counts.set(node.type, (counts.get(node.type) || 0) + 1);

  const typeContainer = el('type-filters');
  typeContainer.replaceChildren();
  const types = Object.values(state.ontology.node_types).filter((t) => !t.abstract);
  types.sort((a, b) => (a.category || '').localeCompare(b.category) || a.label.localeCompare(b.label));
  for (const spec of types) {
    typeContainer.append(filterRow(spec.name, spec.label, spec.color, counts.get(spec.name) || 0, state.hiddenNodeTypes));
  }

  const edgeCounts = new Map();
  for (const edge of state.graph.edges) edgeCounts.set(edge.type, (edgeCounts.get(edge.type) || 0) + 1);

  const questions = [...new Set(Object.values(state.ontology.edge_types).map((e) => e.question).filter(Boolean))];
  const questionContainer = el('question-filters');
  questionContainer.replaceChildren();
  for (const question of questions) {
    questionContainer.append(h('button', {
      class: 'chip on',
      'data-question': question,
      text: question,
      onClick: (event) => toggleQuestion(question, event.currentTarget),
    }));
  }

  const edgeContainer = el('edge-filters');
  edgeContainer.replaceChildren();
  for (const spec of Object.values(state.ontology.edge_types)) {
    edgeContainer.append(filterRow(spec.name, spec.label, spec.color, edgeCounts.get(spec.name) || 0, state.hiddenEdgeTypes));
  }

  const weightCounts = new Map();
  for (const node of state.graph.nodes) {
    const weight = weightOf(node);
    weightCounts.set(weight, (weightCounts.get(weight) || 0) + 1);
  }
  const weightContainer = el('weight-filters');
  weightContainer.replaceChildren();
  for (const weight of WEIGHTS) {
    const chip = h('button', {
      class: `chip weight-${weight}${state.hiddenWeights.has(weight) ? '' : ' on'}`,
      text: `${weight} ${weightCounts.get(weight) || 0}`,
      onClick: () => {
        if (state.hiddenWeights.has(weight)) state.hiddenWeights.delete(weight);
        else state.hiddenWeights.add(weight);
        chip.classList.toggle('on');
        applyFilters();
      },
    });
    weightContainer.append(chip);
  }
}

const WEIGHTS = ['high', 'medium', 'low'];

/** An element with no weight recorded counts as high: that is the ontology default. */
function weightOf(element) {
  const value = element.properties?.weight;
  return WEIGHTS.includes(value) ? value : 'high';
}

function filterRow(name, label, colour, count, hiddenSet) {
  const row = h('div', { class: `filter-row${hiddenSet.has(name) ? ' off' : ''}`, 'data-name': name }, [
    h('i', { class: 'swatch', style: `background:${colour}` }),
    h('span', { text: label }),
    h('span', { class: 'filter-count', text: count }),
  ]);
  row.addEventListener('click', () => {
    if (hiddenSet.has(name)) hiddenSet.delete(name); else hiddenSet.add(name);
    row.classList.toggle('off');
    applyFilters();
  });
  return row;
}

function toggleQuestion(question, button) {
  const specs = Object.values(state.ontology.edge_types).filter((e) => e.question === question);
  const turningOff = button.classList.contains('on');
  for (const spec of specs) {
    if (turningOff) state.hiddenEdgeTypes.add(spec.name);
    else state.hiddenEdgeTypes.delete(spec.name);
  }
  button.classList.toggle('on');
  for (const row of el('edge-filters').children) {
    row.classList.toggle('off', state.hiddenEdgeTypes.has(row.dataset.name));
  }
  applyFilters();
}

function applyFilters() {
  const needle = state.search.trim().toLowerCase();
  const visibleNodes = state.graph.nodes.filter((node) => {
    if (state.hiddenNodeTypes.has(node.type)) return false;
    if (state.hiddenWeights.has(weightOf(node))) return false;
    if (!needle) return true;
    const haystack = `${node.id} ${node.label} ${Object.values(node.properties || {}).join(' ')}`.toLowerCase();
    return haystack.includes(needle);
  });
  const visibleIds = new Set(visibleNodes.map((n) => n.id));
  const visibleEdges = state.graph.edges.filter(
    (edge) => !state.hiddenEdgeTypes.has(edge.type)
      && !state.hiddenWeights.has(weightOf(edge))
      && visibleIds.has(edge.source) && visibleIds.has(edge.target),
  );

  const decorated = visibleNodes.map((node) => {
    const spec = state.ontology.node_types[node.type] || {};
    return {
      id: node.id,
      label: node.label,
      type: node.type,
      type_label: spec.label || node.type,
      category: spec.category || 'Other',
      color: spec.color || node.color,
      status: node.properties?.status || node.properties?.risk_status || '',
    };
  });
  const decoratedEdges = visibleEdges.map((edge) => {
    const spec = state.ontology.edge_types[edge.type] || {};
    return { id: edge.id, source: edge.source, target: edge.target, label: spec.label || edge.type, color: spec.color };
  });

  mapView.setData(decorated, decoratedEdges, state.graph.nodes.length);
  updateStats(visibleNodes.length, visibleEdges.length);
}

function updateStats(nodeCount, edgeCount) {
  el('graph-stats').replaceChildren(
    h('span', { text: `${nodeCount ?? state.graph.nodes.length} shown of ${state.graph.nodes.length} elements` }),
    h('span', { text: `${edgeCount ?? state.graph.edges.length} relations` }),
  );
}

// --------------------------------------------------------------- inspector
async function selectNode(id) {
  state.selectedId = id;
  if (id && mapView.focusId !== id) mapView.focus(id);
  const inspector = el('inspector');
  if (!id) {
    inspector.replaceChildren(h('div', { class: 'empty-state' }, [
      h('h3', { text: 'Nothing selected' }),
      h('p', { text: 'Click an element on the map to focus on it and see its properties and full traceability.' }),
    ]));
    return;
  }

  try {
    const trace = await api.trace(id, 2);
    renderInspector(trace);
  } catch (error) {
    toast(error.message, 'error');
  }
}

function renderInspector(trace) {
  const inspector = el('inspector');
  const node = trace.node;
  const spec = state.ontology.node_types[node.type] || { label: node.type, properties: {} };
  inspector.replaceChildren();

  const head = h('div', { class: 'insp-head' }, [
    h('div', { class: 'insp-type' }, [
      h('i', { class: 'swatch', style: `background:${spec.color}` }),
      spec.label,
    ]),
    h('h3', {}, [
      node.label,
      h('span', { class: `badge ${weightOf(node)}`, text: weightOf(node) }),
    ]),
    h('div', { class: 'mono muted', text: node.id }),
    h('div', { class: 'insp-actions' }, [
      h('button', { class: 'btn', text: 'Edit', onClick: () => openNodeDialog(node.id) }),
      h('button', { class: 'btn', text: 'Link…', onClick: () => openEdgeDialog(node.id) }),
      h('button', { class: 'btn', text: 'Report…', onClick: () => openReportDialog(node.id) }),
      h('button', { class: 'btn', text: 'Show all', onClick: () => mapView.clearFocus() }),
      h('button', { class: 'btn btn-danger', text: 'Delete', onClick: () => deleteNode(node.id) }),
    ]),
  ]);
  inspector.append(head);

  // Completeness: which management questions this element can answer.
  const completeness = trace.completeness || {};
  const missing = Object.entries(completeness.missing || {});
  if (missing.length) {
    inspector.append(h('div', { class: 'section-title', text: 'Traceability gaps' }));
    const list = h('div', { class: 'gap-list' });
    for (const [question, relations] of missing) {
      list.append(h('div', { style: 'margin-bottom:4px' }, [
        `No "${question}" link — add `,
        ...relations.map((r) => h('code', { text: state.ontology.edge_types[r]?.label || r })),
      ]));
    }
    inspector.append(list);
  }

  const questionOrder = ['who', 'when', 'why', 'how', 'what', 'where', 'other'];
  const questions = trace.questions || {};
  if (Object.keys(questions).length) {
    inspector.append(h('div', { class: 'section-title', text: 'Traceability' }));
    for (const question of questionOrder) {
      const items = questions[question];
      if (!items || !items.length) continue;
      const group = h('div', { class: 'rel-group' }, [h('div', { class: 'rel-question', text: question })]);
      for (const item of items) {
        group.append(h('div', { class: 'rel-item' }, [
          h('span', { class: 'rel-verb', text: item.relation_label }),
          h('span', { class: 'rel-target', text: item.node.label, onClick: () => selectNode(item.node.id) }),
          h('button', { class: 'rel-del', text: '×', title: 'Remove this relation', onClick: () => deleteEdge(item.edge_id) }),
        ]));
      }
      inspector.append(group);
    }
  }

  inspector.append(h('div', { class: 'section-title', text: 'Properties' }));
  const properties = h('dl', { class: 'prop-grid' });
  for (const propertySpec of Object.values(spec.properties || {})) {
    const value = node.properties[propertySpec.name];
    if (value === undefined || value === null || value === '') continue;
    properties.append(h('dt', { text: propertySpec.label }), h('dd', { text: formatValue(value) }));
  }
  if (!properties.children.length) properties.append(h('dd', { class: 'muted', text: 'No properties recorded yet.' }));
  inspector.append(properties);

  inspector.append(h('div', { class: 'section-title', text: 'Impact' }));
  inspector.append(h('div', { class: 'muted', style: 'font-size:12.5px;line-height:1.6' }, [
    `${trace.downstream.length} element(s) depend on this one; it draws on ${trace.upstream.length} upstream element(s).`,
  ]));

  inspector.append(h('div', { class: 'section-title', text: 'Provenance' }));
  const provenance = trace.provenance || {};
  inspector.append(h('dl', { class: 'prop-grid' }, [
    h('dt', { text: 'Created' }), h('dd', { text: `${provenance.created_at} by ${provenance.created_by}` }),
    h('dt', { text: 'Updated' }), h('dd', { text: `${provenance.updated_at} by ${provenance.updated_by}` }),
    h('dt', { text: 'Revision' }), h('dd', { text: provenance.revision }),
    h('dt', { text: 'Source' }), h('dd', { text: provenance.source }),
  ]));
}

// ------------------------------------------------------------------ dialogs
function openModal(title, body, onConfirm, { confirmLabel = 'Save', wide = false, cancel = true, confirm = true } = {}) {
  el('modal-backdrop').querySelector('.modal').classList.toggle('modal-wide', wide);
  el('modal-cancel').classList.toggle('hidden', !cancel);
  el('modal-confirm').classList.toggle('hidden', !confirm);
  el('modal-title').textContent = title;
  el('modal-body').replaceChildren(body);
  el('modal-error').textContent = '';
  el('modal-confirm').textContent = confirmLabel;
  el('modal-backdrop').classList.remove('hidden');

  const confirmButton = el('modal-confirm');
  const clone = confirmButton.cloneNode(true);
  confirmButton.replaceWith(clone);
  clone.addEventListener('click', async () => {
    clone.disabled = true;
    try {
      await onConfirm();
      closeModal();
    } catch (error) {
      el('modal-error').textContent = error.message;
    } finally {
      clone.disabled = false;
    }
  });

  const firstInput = body.querySelector('input, select, textarea');
  if (firstInput) setTimeout(() => firstInput.focus(), 40);
}

function closeModal() {
  el('modal-backdrop').classList.add('hidden');
  el('modal-body').replaceChildren();
}

async function openNodeDialog(nodeId = null, defaultType = null) {
  const isNew = !nodeId;
  const existing = isNew ? null : state.nodesById.get(nodeId) || (await api.node(nodeId));
  const wrapper = h('div');

  const types = Object.values(state.ontology.node_types).filter((t) => !t.abstract);
  types.sort((a, b) => a.category.localeCompare(b.category) || a.label.localeCompare(b.label));

  const typeSelect = h('select', { id: 'node-type' });
  for (const spec of types) {
    typeSelect.append(h('option', {
      value: spec.name,
      text: `${spec.category} — ${spec.label}`,
      selected: existing ? existing.type === spec.name : spec.name === defaultType,
    }));
  }

  const typeField = h('div', { class: 'form-field' }, [
    h('label', { for: 'node-type', text: 'Element type' }),
    typeSelect,
    h('div', { class: 'help', id: 'type-help' }),
  ]);
  wrapper.append(typeField);

  const formHost = h('div');
  wrapper.append(formHost);

  const renderForm = () => {
    const spec = state.ontology.node_types[typeSelect.value];
    el('modal-body').querySelector('#type-help').textContent = spec.description || '';
    formHost.replaceChildren(buildPropertyForm(spec, existing ? existing.properties : {}));
  };
  typeSelect.addEventListener('change', renderForm);

  openModal(isNew ? 'New element' : `Edit ${existing.label}`, wrapper, async () => {
    const spec = state.ontology.node_types[typeSelect.value];
    const form = formHost.querySelector('form');
    const properties = readPropertyForm(form, spec);
    if (isNew) {
      const created = await api.createNode({ type: typeSelect.value, properties });
      await applyChange({ node: created });
      if (state.view === 'dashboard') await selectNode(created.id);
      else await switchView(state.view);
      toast(`Created ${spec.label} "${created.properties.name || created.id}"`, 'success');
    } else {
      const retyped = typeSelect.value !== existing.type;
      const updated = await api.updateNode(nodeId, { type: typeSelect.value, properties });
      await applyChange({ node: updated }, retyped ? 2 : 1);
      if (state.view === 'dashboard') await selectNode(nodeId);
      else await switchView(state.view);
      toast('Element updated', 'success');
    }
  });
  renderForm();
}

async function openEdgeDialog(sourceId = null) {
  const wrapper = h('div');
  const nodes = state.graph.nodes;

  const sourceSelect = elementSelect('edge-source', nodes, sourceId);
  const targetSelect = elementSelect('edge-target', nodes, null);
  const relationSelect = h('select', { id: 'edge-type' });
  const relationHelp = h('div', { class: 'help' });
  const propertyHost = h('div');

  wrapper.append(
    h('div', { class: 'form-field' }, [h('label', { for: 'edge-source', text: 'From' }), sourceSelect]),
    h('div', { class: 'form-field' }, [h('label', { for: 'edge-type', text: 'Relation' }), relationSelect, relationHelp]),
    h('div', { class: 'form-field' }, [h('label', { for: 'edge-target', text: 'To' }), targetSelect]),
    propertyHost,
  );

  // Only relations the ontology permits between the chosen endpoints are offered.
  const refreshRelations = async () => {
    const sourceNode = state.nodesById.get(sourceSelect.value);
    if (!sourceNode) return;
    const result = await api.allowedEdges({ source_type: sourceNode.type });
    relationSelect.replaceChildren();
    for (const spec of result.edge_types) {
      relationSelect.append(h('option', { value: spec.name, text: `${spec.label} → ${spec.range.join('/') || 'any'}` }));
    }
    refreshTargets();
  };

  const refreshTargets = () => {
    const spec = state.ontology.edge_types[relationSelect.value];
    relationHelp.textContent = spec?.description || '';
    const allowed = new Set(spec?.range || []);
    const candidates = allowed.size
      ? nodes.filter((n) => allowed.has(n.type) || isSubtype(n.type, allowed))
      : nodes;
    const current = targetSelect.value;
    targetSelect.replaceChildren(...optionsFor(candidates));
    if (candidates.some((n) => n.id === current)) targetSelect.value = current;

    const propertySpec = spec ? { properties: spec.properties } : { properties: {} };
    propertyHost.replaceChildren(
      Object.keys(propertySpec.properties).length
        ? buildPropertyForm(propertySpec, {})
        : h('div', { class: 'help', text: 'This relation carries no properties of its own.' }),
    );
  };

  sourceSelect.addEventListener('change', refreshRelations);
  relationSelect.addEventListener('change', refreshTargets);

  openModal('New relation', wrapper, async () => {
    const spec = state.ontology.edge_types[relationSelect.value];
    const form = propertyHost.querySelector('form');
    const properties = form ? readPropertyForm(form, { properties: spec.properties }) : {};
    const created = await api.createEdge({
      type: relationSelect.value,
      source: sourceSelect.value,
      target: targetSelect.value,
      properties,
    });
    await applyChange({ edge: created });
    if (state.view === 'dashboard') await selectNode(sourceSelect.value);
    else await switchView(state.view);
    toast('Relation created', 'success');
  }, { confirmLabel: 'Create' });

  await refreshRelations();
}

function isSubtype(typeName, allowed) {
  let current = typeName;
  const seen = new Set();
  while (current && !seen.has(current)) {
    if (allowed.has(current)) return true;
    seen.add(current);
    current = state.ontology.node_types[current]?.extends;
  }
  return false;
}

function optionsFor(nodes) {
  return [...nodes]
    .sort((a, b) => a.type.localeCompare(b.type) || a.label.localeCompare(b.label))
    .map((node) => h('option', { value: node.id, text: `${node.label} · ${node.type}` }));
}

function elementSelect(id, nodes, selected) {
  const select = h('select', { id }, optionsFor(nodes));
  if (selected) select.value = selected;
  return select;
}

/** Choose a format and either preview the report or download it. */
function openReportDialog(nodeId) {
  const node = state.nodesById.get(nodeId);
  const formats = [
    ['html', 'Web page', 'Self-contained and styled for printing — the one to put in a review pack.'],
    ['md', 'Markdown', 'Plain text to paste into a minute, a wiki or a merge request.'],
    ['json', 'JSON', 'The same content as data, for a downstream script.'],
  ];

  const body = h('div');
  body.append(h('p', { class: 'muted', style: 'margin-top:0;font-size:12.5px;line-height:1.6' }, [
    `Everything the inspector shows for "${node?.label || nodeId}": properties, traceability grouped by `
    + 'question, the gaps the ontology expects to be filled, impact and provenance.',
  ]));

  for (const [value, label, help] of formats) {
    body.append(h('div', { class: 'form-field' }, [
      h('label', { class: 'inline' }, [
        h('input', { type: 'radio', name: 'report-format', value, checked: value === 'html' }),
        h('span', {}, [h('strong', { text: label })]),
      ]),
      h('div', { class: 'help', style: 'margin-left:24px', text: help }),
    ]));
  }

  body.append(h('div', { class: 'form-field' }, [
    h('label', { for: 'report-depth', text: 'Impact depth' }),
    h('input', { type: 'number', id: 'report-depth', name: 'report-depth', value: '2', min: '1', max: '6' }),
    h('div', { class: 'help', text: 'How many hops of upstream and downstream elements to list.' }),
  ]));

  const chosen = () => body.querySelector('input[name="report-format"]:checked').value;
  const depth = () => body.querySelector('#report-depth').value || '2';
  const url = (download) =>
    `/api/nodes/${encodeURIComponent(nodeId)}/report?format=${chosen()}&depth=${depth()}`
    + (download ? '&download=1' : '');

  // Secondary action lives in the body: openModal owns the footer, and anything
  // appended there would survive into the next dialog.
  body.append(h('div', { style: 'margin-top:4px' }, [
    h('button', {
      class: 'btn',
      type: 'button',
      text: 'Open preview in a new tab',
      onClick: () => download(url(false), { newTab: true }).catch((error) => toast(error.message, 'error')),
    }),
  ]));

  openModal(`Report — ${node?.label || nodeId}`, body, async () => {
    // Fetched with the token header, then saved under the server's filename.
    await download(url(true));
    toast('Report downloaded', 'success');
  }, { confirmLabel: 'Download' });
}

async function deleteNode(id) {
  const node = state.nodesById.get(id);
  const body = h('div', {}, [
    h('p', { text: `Delete "${node?.label || id}"?` }),
    h('p', { class: 'help', text: 'Every relation touching this element is removed with it. This cannot be undone from the interface, though a versioned backend keeps the previous revision.' }),
  ]);
  openModal('Delete element', body, async () => {
    const result = await api.deleteNode(id);
    await applyChange({ deletedNode: result.deleted_node, deletedEdges: result.deleted_edges });
    if (state.view === 'dashboard') await selectNode(null);
    else await switchView(state.view);
    toast(`Deleted element and ${result.deleted_edges.length} relation(s)`, 'success');
  }, { confirmLabel: 'Delete' });
}

async function deleteEdge(edgeId) {
  try {
    const result = await api.deleteEdge(edgeId);
    await applyChange({ deletedEdges: [result.deleted_edge] });
    if (state.selectedId) await selectNode(state.selectedId);
    if (state.view !== 'dashboard') await switchView(state.view);
    toast('Relation removed', 'success');
  } catch (error) {
    toast(error.message, 'error');
  }
}

/** Callback object handed to a board page: create/edit/delete plus jump-to-graph. */
function pageActions(typeName) {
  return {
    onOpen: openFromPage,
    onNew: () => openNodeDialog(null, typeName),
    onEdit: (id) => openNodeDialog(id),
    onDelete: (id) => deleteNode(id),
    onLink: (id) => openEdgeDialog(id),
  };
}

// ------------------------------------------------------------------- chrome
function wireChrome() {
  el('tabs').addEventListener('click', (event) => {
    const button = event.target.closest('.tab');
    if (!button) return;
    switchView(button.dataset.view);
  });

  el('btn-admin').addEventListener('click', (event) => {
    event.stopPropagation();
    const menu = el('admin-menu');
    const opening = menu.classList.contains('hidden');
    menu.classList.toggle('hidden', !opening);
    el('btn-admin').setAttribute('aria-expanded', String(opening));
  });
  el('admin-menu').addEventListener('click', (event) => {
    const item = event.target.closest('.menu-item');
    if (item) switchView(item.dataset.view);
  });
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.menu-wrap')) closeAdminMenu();
  });

  el('search').addEventListener('input', (event) => {
    state.search = event.target.value;
    applyFilters();
  });
  // Enter jumps to the first match: the quickest way to focus on something.
  el('search').addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    const first = mapView.nodes[0];
    if (first) { mapView.focus(first.id); selectNode(first.id); }
  });

  el('btn-new-node').addEventListener('click', () => openNodeDialog());
  el('btn-new-edge').addEventListener('click', () => openEdgeDialog(state.selectedId));

  el('btn-save').addEventListener('click', save);
  el('btn-projects').addEventListener('click', () => switchView('home'));
  el('btn-theme').addEventListener('click', toggleTheme);
  el('modal-close').addEventListener('click', closeModal);
  el('modal-cancel').addEventListener('click', closeModal);
  el('modal-backdrop').addEventListener('click', (event) => {
    if (event.target === el('modal-backdrop')) closeModal();
  });

  for (const button of document.querySelectorAll('[data-toggle-all]')) {
    button.addEventListener('click', () => {
      const kind = button.dataset.toggleAll;
      const set = { node: state.hiddenNodeTypes, edge: state.hiddenEdgeTypes, weight: state.hiddenWeights }[kind];
      set.clear();
      buildFilters();
      applyFilters();
    });
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeModal();
    if (event.target.matches('input, textarea, select')) return;
    if (event.key === '/') { event.preventDefault(); el('search').focus(); }
    if (event.key === 'n') openNodeDialog();
    if (event.key === 'l') openEdgeDialog(state.selectedId);
    if (event.key === 'f') mapView.clearFocus();
    if (event.key === 'r' && state.selectedId) openReportDialog(state.selectedId);
    if ((event.key === 's') && (event.metaKey || event.ctrlKey)) { event.preventDefault(); save(); }
  });
}

function closeAdminMenu() {
  el('admin-menu').classList.add('hidden');
  el('btn-admin').setAttribute('aria-expanded', 'false');
}

async function switchView(view) {
  // Nothing but the start page and settings works before a project is open.
  if (!state.projectOpen && !WITHOUT_PROJECT.has(view)) view = 'home';
  state.view = view;
  // Ontologies/System/Settings live in the gear menu, so some views have no tab
  // in the bar: nothing is highlighted for those, and the menu marks its own.
  for (const tab of document.querySelectorAll('.tab')) tab.classList.toggle('active', tab.dataset.view === view);
  for (const item of document.querySelectorAll('.menu-item')) item.classList.toggle('active', item.dataset.view === view);
  for (const section of document.querySelectorAll('.view')) {
    section.classList.toggle('active', section.id === `view-${view}`);
  }
  closeAdminMenu();
  try {
    if (view === 'home') {
      await showHome();
    } else if (view === 'overview') {
      const report = await api.kpi('report');
      renderOverview(el('overview-body'), report, topRisks(state.graph.nodes, state.ontology), {
        onOpen: openFromPage,
      });
    } else if (view === 'milestones') {
      const data = await api.kpi('milestone_load');
      renderMilestones(el('milestones-body'), data.items || [], pageActions('Milestone'));
    } else if (view === 'people') {
      const data = await api.kpi('workload');
      renderWorkload(el('people-body'), data.items || [], pageActions('Person'));
    } else if (view === 'tools') {
      const data = await api.kpi('tool_usage');
      renderTools(el('tools-body'), data.items || [], pageActions('Tool'));
    } else if (view === 'kpi') {
      renderKpis(el('kpi-body'), await api.kpi('report'), pageActions(null));
    } else if (view === 'ontologies') {
      await showOntologies();
    } else if (view === 'settings') {
      await showSettings();
    } else if (view === 'system') {
      const [health, appKpi, validation] = await Promise.all([api.health(), api.appKpi(), api.validate()]);
      renderSystem(el('system-body'), { health, appKpi, validation }, {
        onSave: save,
        onReloadStorage: async () => {
          await api.reload();
          await refreshAll();
          toast('Reloaded from storage', 'success');
          switchView('system');
        },
      });
    } else if (view === 'dashboard') {
      // The map was laid out while hidden: draw its links now it has a size.
      mapView.render();
    }
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function showSettings(status = '') {
  const [data, examples] = await Promise.all([api.settings(), api.examples()]);
  data.examples = examples.examples;
  renderSettings(el('settings-body'), data, {
    onSave: async (payload) => {
      const result = await api.updateSettings(payload);
      // An API token set here would lock this page out on the next request,
      // so the browser adopts it immediately.
      const token = payload.values?.api_token;
      if (result.changed.includes('api_token') && token && token !== '********') setToken(token);
      if (result.changed.length) toast(result.saved_to ? 'Settings saved' : 'Settings applied', 'success');
      return result;
    },
    onReload: async (message) => { if (state.projectOpen) await refreshAll(); await showSettings(message); },
    onTestStorage: (payload) => api.testStorage(payload),
    onOfferReopen: (result) => confirmReopen(result),
    onLoadJson: (text, merge, filename) => confirmLoadJson(text, merge, filename),
  }, status);
}

/** Switching storage or ontology rebuilds the workspace, which may lose work. */
function confirmReopen(result) {
  const fields = result.needs_reopen.join(', ');
  const body = h('div');
  body.append(h('p', { text: `Changing ${fields} means re-opening the project against the new settings.` }));

  if (result.unsaved_changes) {
    body.append(h('p', { class: 'setting-warn' }, [
      'There are unsaved changes in the current project. Save them first, or they are lost.',
    ]));
    body.append(h('div', { style: 'display:flex;gap:8px;margin-top:8px' }, [
      h('button', {
        class: 'btn',
        type: 'button',
        text: 'Save the current project first',
        onClick: async () => {
          try {
            await api.save('saved before switching storage');
            toast('Saved', 'success');
            body.querySelector('.setting-warn').textContent = 'Saved. Safe to re-open now.';
          } catch (error) {
            toast(error.message, 'error');
          }
        },
      }),
    ]));
  } else {
    body.append(h('p', { class: 'setting-help', text: 'Nothing is unsaved, so this is safe.' }));
  }

  openModal('Re-open the project?', body, async () => {
    const outcome = await api.reopenWorkspace(result.unsaved_changes);
    toast(`Opened ${outcome.storage.scheme}:${outcome.storage.target} — ${outcome.graph.nodes} elements`, 'success');
    await refreshAll();
    await selectNode(null);
    await showSettings();
  }, { confirmLabel: 'Re-open' });
}

/** Load a JSON graph file the user picked in Settings. */
async function confirmLoadJson(text, merge, filename) {
  let document;
  try {
    document = JSON.parse(text);
  } catch (error) {
    toast(`${filename} is not valid JSON: ${error.message}`, 'error');
    return;
  }

  const proceed = async () => {
    try {
      const result = await api.importDocument(document, merge);
      toast(`Loaded ${filename}: ${result.nodes} elements, ${result.edges} relations`, 'success');
      await refreshAll();
      await selectNode(null);
      await switchView('dashboard');
    } catch (error) {
      toast(error.message, 'error');
    }
  };

  // Merging keeps what is already there, so only a replace needs the warning.
  if (merge || !state.dirty) {
    await proceed();
    return;
  }

  const body = h('div', {}, [
    h('p', { text: `Loading ${filename} replaces everything in the current project.` }),
    h('p', { class: 'setting-warn', text: 'There are unsaved changes that will be lost.' }),
  ]);
  openModal('Load project file?', body, proceed, { confirmLabel: 'Load, discard changes' });
}

async function openFromPage(id) {
  await switchView('dashboard');
  mapView.focus(id);
  await selectNode(id);
}

// ----------------------------------------------------------------- projects
// The start page: create, open or load a project. Every path ends the same
// way -- the project (and its own ontology) changes, so everything is re-read.

async function afterProjectChange(message) {
  state.hiddenNodeTypes.clear();
  state.hiddenEdgeTypes.clear();
  state.selectedId = null;
  await refreshHeader();
  await loadProject();
  mapView.clearFocus();
  await selectNode(null);
  await switchView('overview');
  toast(message, 'success');
}

async function showHome() {
  const [listing, examples] = await Promise.all([api.projects(), api.examples()]);
  renderHome(el('home-body'), listing, examples.examples, {
    onCreate: openNewProjectWizard,
    onOpen: confirmOpenProject,
    onLoadExample: (name) => withUnsavedCheck('Load example?', 'Loading an example opens it as a new project.', async (force) => {
      const result = await api.loadExample(name, force);
      await afterProjectChange(`Loaded ${result.created.name} as a new project`);
    }),
    onImport: (text, filename) => {
      let document;
      try {
        document = JSON.parse(text);
      } catch (error) {
        toast(`${filename} is not valid JSON: ${error.message}`, 'error');
        return;
      }
      const name = document?.project?.name && document.project.name !== 'Untitled project'
        ? document.project.name : filename.replace(/\.json$/i, '');
      return withUnsavedCheck('Import project?', `${filename} becomes a new project.`, async (force) => {
        const result = await api.createProject({ name, document, open: true, force });
        await afterProjectChange(`Imported ${result.created.name} as a new project`);
      });
    },
  });
}

/** Run an action that switches project, asking first if unsaved work would be lost. */
async function withUnsavedCheck(title, text, action) {
  if (!state.projectOpen || !state.dirty) {
    try {
      await action(false);
    } catch (error) {
      toast(error.message, 'error');
    }
    return;
  }
  const body = h('div', {}, [
    h('p', { text }),
    h('p', { class: 'setting-warn', text: 'The project you are in has unsaved changes. Continuing discards them — press Save first to keep them.' }),
  ]);
  openModal(title, body, () => action(true), { confirmLabel: 'Continue, discard changes' });
}

function confirmOpenProject(project) {
  return withUnsavedCheck('Open project?', `Open ${project.name}?`, async (force) => {
    await api.openProject(project.storage, force);
    await afterProjectChange(`Opened ${project.name}`);
  });
}

async function openNewProjectWizard() {
  const config = await api.catalogue();
  const setError = (message) => { el('modal-error').textContent = message; };
  const wizard = buildProjectWizard(config, {
    dirty: state.projectOpen && state.dirty,
    setError,
    onCreate: async (payload) => {
      const result = await api.createProject(payload);
      closeModal();
      await afterProjectChange(`Created and opened ${result.created.name}`);
    },
  });
  openModal('New project', wizard, async () => {}, { wide: true, confirm: false });
}

// --------------------------------------------------------------- ontologies
// The project's own ontology, the master, and copying between them.

async function showOntologies() {
  const [summary, compare] = await Promise.all([api.ontologies(), api.compareOntologies()]);
  await renderOntologies(el('ontologies-body'), { summary, compare, project: state.ontology }, {
    tab: state.ontologyTab,
    compareShowAll: state.compareShowAll,
    onTab: (tab) => { state.ontologyTab = tab; showOntologies(); },
    onCompareShowAll: (value) => { state.compareShowAll = value; showOntologies(); },
    loadMaster: () => api.masterOntology(),
    downloadLink,
    onReloadMaster: async () => {
      const result = await api.reloadMaster();
      toast(`Master reloaded (v${result.version})`, 'success');
      showOntologies();
    },
    onAddType: () => editTypeDialog(null),
    onEditType: (name) => editTypeDialog(name),
    onAddRelation: () => editRelationDialog(null),
    onEditRelation: (name) => editRelationDialog(name),
    onRemove: (kind, name, label) => {
      const body = h('div', {}, [
        h('p', { text: `Remove "${label}" from this project's ontology?` }),
        h('p', { class: 'help', text: 'Refused if any element or relation of the project still uses it. The master is not affected.' }),
      ]);
      openModal('Remove from project', body, async () => {
        await api.removeProjectType(kind, name);
        await afterOntologyChange(`Removed ${label}`);
      }, { confirmLabel: 'Remove' });
    },
    onAddFromMaster: addFromMasterDialog,
    onMerge: mergeDialog,
  });
}

/** The project's ontology changed: forms, filters and the map follow. */
async function afterOntologyChange(message) {
  state.ontology = await api.ontology();
  await refreshGraph();
  buildFilters();
  await showOntologies();
  toast(message, 'success');
}

function editTypeDialog(name) {
  const existing = name ? state.ontology.node_types[name] : null;
  const form = elementTypeForm(existing);
  openModal(existing ? `Edit ${existing.label}` : 'New element type (this project only)', form.element, async () => {
    const data = form.read();
    if (!existing && !data.label) throw new Error('Give the element type a name');
    const result = existing ? await api.editProjectType('element-types', name, data) : await api.addProjectType('element-types', data);
    await afterOntologyChange(existing ? `Updated ${existing.label}` : `Added element type ${result.name}`);
  }, { confirmLabel: existing ? 'Save' : 'Add', wide: true });
}

function editRelationDialog(name) {
  const existing = name ? state.ontology.edge_types[name] : null;
  const types = Object.values(state.ontology.node_types).filter((t) => !t.abstract)
    .sort((a, b) => a.label.localeCompare(b.label)).map((t) => ({ name: t.name, label: t.label }));
  const form = relationForm(types, existing);
  openModal(existing ? `Edit ${existing.label}` : 'New relation (this project only)', form.element, async () => {
    const data = form.read();
    if (!existing && !data.label) throw new Error('Give the relation a name');
    const result = existing ? await api.editProjectType('relations', name, data) : await api.addProjectType('relations', data);
    await afterOntologyChange(existing ? `Updated ${existing.label}` : `Added relation ${result.name}`);
  }, { confirmLabel: existing ? 'Save' : 'Add', wide: true });
}

async function addFromMasterDialog() {
  const compare = await api.compareOntologies();
  const available = compare.items.filter((i) => i.status === 'master_only' && !i.abstract);
  if (!available.length) {
    toast('This project already has everything the master offers', 'info');
    return;
  }
  const list = h('div', { class: 'check-columns' });
  for (const kind of ['element_type', 'relation']) {
    const items = available.filter((i) => i.kind === kind).sort((a, b) => a.label.localeCompare(b.label));
    if (!items.length) continue;
    list.append(h('fieldset', { class: 'picker-group' }, [
      h('legend', { text: kind === 'relation' ? 'Relations' : 'Element types' }),
      ...items.map((item) => h('label', { class: 'picker-item' }, [
        h('input', { type: 'checkbox', name: 'master-item', value: `${item.kind}:${item.name}` }),
        h('span', { text: item.label }),
        item.kind === 'relation' ? h('span', { class: 'muted picker-ends', text: `${item.domain.join('/')} → ${item.range.join('/')}` }) : null,
      ])),
    ]));
  }
  const body = h('div', {}, [
    h('p', { class: 'help', text: 'Copy element types and relations from the master into this project. A relation brings the element types it needs.' }),
    list,
  ]);
  openModal('Add from master', body, async () => {
    const items = [...body.querySelectorAll('input[name="master-item"]:checked')].map((box) => {
      const [kind, ...rest] = box.value.split(':');
      return { kind, name: rest.join(':') };
    });
    if (!items.length) throw new Error('Tick at least one');
    const result = await api.mergeOntologies('to_project', items, false);
    await afterOntologyChange(`Added ${describeMerge(result)} from the master`);
  }, { confirmLabel: 'Add to project', wide: true });
}

function describeMerge(result) {
  const names = [...result.copied, ...result.dependencies].map((i) => i.name);
  return names.length === 1 ? names[0] : `${names.length} items`;
}

/** Preview a merge (what comes with it, what is kept), then apply it. */
async function mergeDialog(direction, items) {
  let preview;
  try {
    preview = await api.mergeOntologies(direction, items, true);
  } catch (error) {
    toast(error.message, 'error');
    return;
  }
  const where = direction === 'to_master' ? 'the master ontology' : 'this project';
  const body = h('div', { class: 'merge-preview' }, [
    h('p', { text: `Copy into ${where}:` }),
    h('ul', {}, preview.copied.map((i) => h('li', { text: `${i.name} (${i.kind.replace('_', ' ')})` }))),
    preview.dependencies.length ? h('p', { text: 'Also brings, because they are needed:' }) : null,
    preview.dependencies.length ? h('ul', {}, preview.dependencies.map((i) => h('li', { text: `${i.name} (${i.kind.replace('_', ' ')})` }))) : null,
    ...preview.notes.map((note) => h('p', { class: 'help', text: note })),
    ...preview.skipped.map((s) => h('p', { class: 'setting-warn', text: `Skipped ${s.name}: ${s.reason}` })),
    direction === 'to_master'
      ? h('p', { class: 'help', text: 'The master is saved to its file with a new version number. Other projects take the change only when they copy it themselves.' })
      : h('p', { class: 'help', text: 'Properties this project already uses are kept.' }),
  ]);
  if (!preview.copied.length && !preview.dependencies.length) {
    toast('Nothing to copy: both sides already agree on these', 'info');
    return;
  }
  openModal(direction === 'to_master' ? 'Copy to the master' : 'Copy to this project', body, async () => {
    const result = await api.mergeOntologies(direction, items, false);
    if (direction === 'to_project') {
      await afterOntologyChange(`Copied ${describeMerge(result)} into this project`);
    } else {
      await showOntologies();
      toast(`Copied ${describeMerge(result)} to the master (now v${result.master_version})`, 'success');
    }
  }, { confirmLabel: 'Copy' });
}
async function refreshAll() {
  await refreshGraph();
  await refreshHeader();
  buildFilters();
}

// --------------------------------------------------------- incremental sync
// After a single add, edit or delete the server has already said exactly what
// changed, so the local copy is patched instead of re-downloading the whole
// graph (thousands of elements) after every click. The header refresh that
// follows reports the server's revision: if it is not the one this change
// should have produced -- another tab or user wrote in between -- fall back to
// a full refetch, so the patch can never leave the page out of step.

/** Mirrors Node.label on the server: the first non-empty naming property. */
function labelOf(properties, id) {
  for (const key of ['name', 'title', 'label', 'text']) {
    const value = properties?.[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return id;
}

function nodeBrief(node) {
  const spec = state.ontology.node_types[node.type] || {};
  return {
    id: node.id,
    type: node.type,
    type_label: spec.label || node.type,
    label: labelOf(node.properties, node.id),
    color: spec.color || '#6b7fd7',
    properties: node.properties || {},
  };
}

function edgeBrief(edge) {
  const spec = state.ontology.edge_types[edge.type] || {};
  return {
    id: edge.id,
    type: edge.type,
    label: spec.label || edge.type,
    question: spec.question || '',
    source: edge.source,
    target: edge.target,
    properties: edge.properties || {},
  };
}

function upsert(list, item) {
  const index = list.findIndex((existing) => existing.id === item.id);
  if (index >= 0) list[index] = item; else list.push(item);
}

/**
 * Apply one write's result locally. ``bumps`` is how many revisions the write
 * advanced the server by (an edit that also changes type is two).
 */
async function applyChange({ node, edge, deletedNode, deletedEdges = [] }, bumps = 1) {
  const expected = (state.graph.revision ?? 0) + bumps;
  if (node) upsert(state.graph.nodes, nodeBrief(node));
  if (edge) upsert(state.graph.edges, edgeBrief(edge));
  if (deletedNode) state.graph.nodes = state.graph.nodes.filter((n) => n.id !== deletedNode);
  if (deletedEdges.length) {
    const gone = new Set(deletedEdges);
    state.graph.edges = state.graph.edges.filter((e) => !gone.has(e.id));
  }
  state.graph.revision = expected;
  state.nodesById = new Map(state.graph.nodes.map((n) => [n.id, n]));

  await refreshHeader();
  if (state.serverRevision !== expected) {
    await refreshGraph();  // someone else changed the graph too: take the server's copy
  } else {
    applyFilters();
  }
  buildFilters();
}

async function save() {
  try {
    const result = await api.save('saved from the web interface');
    setDirty(false);
    toast(result.message === 'no changes' ? 'Nothing to save' : `Saved to ${result.location || 'storage'}`, 'success');
  } catch (error) {
    toast(error.message, 'error');
  }
}

function setDirty(value) {
  state.dirty = value;
  el('dirty-flag').classList.toggle('hidden', !value);
}

function toast(message, kind = 'info') {
  const node = h('div', { class: `toast ${kind}`, text: message });
  el('toasts').append(node);
  setTimeout(() => node.remove(), kind === 'error' ? 7000 : 3200);
}

function restoreTheme() {
  const stored = localStorage.getItem('setm.theme');
  if (stored) document.documentElement.dataset.theme = stored;
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('setm.theme', next);
  mapView._drawLinks();
}

boot();
