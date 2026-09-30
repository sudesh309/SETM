// The start page, and the new-project wizard.
//
// SETM opens here with nothing loaded. From here a project is created (with the
// element types and relations it needs), opened from the list, or loaded -- a
// worked example or a project file, each as a project of its own, so loading
// never overwrites anything.

import { h } from './forms.js';
import { buildTypePicker } from './configure.js';
import { elementTypeForm, relationForm } from './ontologies.js';

/**
 * @param listing   GET /api/projects
 * @param examples  GET /api/examples .examples
 * @param actions   {onCreate(), onOpen(project), onLoadExample(name), onImport(text, filename)}
 */
export function renderHome(container, listing, examples, actions) {
  const open = listing.projects.find((p) => p.current);
  const hero = h('div', { class: 'home-hero' }, [
    h('h1', { text: open ? 'Projects' : 'Welcome to SETM' }),
    h('p', { class: 'muted', text: open
      ? `You are working on ${open.name}. Open another, start a new one, or load an example.`
      : 'Nothing is open yet. Create a project, open one you have worked on, or load an example to explore.' }),
  ]);

  const create = h('div', { class: 'card home-card home-create' }, [
    h('h3', { text: 'Create a new project' }),
    h('p', { class: 'muted', text: 'Name it, choose which element types and relations it uses (Light, Full or your own mix), and add any it needs that the master does not have.' }),
    h('button', { class: 'btn btn-primary btn-large', id: 'btn-create-project', text: '+ Create new project', onClick: actions.onCreate }),
  ]);

  const exampleSelect = h('select', { id: 'home-example' }, (examples || []).map((e) => h('option', { value: e.name, text: e.label })));
  const exampleHelp = h('div', { class: 'help', text: examples?.[0]?.description || '' });
  exampleSelect.addEventListener('change', () => {
    exampleHelp.textContent = examples.find((e) => e.name === exampleSelect.value)?.description || '';
  });
  const fileInput = h('input', { type: 'file', accept: 'application/json,.json', style: 'display:none', id: 'home-import-file' });
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    try {
      await actions.onImport(await file.text(), file.name);
    } finally {
      fileInput.value = '';
    }
  });
  const load = h('div', { class: 'card home-card' }, [
    h('h3', { text: 'Load' }),
    h('div', { class: 'form-field' }, [
      h('label', { for: 'home-example', text: 'A worked example' }),
      h('div', { class: 'inline-row' }, [
        exampleSelect,
        h('button', { class: 'btn', id: 'btn-load-example', text: 'Load example', onClick: () => actions.onLoadExample(exampleSelect.value) }),
      ]),
      exampleHelp,
    ]),
    h('div', { class: 'form-field' }, [
      h('label', { text: 'A project file (.json exported from SETM)' }),
      h('button', { class: 'btn', id: 'btn-import-project', text: 'Import file…', onClick: () => fileInput.click() }),
      fileInput,
    ]),
    h('p', { class: 'help', text: 'Either becomes a project of its own; nothing you have is replaced.' }),
  ]);

  const list = h('div', { class: 'project-list', id: 'home-projects' });
  if (!listing.projects.length) {
    list.append(h('div', { class: 'muted', text: 'No projects yet.' }));
  }
  for (const project of listing.projects) {
    const preset = project.preset ? project.preset.charAt(0).toUpperCase() + project.preset.slice(1) : '';
    const detail = project.error
      ? `Cannot be read: ${project.error}`
      : [project.programme, `${project.elements} elements`, preset && `${preset} set of element types`].filter(Boolean).join(' · ');
    list.append(h('div', { class: `project-row${project.current ? ' current' : ''}`, 'data-name': project.name }, [
      h('div', { class: 'project-row-main' }, [
        h('strong', { text: project.name }),
        h('div', { class: 'muted', text: detail }),
        h('div', { class: 'mono faint', text: project.storage }),
      ]),
      project.current
        ? h('span', { class: 'pill', text: 'open' })
        : h('button', { class: 'btn', text: 'Open', disabled: Boolean(project.error), onClick: () => actions.onOpen(project) }),
    ]));
  }

  container.replaceChildren(h('div', { class: 'home' }, [
    hero,
    h('div', { class: 'home-grid' }, [create, load]),
    h('div', { class: 'card' }, [
      h('div', { class: 'card-head' }, [
        h('h3', { text: 'Your projects' }),
        h('span', { class: 'muted', text: `kept in ${listing.projects_dir}` }),
      ]),
      list,
    ]),
  ]));
}

// --------------------------------------------------------------------------- //
// New project wizard: 1 details · 2 from the master · 3 its own additions
// --------------------------------------------------------------------------- //

/** Mirrors setm.ontology.project.type_identifier, so new types can be linked before they exist. */
export function typeIdentifier(label) {
  const words = (label || '').match(/[A-Za-z0-9]+/g) || [];
  const ident = words.map((w) => w[0].toUpperCase() + w.slice(1)).join('');
  return /^[A-Za-z]/.test(ident) ? ident : `T${ident}`;
}

/**
 * @param config   GET /api/ontologies/catalogue
 * @param options  {dirty, onCreate(payload) -> Promise, setError(message)}
 */
export function buildProjectWizard(config, { dirty, onCreate, setError }) {
  const light = config.presets.find((p) => p.name === 'light');
  const picker = buildTypePicker(config, { initial: light ? { ...light, preset: 'light' } : undefined });
  const additions = { element_types: [], relations: [] };
  let step = 1;

  const input = (name, placeholder = '') => h('input', { type: 'text', id: `np-${name}`, name, placeholder });
  const details = h('div', { class: 'wizard-step', 'data-step': 1 }, [
    h('div', { class: 'np-grid' }, [
      h('div', { class: 'form-field required' }, [h('label', { for: 'np-name', text: 'Project name' }), input('name', 'e.g. Cabin retrofit, phase B')]),
      h('div', { class: 'form-field' }, [h('label', { for: 'np-programme', text: 'Programme' }), input('programme')]),
      h('div', { class: 'form-field' }, [h('label', { for: 'np-phase', text: 'Phase' }), input('phase', 'e.g. B')]),
      h('div', { class: 'form-field' }, [h('label', { for: 'np-chief_engineer', text: 'Chief engineer' }), input('chief_engineer')]),
    ]),
    h('div', { class: 'form-field' }, [h('label', { for: 'np-description', text: 'Description' }), h('textarea', { id: 'np-description', name: 'description', rows: 2 })]),
    h('div', { class: 'form-field' }, [
      h('label', { for: 'np-format', text: 'Stored as' }),
      h('select', { id: 'np-format', name: 'format' }, [
        h('option', { value: 'json', text: 'JSON file — simplest, easy to back up and compare' }),
        h('option', { value: 'sqlite', text: 'SQLite database — better for large projects' }),
      ]),
    ]),
    dirty ? h('p', { class: 'setting-warn', text: 'The project you are in has unsaved changes. Creating a new one opens it and discards them — Save first to keep them.' }) : null,
  ]);

  const fromMaster = h('div', { class: 'wizard-step', 'data-step': 2 }, [
    h('p', { class: 'muted', text: 'Which element types and relations from the master ontology this project uses. The project keeps its own copy; you can add more from the master later.' }),
    picker.element,
  ]);

  const ownList = h('div', { class: 'own-list', id: 'wizard-own-list' });
  const ownHost = h('div', { class: 'own-form' });
  const chosenTypes = () => {
    const value = picker.value();
    const names = value.node_types || config.catalogue.node_types.map((t) => t.name);
    const fromMasterTypes = config.catalogue.node_types.filter((t) => names.includes(t.name)).map((t) => ({ name: t.name, label: t.label }));
    return [...fromMasterTypes, ...additions.element_types.map((t) => ({ name: typeIdentifier(t.label), label: t.label }))];
  };
  const renderOwn = () => {
    ownList.replaceChildren();
    if (!additions.element_types.length && !additions.relations.length) {
      ownList.append(h('div', { class: 'muted', text: 'Nothing added yet — this step is optional.' }));
    }
    additions.element_types.forEach((t, i) => ownList.append(h('div', { class: 'own-item' }, [
      h('i', { class: 'status-dot', style: `background:${t.color}` }),
      h('strong', { text: t.label }), h('span', { class: 'muted', text: ` element type · ${t.category} · ${t.properties.length} extra properties` }),
      h('button', { class: 'btn btn-icon', type: 'button', text: '×', title: 'Remove', onClick: () => { additions.element_types.splice(i, 1); renderOwn(); } }),
    ])));
    additions.relations.forEach((r, i) => ownList.append(h('div', { class: 'own-item' }, [
      h('strong', { text: r.label }), h('span', { class: 'muted', text: ` relation · ${r.domain.join(', ')} → ${r.range.join(', ')}` }),
      h('button', { class: 'btn btn-icon', type: 'button', text: '×', title: 'Remove', onClick: () => { additions.relations.splice(i, 1); renderOwn(); } }),
    ])));
  };
  const openForm = (kind) => {
    setError('');
    const form = kind === 'type' ? elementTypeForm() : relationForm(chosenTypes());
    ownHost.replaceChildren(h('div', { class: 'card own-form-card' }, [
      h('h4', { text: kind === 'type' ? 'New element type' : 'New relation' }),
      form.element,
      h('div', { class: 'inline-row' }, [
        h('button', {
          class: 'btn btn-primary', type: 'button', id: 'btn-own-add', text: 'Add',
          onClick: () => {
            const data = form.read();
            if (!data.label) { setError('Give it a name'); return; }
            if (kind === 'type') {
              if (chosenTypes().some((t) => t.name === typeIdentifier(data.label))) { setError(`There is already an element type called ${data.label}`); return; }
              additions.element_types.push(data);
            } else {
              if (!data.domain.length || !data.range.length) { setError('Tick at least one element type on each side'); return; }
              additions.relations.push(data);
            }
            ownHost.replaceChildren();
            setError('');
            renderOwn();
          },
        }),
        h('button', { class: 'btn', type: 'button', text: 'Cancel', onClick: () => ownHost.replaceChildren() }),
      ]),
    ]));
  };
  const own = h('div', { class: 'wizard-step', 'data-step': 3 }, [
    h('p', { class: 'muted', text: 'Element types and relations only this project needs. They live in the project\'s own ontology; later, you can copy them to the master from the Ontologies page.' }),
    h('div', { class: 'inline-row' }, [
      h('button', { class: 'btn', type: 'button', id: 'btn-own-type', text: '+ Element type', onClick: () => openForm('type') }),
      h('button', { class: 'btn', type: 'button', id: 'btn-own-relation', text: '+ Relation', onClick: () => openForm('relation') }),
    ]),
    ownHost,
    ownList,
  ]);
  renderOwn();

  const steps = [
    [1, 'Project'], [2, 'From the master'], [3, 'Its own additions'],
  ];
  const stepper = h('ol', { class: 'stepper' });
  const back = h('button', { class: 'btn', type: 'button', id: 'wizard-back', text: '◀ Back' });
  const next = h('button', { class: 'btn btn-primary', type: 'button', id: 'wizard-next', text: 'Next ▶' });
  const create = h('button', { class: 'btn btn-primary', type: 'button', id: 'wizard-create', text: 'Create project' });
  const nameValue = () => details.querySelector('[name="name"]').value.trim();

  const show = () => {
    for (const panel of [details, fromMaster, own]) panel.classList.toggle('hidden', Number(panel.dataset.step) !== step);
    stepper.replaceChildren(...steps.map(([n, label]) => h('li', { class: n === step ? 'on' : n < step ? 'done' : '' }, [
      h('span', { class: 'step-n', text: n }), label,
    ])));
    back.classList.toggle('hidden', step === 1);
    next.classList.toggle('hidden', step === 3);
  };
  back.addEventListener('click', () => { step -= 1; setError(''); show(); });
  next.addEventListener('click', () => {
    if (step === 1 && !nameValue()) { setError('Give the project a name'); return; }
    setError('');
    step += 1;
    show();
  });
  create.addEventListener('click', async () => {
    if (!nameValue()) { step = 1; show(); setError('Give the project a name'); return; }
    const value = (name) => (details.querySelector(`[name="${name}"]`)?.value || '').trim();
    create.disabled = true;
    setError('');
    try {
      await onCreate({
        name: nameValue(),
        programme: value('programme'),
        phase: value('phase'),
        chief_engineer: value('chief_engineer'),
        description: value('description'),
        format: value('format') || 'json',
        ...picker.value(),
        additions,
        open: true,
        force: dirty,
      });
    } catch (error) {
      setError(error.message);
    } finally {
      create.disabled = false;
    }
  });

  const element = h('div', { class: 'wizard' }, [
    stepper, details, fromMaster, own,
    h('div', { class: 'wizard-nav' }, [back, h('span', { class: 'spacer' }), next, create]),
  ]);
  show();
  return element;
}
