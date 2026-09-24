import { createApp } from 'vue'
import App from './App.vue'
import { applyLang, detectLang } from './i18n.js'
import { get as getPref, load as loadPrefs } from './prefs.js'
import './styles/theme.css'
import './styles/uiverse/basic.css'
import './styles/uiverse/switch-theme.css'
import './styles/uiverse/progress.css'
import './styles/uiverse/modal.css'
import './styles/uiverse/border-glow.css'
import './styles/uiverse/onboarding.css'

// The theme and the language have to be right on the FIRST painted frame, and
// the onboarding flag is read by a component's mount hook -- so the durable
// settings are fetched before the app is mounted.  localStorage is per-origin
// and the page gets a fresh random port every launch, which is why they live
// behind /api/prefs (see prefs.js); the inline <script> in index.html still
// applies the localStorage copy as a fallback for `npm run dev`.
async function boot() {
  try { await loadPrefs() } catch (e) { /* ignore */ }
  const theme = getPref('cala-theme', '')
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme
  // Pick the language BEFORE the first render: a zh system shows Chinese,
  // anything else English, and an explicit choice from a previous run wins.
  applyLang(detectLang())
  createApp(App).mount('#app')
}

boot()
