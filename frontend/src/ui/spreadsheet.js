/**
 * spreadsheet.js — Strand Spreadsheet Panel
 *
 * Provides a collapsible/draggable overlay panel below the menu bar that
 * displays all strands in a linked spreadsheet. Selecting a row highlights
 * the corresponding strand in the 3D view, and editing Notes or Overhang
 * cells writes back to the backend immediately.
 *
 * Columns (all toggle-able except Start/End):
 *   Start | End | 5' Overhang | Sequence | 3' Overhang | Group | Color | Length | Notes
 *
 * TODO: evaluate redundancy with the #overhang-panel sidebar once users have
 *   had a chance to use both. The sidebar's label-size slider is unique; the
 *   overhang sequence editing is now duplicated here.
 */

import * as api from '../api/client.js'
import { pushGroupUndo } from '../state/store.js'
import { showToast } from './toast.js'

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

const LS_HEIGHT_KEY  = 'spreadsheet_height'
const LS_COLS_KEY    = 'spreadsheet_cols'
const LS_OPEN_KEY    = 'spreadsheet_open'

const MIN_HEIGHT = 28   // tab only
const TAB_HEIGHT = 28
const MAX_HEIGHT_OFFSET = 40  // px above viewport bottom

// Staple palette (mirrors helix_renderer.js)
const STAPLE_PALETTE = [
  '#e06c75','#98c379','#d19a66','#61afef',
  '#c678dd','#56b6c2','#e5c07b','#abb2bf',
  '#be5046','#7dab6e','#b07e45','#4e8cc4',
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
  // which: '5p' | '3p'
  const domain = which === '5p' ? strand.domains[0] : strand.domains[strand.domains.length - 1]
  if (!domain?.overhang_id) return null
  return (design.overhangs ?? []).find(o => o.id === domain.overhang_id) ?? null
}

function effectiveColor(strand, strandIndex, strandColors, strandGroups) {
  for (const group of strandGroups ?? []) {
    if (group.color && group.strandIds.includes(strand.id)) return group.color
  }
  const sc = strandColors?.[strand.id]
  if (sc != null) return '#' + sc.toString(16).padStart(6, '0')
  if (strand.strand_type === 'scaffold') return '#29b6f6'
  if (strand.color) return strand.color
  return paletteColor(strandIndex)
}

function groupName(strand, strandGroups) {
  const group = (strandGroups ?? []).find(g => g.strandIds.includes(strand.id))
  return group?.name ?? ''
}

/**
 * Build a display sequence string for a strand, including terminal extension
 * bracket notation at each end where a StrandExtension is attached.
 *
 * Example: "[TT]ACGTGCTA[CY3]" — [TT] is a 5′ extension; [CY3] is a 3′ modification.
 *
 * Returns null if the strand has no sequence and no extensions.
 *
 * @param {object} strand
 * @param {object} design
 * @returns {string|null}
 */
function _strandDisplaySequence(strand, design) {
  const extensions = design?.extensions ?? []
  const domains    = strand.domains ?? []
  const lastIdx    = domains.length - 1

  // Identify terminal overhang domains so we can strip them from the displayed
  // sequence — the dedicated ovhg_5p / ovhg_3p columns show those separately.
  const has5pOvhg = lastIdx >= 0 && domains[0].overhang_id != null
  const has3pOvhg = lastIdx >= 0 && domains[lastIdx].overhang_id != null

  const ext5 = extensions.find(e => e.strand_id === strand.id && e.end === 'five_prime')
  const ext3 = extensions.find(e => e.strand_id === strand.id && e.end === 'three_prime')
  const hasExtensions = !!(ext5 || ext3)

  if (!strand.sequence && !hasExtensions) return null

  // Strip overhang bases from both ends of the assembled sequence.
  let seq = strand.sequence ?? ''
  if (seq && domains.length > 0) {
    const trim5 = has5pOvhg ? domainLength(domains[0])       : 0
    const trim3 = has3pOvhg ? domainLength(domains[lastIdx]) : 0
    seq = seq.slice(trim5, trim3 > 0 ? seq.length - trim3 : undefined)
  }
  let result = seq

  // Prepend/append terminal extension bracket notation.
  // Format: [SEQ], [/MOD], or [SEQ/MOD]
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
  // strand.domains is ordered 5'→3'; for each adjacent pair find the matching
  // crossover and insert [XB] at the cumulative character offset.
  // Overhang domains are skipped — they are ssDNA and cannot have crossovers,
  // and their characters are not present in the (trimmed) result string.
  const crossovers = design?.crossovers ?? []
  if (crossovers.length && domains.length > 1) {
    let charOffset = 0   // chars consumed by non-ovhg domains so far
    let insertions = 0   // chars already inserted by prior brackets

    for (let i = 0; i < domains.length - 1; i++) {
      const d = domains[i]
      // Overhang domains are not in the displayed sequence — skip offset accumulation.
      if (d.overhang_id != null) continue

      const domLen = Math.abs(d.end_bp - d.start_bp) + 1
      charOffset  += domLen

      const nextD = domains[i + 1]
      // No crossover can connect to a ssDNA overhang domain.
      if (nextD.overhang_id != null) continue

      // 3' end of domain[i] in bp-index space.
      // For both FORWARD and REVERSE, domain_bp_range ends at end_bp (inclusive),
      // so end_bp is always the 3' junction regardless of direction.
      const junctionBp = d.end_bp

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

function sortedStrands(design, strandColors, strandGroups) {
  const strands  = design?.strands ?? []
  const scaffold = strands.filter(s => s.strand_type === 'scaffold')
  const staples  = strands.filter(s => s.strand_type !== 'scaffold')
  // Pre-compute color and length using the original array index (stable palette assignment).
  const withMeta = staples.map((s, idx) => ({
    strand: s,
    color:  effectiveColor(s, idx, strandColors ?? {}, strandGroups ?? []),
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

/**
 * Show a lightweight context menu.
 * items: array of { label, action } objects, or null for a separator.
 */
function _showContextMenu(e, items) {
  e.preventDefault()
  _removeCtxMenu()

  const menu = document.createElement('div')
  menu.className = 'ctx-menu'
  // Render off-screen first so we can measure the natural size before placing it.
  menu.style.cssText = 'display:block;visibility:hidden;left:0;top:0'

  for (const item of items) {
    if (item === null) {
      const hr = document.createElement('hr')
      hr.className = 'ctx-sep'
      menu.appendChild(hr)
      continue
    }
    const div = document.createElement('div')
    div.className = 'ctx-item'
    div.textContent = item.label
    div.addEventListener('click', () => { _removeCtxMenu(); item.action() })
    menu.appendChild(div)
  }

  document.body.appendChild(menu)

  // Clamp so the menu never overflows the viewport on any edge.
  const { offsetWidth: w, offsetHeight: h } = menu
  const x = Math.min(e.clientX, window.innerWidth  - w - 4)
  const y = e.clientY + h > window.innerHeight - 4
    ? Math.max(0, e.clientY - h)   // flip above the cursor
    : e.clientY
  menu.style.left       = `${x}px`
  menu.style.top        = `${y}px`
  menu.style.visibility = ''

  _activeCtxMenu = menu
  setTimeout(() => document.addEventListener('pointerdown', _removeCtxMenu, { once: true }), 0)
}

function _showRowContextMenu(e, strand, goToStrand) {
  _showContextMenu(e, [
    { label: 'Go to strand', action: () => goToStrand(strand.id) },
  ])
}

// ── Module init ───────────────────────────────────────────────────────────

/**
 * @param {object} store        — the NADOC state store
 * @param {object} opts
 * @param {function} opts.goToStrand     — goToStrand(strandId): snaps camera to strand bounding box
 * @param {object}   opts.designRenderer — designRenderer with setStrandColor(strandId, hexInt)
 */
export function initSpreadsheet(store, { goToStrand = () => {}, designRenderer = null, selectionManager = null } = {}) {
  const panel       = document.getElementById('spreadsheet-panel')
  const body        = document.getElementById('spreadsheet-body')
  const theadRow    = document.getElementById('spreadsheet-thead-row')
  const tbody       = document.getElementById('spreadsheet-tbody')
  const toggleBar   = document.getElementById('spreadsheet-col-toggles')
  const sheetEdge   = document.getElementById('sheet-edge')
  const sheetToggle = document.getElementById('sheet-toggle')

  if (!panel || !body) return

  // ── Shared datalist for group comboboxes ──────────────────────────
  const datalist = document.createElement('datalist')
  datalist.id = 'sheet-groups-datalist'
  document.body.appendChild(datalist)

  function _updateDatalist(strandGroups) {
    datalist.innerHTML = ''
    for (const g of strandGroups) {
      const opt = document.createElement('option')
      opt.value = g.name
      datalist.appendChild(opt)
    }
  }

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
      _rebuildTable(store.getState())
    })
    label.appendChild(cb)
    label.appendChild(document.createTextNode(col.label))
    toggleBar.appendChild(label)
  }

  // ── Panel height ──────────────────────────────────────────────────
  let panelHeight = 200
  try { panelHeight = parseInt(localStorage.getItem(LS_HEIGHT_KEY) ?? '200', 10) } catch (_) {}

  // ── Panel open/close state ────────────────────────────────────────
  let isOpen = false
  try { isOpen = JSON.parse(localStorage.getItem(LS_OPEN_KEY) ?? 'false') } catch (_) {}

  function setOpen(open) {
    isOpen = open
    panel.style.height = open ? panelHeight + 'px' : '0'
    if (sheetToggle) sheetToggle.textContent = open ? '▼' : '▲'
    localStorage.setItem(LS_OPEN_KEY, JSON.stringify(open))
    if (open) _rebuildTable(store.getState())
  }

  function applyHeight(h) {
    const maxH = window.innerHeight - 32 - 36 - 100  // menu + filter strip + min 3D
    panelHeight = Math.max(TAB_HEIGHT + 60, Math.min(h, maxH))
    panel.style.height = panelHeight + 'px'
    localStorage.setItem(LS_HEIGHT_KEY, String(panelHeight))
  }

  setOpen(isOpen)
  if (isOpen) applyHeight(panelHeight)

  // ── Sheet edge drag → resize; toggle pill → open/close ───────────
  let dragging = false
  let dragStartY = 0
  let dragStartH = 0

  if (sheetEdge) {
    sheetEdge.addEventListener('pointerdown', e => {
      if (e.target === sheetToggle) return
      dragging   = true
      dragStartY = e.clientY
      dragStartH = isOpen ? panelHeight : 0
      sheetEdge.setPointerCapture(e.pointerId)
      document.body.style.cursor = 'ns-resize'
    })

    sheetEdge.addEventListener('pointermove', e => {
      if (!dragging) return
      const delta = dragStartY - e.clientY  // up = positive = grow panel
      const newH  = dragStartH + delta
      if (newH > TAB_HEIGHT + 30 && !isOpen) {
        isOpen = true
        if (sheetToggle) sheetToggle.textContent = '▼'
        localStorage.setItem(LS_OPEN_KEY, 'true')
        _rebuildTable(store.getState())
      } else if (newH <= 10 && isOpen) {
        setOpen(false)
        return
      }
      if (isOpen) applyHeight(newH)
    })

    sheetEdge.addEventListener('pointerup', () => {
      dragging = false
      document.body.style.cursor = ''
    })
  }

  if (sheetToggle) {
    sheetToggle.addEventListener('click', e => {
      e.stopPropagation()
      const wasOpen = isOpen
      setOpen(!wasOpen)
      if (!wasOpen && isOpen) applyHeight(panelHeight)
    })
  }

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
  function _rebuildTable(state) {
    if (!isOpen) return
    _rebuildHeader()

    const design       = state.currentDesign
    const strandColors = state.strandColors ?? {}
    const strandGroups = state.strandGroups ?? []
    // Build highlighted set from multi-selection or single selection
    const multiIds = state.multiSelectedStrandIds ?? []
    const _strandIdFrom = sel => {
      if (!sel) return null
      if (sel.type === 'strand') return sel.id
      return sel.data?.strand_id ?? null
    }
    const singleId = _strandIdFrom(state.selectedObject)
    const highlightedIds = new Set(multiIds.length > 0 ? multiIds : (singleId ? [singleId] : []))

    _updateDatalist(strandGroups)
    tbody.innerHTML = ''
    if (!design) {
      _appendAssemblyLinkerRows(state, highlightedIds)
      return
    }

    const strands = sortedStrands(design, strandColors, strandGroups)
    // Map helix_id → display index (matches cadnano pathview gutter labels)
    const helixIndex = Object.fromEntries((design.helices ?? []).map((h, i) => [h.id, i]))

    strands.forEach((strand, idx) => {
      const isScaffold = strand.strand_type === 'scaffold'
      const color      = effectiveColor(strand, idx, strandColors, strandGroups)
      const ovhg5p     = terminalOverhang(strand, design, '5p')
      const ovhg3p     = terminalOverhang(strand, design, '3p')

      const tr = document.createElement('tr')
      if (isScaffold)                       tr.classList.add('sheet-scaffold')
      if (highlightedIds.has(strand.id))    tr.classList.add('sheet-selected')

      // Left-click → select strand in 3D exactly as a manual click would
      tr.addEventListener('click', e => {
        if (e.target.tagName === 'INPUT') return
        selectionManager?.selectStrand(strand.id)
      })

      // Right-click → context menu
      tr.addEventListener('contextmenu', e => {
        _showRowContextMenu(e, strand, goToStrand)
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
            td.addEventListener('contextmenu', e => {
              e.stopPropagation()
              const items = [{ label: 'Go to strand', action: () => goToStrand(strand.id) }]
              if (ovhg5p?.sequence != null) {
                items.push(null)
                items.push({ label: 'Clear sequence', action: () => api.patchOverhang(ovhg5p.id, { sequence: null }) })
              }
              _showContextMenu(e, items)
            })
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
              const d5    = strand.domains[0]
              const dLast = strand.domains[strand.domains.length - 1]
              const d3    = dLast !== d5 ? dLast : null
              const ovhg5Len = d5?.overhang_id    ? domainLength(d5) : 0
              const ovhg3Len = d3?.overhang_id ? domainLength(d3) : 0
              const len = strandLength(strand, design) - ovhg5Len - ovhg3Len
              const span = document.createElement('span')
              span.className = 'sheet-seq-none'
              span.textContent = `N\xd7${len}`
              td.appendChild(span)
            }
            td.addEventListener('contextmenu', e => {
              e.stopPropagation()
              const items = [{ label: 'Go to strand', action: () => goToStrand(strand.id) }]
              if (strand.sequence != null) {
                items.push(null)
                items.push({ label: 'Clear sequence', action: () => api.patchStrand(strand.id, { sequence: null }) })
              }
              _showContextMenu(e, items)
            })
            break
          }
          case 'ovhg_3p': {
            const d3 = strand.domains[strand.domains.length - 1]
            td.appendChild(_makeOverhangCell(ovhg3p, d3 ? domainLength(d3) : 0))
            td.addEventListener('contextmenu', e => {
              e.stopPropagation()
              const items = [{ label: 'Go to strand', action: () => goToStrand(strand.id) }]
              if (ovhg3p?.sequence != null) {
                items.push(null)
                items.push({ label: 'Clear sequence', action: () => api.patchOverhang(ovhg3p.id, { sequence: null }) })
              }
              _showContextMenu(e, items)
            })
            break
          }
          case 'group': {
            td.appendChild(_makeGroupCell(strand, idx, strandColors, strandGroups))
            break
          }
          case 'color': {
            td.appendChild(_makeColorCell(strand, color, strandGroups))
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

    _appendAssemblyLinkerRows(state, highlightedIds)
  }

  // ── Assembly-level linker rows ────────────────────────────────────
  //
  // Cross-part linkers (generated from AssemblyOverhangConnection) live
  // on `currentAssembly.assembly_strands` with strand_type='linker'. They
  // don't belong to any single part design, so their Start/End cells
  // reference the source instances + overhang labels recorded on the
  // connection, and Sequence shows the pre-composed strand.sequence
  // (RC of OH-A + bridge_sequence + RC of OH-B for ss; per-side composed
  // for ds). Other editable cells (Group, Color, Notes, Overhang inputs)
  // are read-only placeholders for these rows.
  function _appendAssemblyLinkerRows(state, highlightedIds) {
    if (!state.assemblyActive) return
    const assembly = state.currentAssembly
    if (!assembly) return
    const linkers = (assembly.assembly_strands ?? []).filter(s => s.strand_type === 'linker')
    if (!linkers.length) return

    const connsById = Object.fromEntries((assembly.overhang_connections ?? []).map(c => [c.id, c]))
    const instanceById = Object.fromEntries((assembly.instances ?? []).map(i => [i.id, i]))

    function _connForStrand(strand) {
      // Strand ids are '__lnk__<conn_id>__a' / '__b' / '__s'.
      const m = /^__lnk__(.+?)__[abs]$/.exec(strand.id ?? '')
      if (!m) return null
      return connsById[m[1]] ?? null
    }

    function _instOhLabel(instId, ohId) {
      const inst = instanceById[instId]
      const name = inst?.name ?? instId
      const design = inst?.source?.design
      const oh = design?.overhangs?.find(o => o.id === ohId)
      const label = oh?.label ?? ohId
      return `${name}.${label}`
    }

    function _strandTotalBp(strand) {
      let total = 0
      for (const d of (strand.domains ?? [])) {
        total += Math.abs(d.end_bp - d.start_bp) + 1
      }
      return total
    }

    for (const strand of linkers) {
      const conn = _connForStrand(strand)
      const tr = document.createElement('tr')
      tr.classList.add('sheet-linker')
      if (highlightedIds.has(strand.id)) tr.classList.add('sheet-selected')

      tr.addEventListener('click', e => {
        if (e.target.tagName === 'INPUT') return
        selectionManager?.selectStrand?.(strand.id)
      })

      let startText = strand.id
      let endText   = ''
      if (conn) {
        startText = _instOhLabel(conn.instance_a_id, conn.overhang_a_id)
        endText   = _instOhLabel(conn.instance_b_id, conn.overhang_b_id)
        // ds linker strands belong to one side — invert the cell labels for
        // the b-side strand so the spreadsheet row reads in 5'→3' order.
        if (strand.id?.endsWith('__b')) { [startText, endText] = [endText, startText] }
      }

      for (const col of COLUMNS) {
        if (col.toggleable && hiddenCols.has(col.key)) continue
        const td = document.createElement('td')

        switch (col.key) {
          case 'start': {
            td.className = 'sheet-col-endpoint'
            td.textContent = startText
            td.title = strand.id
            break
          }
          case 'end': {
            td.className = 'sheet-col-endpoint'
            td.textContent = endText
            break
          }
          case 'sequence': {
            const seq = strand.sequence ?? ''
            if (seq) {
              const span = document.createElement('span')
              span.className = 'sheet-seq'
              span.textContent = seq.length > 40 ? seq.slice(0, 38) + '…' : seq
              span.title = seq
              td.appendChild(span)
            } else {
              const span = document.createElement('span')
              span.className = 'sheet-seq-none'
              span.textContent = `N\xd7${_strandTotalBp(strand)}`
              td.appendChild(span)
            }
            break
          }
          case 'length': {
            td.textContent = _strandTotalBp(strand)
            break
          }
          case 'color': {
            const swatch = document.createElement('span')
            swatch.className = 'sheet-color-swatch'
            swatch.style.background = strand.color || '#ffffff'
            td.appendChild(swatch)
            break
          }
          // ovhg_5p / ovhg_3p / group / notes — leave empty for assembly linkers
        }

        tr.appendChild(td)
      }

      tbody.appendChild(tr)
    }
  }

  // ── Group combobox cell ───────────────────────────────────────────
  function _makeGroupCell(strand, strandIdx, strandColors, strandGroups) {
    const input = document.createElement('input')
    input.type        = 'text'
    input.className   = 'sheet-group-input'
    input.setAttribute('list', 'sheet-groups-datalist')
    input.value       = groupName(strand, strandGroups)
    input.placeholder = 'No group'

    input.addEventListener('click', e => e.stopPropagation())

    let lastVal = input.value

    function commit() {
      const val = input.value.trim()
      if (val === lastVal) return
      lastVal = val
      _assignGroup(strand, strandIdx, val)
    }

    input.addEventListener('blur', commit)
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); input.blur() }
      if (e.key === 'Escape') { input.value = lastVal; input.blur() }
    })

    return input
  }

  /**
   * Assign `strand` to the group named `groupName` (or remove if '').
   * - Existing group: strand adopts the group's color.
   * - New group: created with the strand's current effective color.
   * - Empty string: strand removed from any group.
   */
  function _assignGroup(strand, strandIdx, newGroupName) {
    pushGroupUndo()
    const state  = store.getState()
    let   groups = state.strandGroups ?? []

    // Remove strand from every group first
    groups = groups.map(g => ({ ...g, strandIds: g.strandIds.filter(id => id !== strand.id) }))

    if (newGroupName === '') {
      store.setState({ strandGroups: groups })
      return
    }

    const existing = groups.find(g => g.name === newGroupName)
    if (existing) {
      // Join existing group — strand adopts group color
      store.setState({
        strandGroups: groups.map(g =>
          g.id === existing.id ? { ...g, strandIds: [...g.strandIds, strand.id] } : g
        ),
      })
      if (existing.color) {
        api.patchStrand(strand.id, { color: existing.color })
      }
    } else {
      // New group — initialise with strand's current effective color
      const color = effectiveColor(strand, strandIdx, state.strandColors, state.strandGroups)
      store.setState({
        strandGroups: [...groups, {
          id: `grp_${Date.now()}`,
          name: newGroupName,
          color,
          strandIds: [strand.id],
        }],
      })
    }
  }

  // ── Color picker cell ─────────────────────────────────────────────
  function _makeColorCell(strand, currentColor, strandGroups) {
    const input = document.createElement('input')
    input.type      = 'color'
    input.className = 'sheet-color-input'
    input.value     = currentColor
    input.title     = 'Click to change strand color'

    input.addEventListener('click', e => e.stopPropagation())

    input.addEventListener('change', async () => {
      const hex    = input.value                          // "#rrggbb"
      const hexInt = parseInt(hex.replace('#', ''), 16)  // number for store/3D

      const group = (strandGroups ?? []).find(g => g.strandIds.includes(strand.id))

      if (group) {
        // Propagate new color to the whole group
        const newGroups = store.getState().strandGroups.map(g =>
          g.id === group.id ? { ...g, color: hex } : g
        )
        store.setState({ strandGroups: newGroups })
        // Persist backend color for every strand in the group
        for (const sid of group.strandIds) {
          api.patchStrand(sid, { color: hex })
        }
      } else {
        // Standalone strand — update only this strand
        designRenderer?.setStrandColor(strand.id, hexInt)
        await api.patchStrand(strand.id, { color: hex })
      }
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

    function _isUnseq(val) { return !val || /^n+$/i.test(val.trim()) }

    // ── Sequenced overhang: editable input + Gen button ─────────────
    if (ovhg.sequence != null) {
      const wrap = document.createElement('span')
      wrap.style.cssText = 'display:flex;align-items:center;gap:4px'

      const input = document.createElement('input')
      input.type        = 'text'
      input.className   = 'sheet-cell-input'
      input.value       = ovhg.sequence
      let lastVal       = input.value

      async function save() {
        const val = input.value.trim().toUpperCase()
        if (val === lastVal) return
        lastVal = val
        await api.patchOverhang(ovhg.id, { sequence: val || null })
      }

      input.addEventListener('focus', () => selectionManager?.selectStrand(ovhg.strand_id))
      input.addEventListener('blur', save)
      input.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); input.blur() }
        if (e.key === 'Escape') { input.value = lastVal; input.blur() }
      })

      const btn = document.createElement('button')
      btn.textContent = 'Gen'
      btn.title       = 'Regenerate sequence'
      btn.className   = 'sheet-gen-btn'
      btn.addEventListener('click', async e => {
        e.stopPropagation()
        btn.disabled = true
        showToast('Using Johnson et al. overhang algorithm — DOI: 10.1021/acs.nanolett.9b02786')
        await api.generateOverhangRandomSequence(ovhg.id)
      })

      function _syncBtn() { btn.style.display = _isUnseq(input.value) ? '' : 'none' }
      _syncBtn()
      input.addEventListener('input', _syncBtn)

      wrap.appendChild(input)
      wrap.appendChild(btn)
      return wrap
    }

    // ── Unsequenced overhang: N×len label + Gen button ───────────────
    // Clicking the label switches to an inline edit input.
    const wrap = document.createElement('span')
    wrap.style.cssText = 'display:flex;align-items:center;gap:4px'

    const label = document.createElement('span')
    label.className   = 'sheet-seq-none'
    label.textContent = overhangLen ? `N\xd7${overhangLen}` : 'N×?'
    label.title       = 'Click to enter a custom sequence'
    label.style.cursor = 'text'

    const editInput = document.createElement('input')
    editInput.type      = 'text'
    editInput.className = 'sheet-cell-input'
    editInput.placeholder = overhangLen ? `N\xd7${overhangLen}` : 'sequence…'
    editInput.style.cssText = 'display:none;min-width:60px'

    label.addEventListener('click', e => {
      e.stopPropagation()
      label.style.display    = 'none'
      editInput.style.display = ''
      editInput.focus()
    })

    editInput.addEventListener('focus', () => selectionManager?.selectStrand(ovhg.strand_id))

    async function commitEdit() {
      const val = editInput.value.trim().toUpperCase()
      if (!val) {
        // Nothing typed — revert to label
        editInput.style.display = 'none'
        label.style.display     = ''
      } else {
        await api.patchOverhang(ovhg.id, { sequence: val })
        // Store updates → spreadsheet re-renders → cell replaced with sequenced input
      }
    }

    editInput.addEventListener('blur', commitEdit)
    editInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); editInput.blur() }
      if (e.key === 'Escape') { editInput.value = ''; editInput.blur() }
    })

    const btn = document.createElement('button')
    btn.textContent = 'Gen'
    btn.title       = 'Generate random sequence'
    btn.className   = 'sheet-gen-btn'
    btn.addEventListener('click', async e => {
      e.stopPropagation()
      btn.disabled = true
      showToast('Using Johnson et al. overhang algorithm — DOI: 10.1021/acs.nanolett.9b02786')
      await api.generateOverhangRandomSequence(ovhg.id)
    })

    wrap.appendChild(label)
    wrap.appendChild(editInput)
    wrap.appendChild(btn)
    return wrap
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
      await api.patchStrand(strand.id, { notes: val || null })
    }

    input.addEventListener('blur', save)
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); input.blur() }
      if (e.key === 'Escape') { input.value = lastVal; input.blur() }
    })

    return input
  }

  // ── Highlight helpers ──────────────────────────────────────────────
  function _applyHighlights(selectedIds) {
    if (!isOpen) return
    const design = store.getState().currentDesign
    if (!design) return
    const state = store.getState()
    const strands = sortedStrands(design, state.strandColors ?? {}, state.strandGroups)
    let scrolled = false
    for (let i = 0; i < strands.length; i++) {
      const row = tbody.children[i]
      if (!row) continue
      const sel = selectedIds.has(strands[i].id)
      row.classList.toggle('sheet-selected', sel)
      if (sel && !scrolled) { row.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); scrolled = true }
    }
  }

  // ── Subscribe to store changes ────────────────────────────────────
  store.subscribe((newState, prevState) => {
    const designChanged  = newState.currentDesign  !== prevState.currentDesign
    // Defensive: also detect strands-array replacement even when the
    // outer currentDesign reference is preserved (some lean paths mutate
    // currentDesign in place rather than replacing it). Catches sequence
    // assignments that produce new strand objects but keep the design ref.
    const strandsChanged = newState.currentDesign?.strands !== prevState.currentDesign?.strands
    const groupsChanged  = newState.strandGroups   !== prevState.strandGroups
    const colorsChanged  = newState.strandColors   !== prevState.strandColors
    const selChanged     = newState.selectedObject !== prevState.selectedObject
    const multiChanged   = newState.multiSelectedStrandIds !== prevState.multiSelectedStrandIds
    const assemblyChanged       = newState.currentAssembly !== prevState.currentAssembly
    const assemblyActiveChanged = newState.assemblyActive  !== prevState.assemblyActive
    const assemblyStrandsChanged = newState.currentAssembly?.assembly_strands
                                  !== prevState.currentAssembly?.assembly_strands

    if (designChanged || strandsChanged || groupsChanged || colorsChanged
        || assemblyChanged || assemblyActiveChanged || assemblyStrandsChanged) {
      _rebuildTable(newState)
      return
    }

    // Multi-selection takes precedence (lasso, cross-window broadcast),
    // but only when it's a positive selection — an empty multi-clear
    // should fall through so the single selectedObject still applies.
    const multiIds = newState.multiSelectedStrandIds ?? []
    if (multiChanged && multiIds.length > 0) {
      _applyHighlights(new Set(multiIds))
      return
    }

    if (selChanged || multiChanged) {
      const _strandIdFrom = sel => {
        if (!sel) return null
        if (sel.type === 'strand') return sel.id
        return sel.data?.strand_id ?? null
      }
      const newId  = _strandIdFrom(newState.selectedObject)
      _applyHighlights(new Set(newId ? [newId] : []))
    }
  })

  return {
    toggle() { setOpen(!isOpen) },
  }
}
