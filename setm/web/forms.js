// Ontology-driven form generation.
//
// No form in this application is hand-written: the widgets, their grouping,
// their help text and their validation all come from the ontology file. Add a
// property there and the dialog grows a field on the next reload.

// Builds DOM nodes. Text always goes in through textContent or text nodes, never
// innerHTML, so nothing read from the graph can be interpreted as markup.
export function h(tag, attributes = {}, children = []) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') element.className = value;
    else if (key === 'text') element.textContent = value;
    else if (key.startsWith('on') && typeof value === 'function') {
      element.addEventListener(key.slice(2).toLowerCase(), value);
    } else element.setAttribute(key, value === true ? '' : value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}

function widgetFor(spec, value) {
  const name = `prop-${spec.name}`;
  const ui = spec.ui || {};

  if (spec.type === 'enum') {
    const select = h('select', { name, id: name });
    select.append(h('option', { value: '', text: spec.required ? '— choose —' : '— none —' }));
    for (const option of spec.values || []) {
      select.append(h('option', { value: option, text: option.replace(/_/g, ' '), selected: String(value) === option }));
    }
    return select;
  }
  if (spec.type === 'boolean') {
    return h('select', { name, id: name }, [
      h('option', { value: '', text: '— none —', selected: value === undefined || value === null || value === '' }),
      h('option', { value: 'true', text: 'yes', selected: value === true }),
      h('option', { value: 'false', text: 'no', selected: value === false }),
    ]);
  }
  if (spec.type === 'text' || ui.widget === 'textarea') {
    return h('textarea', { name, id: name, rows: ui.rows || 3, text: value ?? '' });
  }
  if (spec.type === 'integer' || spec.type === 'number') {
    return h('input', {
      type: 'number', name, id: name,
      step: spec.type === 'integer' ? '1' : 'any',
      min: spec.minimum, max: spec.maximum,
      value: value ?? '',
    });
  }
  if (spec.type === 'list') {
    return h('input', {
      type: 'text', name, id: name,
      value: Array.isArray(value) ? value.join(', ') : (value ?? ''),
      placeholder: 'comma separated',
    });
  }
  if (spec.type === 'date') {
    return h('input', { type: 'date', name, id: name, value: value ?? '' });
  }
  return h('input', {
    type: 'text', name, id: name, value: value ?? '',
    autofocus: ui.autofocus || false,
    pattern: spec.pattern || undefined,
  });
}

/** Build a grouped property form for a node or edge type. */
export function buildPropertyForm(typeSpec, values = {}) {
  const form = h('form', { class: 'property-form', autocomplete: 'off' });
  const groups = new Map();

  for (const spec of Object.values(typeSpec.properties || {})) {
    const group = spec.group || 'General';
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(spec);
  }

  // 'Identity' first: it holds the name, which is what people type first.
  const ordered = [...groups.keys()].sort((a, b) => {
    if (a === 'Identity') return -1;
    if (b === 'Identity') return 1;
    return a.localeCompare(b);
  });

  for (const group of ordered) {
    form.append(h('div', { class: 'form-group-title', text: group }));
    for (const spec of groups.get(group)) {
      const field = h('div', { class: `form-field${spec.required ? ' required' : ''}` });
      field.append(h('label', { for: `prop-${spec.name}`, text: spec.label + (spec.unit ? ` (${spec.unit})` : '') }));
      field.append(widgetFor(spec, values[spec.name]));
      if (spec.description) field.append(h('div', { class: 'help', text: spec.description }));
      form.append(field);
    }
  }
  return form;
}

/** Read a generated form back into a properties object. */
export function readPropertyForm(form, typeSpec) {
  const out = {};
  for (const spec of Object.values(typeSpec.properties || {})) {
    const field = form.elements[`prop-${spec.name}`];
    if (!field) continue;
    const raw = field.value.trim();
    if (raw === '') {
      out[spec.name] = null; // explicit null clears a stored value
      continue;
    }
    if (spec.type === 'list') out[spec.name] = raw.split(',').map((v) => v.trim()).filter(Boolean);
    else if (spec.type === 'integer') out[spec.name] = parseInt(raw, 10);
    else if (spec.type === 'number') out[spec.name] = parseFloat(raw);
    else if (spec.type === 'boolean') out[spec.name] = raw === 'true';
    else out[spec.name] = raw;
  }
  return out;
}

/** A searchable element picker backed by the loaded graph. */
export function nodePicker(nodes, { name, value = '', placeholder = 'Search elements…', onChange } = {}) {
  const wrapper = h('div', { class: 'picker' });
  const listId = `picker-${name}-${Math.random().toString(36).slice(2, 8)}`;
  const input = h('input', { type: 'text', name, id: `prop-${name}`, list: listId, placeholder, value });
  const datalist = h('datalist', { id: listId });
  for (const node of nodes) {
    datalist.append(h('option', { value: node.id, label: `${node.label} · ${node.type}` }));
  }
  if (onChange) input.addEventListener('change', () => onChange(input.value));
  wrapper.append(input, datalist);
  return wrapper;
}

export function formatValue(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'string') return value.replace(/_/g, ' ');
  return String(value);
}
