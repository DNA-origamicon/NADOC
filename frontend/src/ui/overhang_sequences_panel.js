/**
 * Overhang sequences panel — collapsible sidebar list of every overhang on the
 * design, with editable Name + Sequence, a "Gen" button (Johnson et al. random
 * sequence), a "Set" button (persist name/sequence), and — for any overhang that
 * participates in a connection (linker / binding / version) — a link icon that
 * opens the Overhang Connections section on that pair with its applied version
 * selected. Clicking a row selects the overhang (so the Strand Animation section
 * can bind to it); selecting a strand elsewhere highlights its matching row(s).
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
 * @param {object} deps.api                — needs generateOverhangRandomSequence/patchOverhang
 * @param {object} deps.overhangNameOverlay — needs setScale(s)
 * @returns {{ rebuild: Function }}
 */
import { showToast } from './toast.js'
import { assembleOverhangSequence, overhangHasSequenceOverride, overhangDomainLength, overhangHasDuplex, overhangDuplexSegments, overhangRcOfPartner } from '../scene/design_queries.js'
import { openConnectionForPair } from './overhang_connections_panel.js'
import { runOverhangGen } from './overhang_gen.js'
import { relatedStrandIds as canonicalRelatedStrandIds } from '../scene/selection_model.js'

// Inline chain-link glyph for the per-row "open this overhang's connection" icon.
const _LINK_SVG =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.72"/>' +
  '<path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>'

/**
 * Pure: the connection PAIR (if any) this overhang participates in. Prefers a
 * direct binding, then a linker, then a connection-version group — returns the
 * partner pair `{ a, b }` to open in the Overhang Connections section, or null
 * when the overhang has no connection at all. Exported for unit testing.
 */
export function connectionPairForOverhang(design, ovhgId) {
  const involves = (e) => e.overhang_a_id === ovhgId || e.overhang_b_id === ovhgId
  const hit =
    (design?.overhang_bindings    ?? []).find(involves) ||
    (design?.overhang_connections ?? []).find(involves) ||
    (design?.connection_versions  ?? []).find(involves)
  return hit ? { a: hit.overhang_a_id, b: hit.overhang_b_id } : null
}

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
  return (design?.overhangs ?? []).filter(o => !o.auxiliary_endpoint)
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
  return new Set(canonicalRelatedStrandIds(state))
}

// Duplex coverage colors for the sidebar preview line.
const _DUPLEX_COLOR = { paired: '#3fb950', mismatch: '#d29922', toehold: '#8b949e' }

/** The duplex-graph driver overhang id for a duplex (Q4). */
function _driverOverhangId(dx) {
  return dx.driver === 'right' ? dx.right.overhang_id : dx.left.overhang_id
}

/** A monospace line of colored spans showing an overhang's duplex coverage
 *  (paired / mismatch / toehold), or null when it has no bases in a duplex. */
function _duplexPreviewLine(design, overhangId) {
  const segs = overhangDuplexSegments(design, overhangId)
  if (!segs.length) return null
  const line = document.createElement('div')
  line.style.cssText = 'grid-column:1 / -1;white-space:nowrap;letter-spacing:.06em;' +
    'font-family:monospace;font-size:11px;margin:0 0 4px 2px'
  // ▶ marks the DRIVER overhang (Q4) — the side whose helix hosts the duplex.
  const dx = (design?.duplexes ?? []).find(
    d => d.left.overhang_id === overhangId || d.right.overhang_id === overhangId)
  if (dx && _driverOverhangId(dx) === overhangId) {
    const mark = document.createElement('span')
    mark.textContent = '▶ '
    mark.style.color = '#8b949e'
    mark.title = 'Driver — this overhang\'s helix hosts the duplex'
    line.appendChild(mark)
  }
  for (const s of segs) {
    const span = document.createElement('span')
    span.textContent = s.text
    span.style.color = _DUPLEX_COLOR[s.kind] ?? '#c9d1d9'
    line.appendChild(span)
  }
  return line
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
    hdr.innerHTML = '<span>Name</span><span>Sequence</span><span></span><span></span><span title="Open this overhang\'s connection (link to the Overhang Connections section)">Link</span>'
    list.appendChild(hdr)

    for (const ovhg of overhangs) {
      const row = document.createElement('div')
      row.style.cssText = 'display:grid;grid-template-columns:1fr 1fr auto auto auto;gap:4px;' +
                          'margin-bottom:4px;align-items:center;padding:2px 4px;' +
                          'border-radius:3px;border-left:2px solid transparent;transition:background 0.1s'
      row.dataset.strandId = ovhg.strand_id
      row.dataset.overhangId = ovhg.id
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
      // Length the bases must fill = the backing domain's current length (it grows
      // when the user drags the overhang end). Passing it makes the now-undefined
      // 3' positions render as 'N' instead of leaving the row looking fully defined.
      const domainLen = overhangDomainLength(design, ovhg.id) ?? undefined
      const seqInput = document.createElement('input')
      seqInput.type        = 'text'
      seqInput.placeholder = 'Sequence…'
      seqInput.value       = assembleOverhangSequence(ovhg, domainLen)
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
        // Same Gen flow as the Connections panel: coordinates with the connected
        // partner (RC / new-pair / override choice when both are sequenced).
        const design0 = store.getState().currentDesign
        const pair = connectionPairForOverhang(design0, ovhg.id)
        const partnerId = pair ? (pair.a === ovhg.id ? pair.b : pair.a) : null
        try {
          await runOverhangGen(ovhg.id, partnerId, {
            api: {
              generateOverhangRandomSequence: api.generateOverhangRandomSequence,
              patchOverhang: api.patchOverhang,
            },
            getSeq: (id) => store.getState().currentDesign?.overhangs?.find(o => o.id === id)?.sequence ?? null,
            rcOfPartner: (targetId, sourceId) => overhangRcOfPartner(store.getState().currentDesign, targetId, sourceId),
          })
        } catch (err) {
          showToast(err?.message ?? String(err))
        } finally {
          genBtn.disabled = false
        }
      })

      function _syncGenBtn() {
        const v = seqInput.value.trim()
        const connected = !!connectionPairForOverhang(store.getState().currentDesign, ovhg.id)
        // Hide Gen for per-sub-domain overhangs (it would clobber the top-level
        // field). Otherwise show it when unsequenced OR when connected — so the
        // pair/RC/override choice is reachable even after a sequence is set.
        genBtn.style.display = (!perSubDomain && ((!v || /^n+$/i.test(v)) || connected)) ? '' : 'none'
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

      // Link icon — shown only when this overhang participates in a connection
      // (linker / binding / version). Clicking opens the Overhang Connections
      // section on that pair and selects its applied version. Bind/Unbind state
      // is NOT touched here — that lives entirely in the Connections section.
      const linkWrap = document.createElement('span')
      const pair = connectionPairForOverhang(design, ovhg.id)
      if (!pair) {
        linkWrap.style.cssText = 'min-width:54px;display:inline-block;color:#484f58;font-size:10px;text-align:center'
        linkWrap.textContent = '—'
      } else {
        const linkBtn = document.createElement('button')
        linkBtn.innerHTML = _LINK_SVG
        const partnerId = pair.a === ovhg.id ? pair.b : pair.a
        const partner = overhangs.find(o => o.id === partnerId)
        const partnerLabel = partner?.label || partner?.id || partnerId
        linkBtn.title = `Open connection with ${partnerLabel}`
        linkBtn.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;' +
          'padding:2px 8px;background:#161b22;border:1px solid #2f81f7;border-radius:4px;' +
          'color:#2f81f7;cursor:pointer'
        linkBtn.addEventListener('click', (e) => {
          e.stopPropagation()
          openConnectionForPair(pair.a, pair.b)
        })
        linkWrap.appendChild(linkBtn)
      }

      row.appendChild(nameInput)
      row.appendChild(seqInput)
      row.appendChild(genBtn)
      row.appendChild(saveBtn)
      row.appendChild(linkWrap)
      list.appendChild(row)

      // If this overhang participates in a duplex, show a coverage preview line
      // below the row: paired (green) / mismatch (amber) / toehold (grey), read
      // from the register-bearing graph (design.duplexes).
      if (overhangHasDuplex(design, ovhg.id)) {
        const prev = _duplexPreviewLine(design, ovhg.id)
        if (prev) list.appendChild(prev)
      }
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
    } else if (newState.selection !== prevState.selection) {
      _updateHighlight()
    }
  })

  return { rebuild: _rebuildPanel }
}
