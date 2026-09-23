// Project configuration: which element types and relations a project uses.
//
// One picker serves both "New project" and "Customise this project". It is
// generated from GET /api/project/configuration: the presets (Light, Full)
// come from the ontology file, and so does the catalogue of types and
// relations, so a tailored ontology produces a tailored picker.

import { h } from './forms.js';

const CATEGORY_ORDER = ['Why', 'What', 'How', 'Who', 'When'];

/**
 * Build the picker.
 *
 * @param config  the /api/project/configuration payload
 * @param initial {preset, node_types, edge_types} to start from
 * @param lockInUse  when customising a live project: anything with elements
 *                   in it stays ticked, because switching it off would strand them
 * @returns {{element: HTMLElement, value: () => object}}
 */
export function buildTypePicker(config, { initial, lockInUse = false } = {}) {
  const nodeSpecs = config.catalogue.node_types;
  const edgeSpecs = config.catalogue.edge_types;
  const known = new Set(nodeSpecs.map((n) => n.name));
  const presets = config.presets;

  let preset = initial?.preset || 'full';
  const selectedNodes = new Set(initial?.node_types || nodeSpecs.map((n) => n.name));
  const selectedEdges = new Set(initial?.edge_types || edgeSpecs.map((e) => e.name));

  const nodeBoxes = new Map();
  const edgeBoxes = new Map();
  const edgeNotes = new Map();
  const cards = new Map();
  const summary = h('div', { class: 'picker-summary' });

  // A relation end is satisfied by a selected type, a wildcard, or an abstract
  // ancestor (which is not in the catalogue and so cannot be deselected).
  const endOpen = (names) => !names.length
    || names.some((name) => name === '*' || !known.has(name) || selectedNodes.has(name));
  const available = (spec) => endOpen(spec.domain) && endOpen(spec.range);
  const locked = (spec) => lockInUse && spec.in_use > 0;

  function refresh() {
    for (const spec of nodeSpecs) nodeBoxes.get(spec.name).checked = selectedNodes.has(spec.name);
    for (const spec of edgeSpecs) {
      const box = edgeBoxes.get(spec.name);
      const open = available(spec);
      if (!open) selectedEdges.delete(spec.name);
      box.disabled = !open || locked(spec);
      box.checked = open && selectedEdges.has(spec.name);
      const missing = [...spec.domain, ...spec.range].filter((n) => known.has(n) && !selectedNodes.has(n));
      edgeNotes.get(spec.name).textContent = open ? '' : `needs ${[...new Set(missing)].join(' or ')}`;
    }
    for (const [name, card] of cards) card.classList.toggle('active', name === preset);
    const edges = edgeSpecs.filter((spec) => selectedEdges.has(spec.name) && available(spec)).length;
    summary.textContent = `${selectedNodes.size} element type${selectedNodes.size === 1 ? '' : 's'} · `
      + `${edges} relation${edges === 1 ? '' : 's'}`;
  }

  function applyPreset(name) {
    const chosen = presets.find((p) => p.name === name);
    preset = name;
    if (chosen) {
      selectedNodes.clear();
      chosen.node_types.forEach((n) => selectedNodes.add(n));
      selectedEdges.clear();
      chosen.edge_types.forEach((n) => selectedEdges.add(n));
    }
    // Never drop what the project already uses.
    for (const spec of nodeSpecs) if (locked(spec)) selectedNodes.add(spec.name);
    for (const spec of edgeSpecs) if (locked(spec)) selectedEdges.add(spec.name);
    refresh();
  }

  // ---- preset cards
  const cardRow = h('div', { class: 'preset-row' });
  for (const p of [...presets, { name: 'custom', label: 'Custom', description: 'Start from either and tick exactly the element types and relations this project needs.' }]) {
    const counts = p.node_types
      ? `${p.node_types.length} types · ${p.edge_types.length} relations`
      : 'your selection';
    const card = h('button', {
      type: 'button',
      class: 'preset-card',
      'data-preset': p.name,
      onClick: () => {
        if (p.name !== 'custom') { applyPreset(p.name); return; }
        preset = 'custom';
        refresh();
      },
    }, [
      h('strong', { text: p.label }),
      h('span', { class: 'preset-counts', text: counts }),
      h('span', { class: 'preset-desc', text: p.description }),
    ]);
    cards.set(p.name, card);
    cardRow.append(card);
  }

  // ---- element types, by management question
  const nodeHost = h('div', { class: 'picker-columns' });
  const byCategory = new Map();
  for (const spec of nodeSpecs) {
    if (!byCategory.has(spec.category)) byCategory.set(spec.category, []);
    byCategory.get(spec.category).push(spec);
  }
  const rank = (category) => {
    const index = CATEGORY_ORDER.indexOf(category);
    return index === -1 ? CATEGORY_ORDER.length : index;
  };
  const categories = [...byCategory.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  for (const category of categories) {
    const group = h('fieldset', { class: 'picker-group' }, [h('legend', { text: category })]);
    for (const spec of byCategory.get(category)) {
      const box = h('input', {
        type: 'checkbox',
        name: `type-${spec.name}`,
        value: spec.name,
        disabled: locked(spec),
        onChange: (event) => {
          const becameOpen = [];
          if (event.target.checked) {
            // Bring along the relations this type makes possible.
            for (const edge of edgeSpecs) if (!available(edge)) becameOpen.push(edge);
            selectedNodes.add(spec.name);
            for (const edge of becameOpen) if (available(edge)) selectedEdges.add(edge.name);
          } else {
            selectedNodes.delete(spec.name);
          }
          preset = 'custom';
          refresh();
        },
      });
      nodeBoxes.set(spec.name, box);
      group.append(h('label', { class: 'picker-item', title: spec.description || '' }, [
        box,
        h('i', { class: 'status-dot', style: `background:${spec.color}` }),
        h('span', { text: spec.label }),
        locked(spec) ? h('span', { class: 'tag', text: `${spec.in_use} in use` }) : null,
      ]));
    }
    nodeHost.append(group);
  }

  // ---- relations
  const edgeHost = h('div', { class: 'picker-relations' });
  for (const spec of edgeSpecs) {
    const box = h('input', {
      type: 'checkbox',
      name: `rel-${spec.name}`,
      value: spec.name,
      onChange: (event) => {
        if (event.target.checked) selectedEdges.add(spec.name); else selectedEdges.delete(spec.name);
        preset = 'custom';
        refresh();
      },
    });
    const note = h('span', { class: 'picker-note' });
    edgeBoxes.set(spec.name, box);
    edgeNotes.set(spec.name, note);
    edgeHost.append(h('label', { class: 'picker-item', title: spec.description || '' }, [
      box,
      h('span', { text: spec.label }),
      h('span', { class: 'muted picker-ends', text: `${spec.domain.join('/') || 'any'} → ${spec.range.join('/') || 'any'}` }),
      locked(spec) ? h('span', { class: 'tag', text: `${spec.in_use} in use` }) : null,
      note,
    ]));
  }

  const element = h('div', { class: 'type-picker' }, [
    cardRow,
    summary,
    h('div', { class: 'form-group-title', text: 'Element types' }),
    nodeHost,
    h('details', { class: 'picker-rel-wrap' }, [
      h('summary', { text: 'Relations' }),
      h('p', { class: 'help', text: 'A relation is available when both its ends are selected. Ticking an element type brings along the relations it makes possible.' }),
      edgeHost,
    ]),
  ]);
  // Whatever the starting point, what the project already uses stays ticked.
  for (const spec of nodeSpecs) if (locked(spec)) selectedNodes.add(spec.name);
  for (const spec of edgeSpecs) if (locked(spec)) selectedEdges.add(spec.name);
  refresh();

  return {
    element,
    value() {
      // Full is stored as "everything", so types the ontology gains later appear.
      if (preset === 'full') return { preset: 'full' };
      return {
        preset,
        node_types: [...selectedNodes],
        edge_types: edgeSpecs.filter((s) => selectedEdges.has(s.name) && available(s)).map((s) => s.name),
      };
    },
  };
}

/** One line describing a profile: "Light · 8 element types · 15 relations". */
export function describeProfile(config) {
  const presetName = config.profile?.preset || 'full';
  const preset = config.presets.find((p) => p.name === presetName);
  const label = preset ? preset.label : presetName.charAt(0).toUpperCase() + presetName.slice(1);
  return `${label} · ${config.active.node_types.length} element types · ${config.active.edge_types.length} relations`;
}
