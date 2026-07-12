/**
 * Assembly-level Overhangs Manager — Connection Types tab.
 *
 * Visually identical to the per-part Overhangs Manager's Connection Types
 * tab (same .ohc-list-row, .ct-button-box, .ct-popover, .ct-option, .ct-tile
 * styling) so the user has a single mental model across both tools.
 * The only deliberate adaptation is the side lists: each list groups
 * overhangs under a per-PartInstance header so you can see which part each
 * overhang belongs to.
 *
 * Data:
 *   - Reads PartInstance designs from a local cache, populated on open via
 *     api.getInstanceDesign(id) so file-backed instances (which carry no
 *     inline `source.design`) still show their overhangs.
 *   - Mutations route through assembly-level API helpers
 *     (createAssemblyOverhangConnection, createAssemblyOverhangBinding,
 *      delete*, patchInstanceOverhang).
 *   - The per-side overhang Gen button hits POST /design/random-sequence
 *     directly (no design-state dependency), same as the per-part popup.
 */

import * as api from '../api/client.js'
import { ctTileSvg } from './ct_icons.js'
import { classifyAssemblyDuplex } from '../scene/design_queries.js'

// 12 connection-type variants (matches per-part _CT_VARIANTS).
const _VARIANTS = [
  { id: 'end-to-root',                label: 'End-to-Root' },
  { id: 'root-to-root',               label: 'Root-to-Root' },
  { id: 'root-to-root-indirect',      label: 'Root-to-Root Indirect' },
  { id: 'end-to-end-indirect',        label: 'End-to-End Indirect' },
  { id: 'root-to-root-ssdna-linker',  label: 'Root-to-Root ssDNA Linker' },
  { id: 'end-to-end-ssdna-linker',    label: 'End-to-End ssDNA Linker' },
  { id: 'end-to-root-ssdna-linker',   label: 'End-to-Root ssDNA Linker' },
  { id: 'root-to-end-ssdna-linker',   label: 'Root-to-End ssDNA Linker' },
  { id: 'root-to-root-dsdna-linker',  label: 'Root-to-Root dsDNA Linker' },
  { id: 'end-to-end-dsdna-linker',    label: 'End-to-End dsDNA Linker' },
  { id: 'end-to-root-dsdna-linker',   label: 'End-to-Root dsDNA Linker' },
  { id: 'root-to-end-dsdna-linker',   label: 'Root-to-End dsDNA Linker' },
]

const _STORAGE = 'nadoc.assemblyOverhangsManager.connectionType'

// ── Module state ──────────────────────────────────────────────────────────────
let _store    = null
let _modal    = null
let _isOpen   = false
let _unsub    = null

let _variant = 'end-to-root'
// Selection on each side: { instanceId, overhangId }.
let _selA    = null
let _selB    = null
// Currently-selected linker row in the table — drives the bridge box.
let _selectedConnId = null

// Cache: PartInstance.id → Design (the .nadoc-loaded payload).
// Populated on open + when the assembly's instance list changes.
// Inline sources fall back to inst.source.design directly.
const _designCache = new Map()

// Side-list filter queries (lower-case substring on part name OR overhang name).
let _aohcFilterA = ''
let _aohcFilterB = ''
// Table sort state.
let _aohcSortKey = 'name'
let _aohcSortDir = 'asc'

// Per-side, explicitly-expanded PartInstance ids. The actual "is expanded"
// decision OR's these with the part containing the side's current selection
// (see _isPartExpanded), so picking a row inside a part keeps it open and
// the user can't lose sight of what's selected by accidental collapse.
const _expandedA = new Set()
const _expandedB = new Set()

// ── Public API ────────────────────────────────────────────────────────────────

export function initAssemblyOverhangsManagerPopup({ store }) {
  _store = store
  _modal = document.getElementById('assembly-overhangs-manager-modal')
  if (!_modal) return

  document.getElementById('aohc-close')?.addEventListener('click', close)
  document.getElementById('aohc-close-2')?.addEventListener('click', close)
  _modal.addEventListener('click', (e) => { if (e.target === _modal) close() })

  // Restore last variant choice.
  try {
    const saved = localStorage.getItem(_STORAGE)
    if (saved && _VARIANTS.some(v => v.id === saved)) _variant = saved
  } catch { /* ignore */ }

  _initVariantPicker()

  // Event delegation for both side lists: one click listener per list,
  // attached once at init, survives every re-render. Routes part-header
  // clicks to _togglePartExpansion and row clicks to _onPickRow.
  for (const side of ['a', 'b']) {
    const listEl = document.getElementById(`aohc-list-${side}`)
    if (!listEl) continue
    listEl.addEventListener('click', (ev) => {
      const header = ev.target.closest('.aohc-part-header')
      if (header && listEl.contains(header)) {
        const id = header.dataset.instanceId
        if (id) _togglePartExpansion(side, id)
        return
      }
      const row = ev.target.closest('.ohc-list-row')
      if (row && listEl.contains(row)) {
        const inst = row.dataset.instanceId
        const oh   = row.dataset.overhangId
        if (inst && oh) _onPickRow(side, inst, oh)
      }
    })
  }

  // List filter inputs.
  for (const side of ['a', 'b']) {
    const inp = document.getElementById(`aohc-list-search-${side}`)
    if (!inp) continue
    inp.addEventListener('input', () => {
      if (side === 'a') _aohcFilterA = inp.value.trim().toLowerCase()
      else              _aohcFilterB = inp.value.trim().toLowerCase()
      _render()
    })
  }

  // Sortable table headers.
  for (const th of document.querySelectorAll('#aohc-table thead th[data-sort-key]')) {
    th.style.cursor = 'pointer'
    th.addEventListener('click', () => {
      const key = th.dataset.sortKey
      if (_aohcSortKey === key) _aohcSortDir = (_aohcSortDir === 'asc') ? 'desc' : 'asc'
      else { _aohcSortKey = key; _aohcSortDir = 'asc' }
      _renderTable(_assembly())
    })
  }

  // Generate button.
  document.getElementById('aohc-generate')?.addEventListener('click', _onAction)
  document.getElementById('aohc-length')?.addEventListener('input', _refreshActionButton)

  // Per-side sequence editing.
  for (const side of ['a', 'b']) {
    const input = document.getElementById(`aohc-seq-input-${side}`)
    const genBtn = document.getElementById(`aohc-seq-gen-${side}`)
    input?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter')  { e.preventDefault(); input.blur() }
      if (e.key === 'Escape') { e.preventDefault(); _refreshSeqRow(side); input.blur() }
    })
    input?.addEventListener('blur', () => _commitOverhangSequence(side))
    genBtn?.addEventListener('click', () => _generateOverhangSequence(side))
  }

  // Bridge sequence editing.
  const bridgeInputA = document.getElementById('aohc-bridge-input-a')
  bridgeInputA?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter')  { e.preventDefault(); bridgeInputA.blur() }
    if (e.key === 'Escape') { e.preventDefault(); _refreshBridge(); bridgeInputA.blur() }
  })
  bridgeInputA?.addEventListener('input', _syncBridgeRcMirror)
  bridgeInputA?.addEventListener('blur', _commitBridgeSequence)
  document.getElementById('aohc-bridge-gen-a')?.addEventListener('click', _generateBridgeSequence)
}

export async function open() {
  if (!_modal) return
  _isOpen = true
  _selA = _selB = null
  _selectedConnId = null
  // Fully collapsed on open. Parts containing a selection (set just below from
  // the 3D overhang selection) auto-expand via _isPartExpanded.
  _expandedA.clear()
  _expandedB.clear()
  _modal.style.display = 'flex'

  await _ensureDesignCache(_assembly())

  // Prefill Side A / Side B from the ordered overhang selection made in the 3D
  // view (clicking overhang name labels). Snapshot at open time only — no live
  // updates while the popup is open. Keep only entries whose overhang still
  // resolves in the cached design; first → A, second (if distinct) → B.
  const presel = (_store?.getState()?.assemblyOverhangSelection ?? [])
    .filter(s => s && _findOverhang(s.instanceId, s.overhangId))
  if (presel[0]) _selA = { instanceId: presel[0].instanceId, overhangId: presel[0].overhangId }
  if (presel[1] &&
      !(presel[1].instanceId === presel[0]?.instanceId && presel[1].overhangId === presel[0]?.overhangId))
    _selB = { instanceId: presel[1].instanceId, overhangId: presel[1].overhangId }

  _render()

  if (_unsub) _unsub()
  _unsub = _store?.subscribe(() => {
    if (!_isOpen) return
    // Lazily fetch any newly-added instances' designs and re-render.
    _ensureDesignCache(_assembly()).then(() => _render())
  }) ?? null
}

export function close() {
  if (!_modal) return
  _isOpen = false
  _modal.style.display = 'none'
  if (_unsub) { _unsub(); _unsub = null }
}

// ── Design cache (handles file-backed instances) ─────────────────────────────

async function _ensureDesignCache(assembly) {
  if (!assembly) return
  // Prune stale entries (instances removed from the assembly).
  const live = new Set((assembly.instances ?? []).map(i => i.id))
  for (const id of _designCache.keys()) {
    if (!live.has(id)) _designCache.delete(id)
  }
  // Inline instances: use the design straight from the source.
  for (const inst of assembly.instances ?? []) {
    if (inst.source?.type === 'inline' && inst.source.design) {
      _designCache.set(inst.id, inst.source.design)
    }
  }
  // File-backed instances: fetch via the existing endpoint.
  const fetches = []
  for (const inst of assembly.instances ?? []) {
    if (_designCache.has(inst.id)) continue
    if (inst.source?.type !== 'file') continue
    fetches.push(
      api.getInstanceDesign(inst.id).then((json) => {
        if (json?.design) _designCache.set(inst.id, json.design)
      }).catch(() => { /* leave unset; row will say "no overhangs" */ })
    )
  }
  if (fetches.length) await Promise.all(fetches)
}

function _designFor(instanceId) {
  return _designCache.get(instanceId) ?? null
}

function _overhangsFor(instanceId) {
  return _designFor(instanceId)?.overhangs ?? []
}

function _findInstance(id) {
  return _assembly()?.instances?.find(i => i.id === id) ?? null
}

function _findOverhang(instanceId, overhangId) {
  return _overhangsFor(instanceId).find(o => o.id === overhangId) ?? null
}

function _assembly() { return _store?.getState()?.currentAssembly ?? null }

// ── Variant picker (button-box + popover) ────────────────────────────────────

function _initVariantPicker() {
  const box     = document.getElementById('aohc-button-box')
  const popover = document.getElementById('aohc-popover')
  if (!box || !popover) return

  popover.innerHTML = ''
  for (const v of _VARIANTS) {
    const opt = document.createElement('button')
    opt.type = 'button'
    opt.className = 'ct-option'
    opt.dataset.variant = v.id
    opt.setAttribute('role', 'option')
    opt.title = v.label
    opt.innerHTML = `<div class="ct-tile">${ctTileSvg(v.id, null, null, false, false, false)}</div>`
    opt.addEventListener('click', (ev) => {
      ev.stopPropagation()
      _variant = v.id
      try { localStorage.setItem(_STORAGE, v.id) } catch { /* ignore */ }
      _closeVariantPopover()
      _render()
    })
    popover.appendChild(opt)
  }

  box.addEventListener('click', (ev) => {
    ev.stopPropagation()
    if (popover.hasAttribute('hidden')) _openVariantPopover()
    else                                _closeVariantPopover()
  })

  document.addEventListener('click', (ev) => {
    if (popover.hasAttribute('hidden')) return
    if (popover.contains(ev.target) || box.contains(ev.target)) return
    _closeVariantPopover()
  })
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && !popover.hasAttribute('hidden')) _closeVariantPopover()
  })
}

function _openVariantPopover() {
  const box     = document.getElementById('aohc-button-box')
  const popover = document.getElementById('aohc-popover')
  if (!box || !popover) return
  const r = box.getBoundingClientRect()
  // 4-column grid of 188px tiles + gaps + padding ≈ 796px wide.
  const popoverW = 796
  const left = Math.max(8, Math.min(window.innerWidth - popoverW - 8, r.left + r.width / 2 - popoverW / 2))
  popover.style.position = 'fixed'
  popover.style.left = `${Math.round(left)}px`
  popover.style.top  = `${Math.round(r.bottom + 6)}px`
  popover.hidden = false
  box.setAttribute('aria-expanded', 'true')
}

function _closeVariantPopover() {
  const box     = document.getElementById('aohc-button-box')
  const popover = document.getElementById('aohc-popover')
  if (!popover) return
  popover.hidden = true
  if (box) box.setAttribute('aria-expanded', 'false')
}

function _refreshVariantPicker() {
  const box     = document.getElementById('aohc-button-box')
  const popover = document.getElementById('aohc-popover')
  if (!box) return

  const L = _selA ? _polarityOfOverhang(_selA.overhangId) : null
  const R = _selB ? _polarityOfOverhang(_selB.overhangId) : null
  const hasA = !!_selA, hasB = !!_selB
  const forbidden = hasA && hasB && _isForbidden(_variant, L, R)

  box.innerHTML = `<div class="ct-tile">${ctTileSvg(_variant, L, R, forbidden, hasA, hasB)}</div>`

  if (popover) {
    for (const opt of popover.querySelectorAll('.ct-option')) {
      const id = opt.dataset.variant
      const optForbid = hasA && hasB && _isForbidden(id, L, R)
      opt.innerHTML = `<div class="ct-tile">${ctTileSvg(id, L, R, optForbid, hasA, hasB)}</div>`
      opt.classList.toggle('is-selected', id === _variant)
    }
  }
}

// ── Render ───────────────────────────────────────────────────────────────────

function _render() {
  const a = _assembly()
  if (!a || !_modal) return
  _renderSideList('a', a)
  _renderSideList('b', a)
  _refreshSeqRow('a')
  _refreshSeqRow('b')
  _refreshVariantPicker()
  _refreshActionButton()
  _refreshLengthRowVisibility()
  _refreshBridge()
  _renderTable(a)
}

function _isPartExpanded(side, instanceId) {
  // Force-expand the part containing this side's current selection so the
  // user always sees the picked row.
  const sel = side === 'a' ? _selA : _selB
  if (sel && sel.instanceId === instanceId) return true
  const set = side === 'a' ? _expandedA : _expandedB
  return set.has(instanceId)
}

function _togglePartExpansion(side, instanceId) {
  // No-op if the part is force-expanded by an active selection — collapsing
  // would hide the picked row, which is more confusing than helpful.
  const sel = side === 'a' ? _selA : _selB
  if (sel && sel.instanceId === instanceId) return
  const set = side === 'a' ? _expandedA : _expandedB
  if (set.has(instanceId)) set.delete(instanceId)
  else                     set.add(instanceId)
  _renderSideList(side, _assembly())
}

function _renderSideList(side, assembly) {
  const listEl = document.getElementById(`aohc-list-${side}`)
  if (!listEl) return
  listEl.innerHTML = ''

  const instances = assembly.instances ?? []
  if (instances.length === 0) {
    listEl.innerHTML = '<div style="padding:14px;font-size:11px;color:#6e7681;text-align:center">No parts in this assembly.</div>'
    return
  }

  const q = (side === 'a' ? _aohcFilterA : _aohcFilterB)
  let anyOverhangs = false
  let anyMatch = false
  for (const inst of instances) {
    const allOvhgs = [..._overhangsFor(inst.id)].sort(
      (a, b) => _displayName(a).localeCompare(_displayName(b), undefined, { numeric: true })
    )
    if (allOvhgs.length === 0) continue
    anyOverhangs = true

    // When a filter is active, keep this part if its name matches (all
    // overhangs visible) OR any of its overhangs matches. With no filter,
    // honor the user's expand/collapse state.
    let ovhgs = allOvhgs
    let expanded = _isPartExpanded(side, inst.id)
    if (q) {
      const partMatches = (inst.name || inst.id).toLowerCase().includes(q)
      const matching = allOvhgs.filter(o => _displayName(o).toLowerCase().includes(q))
      if (!partMatches && matching.length === 0) continue
      ovhgs = partMatches ? allOvhgs : matching
      expanded = true   // auto-expand parts with matching overhangs while filtering
    }
    anyMatch = true

    const header = document.createElement('button')
    header.type = 'button'
    header.className = 'aohc-part-header'
    header.dataset.instanceId = inst.id
    header.setAttribute('aria-expanded', expanded ? 'true' : 'false')
    header.innerHTML =
      `<span class="aohc-chevron" aria-hidden="true">▶</span>` +
      `<span>${_escape(inst.name || inst.id)}</span>` +
      `<span class="aohc-part-count">${ovhgs.length}</span>`
    // Click handler lives on the parent list (event delegation, see init()).
    listEl.appendChild(header)

    if (expanded) {
      for (const ovhg of ovhgs) {
        listEl.appendChild(_makeListRow(inst, ovhg, side))
      }
    }
  }

  if (!anyOverhangs) {
    listEl.innerHTML = '<div style="padding:14px;font-size:11px;color:#6e7681;text-align:center">No overhangs on any part.</div>'
    return
  }
  if (q && !anyMatch) {
    listEl.innerHTML = `<div style="padding:14px;font-size:11px;color:#6e7681;text-align:center">No matches for "${_escape(q)}".</div>`
    return
  }
  _refreshListSelection()
}

function _makeListRow(inst, ovhg, side) {
  const row = document.createElement('div')
  row.className = 'ohc-list-row'
  row.dataset.instanceId = inst.id
  row.dataset.overhangId = ovhg.id
  row.dataset.side = side
  const nameEl = document.createElement('span')
  nameEl.textContent = _displayName(ovhg)
  const tagEl = document.createElement('span')
  tagEl.className = 'ohc-end-tag'
  tagEl.textContent = _endTag(ovhg.id)
  row.append(nameEl, tagEl)
  // Click handler lives on the parent list (event delegation, see init()).
  return row
}

function _refreshListSelection() {
  for (const row of document.querySelectorAll('#aohc-list-a .ohc-list-row')) {
    const isPicked = !!_selA && row.dataset.instanceId === _selA.instanceId && row.dataset.overhangId === _selA.overhangId
    row.classList.toggle('ct-selected-a', isPicked)
    // Can't pick the same (instance, overhang) on both sides.
    const isOpposite = !!_selB && row.dataset.instanceId === _selB.instanceId && row.dataset.overhangId === _selB.overhangId
    row.classList.toggle('is-disabled', isOpposite)
  }
  for (const row of document.querySelectorAll('#aohc-list-b .ohc-list-row')) {
    const isPicked = !!_selB && row.dataset.instanceId === _selB.instanceId && row.dataset.overhangId === _selB.overhangId
    row.classList.toggle('ct-selected-b', isPicked)
    const isOpposite = !!_selA && row.dataset.instanceId === _selA.instanceId && row.dataset.overhangId === _selA.overhangId
    row.classList.toggle('is-disabled', isOpposite)
  }
}

function _onPickRow(side, instanceId, overhangId) {
  const opposite = side === 'a' ? _selB : _selA
  if (opposite && opposite.instanceId === instanceId && opposite.overhangId === overhangId) return
  const pick = { instanceId, overhangId }
  if (side === 'a') {
    _selA = (_selA && _selA.instanceId === instanceId && _selA.overhangId === overhangId) ? null : pick
  } else {
    _selB = (_selB && _selB.instanceId === instanceId && _selB.overhangId === overhangId) ? null : pick
  }
  _render()
}

function _refreshSeqRow(side) {
  const row   = document.getElementById(`aohc-seq-row-${side}`)
  const input = document.getElementById(`aohc-seq-input-${side}`)
  if (!row || !input) return
  const sel = side === 'a' ? _selA : _selB
  if (!sel) { row.hidden = true; input.value = ''; return }
  row.hidden = false
  const ovhg = _findOverhang(sel.instanceId, sel.overhangId)
  if (document.activeElement !== input) input.value = ovhg?.sequence || ''
}

function _refreshLengthRowVisibility() {
  const row = document.getElementById('aohc-length-row')
  const btn = document.getElementById('aohc-generate')
  if (!row || !btn) return
  const direct   = _isDirectVariant(_variant)
  const indirect = _isIndirectVariant(_variant)
  row.hidden = direct || indirect
  btn.textContent = direct ? 'Make Complementary' : 'Generate Linker'
}

function _refreshActionButton() {
  const btn = document.getElementById('aohc-generate')
  const errorEl = document.getElementById('aohc-error')
  const lenEl = document.getElementById('aohc-length')
  if (!btn) return

  const direct   = _isDirectVariant(_variant)
  const indirect = _isIndirectVariant(_variant)
  const hasBoth   = !!_selA && !!_selB
  const crossPart = hasBoth && _selA.instanceId !== _selB.instanceId
  const L = hasBoth ? _polarityOfOverhang(_selA.overhangId) : null
  const R = hasBoth ? _polarityOfOverhang(_selB.overhangId) : null
  const forbidden = hasBoth && _isForbidden(_variant, L, R)
  const len = parseFloat(lenEl?.value ?? '')
  // direct & indirect connections both bypass the length input.
  const lenOk = (direct || indirect) ? true : (Number.isFinite(len) && len > 0)

  const ok = hasBoth && crossPart && !forbidden && lenOk
  btn.disabled = !ok

  if (errorEl) {
    if (forbidden) {
      errorEl.style.display = 'block'
      errorEl.textContent = _forbiddenReason(_variant, L, R) || 'This polarity combination is not valid for the selected connection type.'
    } else if (hasBoth && !crossPart) {
      errorEl.style.display = 'block'
      errorEl.textContent = 'Both selections are on the same part. Pick across parts.'
    } else {
      errorEl.style.display = 'none'
      errorEl.textContent = ''
    }
  }
}

function _refreshBridge() {
  const section = document.getElementById('aohc-bridge-section')
  const rowB    = document.getElementById('aohc-bridge-row-b')
  const inputA  = document.getElementById('aohc-bridge-input-a')
  const inputB  = document.getElementById('aohc-bridge-input-b')
  const genA    = document.getElementById('aohc-bridge-gen-a')
  if (!section || !inputA) return
  const conn = _selectedConnId
    ? _assembly()?.overhang_connections?.find(c => c.id === _selectedConnId)
    : null
  if (!conn) {
    section.hidden = true
    inputA.value = ''
    if (inputB) inputB.value = ''
    return
  }
  section.hidden = false
  const lenBp = _connectionLengthBp(conn)
  if (document.activeElement !== inputA) inputA.value = conn.bridge_sequence ?? ''
  inputA.placeholder = `${lenBp || ''} bp — type or Gen to assign`
  if (genA) genA.disabled = !conn

  // ds linkers: show the read-only reverse-complement mirror row.
  const isDs = conn.linker_type === 'ds'
  if (rowB) rowB.hidden = !isDs
  if (isDs) _syncBridgeRcMirror()
}

function _syncBridgeRcMirror() {
  const inputA = document.getElementById('aohc-bridge-input-a')
  const inputB = document.getElementById('aohc-bridge-input-b')
  if (!inputA || !inputB) return
  inputB.value = _revcomp(inputA.value || '')
}

// ── Table (mixed linkers + bindings) ─────────────────────────────────────────

function _renderTable(assembly) {
  const tbody = document.getElementById('aohc-table-body')
  if (!tbody) return
  tbody.innerHTML = ''

  const conns    = assembly.overhang_connections ?? []
  const bindings = assembly.overhang_bindings    ?? []
  if (conns.length === 0 && bindings.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="padding:14px;text-align:center;color:#6e7681">No linkers or bindings yet.</td></tr>`
    return
  }

  // Mixed array of conn/binding rows, sorted by the user-chosen column.
  const rows = [
    ...conns.map(c    => ({ kind: 'conn',    e: c })),
    ...bindings.map(b => ({ kind: 'binding', e: b })),
  ]
  function _val(r) {
    const e = r.e
    switch (_aohcSortKey) {
      case 'type':
        return r.kind === 'binding' ? 'binding' : (e.linker_type === 'ds' ? 'dsdna' : 'ssdna')
      case 'length':
        return r.kind === 'conn' ? (Number(e.length_value) || 0) : -1
      case 'overhangs': {
        const instA = _findInstance(e.instance_a_id)
        const instB = _findInstance(e.instance_b_id)
        const ohA   = _findOverhang(e.instance_a_id, e.overhang_a_id)
        const ohB   = _findOverhang(e.instance_b_id, e.overhang_b_id)
        const labA = _displayName(ohA) || e.overhang_a_id || ''
        const labB = _displayName(ohB) || e.overhang_b_id || ''
        return `${instA?.name ?? ''}.${labA} ↔ ${instB?.name ?? ''}.${labB}`.toLowerCase()
      }
      case 'bound':
        return r.kind === 'binding' ? (e.bound ? 1 : 0) : -1
      case 'name':
      default:
        return (e.name ?? '').toLowerCase()
    }
  }
  const dir = _aohcSortDir === 'asc' ? 1 : -1
  rows.sort((a, b) => {
    const va = _val(a); const vb = _val(b)
    if (typeof va === 'number' && typeof vb === 'number') return dir * (va - vb)
    return dir * String(va).localeCompare(String(vb), undefined, { numeric: true })
  })
  _updateAohcSortArrows()

  for (const r of rows) {
    if (r.kind === 'conn')    tbody.insertAdjacentHTML('beforeend', _connectionRowHtml(assembly, r.e))
    else                       tbody.insertAdjacentHTML('beforeend', _bindingRowHtml(assembly, r.e))
  }

  tbody.querySelectorAll('.aohc-del-conn').forEach(btn => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); _onDeleteConnection(btn.dataset.id) })
  })
  tbody.querySelectorAll('.aohc-relax-conn').forEach(btn => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); _onRelaxConnection(btn) })
    // Lazily gate on the backend's relax-status (which part is movable / both
    // fixed / ss). Render enabled, then disable + retitle if unavailable.
    api.getAssemblyOverhangConnectionRelaxStatus(btn.dataset.id).then((st) => {
      if (st && st.available === false) {
        btn.disabled = true
        btn.style.opacity = '0.45'
        btn.style.cursor = 'not-allowed'
        if (st.reason) btn.title = st.reason
      }
    }).catch(() => {})
  })
  tbody.querySelectorAll('.aohc-del-binding').forEach(btn => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); _onDeleteBinding(btn.dataset.id) })
  })
  tbody.querySelectorAll('.aohc-conn-row').forEach(row => {
    row.addEventListener('click', () => {
      const id = row.dataset.id
      _selectedConnId = (_selectedConnId === id) ? null : id
      _refreshBridge()
      _renderTable(_assembly())
    })
  })
}

function _connectionRowHtml(assembly, c) {
  const instA = _findInstance(c.instance_a_id)
  const instB = _findInstance(c.instance_b_id)
  const ohA   = _findOverhang(c.instance_a_id, c.overhang_a_id)
  const ohB   = _findOverhang(c.instance_b_id, c.overhang_b_id)
  const pair  = `${instA?.name ?? '?'}.${_displayName(ohA) || c.overhang_a_id} (${_attachLabel(c.overhang_a_attach)}) ↔ ${instB?.name ?? '?'}.${_displayName(ohB) || c.overhang_b_id} (${_attachLabel(c.overhang_b_attach)})`
  const typeLabel = c.linker_type === 'ds' ? 'dsDNA' : 'ssDNA'
  const length = `${_fmtNum(c.length_value)} ${c.length_unit}`
  const seq = c.bridge_sequence
    ? `<span style="font-family:monospace;color:#c9d1d9">${_escape(c.bridge_sequence)}</span>`
    : '<span style="color:#6e7681">—</span>'
  const highlight = c.id === _selectedConnId ? 'background:#1a2540' : ''
  return `<tr class="aohc-conn-row" data-id="${c.id}" style="cursor:pointer;${highlight}">
    <td>${_escape(c.name || '—')}</td>
    <td>${typeLabel}</td>
    <td>${length}</td>
    <td>${_escape(pair)}</td>
    <td>${seq}</td>
    <td style="color:#6e7681">—</td>
    <td style="text-align:right;white-space:nowrap">
      ${(c.linker_type === 'ds' || (c.linker_type === 'ss' && Number(c.length_value) === 0)) ? `<button class="aohc-relax-conn" data-id="${c.id}" title="Relax linker (rigid-place the free part to close the connector arc)"
              style="background:#152d1c;border:1px solid #3ca35a;color:#3ca35a;border-radius:3px;font-size:11px;cursor:pointer;padding:2px 7px;margin-right:4px">Relax</button>` : ''}
      <button class="aohc-del-conn" data-id="${c.id}" title="Delete linker"
              style="background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:11px;cursor:pointer;padding:2px 7px">×</button>
    </td>
  </tr>`
}

function _bindingRowHtml(assembly, b) {
  const instA = _findInstance(b.instance_a_id)
  const instB = _findInstance(b.instance_b_id)
  const ohA   = _findOverhang(b.instance_a_id, b.overhang_a_id)
  const ohB   = _findOverhang(b.instance_b_id, b.overhang_b_id)
  const pair  = `${instA?.name ?? '?'}.${_displayName(ohA) || b.overhang_a_id} ↔ ${instB?.name ?? '?'}.${_displayName(ohB) || b.overhang_b_id}`
  const seqA  = ohA?.sequence ?? ''
  const seqB  = ohB?.sequence ?? ''
  // Prefer the STORED cross-part duplex register (multivalency / toeholds / sub-domain
  // windows) over the naive whole-sequence complement; fall back when no duplex exists.
  const dx = _duplexForPair(assembly, b)
  const status = dx ? _duplexStatus(assembly, dx) : _pairStatus(seqA, seqB)
  return `<tr>
    <td>${_escape(b.name)}</td>
    <td>Binding</td>
    <td style="color:#6e7681">—</td>
    <td>${_escape(pair)}</td>
    <td>
      <span style="color:#00e1ff;font-family:monospace">${_escape(seqA) || '—'}</span><br>
      <span style="color:#ff36c6;font-family:monospace">${_escape(seqB) || '—'}</span>
    </td>
    <td>${status.html}</td>
    <td style="text-align:right">
      <button class="aohc-del-binding" data-id="${b.id}" title="Delete binding"
              style="background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:11px;cursor:pointer;padding:2px 7px">×</button>
    </td>
  </tr>`
}

// ── Actions ───────────────────────────────────────────────────────────────────

async function _onAction() {
  if (_isDirectVariant(_variant)) await _onMakeComplementary()
  else                            await _onGenerateLinker()
}

async function _onGenerateLinker() {
  if (!_selA || !_selB) return
  const indirect = _isIndirectVariant(_variant)
  let length
  if (indirect) {
    length = 0   // indirect → shared linker, no user-controllable length
  } else {
    const lenEl = document.getElementById('aohc-length')
    length = parseFloat(lenEl?.value ?? '')
    if (!Number.isFinite(length) || length <= 0) { _setStatus('Length must be positive.'); return }
  }
  const [attachA, attachB] = _attachPairFor(_variant)
  const linker_type = _variant.includes('dsdna') ? 'ds' : 'ss'

  // Flush any uncommitted side-input edits.
  await _commitOverhangSequence('a')
  await _commitOverhangSequence('b')

  try {
    const res = await api.createAssemblyOverhangConnection({
      instance_a_id:     _selA.instanceId,
      overhang_a_id:     _selA.overhangId,
      overhang_a_attach: attachA,
      instance_b_id:     _selB.instanceId,
      overhang_b_id:     _selB.overhangId,
      overhang_b_attach: attachB,
      linker_type,
      length_value:      length,
      length_unit:       'bp',
    })
    const newConns = res?.assembly?.overhang_connections ?? []
    const created  = newConns[newConns.length - 1]
    if (created) _selectedConnId = created.id
    _setStatus(`Created ${created?.name ?? 'linker'}.`)
  } catch (err) {
    _setStatus(`Could not create linker: ${err?.message ?? err}`)
  }
}

async function _onMakeComplementary() {
  if (!_selA || !_selB) return
  const ohA = _findOverhang(_selA.instanceId, _selA.overhangId)
  const ohB = _findOverhang(_selB.instanceId, _selB.overhangId)
  if (!ohA || !ohB) return

  // 1. Write reverse-complement of A's sequence to B, if A has a sequence.
  if (ohA.sequence) {
    try {
      await api.patchInstanceOverhang(_selB.instanceId, _selB.overhangId, { sequence: _revcomp(ohA.sequence) })
    } catch (err) {
      _setStatus(`Could not write complement to B: ${err?.message ?? err}`)
      return
    }
  }

  // 2. Create the cross-part binding using each side's first sub-domain.
  const sdA = ohA.sub_domains?.[0]?.id
  const sdB = ohB.sub_domains?.[0]?.id
  if (!sdA || !sdB) {
    _setStatus('Sub-domains missing — cannot bind. Edit sub-domains in the per-part Overhangs Manager.')
    return
  }
  try {
    await api.createAssemblyOverhangBinding({
      instance_a_id:   _selA.instanceId,
      sub_domain_a_id: sdA,
      overhang_a_id:   _selA.overhangId,
      instance_b_id:   _selB.instanceId,
      sub_domain_b_id: sdB,
      overhang_b_id:   _selB.overhangId,
    })
    _setStatus('Created binding.')
  } catch (err) {
    const msg = err?.message ?? String(err)
    if (msg.toLowerCase().includes('already')) _setStatus('Binding already exists for this pair.')
    else _setStatus(`Could not create binding: ${msg}`)
  }
}

async function _onDeleteConnection(id) {
  if (!id) return
  await api.deleteAssemblyOverhangConnection(id)
  if (_selectedConnId === id) _selectedConnId = null
}

async function _onRelaxConnection(btn) {
  const id = btn?.dataset?.id
  if (!id) return
  btn.disabled = true
  try {
    await api.relaxAssemblyOverhangConnection(id)
    _setStatus('Relaxed linker — free part moved to close the connector arc.')
  } catch (err) {
    _setStatus(`Relax failed: ${err?.message ?? err}`)
    btn.disabled = false
  }
}

async function _onDeleteBinding(id) {
  if (!id) return
  await api.deleteAssemblyOverhangBinding(id)
}

async function _commitOverhangSequence(side) {
  const input = document.getElementById(`aohc-seq-input-${side}`)
  const sel   = side === 'a' ? _selA : _selB
  if (!input || !sel) return
  const ovhg = _findOverhang(sel.instanceId, sel.overhangId)
  const typed = (input.value ?? '').toUpperCase().replace(/[^ACGTN]/g, '')
  const stored = ovhg?.sequence ?? ''
  if (typed === stored) return
  try {
    const res = await api.patchInstanceOverhang(sel.instanceId, sel.overhangId, { sequence: typed || null })
    // Refresh the cached design for this instance from the response so the
    // popup's lists reflect the new sequence without a round-trip.
    if (res?.design) _designCache.set(sel.instanceId, res.design)
  } catch (err) {
    _setStatus(`Could not patch overhang sequence: ${err?.message ?? err}`)
  }
}

async function _generateOverhangSequence(side) {
  const sel = side === 'a' ? _selA : _selB
  if (!sel) return
  const ovhg = _findOverhang(sel.instanceId, sel.overhangId)
  const length = _overhangLengthBp(ovhg) || (ovhg?.sequence?.length || 0)
  if (!length) { _setStatus('Cannot determine overhang length for Gen.'); return }
  try {
    const seq = await _fetchRandomSequence(length)
    if (!seq) return
    const input = document.getElementById(`aohc-seq-input-${side}`)
    if (input) input.value = seq
    const res = await api.patchInstanceOverhang(sel.instanceId, sel.overhangId, { sequence: seq })
    if (res?.design) _designCache.set(sel.instanceId, res.design)
  } catch (err) {
    _setStatus(`Could not generate sequence: ${err?.message ?? err}`)
  }
}

async function _commitBridgeSequence() {
  if (!_selectedConnId) return
  const input = document.getElementById('aohc-bridge-input-a')
  const conn = _assembly()?.overhang_connections?.find(c => c.id === _selectedConnId)
  if (!input || !conn) return
  const typed = (input.value ?? '').toUpperCase().replace(/[^ACGTN]/g, '')
  const stored = conn.bridge_sequence ?? ''
  if (typed === stored) return
  try {
    await api.patchAssemblyOverhangConnection(_selectedConnId, { bridge_sequence: typed || null })
  } catch (err) {
    _setStatus(`Could not save bridge: ${err?.message ?? err}`)
  }
}

async function _generateBridgeSequence() {
  if (!_selectedConnId) return
  const conn = _assembly()?.overhang_connections?.find(c => c.id === _selectedConnId)
  if (!conn) return
  const lenBp = _connectionLengthBp(conn)
  if (!lenBp) return
  try {
    const seq = await _fetchRandomSequence(lenBp)
    if (!seq) return
    const input = document.getElementById('aohc-bridge-input-a')
    if (input) input.value = seq
    _syncBridgeRcMirror()
    await api.patchAssemblyOverhangConnection(_selectedConnId, { bridge_sequence: seq })
  } catch (err) {
    _setStatus(`Could not generate bridge: ${err?.message ?? err}`)
  }
}

async function _fetchRandomSequence(length) {
  // Same endpoint the per-part popup hits — Johnson 5-mer against the active
  // design's corpus. Direct fetch (no design-state sync on the client).
  const res = await fetch('/api/design/random-sequence', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ length }),
  })
  if (!res.ok) return null
  const json = await res.json()
  return json?.sequence ?? null
}

// ── Forbidden-polarity rules (mirror per-part popup) ─────────────────────────

function _isDirectVariant(id) {
  return id === 'end-to-root' || id === 'root-to-root'
}

// Indirect variants use a shared linker strand → no user-controllable length.
// Hide the length row + send length_value=0 when creating.
function _isIndirectVariant(id) {
  return id === 'root-to-root-indirect' || id === 'end-to-end-indirect'
}

function _attachPairFor(id) {
  if (id?.startsWith('end-to-root')) return ['free_end', 'root']
  if (id?.startsWith('root-to-end')) return ['root', 'free_end']
  if (id?.startsWith('root-to-root')) return ['root', 'root']
  if (id?.startsWith('end-to-end'))   return ['free_end', 'free_end']
  return ['root', 'root']
}

function _isForbidden(type, L, R) {
  if (L == null || R == null) return false
  if (type === 'root-to-root-dsdna-linker' || type === 'end-to-end-dsdna-linker') return L !== R
  if (type === 'root-to-root-ssdna-linker' || type === 'end-to-end-ssdna-linker' ||
      type === 'root-to-root-indirect'    || type === 'end-to-end-indirect')      return L === R
  if (type === 'end-to-root-dsdna-linker' || type === 'root-to-end-dsdna-linker') return L === R
  if (type === 'end-to-root-ssdna-linker' || type === 'root-to-end-ssdna-linker') return L !== R
  if (type === 'end-to-root')  return L !== R
  if (type === 'root-to-root') return L === R
  return false
}

function _forbiddenReason(type, L, R) {
  if (!_isForbidden(type, L, R)) return null
  const pol = (p) => (p === '5p' ? "5'" : "3'")
  const pair = `${pol(L)}/${pol(R)}`
  if (type === 'end-to-root')
    return `End-to-root direct: Watson-Crick hybridization needs the same polarity on both overhangs. ${pair} would force a parallel duplex.`
  if (type === 'root-to-root')
    return `Root-to-root direct: antiparallel pairing needs opposite polarities. ${pair} would force a parallel duplex.`
  if (type === 'root-to-root-dsdna-linker' || type === 'end-to-end-dsdna-linker')
    return `dsDNA linker (same attach): bridge strands run antiparallel; the linked overhangs must share polarity. ${pair} would force the bridge halves parallel.`
  if (type === 'end-to-root-dsdna-linker' || type === 'root-to-end-dsdna-linker')
    return `dsDNA linker (mixed attach): one root + one free-end flips comp-first polarity on one side, so overhangs must have OPPOSITE polarity. ${pair} would force the bridge halves parallel.`
  if (type === 'root-to-root-ssdna-linker' || type === 'end-to-end-ssdna-linker' ||
      type === 'root-to-root-indirect'    || type === 'end-to-end-indirect')
    return `Single-strand bridge (same attach): one continuous 5'→3' strand can't terminate ${pair}. Pick overhangs with opposite polarities.`
  if (type === 'end-to-root-ssdna-linker' || type === 'root-to-end-ssdna-linker')
    return `Single-strand bridge (mixed attach): one root + one free-end flips comp-first polarity on one side, so overhangs must MATCH polarity. ${pair} breaks the continuous 5'→3' bridge.`
  return 'This polarity combination is not valid for the selected connection type.'
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _displayName(ovhg) {
  if (!ovhg) return ''
  return ovhg.label || ovhg.id
}

function _endTag(ovhgId) {
  if (typeof ovhgId !== 'string') return ''
  if (ovhgId.endsWith('_5p')) return "5'"
  if (ovhgId.endsWith('_3p')) return "3'"
  return ''
}

function _polarityOfOverhang(id) {
  if (typeof id !== 'string') return null
  if (id.endsWith('_5p')) return '5p'
  if (id.endsWith('_3p')) return '3p'
  return null
}

function _attachLabel(a) {
  return a === 'free_end' ? 'free' : 'root'
}

function _overhangLengthBp(ovhg) {
  if (!ovhg) return 0
  return (ovhg.sub_domains ?? []).reduce((s, sd) => s + (sd.length_bp ?? 0), 0)
}

function _connectionLengthBp(c) {
  const v = Number(c?.length_value)
  if (!Number.isFinite(v) || v <= 0) return 0
  return c.length_unit === 'nm' ? Math.max(1, Math.round(v / 0.334)) : Math.round(v)
}

function _fmtNum(x) {
  const n = Number(x)
  if (!Number.isFinite(n)) return '—'
  return Math.abs(n - Math.round(n)) < 1e-6 ? String(Math.round(n)) : n.toFixed(2)
}

function _setStatus(text) {
  const s = document.getElementById('aohc-status')
  if (s) s.textContent = text ?? ''
}

const _COMP = { A:'T', T:'A', C:'G', G:'C', N:'N' }
function _revcomp(s) {
  let out = ''
  for (let i = s.length - 1; i >= 0; i--) out += _COMP[s[i].toUpperCase()] ?? 'N'
  return out
}

// The AssemblyDuplex covering the same (unordered) overhang pair as a binding, or null.
function _duplexForPair(assembly, e) {
  const key = (iid, oid) => `${iid}::${oid}`
  const want = new Set([key(e.instance_a_id, e.overhang_a_id), key(e.instance_b_id, e.overhang_b_id)])
  return (assembly?.duplexes ?? []).find((dx) => {
    const have = new Set([key(dx.left.instance_id, dx.left.overhang_id), key(dx.right.instance_id, dx.right.overhang_id)])
    return have.size === want.size && [...have].every(k => want.has(k))
  }) ?? null
}

// Status derived from the STORED cross-part duplex register — paired/mismatch bp per
// classifyAssemblyDuplex (sourcing each side's bases from its own instance design), NOT
// the naive whole-sequence RC of _pairStatus. Handles toeholds / partial windows.
function _duplexStatus(assembly, dx) {
  const cls = classifyAssemblyDuplex(_designFor(dx.left.instance_id), _designFor(dx.right.instance_id), dx)
  if (!cls.length) return { html: '<span style="color:#6e7681">—</span>' }
  if (cls.n_mismatch === 0) return { html: `<span style="color:#3fb950">paired ${cls.n_complementary}bp</span>` }
  return { html: `<span style="color:#d29922">${cls.n_mismatch} mismatch / ${cls.n_complementary} paired</span>` }
}

function _pairStatus(a, b) {
  if (!a || !b) return { html: '<span style="color:#6e7681">—</span>' }
  if (a.length !== b.length) return { html: `<span style="color:#d29922">${a.length}≠${b.length}</span>` }
  return _revcomp(a) === b.toUpperCase()
    ? { html: '<span style="color:#3fb950">match</span>' }
    : { html: '<span style="color:#d29922">mismatch</span>' }
}

function _escape(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
  ))
}

function _updateAohcSortArrows() {
  const arrow = _aohcSortDir === 'asc' ? ' ▲' : ' ▼'
  for (const th of document.querySelectorAll('#aohc-table thead th[data-sort-key]')) {
    if (!th.dataset.sortLabel) th.dataset.sortLabel = th.textContent.trim()
    th.textContent = th.dataset.sortLabel + (th.dataset.sortKey === _aohcSortKey ? arrow : '')
  }
}
