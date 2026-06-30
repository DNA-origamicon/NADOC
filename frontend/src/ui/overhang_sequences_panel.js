/**
 * Overhang sequences panel — collapsible sidebar list of every overhang on the
 * design, with editable Name + Sequence, a "Gen" button (Johnson et al. random
 * sequence), a "Set" button (persist name/sequence), and a Bind/Unbind toggle
 * for overhangs that belong to an OverhangBinding pair. Clicking a row selects
 * the overhang (so the Strand Animation section can bind to it); selecting a
 * strand elsewhere highlights its matching row(s).
 *
 * Stateful: owns DOM, the label-size slider, a row-by-strand highlight map, and
 * a store subscription. So it's a factory — pass dependencies in. The two pure
 * cores (`liveOverhangs` defensive filter, `selectedStrandIds` collection) are
 * exported + unit-tested in overhang_sequences_panel.test.js; the DOM build
 * stays here.
 *
 * Extracted verbatim from main.js's `_initOverhangPanel` IIFE.
 *
 * @param {object} deps
 * @param {object} deps.store              — Zustand-style store (getState/setState/subscribe)
 * @param {object} deps.selectionManager   — needs selectOverhang(overhangId)
 * @param {object} deps.api                — needs generateOverhangRandomSequence/patchOverhang/patchOverhangBinding
 * @param {object} deps.overhangNameOverlay — needs setScale(s)
 * @returns {{ rebuild: Function }}
 */
import { showToast } from './toast.js'
import { assembleOverhangSequence, overhangHasSequenceOverride } from '../scene/design_queries.js'

/**
 * Pure: overhangs whose backing strand is still live (or that have no strand).
 *
 * Defensive filter — hides overhangs whose backing strand has been deleted but
 * whose OverhangSpec wasn't cascaded out, so the user can't pick ghost
 * overhangs in the binding / linker flows.
 *
 * @param {object} design — Design with .strands / .overhangs
 * @returns {object[]} the live overhangs
 */
export function liveOverhangs(design) {
  const liveStrandIds = new Set((design?.strands ?? []).map(s => s.id))
  return (design?.overhangs ?? [])
    .filter(o => !o.strand_id || liveStrandIds.has(o.strand_id))
}

/**
 * Pure: overhangs ordered for display — alphanumeric by Name (label), ties broken
 * by Sequence, then id. Natural numeric ordering (oh2 before oh10), case-insensitive.
 * Returns a new array; does not mutate the input.
 *
 * @param {object[]} overhangs
 * @returns {object[]}
 */
export function sortOverhangsForDisplay(overhangs) {
  const cmp = (a, b) => (a ?? '').localeCompare(b ?? '', undefined, { numeric: true, sensitivity: 'base' })
  return [...overhangs].sort((a, b) =>
    cmp(a.label, b.label) || cmp(a.sequence, b.sequence) || cmp(a.id, b.id),
  )
}

/**
 * Pure: all strand IDs currently selected (single nucleotide, multi-strand, or
 * multi-domain selection), as a Set.
 *
 * @param {object} state — store state slice
 * @returns {Set<string>}
 */
export function selectedStrandIds(state) {
  const ids = new Set()
  if (state?.selectedObject?.data?.strand_id) ids.add(state.selectedObject.data.strand_id)
  for (const id of state?.multiSelectedStrandIds ?? []) ids.add(id)
  for (const d of state?.multiSelectedDomainIds ?? []) ids.add(d.strandId)
  return ids
}

export function initOverhangSequencesPanel({ store, selectionManager, api, overhangNameOverlay }) {
  const panel      = document.getElementById('overhang-panel')
  const list       = document.getElementById('overhang-list')
  const heading    = document.getElementById('overhang-panel-heading')
  const arrow      = document.getElementById('overhang-panel-arrow')
  const sizeRow    = document.getElementById('overhang-label-size-row')
  const sizeSlider = document.getElementById('overhang-label-size')
  const sizeVal    = document.getElementById('overhang-label-size-val')
  if (!panel || !list) return { rebuild: () => {} }

  if (sizeSlider) {
    sizeSlider.addEventListener('input', () => {
      const s = parseFloat(sizeSlider.value)
      if (sizeVal) sizeVal.textContent = s.toFixed(1)
      overhangNameOverlay.setScale(s)
    })
  }

  // Default to collapsed on load. The label-size slider lives inside the
  // collapse along with the overhang list.
  let _collapsed = true

  function _applyCollapse() {
    list.style.display = _collapsed ? 'none' : ''
    if (sizeRow) sizeRow.style.display = _collapsed ? 'none' : ''
    arrow.classList.toggle('is-collapsed', _collapsed)
  }
  _applyCollapse()

  if (heading) {
    heading.addEventListener('click', () => {
      _collapsed = !_collapsed
      _applyCollapse()
      if (!_collapsed) _rebuildPanel(store.getState().currentDesign)
    })
  }

  const iStyle = 'background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
                 'color:#c9d1d9;padding:2px 5px;font-family:var(--font-ui);font-size:11px;'

  // strand_id → array of row elements (one overhang may share a strand)
  let _rowsByStrandId = {}

  function _rebuildPanel(design) {
    const overhangs = sortOverhangsForDisplay(liveOverhangs(design))
    _rowsByStrandId = {}
    if (_collapsed) return

    list.innerHTML = ''

    if (!overhangs.length) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#484f58;font-size:11px;padding:4px 0'
      empty.textContent   = 'No overhangs on this design.'
      list.appendChild(empty)
      return
    }

    // Column header
    const hdr = document.createElement('div')
    hdr.style.cssText = 'display:grid;grid-template-columns:1fr 1fr auto auto auto;gap:4px;' +
                         'margin-bottom:4px;font-size:var(--text-xs);color:#484f58;text-transform:uppercase;letter-spacing:.05em'
    hdr.innerHTML = '<span>Name</span><span>Sequence</span><span></span><span></span><span title="Toggle direct binding state for the pair this overhang belongs to (empty if unpaired)">Bind</span>'
    list.appendChild(hdr)

    // Index bindings by overhang id once per rebuild (small list — linear
    // scan is fine).
    const allBindings = design?.overhang_bindings ?? []

    for (const ovhg of overhangs) {
      const row = document.createElement('div')
      row.style.cssText = 'display:grid;grid-template-columns:1fr 1fr auto auto auto;gap:4px;' +
                          'margin-bottom:4px;align-items:center;padding:2px 4px;' +
                          'border-radius:3px;border-left:2px solid transparent;transition:background 0.1s'
      row.dataset.strandId = ovhg.strand_id
      row.style.cursor = 'pointer'

      // Row click selects this overhang (so the Strand Animation section can
      // bind to it) and highlights ONLY the overhang domain in 3D — not the
      // whole strand. Clicks on the inputs/buttons keep their own behavior.
      row.addEventListener('click', (e) => {
        if (e.target.closest('input,button')) return
        selectionManager.selectOverhang(ovhg.id)
      })

      // Register for highlight tracking
      if (!_rowsByStrandId[ovhg.strand_id]) _rowsByStrandId[ovhg.strand_id] = []
      _rowsByStrandId[ovhg.strand_id].push(row)

      const nameInput = document.createElement('input')
      nameInput.type        = 'text'
      nameInput.placeholder = 'Name…'
      nameInput.value       = ovhg.label ?? ''
      nameInput.title       = ovhg.id
      nameInput.style.cssText = iStyle + 'width:100%;box-sizing:border-box'

      // Show the ASSEMBLED sequence (sub-domain overrides → parent → N), not just
      // the top-level field — so a split / per-sub-domain-sequenced overhang shows
      // its real bases instead of blank. When the sequence is authored per
      // sub-domain, the single field can't represent it for editing → read-only
      // (edit it in the Domain Designer).
      const perSubDomain = overhangHasSequenceOverride(ovhg)
      const seqInput = document.createElement('input')
      seqInput.type        = 'text'
      seqInput.placeholder = 'Sequence…'
      seqInput.value       = assembleOverhangSequence(ovhg)
      seqInput.readOnly    = perSubDomain
      if (perSubDomain) seqInput.title = 'Sequenced per sub-domain — edit in the Domain Designer'
      seqInput.style.cssText = iStyle + 'width:100%;box-sizing:border-box;letter-spacing:.05em' +
        (perSubDomain ? ';opacity:.7;cursor:not-allowed' : '')

      for (const inp of [nameInput, seqInput]) {
        inp.addEventListener('keydown', e => e.stopPropagation())
        inp.addEventListener('focus', () => selectionManager.selectOverhang(ovhg.id))
      }

      const genBtn = document.createElement('button')
      genBtn.textContent = 'Gen'
      genBtn.title       = 'Generate random sequence (Johnson et al.)'
      genBtn.style.cssText = 'padding:2px 7px;background:#162420;border:1px solid #3fb950;border-radius:4px;' +
                             'color:#3fb950;font-size:11px;cursor:pointer;white-space:nowrap'
      genBtn.addEventListener('click', async () => {
        genBtn.disabled = true
        showToast('Using Johnson et al. overhang algorithm — DOI: 10.1021/acs.nanolett.9b02786')
        await api.generateOverhangRandomSequence(ovhg.id)
        genBtn.disabled = false
      })

      function _syncGenBtn() {
        const v = seqInput.value.trim()
        // Hide Gen for per-sub-domain overhangs (it would clobber the top-level
        // field, which is not what drives their sequence) and once a real
        // sequence is present.
        genBtn.style.display = (!perSubDomain && (!v || /^n+$/i.test(v))) ? '' : 'none'
      }
      _syncGenBtn()
      seqInput.addEventListener('input', _syncGenBtn)

      const saveBtn = document.createElement('button')
      saveBtn.textContent   = 'Set'
      saveBtn.style.cssText = 'padding:2px 7px;background:#1f6feb;border:none;border-radius:4px;' +
                              'color:#fff;font-size:11px;cursor:pointer;white-space:nowrap'
      saveBtn.addEventListener('click', async () => {
        // For per-sub-domain overhangs the displayed (assembled) sequence is
        // read-only — only the label is editable here; the sequence is owned by
        // the sub-domains (Domain Designer), so don't push it to the top-level field.
        const patch = perSubDomain
          ? { label: nameInput.value.trim() || null }
          : { sequence: seqInput.value.trim().toUpperCase() || null,
              label:    nameInput.value.trim() || null }
        await api.patchOverhang(ovhg.id, patch)
      })

      // ⚠️ TECH DEBT / FOR REVIEW (flagged 2026-06-03): the Bind/Unbind button drives
      // the LEGACY OverhangBinding pair model (overhang_a_id/overhang_b_id + `bound`
      // flag, toggled via api.patchOverhangBinding). This whole approach is being
      // superseded by oh_binder strands (StrandType.OH_BINDER + Domain.binds_overhang_id).
      // Do NOT extend it; it's slated for removal once the binder migration completes.
      // See memory project_oh_binder + project_tech_debt.
      //
      // Bind/Unbind toggle — visible only when this overhang is in an
      // OverhangBinding pair. Click toggles `bound` server-side via
      // patchOverhangBinding; the cluster-pose move (or restore) happens
      // automatically there. Multiple bindings on one OH are rare —
      // showing the FIRST binding's state, click cycles its bound flag.
      const bindWrap = document.createElement('span')
      const myBindings = allBindings.filter(b =>
        b.overhang_a_id === ovhg.id || b.overhang_b_id === ovhg.id,
      )
      if (myBindings.length === 0) {
        bindWrap.style.cssText = 'min-width:54px;display:inline-block;color:#484f58;font-size:10px;text-align:center'
        bindWrap.textContent = '—'
      } else {
        const b = myBindings[0]
        const bindBtn = document.createElement('button')
        bindBtn.textContent = b.bound ? 'Unbind' : 'Bind'
        const partnerId = b.overhang_a_id === ovhg.id ? b.overhang_b_id : b.overhang_a_id
        const partner = overhangs.find(o => o.id === partnerId)
        const partnerLabel = partner?.label || partner?.id || partnerId
        bindBtn.title = `Pair ${b.name ?? b.id.slice(0, 6)} with ${partnerLabel} (${b.bound ? 'bound' : 'unbound'})`
        bindBtn.style.cssText = 'padding:2px 7px;background:' +
          (b.bound ? '#1f2a36' : '#162420') +
          ';border:1px solid ' + (b.bound ? '#5394e0' : '#3fb950') +
          ';border-radius:4px;color:' + (b.bound ? '#5394e0' : '#3fb950') +
          ';font-size:11px;cursor:pointer;white-space:nowrap'
        bindBtn.addEventListener('click', async () => {
          bindBtn.disabled = true
          try {
            await api.patchOverhangBinding(b.id, { bound: !b.bound })
          } catch (err) {
            showToast(err?.message || String(err))
          } finally {
            bindBtn.disabled = false
          }
        })
        bindWrap.appendChild(bindBtn)
      }

      row.appendChild(nameInput)
      row.appendChild(seqInput)
      row.appendChild(genBtn)
      row.appendChild(saveBtn)
      row.appendChild(bindWrap)
      list.appendChild(row)
    }

    // Apply highlight for whatever is currently selected
    _updateHighlight()
  }

  function _updateHighlight() {
    const selected = selectedStrandIds(store.getState())
    for (const [strandId, rows] of Object.entries(_rowsByStrandId)) {
      const active = selected.has(strandId)
      for (const row of rows) {
        row.style.background  = active ? '#1e3a5f' : ''
        row.style.borderLeft  = active ? '2px solid #58a6ff' : '2px solid transparent'
      }
    }
  }

  store.subscribe((newState, prevState) => {
    if (newState.currentDesign !== prevState.currentDesign) {
      _rebuildPanel(newState.currentDesign)
    } else if (
      newState.selectedObject         !== prevState.selectedObject         ||
      newState.multiSelectedStrandIds !== prevState.multiSelectedStrandIds ||
      newState.multiSelectedDomainIds !== prevState.multiSelectedDomainIds
    ) {
      _updateHighlight()
    }
  })

  return { rebuild: _rebuildPanel }
}
