// Thin wrapper over the SETM HTTP API.
// Every call goes through request(), so error shaping and the actor header are
// defined in exactly one place.

const TOKEN_KEY = 'setm.token';
const USER_KEY = 'setm.user';

export function setToken(value) { localStorage.setItem(TOKEN_KEY, value || ''); }
export function getUser() { return localStorage.getItem(USER_KEY) || ''; }
export function setUser(value) { localStorage.setItem(USER_KEY, value || ''); }

async function request(method, path, { body, query } = {}) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(query || {})) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, v));
    else url.searchParams.set(key, value);
  }

  const headers = {};
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers['X-SETM-Token'] = token;
  const user = getUser();
  if (user) headers['X-SETM-User'] = user;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const response = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const text = await response.text();
  const contentType = response.headers.get('Content-Type') || '';
  const payload = contentType.includes('application/json') && text ? JSON.parse(text) : text;

  if (!response.ok) {
    const detail = payload && payload.error ? payload.error : { message: String(payload || response.statusText) };
    const error = new Error(detail.message || 'Request failed');
    error.code = detail.code;
    error.issues = detail.issues || [];
    error.status = response.status;
    throw error;
  }
  return payload;
}

export const api = {
  health: () => request('GET', '/api/health'),
  ontology: () => request('GET', '/api/ontology'),
  reloadOntology: () => request('POST', '/api/ontology/reload', { body: {} }),

  project: () => request('GET', '/api/project'),
  updateProject: (values) => request('PATCH', '/api/project', { body: values }),

  graph: (query) => request('GET', '/api/graph', { query }),
  nodes: (query) => request('GET', '/api/nodes', { query }),
  node: (id) => request('GET', `/api/nodes/${encodeURIComponent(id)}`),
  createNode: (body) => request('POST', '/api/nodes', { body }),
  updateNode: (id, body) => request('PATCH', `/api/nodes/${encodeURIComponent(id)}`, { body }),
  deleteNode: (id) => request('DELETE', `/api/nodes/${encodeURIComponent(id)}`),

  edges: (query) => request('GET', '/api/edges', { query }),
  allowedEdges: (query) => request('GET', '/api/edges/allowed', { query }),
  createEdge: (body) => request('POST', '/api/edges', { body }),
  updateEdge: (id, body) => request('PATCH', `/api/edges/${encodeURIComponent(id)}`, { body }),
  deleteEdge: (id) => request('DELETE', `/api/edges/${encodeURIComponent(id)}`),

  trace: (id, depth) => request('GET', `/api/nodes/${encodeURIComponent(id)}/trace`, { query: { depth } }),
  context: (id, query) => request('GET', `/api/nodes/${encodeURIComponent(id)}/context`, { query }),
  impact: (id, query) => request('GET', `/api/nodes/${encodeURIComponent(id)}/impact`, { query }),
  paths: (query) => request('GET', '/api/paths', { query }),

  settings: () => request('GET', '/api/settings'),
  updateSettings: (body) => request('PATCH', '/api/settings', { body }),
  reopenWorkspace: (force) => request('POST', '/api/settings/reopen', { body: { force } }),
  testStorage: (body) => request('POST', '/api/settings/test-storage', { body }),

  examples: () => request('GET', '/api/examples'),
  loadExample: (name) => request('POST', '/api/examples/load', { body: { name } }),
  importDocument: (document, merge) => request('POST', '/api/import', { body: { document, merge } }),

  kpi: (section) => request('GET', '/api/kpi', { query: { section } }),
  appKpi: () => request('GET', '/api/kpi/app'),
  validate: () => request('GET', '/api/validate'),

  save: (message) => request('POST', '/api/save', { body: { message } }),
  reload: () => request('POST', '/api/reload', { body: {} }),
  exportUrl: (format) => `/api/export?format=${encodeURIComponent(format)}`,
};
