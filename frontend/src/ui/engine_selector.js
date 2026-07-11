/**
 * engine_selector.js — U4, "unified panel" track. Collapse the five stacked
 * simulation panels (oxDNA / LAMMPS / mrDNA / CanDo / NAMD) into ONE Simulate
 * section fronted by an engine selector.
 *
 * Today the five `*_jobs_panel.js` panels stack vertically in the Dynamics tab,
 * all visible at once, and where an engine can't do a card the panel simply omits
 * it — so "unsupported" reads as "missing". This module is the selector that
 * fronts them: a segmented control (one button per engine, in the U1
 * `ENGINE_KEYS` order) shows EXACTLY the selected engine's panel and hides the
 * rest, and a capability card-strip — driven by the U1 descriptor — renders every
 * card in the universe, supported cards as live chips and unsupported cards as
 * GREYED chips carrying the descriptor's why-reason as a tooltip (present, never
 * absent — the "CHARMM-GUI model").
 *
 * It owns no engine logic and no panel internals: it toggles whole-panel
 * `display` (the panels own their own collapse/advanced/poll — none of them
 * touch whole-panel display, so the selector is the sole owner) and reads the
 * card facts from `engine_capabilities.js`. The pure decisions
 * (`panelVisibility`, `selectedEngineCards`) are exported for the unit oracle;
 * the factory wires them to the DOM.
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
 * @param {Element}  deps.selectorMount  where the segmented control is rendered
 * @param {Element}  [deps.stripMount]   optional element for the capability strip
 * @param {Object<string,Element>} deps.panelEls  engineKey -> panel-section element
 * @param {string}   [deps.initial]      engine selected on init (default first key)
 * @param {Object<string,string>} [deps.labels]   engineKey -> display label
 * @param {(engineKey:string)=>void} [deps.onSelect]  fired after each selection
 * @returns {{ select:(k:string)=>void, getSelected:()=>string, el:Element }}
 */
export function initEngineSelector({
  selectorMount,
  stripMount = null,
  panelEls,
  runControlEls = null,
  initial = ENGINE_KEYS[0],
  labels = ENGINE_LABELS,
  onSelect = null,
}) {
  let _selected = null
  const buttons = {}
  const warns = {}   // engineKey → the ⚠ not-installed span in its tab

  // Build the segmented control once. Each tab is [label][⚠ warn], where the warn
  // span is shown when the engine isn't installed (setEngineStatus), tooltip guiding
  // the user to Help ▸ MD Engines.
  selectorMount.classList.add('engine-selector')
  selectorMount.setAttribute('role', 'tablist')
  for (const key of ENGINE_KEYS) {
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.className = 'engine-selector-btn'
    btn.dataset.engine = key
    btn.setAttribute('role', 'tab')
    const lbl = document.createElement('span')
    lbl.className = 'engine-selector-label'
    lbl.textContent = labels[key] ?? key
    const warn = document.createElement('span')
    warn.className = 'engine-warn'
    warn.textContent = '⚠'
    warn.hidden = true
    warn.setAttribute('aria-hidden', 'true')
    btn.append(lbl, warn)
    btn.addEventListener('click', () => select(key))
    selectorMount.appendChild(btn)
    buttons[key] = btn
    warns[key] = warn
  }

  /** Reflect an engine's install status on its tab: show a ⚠ (with a tooltip pointing
   *  at Help ▸ MD Engines) when it isn't installed, hide it when it is. */
  function setEngineStatus(engineKey, { ok = true, reason = '' } = {}) {
    const warn = warns[engineKey]
    const btn = buttons[engineKey]
    if (!warn) return
    warn.hidden = !!ok
    warn.title = ok ? '' : `${reason || 'This engine is not installed.'}\nOpen Help ▸ MD Engines to install.`
    if (btn) btn.classList.toggle('is-uninstalled', !ok)
  }

  // A panel probes its engine's binaries and broadcasts the result; the tab reflects it.
  window.addEventListener('nadoc:engine-availability', (e) => {
    const d = e.detail || {}
    if (d.engine) setEngineStatus(d.engine, d)
  })

  function renderStrip(engineKey) {
    if (!stripMount) return
    stripMount.replaceChildren()
    stripMount.classList.add('engine-capability-strip')
    for (const card of selectedEngineCards(engineKey)) {
      const chip = document.createElement('span')
      chip.className = `capability-chip is-${card.state}`
      chip.dataset.card = card.key
      chip.textContent = card.label
      if (card.state === 'greyed' && card.reason) {
        chip.title = card.reason
        chip.setAttribute('aria-disabled', 'true')
      } else if (card.domAnchorId) {
        chip.dataset.anchor = card.domAnchorId
      }
      stripMount.appendChild(chip)
    }
  }

  function select(engineKey) {
    if (!isEngine(engineKey)) return
    _selected = engineKey
    const vis = panelVisibility(engineKey)
    for (const key of ENGINE_KEYS) {
      const el = panelEls?.[key]
      if (el) el.style.display = vis[key] ? '' : 'none'
      else console.warn(`[engine-selector] no panel element for "${key}" — its panel won't hide/show`)
      // The run-control cluster (Relax/Coarse/Fine/… above the jobs card) tracks the tab.
      const rc = runControlEls?.[key]
      if (rc) rc.style.display = vis[key] ? '' : 'none'
      const btn = buttons[key]
      if (btn) {
        const active = key === engineKey
        btn.classList.toggle('is-active', active)
        btn.setAttribute('aria-selected', active ? 'true' : 'false')
      }
    }
    renderStrip(engineKey)
    if (onSelect) onSelect(engineKey)
  }

  select(isEngine(initial) ? initial : ENGINE_KEYS[0])

  return {
    select,
    getSelected: () => _selected,
    setEngineStatus,
    el: selectorMount,
  }
}
