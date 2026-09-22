// Tree view: the same traceability the graph canvas shows, laid out as an
// expandable outline instead of a force-directed drawing. Grouped by the
// ontology's own Who/When/Why/What/How categories so the structure reads the
// same way the sidebar's type filters do, with each row's relations fetched
// lazily (one /trace call per expand) rather than pre-loading the whole graph.

import { h } from './forms.js';
import { newButton, pageHead, rowActions } from './views.js';

const CATEGORY_ORDER = ['Who', 'When', 'Why', 'What', 'How'];
const QUESTION_ORDER = ['who', 'when', 'why', 'how', 'what', 'where', 'other'];

export function renderTree(container, nodes, ontology, actions) {
  container.replaceChildren(
    pageHead(
      'Tree view',
      'The same elements and relations as the graph, structured as an outline. Expand a row to walk its '
      + 'traceability - who, when, why, how, what - without the canvas.',
    ),
  );
  container.append(newButton('Element', actions.onNew));

  const byCategory = new Map();
  for (const node of nodes) {
    const category = ontology.node_types[node.type]?.category || 'Other';
    if (!byCategory.has(category)) byCategory.set(category, []);
    byCategory.get(category).push(node);
  }

  const categories = [...CATEGORY_ORDER, ...[...byCategory.keys()].filter((c) => !CATEGORY_ORDER.includes(c))];
  for (const category of categories) {
    const items = byCategory.get(category);
    if (!items || !items.length) continue;
    const card = h('div', { class: 'card' });
    card.append(h('div', { class: 'card-head' }, [
      h('h3', { text: category }),
      h('span', { class: 'muted', text: `${items.length} element${items.length === 1 ? '' : 's'}` }),
    ]));
    const list = h('div', { class: 'tree-list' });
    for (const node of [...items].sort((a, b) => a.label.localeCompare(b.label))) {
      list.append(treeRow(node, ontology, actions, new Set()));
    }
    card.append(list);
    container.append(card);
  }

  if (!categories.some((c) => byCategory.get(c)?.length)) {
    container.append(h('div', { class: 'card' }, [
      h('p', { class: 'muted', text: 'No elements yet. Use "+ New Element" to add the first one.' }),
    ]));
  }
}

function treeRow(node, ontology, actions, ancestry) {
  const spec = ontology.node_types[node.type] || {};
  const weight = ['low', 'medium', 'high'].includes(node.properties?.weight) ? node.properties.weight : 'high';

  const details = h('details', { class: 'tree-node' });
  details.append(h('summary', {}, [
    h('i', { class: 'swatch', style: `background:${node.color || spec.color || '#6b7fd7'}` }),
    h('span', {
      class: 'tree-label',
      text: node.label,
      onClick: (event) => { event.preventDefault(); actions.onOpen(node.id); },
    }),
    h('span', { class: 'tag', text: node.type_label || spec.label || node.type }),
    h('span', { class: `badge ${weight}`, text: weight }),
    rowActions(node.id, actions),
  ]));

  const body = h('div', { class: 'tree-children' });
  details.append(body);

  details.addEventListener('toggle', async () => {
    if (!details.open || details.dataset.loaded) return;
    details.dataset.loaded = '1';
    if (ancestry.has(node.id)) {
      body.append(h('p', { class: 'muted', text: 'Already shown further up this branch - stopping here to avoid a loop.' }));
      return;
    }
    body.append(h('p', { class: 'muted', text: 'Loading…' }));
    let trace;
    try {
      trace = await actions.fetchTrace(node.id);
    } catch (error) {
      body.replaceChildren(h('p', { class: 'muted', text: `Could not load relations: ${error.message}` }));
      return;
    }
    body.replaceChildren();
    const questions = trace.questions || {};
    const childAncestry = new Set(ancestry);
    childAncestry.add(node.id);
    let any = false;
    for (const question of QUESTION_ORDER) {
      const items = questions[question];
      if (!items || !items.length) continue;
      any = true;
      body.append(h('div', { class: 'tree-question', text: question }));
      for (const item of items) {
        const row = h('div', { class: 'tree-rel' }, [
          h('span', { class: 'tree-rel-verb', text: item.relation_label }),
        ]);
        row.append(treeRow(item.node, ontology, actions, childAncestry));
        body.append(row);
      }
    }
    if (!any) body.append(h('p', { class: 'muted', text: 'No traced relations.' }));
  });

  return details;
}
