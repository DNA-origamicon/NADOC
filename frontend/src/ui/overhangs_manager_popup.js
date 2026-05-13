/**
 * Overhangs Manager popup.
 *
 * Lets the user define metadata-only linker records between two overhangs of
 * the currently open Part, plus auto-generated complement strands paired with
 * each overhang. Persisted in design.overhang_connections.
 *
 * Opened from:
 *   - Tools → Overhangs Manager
 *   - Right-click on a strand while 1–2 overhangs are selected
 * Auto-prepopulates lists from the current overhang selection (up to 2).
 */

import * as api from '../api/client.js'
import {
  patchSubDomain,
  recomputeSubDomainAnnotations,
  generateSubDomainRandom,
  splitSubDomain,
  mergeSubDomains,
  patchTmSettings,
  createOverhangBinding,
  patchOverhangBinding,
  deleteOverhangBinding,
  resizeOverhangFreeEnd,
  patchOverhang,
  generateOverhangRandomSequence,
  generateRandomSequence,
} from '../api/overhang_endpoints.js'
import { showToast } from './toast.js'
import { setDomainDesignerSelection, setDomainDesignerModalActive } from '../state/store.js'
import { initOverhangPathview }      from './overhang_pathview.js'
import { initDomainDesignerPanel }   from './domain_designer_panel.js'

// ── Debug instrumentation (Phase 3 fix-up) ───────────────────────────────────
// Flip to `false` to silence the Domain Designer console traces. The same
// pattern lives in each Domain Designer module — toggle each one independently
// when narrowing a bug.
const DEBUG = true
const _debug = (...args) => { if (DEBUG) console.debug('[DD-tab]', ...args) }

let _store    = null
let _modal    = null
let _modalContent = null
let _closeBtn = null

// ── Tab controller state ─────────────────────────────────────────────────────
// The Linker Generator tab was removed in favor of the Connection Types tab,
// which provides the same generation flow plus the icon-driven type picker.
const _OHC_TABS = ['domain-designer', 'connection-types']
const _OHC_TAB_STORAGE = 'nadoc.overhangsManager.activeTab'
let _activeTab = 'connection-types'
let _ddPathview = null
let _ddPanel    = null
let _ddInited   = false

// ── Connection Types tab (mock-up; selection only, no backend) ───────────────
// One variant per connection-type family, all on the standard blue background.
//
//  - end-to-root           : free end of one overhang meets the root of the
//                            other; backbones step at opposite ends.
//  - root-to-root          : both roots are inline (same x) at one end of the
//                            hybridized duplex; free ends point the other way.
//  - root-to-root-indirect : two separate duplexes joined by a shared linker
//                            strand (one continuous strand traces the top of
//                            one duplex, jogs over, and continues as the
//                            bottom of the other).
const _CT_STANDARD_BG = '#15233a'
const _CT_VARIANTS = [
  { id: 'end-to-root',              label: 'End-to-Root',              bg: _CT_STANDARD_BG },
  { id: 'root-to-root',             label: 'Root-to-Root',             bg: _CT_STANDARD_BG },
  { id: 'root-to-root-indirect',    label: 'Root-to-Root Indirect',    bg: _CT_STANDARD_BG },
  { id: 'end-to-end-indirect',      label: 'End-to-End Indirect',      bg: _CT_STANDARD_BG },
  { id: 'root-to-root-ssdna-linker', label: 'Root-to-Root ssDNA Linker', bg: _CT_STANDARD_BG },
  { id: 'end-to-end-ssdna-linker',   label: 'End-to-End ssDNA Linker',   bg: _CT_STANDARD_BG },
  { id: 'end-to-root-ssdna-linker',  label: 'End-to-Root ssDNA Linker',  bg: _CT_STANDARD_BG },
  { id: 'root-to-end-ssdna-linker',  label: 'Root-to-End ssDNA Linker',  bg: _CT_STANDARD_BG },
  { id: 'root-to-root-dsdna-linker', label: 'Root-to-Root dsDNA Linker', bg: _CT_STANDARD_BG },
  { id: 'end-to-end-dsdna-linker',   label: 'End-to-End dsDNA Linker',   bg: _CT_STANDARD_BG },
  { id: 'end-to-root-dsdna-linker',  label: 'End-to-Root dsDNA Linker',  bg: _CT_STANDARD_BG },
  { id: 'root-to-end-dsdna-linker',  label: 'Root-to-End dsDNA Linker',  bg: _CT_STANDARD_BG },
]
const _CT_STORAGE = 'nadoc.overhangsManager.connectionType'
// Neon colors for the LEFT / RIGHT overhang strands inside the connection-
// type icon. These match the list-row highlight colors so it's visually
// obvious which side of the icon corresponds to which list selection.
const _CT_LEFT_NEON  = '#00e1ff'
const _CT_RIGHT_NEON = '#ff36c6'
let _ctSelectedId = 'end-to-root'
let _ctSelectedA  = null   // overhang id selected from LEFT list
let _ctSelectedB  = null   // overhang id selected from RIGHT list
let _ctSelectedConnId = null  // currently-selected linker row in the table
let _ctInited     = false

// ── Public API ────────────────────────────────────────────────────────────────

export function initOverhangsManagerPopup({ store }) {
  _store = store

  _modal     = document.getElementById('overhangs-manager-modal')
  _modalContent = document.getElementById('ohc-modal-content')
  _closeBtn  = document.getElementById('ohc-close')
  if (!_modal) return

  _closeBtn.addEventListener('click', close)
  _modal.addEventListener('click', (e) => { if (e.target === _modal) close() })

  // ── Tab strip wiring (Phase 3 overhang revamp) ──────────────────────────
  // Inline closure mirroring the left-sidebar tab pattern at main.js#L8619.
  // DOM contract: `data-tab="id"` buttons + `id="tab-content-{id}"` panes.
  const tabStrip = _modal.querySelector('#ohc-tab-strip')
  if (tabStrip) {
    // Restore last-used tab from localStorage.
    try {
      const saved = localStorage.getItem(_OHC_TAB_STORAGE)
      if (saved && _OHC_TABS.includes(saved)) _activeTab = saved
    } catch { /* ignore */ }

    tabStrip.addEventListener('click', (ev) => {
      const btn = ev.target.closest('.ohc-tab')
      if (!btn) return
      const id = btn.dataset.tab
      if (!id || !_OHC_TABS.includes(id)) return
      _switchTab(id)
    })
  }

  _initConnectionTypesTab()
}

// ── Connection Types tab init + interactions ─────────────────────────────────

function _initConnectionTypesTab() {
  if (_ctInited) return
  const box     = document.getElementById('ct-button-box')
  const popover = document.getElementById('ct-popover')
  if (!box || !popover) return

  // Center action button. Label + behavior swap based on the selected
  // connection type:
  //  - Linker types:  "Generate Linker" (placeholder no-op for now)
  //  - Direct types:  "Make complementary" — writes the reverse complement
  //                   of overhang A's sequence into overhang B.
  const generateBtn = document.getElementById('ct-generate')
  generateBtn?.addEventListener('click', async (ev) => {
    ev.stopPropagation()
    if (generateBtn.disabled) return
    if (_ctIsDirectType(_ctSelectedId)) {
      await _onMakeComplementary(generateBtn)
    } else {
      await _onCtGenerateLinker(generateBtn)
    }
  })

  // Sequence rows under each overhang list. Show up only after an overhang
  // is selected on that side. Text input commits to the backend via
  // patchOverhang; "Gen" button calls generateOverhangRandomSequence
  // (same Johnson et al. algorithm used by the spreadsheet).
  for (const side of ['a', 'b']) {
    const input = document.getElementById(`ct-seq-input-${side}`)
    const gen   = document.getElementById(`ct-seq-gen-${side}`)
    if (!input || !gen) continue
    let lastVal = ''
    input.addEventListener('focus', () => { lastVal = input.value.trim().toUpperCase() })
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter')  { e.preventDefault(); input.blur() }
      if (e.key === 'Escape') { input.value = lastVal; input.blur() }
    })
    input.addEventListener('blur', async () => {
      const id = (side === 'a') ? _ctSelectedA : _ctSelectedB
      if (!id) return
      const next = input.value.trim().toUpperCase()
      if (next === lastVal) return
      // Strip any non-ACGTN characters that snuck in.
      const clean = next.replace(/[^ACGTN]/g, '')
      try {
        await patchOverhang(id, { sequence: clean || null })
        _refreshConnectionTypesUI()
      } catch (err) {
        showToast(err?.message ?? String(err))
        _refreshCtSeqRows()  // revert input to previous value
      }
    })
    gen.addEventListener('click', async (ev) => {
      ev.stopPropagation()
      const id = (side === 'a') ? _ctSelectedA : _ctSelectedB
      if (!id) return
      gen.disabled = true
      try {
        showToast('Using Johnson et al. overhang algorithm — DOI: 10.1021/acs.nanolett.9b02786')
        await generateOverhangRandomSequence(id)
        _refreshConnectionTypesUI()
      } catch (err) {
        showToast(err?.message ?? String(err))
      } finally {
        gen.disabled = false
      }
    })
  }

  // Bridge sequence editor — operates on the CURRENTLY-SELECTED linker row.
  // No selection → input + Gen are disabled and the boxes are empty. Edits
  // are live-PATCH'd to the selected connection on blur / Enter. The Gen
  // button writes the generated bridge to the selected linker too.
  const bridgeInputA = document.getElementById('ct-bridge-input-a')
  const bridgeInputB = document.getElementById('ct-bridge-input-b')
  const bridgeGenA   = document.getElementById('ct-bridge-gen-a')
  if (bridgeInputA) {
    let _bridgeLastVal = ''
    bridgeInputA.addEventListener('focus', () => { _bridgeLastVal = bridgeInputA.value })
    bridgeInputA.addEventListener('input', () => {
      const cleaned = bridgeInputA.value.toUpperCase().replace(/[^ACGTN]/g, '')
      if (cleaned !== bridgeInputA.value) bridgeInputA.value = cleaned
      _syncCtBridgeRcMirror()
    })
    bridgeInputA.addEventListener('keydown', (e) => {
      if (e.key === 'Enter')  { e.preventDefault(); bridgeInputA.blur() }
      if (e.key === 'Escape') { bridgeInputA.value = _bridgeLastVal; bridgeInputA.blur() }
    })
    bridgeInputA.addEventListener('blur', async () => {
      if (!_ctSelectedConnId) return
      const next = bridgeInputA.value.toUpperCase().replace(/[^ACGTN]/g, '')
      if (next === _bridgeLastVal) return
      try {
        await api.patchOverhangConnection(_ctSelectedConnId, { bridge_sequence: next })
        _bridgeLastVal = next
      } catch (err) {
        showToast(err?.message ?? String(err))
        bridgeInputA.value = _bridgeLastVal
        _syncCtBridgeRcMirror()
      }
    })
  }
  if (bridgeGenA) {
    bridgeGenA.addEventListener('click', async (ev) => {
      ev.stopPropagation()
      if (!_ctSelectedConnId) return   // double-guard; Gen is also `disabled`
      const conn = _connections().find(c => c.id === _ctSelectedConnId)
      // Length is whatever the selected linker was created with, in bp.
      const length = _linkerLengthInBp(conn)
      if (!Number.isFinite(length) || length <= 0) {
        showToast('Selected linker has no resolvable length.')
        return
      }
      bridgeGenA.disabled = true
      try {
        showToast('Using Johnson et al. overhang algorithm — DOI: 10.1021/acs.nanolett.9b02786')
        const seq = await generateRandomSequence(length)
        if (typeof seq === 'string' && seq) {
          await api.patchOverhangConnection(_ctSelectedConnId, { bridge_sequence: seq })
        } else {
          // `_request` returns null on any non-2xx response and parks the
          // status in `store.lastError`. Surface that here so the user
          // doesn't see a silent dead-button.
          const err = _store?.getState?.()?.lastError
          showToast(err?.status
            ? `Bridge sequence generation failed (HTTP ${err.status}): ${err.message ?? 'unknown'}`
            : 'Bridge sequence generation failed.')
        }
      } catch (err) {
        showToast(err?.message ?? String(err))
      } finally {
        bridgeGenA.disabled = !_ctSelectedConnId   // restore (still disabled if no selection)
      }
    })
  }

  try {
    const saved = localStorage.getItem(_CT_STORAGE)
    if (saved && _CT_VARIANTS.some(v => v.id === saved)) _ctSelectedId = saved
  } catch { /* ignore */ }

  // Build popover options once. Single row of tiles, one per connection type.
  popover.innerHTML = ''
  for (const v of _CT_VARIANTS) {
    const opt = document.createElement('button')
    opt.type = 'button'
    opt.className = 'ct-option'
    opt.dataset.variant = v.id
    opt.setAttribute('role', 'option')
    opt.title = v.label
    opt.innerHTML = _ctTileHTML(v.bg, v.id)
    opt.addEventListener('click', (ev) => {
      ev.stopPropagation()
      _ctSelectedId = v.id
      try { localStorage.setItem(_CT_STORAGE, v.id) } catch { /* ignore */ }
      _refreshConnectionTypesUI()
      _closeCtPopover()
    })
    // Red explanatory tooltip on hover when this variant is forbidden for
    // the currently-selected overhang pair. Suppresses the native `title`
    // tooltip while shown so the two don't overlap.
    opt.addEventListener('mouseenter', (ev) => _ctShowForbiddenTooltip(v.id, opt, ev))
    opt.addEventListener('mousemove',  (ev) => _ctMoveForbiddenTooltip(ev))
    opt.addEventListener('mouseleave', ()   => _ctHideForbiddenTooltip(opt))
    popover.appendChild(opt)
  }

  // Same forbidden-tooltip behavior on the button-box itself.
  box.addEventListener('mouseenter', (ev) => _ctShowForbiddenTooltip(_ctSelectedId, box, ev))
  box.addEventListener('mousemove',  (ev) => _ctMoveForbiddenTooltip(ev))
  box.addEventListener('mouseleave', ()   => _ctHideForbiddenTooltip(box))

  box.addEventListener('click', (ev) => {
    ev.stopPropagation()
    if (popover.hasAttribute('hidden')) _openCtPopover()
    else _closeCtPopover()
  })

  // Click outside the popover closes it.
  document.addEventListener('click', (ev) => {
    if (popover.hasAttribute('hidden')) return
    if (popover.contains(ev.target) || box.contains(ev.target)) return
    _closeCtPopover()
  })
  // Escape also closes.
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && !popover.hasAttribute('hidden')) _closeCtPopover()
  })

  _refreshConnectionTypesUI()

  // Re-render the Sequence column on any design change so it stays in sync
  // when overhang sequences are edited outside the popup (spreadsheet, undo,
  // file load) — `_refreshConnectionTypesUI`'s explicit calls only cover
  // edits that originate inside the Connection Types tab itself.
  _store?.subscribeSlice?.('design', () => {
    if (!_modal || _modal.style.display === 'none') return  // popup closed → skip
    _renderTable()
    _refreshCtBridgeBoxFromSelection()   // pull conn.bridge_sequence into the input
    _refreshCtSeqRows()                  // pull overhang.sequence into side inputs
  })

  _ctInited = true
}

function _openCtPopover() {
  const box     = document.getElementById('ct-button-box')
  const popover = document.getElementById('ct-popover')
  if (!box || !popover) return
  // Position the popover directly under the button-box, in viewport coords
  // (the modal scroll-container clips overflow, so we position fixed instead).
  const r = box.getBoundingClientRect()
  popover.style.position = 'fixed'
  popover.style.left = `${Math.round(r.left)}px`
  popover.style.top  = `${Math.round(r.bottom + 6)}px`
  popover.hidden = false
  box.setAttribute('aria-expanded', 'true')
}

function _closeCtPopover() {
  const box     = document.getElementById('ct-button-box')
  const popover = document.getElementById('ct-popover')
  if (!popover) return
  popover.hidden = true
  if (box) box.setAttribute('aria-expanded', 'false')
}

function _refreshConnectionTypesUI() {
  const box     = document.getElementById('ct-button-box')
  const popover = document.getElementById('ct-popover')
  const variant = _CT_VARIANTS.find(v => v.id === _ctSelectedId) ?? _CT_VARIANTS[0]
  if (box) box.innerHTML = _ctTileHTML(variant.bg, variant.id)
  if (popover) {
    for (const opt of popover.querySelectorAll('.ct-option')) {
      opt.classList.toggle('is-selected', opt.dataset.variant === _ctSelectedId)
    }
  }
  _refreshCtListSelection()
  // Linker-length + bridge-sequence visibility: shown for all linker-bearing
  // types (anything that's not a direct overhang-overhang connection). The
  // bridge section's second row only appears for dsDNA.
  const direct = _ctIsDirectType(_ctSelectedId)
  const hasLinker = !direct
  const lengthRow = document.getElementById('ct-length-row')
  if (lengthRow) lengthRow.hidden = !hasLinker
  const bridgeSec  = document.getElementById('ct-bridge-section')
  const bridgeRowB = document.getElementById('ct-bridge-row-b')
  if (bridgeSec)  bridgeSec.hidden  = !hasLinker
  if (bridgeRowB) bridgeRowB.hidden = !_ctIsDsLinker(_ctSelectedId)
  _syncCtBridgeRcMirror()
  // Center action button — label + tooltip + disabled state vary by mode.
  const generateBtn = document.getElementById('ct-generate')
  if (generateBtn) {
    if (direct) {
      const aSeq = _selectedOverhangSequence('A')
      const hasBoth = _ctSelectedA != null && _ctSelectedB != null
      generateBtn.textContent = 'Make complementary'
      generateBtn.disabled = !hasBoth || !aSeq
      generateBtn.title = hasBoth
        ? (aSeq
            ? "Overwrite overhang B's sequence with the reverse complement of overhang A's sequence"
            : "Assign overhang A a sequence first — Make complementary will use it to set overhang B")
        : 'Select an overhang on each side first'
    } else {
      // Linker mode: enable only when both overhangs are selected AND the
      // polarity combination is not forbidden for this connection type.
      const hasBoth   = _ctSelectedA != null && _ctSelectedB != null
      const L         = hasBoth ? _endOf(_ctSelectedA) : null
      const R         = hasBoth ? _endOf(_ctSelectedB) : null
      const forbidden = hasBoth && _ctIsForbidden(_ctSelectedId, L, R)
      generateBtn.textContent = 'Generate Linker'
      generateBtn.disabled = !hasBoth || forbidden
      generateBtn.title = !hasBoth
        ? 'Select an overhang on each side first'
        : forbidden
          ? "This polarity combination isn't valid for the selected connection type"
          : 'Generate a linker for the selected connection type'
    }
  }
  _refreshCtSeqRows()
  // Keep the linker table's Sequence column in sync with the current overhang
  // sequences. Calls cheap enough that re-running on every CT-tab refresh is
  // simpler than threading explicit refreshes through every overhang-edit
  // call site. Also refreshes the bridge input + Gen enable state in case
  // the variant change toggled ds/ss (the second box shows / hides) or the
  // selection state changed.
  _renderTable()
  _refreshCtBridgeBoxFromSelection()
}

function _ctIsDirectType(id) {
  return id === 'end-to-root' || id === 'root-to-root'
}

function _ctIsDsLinker(id) {
  return typeof id === 'string' && id.includes('dsdna')
}

// Resolve a connection's bridge length in bp. `length_unit` may be 'bp' or
// 'nm'; nm is converted via the standard B-DNA rise (0.334 nm/bp).
function _linkerLengthInBp(conn) {
  if (!conn) return NaN
  const v = Number(conn.length_value)
  if (!Number.isFinite(v) || v <= 0) return NaN
  return conn.length_unit === 'nm' ? Math.max(1, Math.round(v / 0.334)) : Math.round(v)
}

// Sync the bridge input + Gen button state with `_ctSelectedConnId`.
// No selection → both disabled, both boxes empty. Selected → both enabled,
// input shows `conn.bridge_sequence` (or empty), Gen ready.
function _refreshCtBridgeBoxFromSelection() {
  const inputA = document.getElementById('ct-bridge-input-a')
  const inputB = document.getElementById('ct-bridge-input-b')
  const genA   = document.getElementById('ct-bridge-gen-a')
  const conn = _ctSelectedConnId
    ? _connections().find(c => c.id === _ctSelectedConnId)
    : null
  // Drop a stale selection pointer (e.g. the selected linker was deleted
  // through another path) so subsequent checks see "no selection".
  if (_ctSelectedConnId && !conn) _ctSelectedConnId = null
  const hasSel = !!conn
  if (inputA) {
    inputA.disabled = !hasSel
    inputA.value = conn?.bridge_sequence ?? ''
    inputA.placeholder = hasSel
      ? (`${_linkerLengthInBp(conn) || ''} bp — type or Gen to assign`)
      : 'Select a linker row to edit its bridge'
  }
  if (genA) {
    genA.disabled = !hasSel
    genA.title = hasSel
      ? 'Generate a random bridge sequence for the selected linker'
      : 'Select a linker row in the table first'
  }
  _syncCtBridgeRcMirror()
  if (inputB) inputB.disabled = !hasSel || !_ctIsDsLinker(_ctSelectedId)
}

// Keep the ds bridge's "B" input mirroring the reverse complement of the
// "A" input. Called whenever the A input changes, the connection type
// switches between ss/ds, or a linker-table row is clicked.
function _syncCtBridgeRcMirror() {
  const a = document.getElementById('ct-bridge-input-a')
  const b = document.getElementById('ct-bridge-input-b')
  if (!a || !b) return
  if (!_ctIsDsLinker(_ctSelectedId)) { b.value = ''; return }
  b.value = _reverseComplement(a.value || '')
}

function _selectedOverhangSequence(side) {
  const id = side === 'A' ? _ctSelectedA : _ctSelectedB
  if (!id) return null
  const o = _overhangs().find(x => x.id === id)
  return o?.sequence ?? null
}

// 5'→3' reverse complement of an ACGTN sequence. Preserves any non-ACGTN
// characters as-is (defensive — backend would reject them anyway).
function _reverseComplement(seq) {
  if (!seq) return ''
  const map = { A: 'T', T: 'A', C: 'G', G: 'C', N: 'N',
                a: 't', t: 'a', c: 'g', g: 'c', n: 'n' }
  let out = ''
  for (let i = seq.length - 1; i >= 0; i--) out += map[seq[i]] ?? seq[i]
  return out
}

// Map a Connection Type id to the (attach_a, attach_b) pair the backend
// expects. Tested longest-prefix-first so "end-to-root-…" and "root-to-end-…"
// linker variants don't collide with the same-attach families.
//   "end-to-root[-*]"   → (free_end, root)
//   "root-to-end-*"     → (root, free_end)
//   "root-to-root[-*]"  → both root
//   "end-to-end[-*]"    → both free_end
function _ctAttachPair(id) {
  if (id?.startsWith('end-to-root')) return ['free_end', 'root']
  if (id?.startsWith('root-to-end')) return ['root', 'free_end']
  if (id?.startsWith('root-to-root')) return ['root', 'root']
  if (id?.startsWith('end-to-end'))   return ['free_end', 'free_end']
  return ['root', 'root']
}

// Map a Connection Type id to the backend's `linker_type` ('ss' | 'ds').
// Indirect / ssDNA-linker variants both map to 'ss' (the backend has no
// separate "indirect" type — indirect is just a short / zero-length ss
// bridge that the visualization renders without an explicit gap).
function _ctLinkerTypeForId(id) {
  return id?.includes('dsdna') ? 'ds' : 'ss'
}

// Generate-Linker action. Creates an `OverhangConnection` from the
// currently-selected pair of overhangs and the active CT variant; on
// success clears A/B and refreshes the linker table.
async function _onCtGenerateLinker(btn) {
  if (!_ctSelectedA || !_ctSelectedB) return
  const lenEl = document.getElementById('ct-length')
  const lengthValue = parseFloat(lenEl?.value ?? '')
  if (!Number.isFinite(lengthValue) || lengthValue <= 0) {
    showToast('Linker length must be a positive number.')
    return
  }
  const [attachA, attachB] = _ctAttachPair(_ctSelectedId)
  const payload = {
    overhang_a_id:     _ctSelectedA,
    overhang_a_attach: attachA,
    overhang_b_id:     _ctSelectedB,
    overhang_b_attach: attachB,
    linker_type:       _ctLinkerTypeForId(_ctSelectedId),
    length_value:      lengthValue,
    length_unit:       'bp',
  }
  btn.disabled = true
  // Flush any uncommitted side-input edits before creating the linker.
  // The side input commits on blur via an async `patchOverhang`, which
  // races the click handler — clicking Generate Linker without first
  // tabbing out of an overhang sequence input can otherwise create the
  // linker against not-yet-committed overhang sequences and the table's
  // complement portion renders as N×L. Awaiting each pending patch here
  // eliminates the race.
  try {
    for (const side of ['a', 'b']) {
      const input = document.getElementById(`ct-seq-input-${side}`)
      if (!input) continue
      const ovhgId = side === 'a' ? _ctSelectedA : _ctSelectedB
      if (!ovhgId) continue
      const ovhg = _overhangs().find(o => o.id === ovhgId)
      const typed = (input.value ?? '').toUpperCase().replace(/[^ACGTN]/g, '')
      const stored = ovhg?.sequence ?? ''
      if (typed === stored) continue   // nothing to commit
      await patchOverhang(ovhgId, { sequence: typed || null })
    }
  } catch (err) {
    showToast(`Couldn't commit overhang sequences before generating linker: ${err?.message ?? err}`)
    btn.disabled = false
    return
  }
  // Snapshot existing conn ids so we can pick out the new one after the call
  // and auto-select its row in the linker table.
  const before = new Set(_connections().map(c => c.id))
  try {
    await api.createOverhangConnection(payload)
    const newConn = _connections().find(c => !before.has(c.id))
    _ctSelectedConnId = newConn?.id ?? null
    // Leave _ctSelectedA / _ctSelectedB intact so the just-created linker's
    // overhangs stay highlighted in the side lists (the new linker row is
    // also highlighted in the table) — selection of the linker IS the
    // selection of its two overhangs.
    _renderTable()
    _refreshConnectionTypesUI()
    _refreshCtPopoverTiles()
  } catch (err) {
    showToast(err?.message ?? String(err))
  } finally {
    _refreshConnectionTypesUI()
  }
}

// Wire the "Make complementary" action — patches overhang B with the
// reverse complement of overhang A's sequence AND creates an
// OverhangBinding referencing the tip sub-domains of each overhang on
// the attach ends selected by the current CT tile (end-to-root or
// root-to-root). The binding starts unbound; the user toggles its
// Bound column or the main-app sidebar button to activate it.
//
// Backend per-pair mutex (`_binding_pair_keys`) is the authority — if a
// binding already exists for this sub-domain pair the create call
// returns 409 and we surface it via a toast. The RC-write step is
// always performed first so the existing one-shot convenience still
// works for users who only want to sync sequences.
async function _onMakeComplementary(btn) {
  const aSeq = _selectedOverhangSequence('A')
  if (!aSeq || !_ctSelectedA || !_ctSelectedB) return
  const rc = _reverseComplement(aSeq).toUpperCase()
  btn.disabled = true
  try {
    // 1) sequence sync (existing behaviour)
    await patchOverhang(_ctSelectedB, { sequence: rc })

    // 2) create binding at the tip sub-domains for this tile's attach combo
    const [attachA, attachB] = _ctAttachPair(_ctSelectedId)
    const sdAId = _subDomainAtAttach(_ctSelectedA, attachA)
    const sdBId = _subDomainAtAttach(_ctSelectedB, attachB)
    if (!sdAId || !sdBId) {
      alert(
        'Make complementary: cannot create binding — overhangs must have sub-domains defined.\n\n' +
        'The RC sequence sync still happened.'
      )
      return
    }
    // Pre-flight: warn the user if sub-domain lengths mismatch, since the
    // backend binding-create requires equal-length pairs. We still attempt
    // the call below so the actual server error message wins on edge cases.
    const ohById = new Map(_overhangs().map(o => [o.id, o]))
    const sdA = (ohById.get(_ctSelectedA)?.sub_domains ?? []).find(sd => sd.id === sdAId)
    const sdB = (ohById.get(_ctSelectedB)?.sub_domains ?? []).find(sd => sd.id === sdBId)
    if (sdA && sdB && sdA.length_bp !== sdB.length_bp) {
      alert(
        `Make complementary did the sequence sync, but the binding pair was not created.\n\n` +
        `The two tip sub-domains have different lengths (${sdA.length_bp} bp vs ${sdB.length_bp} bp). ` +
        `OverhangBinding requires equal-length sub-domains.\n\n` +
        `Fix: open the Domain Designer for one of the overhangs and resize the tip ` +
        `sub-domain so the two match. Then re-click "Make complementary".`
      )
      _refreshConnectionTypesUI()
      return
    }
    // Skip the create call if a binding already exists for this pair.
    const existing = _bindingsForOverhangPair(_ctSelectedA, _ctSelectedB)
      .find(b =>
        (b.sub_domain_a_id === sdAId && b.sub_domain_b_id === sdBId) ||
        (b.sub_domain_a_id === sdBId && b.sub_domain_b_id === sdAId),
      )
    if (existing) {
      showToast?.(`Pair already exists as binding ${existing.name ?? existing.id.slice(0, 6)} — toggle Bound in the table to engage it.`)
    } else {
      try {
        await createOverhangBinding({
          sub_domain_a_id: sdAId,
          sub_domain_b_id: sdBId,
        })
      } catch (err) {
        // Unmissable alert: the toast pattern is too subtle for this case
        // since the user often expects a new B1 row to appear and doesn't
        // notice the toast when nothing visible changes.
        const detail = err?.detail || err?.message || String(err)
        alert(
          `Make complementary did the sequence sync, but the binding pair was not created.\n\n` +
          `Server said: ${detail}\n\n` +
          `Common causes:\n` +
          `  • Sub-domain lengths don't match (resize one to match the other)\n` +
          `  • Sequences aren't reverse-complementary (try again — RC sync may have raced)\n` +
          `  • This pair is already a linker or another binding`
        )
      }
    }
    _refreshConnectionTypesUI()
  } catch (err) {
    showToast(err?.message ?? String(err))
  } finally {
    _refreshConnectionTypesUI()
  }
}

// Sequence row under each list: shown only when the side has a selection;
// populated from the selected overhang's current sequence (or "N×<length>"
// placeholder when unsequenced — matches the spreadsheet column).
function _refreshCtSeqRows() {
  for (const side of ['a', 'b']) {
    const row   = document.getElementById(`ct-seq-row-${side}`)
    const input = document.getElementById(`ct-seq-input-${side}`)
    if (!row || !input) continue
    const id = (side === 'a') ? _ctSelectedA : _ctSelectedB
    if (!id) { row.hidden = true; continue }
    const ovhg = _overhangs().find(o => o.id === id)
    if (!ovhg) { row.hidden = true; continue }
    row.hidden = false
    const len = _overhangLengthBp(ovhg)
    if (ovhg.sequence) {
      input.value = ovhg.sequence
      input.placeholder = ''
    } else {
      input.value = ''
      input.placeholder = len ? `N×${len}` : 'sequence…'
    }
  }
}

// Sum of an overhang's sub-domain lengths == the backing domain length
// (invariant enforced by the OverhangSpec model).
function _overhangLengthBp(ovhg) {
  return (ovhg?.sub_domains ?? []).reduce((s, sd) => s + (sd.length_bp ?? 0), 0)
}

// Highlight the currently-selected A/B rows in each list, and disable the
// opposite-side row for the same overhang (since you can't pick the same
// overhang on both sides).
function _refreshCtListSelection() {
  for (const row of document.querySelectorAll('#ct-list-a .ohc-list-row')) {
    row.classList.toggle('ct-selected-a', row.dataset.ovhgId === _ctSelectedA)
    row.classList.toggle('is-disabled',
      _ctSelectedB != null && row.dataset.ovhgId === _ctSelectedB)
  }
  for (const row of document.querySelectorAll('#ct-list-b .ohc-list-row')) {
    row.classList.toggle('ct-selected-b', row.dataset.ovhgId === _ctSelectedB)
    row.classList.toggle('is-disabled',
      _ctSelectedA != null && row.dataset.ovhgId === _ctSelectedA)
  }
}

// Render the Connection Types tab's overhang lists. Each row is clickable —
// selecting an overhang on a side sets _ctSelectedA / _ctSelectedB, drives
// the icon's strand color + polarity marker on that side, and highlights
// the row in the matching neon color.
function _renderCtLists() {
  const listA = document.getElementById('ct-list-a')
  const listB = document.getElementById('ct-list-b')
  if (!listA || !listB) return
  const overhangs = _overhangs()
  listA.innerHTML = ''
  listB.innerHTML = ''
  if (overhangs.length === 0) {
    const empty = '<div style="padding:14px;font-size:11px;color:#6e7681;text-align:center">No overhangs in this design.</div>'
    listA.innerHTML = empty
    listB.innerHTML = empty
    return
  }
  const sorted = [...overhangs].sort((a, b) => _displayName(a).localeCompare(_displayName(b), undefined, { numeric: true }))
  for (const ovhg of sorted) {
    listA.appendChild(_makeCtListRow(ovhg, 'A'))
    listB.appendChild(_makeCtListRow(ovhg, 'B'))
  }
  _refreshCtListSelection()
}

function _makeCtListRow(ovhg, side) {
  const row = document.createElement('div')
  row.className = 'ohc-list-row'
  row.dataset.ovhgId = ovhg.id
  row.dataset.side = side
  const nameEl = document.createElement('span')
  nameEl.textContent = _displayName(ovhg)
  const tagEl = document.createElement('span')
  tagEl.className = 'ohc-end-tag'
  tagEl.textContent = _endTag(ovhg.id)
  row.append(nameEl, tagEl)
  row.addEventListener('click', () => _onCtPickRow(side, ovhg.id))
  return row
}

function _onCtPickRow(side, ovhgId) {
  // Can't pick the same overhang on both sides.
  const opposite = side === 'A' ? _ctSelectedB : _ctSelectedA
  if (ovhgId === opposite) return
  if (side === 'A') {
    _ctSelectedA = (_ctSelectedA === ovhgId) ? null : ovhgId
  } else {
    _ctSelectedB = (_ctSelectedB === ovhgId) ? null : ovhgId
  }
  _refreshConnectionTypesUI()
  _refreshCtPopoverTiles()
}

// Re-render all popover tiles (used after polarity toggle so visible options
// in the open popover update too).
function _refreshCtPopoverTiles() {
  const popover = document.getElementById('ct-popover')
  if (!popover) return
  for (const opt of popover.querySelectorAll('.ct-option')) {
    const id = opt.dataset.variant
    const v = _CT_VARIANTS.find(x => x.id === id)
    if (v) opt.innerHTML = _ctTileHTML(v.bg, v.id)
  }
}

// Build a tile (background + connection-type icon). The icon is chosen by id.
// Polarity (5'/3') is derived from the user's overhang selection in the
// LEFT/RIGHT lists — each overhang id encodes its terminal-end polarity via
// a `_5p` / `_3p` suffix (parsed by `_endOf`). When nothing is selected on a
// side, that side's strand stays white and no marker is drawn; once an
// overhang is picked the strand picks up the matching neon color and the
// polarity marker appears.
function _ctTileHTML(bg, type) {
  const hasA = _ctSelectedA != null
  const hasB = _ctSelectedB != null
  const L = hasA ? _endOf(_ctSelectedA) : null
  const R = hasB ? _endOf(_ctSelectedB) : null
  const warn = hasA && hasB && _ctIsForbidden(type, L, R)
  const leftColor  = hasA ? _CT_LEFT_NEON  : 'white'
  const rightColor = hasB ? _CT_RIGHT_NEON : 'white'
  let svg
  if      (type === 'root-to-root')              svg = _ctRootToRootSvg(L, R, warn, leftColor, rightColor)
  else if (type === 'root-to-root-indirect')     svg = _ctRootToRootIndirectSvg(L, R, warn, leftColor, rightColor)
  else if (type === 'end-to-end-indirect')       svg = _ctEndToEndIndirectSvg(L, R, warn, leftColor, rightColor)
  else if (type === 'root-to-root-ssdna-linker') svg = _ctRootToRootSsdnaLinkerSvg(L, R, warn, leftColor, rightColor)
  else if (type === 'end-to-end-ssdna-linker')   svg = _ctEndToEndSsdnaLinkerSvg(L, R, warn, leftColor, rightColor)
  else if (type === 'end-to-root-ssdna-linker')  svg = _ctMixedSsdnaLinkerSvg(false, true,  L, R, warn, leftColor, rightColor)
  else if (type === 'root-to-end-ssdna-linker')  svg = _ctMixedSsdnaLinkerSvg(true,  false, L, R, warn, leftColor, rightColor)
  else if (type === 'root-to-root-dsdna-linker') svg = _ctRootToRootDsdnaLinkerSvg(L, R, warn, leftColor, rightColor)
  else if (type === 'end-to-end-dsdna-linker')   svg = _ctEndToEndDsdnaLinkerSvg(L, R, warn, leftColor, rightColor)
  else if (type === 'end-to-root-dsdna-linker')  svg = _ctMixedDsdnaLinkerSvg(false, true,  L, R, warn, leftColor, rightColor)
  else if (type === 'root-to-end-dsdna-linker')  svg = _ctMixedDsdnaLinkerSvg(true,  false, L, R, warn, leftColor, rightColor)
  else                                           svg = _ctEndToRootSvg(L, R, warn, leftColor, rightColor)
  return `<div class="ct-tile" style="background:${bg}">${svg}</div>`
}

// Helper: flip 5p ↔ 3p. Used when deriving linker-strand terminus polarity
// from the user-set switch polarity (which represents the overhang's free
// end). The linker strand pairs antiparallel with the overhang, so the
// linker terminus polarity is the inverse of whatever sits across the
// duplex at that side — see notes in each icon function.
function _oppPolarity(p) {
  if (p === '5p') return '3p'
  if (p === '3p') return '5p'
  return null  // propagate "no selection" through the linker-terminus derivation
}

// Combination validity. The user-set polarities (5p/3p) represent each
// overhang's FREE-END polarity; from those we can decide whether a
// Watson-Crick antiparallel linker is geometrically possible.
//
//  - ssDNA / indirect linker types: forbidden when LEFT === RIGHT (linker
//    is a single strand that runs through both duplex regions; if both
//    overhang free ends share polarity, the linker would need 5'/5' or
//    3'/3' ends — impossible for a single strand).
//  - dsDNA linker types: forbidden when LEFT !== RIGHT (the two linker
//    strands need to be antiparallel to each other in the body; opposite-
//    polarity overhangs force them parallel).
function _ctIsForbidden(type, L, R) {
  if (L == null || R == null) return false  // unset polarities can't violate a rule
  // Same-attach linker families (both root, or both free-end).
  if (type === 'root-to-root-dsdna-linker' || type === 'end-to-end-dsdna-linker') {
    return L !== R   // ds bridge halves must pair antiparallel
  }
  if (type === 'root-to-root-ssdna-linker' || type === 'end-to-end-ssdna-linker' ||
      type === 'root-to-root-indirect'    || type === 'end-to-end-indirect') {
    return L === R   // ss bridge can't have matching 5'/5' or 3'/3' termini
  }
  // Mixed-attach linker families (one root, one free-end). The
  // comp_first := (5p AND free) OR (3p AND root) polarity flips between
  // the two sides, so the Watson-Crick parity condition inverts vs. the
  // same-attach families:
  //   ds wants comp_first(A) == comp_first(B) → L != R for mixed-attach
  //   ss wants comp_first(A) != comp_first(B) → L == R for mixed-attach
  if (type === 'end-to-root-dsdna-linker' || type === 'root-to-end-dsdna-linker') {
    return L === R
  }
  if (type === 'end-to-root-ssdna-linker' || type === 'root-to-end-ssdna-linker') {
    return L !== R
  }
  // Direct connections: derived from antiparallel Watson-Crick pairing of
  // each strand's connection end relative to its free-end polarity (set by
  // the user-selected overhang).
  if (type === 'end-to-root')  return L !== R
  if (type === 'root-to-root') return L === R
  return false
}

// Human-readable explanation for why the current overhang pair is forbidden
// under the given connection type. Returns null when the combination is
// valid (or undetermined because polarities aren't set on both sides).
// Surfaced as a red-text tooltip on hover over the button-box / popover tiles.
function _ctForbiddenReason(type, L, R) {
  if (!_ctIsForbidden(type, L, R)) return null
  const pol = (p) => (p === '5p' ? "5'" : "3'")
  const pair = `${pol(L)}/${pol(R)}`
  if (type === 'end-to-root') {
    return `End-to-root direct: Watson-Crick hybridization needs the same polarity on both overhangs. ` +
           `${pair} would force a parallel duplex.`
  }
  if (type === 'root-to-root') {
    return `Root-to-root direct: antiparallel Watson-Crick pairing needs opposite polarities ` +
           `(one 5', one 3'). ${pair} would force a parallel duplex.`
  }
  if (type === 'root-to-root-dsdna-linker' || type === 'end-to-end-dsdna-linker') {
    return `dsDNA linker (same attach): the two bridge strands run antiparallel on the virtual helix, ` +
           `so the linked overhangs must share polarity. ${pair} would force the bridge halves parallel.`
  }
  if (type === 'end-to-root-dsdna-linker' || type === 'root-to-end-dsdna-linker') {
    return `dsDNA linker (mixed attach): one root + one free-end flips one side's comp-first polarity, ` +
           `so the overhangs must have OPPOSITE polarity. ${pair} would force the bridge halves parallel.`
  }
  if (type === 'root-to-root-ssdna-linker' || type === 'end-to-end-ssdna-linker' ||
      type === 'root-to-root-indirect'    || type === 'end-to-end-indirect') {
    return `Single-strand bridge (same attach): one continuous 5'→3' strand can't terminate ` +
           `${pol(L)}/${pol(R)} on both ends. Pick overhangs with opposite polarities.`
  }
  if (type === 'end-to-root-ssdna-linker' || type === 'root-to-end-ssdna-linker') {
    return `Single-strand bridge (mixed attach): one root + one free-end flips one side's comp-first ` +
           `polarity, so the overhangs must MATCH polarity. ${pair} breaks the continuous 5'→3' bridge.`
  }
  return 'This polarity combination is not valid for the selected connection type.'
}

// ── Forbidden-combination hover tooltip ──────────────────────────────────────
// Floating red-text tooltip displayed when the user hovers a CT button-box or
// popover tile whose variant is forbidden for the current overhang pair.
// One shared element re-used for both; positioned in fixed viewport coords
// near the mouse so it works inside the modal's clipping scroll container.

let _ctForbiddenTooltipEl = null

function _ctEnsureForbiddenTooltip() {
  if (_ctForbiddenTooltipEl) return _ctForbiddenTooltipEl
  const el = document.createElement('div')
  el.id = 'ct-rule-tooltip'
  el.setAttribute('role', 'tooltip')
  el.style.cssText = [
    'position:fixed',
    'z-index:10001',
    'max-width:280px',
    'padding:8px 10px',
    'background:#1a0a0a',
    'border:1px solid #a83232',
    'border-radius:4px',
    'color:#ff6b6b',
    'font:12px/1.4 monospace',
    'box-shadow:0 4px 14px rgba(0,0,0,0.5)',
    'pointer-events:none',
    'display:none',
    'white-space:normal',
  ].join(';')
  document.body.appendChild(el)
  _ctForbiddenTooltipEl = el
  return el
}

function _ctShowForbiddenTooltip(type, anchorEl, ev) {
  const L = _endOf(_ctSelectedA)
  const R = _endOf(_ctSelectedB)
  const reason = _ctForbiddenReason(type, L, R)
  if (!reason) return
  const el = _ctEnsureForbiddenTooltip()
  el.textContent = reason
  el.style.display = 'block'
  // Suppress the native `title` tooltip while ours is visible.
  if (anchorEl && anchorEl.title) {
    anchorEl.dataset.ctSavedTitle = anchorEl.title
    anchorEl.title = ''
  }
  _ctMoveForbiddenTooltip(ev)
}

function _ctMoveForbiddenTooltip(ev) {
  const el = _ctForbiddenTooltipEl
  if (!el || el.style.display === 'none') return
  // Offset from cursor so the tooltip doesn't sit under the pointer; clamp
  // to the viewport to keep the full text visible near edges.
  const offset = 14
  const r = el.getBoundingClientRect()
  const x = Math.min(window.innerWidth  - r.width  - 4, ev.clientX + offset)
  const y = Math.min(window.innerHeight - r.height - 4, ev.clientY + offset)
  el.style.left = `${Math.max(4, x)}px`
  el.style.top  = `${Math.max(4, y)}px`
}

function _ctHideForbiddenTooltip(anchorEl) {
  if (_ctForbiddenTooltipEl) _ctForbiddenTooltipEl.style.display = 'none'
  if (anchorEl?.dataset?.ctSavedTitle != null) {
    anchorEl.title = anchorEl.dataset.ctSavedTitle
    delete anchorEl.dataset.ctSavedTitle
  }
}

// Yellow warning triangle (⚠) centered over the tile when the user picks a
// forbidden polarity combination for the active connection type. Rendered as
// part of the SVG so it scales with the icon.
function _warningOverlay(viewW, viewH) {
  const cx = viewW / 2
  const cy = viewH / 2
  const r = Math.min(viewW, viewH) * 0.28
  const top    = `${cx},${cy - r}`
  const left   = `${cx - r * 0.9},${cy + r * 0.7}`
  const right  = `${cx + r * 0.9},${cy + r * 0.7}`
  return `
    <g pointer-events="none">
      <polygon points="${top} ${left} ${right}"
               fill="#f5c518" stroke="#5a3a00" stroke-width="1.2" stroke-linejoin="round"/>
      <text x="${cx}" y="${cy + r * 0.4}"
            font-family="sans-serif" font-size="${r * 0.95}" font-weight="bold"
            text-anchor="middle" fill="#5a3a00">!</text>
    </g>`
}

// Render a polarity marker at (x, y) on an overhang's terminal end.
// `polarity` is '5p' (square) or '3p' (triangle).
// `dir` is the direction the marker points AWAY from the strand body —
// used for the triangle's apex direction; ignored for the square. May be a
// cardinal string ('left' / 'right' / 'up' / 'down') OR an [dx, dy] array
// for arbitrary angles (used for triangles on slanted strands).
function _polarityMarker(x, y, dir, polarity, color = 'white') {
  if (polarity !== '5p' && polarity !== '3p') return ''  // no marker when nothing selected
  const S = 3
  const FILL = color
  if (polarity === '5p') {
    return `<rect x="${x - S}" y="${y - S}" width="${S * 2}" height="${S * 2}" fill="${FILL}"/>`
  }
  let dx, dy
  if (Array.isArray(dir)) {
    [dx, dy] = dir
    const len = Math.hypot(dx, dy) || 1
    dx /= len; dy /= len
  } else {
    switch (dir) {
      case 'left':  dx = -1; dy = 0; break
      case 'right': dx =  1; dy = 0; break
      case 'up':    dx = 0; dy = -1; break
      case 'down':  dx = 0; dy =  1; break
      default:      dx = 1; dy = 0
    }
  }
  // Apex points in (dx, dy) direction; base perpendicular at the far side.
  const ax = x + dx * S
  const ay = y + dy * S
  const px = -dy
  const py =  dx
  const b1x = x - dx * S + px * S
  const b1y = y - dy * S + py * S
  const b2x = x - dx * S - px * S
  const b2y = y - dy * S - py * S
  const f = (n) => Number.isInteger(n) ? `${n}` : n.toFixed(2)
  return `<polygon points="${f(ax)},${f(ay)} ${f(b1x)},${f(b1y)} ${f(b2x)},${f(b2y)}" fill="${FILL}"/>`
}

// End-to-root: the two overhang roots sit at OPPOSITE ends of the hybridized
// duplex. Drawn as a Z-shape: top backbone exits up-right; bottom backbone
// enters up-left. The two end-steps lie at different x-positions.
function _ctEndToRootSvg(L = null, R = null, warn = false, leftColor = 'white', rightColor = 'white') {
  // Top backbone = LEFT overhang (free end at (6, 14)).
  // Bottom backbone = RIGHT overhang (free end at (94, 22)).
  return `
    <svg viewBox="0 0 100 36" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="16" y1="15" x2="16" y2="21"/>
        <line x1="20" y1="15" x2="20" y2="21"/>
        <line x1="24" y1="15" x2="24" y2="21"/>
        <line x1="28" y1="15" x2="28" y2="21"/>
        <line x1="32" y1="15" x2="32" y2="21"/>
        <line x1="36" y1="15" x2="36" y2="21"/>
        <line x1="40" y1="15" x2="40" y2="21"/>
        <line x1="44" y1="15" x2="44" y2="21"/>
        <line x1="48" y1="15" x2="48" y2="21"/>
        <line x1="52" y1="15" x2="52" y2="21"/>
        <line x1="56" y1="15" x2="56" y2="21"/>
        <line x1="60" y1="15" x2="60" y2="21"/>
        <line x1="64" y1="15" x2="64" y2="21"/>
        <line x1="68" y1="15" x2="68" y2="21"/>
        <line x1="72" y1="15" x2="72" y2="21"/>
        <line x1="76" y1="15" x2="76" y2="21"/>
        <line x1="80" y1="15" x2="80" y2="21"/>
        <line x1="84" y1="15" x2="84" y2="21"/>
      </g>
      <path d="M 6 14 L 86 14 L 86 6"
            stroke="${leftColor}" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M 14 30 L 14 22 L 94 22"
            stroke="${rightColor}" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      ${_polarityMarker(6,  14, 'left',  L, leftColor)}
      ${_polarityMarker(94, 22, 'right', R, rightColor)}
      ${warn ? _warningOverlay(100, 36) : ''}
    </svg>`
}

// Root-to-root: both overhang roots are INLINE (same x) at one end of the
// hybridized duplex, but they cross into helices on OPPOSITE sides of the
// duplex — so the root stub on the top backbone points UP, and the stub on
// the bottom backbone points DOWN. Free ends point right.
function _ctRootToRootSvg(L = null, R = null, warn = false, leftColor = 'white', rightColor = 'white') {
  // Top strand = LEFT overhang. Bottom strand = RIGHT overhang.
  return `
    <svg viewBox="0 0 100 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="26" y1="19" x2="26" y2="25"/>
        <line x1="30" y1="19" x2="30" y2="25"/>
        <line x1="34" y1="19" x2="34" y2="25"/>
        <line x1="38" y1="19" x2="38" y2="25"/>
        <line x1="42" y1="19" x2="42" y2="25"/>
        <line x1="46" y1="19" x2="46" y2="25"/>
        <line x1="50" y1="19" x2="50" y2="25"/>
        <line x1="54" y1="19" x2="54" y2="25"/>
        <line x1="58" y1="19" x2="58" y2="25"/>
        <line x1="62" y1="19" x2="62" y2="25"/>
        <line x1="66" y1="19" x2="66" y2="25"/>
        <line x1="70" y1="19" x2="70" y2="25"/>
        <line x1="74" y1="19" x2="74" y2="25"/>
        <line x1="78" y1="19" x2="78" y2="25"/>
        <line x1="82" y1="19" x2="82" y2="25"/>
        <line x1="86" y1="19" x2="86" y2="25"/>
      </g>
      <line x1="18" y1="18" x2="92" y2="18"
            stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="18" y1="26" x2="92" y2="26"
            stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="18" y1="18" x2="18" y2="6"
            stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="18" y1="26" x2="18" y2="38"
            stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${_polarityMarker(92, 18, 'right', L, leftColor)}
      ${_polarityMarker(92, 26, 'right', R, rightColor)}
      ${warn ? _warningOverlay(100, 44) : ''}
    </svg>`
}

// Root-to-root indirect: two separate hybridized duplexes, diagonally offset
// (lower-left + upper-right), joined by a shared linker strand that traces
// the TOP of the left duplex, jogs up at the midpoint, and continues as the
// BOTTOM of the right duplex. The two overhang strands (left-duplex bottom
// and right-duplex top) terminate independently — they never directly
// hybridize, only through the shared linker. Roots are short stubs at each
// overhang's INNER end, flanking the linker step: left-duplex bottom goes
// DOWN, right-duplex top goes UP — both facing across the linker bridge.
function _ctRootToRootIndirectSvg(L = null, R = null, warn = false, leftColor = 'white', rightColor = 'white') {
  // LEFT overhang (LEFT BOTTOM): root stub at INNER (48, 32) DOWN.
  //   Free end at OUTER (6, 32). Body extends RIGHT → apex LEFT.
  // RIGHT overhang (RIGHT TOP):  root stub at INNER (52, 12) UP.
  //   Free end at OUTER (94, 12). Body extends LEFT → apex RIGHT.
  // Linker = shared strand: LEFT TOP at y=24 + step + RIGHT BOTTOM at y=20.
  //   LEFT terminus (6, 24) and RIGHT terminus (94, 20). For root-to-root the
  //   linker terminus polarity is OPPOSITE of the same-side switch.
  const lL = _oppPolarity(L)
  const lR = _oppPolarity(R)
  return `
    <svg viewBox="0 0 100 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="10" y1="25" x2="10" y2="31"/>
        <line x1="14" y1="25" x2="14" y2="31"/>
        <line x1="18" y1="25" x2="18" y2="31"/>
        <line x1="22" y1="25" x2="22" y2="31"/>
        <line x1="26" y1="25" x2="26" y2="31"/>
        <line x1="30" y1="25" x2="30" y2="31"/>
        <line x1="34" y1="25" x2="34" y2="31"/>
        <line x1="38" y1="25" x2="38" y2="31"/>
        <line x1="42" y1="25" x2="42" y2="31"/>
        <line x1="46" y1="25" x2="46" y2="31"/>
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="54" y1="13" x2="54" y2="19"/>
        <line x1="58" y1="13" x2="58" y2="19"/>
        <line x1="62" y1="13" x2="62" y2="19"/>
        <line x1="66" y1="13" x2="66" y2="19"/>
        <line x1="70" y1="13" x2="70" y2="19"/>
        <line x1="74" y1="13" x2="74" y2="19"/>
        <line x1="78" y1="13" x2="78" y2="19"/>
        <line x1="82" y1="13" x2="82" y2="19"/>
        <line x1="86" y1="13" x2="86" y2="19"/>
        <line x1="90" y1="13" x2="90" y2="19"/>
      </g>
      <line x1="6" y1="32" x2="48" y2="32"
            stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <path d="M 6 24 L 50 24 L 50 20 L 94 20"
            stroke="white" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="52" y1="12" x2="94" y2="12"
            stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="48" y1="32" x2="48" y2="40"
            stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="52" y1="12" x2="52" y2="4"
            stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${_polarityMarker(6,  32, 'left',  L,  leftColor)}
      ${_polarityMarker(94, 12, 'right', R,  rightColor)}
      ${_polarityMarker(6,  24, 'left',  lL, 'white')}
      ${_polarityMarker(94, 20, 'right', lR, 'white')}
      ${warn ? _warningOverlay(100, 44) : ''}
    </svg>`
}

// End-to-end indirect: same geometry as root-to-root-indirect (two diagonally
// offset duplexes joined by a shared linker that jogs up at the midpoint),
// but the root stubs are moved to the OUTER ends of the two overhang strands
// — far-left of the lower duplex's bottom strand going DOWN, far-right of the
// upper duplex's top strand going UP. The overhangs' free ends become the
// inner terminations near the linker bridge; both free ends face the same
// side of the linker, hence "end-to-end".
function _ctEndToEndIndirectSvg(L = null, R = null, warn = false, leftColor = 'white', rightColor = 'white') {
  // LEFT overhang (LEFT BOTTOM): root stub at OUTER (6, 32) DOWN.
  //   Free end at INNER (48, 32). Body extends LEFT → apex RIGHT.
  // RIGHT overhang (RIGHT TOP):  root stub at OUTER (94, 12) UP.
  //   Free end at INNER (52, 12). Body extends RIGHT → apex LEFT.
  // Linker terminus polarity = same as same-side switch (end-to-end pattern).
  return `
    <svg viewBox="0 0 100 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="10" y1="25" x2="10" y2="31"/>
        <line x1="14" y1="25" x2="14" y2="31"/>
        <line x1="18" y1="25" x2="18" y2="31"/>
        <line x1="22" y1="25" x2="22" y2="31"/>
        <line x1="26" y1="25" x2="26" y2="31"/>
        <line x1="30" y1="25" x2="30" y2="31"/>
        <line x1="34" y1="25" x2="34" y2="31"/>
        <line x1="38" y1="25" x2="38" y2="31"/>
        <line x1="42" y1="25" x2="42" y2="31"/>
        <line x1="46" y1="25" x2="46" y2="31"/>
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="54" y1="13" x2="54" y2="19"/>
        <line x1="58" y1="13" x2="58" y2="19"/>
        <line x1="62" y1="13" x2="62" y2="19"/>
        <line x1="66" y1="13" x2="66" y2="19"/>
        <line x1="70" y1="13" x2="70" y2="19"/>
        <line x1="74" y1="13" x2="74" y2="19"/>
        <line x1="78" y1="13" x2="78" y2="19"/>
        <line x1="82" y1="13" x2="82" y2="19"/>
        <line x1="86" y1="13" x2="86" y2="19"/>
        <line x1="90" y1="13" x2="90" y2="19"/>
      </g>
      <line x1="6" y1="32" x2="48" y2="32"
            stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <path d="M 6 24 L 50 24 L 50 20 L 94 20"
            stroke="white" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="52" y1="12" x2="94" y2="12"
            stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="6" y1="32" x2="6" y2="40"
            stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="94" y1="12" x2="94" y2="4"
            stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${_polarityMarker(48, 32, 'right', L, leftColor)}
      ${_polarityMarker(52, 12, 'left',  R, rightColor)}
      ${_polarityMarker(6,  24, 'left',  L, 'white')}
      ${_polarityMarker(94, 20, 'right', R, 'white')}
      ${warn ? _warningOverlay(100, 44) : ''}
    </svg>`
}

// Root-to-root ssDNA linker: two diagonally offset hybridized duplexes joined
// by a SINGLE-STRANDED flexible linker drawn as a smooth S-curve (vs. the
// rigid step used in the *-indirect icons). Root stubs at the inner ends of
// each overhang strand (left bottom going DOWN, right top going UP) — the
// same root-facing-the-linker convention used by Root-to-Root Indirect. The
// vertical gap between duplexes is wider here to give the curve room to read
// as a flexible ssDNA bridge rather than a small step.
function _ctRootToRootSsdnaLinkerSvg(L = null, R = null, warn = false, leftColor = 'white', rightColor = 'white') {
  // LEFT overhang (LEFT BOTTOM y=34): root at INNER (42, 34) DOWN.
  //   Free end at OUTER (6, 34). Body RIGHT → apex LEFT.
  // RIGHT overhang (RIGHT TOP y=10): root at INNER (58, 10) UP.
  //   Free end at OUTER (94, 10). Body LEFT → apex RIGHT.
  // Linker = LEFT TOP + S-curve + RIGHT BOTTOM. Termini at (6, 26) and
  // (94, 18). Root-to-root: linker terminus polarity = OPPOSITE of switch.
  const lL = _oppPolarity(L)
  const lR = _oppPolarity(R)
  return `
    <svg viewBox="0 0 100 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="10" y1="27" x2="10" y2="33"/>
        <line x1="14" y1="27" x2="14" y2="33"/>
        <line x1="18" y1="27" x2="18" y2="33"/>
        <line x1="22" y1="27" x2="22" y2="33"/>
        <line x1="26" y1="27" x2="26" y2="33"/>
        <line x1="30" y1="27" x2="30" y2="33"/>
        <line x1="34" y1="27" x2="34" y2="33"/>
        <line x1="38" y1="27" x2="38" y2="33"/>
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="62" y1="11" x2="62" y2="17"/>
        <line x1="66" y1="11" x2="66" y2="17"/>
        <line x1="70" y1="11" x2="70" y2="17"/>
        <line x1="74" y1="11" x2="74" y2="17"/>
        <line x1="78" y1="11" x2="78" y2="17"/>
        <line x1="82" y1="11" x2="82" y2="17"/>
        <line x1="86" y1="11" x2="86" y2="17"/>
        <line x1="90" y1="11" x2="90" y2="17"/>
      </g>
      <line x1="6" y1="26" x2="42" y2="26"
            stroke="white" stroke-width="2" stroke-linecap="round"/>
      <line x1="6" y1="34" x2="42" y2="34"
            stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="58" y1="10" x2="94" y2="10"
            stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="58" y1="18" x2="94" y2="18"
            stroke="white" stroke-width="2" stroke-linecap="round"/>
      <path d="M 42 26 C 50 26, 50 18, 58 18"
            stroke="white" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="42" y1="34" x2="42" y2="40"
            stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="58" y1="10" x2="58" y2="4"
            stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${_polarityMarker(6,  34, 'left',  L,  leftColor)}
      ${_polarityMarker(94, 10, 'right', R,  rightColor)}
      ${_polarityMarker(6,  26, 'left',  lL, 'white')}
      ${_polarityMarker(94, 18, 'right', lR, 'white')}
      ${warn ? _warningOverlay(100, 44) : ''}
    </svg>`
}

// End-to-end ssDNA linker: same geometry as Root-to-Root ssDNA Linker (two
// diagonally offset duplexes joined by a smooth ssDNA S-curve) but the root
// stubs are relocated to the OUTER ends — far-left of the lower duplex's
// bottom strand going DOWN, far-right of the upper duplex's top strand going
// UP. The overhangs' free ends become the inner terminations where the curve
// connects, putting both free ends on the same side of the linker bridge.
function _ctEndToEndSsdnaLinkerSvg(L = null, R = null, warn = false, leftColor = 'white', rightColor = 'white') {
  // LEFT overhang (LEFT BOTTOM y=34): root at OUTER (6, 34) DOWN.
  //   Free end at INNER (42, 34). Body LEFT → apex RIGHT.
  // RIGHT overhang (RIGHT TOP y=10): root at OUTER (94, 10) UP.
  //   Free end at INNER (58, 10). Body RIGHT → apex LEFT.
  // Linker termini at (6, 26) and (94, 18). End-to-end: linker terminus
  // polarity = SAME as switch.
  return `
    <svg viewBox="0 0 100 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="10" y1="27" x2="10" y2="33"/>
        <line x1="14" y1="27" x2="14" y2="33"/>
        <line x1="18" y1="27" x2="18" y2="33"/>
        <line x1="22" y1="27" x2="22" y2="33"/>
        <line x1="26" y1="27" x2="26" y2="33"/>
        <line x1="30" y1="27" x2="30" y2="33"/>
        <line x1="34" y1="27" x2="34" y2="33"/>
        <line x1="38" y1="27" x2="38" y2="33"/>
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="62" y1="11" x2="62" y2="17"/>
        <line x1="66" y1="11" x2="66" y2="17"/>
        <line x1="70" y1="11" x2="70" y2="17"/>
        <line x1="74" y1="11" x2="74" y2="17"/>
        <line x1="78" y1="11" x2="78" y2="17"/>
        <line x1="82" y1="11" x2="82" y2="17"/>
        <line x1="86" y1="11" x2="86" y2="17"/>
        <line x1="90" y1="11" x2="90" y2="17"/>
      </g>
      <line x1="6" y1="26" x2="42" y2="26"
            stroke="white" stroke-width="2" stroke-linecap="round"/>
      <line x1="6" y1="34" x2="42" y2="34"
            stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="58" y1="10" x2="94" y2="10"
            stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="58" y1="18" x2="94" y2="18"
            stroke="white" stroke-width="2" stroke-linecap="round"/>
      <path d="M 42 26 C 50 26, 50 18, 58 18"
            stroke="white" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="6" y1="34" x2="6" y2="40"
            stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="94" y1="10" x2="94" y2="4"
            stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${_polarityMarker(42, 34, 'right', L, leftColor)}
      ${_polarityMarker(58, 10, 'left',  R, rightColor)}
      ${_polarityMarker(6,  26, 'left',  L, 'white')}
      ${_polarityMarker(94, 18, 'right', R, 'white')}
      ${warn ? _warningOverlay(100, 44) : ''}
    </svg>`
}

// Root-to-root dsDNA linker: two diagonally offset overhang duplexes connected
// by a slanted dsDNA linker. Backbones are continuous polylines that bend
// through the linker section — left horizontal segment (overhang duplex) →
// slanted segment (linker, rise -16 over run 32, ~30° slope) → right
// horizontal segment (overhang duplex). The linker has its own perpendicular
// base-pair hatching (slanted, perpendicular to the slanted backbones), so it
// reads as a distinct dsDNA molecule even though the strands are continuous
// across the joins. Root stubs at the OUTER corners (far-left bottom DOWN,
// far-right top UP) per the reference image.
function _ctRootToRootDsdnaLinkerSvg(L = null, R = null, warn = false, leftColor = 'white', rightColor = 'white') {
  // LEFT overhang (LEFT BOTTOM y=50): root at OUTER (4, 50) DOWN.
  //   Free end at INNER (32, 50). Body LEFT → apex RIGHT.
  // RIGHT overhang (RIGHT TOP y=10): root at OUTER (96, 10) UP.
  //   Free end at INNER (64, 10). Body RIGHT → apex LEFT.
  // RED LINKER STRAND: (4, 42) horizontal + tilted to (64, 26). Its LEFT
  //   terminus polarity = LEFT switch (antiparallel with overhang A in
  //   LEFT duplex, with the convention that the free end is at INNER for
  //   root-to-root dsDNA). RIGHT terminus = OPPOSITE(LEFT).
  // GREEN LINKER STRAND: (32, 34) tilted + horizontal to (96, 18). LEFT
  //   terminus = OPPOSITE(RIGHT). RIGHT terminus = RIGHT switch.
  const RED   = '#dc3545'
  const GREEN = '#27ae60'
  const redL  = L
  const redR  = _oppPolarity(L)
  const grnL  = _oppPolarity(R)
  const grnR  = R
  return `
    <svg viewBox="0 0 100 56" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="8"  y1="43" x2="8"  y2="49"/>
        <line x1="12" y1="43" x2="12" y2="49"/>
        <line x1="16" y1="43" x2="16" y2="49"/>
        <line x1="20" y1="43" x2="20" y2="49"/>
        <line x1="24" y1="43" x2="24" y2="49"/>
        <line x1="28" y1="43" x2="28" y2="49"/>
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="36" y1="32" x2="39.2" y2="38.4"/>
        <line x1="40" y1="30" x2="43.2" y2="36.4"/>
        <line x1="44" y1="28" x2="47.2" y2="34.4"/>
        <line x1="48" y1="26" x2="51.2" y2="32.4"/>
        <line x1="52" y1="24" x2="55.2" y2="30.4"/>
        <line x1="56" y1="22" x2="59.2" y2="28.4"/>
        <line x1="60" y1="20" x2="63.2" y2="26.4"/>
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="68" y1="11" x2="68" y2="17"/>
        <line x1="72" y1="11" x2="72" y2="17"/>
        <line x1="76" y1="11" x2="76" y2="17"/>
        <line x1="80" y1="11" x2="80" y2="17"/>
        <line x1="84" y1="11" x2="84" y2="17"/>
        <line x1="88" y1="11" x2="88" y2="17"/>
        <line x1="92" y1="11" x2="92" y2="17"/>
      </g>
      <line x1="4" y1="50" x2="32" y2="50" stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="64" y1="10" x2="96" y2="10" stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <path d="M 4 42 L 32 42 L 64 26"
            stroke="${RED}" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M 32 34 L 64 18 L 96 18"
            stroke="${GREEN}" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="4"  y1="50" x2="4"  y2="56" stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="96" y1="10" x2="96" y2="4"  stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${_polarityMarker(32, 50, 'right', L,    leftColor)}
      ${_polarityMarker(64, 10, 'left',  R,    rightColor)}
      ${_polarityMarker(4,  42, 'left',  redL, RED)}
      ${_polarityMarker(64, 26, [ 32, -16], redR, RED)}
      ${_polarityMarker(32, 34, [-32,  16], grnL, GREEN)}
      ${_polarityMarker(96, 18, 'right', grnR, GREEN)}
      ${warn ? _warningOverlay(100, 56) : ''}
    </svg>`
}

// End-to-end dsDNA linker: same slanted-linker geometry as Root-to-Root dsDNA
// Linker, but root stubs at the INNER ends — flush with each overhang's inner
// terminus (x=32 for LEFT BOTTOM's right end, x=64 for RIGHT TOP's left end).
// Mirrors the root-to-root / end-to-end pair convention for the dsDNA-linker
// family.
function _ctEndToEndDsdnaLinkerSvg(L = null, R = null, warn = false, leftColor = 'white', rightColor = 'white') {
  // LEFT overhang (LEFT BOTTOM y=50): root at INNER (32, 50) DOWN, flush.
  //   Free end at OUTER (4, 50). Body RIGHT → apex LEFT.
  // RIGHT overhang (RIGHT TOP y=10): root at INNER (64, 10) UP, flush.
  //   Free end at OUTER (96, 10). Body LEFT → apex RIGHT.
  // For end-to-end dsDNA: free end at OUTER, root at INNER. Antiparallel
  // pairing in each duplex gives:
  //   RED LEFT terminus (4, 42) = OPPOSITE(L). RED RIGHT (64, 26) = L.
  //   GREEN LEFT (32, 34) = R. GREEN RIGHT (96, 18) = OPPOSITE(R).
  const RED   = '#dc3545'
  const GREEN = '#27ae60'
  const redL  = _oppPolarity(L)
  const redR  = L
  const grnL  = R
  const grnR  = _oppPolarity(R)
  return `
    <svg viewBox="0 0 100 56" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="8"  y1="43" x2="8"  y2="49"/>
        <line x1="12" y1="43" x2="12" y2="49"/>
        <line x1="16" y1="43" x2="16" y2="49"/>
        <line x1="20" y1="43" x2="20" y2="49"/>
        <line x1="24" y1="43" x2="24" y2="49"/>
        <line x1="28" y1="43" x2="28" y2="49"/>
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="36" y1="32" x2="39.2" y2="38.4"/>
        <line x1="40" y1="30" x2="43.2" y2="36.4"/>
        <line x1="44" y1="28" x2="47.2" y2="34.4"/>
        <line x1="48" y1="26" x2="51.2" y2="32.4"/>
        <line x1="52" y1="24" x2="55.2" y2="30.4"/>
        <line x1="56" y1="22" x2="59.2" y2="28.4"/>
        <line x1="60" y1="20" x2="63.2" y2="26.4"/>
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="68" y1="11" x2="68" y2="17"/>
        <line x1="72" y1="11" x2="72" y2="17"/>
        <line x1="76" y1="11" x2="76" y2="17"/>
        <line x1="80" y1="11" x2="80" y2="17"/>
        <line x1="84" y1="11" x2="84" y2="17"/>
        <line x1="88" y1="11" x2="88" y2="17"/>
        <line x1="92" y1="11" x2="92" y2="17"/>
      </g>
      <line x1="4" y1="50" x2="32" y2="50" stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="64" y1="10" x2="96" y2="10" stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <path d="M 4 42 L 32 42 L 64 26"
            stroke="${RED}" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M 32 34 L 64 18 L 96 18"
            stroke="${GREEN}" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="32" y1="50" x2="32" y2="56" stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="64" y1="10" x2="64" y2="4"  stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${_polarityMarker(4,  50, 'left',  L,    leftColor)}
      ${_polarityMarker(96, 10, 'right', R,    rightColor)}
      ${_polarityMarker(4,  42, 'left',  redL, RED)}
      ${_polarityMarker(64, 26, [ 32, -16], redR, RED)}
      ${_polarityMarker(32, 34, [-32,  16], grnL, GREEN)}
      ${_polarityMarker(96, 18, 'right', grnR, GREEN)}
      ${warn ? _warningOverlay(100, 56) : ''}
    </svg>`
}

// Mixed-attach ssDNA linker icon. Same diagonal two-duplex geometry as the
// same-attach ssDNA variants, but each side independently picks whether the
// root stub sits at INNER (root attach) or OUTER (free-end attach), with the
// free-end polarity marker placed at the opposite end. The linker terminus
// polarity at each side mirrors its attach: free-end → polarity = switch,
// root → polarity = OPPOSITE(switch).
function _ctMixedSsdnaLinkerSvg(leftIsRoot, rightIsRoot, L = null, R = null,
                                warn = false, leftColor = 'white', rightColor = 'white') {
  // LEFT BOTTOM y=34 strand body spans x=6..42; RIGHT TOP y=10 strand body
  // spans x=58..94. Bridge S-curve always joins INNER corners (42,26) ↔ (58,18).
  const leftStubX  = leftIsRoot  ? 42 : 6   // root stub at INNER (root) or OUTER (free)
  const rightStubX = rightIsRoot ? 58 : 94
  const leftMarkX  = leftIsRoot  ? 6  : 42  // free-end marker on the opposite side
  const rightMarkX = rightIsRoot ? 94 : 58
  const leftMarkDir  = leftIsRoot  ? 'left'  : 'right'
  const rightMarkDir = rightIsRoot ? 'right' : 'left'
  const lL = leftIsRoot  ? _oppPolarity(L) : L
  const lR = rightIsRoot ? _oppPolarity(R) : R
  return `
    <svg viewBox="0 0 100 44" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="10" y1="27" x2="10" y2="33"/>
        <line x1="14" y1="27" x2="14" y2="33"/>
        <line x1="18" y1="27" x2="18" y2="33"/>
        <line x1="22" y1="27" x2="22" y2="33"/>
        <line x1="26" y1="27" x2="26" y2="33"/>
        <line x1="30" y1="27" x2="30" y2="33"/>
        <line x1="34" y1="27" x2="34" y2="33"/>
        <line x1="38" y1="27" x2="38" y2="33"/>
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="62" y1="11" x2="62" y2="17"/>
        <line x1="66" y1="11" x2="66" y2="17"/>
        <line x1="70" y1="11" x2="70" y2="17"/>
        <line x1="74" y1="11" x2="74" y2="17"/>
        <line x1="78" y1="11" x2="78" y2="17"/>
        <line x1="82" y1="11" x2="82" y2="17"/>
        <line x1="86" y1="11" x2="86" y2="17"/>
        <line x1="90" y1="11" x2="90" y2="17"/>
      </g>
      <line x1="6" y1="26" x2="42" y2="26"
            stroke="white" stroke-width="2" stroke-linecap="round"/>
      <line x1="6" y1="34" x2="42" y2="34"
            stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="58" y1="10" x2="94" y2="10"
            stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="58" y1="18" x2="94" y2="18"
            stroke="white" stroke-width="2" stroke-linecap="round"/>
      <path d="M 42 26 C 50 26, 50 18, 58 18"
            stroke="white" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="${leftStubX}"  y1="34" x2="${leftStubX}"  y2="40"
            stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="${rightStubX}" y1="10" x2="${rightStubX}" y2="4"
            stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${_polarityMarker(leftMarkX,  34, leftMarkDir,  L,  leftColor)}
      ${_polarityMarker(rightMarkX, 10, rightMarkDir, R,  rightColor)}
      ${_polarityMarker(6,  26, 'left',  lL, 'white')}
      ${_polarityMarker(94, 18, 'right', lR, 'white')}
      ${warn ? _warningOverlay(100, 44) : ''}
    </svg>`
}

// Mixed-attach dsDNA linker icon. Same slanted-linker geometry as the
// same-attach dsDNA variants. Per the established dsDNA stub convention
// (INVERTED from ssDNA): root attach → stub at OUTER; free-end attach →
// stub at INNER. Linker strand terminus polarities follow:
//   root  side : near-terminus = switch; far-terminus = OPPOSITE(switch)
//   free  side : near-terminus = OPPOSITE(switch); far-terminus = switch
function _ctMixedDsdnaLinkerSvg(leftIsRoot, rightIsRoot, L = null, R = null,
                                warn = false, leftColor = 'white', rightColor = 'white') {
  const RED   = '#dc3545'
  const GREEN = '#27ae60'
  // Stub positions per the inverted dsDNA convention.
  const leftStubX  = leftIsRoot  ? 4  : 32  // root → OUTER; free → INNER
  const rightStubX = rightIsRoot ? 96 : 64
  const leftMarkX  = leftIsRoot  ? 32 : 4   // free-end marker at the opposite end
  const rightMarkX = rightIsRoot ? 64 : 96
  const leftMarkDir  = leftIsRoot  ? 'right' : 'left'
  const rightMarkDir = rightIsRoot ? 'left'  : 'right'
  const redL = leftIsRoot  ? L : _oppPolarity(L)
  const redR = leftIsRoot  ? _oppPolarity(L) : L
  const grnL = rightIsRoot ? _oppPolarity(R) : R
  const grnR = rightIsRoot ? R : _oppPolarity(R)
  return `
    <svg viewBox="0 0 100 56" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="8"  y1="43" x2="8"  y2="49"/>
        <line x1="12" y1="43" x2="12" y2="49"/>
        <line x1="16" y1="43" x2="16" y2="49"/>
        <line x1="20" y1="43" x2="20" y2="49"/>
        <line x1="24" y1="43" x2="24" y2="49"/>
        <line x1="28" y1="43" x2="28" y2="49"/>
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="36" y1="32" x2="39.2" y2="38.4"/>
        <line x1="40" y1="30" x2="43.2" y2="36.4"/>
        <line x1="44" y1="28" x2="47.2" y2="34.4"/>
        <line x1="48" y1="26" x2="51.2" y2="32.4"/>
        <line x1="52" y1="24" x2="55.2" y2="30.4"/>
        <line x1="56" y1="22" x2="59.2" y2="28.4"/>
        <line x1="60" y1="20" x2="63.2" y2="26.4"/>
      </g>
      <g stroke="white" stroke-width="0.9" stroke-linecap="round">
        <line x1="68" y1="11" x2="68" y2="17"/>
        <line x1="72" y1="11" x2="72" y2="17"/>
        <line x1="76" y1="11" x2="76" y2="17"/>
        <line x1="80" y1="11" x2="80" y2="17"/>
        <line x1="84" y1="11" x2="84" y2="17"/>
        <line x1="88" y1="11" x2="88" y2="17"/>
        <line x1="92" y1="11" x2="92" y2="17"/>
      </g>
      <line x1="4" y1="50" x2="32" y2="50" stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="64" y1="10" x2="96" y2="10" stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      <path d="M 4 42 L 32 42 L 64 26"
            stroke="${RED}" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M 32 34 L 64 18 L 96 18"
            stroke="${GREEN}" stroke-width="2" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <line x1="${leftStubX}"  y1="50" x2="${leftStubX}"  y2="56" stroke="${leftColor}" stroke-width="2" stroke-linecap="round"/>
      <line x1="${rightStubX}" y1="10" x2="${rightStubX}" y2="4"  stroke="${rightColor}" stroke-width="2" stroke-linecap="round"/>
      ${_polarityMarker(leftMarkX,  50, leftMarkDir,  L,    leftColor)}
      ${_polarityMarker(rightMarkX, 10, rightMarkDir, R,    rightColor)}
      ${_polarityMarker(4,  42, 'left',  redL, RED)}
      ${_polarityMarker(64, 26, [ 32, -16], redR, RED)}
      ${_polarityMarker(32, 34, [-32,  16], grnL, GREEN)}
      ${_polarityMarker(96, 18, 'right', grnR, GREEN)}
      ${warn ? _warningOverlay(100, 56) : ''}
    </svg>`
}

/**
 * Open the manager. If `preselect` is given, it's an array of up to 2
 * overhang ids to drop into sides A and B (in order). When omitted, the
 * popup pulls the current overhang selection from the store
 * (`multiSelectedOverhangIds`, then any single selectedObject overhang).
 */
export function open(preselect) {
  if (!_modal) return
  const state = _store?.getState()
  if (!state?.currentDesign) {
    alert('No design loaded.')
    return
  }
  const ids = _resolvePreselect(state, preselect)
  // Seed the Connection Types tab from the caller-supplied / current selection.
  _ctSelectedA = ids[0] ?? null
  _ctSelectedB = ids[1] ?? null
  // Fresh modal open → no linker row is selected; bridge inputs stay empty
  // and disabled until the user clicks a row (or creates one).
  _ctSelectedConnId = null
  _renderCtLists()
  _renderTable()
  _refreshCtSeqRows()
  _refreshCtBridgeBoxFromSelection()
  _modal.style.display = 'flex'
  // Apply persisted active tab (default 'connection-types'). Domain Designer
  // is lazily inited inside `_switchTab` on first activation so its 3D context
  // isn't created until the user clicks the tab.
  _switchTab(_activeTab, { preselect: ids })
}

function _resolvePreselect(state, explicit) {
  const all = state.currentDesign?.overhangs ?? []
  const valid = (id) => id && all.some(o => o.id === id)
  // Caller-supplied ids win.
  if (Array.isArray(explicit) && explicit.length > 0) {
    return explicit.filter(valid).slice(0, 2)
  }
  // Multi-overhang selection (lasso / ctrl+click) — first 2.
  const multi = (state.multiSelectedOverhangIds ?? []).filter(valid).slice(0, 2)
  if (multi.length > 0) return multi
  // Single-selected overhang via domain-mode click.
  const single = state.selectedObject?.data?.overhang_id
  return valid(single) ? [single] : []
}

export function close() {
  if (_modal) _modal.style.display = 'none'
  // Clear the modal-active flag — design_renderer now flushes its single
  // deferred rebuild against the latest design + geometry.
  setDomainDesignerModalActive(false)
  // Tear down the Domain Designer panel + pathview so listeners detach.
  if (_ddInited) {
    try { _ddPanel?.close?.() } catch (err) { _debug('panel close threw', err) }
    try { _ddPathview?.destroy?.() } catch (err) { _debug('pathview destroy threw', err) }
    _ddPanel = _ddPathview = null
    _ddInited = false
  }
}

// ── Tab controller (Phase 3 overhang revamp) ──────────────────────────────────

function _switchTab(id, { preselect } = {}) {
  if (!_OHC_TABS.includes(id)) return
  const oldTab = _activeTab
  _activeTab = id
  try { localStorage.setItem(_OHC_TAB_STORAGE, id) } catch { /* ignore */ }

  // Update button visual state.
  const strip = _modal.querySelector('#ohc-tab-strip')
  if (strip) {
    for (const btn of strip.querySelectorAll('.ohc-tab')) {
      const active = btn.dataset.tab === id
      btn.classList.toggle('active', active)
      // Inline-style swap matches the dark Primer palette in index.html.
      btn.style.background = active ? '#0d1117' : '#161b22'
      btn.style.color      = active ? '#c9d1d9' : '#8b949e'
    }
  }

  // Toggle panes via the `hidden` attribute (DOM contract).
  for (const tabId of _OHC_TABS) {
    const pane = document.getElementById(`tab-content-${tabId}`)
    if (pane) pane.hidden = (tabId !== id)
  }

  // Modal-content width swap.
  const newWidth = (id === 'domain-designer') ? '1000px' : '760px'
  if (_modalContent) _modalContent.style.width = newWidth
  _debug('tab activate', oldTab, '→', id, 'modal width →', newWidth)

  if (id === 'domain-designer') {
    // Set the modal-active flag so design_renderer defers main-scene rebuilds
    // until the user closes the popup (or switches back to Linker Generator).
    setDomainDesignerModalActive(true)
    // Defer panel/pathview init to the next macrotask so the modal visibly
    // switches tabs before the panel render runs.
    setTimeout(() => {
      const t0 = (typeof performance !== 'undefined') ? performance.now() : Date.now()
      _debug('lazy-init start')
      try {
        _ensureDomainDesignerInited()
        _ddPanel?.open?.(preselect)
      } catch (err) {
        _debug('lazy-init threw', err)
        console.error('[DD-tab] lazy-init failed', err)
      }
      const t1 = (typeof performance !== 'undefined') ? performance.now() : Date.now()
      _debug('lazy-init done', (t1 - t0).toFixed(1), 'ms')
    }, 0)
  } else {
    // Clear the flag and flush any deferred rebuild as the user leaves DD.
    setDomainDesignerModalActive(false)
    if (_ddPanel) _ddPanel.close()
  }
}

function _ensureDomainDesignerInited() {
  if (_ddInited) return
  const pathCanvas = document.getElementById('dd-pathview-canvas')
  const pathWrap   = document.getElementById('dd-pathview-wrap')
  const resetBtn   = document.getElementById('dd-pathview-reset')
  if (!pathCanvas) {
    _debug('init aborted — #dd-pathview-canvas missing from DOM')
    return
  }

  const ddApi = {
    patchSubDomain,
    recomputeSubDomainAnnotations,
    generateSubDomainRandom,
    splitSubDomain,
    mergeSubDomains,
    patchTmSettings,
    createOverhangBinding,
    patchOverhangBinding,
    deleteOverhangBinding,
  }

  _ddPathview = initOverhangPathview(pathCanvas, {
    store: _store,
    wrapEl: pathWrap,
    onSelectSubDomain: (sdId, _ovhgId) => {
      // PERSPECTIVE LOCK: only the listing changes the perspective anchor
      // (`selectedOverhangId`). Pathview clicks update ONLY `selectedSubDomainId`
      // so the user can edit the partner overhang's sub-domain without
      // flipping the multi-grid stack. The annotations panel resolves the
      // owning overhang by walking design.overhangs.
      setDomainDesignerSelection({ subDomainId: sdId })
    },
    onSplit: (ovhgId, { sub_domain_id, split_at_offset }) => {
      // ovhgId is the OWNING overhang from the hit-test, NOT necessarily the
      // listing-selected one. Routes the split to the correct overhang.
      if (!ovhgId) return
      _debug('split', ovhgId, sub_domain_id, '@', split_at_offset)
      splitSubDomain(ovhgId, { sub_domain_id, split_at_offset })
    },
    onResizeFreeEnd: (ovhgId, { end, delta_bp }) => {
      if (!ovhgId) return
      _debug('resize-free-end', ovhgId, end, delta_bp)
      resizeOverhangFreeEnd(ovhgId, { end, deltaBp: delta_bp })
        .catch(err => console.warn('[DD-tab] resize failed', err))
    },
    onResizeLinker: (connId, lengthDelta) => {
      // Bridge length resize. Read the current length and PATCH with the
      // delta applied. Backend keeps unit unchanged AND preserves the
      // existing complement-domain bp ranges across the regeneration.
      if (!connId) return
      const conn = _store.getState().currentDesign?.overhang_connections
        ?.find(c => c.id === connId)
      if (!conn) return
      const newLen = Math.max(1, (conn.length_value ?? 0) + lengthDelta)
      _debug('resize-linker', connId, 'lenΔ', lengthDelta, 'newLen', newLen)
      api.patchOverhangConnection(connId, { length_value: newLen })
        .catch(err => console.warn('[DD-tab] linker resize failed', err))
    },
    onResizeBinding: ({ strand_id, helix_id, end, delta_bp }) => {
      // Resize the linker strand's binding-domain 3' end by hitting the
      // generic strand-end-resize endpoint. The backend's persistence in
      // patch_overhang_connection ensures the resized binding survives any
      // subsequent linker bridge resize.
      _debug('resize-binding', strand_id, helix_id, end, delta_bp)
      api.resizeStrandEnds([{ strand_id, helix_id, end, delta_bp }])
        .catch(err => console.warn('[DD-tab] binding resize failed', err))
    },
  })

  if (resetBtn && _ddPathview?.resetView) {
    resetBtn.addEventListener('click', () => {
      _debug('reset view click')
      _ddPathview.resetView()
    })
  }
  _ddPanel = initDomainDesignerPanel(_modalContent, {
    store: _store,
    api: ddApi,
    pathview: _ddPathview,
  })
  _ddInited = true
}

// ── Internal ──────────────────────────────────────────────────────────────────

function _design() {
  return _store?.getState()?.currentDesign
}

function _overhangs() {
  // Defensive filter: hide overhangs whose backing strand has been deleted
  // but whose OverhangSpec wasn't cascaded out. Stops the user from picking
  // ghost overhangs in the CT tab side lists, the linker create flow, and
  // the binding create flow (where the resolved sub-domains would also be
  // orphaned).
  const design = _design()
  if (!design) return []
  const liveStrandIds = new Set((design.strands ?? []).map(s => s.id))
  return (design.overhangs ?? [])
    .filter(o => !o.strand_id || liveStrandIds.has(o.strand_id))
}

function _connections() {
  return _design()?.overhang_connections ?? []
}

function _bindings() {
  return _design()?.overhang_bindings ?? []
}

/** Return any OverhangBinding rows whose A or B overhang_id involves both
 * `aId` and `bId` (in either order). Used by the CT tab to decide whether
 * to draw a "create binding" button vs. show the existing pair's state. */
function _bindingsForOverhangPair(aId, bId) {
  return _bindings().filter(b =>
    (b.overhang_a_id === aId && b.overhang_b_id === bId) ||
    (b.overhang_a_id === bId && b.overhang_b_id === aId),
  )
}

/** Find the binding(s) referencing an overhang id (used by main-app sidebar
 * + per-row buttons in the CT tab). */
function _bindingsForOverhang(ovhgId) {
  return _bindings().filter(b =>
    b.overhang_a_id === ovhgId || b.overhang_b_id === ovhgId,
  )
}

/** Resolve the sub-domain id at an attach end, mirroring the backend
 * `_sub_domain_at_attach` helper. */
function _subDomainAtAttach(ovhgId, attach /* 'root' | 'free_end' */) {
  const ovhg = _overhangs().find(o => o.id === ovhgId)
  if (!ovhg || !ovhg.sub_domains?.length) return null
  const sorted = [...ovhg.sub_domains].sort(
    (a, b) => (a.start_bp_offset ?? 0) - (b.start_bp_offset ?? 0),
  )
  return attach === 'root' ? sorted[0].id : sorted[sorted.length - 1].id
}

/** Parse 5p/3p suffix from id. */
function _endTag(ovhgId) {
  if (ovhgId.endsWith('_5p')) return "5'"
  if (ovhgId.endsWith('_3p')) return "3'"
  return ''
}

function _displayName(ovhg) {
  return ovhg.label || ovhg.id
}

// Render the linkers + direct-binding table into the Connection Types tab body.
// Rows are a UNION of OverhangConnections (ss/ds linkers) and OverhangBindings
// (direct WC pairs). Both row kinds share Name | Type | Length | Overhangs |
// Sequence | Bound | Delete columns; the Bound checkbox is only interactive
// on binding rows. Linker rows render '—' in the Bound cell.
function _renderTable() {
  const tbody = document.getElementById('ct-table-body')
  if (!tbody) return
  tbody.innerHTML = ''
  const conns = _connections()
  const bindings = _bindings()
  if (conns.length === 0 && bindings.length === 0) {
    const tr = document.createElement('tr')
    tr.innerHTML = '<td colspan="7" style="padding:10px;color:#6e7681;text-align:center;font-size:11px">No linkers or direct bindings defined.</td>'
    tbody.appendChild(tr)
    return
  }

  // Build a label lookup for overhang ids → display names
  const labelById = new Map(_overhangs().map(o => [o.id, _displayName(o)]))

  // Display L1, L2, ... + B1, B2, ... in name order. Linkers and bindings
  // share the table; the row factory keys off `c.linker_type` vs `c.bound`
  // (= "is binding") so callers can mix freely.
  const allRows = [
    ...conns.map(c => ({ kind: 'conn', entity: c })),
    ...bindings.map(b => ({ kind: 'binding', entity: b })),
  ]
  allRows.sort((a, b) => (a.entity.name ?? '').localeCompare(
    b.entity.name ?? '', undefined, { numeric: true },
  ))

  for (const row of allRows) {
    const isConn = row.kind === 'conn'
    const c = row.entity
    const tr = document.createElement('tr')
    if (isConn) {
      tr.dataset.connId = c.id
      tr.className = 'ohc-link-row' + (c.id === _ctSelectedConnId ? ' ohc-link-row-selected' : '')
    } else {
      tr.dataset.bindingId = c.id
    }
    tr.style.cursor = 'pointer'
    if (isConn) {
      tr.addEventListener('click', () => _onLinkRowClick(c))
    }

    // Name — editable.
    const nameTd = document.createElement('td')
    nameTd.addEventListener('click', e => e.stopPropagation())
    _attachEditableText(nameTd, c.name ?? '', async (v) => {
      const newName = v.trim()
      if (!newName || newName === c.name) return
      try {
        if (isConn) await api.patchOverhangConnection(c.id, { name: newName })
        else        await patchOverhangBinding(c.id, { name: newName })
        _renderTable()
      } catch (err) { alert(err?.message || String(err)); _renderTable() }
    })

    // Type — read-only
    const typeTd = document.createElement('td')
    typeTd.textContent = isConn
      ? (c.linker_type === 'ds' ? 'dsDNA' : 'ssDNA')
      : 'Binding'

    // Length — editable for conn; '—' read-only for binding.
    const lenTd = document.createElement('td')
    lenTd.addEventListener('click', e => e.stopPropagation())
    if (isConn) {
      _attachEditableLength(lenTd, c.length_value, c.length_unit, async (newVal, newUnit) => {
        const patch = {}
        if (newVal !== c.length_value)  patch.length_value = newVal
        if (newUnit !== c.length_unit)  patch.length_unit  = newUnit
        if (!Object.keys(patch).length) return
        try { await api.patchOverhangConnection(c.id, patch); _renderTable() }
        catch (err) { alert(err?.message || String(err)); _renderTable() }
      })
    } else {
      lenTd.textContent = '—'
      lenTd.style.color = '#6e7681'
    }

    // Overhangs — read-only
    const ohTd = document.createElement('td')
    const aLabel = labelById.get(c.overhang_a_id) ?? c.overhang_a_id
    const bLabel = labelById.get(c.overhang_b_id) ?? c.overhang_b_id
    if (isConn) {
      ohTd.textContent = `${aLabel} (${_attachLabel(c.overhang_a_attach)}) ↔ ${bLabel} (${_attachLabel(c.overhang_b_attach)})`
    } else {
      ohTd.textContent = `${aLabel} ↔ ${bLabel}`
    }

    // Sequence cell. Linker → colored bridge+complement spans. Binding →
    // sub-domain sequence and its RC mirror (one row each).
    const seqTd = document.createElement('td')
    seqTd.className = 'ct-link-seq-cell'
    seqTd.style.fontFamily = 'monospace'
    seqTd.style.fontSize   = '11px'
    if (isConn) {
      _renderLinkerSequenceCell(seqTd, c)
    } else {
      _renderBindingSequenceCell(seqTd, c)
    }

    // Bound checkbox — interactive on binding rows; '—' on linker rows.
    const boundTd = document.createElement('td')
    boundTd.style.textAlign = 'center'
    boundTd.addEventListener('click', e => e.stopPropagation())
    if (isConn) {
      boundTd.textContent = '—'
      boundTd.style.color = '#6e7681'
    } else {
      const cb = document.createElement('input')
      cb.type = 'checkbox'
      cb.checked = !!c.bound
      cb.dataset.test = 'ct-binding-bound-cb'
      cb.dataset.bindingId = c.id
      cb.addEventListener('change', async (ev) => {
        const next = ev.target.checked
        cb.disabled = true
        try {
          const result = await patchOverhangBinding(c.id, { bound: next })
          if (result === null || result === undefined) {
            cb.checked = !next
            showToast?.('Could not change bound state — see console for details')
          }
        } catch (err) {
          cb.checked = !next
          showToast?.(err?.message || String(err))
        } finally {
          cb.disabled = false
        }
      })
      boundTd.appendChild(cb)
    }

    // Delete
    const delTd = document.createElement('td')
    const delBtn = document.createElement('button')
    delBtn.className = 'ohc-row-delete'
    delBtn.textContent = '×'
    delBtn.title = isConn ? 'Delete linker' : 'Delete binding'
    delBtn.addEventListener('click', async (e) => {
      e.stopPropagation()
      if (isConn) { _onDelete(c); return }
      if (!confirm(`Delete binding ${c.name ?? c.id.slice(0, 6)}?`)) return
      try { await deleteOverhangBinding(c.id) }
      catch (err) { showToast?.(err?.message || String(err)) }
    })
    delTd.appendChild(delBtn)

    tr.append(nameTd, typeTd, lenTd, ohTd, seqTd, boundTd, delTd)
    tbody.appendChild(tr)
  }
}

// Sequence cell for a binding row: render the two paired sub-domains'
// sequences, one per line (sub_domain_a on top, sub_domain_b on bottom).
// Reverse-complementarity is enforced server-side (POST /design/overhang-
// bindings 422s on non-WC), so the lines should always be antiparallel-RC
// of each other up to N-wildcards.
function _renderBindingSequenceCell(td, binding) {
  td.innerHTML = ''
  const design = _design()
  if (!design) return
  const sdLookup = new Map()
  for (const o of (design.overhangs ?? [])) {
    for (const sd of (o.sub_domains ?? [])) sdLookup.set(sd.id, { ovhg: o, sd })
  }
  const a = sdLookup.get(binding.sub_domain_a_id)
  const b = sdLookup.get(binding.sub_domain_b_id)
  const wrap = document.createElement('div')
  wrap.style.cssText = 'display:flex;flex-direction:column;gap:2px;align-items:flex-start'
  const lineA = document.createElement('div')
  lineA.style.cssText = 'white-space:nowrap;letter-spacing:0.04em;color:#39d0d8'
  lineA.textContent = _resolveSubDomainSeq(a?.ovhg, a?.sd) || '(empty)'
  const lineB = document.createElement('div')
  lineB.style.cssText = 'white-space:nowrap;letter-spacing:0.04em;color:#f06292'
  lineB.textContent = _resolveSubDomainSeq(b?.ovhg, b?.sd) || '(empty)'
  wrap.appendChild(lineA)
  wrap.appendChild(lineB)
  td.appendChild(wrap)
}

function _resolveSubDomainSeq(ovhg, sd) {
  if (!ovhg || !sd) return null
  if (sd.sequence_override) return sd.sequence_override.toUpperCase()
  if (!ovhg.sequence) return null
  const start = sd.start_bp_offset ?? 0
  const end = start + (sd.length_bp ?? 0)
  return ovhg.sequence.slice(start, end).toUpperCase()
}

// ── Linker sequence cell ─────────────────────────────────────────────────────
// Per-domain colored spans for each linker strand belonging to one connection
// row, plus a "Gen" button. The colors match the connection-type icon:
//   * complement portions use the neon LEFT/RIGHT color of the paired overhang
//     (cyan / magenta — same as the list-row highlight)
//   * bridge portions use the linker-strand color shown in the icon
//     (white for ss; red / green for the two ds halves)

const _LINKER_BRIDGE_COLOR = '#ffffff'
const _LINKER_DS_A_COLOR   = '#dc3545'   // red — matches `_makeDsLinkerMeshes`
const _LINKER_DS_B_COLOR   = '#27ae60'   // green

function _renderLinkerSequenceCell(td, conn) {
  td.innerHTML = ''
  const wrap = document.createElement('div')
  wrap.style.cssText = 'display:flex;flex-direction:column;gap:2px;align-items:flex-start'
  td.appendChild(wrap)

  for (const segs of _linkerStrandSegments(conn)) {
    const line = document.createElement('div')
    line.style.cssText = 'white-space:nowrap;letter-spacing:0.04em'
    line.dataset.strandId = segs.strandId
    for (const s of segs.segments) {
      const span = document.createElement('span')
      span.textContent = s.text
      span.style.color = s.color
      span.dataset.role = s.role  // 'complement' or 'bridge'
      line.appendChild(span)
    }
    wrap.appendChild(line)
  }
}

// Compute the colored span list for every linker strand of one connection.
// Returns: [{ strandId, segments: [{ text, color, role }, …] }, …]
//
// The composition is reconstructed every render from live design state, NOT
// from strand.sequence: complement portions are the RC of the bound
// overhang's current sequence (or N×L when the overhang isn't sequenced
// yet), and the bridge portion is `conn.bridge_sequence` (with RC on ds
// strand `__b`). This means the column reflects edits to the overhang
// sequences without any backend re-derivation step.
function _linkerStrandSegments(conn) {
  const design = _design()
  if (!design) return []
  const prefix = `__lnk__${conn.id}`
  const strands = (design.strands ?? [])
    .filter(s => s.id.startsWith(prefix))
    .sort((a, b) => a.id.localeCompare(b.id))   // __a < __b alphabetically
  const ovhgById = new Map((design.overhangs ?? []).map(o => [o.id, o]))
  const aSeq = ovhgById.get(conn.overhang_a_id)?.sequence ?? null
  const bSeq = ovhgById.get(conn.overhang_b_id)?.sequence ?? null
  const userBridge = (conn.bridge_sequence ?? '').toUpperCase()

  // Trim / pad a sequence to exactly `length` chars so the rendered cell
  // length always matches the domain span — even if the user typed a
  // longer / shorter bridge than the linker bp count.
  const pad = (seq, length) =>
    seq.length >= length ? seq.slice(0, length) : seq + 'N'.repeat(length - seq.length)

  const out = []
  for (const strand of strands) {
    const suffix = strand.id.slice(prefix.length + 2)  // 'a' | 'b' | 's'
    const bridgeColor = conn.linker_type === 'ds'
      ? (suffix === 'a' ? _LINKER_DS_A_COLOR : _LINKER_DS_B_COLOR)
      : _LINKER_BRIDGE_COLOR
    const thisBridge = conn.linker_type === 'ds' && suffix === 'b'
      ? _reverseComplement(userBridge)
      : userBridge
    const segments = []
    let complementsSeen = 0
    for (const dom of strand.domains ?? []) {
      const length = Math.max(0, Math.abs((dom.end_bp ?? 0) - (dom.start_bp ?? 0)) + 1)
      if (length === 0) continue
      const isBridge = (dom.helix_id ?? '').startsWith('__lnk__')
      if (isBridge) {
        const text = thisBridge ? pad(thisBridge, length) : 'N'.repeat(length)
        segments.push({ text, color: bridgeColor, role: 'bridge' })
      } else {
        const ohSide = suffix === 'a' ? 'A'
                     : suffix === 'b' ? 'B'
                     : (complementsSeen === 0 ? 'A' : 'B')
        const targetSeq = ohSide === 'A' ? aSeq : bSeq
        // The OH's `sequence` may be SHORTER than its strand-domain length
        // (sub-domain has `length_bp=10` but the user only typed 8 chars,
        // for example). Pad the missing 3' positions of the OH with N before
        // reverse-complementing — those N's land at the 5' end of the linker
        // complement, which is the antiparallel side of the unsequenced OH
        // bases. Slice the head if the OH is somehow longer than its domain.
        const ohSeq = (targetSeq ?? '').slice(0, length).padEnd(length, 'N')
        const text = _reverseComplement(ohSeq)
        segments.push({
          text,
          color: ohSide === 'A' ? _CT_LEFT_NEON : _CT_RIGHT_NEON,
          role: 'complement',
        })
        complementsSeen += 1
      }
    }
    out.push({ strandId: strand.id, segments })
  }
  return out
}

// Map an OverhangConnection back to a Connection Types tile id. Covers all
// four attach combos × {ss, ds}: same-attach maps to root-to-root or
// end-to-end families; mixed-attach maps to end-to-root / root-to-end.
function _ctVariantForConnection(conn) {
  if (!conn) return null
  const kind = conn.linker_type === 'ds' ? 'dsdna' : 'ssdna'
  const a = conn.overhang_a_attach
  const b = conn.overhang_b_attach
  let family
  if      (a === 'root'     && b === 'root')     family = 'root-to-root'
  else if (a === 'free_end' && b === 'free_end') family = 'end-to-end'
  else if (a === 'free_end' && b === 'root')     family = 'end-to-root'
  else if (a === 'root'     && b === 'free_end') family = 'root-to-end'
  else return null
  return `${family}-${kind}-linker`
}

// Click handler for a row in the linker table — populate the Connection
// Types selector with this linker's overhangs + matching variant tile, then
// scroll each overhang list so the highlighted row is in view.
function _onLinkRowClick(conn) {
  _ctSelectedConnId = conn?.id ?? null
  _ctSelectedA = conn.overhang_a_id ?? null
  _ctSelectedB = conn.overhang_b_id ?? null
  const variantId = _ctVariantForConnection(conn)
  if (variantId && _CT_VARIANTS.some(v => v.id === variantId)) {
    _ctSelectedId = variantId
    try { localStorage.setItem(_CT_STORAGE, variantId) } catch { /* ignore */ }
  }
  _refreshConnectionTypesUI()
  _refreshCtPopoverTiles()
  _scrollCtListToSelection()
}

// Bridge sequence stored on the connection itself (round-tripped into the
// bridge input on row click). `null` / empty means "no bridge set yet".
function _bridgeSeqOfConn(conn) {
  return conn?.bridge_sequence ?? null
}

// Scroll each overhang list so the currently-selected row is visible.
// Uses `scrollIntoView({ block: 'nearest' })` so already-visible rows stay
// in place; off-screen rows jump into view without yanking the page.
function _scrollCtListToSelection() {
  for (const [listId, ovhgId] of [['ct-list-a', _ctSelectedA], ['ct-list-b', _ctSelectedB]]) {
    if (!ovhgId) continue
    const list = document.getElementById(listId)
    if (!list) continue
    const row = list.querySelector(`.ohc-list-row[data-ovhg-id="${CSS.escape(ovhgId)}"]`)
    row?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }
}

function _attachLabel(attach) {
  return attach === 'free_end' ? 'free' : 'root'
}

function _fmtLength(v) {
  return Number.isInteger(v) ? String(v) : String(v)
}

// ── Inline-editing helpers ────────────────────────────────────────────────────

function _attachEditableText(td, value, onCommit) {
  td.textContent = value || '—'
  td.style.cursor = 'text'
  td.title = 'Click to edit'
  td.addEventListener('click', () => _swapToTextInput(td, value, onCommit))
}

function _swapToTextInput(td, value, onCommit) {
  td.textContent = ''
  const input = document.createElement('input')
  input.type = 'text'
  input.value = value
  input.style.cssText = 'background:#0d1117;border:1px solid #1f6feb;border-radius:3px;color:#fff;font:inherit;padding:3px 4px;width:80px;outline:none'
  td.appendChild(input)
  input.focus()
  input.select()
  let done = false
  const finish = (commit) => {
    if (done) return
    done = true
    if (commit) onCommit(input.value)
    else td.textContent = value || '—'
  }
  input.addEventListener('blur',    () => finish(true))
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter')  { e.preventDefault(); input.blur() }
    if (e.key === 'Escape') { e.preventDefault(); finish(false) }
  })
}

function _attachEditableLength(td, value, unit, onCommit) {
  td.textContent = `${_fmtLength(value)} ${unit}`
  td.style.cursor = 'text'
  td.title = 'Click to edit length'
  td.addEventListener('click', () => _swapToLengthInputs(td, value, unit, onCommit))
}

function _swapToLengthInputs(td, value, unit, onCommit) {
  td.textContent = ''
  const wrap = document.createElement('span')
  wrap.style.cssText = 'display:inline-flex;gap:3px;align-items:center'
  const numInput = document.createElement('input')
  numInput.type = 'number'; numInput.min = '0'; numInput.step = 'any'
  numInput.value = value
  numInput.style.cssText = 'background:#0d1117;border:1px solid #1f6feb;border-radius:3px;color:#fff;font:inherit;padding:3px 4px;width:54px;outline:none'
  const unitSel = document.createElement('select')
  unitSel.innerHTML = '<option value="bp">bp</option><option value="nm">nm</option>'
  unitSel.value = unit
  unitSel.style.cssText = 'background:#0d1117;border:1px solid #30363d;border-radius:3px;color:#c9d1d9;font:inherit;padding:3px 2px;outline:none'
  wrap.append(numInput, unitSel)
  td.appendChild(wrap)
  numInput.focus(); numInput.select()
  let done = false
  const finish = (commit) => {
    if (done) return
    done = true
    if (commit) {
      const v = parseFloat(numInput.value)
      if (Number.isFinite(v) && v > 0) onCommit(v, unitSel.value)
      else td.textContent = `${_fmtLength(value)} ${unit}`
    } else {
      td.textContent = `${_fmtLength(value)} ${unit}`
    }
  }
  // Commit when focus leaves the wrapper entirely.
  wrap.addEventListener('focusout', (e) => {
    if (!wrap.contains(e.relatedTarget)) finish(true)
  })
  numInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter')  { e.preventDefault(); finish(true) }
    if (e.key === 'Escape') { e.preventDefault(); finish(false) }
  })
}

// ── Polarity helpers ─────────────────────────────────────────────────────────

function _endOf(ovhgId) {
  if (!ovhgId) return null
  if (ovhgId.endsWith('_5p')) return '5p'
  if (ovhgId.endsWith('_3p')) return '3p'
  return null
}

async function _onDelete(conn) {
  if (!confirm(`Delete linker "${conn.name ?? conn.id}"?`)) return
  try {
    await api.deleteOverhangConnection(conn.id)
    // If the deleted linker was selected, clear the selection so the bridge
    // box clears + Gen disables (per "no selection → empty boxes" contract).
    if (_ctSelectedConnId === conn.id) _ctSelectedConnId = null
    _renderTable()
    _refreshConnectionTypesUI()
  } catch (err) {
    showToast(err?.message || String(err))
  }
}
