/**
 * engine_selector.js — U4, "unified panel" track. Collapse the five stacked
 * simulation panels (oxDNA / LAMMPS / mrDNA / CanDo / NAMD) into ONE Simulate
 * section fronted by an engine selector.
 *
 * Today the five `*_jobs_panel.js` panels stack vertically in the Dynamics tab,
 * all visible at once, and where an engine can't do a card the panel simply omits
 * it — so "unsupported" reads as "missing". This module is the selector that
 * fronts them: a dropdown (one option per engine, in the U1 `ENGINE_KEYS` order)
 * shows EXACTLY the selected engine's panel and hides the rest.
 *
 * It owns no engine logic and no panel internals: it toggles whole-panel
 * `display` (the panels own their own collapse/advanced/poll — none of them
 * touch whole-panel display, so the selector is the sole owner). The pure
 * decisions (`panelVisibility`, `selectedEngineCards`) are exported for the unit
 * oracle; the factory wires the panel visibility to the DOM.
 */

import {
  ENGINE_KEYS, ENGINE_LABELS, engineCards,
} from './engine_capabilities.js'

// ── Pure selector state (unit-tested against the U1 descriptor) ───────────────

/**
 * engineKey -> boolean shown. Exactly the selected engine's panel is visible;
 * every other engine's panel is hidden. Unknown selections hide everything.
 */
export function panelVisibility(selectedEngine) {
  const out = {}
  for (const k of ENGINE_KEYS) out[k] = k === selectedEngine
  return out
}

/**
 * The full card census for the selected engine, straight from U1: every
 * per-engine card (the `CARD_KEYS` universe — the cross-engine `GLOBAL_CARDS`
 * live once, outside the selector), each tagged `state:'enabled'` (the panel
 * renders it today) or `state:'greyed'` (unsupported — present WITH a why-reason,
 * never absent). This is what the capability strip renders and what the selector
 * exposes to a future unified card stack. Unknown engines yield an empty census.
 */
export function selectedEngineCards(selectedEngine) {
  return engineCards(selectedEngine).map((c) => ({
    key: c.key,
    label: c.label,
    state: c.enabled ? 'enabled' : 'greyed',
    reason: c.reason,
    domAnchorId: c.domAnchorId,
  }))
}

/** Is `engineKey` a known selectable engine? */
export function isEngine(engineKey) {
  return ENGINE_KEYS.includes(engineKey)
}

// ── Stateful factory (wires the pure decisions to the DOM) ────────────────────

/**
 * @param {object}   deps
 * @param {Element}  deps.selectorMount  where the dropdown is rendered
 * @param {Object<string,Element>} deps.panelEls  engineKey -> panel-section element
 * @param {string}   [deps.initial]      engine selected on init (default first key)
 * @param {Object<string,string>} [deps.labels]   engineKey -> display label
 * @param {(engineKey:string)=>void} [deps.onSelect]  fired after each selection
 * @returns {{ select:(k:string)=>void, getSelected:()=>string, el:Element }}
 */
export function initEngineSelector({
  selectorMount,
  panelEls,
  initial = ENGINE_KEYS[0],
  labels = ENGINE_LABELS,
  onSelect = null,
}) {
  let _selected = null

  // Build the dropdown once.
  selectorMount.classList.add('engine-selector')
  const dropdown = document.createElement('select')
  dropdown.className = 'engine-selector-dropdown'
  dropdown.setAttribute('aria-label', 'Simulation engine')
  for (const key of ENGINE_KEYS) {
    const opt = document.createElement('option')
    opt.value = key
    opt.textContent = labels[key] ?? key
    dropdown.appendChild(opt)
  }
  dropdown.addEventListener('change', () => select(dropdown.value))
  selectorMount.appendChild(dropdown)

  function select(engineKey) {
    if (!isEngine(engineKey)) return
    _selected = engineKey
    const vis = panelVisibility(engineKey)
    for (const key of ENGINE_KEYS) {
      const el = panelEls?.[key]
      if (el) el.style.display = vis[key] ? '' : 'none'
      else console.warn(`[engine-selector] no panel element for "${key}" — its panel won't hide/show`)
    }
    if (dropdown.value !== engineKey) dropdown.value = engineKey
    if (onSelect) onSelect(engineKey)
  }

  select(isEngine(initial) ? initial : ENGINE_KEYS[0])

  return {
    select,
    getSelected: () => _selected,
    el: selectorMount,
  }
}
