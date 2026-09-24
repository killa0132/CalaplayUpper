// ==========================================================================
// Settings that must outlive the window.
//
// `localStorage` looks like the obvious home for the onboarding flag / language
// / theme / split ratio, and it is NOT one here: the page is served from
// http://127.0.0.1:<random port>/ and the port changes on every launch, so the
// origin changes with it and the WebView2 profile starts empty every time
// (that was the "引导每次打开都会弹" bug).  The durable copy lives in
// %LOCALAPPDATA%\CalaPlayerSrcmBuilder\prefs.json, behind /api/prefs.
//
// Reads are synchronous (`get`) because the values are needed during the very
// first render (theme + language) and by components' mount logic -- so `load()`
// is awaited once in main.js *before* the app is mounted, and everything after
// that reads the local cache.  localStorage is kept in sync as a fallback, which
// is what keeps `npm run dev` (a vite origin) working.
// ==========================================================================
import { api } from './api.js'

const cache = {}
let loaded = false

function lsGet(k) {
  try { return localStorage.getItem(k) } catch (e) { return null }
}
function lsSet(k, v) {
  try { localStorage.setItem(k, v) } catch (e) { /* ignore */ }
}

//: pull the backend copy once; a failure (dev server, offline backend) simply
//: leaves the localStorage fallback in charge
export async function load() {
  try {
    const r = await api.prefs()
    if (r && r.prefs) Object.assign(cache, r.prefs)
  } catch (e) { /* ignore */ }
  loaded = true
  return cache
}

export function get(key, fallback) {
  if (Object.prototype.hasOwnProperty.call(cache, key)) return cache[key]
  const v = lsGet(key)
  return v === null || v === undefined ? fallback : v
}

export function set(key, value) {
  const v = String(value)
  cache[key] = v
  lsSet(key, v)
  // fire and forget: a failed write only means "not remembered next launch"
  try { api.putPrefs({ [key]: v }).catch(() => {}) } catch (e) { /* ignore */ }
  return v
}

export function isLoaded() { return loaded }
export function snapshot() { return { ...cache } }
