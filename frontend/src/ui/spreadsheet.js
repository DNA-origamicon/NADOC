/**
 * spreadsheet.js — Strand Spreadsheet Panel
 *
 * Provides a collapsible/draggable overlay panel below the menu bar that
 * displays all strands in a linked spreadsheet. Selecting a row highlights
 * the corresponding strand in the 3D view, and editing Notes or Overhang
 * cells writes back to the backend immediately.
 *
 * Columns (all toggle-able except Strand ID):
 *   Strand ID | Helix | 5' Overhang | Sequence | 3' Overhang | Group | Color | Length | Notes
 *
 * TODO: evaluate redundancy with the #overhang-panel sidebar once users have
 *   had a chance to use both. The sidebar's label-size slider is unique; the
 *   overhang sequence editing is now duplicated here.
 */

import * as api from '../api/client.js'
import { pushGroupUndo } from '../state/store.js'

// ── Column definitions ────────────────────────────────────────────────────

const COLUMNS = [
  { key: 'strand_id', label: 'Strand ID',   toggleable: false, editable: false },
  { key: 'helix',     label: 'Helix',       toggleable: true,  editable: false },
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

// ── Helpers ───────────────────────────────────────────────────────────────

function domainLength(domain) {
  return Math.abs(domain.end_bp - domain.start_bp) + 1
}

function strandLength(strand) {
  return strand.domains.reduce((sum, d) => sum + domainLength(d), 0)
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

function sortedStrands(design) {
  const strands = design?.strands ?? []
  const scaffold = strands.filter(s => s.strand_type === 'scaffold')
  const staples  = strands.filter(s => s.strand_type !== 'scaffold')
  staples.sort((a, b) => {
    const ha = a.domains[0]?.helix_id ?? ''
    const hb = b.domains[0]?.helix_id ?? ''
    if (ha < hb) return -1
    if (ha > hb) return 1
    return (a.domains[0]?.start_bp ?? 0) - (b.domains[0]?.start_bp ?? 0)
  })
  return [...scaffold, ...staples]
}

// ── Context menu ──────────────────────────────────────────────────────────

let _activeCtxMenu = null

function _removeCtxMenu() {
  if (_activeCtxMenu) { _activeCtxMenu.remove(); _activeCtxMenu = null }
}

function _showRowContextMenu(e, strand, goToStrand) {
  e.preventDefault()
  _removeCtxMenu()

  const menu = document.createElement('div')
  menu.className = 'ctx-menu'
  menu.style.cssText = `left:${e.clientX}px;top:${e.clientY}px`

  const goItem = document.createElement('div')
  goItem.className = 'ctx-item'
  goItem.textContent = 'Go to strand'
  goItem.addEventListener('click', () => {
    _removeCtxMenu()
    goToStrand(strand.id)
  })

  menu.appendChild(goItem)
  document.body.appendChild(menu)
  _activeCtxMenu = menu

  // Dismiss on next click anywhere
  setTimeout(() => document.addEventListener('pointerdown', _removeCtxMenu, { once: true }), 0)
}

// ── Module init ───────────────────────────────────────────────────────────

/**
 * @param {object} store        — the NADOC state store
 * @param {object} opts
 * @param {function} opts.goToStrand     — goToStrand(strandId): snaps camera to strand bounding box
 * @param {object}   opts.designRenderer — designRenderer with setStrandColor(strandId, hexInt)
 */
export function initSpreadsheet(store, { goToStrand = () => {}, designRenderer = null, selectionManager = null } = {}) {
  const panel     = document.getElementById('spreadsheet-panel')
  const tab       = document.getElementById('spreadsheet-tab')
  const arrow     = document.getElementById('spreadsheet-arrow')
  const body      = document.getElementById('spreadsheet-body')
  const theadRow  = document.getElementById('spreadsheet-thead-row')
  const tbody     = document.getElementById('spreadsheet-tbody')
  const toggleBar = document.getElementById('spreadsheet-col-toggles')
  const grip      = document.getElementById('spreadsheet-drag-grip')

  if (!panel || !tab || !body) return

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

  // ── Panel open/close state ────────────────────────────────────────
  let isOpen = false
  try { isOpen = JSON.parse(localStorage.getItem(LS_OPEN_KEY) ?? 'false') } catch (_) {}

  function setOpen(open) {
    isOpen = open
    body.style.display  = open ? 'block' : 'none'
    arrow.textContent   = open ? '▼' : '▶'
    localStorage.setItem(LS_OPEN_KEY, JSON.stringify(open))
    if (open) _rebuildTable(store.getState())
  }

  setOpen(isOpen)

  // ── Panel height (for drag-resize) ────────────────────────────────
  let panelHeight = 200
  try { panelHeight = parseInt(localStorage.getItem(LS_HEIGHT_KEY) ?? '200', 10) } catch (_) {}

  function applyHeight(h) {
    const maxH = window.innerHeight - 32 - MAX_HEIGHT_OFFSET
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
    const delta = e.clientY - dragStartY
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
    const selectedId   = state.selectedObject?.type === 'strand' ? state.selectedObject.id : null

    _updateDatalist(strandGroups)
    tbody.innerHTML = ''
    if (!design) return

    const strands = sortedStrands(design)

    strands.forEach((strand, idx) => {
      const isScaffold = strand.strand_type === 'scaffold'
      const color      = effectiveColor(strand, idx, strandColors, strandGroups)
      const ovhg5p     = terminalOverhang(strand, design, '5p')
      const ovhg3p     = terminalOverhang(strand, design, '3p')

      const tr = document.createElement('tr')
      if (isScaffold)               tr.classList.add('sheet-scaffold')
      if (strand.id === selectedId) tr.classList.add('sheet-selected')

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
          case 'strand_id': {
            td.textContent = strand.id.slice(0, 8) + '…'
            td.title = strand.id
            break
          }
          case 'helix': {
            td.textContent = strand.domains[0]?.helix_id ?? '—'
            break
          }
          case 'ovhg_5p': {
            td.appendChild(_makeOverhangCell(ovhg5p))
            break
          }
          case 'sequence': {
            if (strand.sequence) {
              const span = document.createElement('span')
              span.className = 'sheet-seq'
              const full = strand.sequence
              span.textContent = full.length > 40 ? full.slice(0, 38) + '…' : full
              span.title = full
              td.appendChild(span)
            } else {
              const len = strandLength(strand)
              const span = document.createElement('span')
              span.className = 'sheet-seq-none'
              span.textContent = `N×${len}`
              td.appendChild(span)
            }
            break
          }
          case 'ovhg_3p': {
            td.appendChild(_makeOverhangCell(ovhg3p))
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
            td.textContent = strandLength(strand)
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
  function _makeOverhangCell(ovhg) {
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
    input.placeholder = 'Insert overhang…'

    let lastVal = input.value

    async function save() {
      const val = input.value.trim()
      if (val === lastVal) return
      lastVal = val
      await api.patchOverhang(ovhg.id, { sequence: val || null })
      // patchOverhang → _syncFromDesignResponse → getGeometry() → 3D view rebuilds
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
      await api.patchStrand(strand.id, { notes: val || null })
    }

    input.addEventListener('blur', save)
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); input.blur() }
      if (e.key === 'Escape') { input.value = lastVal; input.blur() }
    })

    return input
  }

  // ── Subscribe to store changes ────────────────────────────────────
  store.subscribe((newState, prevState) => {
    const designChanged = newState.currentDesign  !== prevState.currentDesign
    const groupsChanged = newState.strandGroups   !== prevState.strandGroups
    const colorsChanged = newState.strandColors   !== prevState.strandColors
    const selChanged    = newState.selectedObject !== prevState.selectedObject

    if (designChanged || groupsChanged || colorsChanged) {
      _rebuildTable(newState)
      return
    }

    if (selChanged) {
      const prevId = prevState.selectedObject?.type === 'strand' ? prevState.selectedObject.id : null
      const newId  = newState.selectedObject?.type  === 'strand' ? newState.selectedObject.id  : null

      if (prevId !== newId) {
        const design = newState.currentDesign
        if (!design) return
        sortedStrands(design).forEach((s, i) => {
          const row = tbody.children[i]
          if (!row) return
          if (s.id === prevId) row.classList.remove('sheet-selected')
          if (s.id === newId)  { row.classList.add('sheet-selected'); row.scrollIntoView({ block: 'nearest' }) }
        })
      }
    }
  })

  return {
    toggle() { setOpen(!isOpen) },
  }
}
