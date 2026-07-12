/**
 * Assembly right-sidebar "Overhangs" section — lists every overhang across all
 * part instances, grouped under each part, in the style of the Overhangs Manager
 * popup's Side A / Side B lists (`.ohc-list-row` + `.aohc-part-header`).
 *
 * Two-way selection: it shares the `assemblyOverhangSelection` store slice with
 * the 3D overhang-selection tool (see scene/assembly_pointer.js). Clicking a row
 * toggles that overhang in the SAME ordered array the tool writes, so:
 *   - a 3D tool click repaints the matching row here (via the store subscription);
 *   - a row click here drives the 3D green-ring highlight (via the existing
 *     `assemblyOverhangSelection` subscriber in main.js) and the manager prefill.
 *
 * Selected rows are colored by their ORDER in the selection — index 0 = Side A
 * (cyan), index 1 = Side B (magenta), later = generic — mirroring the manager's
 * A/B semantics.
 *
 * Pure helpers (`selectionClass`, `groupOverhangs`, `endTagFor`) are unit-tested
 * in assembly_overhang_list_panel.test.js.
 */

import { initInstanceDesignCache } from './assembly_instance_designs.js'

const _LIST_ID = 'asm-oh-list'

/** 5'/3' end tag from an overhang id suffix (mirrors the popup's `_endTag`). */
export function endTagFor(overhangId) {
  if (typeof overhangId !== 'string') return ''
  if (overhangId.endsWith('_5p')) return "5'"
  if (overhangId.endsWith('_3p')) return "3'"
  return ''
}

/** Selection-order → row CSS class. index 0 = Side A, 1 = Side B, ≥2 = generic. */
export function selectionClass(index) {
  if (index === 0) return 'ct-selected-a'
  if (index === 1) return 'ct-selected-b'
  return 'is-selected'
}

/**
 * Pure: group every instance's overhangs for display.
 * @param {object} assembly — { instances: [...] }
 * @param {(inst:object)=>object|null} resolveDesign — instance → its Design (with .overhangs)
 * @returns {{instanceId:string, name:string, overhangs:{id:string,label:string,endTag:string}[]}[]}
 */
export function groupOverhangs(assembly, resolveDesign) {
  const out = []
  for (const inst of assembly?.instances ?? []) {
    const design = resolveDesign?.(inst) ?? null
    const overhangs = [...(design?.overhangs ?? [])]
      .map(o => ({ id: o.id, label: o.label || o.id, endTag: endTagFor(o.id) }))
      .sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }))
    out.push({ instanceId: inst.id, name: inst.name || inst.id, overhangs })
  }
  return out
}

function _escape(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ))
}

/**
 * @param {object} deps
 * @param {object} deps.store
 * @param {(instanceId:string)=>object|null} [deps.getInstanceDesign] — renderer-cached
 *        per-instance design resolver (sync fast-path; may be null before the
 *        renderer finishes building).
 * @param {(instanceId:string)=>Promise<{design?:object}>} [deps.fetchInstanceDesign] —
 *        async fallback (GET /assembly/instances/{id}/design). Needed because inline
 *        sources are spilled to disk on import, so instances are file-backed and carry
 *        no client-side `source.design`. Mirrors the Overhangs Manager popup's cache.
 */
export function initAssemblyOverhangListPanel({ store, getInstanceDesign, fetchInstanceDesign } = {}) {
  const _collapsed = new Set()          // instanceIds the user collapsed
  const _designs = initInstanceDesignCache({ getInstanceDesign, fetchInstanceDesign })
  let _prevAssembly = undefined
  let _prevSel = undefined

  const _listEl = () => document.getElementById(_LIST_ID)
  const _assembly = () => store?.getState()?.currentAssembly ?? null
  const _selection = () => store?.getState()?.assemblyOverhangSelection ?? []

  const _resolveDesign = (inst) => _designs.resolve(inst)

  function _selIndex(instanceId, overhangId) {
    return _selection().findIndex(s => s.instanceId === instanceId && s.overhangId === overhangId)
  }

  // Toggle into the SHARED ordered selection — byte-identical semantics to
  // assembly_pointer.js `_toggleAssemblyOverhangSelection` (no toast here; the
  // row highlight + 3D ring are the feedback).
  function _toggle(instanceId, overhangId, label) {
    const cur = _selection()
    const idx = cur.findIndex(s => s.instanceId === instanceId && s.overhangId === overhangId)
    const next = idx >= 0
      ? cur.filter((_, i) => i !== idx)
      : [...cur, { instanceId, overhangId, label }]
    store.setState({ assemblyOverhangSelection: next })
  }

  function rebuild() {
    const el = _listEl()
    if (!el) return
    const assembly = _assembly()
    const groups = groupOverhangs(assembly, _resolveDesign)
    // Kick an async fetch for any not-yet-resolvable instance (file-backed parts
    // before the renderer cache is warm); it re-renders when designs arrive.
    _designs.ensure(assembly, () => { if (assembly === _assembly()) rebuild() })
    if (groups.length === 0) {
      el.innerHTML = '<div class="asm-oh-empty">No parts in this assembly.</div>'
      return
    }
    if (groups.every(g => g.overhangs.length === 0)) {
      el.innerHTML = '<div class="asm-oh-empty">No overhangs on any part.</div>'
      return
    }
    let html = ''
    for (const g of groups) {
      if (g.overhangs.length === 0) continue
      const expanded = !_collapsed.has(g.instanceId)
      html +=
        `<button type="button" class="aohc-part-header" data-instance-id="${_escape(g.instanceId)}" aria-expanded="${expanded}">` +
        `<span class="aohc-chevron" aria-hidden="true">▶</span>` +
        `<span>${_escape(g.name)}</span>` +
        `<span class="aohc-part-count">${g.overhangs.length}</span></button>`
      if (!expanded) continue
      for (const o of g.overhangs) {
        html +=
          `<div class="ohc-list-row" data-instance-id="${_escape(g.instanceId)}" data-overhang-id="${_escape(o.id)}">` +
          `<span>${_escape(o.label)}</span>` +
          `<span class="ohc-end-tag">${_escape(o.endTag)}</span></div>`
      }
    }
    el.innerHTML = html
    refreshSelection()
  }

  function refreshSelection() {
    const el = _listEl()
    if (!el) return
    for (const row of el.querySelectorAll('.ohc-list-row')) {
      const idx = _selIndex(row.dataset.instanceId, row.dataset.overhangId)
      row.classList.remove('ct-selected-a', 'ct-selected-b', 'is-selected')
      if (idx >= 0) row.classList.add(selectionClass(idx))
    }
  }

  // One delegated click handler survives innerHTML rebuilds.
  function _onClick(ev) {
    const header = ev.target.closest('.aohc-part-header')
    if (header) {
      const id = header.dataset.instanceId
      if (_collapsed.has(id)) _collapsed.delete(id)
      else _collapsed.add(id)
      rebuild()
      return
    }
    const row = ev.target.closest('.ohc-list-row')
    if (!row) return
    const { instanceId, overhangId } = row.dataset
    const label = row.querySelector('span')?.textContent ?? overhangId
    _toggle(instanceId, overhangId, label)   // subscription repaints selection + 3D ring
  }

  const el = _listEl()
  if (el) el.addEventListener('click', _onClick)

  store?.subscribe?.((s) => {
    if (s.currentAssembly !== _prevAssembly) {
      // currentAssembly ref changes on every assembly mutation — prune caches to
      // the live instance set (keep resolved designs; don't flash+refetch).
      _designs.prune((s.currentAssembly?.instances ?? []).map(i => i.id))
      _prevAssembly = s.currentAssembly
      _prevSel = s.assemblyOverhangSelection
      rebuild()
    } else if (s.assemblyOverhangSelection !== _prevSel) {
      _prevSel = s.assemblyOverhangSelection
      refreshSelection()
    }
  })

  return { rebuild, refreshSelection }
}
