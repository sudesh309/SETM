// Thin wrapper over the SETM HTTP API.
// Every call goes through request(), so error shaping and the actor header are
// defined in exactly one place.

const TOKEN_KEY = 'setm.token';
const USER_KEY = 'setm.user';

export function setToken(value) { localStorage.setItem(TOKEN_KEY, value || ''); }
export function getUser() { return localStorage.getItem(USER_KEY) || ''; }
export function setUser(value) { localStorage.setItem(USER_KEY, value || ''); }

function authHeaders() {
  const headers = {};
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers['X-SETM-Token'] = token;
  const user = getUser();
  if (user) headers['X-SETM-User'] = user;
  return headers;
}

function errorFrom(response, payload) {
  const detail = payload && payload.error ? payload.error : { message: String(payload || response.statusText) };
  const error = new Error(detail.message || 'Request failed');
  error.code = detail.code;
  error.issues = detail.issues || [];
  error.status = response.status;
  return error;
}

// Downloads and previews go through fetch rather than a plain link, so they
// carry the API token header like every other call (a navigation cannot, and
// the server no longer accepts the token in the URL).
export async function download(path, { newTab = false } = {}) {
  // Opened before the await: a window opened after it counts as a popup.
  const win = newTab ? window.open('', '_blank') : null;
  try {
    const response = await fetch(new URL(path, window.location.origin), { headers: authHeaders() });
    if (!response.ok) {
      const text = await response.text();
      let payload = text;
      try { payload = JSON.parse(text); } catch { /* not JSON */ }
      throw errorFrom(response, payload);
    }
    let blob = await response.blob();
    // Show text formats as text in a preview tab instead of offering a download.
    if (newTab && blob.type.startsWith('text/') && !blob.type.startsWith('text/html')) {
      blob = new Blob([blob], { type: 'text/plain;charset=utf-8' });
    }
    const href = URL.createObjectURL(blob);
    setTimeout(() => URL.revokeObjectURL(href), 60_000);
    if (win) {
      win.opener = null;
      win.location.href = href;
      return;
    }
    const link = document.createElement('a');
    link.href = href;
    link.download = filenameFrom(response, path);
    document.body.append(link);
    link.click();
    link.remove();
  } catch (error) {
    if (win) win.close();
    throw error;
  }
}

function filenameFrom(response, path) {
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  if (match) return match[1];
  return new URL(path, window.location.origin).pathname.split('/').filter(Boolean).pop() || 'download';
}

async function request(method, path, { body, query } = {}) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(query || {})) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, v));
    else url.searchParams.set(key, value);
  }

  const headers = authHeaders();
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const response = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const text = await response.text();
  const contentType = response.headers.get('Content-Type') || '';
  const payload = contentType.includes('application/json') && text ? JSON.parse(text) : text;

  if (!response.ok) throw errorFrom(response, payload);
  return payload;
}

export const api = {
  health: () => request('GET', '/api/health'),
  ontology: () => request('GET', '/api/ontology'),
  reloadOntology: () => request('POST', '/api/ontology/reload', { body: {} }),

  project: () => request('GET', '/api/project'),
  updateProject: (values) => request('PATCH', '/api/project', { body: values }),
  configuration: () => request('GET', '/api/project/configuration'),
  setConfiguration: (profile) => request('PUT', '/api/project/configuration', { body: profile }),

  projects: () => request('GET', '/api/projects'),
  createProject: (body) => request('POST', '/api/projects', { body }),
  openProject: (storage, force) => request('POST', '/api/projects/open', { body: { storage, force } }),

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
