/**
 * strands_spreadsheet.js — Strand Spreadsheet Panel (cadnano editor)
 *
 * 1:1 port of frontend/src/ui/spreadsheet.js for the cadnano-editor page.
 * Same columns, same toggles, same cell builders, same sort order.
 *
 * Columns (all toggle-able except Start/End):
 *   Start | End | 5' Overhang | Sequence | 3' Overhang | Group | Color | Length | Notes
 */

import { patchStrand, patchOverhang } from './api.js'

// ── Column definitions ────────────────────────────────────────────────────

const COLUMNS = [
  { key: 'start',    label: 'Start',       toggleable: false, editable: false },
  { key: 'end',      label: 'End',         toggleable: false, editable: false },
  { key: 'ovhg_5p',  label: "5' Overhang", toggleable: true,  editable: true  },
  { key: 'sequence',  label: 'Sequence',    toggleable: true,  editable: false },
  { key: 'ovhg_3p',  label: "3' Overhang", toggleable: true,  editable: true  },
  { key: 'group',     label: 'Group',       toggleable: true,  editable: false },
  { key: 'color',     label: 'Color',       toggleable: true,  editable: false },
  { key: 'length',    label: 'Length',      toggleable: true,  editable: false },
  { key: 'notes',     label: 'Notes',       toggleable: true,  editable: true  },
]

const LS_HEIGHT_KEY  = 'editor_spreadsheet_height'
const LS_COLS_KEY    = 'editor_spreadsheet_cols'
const LS_OPEN_KEY    = 'editor_spreadsheet_open'

const MIN_HEIGHT = 28   // tab only
const TAB_HEIGHT = 28
const MAX_HEIGHT_OFFSET = 60  // px above viewport bottom (leaves room for status bar)

// Staple palette (mirrors pathview.js / helix_renderer.js)
const STAPLE_PALETTE = [
  '#ff6b6b', '#ffd93d', '#6bcb77', '#f9844a',
  '#a29bfe', '#ff9ff3', '#00cec9', '#e17055',
  '#74b9ff', '#55efc4', '#fdcb6e', '#d63031',
]

function paletteColor(strandIndex) {
  return STAPLE_PALETTE[strandIndex % STAPLE_PALETTE.length]
}

/** Format a strand endpoint as "label[bp]" using the 5' or 3' terminal domain. */
function strandEndpoint(strand, end, helixIndex) {
  if (!strand.domains?.length) return '—'
  const dom = end === '5p' ? strand.domains[0] : strand.domains[strand.domains.length - 1]
  const bp = end === '5p' ? dom.start_bp : dom.end_bp
  const label = helixIndex?.[dom.helix_id] ?? dom.helix_id
  return `${label}[${bp}]`
}

// ── Helpers ───────────────────────────────────────────────────────────────

function domainLength(domain) {
  return Math.abs(domain.end_bp - domain.start_bp) + 1
}

function strandLength(strand, design) {
  const helixById = Object.fromEntries((design?.helices ?? []).map(h => [h.id, h]))
  return strand.domains.reduce((sum, d) => {
    const helix = helixById[d.helix_id]
    const lo = Math.min(d.start_bp, d.end_bp)
    const hi = Math.max(d.start_bp, d.end_bp)
    const skipDelta = helix?.loop_skips
      ?.filter(ls => ls.bp_index >= lo && ls.bp_index <= hi)
      ?.reduce((s, ls) => s + ls.delta, 0) ?? 0
    return sum + domainLength(d) + skipDelta
  }, 0)
}

function terminalOverhang(strand, design, which) {
  const domain = which === '5p' ? strand.domains[0] : strand.domains[strand.domains.length - 1]
  if (!domain?.overhang_id) return null
  return (design.overhangs ?? []).find(o => o.id === domain.overhang_id) ?? null
}

function effectiveColor(strand, strandIndex) {
  if (strand.strand_type === 'scaffold') return '#29b6f6'
  if (strand.color) return strand.color
  return paletteColor(strandIndex)
}

function _strandDisplaySequence(strand, design) {
  const extensions = design?.extensions ?? []
  const ext5 = extensions.find(e => e.strand_id === strand.id && e.end === 'five_prime')
  const ext3 = extensions.find(e => e.strand_id === strand.id && e.end === 'three_prime')
  const hasExtensions = !!(ext5 || ext3)

  if (!strand.sequence && !hasExtensions) return null

  let result = strand.sequence ?? ''

  function _extBracket(ext) {
    const s = (ext.sequence ?? '').toUpperCase()
    const m = (ext.modification ?? '').toUpperCase()
    if (s && m) return `[${s}/${m}]`
    if (s)      return `[${s}]`
    return              `[/${m}]`
  }
  const prefixLen = ext5 ? _extBracket(ext5).length : 0
  if (ext5) result = _extBracket(ext5) + result
  if (ext3) result = result + _extBracket(ext3)

  // Inject crossover extra-base brackets at each inter-domain junction.
  const crossovers = design?.crossovers ?? []
  if (crossovers.length && strand.domains?.length > 1) {
    const domains = strand.domains
    let charOffset = 0
    let insertions = 0

    for (let i = 0; i < domains.length - 1; i++) {
      const d      = domains[i]
      const domLen = Math.abs(d.end_bp - d.start_bp) + 1
      charOffset  += domLen

      const junctionBp = d.direction === 'FORWARD' ? d.end_bp : d.start_bp
      const nextD      = domains[i + 1]

      const xo = crossovers.find(x => {
        const matchA = x.half_a.helix_id === d.helix_id &&
                       x.half_a.index    === junctionBp &&
                       x.half_a.strand   === d.direction &&
                       x.half_b.helix_id === nextD.helix_id &&
                       x.half_b.strand   === nextD.direction
        const matchB = x.half_b.helix_id === d.helix_id &&
                       x.half_b.index    === junctionBp &&
                       x.half_b.strand   === d.direction &&
                       x.half_a.helix_id === nextD.helix_id &&
                       x.half_a.strand   === nextD.direction
        return matchA || matchB
      })

      if (xo?.extra_bases) {
        const bracket = `[${xo.extra_bases}]`
        const pos     = prefixLen + charOffset + insertions
        result        = result.slice(0, pos) + bracket + result.slice(pos)
        insertions   += bracket.length
      }
    }
  }

  return result || null
}

function sortedStrands(design) {
  const strands  = design?.strands ?? []
  const scaffold = strands.filter(s => s.strand_type === 'scaffold')
  const staples  = strands.filter(s => s.strand_type !== 'scaffold')
  const withMeta = staples.map((s, idx) => ({
    strand: s,
    color:  effectiveColor(s, idx),
    length: strandLength(s, design),
  }))
  withMeta.sort((a, b) => {
    if (a.color < b.color) return -1
    if (a.color > b.color) return 1
    return a.length - b.length
  })
  return [...scaffold, ...withMeta.map(m => m.strand)]
}

// ── Context menu ──────────────────────────────────────────────────────────

let _activeCtxMenu = null

function _removeCtxMenu() {
  if (_activeCtxMenu) { _activeCtxMenu.remove(); _activeCtxMenu = null }
}

// ── Module init ───────────────────────────────────────────────────────────

/**
 * @param {object} opts
 * @param {function} opts.onSelectStrand  — (strandId) => void; select strand in pathview
 * @param {function} opts.onSelectionChange — (strandIds) => void; broadcast selection
 */
export function initStrandsSpreadsheet({ onSelectStrand, onSelectionChange } = {}) {
  const panel     = document.getElementById('spreadsheet-panel')
  const tab       = document.getElementById('spreadsheet-tab')
  const arrow     = document.getElementById('spreadsheet-arrow')
  const body      = document.getElementById('spreadsheet-body')
  const theadRow  = document.getElementById('spreadsheet-thead-row')
  const tbody     = document.getElementById('spreadsheet-tbody')
  const toggleBar = document.getElementById('spreadsheet-col-toggles')
  const grip      = document.getElementById('spreadsheet-drag-grip')

  if (!panel || !tab || !body) return { update() {}, setSelectedStrands() {}, toggle() {} }

  // ── Track selected strand IDs (from pathview) ──────────────────
  let _selectedStrandIds = new Set()
  let _design = null

  // ── Persistent column visibility ──────────────────────────────────
  let hiddenCols = new Set()
  try {
    const saved = JSON.parse(localStorage.getItem(LS_COLS_KEY) ?? '[]')
    hiddenCols = new Set(saved)
  } catch (_) { /* ignore */ }

  function saveHiddenCols() {
    localStorage.setItem(LS_COLS_KEY, JSON.stringify([...hiddenCols]))
  }

  // ── Build column toggle checkboxes in tab ─────────────────────────
  for (const col of COLUMNS) {
    if (!col.toggleable) continue
    const label = document.createElement('label')
    label.className = 'sheet-col-toggle'
    const cb = document.createElement('input')
    cb.type    = 'checkbox'
    cb.checked = !hiddenCols.has(col.key)
    cb.addEventListener('change', () => {
      if (cb.checked) hiddenCols.delete(col.key)
      else            hiddenCols.add(col.key)
      saveHiddenCols()
      _rebuildTable()
    })
    label.appendChild(cb)
    label.appendChild(document.createTextNode(col.label))
    toggleBar.appendChild(label)
  }

  // ── Panel open/close state ────────────────────────────────────────
  let isOpen = false
  try { isOpen = JSON.parse(localStorage.getItem(LS_OPEN_KEY) ?? 'false') } catch (_) {}

  function setOpen(open) {
    isOpen = open
    body.style.display  = open ? 'block' : 'none'
    arrow.textContent   = open ? '▼' : '▶'
    localStorage.setItem(LS_OPEN_KEY, JSON.stringify(open))
    if (open) _rebuildTable()
  }

  setOpen(isOpen)

  // ── Panel height (for drag-resize) ────────────────────────────────
  let panelHeight = 200
  try { panelHeight = parseInt(localStorage.getItem(LS_HEIGHT_KEY) ?? '200', 10) } catch (_) {}

  function applyHeight(h) {
    const maxH = window.innerHeight - TAB_HEIGHT - MAX_HEIGHT_OFFSET
    panelHeight = Math.max(TAB_HEIGHT + 60, Math.min(h, maxH))
    body.style.height = (panelHeight - TAB_HEIGHT) + 'px'
    localStorage.setItem(LS_HEIGHT_KEY, String(panelHeight))
  }

  if (isOpen) applyHeight(panelHeight)

  // ── Tab click → toggle; drag grip → resize ────────────────────────
  let dragging = false
  let dragStartY = 0
  let dragStartH = 0

  grip.addEventListener('pointerdown', e => {
    e.stopPropagation()
    dragging    = true
    dragStartY  = e.clientY
    dragStartH  = isOpen ? panelHeight : TAB_HEIGHT
    grip.setPointerCapture(e.pointerId)
    document.body.style.cursor = 'ns-resize'
  })

  grip.addEventListener('pointermove', e => {
    if (!dragging) return
    // Bottom-anchored: dragging up (negative delta) → increase height
    const delta = dragStartY - e.clientY
    const newH  = dragStartH + delta
    if (newH > TAB_HEIGHT + 30 && !isOpen) {
      setOpen(true)
    } else if (newH <= TAB_HEIGHT + 10 && isOpen) {
      setOpen(false)
      return
    }
    if (isOpen) applyHeight(newH)
  })

  grip.addEventListener('pointerup', () => {
    dragging = false
    document.body.style.cursor = ''
  })

  tab.addEventListener('click', e => {
    if (e.target === grip || e.target.closest('#spreadsheet-col-toggles')) return
    if (dragging) return
    const wasOpen = isOpen
    setOpen(!wasOpen)
    if (!wasOpen && isOpen) applyHeight(panelHeight)
  })

  // ── Build table header ────────────────────────────────────────────
  function _rebuildHeader() {
    theadRow.innerHTML = ''
    for (const col of COLUMNS) {
      if (col.toggleable && hiddenCols.has(col.key)) continue
      const th = document.createElement('th')
      th.textContent = col.label
      if (col.key === 'start' || col.key === 'end') th.className = 'sheet-col-endpoint'
      theadRow.appendChild(th)
    }
  }

  // ── Build table body ──────────────────────────────────────────────
  function _rebuildTable() {
    if (!isOpen) return
    _rebuildHeader()

    const design = _design
    tbody.innerHTML = ''
    if (!design?.strands?.length) return

    const strands = sortedStrands(design)
    const helixIndex = Object.fromEntries((design.helices ?? []).map((h, i) => [h.id, i]))

    strands.forEach((strand, idx) => {
      const isScaffold = strand.strand_type === 'scaffold'
      const color      = effectiveColor(strand, idx)
      const ovhg5p     = terminalOverhang(strand, design, '5p')
      const ovhg3p     = terminalOverhang(strand, design, '3p')

      const tr = document.createElement('tr')
      if (isScaffold)                          tr.classList.add('sheet-scaffold')
      if (_selectedStrandIds.has(strand.id))   tr.classList.add('sheet-selected')

      // Left-click → select strand in pathview
      tr.addEventListener('click', e => {
        if (e.target.tagName === 'INPUT') return
        onSelectStrand?.(strand.id)
      })

      for (const col of COLUMNS) {
        if (col.toggleable && hiddenCols.has(col.key)) continue
        const td = document.createElement('td')

        switch (col.key) {
          case 'start': {
            td.className = 'sheet-col-endpoint'
            td.textContent = strandEndpoint(strand, '5p', helixIndex)
            td.title = strand.id
            break
          }
          case 'end': {
            td.className = 'sheet-col-endpoint'
            td.textContent = strandEndpoint(strand, '3p', helixIndex)
            break
          }
          case 'ovhg_5p': {
            const d5 = strand.domains[0]
            td.appendChild(_makeOverhangCell(ovhg5p, d5 ? domainLength(d5) : 0))
            break
          }
          case 'sequence': {
            const displaySeq = _strandDisplaySequence(strand, design)
            if (displaySeq) {
              const span = document.createElement('span')
              span.className = 'sheet-seq'
              span.textContent = displaySeq.length > 40 ? displaySeq.slice(0, 38) + '…' : displaySeq
              span.title = displaySeq
              td.appendChild(span)
            } else {
              const len = strandLength(strand, design)
              const span = document.createElement('span')
              span.className = 'sheet-seq-none'
              span.textContent = `N\xd7${len}`
              td.appendChild(span)
            }
            break
          }
          case 'ovhg_3p': {
            const d3 = strand.domains[strand.domains.length - 1]
            td.appendChild(_makeOverhangCell(ovhg3p, d3 ? domainLength(d3) : 0))
            break
          }
          case 'group': {
            // Group column — display-only in the editor (no group system in editorStore)
            td.textContent = '—'
            break
          }
          case 'color': {
            td.appendChild(_makeColorCell(strand, color))
            break
          }
          case 'length': {
            td.textContent = strandLength(strand, design)
            break
          }
          case 'notes': {
            td.appendChild(_makeNotesCell(strand))
            break
          }
        }

        tr.appendChild(td)
      }

      tbody.appendChild(tr)
    })
  }

  // ── Color picker cell ─────────────────────────────────────────────
  function _makeColorCell(strand, currentColor) {
    const input = document.createElement('input')
    input.type      = 'color'
    input.className = 'sheet-color-input'
    input.value     = currentColor
    input.title     = 'Click to change strand color'

    input.addEventListener('click', e => e.stopPropagation())

    input.addEventListener('change', async () => {
      const hex = input.value
      await patchStrand(strand.id, { color: hex })
    })

    return input
  }

  // ── Overhang editable cell ────────────────────────────────────────
  function _makeOverhangCell(ovhg, overhangLen) {
    if (!ovhg) {
      const span = document.createElement('span')
      span.className   = 'sheet-seq-none'
      span.textContent = 'not available'
      return span
    }

    const input = document.createElement('input')
    input.type        = 'text'
    input.className   = 'sheet-cell-input'
    input.value       = ovhg.sequence ?? ''
    input.placeholder = overhangLen ? `N\xd7${overhangLen}` : 'Insert overhang…'

    let lastVal = input.value

    async function save() {
      const val = input.value.trim()
      if (val === lastVal) return
      lastVal = val
      await patchOverhang(ovhg.id, { sequence: val || null })
    }

    input.addEventListener('blur', save)
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); input.blur() }
      if (e.key === 'Escape') { input.value = lastVal; input.blur() }
    })

    return input
  }

  // ── Notes editable cell ───────────────────────────────────────────
  function _makeNotesCell(strand) {
    const input = document.createElement('input')
    input.type        = 'text'
    input.className   = 'sheet-cell-input'
    input.value       = strand.notes ?? ''
    input.placeholder = 'Add note…'

    let lastVal = input.value

    async function save() {
      const val = input.value
      if (val === lastVal) return
      lastVal = val
      await patchStrand(strand.id, { notes: val || null })
    }

    input.addEventListener('blur', save)
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); input.blur() }
      if (e.key === 'Escape') { input.value = lastVal; input.blur() }
    })

    return input
  }

  // ── Highlight selected rows ───────────────────────────────────────
  function _applyHighlights() {
    if (!_design?.strands?.length) return
    const strands = sortedStrands(_design)
    for (let i = 0; i < strands.length; i++) {
      const row = tbody.children[i]
      if (!row) continue
      row.classList.toggle('sheet-selected', _selectedStrandIds.has(strands[i].id))
    }
  }

  return {
    /** Update with a new design — rebuilds all rows. */
    update(design) {
      _design = design
      _rebuildTable()
    },

    /** Set which strand IDs are highlighted (from pathview selection). */
    setSelectedStrands(strandIds) {
      _selectedStrandIds = new Set(strandIds)
      if (!isOpen) return
      _applyHighlights()
      // Scroll the first selected row into view
      if (strandIds.length > 0) {
        const strands = sortedStrands(_design)
        for (let i = 0; i < strands.length; i++) {
          if (_selectedStrandIds.has(strands[i].id)) {
            const row = tbody.children[i]
            if (row) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
            break
          }
        }
      }
    },

    toggle() { setOpen(!isOpen) },
  }
}
