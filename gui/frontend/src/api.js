// Thin wrapper around the local FastAPI backend.
// The one-shot token is taken from our own URL (?t=...) and attached to every
// call; EventSource cannot set headers, so the SSE URL carries it as a query
// parameter (the backend accepts both).

const token = new URLSearchParams(location.search).get('t') || ''

function url(path, params) {
  const u = new URL(path, location.origin)
  if (token) u.searchParams.set('t', token)
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== '') u.searchParams.set(k, v)
  }
  return u.toString()
}

async function j(res) {
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail || detail } catch (e) { /* ignore */ }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  return res.json()
}

export const api = {
  token,
  hasToken: !!token,

  start(body) {
    return fetch(url('/api/start'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(j)
  },
  report(id) { return fetch(url('/api/report/' + id)).then(j) },
  cancel(id) { return fetch(url('/api/cancel/' + id), { method: 'POST' }).then(j) },
  selectFolder(kind, dir) { return fetch(url('/api/select_folder', { kind, dir })).then(j) },
  openFolder(taskId, what) { return fetch(url('/api/open_folder', { task_id: taskId, what })).then(j) },
  uninstall(taskId, paks) {
    return fetch(url('/api/uninstall'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_id: taskId, paks })
    }).then(j)
  },
  health() { return fetch(url('/api/health')).then(j) },
  // settings that must survive a restart -- localStorage cannot (the page's
  // origin carries a fresh random port every launch).  See prefs.js.
  prefs() { return fetch(url('/api/prefs')).then(j) },
  putPrefs(body) {
    return fetch(url('/api/prefs'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(j)
  },
  // the failure modal's 导出错误日志 button: opens a native save dialog
  // server-side and writes build log + report there
  exportLog(id) {
    return fetch(url('/api/export_log/' + id), { method: 'POST' }).then(j)
  },
  // The community links are handed to the OS browser by the backend: in
  // WebView2 a plain target="_blank" may simply be swallowed (dead button).
  openUrl(u, dry) {
    return fetch(url('/api/open_url', { url: u, dry: dry ? 1 : '' })).then(j)
  },
  // ... and the QQ group number is copied by the backend for the same reason
  // (navigator.clipboard needs a secure context + gesture and fails silently).
  copyText(t, dry) {
    return fetch(url('/api/copy', { text: t, dry: dry ? 1 : '' })).then(j)
  },

  logs(taskId) { return new EventSource(url('/api/logs/' + taskId)) }
}
