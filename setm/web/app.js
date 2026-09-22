// Application controller: state, wiring and the inspector.

import { api, setToken } from './api.js';
import { GraphView } from './graph.js';
import { buildPropertyForm, formatValue, h, readPropertyForm } from './forms.js';
import {
  renderKpis, renderMilestones, renderOntology, renderSettings, renderSystem, renderTools, renderWorkload,
} from './views.js';
import { renderTree } from './tree.js';

const state = {
  ontology: null,
  graph: { nodes: [], edges: [] },
  nodesById: new Map(),
  selectedId: null,
  hiddenNodeTypes: new Set(),
  hiddenEdgeTypes: new Set(),
  hiddenWeights: new Set(),
  search: '',
  view: 'graph',
  dirty: false,
};

const el = (id) => document.getElementById(id);
let graphView;

// --------------------------------------------------------------------- init
async function boot() {
  restoreTheme();
  wireChrome();
  graphView = new GraphView(el('graph-canvas'), {
    onSelect: (node) => selectNode(node.id),
    onHover: showTooltip,
    onBackground: () => selectNode(null),
  });

  try {
    state.ontology = await api.ontology();
    await refreshGraph();
    await refreshHeader();
    buildFilters();
    graphView.fit();
    // The layout keeps settling after the first paint; re-fit once it has.
    setTimeout(() => graphView.fit(), 1400);
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function refreshHeader() {
  const health = await api.health();
  const project = health.graph ? await api.project() : {};
  el('project-name').textContent = project.name || 'Untitled project';
  el('project-meta').textContent = [
    project.programme,
    project.phase ? `phase ${project.phase}` : '',
    `${health.graph.nodes} elements`,
    `${health.storage.scheme} storage`,
  ].filter(Boolean).join(' · ');
  setDirty(health.unsaved_changes);
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
    return { ...node, color: spec.color || node.color, shape: spec.shape || 'round' };
  });
  const decoratedEdges = visibleEdges.map((edge) => {
    const spec = state.ontology.edge_types[edge.type] || {};
    return { ...edge, color: spec.color, style: spec.style, weight: weightOf(edge) };
  });

  graphView.setData(decorated, decoratedEdges);
  graphView.select(state.selectedId);
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
  graphView.select(id);
  const inspector = el('inspector');
  if (!id) {
    inspector.replaceChildren(h('div', { class: 'empty-state' }, [
      h('h3', { text: 'Nothing selected' }),
      h('p', { text: "Pick an element in the graph, or create one, to see its properties and full traceability." }),
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
      h('button', { class: 'btn', text: 'Focus', onClick: () => { graphView.centreOn(node.id); } }),
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
function openModal(title, body, onConfirm, { confirmLabel = 'Save' } = {}) {
  el('modal-title').textContent = title;
  el('modal-body').replaceChildren(body);
  el('modal-error').textContent = '';
  el('modal-confirm').textContent = confirmLabel;
  el('modal-backdrop').classList.remove('hidden');

  const confirm = el('modal-confirm');
  const clone = confirm.cloneNode(true);
  confirm.replaceWith(clone);
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
      await refreshAll();
      if (state.view === 'graph') await selectNode(created.id);
      else await switchView(state.view);
      toast(`Created ${spec.label} "${created.properties.name || created.id}"`, 'success');
    } else {
      await api.updateNode(nodeId, { type: typeSelect.value, properties });
      await refreshAll();
      if (state.view === 'graph') await selectNode(nodeId);
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
    await api.createEdge({
      type: relationSelect.value,
      source: sourceSelect.value,
      target: targetSelect.value,
      properties,
    });
    await refreshAll();
    if (state.view === 'graph') await selectNode(sourceSelect.value);
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
      onClick: () => window.open(url(false), '_blank', 'noopener'),
    }),
  ]));

  openModal(`Report — ${node?.label || nodeId}`, body, async () => {
    // A navigation rather than a fetch, so the browser names and saves the file.
    window.location.href = url(true);
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
    await refreshAll();
    if (state.view === 'graph') await selectNode(null);
    else await switchView(state.view);
    toast(`Deleted element and ${result.deleted_edges.length} relation(s)`, 'success');
  }, { confirmLabel: 'Delete' });
}

async function deleteEdge(edgeId) {
  try {
    await api.deleteEdge(edgeId);
    await refreshAll();
    if (state.selectedId) await selectNode(state.selectedId);
    if (state.view !== 'graph') await switchView(state.view);
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

  el('search').addEventListener('input', (event) => {
    state.search = event.target.value;
    applyFilters();
  });

  el('focus-mode').addEventListener('change', (event) => {
    graphView.focusMode = event.target.checked;
    graphView._draw();
  });
  el('focus-depth').addEventListener('input', (event) => {
    graphView.focusDepth = Number(event.target.value);
    el('focus-depth-value').value = event.target.value;
    graphView._draw();
  });
  el('show-labels').addEventListener('change', (event) => graphView.setShowLabels(event.target.checked));

  el('btn-new-node').addEventListener('click', () => openNodeDialog());
  el('btn-new-edge').addEventListener('click', () => openEdgeDialog(state.selectedId));
  el('btn-relayout').addEventListener('click', () => { graphView.relayout(); });
  el('zoom-in').addEventListener('click', () => graphView.zoom(1.2));
  el('zoom-out').addEventListener('click', () => graphView.zoom(1 / 1.2));
  el('zoom-fit').addEventListener('click', () => graphView.fit());

  el('btn-save').addEventListener('click', save);
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
    if (event.key === 'f') graphView.fit();
    if (event.key === 'r' && state.selectedId) openReportDialog(state.selectedId);
    if ((event.key === 's') && (event.metaKey || event.ctrlKey)) { event.preventDefault(); save(); }
  });
}

async function switchView(view) {
  state.view = view;
  for (const tab of document.querySelectorAll('.tab')) tab.classList.toggle('active', tab.dataset.view === view);
  for (const section of document.querySelectorAll('.view')) {
    section.classList.toggle('active', section.id === `view-${view}`);
  }
  try {
    if (view === 'milestones') {
      const data = await api.kpi('milestone_load');
      renderMilestones(el('milestones-body'), data.items || [], pageActions('Milestone'));
    } else if (view === 'people') {
      const data = await api.kpi('workload');
      renderWorkload(el('people-body'), data.items || [], pageActions('Person'));
    } else if (view === 'tools') {
      const data = await api.kpi('tool_usage');
      renderTools(el('tools-body'), data.items || [], pageActions('Tool'));
    } else if (view === 'tree') {
      renderTree(el('tree-body'), state.graph.nodes, state.ontology, {
        onOpen: openFromPage,
        onEdit: (id) => openNodeDialog(id),
        onDelete: (id) => deleteNode(id),
        fetchTrace: (id) => api.trace(id, 1),
      });
    } else if (view === 'kpi') {
      renderKpis(el('kpi-body'), await api.kpi('report'), openFromPage);
    } else if (view === 'ontology') {
      renderOntology(el('ontology-body'), state.ontology, async () => {
        const result = await api.reloadOntology();
        state.ontology = result.ontology;
        buildFilters();
        applyFilters();
        renderOntology(el('ontology-body'), state.ontology, () => switchView('ontology'));
        toast('Ontology reloaded', 'success');
      });
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
    } else if (view === 'graph') {
      graphView._resize();
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
    onReload: async (message) => { await refreshAll(); await showSettings(message); },
    onTestStorage: (payload) => api.testStorage(payload),
    onOfferReopen: (result) => confirmReopen(result),
    onLoadExample: (name) => confirmLoadExample(name),
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

/** Loading an example replaces the whole current graph, so confirm first if there's unsaved work. */
async function confirmLoadExample(name) {
  const proceed = async () => {
    const result = await api.loadExample(name);
    toast(`Loaded example: ${result.nodes} elements, ${result.edges} relations`, 'success');
    await refreshAll();
    await selectNode(null);
    await switchView('graph');
  };

  if (!state.dirty) {
    await proceed();
    return;
  }

  const body = h('div', {}, [
    h('p', { text: 'This replaces everything in the current project.' }),
    h('p', { class: 'setting-warn', text: 'There are unsaved changes that will be lost.' }),
  ]);
  openModal('Load example?', body, proceed, { confirmLabel: 'Load, discard changes' });
}

async function openFromPage(id) {
  await switchView('graph');
  await selectNode(id);
  graphView.centreOn(id);
}

async function refreshAll() {
  await refreshGraph();
  await refreshHeader();
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

function showTooltip(node, event) {
  const tooltip = el('tooltip');
  if (!node) { tooltip.classList.add('hidden'); return; }
  const spec = state.ontology.node_types[node.type] || {};
  const rows = Object.entries(node.properties || {})
    .filter(([key]) => ['status', 'maturity', 'activity_type', 'gate', 'role', 'priority'].includes(key))
    .map(([key, value]) => `${key.replace(/_/g, ' ')}: ${formatValue(value)}`);

  tooltip.replaceChildren(
    h('div', { class: 'tt-type', text: spec.label || node.type }),
    h('div', { style: 'font-weight:600;margin:2px 0 3px', text: node.label }),
    ...rows.map((row) => h('div', { class: 'muted', style: 'font-size:11px', text: row })),
  );
  tooltip.classList.remove('hidden');
  const wrap = tooltip.parentElement.getBoundingClientRect();
  tooltip.style.left = `${Math.min(event.clientX - wrap.left + 14, wrap.width - 330)}px`;
  tooltip.style.top = `${event.clientY - wrap.top + 14}px`;
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
  graphView._draw();
}

boot();
