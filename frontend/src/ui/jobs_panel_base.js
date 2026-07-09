/**
 * jobs_panel_base.js — the shared STATEFUL scaffold every jobs panel repeats
 * (U3 slice 2c, "unified panel" track). Companion to the pure list model
 * (`jobs_panel_model.js`) and DOM renderer (`jobs_panel_render.js`): those own
 * the job LIST; this owns the three behaviours that wrap the list identically in
 * every `*_jobs_panel.js`:
 *
 *   • section collapse — heading click toggles the body + arrow and persists the
 *     state per-tab (`section_collapse_state.js`), firing onOpen / onClose hooks;
 *   • advanced-parameters drawer — its toggle shows/hides the advanced body + arrow;
 *   • REST poll loop — a single `setTimeout` that re-fetches while the panel is
 *     OPEN and a job is active, cleared otherwise.
 *
 * Historically mrDNA/CanDo/LAMMPS/oxDNA/md each re-implemented these verbatim
 * (`_applyCollapsed` / `_clearPoll` / `_scheduleNextPoll` + an advToggle listener).
 * This factory lifts them into one place; a panel supplies its DOM elements + a
 * few callbacks (`hasActive`, `tick`, `onOpen`, `onClose`) and gets back the small
 * api it drives. Pure decisions (`bodyDisplay`, `arrowChar`, `shouldPoll`) are
 * exported for the unit oracle; the factory wires them to the DOM.
 *
 * `arrowStyle` covers the three arrow idioms in the panels: 'text' (▾/▸ via
 * textContent — mrDNA/CanDo), 'class' (`is-collapsed` class — LAMMPS), 'rotate'
 * (CSS transform — oxDNA/md). Only 'text' has live consumers today (slice 2c-1);
 * the others are pinned by the oracle so converging those panels is a pure add.
 *
 * `collapsible:false` makes a SECTION permanently open — no heading toggle, the
 * persisted collapse state is ignored, and `initCollapsed()` forces the body open
 * (firing `onOpen` once). The advanced-parameters drawer and the poll loop are
 * unaffected. This is how the engine panels behave under the unified Simulate
 * section: the *Simulate* header owns the one collapse; each engine's own header
 * is a static label (the engine selector shows/hides whole panels).
 */

import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'

// ── Pure decisions (unit-tested) ──────────────────────────────────────────────

/** CSS display for a section body given its collapsed flag. */
export function bodyDisplay(collapsed) {
  return collapsed ? 'none' : ''
}

/** The text-arrow glyph for an open/closed disclosure (▾ open, ▸ closed). */
export function arrowChar(open) {
  return open ? '▾' : '▸'
}

/** Poll iff the panel is open AND a job is active — the shared gate. */
export function shouldPoll({ open, hasActive }) {
  return !!open && !!hasActive
}

/**
 * Apply an open/closed state to a disclosure arrow element, per idiom. Pure DOM
 * mutation on a single element (no reads) — safe to unit-test against a stub el.
 */
export function applyArrow(el, open, style = 'text') {
  if (!el) return
  if (style === 'class') el.classList.toggle('is-collapsed', !open)
  else if (style === 'rotate') el.style.transform = open ? 'rotate(90deg)' : ''
  else el.textContent = arrowChar(open)
}

// ── Stateful factory ──────────────────────────────────────────────────────────

/**
 * @param tab          collapse-state tab key (default 'dynamics')
 * @param section      collapse-state section id (the panel's root element id)
 * @param els          { heading, body, arrow, advToggle, advArrow, advBody }
 * @param pollMs       poll interval (default 1500)
 * @param arrowStyle   'text' | 'class' | 'rotate' (section arrow idiom)
 * @param advArrowStyle same, for the advanced drawer arrow (default 'text')
 * @param hasActive    () => boolean — is a job active (keep polling)?
 * @param tick         () => void    — the poll fetch, called on each interval
 * @param onOpen       () => void    — panel opened (mount/refresh)
 * @param onClose      () => void    — panel collapsed (teardown; poll already cleared)
 * @returns { isOpen, applyCollapsed, clearPoll, schedulePoll, initCollapsed }
 */
export function initJobsPanelBase({
  tab = 'dynamics',
  section,
  els = {},
  pollMs = 1500,
  arrowStyle = 'text',
  advArrowStyle = 'text',
  collapsible = true,
  hasActive = null,
  tick = null,
  onOpen = null,
  onClose = null,
} = {}) {
  const { heading, body, arrow, advToggle, advArrow, advBody } = els
  let _pollTimer = null

  const isOpen = () => !!body && body.style.display !== 'none'

  function clearPoll() {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null }
  }

  function schedulePoll() {
    clearPoll()
    if (shouldPoll({ open: isOpen(), hasActive: hasActive ? hasActive() : false }) && tick) {
      _pollTimer = setTimeout(tick, pollMs)
    }
  }

  function applyCollapsed(collapsed) {
    if (body) body.style.display = bodyDisplay(collapsed)
    applyArrow(arrow, !collapsed, arrowStyle)
    if (!collapsed) onOpen?.()
    else { clearPoll(); onClose?.() }
  }

  if (collapsible && heading && body) {
    heading.addEventListener('click', () => {
      const next = isOpen()           // currently open → collapse it
      setSectionCollapsed(tab, section, next)
      applyCollapsed(next)
    })
  }

  if (advToggle && advBody) {
    advToggle.addEventListener('click', () => {
      const hidden = advBody.style.display === 'none'
      advBody.style.display = hidden ? '' : 'none'
      applyArrow(advArrow, hidden, advArrowStyle)
    })
  }

  /** Apply the persisted collapse state on mount (defaults to collapsed).
   *
   * A non-collapsible section ignores persistence and forces itself open. Its body +
   * arrow open synchronously, but `onOpen` is DEFERRED to a microtask: a permanently-open
   * engine panel is initialised early in the composition root, and firing its onOpen fetch
   * synchronously here would run before late-declared deps (e.g. main.js's `_workspacePath`,
   * read lazily by `getWorkspacePath()`) exist → a TDZ. The microtask fires after the
   * synchronous init body completes, so those deps are ready. */
  function initCollapsed(defaultCollapsed = true) {
    if (!collapsible) {
      if (body) body.style.display = bodyDisplay(false)
      applyArrow(arrow, true, arrowStyle)
      if (onOpen) queueMicrotask(onOpen)
      return
    }
    applyCollapsed(getSectionCollapsed(tab, section, defaultCollapsed))
  }

  return { isOpen, applyCollapsed, clearPoll, schedulePoll, initCollapsed }
}
