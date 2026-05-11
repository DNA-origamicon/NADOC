/**
 * Domain Designer panel — listing + annotations + cross-refs.
 *
 * Phase 3 (overhang revamp). Owns the helix-grouped left listing
 * (`#dd-overhang-list`), the right-side annotations panel
 * (`#dd-annotations-panel`), and the bottom-right cross-references list
 * (`#dd-cross-refs`). Pathview is injected; this module does not import
 * Three.js or Canvas2D.
 *
 * Public API:
 *
 *     initDomainDesignerPanel(rootEl, { store, api, pathview })
 *       → { open(preselect?), close(), refresh() }
 *
 * Selection rule (LOCKED): clicks here update only `store.domainDesigner.*`.
 * They do NOT touch `selectedObject` or `multiSelectedOverhangIds`.
 *
 * Three-Layer Law: every sub-domain mutation goes through the injected
 * `api.patchSubDomain` / `api.recomputeSubDomainAnnotations` /
 * `api.generateSubDomainRandom` wrappers — never via direct store writes.
 *
 * ## Phase 3 fix-up (2026-05-10)
 *
 * The original implementation re-rendered the entire annotations panel on
 * every store change. Side-effect: the user types into the sequence override
 * textarea → 150 ms debounce fires → PATCH → backend response → store update
 * → subscribe callback → `_renderAnnotations()` blows away the textarea
 * mid-type, focus is lost, and subsequent keystrokes drop on the floor. The
 * same churn killed the Gen button and the hairpin banner.
 *
 * Fix: track which sub-domain is currently focused; if the selection didn't
 * change, skip the full annotations rebuild and just update the cached
 * fields (Tm/GC + warning banner + Gen-button disabled state) in place. The
 * sequence textarea / name input / notes input keep their DOM identity and
 * therefore keep focus + cursor position.
 */

import {
  setDomainDesignerSelection,
  toggleDomainDesignerHelix,
} from '../state/store.js'


const DEBOUNCE_PATCH_MS = 150

// ── Debug instrumentation (Phase 3 fix-up + Phase 5 [DD-bind]) ───────────────
const DEBUG = true
const _debug = (...args) => { if (DEBUG) console.debug('[DD-panel]', ...args) }
const _debugBind = (...args) => { if (DEBUG) console.debug('[DD-bind]', ...args) }


/** Helix label fallback chain.
 *
 *  In `workspace/hinge.nadoc` and most user-authored designs, `helix.label`
 *  is `null` for every helix (label is an optional user field, not auto-set
 *  by the importer). The cadnano editor falls back to the helix's INDEX in
 *  `design.helices` for the gutter label — match that convention here so the
 *  Domain Designer never shows raw UUIDs.
 *
 *  Phase 3 fix-up #2 (2026-05-10): take `(helix, design)` and resolve the
 *  index from the array. Earlier fix-up's `slice(0,8)…` fallback was
 *  exposing UUIDs whenever no human label was set (which is the common case).
 */
function _helixDisplayName(helix, design) {
  if (helix?.label) return helix.label
  if (helix?.id && design?.helices) {
    const idx = design.helices.findIndex(h => h.id === helix.id)
    if (idx >= 0) return String(idx)
  }
  if (helix?.id) return `(${String(helix.id).slice(0, 8)}…)`
  return '(unknown)'
}


export function initDomainDesignerPanel(rootEl, { store, api, pathview }) {
  // rootEl is the modal-content div; we look up the three pane elements
  // inside it. They're created by `index.html` (Phase 3 §A/B).
  const listEl     = rootEl.querySelector('#dd-overhang-list')
  const annEl      = rootEl.querySelector('#dd-annotations-panel')
  const crossEl    = rootEl.querySelector('#dd-cross-refs')

  let _open = false
  let _unsubscribe = null
  let _seqDebounceTimer = null
  // Identity tracking — skip full re-render when these don't change.
  let _renderedOvhgId = null
  let _renderedSdId   = null
  // PATCH-latency profiling helper.
  let _seqPatchT0 = 0


  // ── Helpers ──────────────────────────────────────────────────────────────

  function _design() {
    return store.getState()?.currentDesign ?? null
  }

  function _overhangs() {
    return _design()?.overhangs ?? []
  }

  /** Listing-selected overhang (perspective anchor in the multi-grid pathview).
   *  This is what the sidebar listing highlights. NOT necessarily the owner
   *  of the active sub-domain — see `_focusedOvhg` for that. */
  function _listingOvhg() {
    const dd = store.getState().domainDesigner
    if (!dd?.selectedOverhangId) return null
    return _overhangs().find(o => o.id === dd.selectedOverhangId) ?? null
  }

  /** Active sub-domain (whatever the user clicked last in the pathview or
   *  the listing). Walks ALL overhangs because the active sd may belong to
   *  the partner overhang in multi-grid mode without flipping perspective. */
  function _focusedSubDomain() {
    const sdId = store.getState().domainDesigner.selectedSubDomainId
    if (!sdId) return null
    for (const ovhg of _overhangs()) {
      const sd = (ovhg.sub_domains ?? []).find(s => s.id === sdId)
      if (sd) return sd
    }
    return null
  }

  /** Owning overhang of the active sub-domain (could be selected OR partner).
   *  Used by the annotations panel to route PATCH/Gen calls to the correct
   *  overhang_id. Falls back to the listing-selected overhang when no sd. */
  function _focusedOvhg() {
    const sdId = store.getState().domainDesigner.selectedSubDomainId
    if (sdId) {
      for (const ovhg of _overhangs()) {
        if ((ovhg.sub_domains ?? []).some(s => s.id === sdId)) return ovhg
      }
    }
    return _listingOvhg()
  }

  // Backwards-compat alias for existing call sites that use `_focused()`.
  // Returns the OWNER of the active sd so PATCH calls hit the right overhang.
  const _focused = _focusedOvhg


  // ── Listing render ───────────────────────────────────────────────────────

  // Re-entrancy guard for <details> toggle event.
  //
  // Phase 3 fix-up #2: the prior implementation listened on `toggle` and
  // re-dispatched to the store. The store change synchronously triggered a
  // listing rebuild, which destroyed the very `<details>` whose toggle was
  // still propagating — the user's intent was lost AND the new element's
  // imperative `det.open = …` could itself fire a follow-on `toggle` event,
  // racing against the user click. Outcome: clicking the summary did nothing
  // visible. Fix: handle the user intent on the `summary`'s `click` event
  // (`preventDefault` the native toggle), dispatch to store, then let the
  // re-render set `det.open` declaratively. `toggle` itself is ignored.
  let _suppressNativeToggleRebuild = false

  function _renderListing() {
    if (!listEl) return
    const overhangs = _overhangs()
    const design    = _design()
    const helices   = design?.helices ?? []
    _debug('listing rebuild', helices.length, 'helices,', overhangs.length, 'overhangs')
    listEl.innerHTML = ''
    if (overhangs.length === 0) {
      const empty = document.createElement('div')
      empty.style.cssText = 'padding:14px;color:#6e7681;text-align:center;font-size:11px'
      empty.textContent = 'No overhangs in this design — create one from the main scene…'
      listEl.appendChild(empty)
      return
    }

    // Group by helix_id.
    const byHelix = new Map()
    for (const o of overhangs) {
      if (!byHelix.has(o.helix_id)) byHelix.set(o.helix_id, [])
      byHelix.get(o.helix_id).push(o)
    }

    const dd = store.getState().domainDesigner
    for (const [helixId, ovhgs] of byHelix) {
      const helix = helices.find(h => h.id === helixId)
      const helixLabel = _helixDisplayName(helix ?? { id: helixId }, design)
      const det = document.createElement('details')
      // Phase 3 fix-up #2: explicit declarative wiring — `expandedHelices`
      // is the source of truth. Default-open for first-time view so the user
      // sees content without having to click first.
      det.open = dd.expandedHelices?.has(helixId)
        ? true
        : (dd.expandedHelices?.size === 0)   // first render — start all open
      det.dataset.helixId = helixId
      det.style.cssText = 'margin-bottom:4px;display:block'  // explicit block
                                                              // so no parent
                                                              // grid/flex
                                                              // breaks the
                                                              // native marker
      const sum = document.createElement('summary')
      sum.style.cssText = 'cursor:pointer;color:#8b949e;font-size:11px;padding:2px 0;list-style:revert'
      sum.textContent = `Helix ${helixLabel} · ${ovhgs.length}`
      sum.title = `Helix ${helixLabel}` + (helix?.id ? ` (${helix.id})` : '')
      // Handle the user's intent on click (not on `toggle`) so the store
      // update doesn't race the native toggle event.
      sum.addEventListener('click', (ev) => {
        ev.preventDefault()           // don't let the native toggle fire
        _debug('summary click', helixId, 'currently open=', det.open)
        toggleDomainDesignerHelix(helixId)
      })
      // Defensive: if anything else flips `open` imperatively (e.g. keyboard
      // Enter on the summary), keep the store in sync without re-rendering.
      det.addEventListener('toggle', () => {
        if (_suppressNativeToggleRebuild) return
        const isInSet = !!dd.expandedHelices?.has(helixId)
        if (det.open !== isInSet) {
          _suppressNativeToggleRebuild = true
          try { toggleDomainDesignerHelix(helixId) }
          finally { _suppressNativeToggleRebuild = false }
        }
      })
      det.appendChild(sum)

      for (const o of ovhgs) {
        // Overhang row (parent <details> for sub-domains).
        const ovhgDet = document.createElement('details')
        ovhgDet.dataset.overhangId = o.id
        ovhgDet.style.cssText = 'margin-left:6px;display:block'
        // Auto-open the selected overhang so its sub-items are visible.
        ovhgDet.open = (dd.selectedOverhangId === o.id) || (o.sub_domains?.length ?? 0) > 0

        const ovhgSum = document.createElement('summary')
        const isSel = dd.selectedOverhangId === o.id
        ovhgSum.dataset.overhangId = o.id
        ovhgSum.style.cssText = (
          'padding:3px 6px;border-radius:3px;cursor:pointer;font-size:11px;list-style:revert;'
          + (isSel
              ? 'background:#1f2937;color:#fff;border-left:3px solid #ffd33d'
              : 'background:transparent;color:#c9d1d9;border-left:3px solid transparent')
        )
        const sdCount = o.sub_domains?.length ?? 0
        ovhgSum.textContent = `${o.label || o.id} (${sdCount})`
        // Click on the summary text → select the overhang AND first sub-domain.
        // Stop the native toggle so it doesn't fight our selection logic.
        ovhgSum.addEventListener('click', (ev) => {
          ev.preventDefault()
          ovhgDet.open = !ovhgDet.open
          _debug('overhang click', o.id, 'helix', helixLabel)
          setDomainDesignerSelection({
            overhangId: o.id,
            subDomainId: o.sub_domains?.[0]?.id ?? null,
          })
        })
        ovhgDet.appendChild(ovhgSum)

        // Sub-domain children — clicking selects the specific sub-domain.
        const sdsOrdered = [...(o.sub_domains ?? [])].sort(
          (a, b) => (a.start_bp_offset ?? 0) - (b.start_bp_offset ?? 0),
        )
        for (const sd of sdsOrdered) {
          const sdRow = document.createElement('div')
          // Active-sd highlight is independent of which overhang is the
          // listing-perspective anchor — partner-grid sd clicks light up
          // the row even though `selectedOverhangId` stays on the listed one.
          const sdSel = dd.selectedSubDomainId === sd.id
          sdRow.dataset.subDomainId = sd.id
          sdRow.style.cssText = (
            'padding:2px 6px 2px 22px;border-radius:3px;cursor:pointer;font-size:10.5px;'
            + 'display:flex;align-items:center;gap:6px;'
            + (sdSel
                ? 'background:#2a3242;color:#fff;border-left:3px solid #ffd33d'
                : 'background:transparent;color:#a8b3bf;border-left:3px solid transparent')
          )
          // Color swatch.
          const swatch = document.createElement('span')
          const swColor = sd.color || '#8b949e'
          swatch.style.cssText = (
            `display:inline-block;width:8px;height:8px;border-radius:2px;`
            + `background:${swColor};border:1px solid #30363d;flex:0 0 auto`
          )
          // Name + length.
          const nameSpan = document.createElement('span')
          nameSpan.textContent = `${sd.name ?? '(unnamed)'}  ${sd.length_bp}bp`
          nameSpan.style.cssText = 'flex:1 1 auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'
          // Override-lock indicator.
          const lockSpan = document.createElement('span')
          if (sd.sequence_override) {
            lockSpan.textContent = '🔒'
            lockSpan.title = 'Sequence override active'
            lockSpan.style.cssText = 'font-size:9px;flex:0 0 auto;color:#d08800'
          }
          // Warning indicator.
          const warnSpan = document.createElement('span')
          if (sd.hairpin_warning || sd.dimer_warning) {
            warnSpan.textContent = '⚠'
            warnSpan.title = sd.hairpin_warning ? 'Hairpin warning' : 'Dimer warning'
            warnSpan.style.cssText = 'font-size:10px;flex:0 0 auto;color:#f85149'
          }
          sdRow.append(swatch, nameSpan, lockSpan, warnSpan)
          sdRow.addEventListener('click', (ev) => {
            ev.stopPropagation()
            _debug('sub-domain click', o.id, sd.id)
            setDomainDesignerSelection({
              overhangId: o.id,
              subDomainId: sd.id,
            })
          })
          ovhgDet.appendChild(sdRow)
        }
        det.appendChild(ovhgDet)
      }
      listEl.appendChild(det)
    }
  }


  // ── Annotations panel — full rebuild ─────────────────────────────────────
  //
  // Only called when the focused sub-domain changes (or first open).
  // While the user is editing the same sub-domain, `_patchAnnotationsInPlace`
  // updates the read-only fields without touching the inputs.

  function _renderAnnotations() {
    if (!annEl) return
    const sd = _focusedSubDomain()
    const ovhg = _focused()
    annEl.innerHTML = ''
    if (!sd || !ovhg) {
      annEl.style.color = '#6e7681'
      annEl.textContent = 'No sub-domain selected.'
      _renderedOvhgId = null
      _renderedSdId = null
      return
    }
    annEl.style.color = '#c9d1d9'
    _debug('panel refresh for sd', sd.id, 'name', sd.name)
    _renderedOvhgId = ovhg.id
    _renderedSdId   = sd.id

    // Header
    const header = document.createElement('div')
    header.className = 'dd-ann-header'
    header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;font-weight:bold'
    const hLabel = document.createElement('span')
    hLabel.textContent = sd.name ?? '(unnamed)'
    const recompute = document.createElement('button')
    recompute.className = 'dd-ann-recompute'
    recompute.title = 'Recompute Tm / GC / warnings'
    recompute.textContent = '↻'
    recompute.style.cssText = 'background:none;border:1px solid #30363d;border-radius:3px;color:#8b949e;cursor:pointer;padding:2px 6px;font-family:monospace;font-size:11px'
    recompute.addEventListener('click', () => {
      api.recomputeSubDomainAnnotations?.(ovhg.id, sd.id)
    })
    header.append(hLabel, recompute)
    annEl.appendChild(header)

    // Name
    const nameLabel = document.createElement('label')
    nameLabel.style.cssText = 'display:block;margin-bottom:6px'
    nameLabel.innerHTML = '<span style="display:block;color:#8b949e;font-size:10px;margin-bottom:2px">Name</span>'
    const nameInput = document.createElement('input')
    nameInput.type = 'text'
    nameInput.className = 'dd-ann-name'
    nameInput.value = sd.name ?? ''
    nameInput.style.cssText = 'width:100%;background:#161b22;border:1px solid #30363d;border-radius:3px;color:#c9d1d9;font-family:monospace;font-size:11px;padding:3px 6px;outline:none;box-sizing:border-box'
    const _commitName = () => {
      const v = nameInput.value.trim()
      // Re-read latest sub-domain to avoid stale-closure compare on rapid edits.
      const latest = _focusedSubDomain()
      if (v && latest && v !== latest.name) api.patchSubDomain?.(ovhg.id, sd.id, { name: v })
    }
    nameInput.addEventListener('blur', _commitName)
    nameInput.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') nameInput.blur() })
    nameLabel.appendChild(nameInput)
    annEl.appendChild(nameLabel)

    // Color
    const colorLabel = document.createElement('label')
    colorLabel.style.cssText = 'display:block;margin-bottom:6px'
    colorLabel.innerHTML = '<span style="display:block;color:#8b949e;font-size:10px;margin-bottom:2px">Color</span>'
    const colorWrap = document.createElement('div')
    colorWrap.style.cssText = 'display:flex;gap:4px;align-items:center'
    const colorInput = document.createElement('input')
    colorInput.type = 'color'
    colorInput.className = 'dd-ann-color'
    colorInput.value = sd.color ?? '#888888'
    colorInput.style.cssText = 'width:28px;height:22px;border:1px solid #30363d;background:#161b22;border-radius:3px'
    colorInput.addEventListener('change', () => {
      api.patchSubDomain?.(ovhg.id, sd.id, { color: colorInput.value })
    })
    const colorClear = document.createElement('button')
    colorClear.className = 'dd-ann-color-clear'
    colorClear.textContent = 'Clear'
    colorClear.style.cssText = 'background:#161b22;border:1px solid #30363d;border-radius:3px;color:#8b949e;cursor:pointer;font-family:monospace;font-size:10px;padding:3px 6px'
    colorClear.addEventListener('click', () => {
      api.patchSubDomain?.(ovhg.id, sd.id, { color: null })
    })
    colorWrap.append(colorInput, colorClear)
    colorLabel.appendChild(colorWrap)
    annEl.appendChild(colorLabel)

    // Sequence override
    const seqLabel = document.createElement('label')
    seqLabel.style.cssText = 'display:block;margin-bottom:6px'
    const seqHeader = document.createElement('span')
    seqHeader.className = 'dd-ann-seq-header'
    seqHeader.style.cssText = 'display:block;color:#8b949e;font-size:10px;margin-bottom:2px'
    seqHeader.textContent = `Sequence override (${sd.length_bp} bp)`
    seqLabel.appendChild(seqHeader)
    const seqInput = document.createElement('textarea')
    seqInput.className = 'dd-ann-seq'
    seqInput.rows = 2
    seqInput.value = sd.sequence_override ?? ''
    seqInput.style.cssText = 'width:100%;background:#161b22;border:1px solid #30363d;border-radius:3px;color:#c9d1d9;font-family:monospace;font-size:11px;padding:3px 6px;outline:none;box-sizing:border-box;resize:vertical'
    const seqStatus = document.createElement('span')
    seqStatus.className = 'dd-ann-seq-status'
    seqStatus.style.cssText = 'display:inline-block;margin-top:2px;font-size:10px'
    seqLabel.appendChild(seqInput)
    seqLabel.appendChild(seqStatus)
    seqInput.addEventListener('input', () => {
      const raw = seqInput.value.toUpperCase().replace(/[^ACGTN]/g, '')
      if (raw !== seqInput.value) seqInput.value = raw   // strip invalid bases
      _debug('seq input', raw.length, 'chars')
      // Re-read the latest sub-domain (length_bp may have changed via split).
      const latest = _focusedSubDomain() ?? sd
      if (raw.length !== latest.length_bp) {
        seqStatus.textContent = `× length ${raw.length}/${latest.length_bp}`
        seqStatus.style.color = '#f85149'
      } else {
        seqStatus.textContent = '✓'
        seqStatus.style.color = '#3fb950'
      }
      if (_seqDebounceTimer) clearTimeout(_seqDebounceTimer)
      _seqDebounceTimer = setTimeout(() => {
        const cur = _focusedSubDomain() ?? sd
        if (raw.length === cur.length_bp) {
          _debug('seq PATCH fire', sd.id)
          _seqPatchT0 = (typeof performance !== 'undefined') ? performance.now() : Date.now()
          Promise.resolve(api.patchSubDomain?.(ovhg.id, sd.id, { sequence_override: raw }))
            .then(() => {
              const t1 = (typeof performance !== 'undefined') ? performance.now() : Date.now()
              _debug('seq PATCH ok', (t1 - _seqPatchT0).toFixed(1), 'ms')
            })
            .catch((err) => _debug('seq PATCH failed', err))
        }
      }, DEBOUNCE_PATCH_MS)
    })
    annEl.appendChild(seqLabel)

    // Cached: Tm / GC
    const cached = document.createElement('div')
    cached.className = 'dd-ann-cached'
    cached.style.cssText = 'font-size:10px;color:#8b949e;margin-bottom:6px'
    cached.textContent = _formatAnnotations(sd)
    annEl.appendChild(cached)

    // Rotation editor removed 2026-05-11 — sub-domain rotation is no longer
    // user-driven from the Domain Designer. The `rotation_theta_deg` /
    // `rotation_phi_deg` fields on SubDomain are still read by the geometry
    // pipeline if set in the saved file, but the Domain Designer no longer
    // exposes a UI to edit them.

    // Warnings banner.
    const warnEl = document.createElement('div')
    warnEl.className = 'dd-ann-warnings'
    _applyWarningBanner(warnEl, sd, ovhg)
    annEl.appendChild(warnEl)

    // Notes
    const notesLabel = document.createElement('label')
    notesLabel.style.cssText = 'display:block;margin-bottom:6px'
    notesLabel.innerHTML = '<span style="display:block;color:#8b949e;font-size:10px;margin-bottom:2px">Notes</span>'
    const notesInput = document.createElement('textarea')
    notesInput.className = 'dd-ann-notes'
    notesInput.rows = 3
    notesInput.value = sd.notes ?? ''
    notesInput.style.cssText = 'width:100%;background:#161b22;border:1px solid #30363d;border-radius:3px;color:#c9d1d9;font-family:monospace;font-size:11px;padding:3px 6px;outline:none;box-sizing:border-box;resize:vertical'
    notesInput.addEventListener('blur', () => {
      const latest = _focusedSubDomain() ?? sd
      if (notesInput.value !== (latest.notes ?? '')) {
        api.patchSubDomain?.(ovhg.id, sd.id, { notes: notesInput.value })
      }
    })
    notesLabel.appendChild(notesInput)
    annEl.appendChild(notesLabel)

    // Generate-random button.
    const genBtn = document.createElement('button')
    genBtn.className = 'dd-ann-generate'
    genBtn.textContent = 'Gen this sub-domain'
    _applyGenButtonState(genBtn, sd)
    genBtn.addEventListener('click', () => {
      const cur = _focusedSubDomain() ?? sd
      const blocked = !!(cur.hairpin_warning || cur.dimer_warning)
      _debug('gen click', sd.id, 'disabled=', blocked)
      if (!blocked) api.generateSubDomainRandom?.(ovhg.id, sd.id, {})
    })
    annEl.appendChild(genBtn)
  }


  // ── In-place updates ─────────────────────────────────────────────────────
  //
  // Called when the focused sub-domain ID hasn't changed but its annotation
  // payload (Tm/GC/warnings) has. Touches ONLY read-only display fields, so
  // the user's focused input keeps its caret + selection.

  function _patchAnnotationsInPlace() {
    const sd = _focusedSubDomain()
    const ovhg = _focused()
    if (!sd || !ovhg) return
    const cached = annEl.querySelector('.dd-ann-cached')
    if (cached) cached.textContent = _formatAnnotations(sd)
    const warnEl = annEl.querySelector('.dd-ann-warnings')
    if (warnEl) _applyWarningBanner(warnEl, sd, ovhg)
    const genBtn = annEl.querySelector('.dd-ann-generate')
    if (genBtn) _applyGenButtonState(genBtn, sd)
    // Sequence-override length hint may move after a split.
    const seqHeader = annEl.querySelector('.dd-ann-seq-header')
    if (seqHeader) seqHeader.textContent = `Sequence override (${sd.length_bp} bp)`
    _debug('annotations update', sd.id, 'tm', sd.tm_celsius)
  }

  function _formatAnnotations(sd) {
    const tmText = (sd.tm_celsius != null) ? `${Math.round(sd.tm_celsius)}°C` : '—'
    const gcText = (sd.gc_percent != null) ? `${Math.round(sd.gc_percent)}%` : '—'
    return `Tm: ${tmText}  GC: ${gcText}`
  }

  function _applyWarningBanner(warnEl, sd, ovhg) {
    if (sd.hairpin_warning || sd.dimer_warning) {
      const ordered = [...(ovhg.sub_domains ?? [])].sort(
        (a, b) => a.start_bp_offset - b.start_bp_offset,
      )
      const myIdx = ordered.findIndex(s => s.id === sd.id)
      const prev = ordered[myIdx - 1]
      const next = ordered[myIdx + 1]
      let msg = ''
      if (sd.hairpin_warning) {
        const neighbourName = next?.name ?? prev?.name ?? '?'
        msg = `Hairpin across boundary with ${neighbourName}`
      } else if (sd.dimer_warning) {
        msg = 'Self-dimer detected'
      }
      warnEl.hidden = false
      warnEl.style.cssText = 'background:#5a1d1d;color:#f85149;padding:6px 8px;font:11px monospace;border-radius:3px;margin-bottom:6px'
      warnEl.textContent = msg
      _debug('hairpin banner shown', sd.id, msg)
    } else {
      // Wipe contents AND collapse so the empty banner doesn't take vertical
      // space. Reset cssText so a re-show paints correctly.
      warnEl.hidden = true
      warnEl.textContent = ''
      warnEl.style.cssText = 'display:none'
      _debug('hairpin banner hidden', sd.id)
    }
  }

  function _applyGenButtonState(btn, sd) {
    const isBlocked = !!(sd.hairpin_warning || sd.dimer_warning)
    btn.disabled = isBlocked
    btn.style.cssText = (
      'padding:6px 12px;background:' + (isBlocked ? '#3a3f47' : '#238636')
      + ';border:none;border-radius:3px;color:#fff;font-family:monospace;'
      + 'font-size:11px;cursor:' + (isBlocked ? 'not-allowed' : 'pointer')
    )
    btn.title = isBlocked
      ? 'Resolve the active hairpin/dimer warning first.'
      : ''
  }


  // ── Cross-references (read-only OverhangConnection entries) ──────────────

  function _renderCrossRefs() {
    if (!crossEl) return
    crossEl.innerHTML = ''
    const ovhg = _focused()
    if (!ovhg) {
      crossEl.textContent = 'No overhang selected.'
      return
    }
    const design = _design()
    const helices = design?.helices ?? []
    const overhangs = _overhangs()
    const helixLabelForOvhg = (oid) => {
      const o = overhangs.find(x => x.id === oid)
      if (!o) return oid
      const h = helices.find(hh => hh.id === o.helix_id)
      const label = _helixDisplayName(h ?? { id: o.helix_id }, design)
      return `${o.label ?? o.id} (Helix ${label})`
    }
    const conns = (_design()?.overhang_connections ?? [])
      .filter(c => c.overhang_a_id === ovhg.id || c.overhang_b_id === ovhg.id)
    const header = document.createElement('div')
    header.style.cssText = 'font-size:10px;color:#8b949e;margin-bottom:4px'
    header.textContent = `Cross-references (${conns.length})`
    crossEl.appendChild(header)
    if (conns.length === 0) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#6e7681'
      empty.textContent = 'No linkers reference this overhang.'
      crossEl.appendChild(empty)
    } else {
      for (const c of conns) {
        const row = document.createElement('div')
        row.style.cssText = 'padding:2px 0;font-size:11px;color:#c9d1d9'
        const other = (c.overhang_a_id === ovhg.id) ? c.overhang_b_id : c.overhang_a_id
        row.textContent =
          `${c.name ?? c.id} · ${c.linker_type} ${c.length_value} ${c.length_unit} → ${helixLabelForOvhg(other)}`
        crossEl.appendChild(row)
      }
    }

    // ── Phase 5: OverhangBinding cross-references ─────────────────────────
    _renderBindingsSection(ovhg, design, overhangs)
  }


  // ── Bindings (Phase 5) ──────────────────────────────────────────────────
  // Renders the Bindings (n) subsection under cross-refs, an inline
  // "Create binding" form, and per-binding rows with Bound checkbox + Delete.

  function _renderBindingsSection(ovhg, design, overhangs) {
    if (!crossEl) return
    const bindings = (design?.overhang_bindings ?? [])
      .filter(b => b.overhang_a_id === ovhg.id || b.overhang_b_id === ovhg.id)
    const subDomainById = new Map()
    for (const o of overhangs) {
      for (const sd of (o.sub_domains ?? [])) subDomainById.set(sd.id, { sd, ovhg: o })
    }
    const joints = design?.cluster_joints ?? []

    const bindHeader = document.createElement('div')
    bindHeader.style.cssText = 'font-size:10px;color:#8b949e;margin:8px 0 4px;display:flex;align-items:center;gap:6px'
    const bindTitle = document.createElement('span')
    bindTitle.textContent = `Bindings (${bindings.length})`
    bindHeader.appendChild(bindTitle)
    const addBtn = document.createElement('button')
    addBtn.textContent = '+ Create binding'
    addBtn.style.cssText =
      'margin-left:auto;padding:1px 8px;font-size:10px;background:#238636;border:none;'
      + 'border-radius:3px;color:#fff;cursor:pointer'
    addBtn.dataset.test = 'dd-bind-create-btn'
    addBtn.addEventListener('click', () => {
      const existing = crossEl.querySelector('[data-test="dd-bind-create-form"]')
      if (existing) { existing.remove(); return }
      _renderCreateBindingForm(ovhg, overhangs, joints)
    })
    bindHeader.appendChild(addBtn)
    crossEl.appendChild(bindHeader)

    if (bindings.length === 0) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#6e7681;font-size:11px'
      empty.textContent = 'No bindings reference this overhang.'
      crossEl.appendChild(empty)
      return
    }
    for (const b of bindings) {
      const row = document.createElement('div')
      row.style.cssText =
        'padding:3px 4px;margin:2px 0;font-size:11px;color:#c9d1d9;'
        + 'border:1px solid #30363d;border-radius:3px;'
        + 'display:flex;align-items:center;gap:6px;cursor:pointer'
      row.dataset.test = 'dd-bind-row'
      row.dataset.bindingId = b.id

      // Name pill
      const namePill = document.createElement('span')
      namePill.textContent = b.name ?? b.id.slice(0, 6)
      namePill.style.cssText =
        'background:#21262d;padding:1px 6px;border-radius:3px;font-weight:bold'
      row.appendChild(namePill)

      // Mode badge
      const mode = b.binding_mode ?? 'duplex'
      const modeBadge = document.createElement('span')
      modeBadge.textContent = mode
      modeBadge.style.cssText =
        'padding:1px 5px;border-radius:3px;color:#fff;font-size:9px;'
        + 'background:' + (mode === 'toehold' ? '#bf8700' : '#3fb950')
      row.appendChild(modeBadge)

      // Labels
      const sdAInfo = subDomainById.get(b.sub_domain_a_id)
      const sdBInfo = subDomainById.get(b.sub_domain_b_id)
      const sdAName = sdAInfo?.sd?.name ?? b.sub_domain_a_id.slice(0, 6)
      const sdBName = sdBInfo?.sd?.name ?? b.sub_domain_b_id.slice(0, 6)
      // Identify the OTHER side (the partner, not us).
      const ours = (b.overhang_a_id === ovhg.id) ? 'a' : 'b'
      const partnerOvhgId = (ours === 'a') ? b.overhang_b_id : b.overhang_a_id
      const partnerSdId = (ours === 'a') ? b.sub_domain_b_id : b.sub_domain_a_id
      const partnerOvhg = overhangs.find(o => o.id === partnerOvhgId)
      const partnerLabel = partnerOvhg?.label ?? partnerOvhgId.slice(0, 10)
      const labelText = document.createElement('span')
      labelText.textContent = `${sdAName} ↔ ${sdBName} (partner: ${partnerLabel})`
      labelText.style.cssText = 'flex:1'
      row.appendChild(labelText)

      // Joint + locked angle.
      const joint = (b.target_joint_id != null)
        ? joints.find(j => j.id === b.target_joint_id)
        : null
      if (joint) {
        const jLabel = document.createElement('span')
        const angleText = (b.locked_angle_deg != null)
          ? ` ${b.locked_angle_deg.toFixed(1)}°`
          : ''
        jLabel.textContent = `Joint: ${joint.name ?? joint.id.slice(0, 6)}${angleText}`
        jLabel.style.cssText = 'color:#7ea3c5;font-size:10px'
        row.appendChild(jLabel)
      }

      // Bound checkbox.
      const boundLabel = document.createElement('label')
      boundLabel.style.cssText = 'display:flex;align-items:center;gap:3px;font-size:10px;cursor:pointer'
      const boundCb = document.createElement('input')
      boundCb.type = 'checkbox'
      boundCb.checked = !!b.bound
      boundCb.dataset.test = 'dd-bind-bound-cb'
      boundCb.addEventListener('click', ev => ev.stopPropagation())
      boundCb.addEventListener('change', async ev => {
        _debugBind('toggle bound', b.id, '->', ev.target.checked)
        try {
          const result = await api.patchOverhangBinding?.(b.id, { bound: ev.target.checked })
          if (result === null || result === undefined) {
            // 422 surface — revert.
            boundCb.checked = !ev.target.checked
            _showBindingToast('Could not change binding lock state.')
          }
        } catch (err) {
          _debugBind('patch threw', err)
          boundCb.checked = !ev.target.checked
        }
      })
      boundLabel.appendChild(boundCb)
      boundLabel.appendChild(document.createTextNode(' Bound'))
      row.appendChild(boundLabel)

      // Delete button.
      const delBtn = document.createElement('button')
      delBtn.textContent = '✕'
      delBtn.dataset.test = 'dd-bind-delete-btn'
      delBtn.style.cssText =
        'background:none;border:1px solid #6e7681;color:#c9d1d9;border-radius:3px;'
        + 'padding:0 5px;cursor:pointer;font-size:10px'
      delBtn.addEventListener('click', async ev => {
        ev.stopPropagation()
        if (!confirm(`Delete binding ${b.name ?? b.id.slice(0, 6)}?`)) return
        _debugBind('delete', b.id)
        try {
          await api.deleteOverhangBinding?.(b.id)
        } catch (err) {
          _debugBind('delete threw', err)
        }
      })
      row.appendChild(delBtn)

      // Row click → select partner sub-domain.
      row.addEventListener('click', ev => {
        if (ev.target.tagName === 'INPUT' || ev.target.tagName === 'BUTTON') return
        _debugBind('row click → select partner', { partnerOvhgId, partnerSdId })
        setDomainDesignerSelection({
          overhangId: partnerOvhgId,
          subDomainId: partnerSdId,
        })
      })
      crossEl.appendChild(row)
    }
  }

  function _renderCreateBindingForm(ovhg, overhangs, joints) {
    if (!crossEl) return
    const form = document.createElement('div')
    form.dataset.test = 'dd-bind-create-form'
    form.style.cssText =
      'padding:4px;margin:4px 0;background:#161b22;border:1px solid #30363d;'
      + 'border-radius:3px;font-size:11px;color:#c9d1d9'

    // Resolve focused sub-domain → the binding's "a" side.
    const sd = _focusedSubDomain()
    const lengthBp = sd?.length_bp ?? 0

    // Eligible partner sub-domains: matching length_bp, different parent overhang.
    const eligible = []
    for (const o of overhangs) {
      if (o.id === ovhg.id) continue
      for (const candSd of (o.sub_domains ?? [])) {
        if (candSd.length_bp === lengthBp) {
          eligible.push({ ovhg: o, sd: candSd })
        }
      }
    }

    const introRow = document.createElement('div')
    introRow.style.cssText = 'margin-bottom:4px'
    if (!sd) {
      introRow.textContent = 'Select a sub-domain first.'
      form.appendChild(introRow)
      crossEl.appendChild(form)
      return
    }
    introRow.textContent = `Bind ${sd.name} (${lengthBp} bp) with:`
    form.appendChild(introRow)

    // Partner select.
    const partnerSelect = document.createElement('select')
    partnerSelect.dataset.test = 'dd-bind-partner-select'
    partnerSelect.style.cssText =
      'width:100%;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;padding:2px;margin-bottom:4px'
    if (eligible.length === 0) {
      const opt = document.createElement('option')
      opt.value = ''
      opt.textContent = '(no sub-domains of matching length)'
      partnerSelect.appendChild(opt)
      partnerSelect.disabled = true
    } else {
      for (const e of eligible) {
        const opt = document.createElement('option')
        opt.value = e.sd.id
        opt.textContent = `${e.ovhg.label ?? e.ovhg.id.slice(0, 8)} / ${e.sd.name}`
        partnerSelect.appendChild(opt)
      }
    }
    form.appendChild(partnerSelect)

    // Mode radio.
    const modeRow = document.createElement('div')
    modeRow.style.cssText = 'margin-bottom:4px;display:flex;gap:8px'
    for (const m of ['duplex', 'toehold']) {
      const label = document.createElement('label')
      label.style.cssText = 'display:flex;align-items:center;gap:3px;cursor:pointer'
      const r = document.createElement('input')
      r.type = 'radio'
      r.name = 'dd-bind-mode'
      r.value = m
      r.dataset.test = `dd-bind-mode-${m}`
      if (m === 'duplex') r.checked = true
      label.appendChild(r)
      label.appendChild(document.createTextNode(m))
      modeRow.appendChild(label)
    }
    form.appendChild(modeRow)

    // Joint select.
    const jLabel = document.createElement('div')
    jLabel.textContent = 'Target joint:'
    jLabel.style.cssText = 'margin-bottom:2px;color:#8b949e'
    form.appendChild(jLabel)
    const jointSelect = document.createElement('select')
    jointSelect.dataset.test = 'dd-bind-joint-select'
    jointSelect.style.cssText =
      'width:100%;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;padding:2px;margin-bottom:4px'
    const autoOpt = document.createElement('option')
    autoOpt.value = ''
    autoOpt.textContent = 'Auto-detect'
    jointSelect.appendChild(autoOpt)
    for (const j of joints) {
      const opt = document.createElement('option')
      opt.value = j.id
      opt.textContent = j.name ?? j.id.slice(0, 8)
      jointSelect.appendChild(opt)
    }
    form.appendChild(jointSelect)

    // Submit / cancel.
    const btnRow = document.createElement('div')
    btnRow.style.cssText = 'display:flex;gap:6px;margin-top:4px'
    const submit = document.createElement('button')
    submit.textContent = 'Create'
    submit.dataset.test = 'dd-bind-submit'
    submit.style.cssText =
      'flex:1;padding:3px;background:#238636;border:none;color:#fff;border-radius:3px;cursor:pointer'
    submit.addEventListener('click', async () => {
      const partnerSd = partnerSelect.value
      if (!partnerSd) return
      const mode = form.querySelector('input[name="dd-bind-mode"]:checked')?.value ?? 'duplex'
      const joint = jointSelect.value || null
      _debugBind('create submit', { sd: sd.id, partnerSd, mode, joint })
      try {
        const result = await api.createOverhangBinding?.({
          sub_domain_a_id: sd.id,
          sub_domain_b_id: partnerSd,
          binding_mode: mode,
          target_joint_id: joint,
        })
        if (result === null || result === undefined) {
          _showBindingToast('Could not create binding (server rejected).')
        } else {
          form.remove()
        }
      } catch (err) {
        _debugBind('create threw', err)
      }
    })
    const cancel = document.createElement('button')
    cancel.textContent = 'Cancel'
    cancel.style.cssText =
      'padding:3px 8px;background:#21262d;border:1px solid #30363d;color:#c9d1d9;border-radius:3px;cursor:pointer'
    cancel.addEventListener('click', () => form.remove())
    btnRow.appendChild(submit)
    btnRow.appendChild(cancel)
    form.appendChild(btnRow)

    crossEl.appendChild(form)
  }

  function _showBindingToast(message) {
    // Inline toast — domain designer is already a modal popup, so a simple
    // ephemeral message at the cross-refs panel is sufficient. The standard
    // app-level toast helper isn't imported here to keep this module self-
    // contained for the panel.
    const toast = document.createElement('div')
    toast.textContent = message
    toast.style.cssText =
      'position:fixed;bottom:60px;right:20px;padding:8px 12px;'
      + 'background:#f85149;color:#fff;border-radius:3px;font-size:11px;'
      + 'z-index:99999;box-shadow:0 2px 8px rgba(0,0,0,0.5)'
    document.body.appendChild(toast)
    setTimeout(() => toast.remove(), 3500)
  }


  // ── Pathview + Preview wiring ────────────────────────────────────────────

  function _rebuildPathview() {
    const ovhg = _focused()
    if (!ovhg || !pathview) return
    const state = store.getState()
    pathview.rebuild?.(ovhg, state.currentGeometry, state.currentDesign)
  }

  // ── Refresh ──────────────────────────────────────────────────────────────
  //
  // Smart-refresh: full annotations rebuild only when the focused sub-domain
  // identity changes; in-place patch otherwise (so input focus survives).

  function refresh() {
    if (!_open) return
    _renderListing()
    _renderCrossRefs()
    _rebuildPathview()
    const ovhg = _focused()
    const sd   = _focusedSubDomain()
    const sameTarget = (
      ovhg && sd
      && _renderedOvhgId === ovhg.id
      && _renderedSdId   === sd.id
    )
    if (!ovhg || !sd) {
      _renderAnnotations()
    } else if (sameTarget) {
      _patchAnnotationsInPlace()
    } else {
      _renderAnnotations()
    }
  }


  // ── Open / Close ─────────────────────────────────────────────────────────

  function open(preselect) {
    _open = true
    const overhangs = _overhangs()
    const dd = store.getState().domainDesigner
    let ovhgId = dd.selectedOverhangId
    if (Array.isArray(preselect) && preselect.length > 0) {
      ovhgId = preselect[0]
    }
    if (!ovhgId && overhangs.length > 0) {
      ovhgId = overhangs[0].id
    }
    if (ovhgId) {
      const o = overhangs.find(x => x.id === ovhgId)
      setDomainDesignerSelection({
        overhangId: ovhgId,
        subDomainId: o?.sub_domains?.[0]?.id ?? null,
      })
    }
    // Subscribe to selection + design changes; refresh from store reads.
    _unsubscribe = store.subscribe(() => { if (_open) refresh() })
    refresh()
  }

  function close() {
    _open = false
    _unsubscribe?.()
    _unsubscribe = null
    _renderedOvhgId = null
    _renderedSdId   = null
  }

  return { open, close, refresh }
}
