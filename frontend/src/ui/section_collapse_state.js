/**
 * Per-tab persistent collapse state for left-sidebar sub-sections.
 *
 * Each left-sidebar tab (feature-log / dynamics / scene) gets its own
 * independent slice keyed by section id, so sections in different tabs
 * never share state. Persisted to localStorage so the layout survives
 * page reloads.
 *
 * Storage shape:
 *   {
 *     "feature-log": { "feature-log-panel": false },
 *     "dynamics":    { "cluster-panel": false, "physics-section": true, ... },
 *     "scene":       { "camera-panel": false, ... }
 *   }
 */

const STORAGE_KEY = 'nadoc.leftSidebar.sections.v1'

function _read() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return (parsed && typeof parsed === 'object') ? parsed : {}
  } catch {
    return {}
  }
}

function _write(state) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)) } catch {}
}

export function getSectionCollapsed(tab, section, defaultValue = false) {
  const v = _read()[tab]?.[section]
  return typeof v === 'boolean' ? v : defaultValue
}

export function setSectionCollapsed(tab, section, collapsed) {
  const state = _read()
  if (!state[tab] || typeof state[tab] !== 'object') state[tab] = {}
  state[tab][section] = !!collapsed
  _write(state)
}
