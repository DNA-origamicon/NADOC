/**
 * Assembly right-sidebar "Overhang Connections" section — the CROSS-PART twin of
 * the per-part `overhang_connections_panel.js`. Two overhang dropdowns (Side A /
 * B, grouped by part with <optgroup>), the shared connection-type icon picker (all
 * 12 variants), a length field, and a Generate button that creates a cross-part
 * linker (AssemblyOverhangConnection) or, for the two DIRECT variants, a binding
 * (AssemblyOverhangBinding) after writing B ← reverse-complement(A).
 *
 * Purpose: create connections between two parts by picking A/B from dropdowns —
 * populated + two-way synced with the 3D overhang-selection tool via the shared
 * `assemblyOverhangSelection` store slice (index 0 = A, 1 = B) — instead of
 * scrolling long overhang lists.
 *
 * Reuse (no fork): variant rules/icons from `ct_icons.js` (same source of truth as
 * the per-part panel + the Overhangs Manager popup), the grouped overhang model
 * from `groupOverhangs`, per-instance design resolution from
 * `initInstanceDesignCache`, and the cross-part create bodies mirror the popup's
 * `_onGenerateLinker` / `_onMakeComplementary`.
 */

import {
  CT_VARIANTS, ctTileSvg, endOf, ctIsForbidden, ctForbiddenReason,
  ctAttachPair, ctIsDirect, ctIsIndirect, ctLinkerType, ctVariantForConnection,
} from './ct_icons.js'
import {
  createAssemblyOverhangConnection, createAssemblyOverhangBinding,
  deleteAssemblyOverhangConnection, deleteAssemblyOverhangBinding, patchInstanceOverhang,
} from '../api/client.js'
import { initInstanceDesignCache } from './assembly_instance_designs.js'
import { groupOverhangs } from './assembly_overhang_list_panel.js'

const _STORAGE = 'nadoc.assemblyOverhangConnections.connectionType'
const SEP = ''   // unit separator — safe against ':'-bearing namespaced ids

// ── Pure helpers (unit-tested) ────────────────────────────────────────────────

export function encodeOption(instanceId, overhangId) { return `${instanceId}${SEP}${overhangId}` }
export function decodeOption(value) {
  if (!value) return null
  const i = value.indexOf(SEP)
  if (i < 0) return null
  return { instanceId: value.slice(0, i), overhangId: value.slice(i + 1) }
}

const _WC = { A: 'T', T: 'A', C: 'G', G: 'C', N: 'N' }
export function revcomp(s) {
  let out = ''
  for (const ch of String(s ?? '').toUpperCase()) out = (_WC[ch] ?? 'N') + out
  return out
}

/** The createAssemblyOverhangConnection body for a linker variant (pure). */
export function connectionBody(variant, A, B, length) {
  const [attachA, attachB] = ctAttachPair(variant)
  return {
    instance_a_id: A.instanceId, overhang_a_id: A.overhangId, overhang_a_attach: attachA,
    instance_b_id: B.instanceId, overhang_b_id: B.overhangId, overhang_b_attach: attachB,
    linker_type: ctLinkerType(variant),
    length_value: ctIsIndirect(variant) ? 0 : length,
    length_unit: 'bp',
  }
}

/** Whether the Generate button should be enabled (pure). */
export function canGenerate({ A, B, variant, length }) {
  if (!A || !B) return false
  if (A.instanceId === B.instanceId) return false                       // must be cross-part
  if (ctIsForbidden(variant, endOf(A.overhangId), endOf(B.overhangId))) return false
  if (ctIsDirect(variant) || ctIsIndirect(variant)) return true         // no length needed
  return Number.isFinite(length) && length > 0
}

function _escape(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}

// ── Factory ───────────────────────────────────────────────────────────────────

export function initAssemblyOverhangConnectionsPanel({ store, getInstanceDesign, fetchInstanceDesign } = {}) {
  const _designs = initInstanceDesignCache({ getInstanceDesign, fetchInstanceDesign })
  let _variant = (() => { try { return localStorage.getItem(_STORAGE) || 'end-to-root' } catch { return 'end-to-root' } })()
  let _prevAssembly = undefined
  let _prevSel = undefined

  const $ = (id) => document.getElementById(id)
  const _assembly = () => store?.getState()?.currentAssembly ?? null
  const _selection = () => store?.getState()?.assemblyOverhangSelection ?? []
  const _sideA = () => _selection()[0] ?? null
  const _sideB = () => _selection()[1] ?? null

  const _overhang = (instanceId, overhangId) =>
    _designs.overhangsFor(instanceId).find(o => o.id === overhangId) ?? null
  const _label = (instanceId, overhangId) =>
    _overhang(instanceId, overhangId)?.label || overhangId

  // ── Two-way with the 3D tool: A = selection[0], B = selection[1] ────────────
  function _setSide(side, pick) {
    const a = side === 'a' ? pick : _sideA()
    const b = side === 'b' ? pick : _sideB()
    const next = []
    if (a) next.push(a)
    if (b) next.push(b)
    store.setState({ assemblyOverhangSelection: next })
  }

  // ── Dropdowns ───────────────────────────────────────────────────────────────
  function _buildSelect(side) {
    const sel = $(`asm-oconn-select-${side}`)
    if (!sel) return
    const cur = side === 'a' ? _sideA() : _sideB()
    const groups = groupOverhangs(_assembly(), (inst) => _designs.resolve(inst))
    let html = `<option value="">— none —</option>`
    for (const g of groups) {
      if (!g.overhangs.length) continue
      html += `<optgroup label="${_escape(g.name)}">`
      for (const o of g.overhangs) {
        html += `<option value="${_escape(encodeOption(g.instanceId, o.id))}">${_escape(o.label)}${o.endTag ? ' ' + o.endTag : ''}</option>`
      }
      html += `</optgroup>`
    }
    sel.innerHTML = html
    sel.value = cur ? encodeOption(cur.instanceId, cur.overhangId) : ''
  }

  function _onSelectChange(side, ev) {
    const picked = decodeOption(ev.target.value)
    _setSide(side, picked ? { ...picked, label: _label(picked.instanceId, picked.overhangId) } : null)
    // subscription re-syncs the dropdown value + icon + button + list highlight
  }

  // ── Connection-type icon picker (button-box + popover) ──────────────────────
  function _initVariantPicker() {
    const box = $('asm-oconn-button-box')
    const pop = $('asm-oconn-popover')
    if (!box || !pop) return
    pop.innerHTML = ''
    for (const v of CT_VARIANTS) {
      const opt = document.createElement('button')
      opt.type = 'button'
      opt.className = 'ct-option'
      opt.dataset.variant = v.id
      opt.title = v.label
      opt.innerHTML = `<div class="ct-tile">${ctTileSvg(v.id, null, null, false, false, false)}</div>`
      opt.addEventListener('click', (e) => {
        e.stopPropagation()
        _variant = v.id
        try { localStorage.setItem(_STORAGE, v.id) } catch { /* ignore */ }
        pop.hidden = true
        _refresh()
      })
      pop.appendChild(opt)
    }
    box.addEventListener('click', (e) => {
      e.stopPropagation()
      if (pop.hidden) {
        const r = box.getBoundingClientRect()
        pop.style.position = 'fixed'
        pop.style.left = `${Math.round(Math.max(8, Math.min(window.innerWidth - 796 - 8, r.left + r.width / 2 - 398)))}px`
        pop.style.top = `${Math.round(r.bottom + 6)}px`
        pop.hidden = false
      } else { pop.hidden = true }
    })
    document.addEventListener('click', (e) => {
      if (pop.hidden) return
      if (pop.contains(e.target) || box.contains(e.target)) return
      pop.hidden = true
    })
  }

  function _refreshIcon() {
    const box = $('asm-oconn-button-box')
    if (!box) return
    const A = _sideA(), B = _sideB()
    const L = A ? endOf(A.overhangId) : null
    const R = B ? endOf(B.overhangId) : null
    const hasA = !!A, hasB = !!B
    const forbidden = hasA && hasB && ctIsForbidden(_variant, L, R)
    box.innerHTML = `<div class="ct-tile">${ctTileSvg(_variant, L, R, forbidden, hasA, hasB)}</div>`
    const pop = $('asm-oconn-popover')
    if (pop) for (const opt of pop.querySelectorAll('.ct-option')) {
      const id = opt.dataset.variant
      opt.innerHTML = `<div class="ct-tile">${ctTileSvg(id, L, R, hasA && hasB && ctIsForbidden(id, L, R), hasA, hasB)}</div>`
      opt.classList.toggle('is-selected', id === _variant)
    }
  }

  // ── Length + Generate button state ──────────────────────────────────────────
  function _refreshControls() {
    const A = _sideA(), B = _sideB()
    const direct = ctIsDirect(_variant), indirect = ctIsIndirect(_variant)
    const lenRow = $('asm-oconn-length-row')
    if (lenRow) lenRow.style.display = (direct || indirect) ? 'none' : ''
    const length = parseFloat($('asm-oconn-length')?.value ?? '')
    const btn = $('asm-oconn-generate')
    if (btn) {
      btn.textContent = direct ? 'Make Complementary' : 'Generate Linker'
      btn.disabled = !canGenerate({ A, B, variant: _variant, length })
    }
    const warn = $('asm-oconn-warning')
    if (warn) {
      const hasBoth = !!A && !!B
      const L = A ? endOf(A.overhangId) : null
      const R = B ? endOf(B.overhangId) : null
      if (hasBoth && A.instanceId === B.instanceId) {
        warn.hidden = false; warn.textContent = 'Both overhangs are on the same part — pick across two parts.'
      } else if (hasBoth && ctIsForbidden(_variant, L, R)) {
        warn.hidden = false; warn.textContent = ctForbiddenReason(_variant, L, R) || 'Invalid polarity for this connection type.'
      } else { warn.hidden = true; warn.textContent = '' }
    }
  }

  function _setStatus(t) { const s = $('asm-oconn-status'); if (s) s.textContent = t ?? '' }

  // ── Create ──────────────────────────────────────────────────────────────────
  async function _onGenerate() {
    const A = _sideA(), B = _sideB()
    if (!A || !B) return
    if (ctIsDirect(_variant)) return _makeComplementary(A, B)
    const length = ctIsIndirect(_variant) ? 0 : parseFloat($('asm-oconn-length')?.value ?? '')
    try {
      await createAssemblyOverhangConnection(connectionBody(_variant, A, B, length))
      _setStatus('Created linker.')
    } catch (err) { _setStatus(`Could not create linker: ${err?.message ?? err}`) }
  }

  async function _makeComplementary(A, B) {
    const ohA = _overhang(A.instanceId, A.overhangId)
    const ohB = _overhang(B.instanceId, B.overhangId)
    if (!ohA || !ohB) return
    if (ohA.sequence) {
      try { await patchInstanceOverhang(B.instanceId, B.overhangId, { sequence: revcomp(ohA.sequence) }) }
      catch (err) { _setStatus(`Could not write complement to B: ${err?.message ?? err}`); return }
    }
    const sdA = ohA.sub_domains?.[0]?.id
    const sdB = ohB.sub_domains?.[0]?.id
    if (!sdA || !sdB) { _setStatus('Sub-domains missing — cannot bind.'); return }
    try {
      await createAssemblyOverhangBinding({
        instance_a_id: A.instanceId, sub_domain_a_id: sdA, overhang_a_id: A.overhangId,
        instance_b_id: B.instanceId, sub_domain_b_id: sdB, overhang_b_id: B.overhangId,
      })
      _setStatus('Created binding.')
    } catch (err) {
      const msg = err?.message ?? String(err)
      _setStatus(msg.toLowerCase().includes('already') ? 'Binding already exists for this pair.' : `Could not create binding: ${msg}`)
    }
  }

  // ── Created linkers + bindings list ─────────────────────────────────────────
  function _rebuildList() {
    const el = $('asm-oconn-list')
    if (!el) return
    const a = _assembly()
    const conns = a?.overhang_connections ?? []
    const binds = a?.overhang_bindings ?? []
    if (!conns.length && !binds.length) {
      el.innerHTML = '<div style="padding:10px;font-size:11px;color:#6e7681;text-align:center">No linkers or bindings yet.</div>'
      return
    }
    const pair = (e) => `${_label(e.instance_a_id, e.overhang_a_id)} ↔ ${_label(e.instance_b_id, e.overhang_b_id)}`
    let html = ''
    for (const c of conns) {
      const sub = `${c.linker_type === 'ds' ? 'dsDNA' : 'ssDNA'} · ${_escape(pair(c))}`
      html += `<div class="asm-oconn-row" data-kind="conn" data-id="${_escape(c.id)}"><div class="asm-oconn-row-main">` +
        `<div class="asm-oconn-row-name">${_escape(c.name || 'linker')}</div><div class="asm-oconn-row-sub">${sub}</div></div>` +
        `<button class="asm-oconn-row-del" data-kind="conn" data-id="${_escape(c.id)}" title="Delete linker">×</button></div>`
    }
    for (const b of binds) {
      html += `<div class="asm-oconn-row" data-kind="binding" data-id="${_escape(b.id)}"><div class="asm-oconn-row-main">` +
        `<div class="asm-oconn-row-name">${_escape(b.name || 'binding')}</div><div class="asm-oconn-row-sub">Binding · ${_escape(pair(b))}</div></div>` +
        `<button class="asm-oconn-row-del" data-kind="binding" data-id="${_escape(b.id)}" title="Delete binding">×</button></div>`
    }
    el.innerHTML = html
  }

  async function _onListClick(ev) {
    const del = ev.target.closest('.asm-oconn-row-del')
    if (del) {
      ev.stopPropagation()
      const { kind, id } = del.dataset
      try {
        if (kind === 'conn') await deleteAssemblyOverhangConnection(id)
        else await deleteAssemblyOverhangBinding(id)
      } catch (err) { _setStatus(`Delete failed: ${err?.message ?? err}`) }
      return
    }
    // Click a linker row → reselect its A/B + variant (part-editor parity).
    const row = ev.target.closest('.asm-oconn-row')
    if (!row || row.dataset.kind !== 'conn') return
    const conn = (_assembly()?.overhang_connections ?? []).find(c => c.id === row.dataset.id)
    if (!conn) return
    const v = ctVariantForConnection(conn)
    if (v) { _variant = v; try { localStorage.setItem(_STORAGE, v) } catch { /* ignore */ } }
    store.setState({ assemblyOverhangSelection: [
      { instanceId: conn.instance_a_id, overhangId: conn.overhang_a_id, label: _label(conn.instance_a_id, conn.overhang_a_id) },
      { instanceId: conn.instance_b_id, overhangId: conn.overhang_b_id, label: _label(conn.instance_b_id, conn.overhang_b_id) },
    ] })
  }

  // ── Render orchestration ─────────────────────────────────────────────────────
  function _refresh() {
    _buildSelect('a')
    _buildSelect('b')
    _refreshIcon()
    _refreshControls()
  }

  function rebuild() {
    const assembly = _assembly()
    _designs.ensure(assembly, () => { if (assembly === _assembly()) rebuild() })
    _refresh()
    _rebuildList()
  }

  // ── Wiring ────────────────────────────────────────────────────────────────────
  _initVariantPicker()
  $('asm-oconn-select-a')?.addEventListener('change', (e) => _onSelectChange('a', e))
  $('asm-oconn-select-b')?.addEventListener('change', (e) => _onSelectChange('b', e))
  $('asm-oconn-length')?.addEventListener('input', _refreshControls)
  $('asm-oconn-generate')?.addEventListener('click', _onGenerate)
  $('asm-oconn-list')?.addEventListener('click', _onListClick)

  store?.subscribe?.((s) => {
    if (s.currentAssembly !== _prevAssembly) {
      _designs.prune((s.currentAssembly?.instances ?? []).map(i => i.id))
      _prevAssembly = s.currentAssembly
      _prevSel = s.assemblyOverhangSelection
      rebuild()
    } else if (s.assemblyOverhangSelection !== _prevSel) {
      _prevSel = s.assemblyOverhangSelection
      _refresh()   // dropdown values + icon + button follow the 3D-tool selection
    }
  })

  return { rebuild }
}
