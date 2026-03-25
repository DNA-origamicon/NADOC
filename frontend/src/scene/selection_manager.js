/**
 * Selection manager — raycaster-based click-to-select with three-click model.
 *
 * Click model (beads and cones both participate):
 *   First click on a bead/cone  → select the entire strand.
 *   Second click on a bead      → select that individual nucleotide.
 *   Click on same bead again    → deselect (clear selection).
 *   Click on a different bead (bead mode, same strand) → select that bead.
 *   Second click on a cone      → select that individual cone.
 *   Click on empty space        → clear selection.
 *
 * Ctrl+left-click (no drag) → toggle individual nucleotide in _ctrlBeads.
 * Ctrl+left-drag             → rectangle lasso multi-select.
 *
 * Right-click behaviour:
 *   On a cone (any mode) → "Nick here" context menu.
 *   On a bead (strand or domain selected) → colour-picker menu.
 *   On a bead (bead mode) → loop/skip menu.
 *
 * Selection state is stored in the store as selectedObject:
 *   { type: 'strand',     id, data: { strand_id } }
 *   { type: 'domain',     id, data: { strand_id, domain_index, helix_id, direction, overhang_id } }
 *   { type: 'nucleotide', id, data: nuc }
 *   { type: 'cone',       id, data: { fromNuc, toNuc, strand_id } }
 *   null — nothing selected
 */

import * as THREE from 'three'
import { store, pushGroupUndo } from '../state/store.js'
import * as api from '../api/client.js'

// ── Colour constants ───────────────────────────────────────────────────────────

const C_SELECT_BEAD          = 0xffffff
const C_SELECT_CONE          = 0xffffff
const C_SELECT_STRAND        = 0xffffff
const C_SCAFFOLD_FIVE_PRIME  = 0xff4444   // glowing red — scaffold 5′ end
const C_SCAFFOLD_THREE_PRIME = 0x4488ff   // glowing blue — scaffold 3′ end

const PICKER_COLORS = [
  { hex: 0xff6b6b, css: '#ff6b6b', label: 'Coral'      },
  { hex: 0xffd93d, css: '#ffd93d', label: 'Amber'      },
  { hex: 0x6bcb77, css: '#6bcb77', label: 'Green'      },
  { hex: 0xf9844a, css: '#f9844a', label: 'Orange'     },
  { hex: 0xa29bfe, css: '#a29bfe', label: 'Lavender'   },
  { hex: 0xff9ff3, css: '#ff9ff3', label: 'Pink'       },
  { hex: 0x00cec9, css: '#00cec9', label: 'Teal'       },
  { hex: 0xe17055, css: '#e17055', label: 'Terracotta' },
  { hex: 0x74b9ff, css: '#74b9ff', label: 'Steel blue' },
  { hex: 0x55efc4, css: '#55efc4', label: 'Mint'       },
  { hex: 0xfdcb6e, css: '#fdcb6e', label: 'Yellow'     },
  { hex: 0xd63031, css: '#d63031', label: 'Crimson'    },
]

// ── Raycaster ─────────────────────────────────────────────────────────────────

const raycaster  = new THREE.Raycaster()
const _ndc       = new THREE.Vector2()
const _arcHitPx  = 12   // screen-space proximity threshold for arc midpoint hits

// ── Context menu ──────────────────────────────────────────────────────────────

let _menuEl = null

function _dismissMenu() {
  if (_menuEl) {
    _menuEl.remove()
    _menuEl = null
  }
}

function _menuOutsideListeners(menu) {
  const onOutside = e => {
    if (!menu.contains(e.target)) {
      _dismissMenu()
      document.removeEventListener('pointerdown', onOutside)
      document.removeEventListener('keydown', onEsc)
    }
  }
  const onEsc = e => {
    if (e.key === 'Escape') {
      _dismissMenu()
      document.removeEventListener('pointerdown', onOutside)
      document.removeEventListener('keydown', onEsc)
    }
  }
  setTimeout(() => {
    document.addEventListener('pointerdown', onOutside)
    document.addEventListener('keydown', onEsc)
  }, 0)
}

function _menuBase(x, y) {
  const menu = document.createElement('div')
  menu.style.cssText = `
    position: fixed; left: ${x}px; top: ${y}px;
    background: #1e2a3a; border: 1px solid #3a4a5a; border-radius: 6px;
    padding: 4px 0; min-width: 110px; z-index: 9999;
    box-shadow: 0 4px 16px rgba(0,0,0,0.5); font-family: monospace; font-size: 12px;
  `
  return menu
}

function _menuItem(text, onClick) {
  const item = document.createElement('div')
  item.textContent = text
  item.style.cssText = `padding: 6px 14px; color: #eef; cursor: pointer;`
  item.addEventListener('mouseenter', () => { item.style.background = '#2a3a4a' })
  item.addEventListener('mouseleave', () => { item.style.background = 'transparent' })
  item.addEventListener('click', e => { e.stopPropagation(); _dismissMenu(); onClick() })
  return item
}

function _menuSep() {
  const hr = document.createElement('div')
  hr.style.cssText = `border-top: 1px solid #3a4a5a; margin: 4px 0;`
  return hr
}

function _showColorMenu(x, y, strandId, designRenderer) {
  _dismissMenu()
  const menu = _menuBase(x, y)

  // Check if this strand is a scaffold
  const design = store.getState().currentDesign
  const isScaffold = design?.strands?.find(s => s.id === strandId)?.strand_type === 'scaffold'

  // Isolate / Un-isolate (only for non-scaffold strands)
  if (!isScaffold) {
    const { isolatedStrandId } = store.getState()
    const isIsolated = isolatedStrandId === strandId
    menu.appendChild(_menuItem(
      isIsolated ? 'Un-isolate' : 'Isolate',
      () => store.setState({ isolatedStrandId: isIsolated ? null : strandId }),
    ))
    menu.appendChild(_menuSep())
  }

  const header = document.createElement('div')
  header.textContent = 'Color'
  header.style.cssText = `
    padding: 4px 12px; color: #8899aa; font-size: 11px; letter-spacing: 0.05em;
    text-transform: uppercase; border-bottom: 1px solid #3a4a5a; margin-bottom: 4px;
  `
  menu.appendChild(header)

  const grid = document.createElement('div')
  grid.style.cssText = `display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; padding: 4px 8px;`
  for (const { hex, css, label } of PICKER_COLORS) {
    const swatch = document.createElement('div')
    swatch.title = label
    swatch.style.cssText = `
      width: 20px; height: 20px; border-radius: 3px; cursor: pointer;
      background: ${css}; border: 2px solid transparent; transition: border-color 0.1s;
    `
    swatch.addEventListener('mouseenter', () => { swatch.style.borderColor = '#ffffff' })
    swatch.addEventListener('mouseleave', () => { swatch.style.borderColor = 'transparent' })
    swatch.addEventListener('click', e => {
      e.stopPropagation()
      designRenderer.setStrandColor(strandId, hex)
      _dismissMenu()
    })
    grid.appendChild(swatch)
  }
  menu.appendChild(grid)

  // Custom RGB color picker
  if (!isScaffold) {
    const rgbRow = document.createElement('div')
    rgbRow.style.cssText = 'display:flex;align-items:center;gap:6px;padding:4px 8px 2px'
    const rgbLabel = document.createElement('span')
    rgbLabel.textContent = 'Custom'
    rgbLabel.style.cssText = 'color:#8899aa;font-size:11px'
    const rgbInput = document.createElement('input')
    rgbInput.type = 'color'
    rgbInput.value = '#ffffff'
    rgbInput.style.cssText = 'width:36px;height:22px;border:none;background:none;cursor:pointer;padding:0;border-radius:3px'
    rgbInput.addEventListener('change', e => {
      e.stopPropagation()
      const hex = parseInt(rgbInput.value.replace('#', ''), 16)
      designRenderer.setStrandColor(strandId, hex)
      _dismissMenu()
    })
    rgbRow.appendChild(rgbLabel)
    rgbRow.appendChild(rgbInput)
    menu.appendChild(rgbRow)
  }

  // Groups section (non-scaffold only)
  if (!isScaffold) {
    menu.appendChild(_menuSep())
    const grpHeader = document.createElement('div')
    grpHeader.textContent = 'Group'
    grpHeader.style.cssText = 'padding:4px 12px;color:#8899aa;font-size:11px;letter-spacing:.05em;' +
                               'text-transform:uppercase;border-bottom:1px solid #3a4a5a;margin-bottom:6px'
    menu.appendChild(grpHeader)

    const grpRow = document.createElement('div')
    grpRow.style.cssText = 'padding:0 10px 6px'

    const { strandGroups } = store.getState()
    const currentGroup = strandGroups.find(g => g.strandIds.includes(strandId))

    const sel = document.createElement('select')
    sel.style.cssText = 'width:100%;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;' +
                        'border-radius:4px;padding:4px 6px;font-size:12px;cursor:pointer;outline:none'
    sel.addEventListener('click', e => e.stopPropagation())

    const noneOpt = document.createElement('option')
    noneOpt.value       = ''
    noneOpt.textContent = '(no group)'
    sel.appendChild(noneOpt)

    for (const g of strandGroups) {
      const opt = document.createElement('option')
      opt.value       = g.id
      opt.textContent = g.name
      if (g.id === currentGroup?.id) opt.selected = true
      sel.appendChild(opt)
    }

    const newOpt = document.createElement('option')
    newOpt.value       = '__new__'
    newOpt.textContent = '＋ New group…'
    sel.appendChild(newOpt)

    if (!currentGroup) sel.value = ''

    // Inline name input — shown only when "＋ New group…" is chosen
    const newInput = document.createElement('input')
    newInput.type        = 'text'
    newInput.placeholder = 'Group name…'
    newInput.style.cssText = 'display:none;margin-top:5px;width:100%;box-sizing:border-box;' +
                              'background:#0d1117;color:#c9d1d9;border:1px solid #30363d;' +
                              'border-radius:4px;padding:4px 6px;font-size:12px;outline:none'
    newInput.addEventListener('click', e => e.stopPropagation())

    function _applyGroupChange(groupId) {
      pushGroupUndo()
      const gs = store.getState().strandGroups
      // Remove strand from every group, then add to chosen one
      let updated = gs.map(g => ({ ...g, strandIds: g.strandIds.filter(s => s !== strandId) }))
      if (groupId) {
        updated = updated.map(g =>
          g.id === groupId ? { ...g, strandIds: [...g.strandIds, strandId] } : g
        )
      }
      store.setState({ strandGroups: updated })
    }

    function _createAndAssign(name) {
      name = name.trim()
      if (!name) { sel.value = currentGroup?.id ?? ''; return }
      pushGroupUndo()
      const gs = store.getState().strandGroups
      const existing = gs.find(g => g.name === name)
      if (existing) {
        const updated = gs.map(g => ({
          ...g,
          strandIds: g.id === existing.id
            ? [...g.strandIds.filter(s => s !== strandId), strandId]
            : g.strandIds.filter(s => s !== strandId),
        }))
        store.setState({ strandGroups: updated })
      } else {
        const palette = ['#74b9ff','#6bcb77','#ff6b6b','#ffd93d','#a29bfe','#55efc4']
        const color   = palette[gs.length % palette.length]
        const newId   = `grp_${Date.now()}`
        let updated   = gs.map(g => ({ ...g, strandIds: g.strandIds.filter(s => s !== strandId) }))
        updated = [...updated, { id: newId, name, color, strandIds: [strandId] }]
        store.setState({ strandGroups: updated })
      }
      _dismissMenu()
    }

    sel.addEventListener('change', e => {
      e.stopPropagation()
      if (sel.value === '__new__') {
        newInput.style.display = 'block'
        newInput.value = ''
        newInput.focus()
      } else {
        newInput.style.display = 'none'
        _applyGroupChange(sel.value)
        _dismissMenu()
      }
    })

    newInput.addEventListener('keydown', e => {
      e.stopPropagation()
      if (e.key === 'Enter')  { _createAndAssign(newInput.value) }
      if (e.key === 'Escape') { newInput.style.display = 'none'; sel.value = currentGroup?.id ?? '' }
    })
    newInput.addEventListener('blur', () => {
      if (newInput.style.display !== 'none') _createAndAssign(newInput.value)
    })

    grpRow.appendChild(sel)
    grpRow.appendChild(newInput)
    menu.appendChild(grpRow)
  }

  // Delete (non-scaffold only)
  if (!isScaffold) {
    menu.appendChild(_menuSep())
    const delItem = _menuItem('Delete strand', () => api.deleteStrand(strandId))
    delItem.style.color = '#ff6b6b'
    menu.appendChild(delItem)
  }

  document.body.appendChild(menu)
  _menuEl = menu
  _menuOutsideListeners(menu)
}

function _showMultiMenu(x, y, strandIds, designRenderer) {
  _dismissMenu()
  const menu = _menuBase(x, y)

  // Header
  const hdr = document.createElement('div')
  hdr.textContent = `${strandIds.length} strand${strandIds.length === 1 ? '' : 's'} selected`
  hdr.style.cssText = 'padding:4px 12px;color:#8899aa;font-size:11px;letter-spacing:.05em;' +
                      'border-bottom:1px solid #3a4a5a;margin-bottom:4px'
  menu.appendChild(hdr)

  // Color all header
  const colorHdr = document.createElement('div')
  colorHdr.textContent = 'Color all'
  colorHdr.style.cssText = 'padding:4px 12px;color:#8899aa;font-size:11px;letter-spacing:.05em;' +
                            'text-transform:uppercase;border-bottom:1px solid #3a4a5a;margin-bottom:4px'
  menu.appendChild(colorHdr)

  const grid = document.createElement('div')
  grid.style.cssText = 'display:grid;grid-template-columns:repeat(4,1fr);gap:4px;padding:4px 8px'
  for (const { hex, css, label } of PICKER_COLORS) {
    const sw = document.createElement('div')
    sw.title = label
    sw.style.cssText = `width:20px;height:20px;border-radius:3px;cursor:pointer;background:${css};border:2px solid transparent;transition:border-color .1s`
    sw.addEventListener('mouseenter', () => { sw.style.borderColor = '#fff' })
    sw.addEventListener('mouseleave', () => { sw.style.borderColor = 'transparent' })
    sw.addEventListener('click', e => {
      e.stopPropagation()
      for (const sid of strandIds) designRenderer.setStrandColor(sid, hex)
      _dismissMenu()
    })
    grid.appendChild(sw)
  }
  menu.appendChild(grid)

  // Custom RGB
  const rgbRow = document.createElement('div')
  rgbRow.style.cssText = 'display:flex;align-items:center;gap:6px;padding:4px 8px 2px'
  const rgbLabel = document.createElement('span')
  rgbLabel.textContent = 'Custom'
  rgbLabel.style.cssText = 'color:#8899aa;font-size:11px'
  const rgbInput = document.createElement('input')
  rgbInput.type = 'color'
  rgbInput.value = '#ffffff'
  rgbInput.style.cssText = 'width:36px;height:22px;border:none;background:none;cursor:pointer;padding:0;border-radius:3px'
  rgbInput.addEventListener('change', e => {
    e.stopPropagation()
    const hex = parseInt(rgbInput.value.replace('#', ''), 16)
    for (const sid of strandIds) designRenderer.setStrandColor(sid, hex)
    _dismissMenu()
  })
  rgbRow.appendChild(rgbLabel)
  rgbRow.appendChild(rgbInput)
  menu.appendChild(rgbRow)

  // Groups
  menu.appendChild(_menuSep())
  const grpHdr = document.createElement('div')
  grpHdr.textContent = 'Groups'
  grpHdr.style.cssText = 'padding:4px 12px;color:#8899aa;font-size:11px;letter-spacing:.05em;' +
                          'text-transform:uppercase;border-bottom:1px solid #3a4a5a;margin-bottom:4px'
  menu.appendChild(grpHdr)

  const multiGrpRow = document.createElement('div')
  multiGrpRow.style.cssText = 'padding:4px 8px;display:flex;gap:6px;align-items:center'

  const multiSel = document.createElement('select')
  multiSel.style.cssText = 'flex:1;background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
                            'color:#c9d1d9;padding:3px 5px;font-size:11px;font-family:monospace'
  const multiNone = document.createElement('option')
  multiNone.value = ''; multiNone.textContent = '— none —'
  multiSel.appendChild(multiNone)

  const { strandGroups: multiGroups } = store.getState()
  for (const g of multiGroups) {
    const opt = document.createElement('option')
    opt.value = g.id
    const anyIn = strandIds.some(sid => g.strandIds.includes(sid))
    opt.textContent = (anyIn ? '✓ ' : '\u00a0\u00a0') + g.name
    multiSel.appendChild(opt)
  }
  const multiNewOpt = document.createElement('option')
  multiNewOpt.value = '__new__'; multiNewOpt.textContent = '＋ New group…'
  multiSel.appendChild(multiNewOpt)

  const multiNewInput = document.createElement('input')
  multiNewInput.type = 'text'; multiNewInput.placeholder = 'Group name…'
  multiNewInput.style.cssText = 'display:none;flex:1;background:#0d1117;border:1px solid #30363d;' +
                                 'border-radius:4px;color:#c9d1d9;padding:3px 5px;font-size:11px;font-family:monospace'

  function _multiApplyGroup(groupId) {
    pushGroupUndo()
    const gs = store.getState().strandGroups
    const target = gs.find(g => g.id === groupId)
    store.setState({
      strandGroups: gs.map(g => {
        if (g.id !== groupId) return { ...g, strandIds: g.strandIds.filter(s => !strandIds.includes(s)) }
        return { ...g, strandIds: [...new Set([...g.strandIds, ...strandIds])] }
      }),
    })
    // Persist the group color to each strand on the backend so it survives group removal.
    if (target?.color) {
      for (const sid of strandIds) api.patchStrand(sid, { color: target.color })
    }
    _dismissMenu()
  }

  function _multiCreateAndAssign(name) {
    name = name.trim()
    if (!name) { multiNewInput.style.display = 'none'; multiSel.style.display = ''; return }
    pushGroupUndo()
    const gs = store.getState().strandGroups
    // Check if a group with this name already exists — if so, join it.
    const existing = gs.find(g => g.name === name)
    if (existing) {
      _multiApplyGroup(existing.id)
      return
    }
    const palette = ['#74b9ff','#6bcb77','#ff6b6b','#ffd93d','#a29bfe','#55efc4']
    const color   = palette[gs.length % palette.length]
    const newGroup = { id: `grp_${Date.now()}`, name, color, strandIds: [...strandIds] }
    store.setState({
      strandGroups: [...gs.map(g => ({ ...g, strandIds: g.strandIds.filter(s => !strandIds.includes(s)) })), newGroup],
    })
    // Persist the new group color to each strand on the backend.
    for (const sid of strandIds) api.patchStrand(sid, { color })
    _dismissMenu()
  }

  multiSel.addEventListener('change', e => {
    e.stopPropagation()
    if (multiSel.value === '__new__') {
      multiSel.style.display = 'none'
      multiNewInput.style.display = ''
      multiNewInput.focus()
    } else if (multiSel.value === '') {
      // remove from all groups
      pushGroupUndo()
      const gs = store.getState().strandGroups
      store.setState({ strandGroups: gs.map(g => ({ ...g, strandIds: g.strandIds.filter(s => !strandIds.includes(s)) })) })
      _dismissMenu()
    } else {
      _multiApplyGroup(multiSel.value)
    }
  })

  multiNewInput.addEventListener('keydown', e => {
    e.stopPropagation()
    if (e.key === 'Enter')  _multiCreateAndAssign(multiNewInput.value)
    if (e.key === 'Escape') { multiNewInput.style.display = 'none'; multiSel.style.display = ''; multiSel.value = '' }
  })
  multiNewInput.addEventListener('blur', () => {
    if (multiNewInput.style.display !== 'none') _multiCreateAndAssign(multiNewInput.value)
  })

  multiGrpRow.appendChild(multiSel)
  multiGrpRow.appendChild(multiNewInput)
  menu.appendChild(multiGrpRow)

  // Delete all
  menu.appendChild(_menuSep())
  const delItem = _menuItem(`Delete ${strandIds.length} strand${strandIds.length === 1 ? '' : 's'}`, async () => {
    for (const sid of strandIds) await api.deleteStrand(sid)
  })
  delItem.style.color = '#ff6b6b'
  menu.appendChild(delItem)

  document.body.appendChild(menu)
  _menuEl = menu
  _menuOutsideListeners(menu)
}

function _showNickMenu(x, y, coneEntry, onNick) {
  _dismissMenu()
  const menu = _menuBase(x, y)

  const item = document.createElement('div')
  item.textContent = 'Nick here'
  item.style.cssText = `padding: 6px 14px; color: #eef; cursor: pointer;`
  item.addEventListener('mouseenter', () => { item.style.background = '#2a3a4a' })
  item.addEventListener('mouseleave', () => { item.style.background = 'transparent' })
  item.addEventListener('click', e => {
    e.stopPropagation()
    _dismissMenu()
    const { helix_id, bp_index, direction } = coneEntry.fromNuc
    onNick?.({ helixId: helix_id, bpIndex: bp_index, direction })
  })
  menu.appendChild(item)

  document.body.appendChild(menu)
  _menuEl = menu
  _menuOutsideListeners(menu)
}

function _showLoopSkipMenu(x, y, nuc, onLoopSkip) {
  _dismissMenu()
  const menu = _menuBase(x, y)

  const { helix_id, bp_index } = nuc

  // Check if there's an existing loop/skip at this position
  const design = store.getState().currentDesign
  const helix  = design?.helices?.find(h => h.id === helix_id)
  const existing = helix?.loop_skips?.find(ls => ls.bp_index === bp_index)

  if (existing) {
    menu.appendChild(_menuItem(
      existing.delta === 1 ? 'Remove loop' : 'Remove skip',
      () => onLoopSkip?.({ helixId: helix_id, bpIndex: bp_index, delta: 0 }),
    ))
    menu.appendChild(_menuSep())
  }

  menu.appendChild(_menuItem(
    'Add loop (+1 bp)',
    () => onLoopSkip?.({ helixId: helix_id, bpIndex: bp_index, delta: 1 }),
  ))
  menu.appendChild(_menuItem(
    'Add skip (−1 bp)',
    () => onLoopSkip?.({ helixId: helix_id, bpIndex: bp_index, delta: -1 }),
  ))

  document.body.appendChild(menu)
  _menuEl = menu
  _menuOutsideListeners(menu)
}

// ── Main initialiser ──────────────────────────────────────────────────────────

/**
 * @param {HTMLCanvasElement} canvas
 * @param {THREE.Camera} camera
 * @param {object} designRenderer
 * @param {{ onNick?: Function, onLoopSkip?: Function, onOverhangArrow?: Function, getUnfoldView?: () => object, getOverhangLocations?: () => object, controls?: object }} [opts]
 */
export function initSelectionManager(canvas, camera, designRenderer, opts = {}) {
  const { onNick, onLoopSkip, onOverhangArrow, getUnfoldView, getOverhangLocations, controls } = opts

  // ── State ────────────────────────────────────────────────────────────────
  let _mode            = 'none'   // 'none' | 'strand' | 'bead' | 'cone'
  let _strandId        = null
  let _domainIndex     = null     // domain_index of selected domain (domain/bead modes)
  let _beadEntry       = null
  let _coneEntry       = null
  let _strandEntries     = []     // backbone entries for selected strand
  let _strandConeEntries = []     // cone entries for selected strand
  let _strandArcEntries  = []     // arc entries for selected strand

  // ── Highlight helpers ────────────────────────────────────────────────────

  function _restoreStrand() {
    for (const e of _strandEntries) {
      designRenderer.setEntryColor(e, e.defaultColor)
      designRenderer.setBeadScale(e, 1.0)
    }
    for (const e of _strandConeEntries) {
      designRenderer.setEntryColor(e, e.defaultColor)
      designRenderer.setConeXZScale(e, e.coneRadius)
    }
    for (const e of _strandArcEntries) {
      e.setColor(e.defaultColor)
    }
    _clearSelectionGlow()
    _strandEntries     = []
    _strandConeEntries = []
    _strandArcEntries  = []
    _domainIndex       = null
    _beadEntry         = null
    _coneEntry         = null
  }

  function _highlightStrand(backboneEntries, coneEntries, strandId) {
    _restoreStrand()
    _strandEntries     = backboneEntries.filter(e => e.nuc.strand_id === strandId)
    _strandConeEntries = coneEntries.filter(e => e.strandId === strandId)
    _strandArcEntries  = (getUnfoldView?.()?.getArcEntries() ?? []).filter(e => e.strandId === strandId)
    for (const e of _strandEntries) {
      designRenderer.setBeadScale(e, 1.3)   // scale up; color unchanged
    }
    for (const e of _strandArcEntries) {
      e.setColor(C_SCAFFOLD_FIVE_PRIME)     // green tint for unfold arcs (no glow layer there)
    }
    _setSelectionGlow(_strandEntries)
    // Scaffold 5′/3′ glow — red for 5′ start, blue for 3′ end
    const isScaffold = _strandEntries.length > 0 && _strandEntries[0].nuc.strand_type === 'scaffold'
    if (isScaffold) {
      for (const e of _strandEntries) {
        if (e.nuc.is_five_prime)  { designRenderer.setEntryColor(e, C_SCAFFOLD_FIVE_PRIME);  designRenderer.setBeadScale(e, 2.0) }
        if (e.nuc.is_three_prime) { designRenderer.setEntryColor(e, C_SCAFFOLD_THREE_PRIME); designRenderer.setBeadScale(e, 2.0) }
      }
    }
  }

  function _highlightDomain(domainIdx) {
    for (const e of _strandEntries) {
      designRenderer.setBeadScale(e, e.nuc.domain_index === domainIdx ? 1.5 : 0.9)
    }
    _domainIndex = domainIdx
    _setSelectionGlow(_strandEntries.filter(e => e.nuc.domain_index === domainIdx))
  }

  function _highlightBead(entry) {
    for (const e of _strandEntries) {
      designRenderer.setBeadScale(e, e === entry ? 1.6 : 1.2)
    }
    _beadEntry = entry
    _setSelectionGlow([entry])
  }

  function _highlightCone(entry) {
    for (const e of _strandConeEntries) {
      designRenderer.setConeXZScale(e, e === entry ? 0.12 : e.coneRadius)
      designRenderer.setEntryColor(e, e === entry ? C_SELECT_CONE : C_SELECT_STRAND)
    }
    _coneEntry = entry
  }

  function _clearAll() {
    _restoreStrand()
    _mode     = 'none'
    _strandId = null
    store.setState({ selectedObject: null })
  }

  // ── Multi-selection (Ctrl+drag rectangle lasso) ──────────────────────────

  let _inLassoMode     = false
  let _lassoStart      = null   // { x, y } in client coords
  let _lassoOverlay    = null   // <div> rubber-band rect
  let _multiStrandIds  = []
  let _multiEntries    = []
  let _multiConeEntries = []

  function _createLassoOverlay() {
    const div = document.createElement('div')
    div.style.cssText = 'position:fixed;border:1.5px dashed #74b9ff;background:rgba(116,185,255,0.07);' +
                        'pointer-events:none;z-index:1000;box-sizing:border-box'
    document.body.appendChild(div)
    return div
  }

  function _updateLassoOverlay(x1, y1, x2, y2) {
    if (!_lassoOverlay) return
    _lassoOverlay.style.left   = Math.min(x1, x2) + 'px'
    _lassoOverlay.style.top    = Math.min(y1, y2) + 'px'
    _lassoOverlay.style.width  = Math.abs(x2 - x1) + 'px'
    _lassoOverlay.style.height = Math.abs(y2 - y1) + 'px'
  }

  function _applyMultiHighlight(strandIds) {
    // Restore previous multi-highlight without touching store
    for (const e of _multiEntries)     { designRenderer.setEntryColor(e, e.defaultColor); designRenderer.setBeadScale(e, 1.0) }
    for (const e of _multiConeEntries) { designRenderer.setEntryColor(e, e.defaultColor) }
    _multiEntries     = designRenderer.getBackboneEntries().filter(e => strandIds.includes(e.nuc.strand_id))
    _multiConeEntries = designRenderer.getConeEntries().filter(e => strandIds.includes(e.strandId))
    _multiStrandIds   = strandIds
    for (const e of _multiEntries)     { designRenderer.setEntryColor(e, C_SELECT_STRAND); designRenderer.setBeadScale(e, 1.3) }
    for (const e of _multiConeEntries) { designRenderer.setEntryColor(e, C_SELECT_STRAND) }
  }

  function _clearMultiSelection() {
    for (const e of _multiEntries)     { designRenderer.setEntryColor(e, e.defaultColor); designRenderer.setBeadScale(e, 1.0) }
    for (const e of _multiConeEntries) { designRenderer.setEntryColor(e, e.defaultColor) }
    _multiEntries      = []
    _multiConeEntries  = []
    _multiStrandIds    = []
    store.setState({ multiSelectedStrandIds: [] })
  }

  // ── Ctrl+click nucleotide selection ─────────────────────────────────────

  const C_CTRL_BEAD = 0x00e5ff   // cyan — distinct from selection white and fc orange

  let _ctrlBeads            = []   // [{entry, nuc}, ...] individually ctrl-picked beads
  let _ctrlBeadsChangeCb    = null
  let _selectionGlowEntries = []   // current glow from regular strand/bead selection

  // Merged glow: always combines selection glow + ctrl bead glow.
  function _setSelectionGlow(entries) {
    _selectionGlowEntries = entries
    designRenderer.setGlowEntries([..._selectionGlowEntries, ..._ctrlBeads.map(b => b.entry)])
  }

  function _clearSelectionGlow() {
    _selectionGlowEntries = []
    const ctrlEntries = _ctrlBeads.map(b => b.entry)
    if (ctrlEntries.length) designRenderer.setGlowEntries(ctrlEntries)
    else                    designRenderer.clearGlow()
  }

  function _refreshCtrlGlow() {
    designRenderer.setGlowEntries([..._selectionGlowEntries, ..._ctrlBeads.map(b => b.entry)])
  }

  function _notifyCtrlBeadsChange() {
    _ctrlBeadsChangeCb?.([..._ctrlBeads])
  }

  function _clearCtrlBeads() {
    for (const b of _ctrlBeads) {
      designRenderer.setEntryColor(b.entry, b.entry.defaultColor)
      designRenderer.setBeadScale(b.entry, 1.0)
      if (b.entry.instMesh.instanceColor)  b.entry.instMesh.instanceColor.needsUpdate  = true
      if (b.entry.instMesh.instanceMatrix) b.entry.instMesh.instanceMatrix.needsUpdate = true
    }
    _ctrlBeads = []
    _refreshCtrlGlow()
    _notifyCtrlBeadsChange()
  }

  function _handleCtrlClickNuc(e) {
    if (e.clientX > window.innerWidth - 300) return

    _setNdc(e.clientX, e.clientY)
    raycaster.setFromCamera(_ndc, camera)

    const backboneEntries = designRenderer.getBackboneEntries()
    const beadMeshes = [...new Set(backboneEntries.map(be => be.instMesh))]
    const hits = raycaster.intersectObjects(beadMeshes)

    if (!hits.length) {
      _clearCtrlBeads()
      return
    }

    const hit = hits[0]
    const entry = backboneEntries.find(be => be.instMesh === hit.object && be.id === hit.instanceId)
    if (!entry) { _clearCtrlBeads(); return }

    const idx = _ctrlBeads.findIndex(b =>
      b.nuc.helix_id  === entry.nuc.helix_id &&
      b.nuc.bp_index  === entry.nuc.bp_index &&
      b.nuc.direction === entry.nuc.direction
    )
    if (idx >= 0) {
      // Deselect
      designRenderer.setEntryColor(_ctrlBeads[idx].entry, _ctrlBeads[idx].entry.defaultColor)
      designRenderer.setBeadScale(_ctrlBeads[idx].entry, 1.0)
      if (_ctrlBeads[idx].entry.instMesh.instanceColor)  _ctrlBeads[idx].entry.instMesh.instanceColor.needsUpdate  = true
      if (_ctrlBeads[idx].entry.instMesh.instanceMatrix) _ctrlBeads[idx].entry.instMesh.instanceMatrix.needsUpdate = true
      _ctrlBeads.splice(idx, 1)
    } else {
      // Select
      designRenderer.setEntryColor(entry, C_CTRL_BEAD)
      designRenderer.setBeadScale(entry, 1.6)
      if (entry.instMesh.instanceColor)  entry.instMesh.instanceColor.needsUpdate  = true
      if (entry.instMesh.instanceMatrix) entry.instMesh.instanceMatrix.needsUpdate = true
      _ctrlBeads.push({ entry, nuc: entry.nuc })
    }
    _refreshCtrlGlow()
    _notifyCtrlBeadsChange()
  }

  function _finalizeLasso(endX, endY) {
    _inLassoMode = false
    canvas.style.cursor = ''
    if (_lassoOverlay) { _lassoOverlay.remove(); _lassoOverlay = null }
    if (!_lassoStart) return

    const sx1 = Math.min(_lassoStart.x, endX)
    const sy1 = Math.min(_lassoStart.y, endY)
    const sx2 = Math.max(_lassoStart.x, endX)
    const sy2 = Math.max(_lassoStart.y, endY)
    _lassoStart = null

    if (sx2 - sx1 < 4 && sy2 - sy1 < 4) return   // too small — treat as click-miss

    // Convert lasso rect from client→canvas-relative coords for _toScreen comparison
    const rect = canvas.getBoundingClientRect()
    const cx1 = sx1 - rect.left,  cy1 = sy1 - rect.top
    const cx2 = sx2 - rect.left,  cy2 = sy2 - rect.top

    const mat = new THREE.Matrix4()
    const pos = new THREE.Vector3()
    const strandIdSet = new Set()

    for (const entry of designRenderer.getBackboneEntries()) {
      if (entry.nuc.strand_type !== 'staple') continue
      if (!entry.nuc.strand_id) continue
      entry.instMesh.getMatrixAt(entry.id, mat)
      pos.setFromMatrixPosition(mat)
      const sp = _toScreen(pos)
      if (sp.x >= cx1 && sp.x <= cx2 && sp.y >= cy1 && sp.y <= cy2) {
        strandIdSet.add(entry.nuc.strand_id)
      }
    }

    const strandIds = [...strandIdSet]
    if (!strandIds.length) return

    _applyMultiHighlight(strandIds)
    store.setState({ multiSelectedStrandIds: strandIds })
  }

  // ── Shared NDC + screen helpers ──────────────────────────────────────────

  function _setNdc(clientX, clientY) {
    const rect = canvas.getBoundingClientRect()
    _ndc.set(
      ((clientX - rect.left) / rect.width)  *  2 - 1,
      -((clientY - rect.top)  / rect.height) * 2 + 1,
    )
  }

  /** Project a world position to canvas-relative screen coordinates. */
  function _toScreen(worldPos) {
    const v    = worldPos.clone().project(camera)
    const rect = canvas.getBoundingClientRect()
    return {
      x: (v.x *  0.5 + 0.5) * rect.width,
      y: (v.y * -0.5 + 0.5) * rect.height,
    }
  }

  /**
   * Find the arc entry whose midpoint is closest to (sx, sy) in screen space,
   * within _arcHitPx pixels.  Returns null if nothing is close enough.
   */
  function _findArcAt(sx, sy) {
    const arcEntries = getUnfoldView?.()?.getArcEntries() ?? []
    if (!arcEntries.length) return null
    let best = null, bestDist = _arcHitPx
    for (const e of arcEntries) {
      const sp = _toScreen(e.getMidWorld())
      const d  = Math.hypot(sp.x - sx, sp.y - sy)
      if (d < bestDist) { bestDist = d; best = e }
    }
    return best
  }

  // ── Left-click ───────────────────────────────────────────────────────────

  // Capture-phase: disable controls before OrbitControls sees Ctrl+left so it
  // cannot start a pan gesture that competes with the lasso drag.
  canvas.addEventListener('pointerdown', e => {
    if (e.button === 0 && e.ctrlKey && controls) controls.enabled = false
  }, { capture: true })

  let _downPos     = null
  let _ctrlDownPos = null   // pending ctrl+left-down — becomes lasso (drag) or nucleotide pick (click)

  canvas.addEventListener('pointerdown', e => {
    if (e.button !== 0) return

    // Ctrl+left — defer: determine on move/up whether this is a lasso drag or a nucleotide pick
    if (e.ctrlKey) {
      _ctrlDownPos = { x: e.clientX, y: e.clientY }
      return
    }

    // Regular left click — clear any active multi-selection
    if (_multiStrandIds.length > 0) _clearMultiSelection()

    _downPos = { x: e.clientX, y: e.clientY }

    // Disable OrbitControls for this click if a bead or cone is under the cursor,
    // so the camera does not drift when the user selects a strand.
    if (controls) {
      _setNdc(e.clientX, e.clientY)
      raycaster.setFromCamera(_ndc, camera)
      const beadMeshes = [...new Set(designRenderer.getBackboneEntries().map(e => e.instMesh))]
      const coneMeshes = [...new Set(designRenderer.getConeEntries().map(e => e.instMesh))]
      const beadHit = raycaster.intersectObjects(beadMeshes).length > 0
      const coneHit = raycaster.intersectObjects(coneMeshes).length > 0
      if (beadHit || coneHit) controls.enabled = false
    }
  })

  canvas.addEventListener('pointermove', e => {
    // If ctrl is held and we haven't yet started a lasso, check if the drag threshold is exceeded.
    if (_ctrlDownPos && !_inLassoMode) {
      if (Math.hypot(e.clientX - _ctrlDownPos.x, e.clientY - _ctrlDownPos.y) > 4) {
        _inLassoMode  = true
        _lassoStart   = _ctrlDownPos
        _ctrlDownPos  = null
        _lassoOverlay = _createLassoOverlay()
        _updateLassoOverlay(_lassoStart.x, _lassoStart.y, e.clientX, e.clientY)
        canvas.style.cursor = 'crosshair'
        _clearAll()
        _clearMultiSelection()
      }
      return
    }
    if (!_inLassoMode || !_lassoStart) return
    _updateLassoOverlay(_lassoStart.x, _lassoStart.y, e.clientX, e.clientY)
  })

  canvas.addEventListener('pointerup', e => {
    if (controls) controls.enabled = true
    if (e.button !== 0) return

    // Lasso finalize
    if (_inLassoMode) {
      _ctrlDownPos = null
      _finalizeLasso(e.clientX, e.clientY)
      return
    }

    // Ctrl+left click (no drag) → toggle nucleotide in ctrl-select set
    if (_ctrlDownPos) {
      const moved = Math.hypot(e.clientX - _ctrlDownPos.x, e.clientY - _ctrlDownPos.y)
      _ctrlDownPos = null
      if (moved <= 4) _handleCtrlClickNuc(e)
      return
    }

    if (_downPos && Math.hypot(e.clientX - _downPos.x, e.clientY - _downPos.y) > 4) return
    if (e.clientX > window.innerWidth - 300) return

    _dismissMenu()

    // Regular (non-ctrl) click clears the ctrl-click nucleotide selection
    if (_ctrlBeads.length > 0) _clearCtrlBeads()

    _setNdc(e.clientX, e.clientY)
    raycaster.setFromCamera(_ndc, camera)

    const { selectableTypes } = store.getState()

    const backboneEntries = designRenderer.getBackboneEntries()
    const coneEntries     = designRenderer.getConeEntries()

    // Respect selection filter
    const selBackbone = backboneEntries.filter(e =>
      e.nuc.strand_type === 'scaffold' ? selectableTypes.scaffold : selectableTypes.staples
    )
    const selCones = coneEntries.filter(e => {
      const isScaf = e.fromNuc?.strand_type === 'scaffold'
      return isScaf ? selectableTypes.scaffold : selectableTypes.staples
    })

    // Raycast against all unique InstancedMeshes, then find the closest
    // intersection whose instanceId belongs to a selectable entry.
    const beadMeshes = [...new Set(backboneEntries.map(e => e.instMesh))]
    const coneMeshes = [...new Set(coneEntries.map(e => e.instMesh))]

    const allBeadHits = raycaster.intersectObjects(beadMeshes)
    const allConeHits = raycaster.intersectObjects(coneMeshes)

    const beadHit0 = allBeadHits.find(h =>
      selBackbone.some(e => e.instMesh === h.object && e.id === h.instanceId))
    const coneHit0 = allConeHits.find(h =>
      selCones.some(e => e.instMesh === h.object && e.id === h.instanceId))

    const beadDist = beadHit0?.distance ?? Infinity
    const coneDist = coneHit0?.distance ?? Infinity

    if (beadDist === Infinity && coneDist === Infinity) {
      // No bead or cone hit — try arc proximity.
      const rect2 = canvas.getBoundingClientRect()
      const arcHit = _findArcAt(e.clientX - rect2.left, e.clientY - rect2.top)
      if (!arcHit || !arcHit.strandId) { _clearAll(); return }

      const hitStrandId = arcHit.strandId
      if (_mode === 'none' || hitStrandId !== _strandId) {
        _mode     = 'strand'
        _strandId = hitStrandId
        _highlightStrand(backboneEntries, coneEntries, hitStrandId)
        store.setState({
          selectedObject: {
            type: 'strand',
            id:   hitStrandId,
            data: { strand_id: hitStrandId },
          },
        })
      } else {
        // Second click on same strand arc → select as cone-equivalent
        _mode = 'cone'
        const { fromNuc, toNuc } = arcHit
        store.setState({
          selectedObject: {
            type: 'cone',
            id:   `${fromNuc.helix_id}:${fromNuc.bp_index}:${fromNuc.direction}→${toNuc.helix_id}:${toNuc.bp_index}:${toNuc.direction}`,
            data: { fromNuc, toNuc, strand_id: hitStrandId },
          },
        })
      }
      return
    }

    if (coneDist < beadDist) {
      // ── Cone hit ────────────────────────────────────────────────────────
      const hitCone = selCones.find(e => e.instMesh === coneHit0.object && e.id === coneHit0.instanceId)
      if (!hitCone) return
      const hitStrandId = hitCone.strandId

      if (_mode === 'none' || hitStrandId !== _strandId) {
        _mode     = 'strand'
        _strandId = hitStrandId
        _highlightStrand(backboneEntries, coneEntries, hitStrandId)
        store.setState({
          selectedObject: {
            type: 'strand',
            id:   hitStrandId,
            data: { strand_id: hitStrandId },
          },
        })
      } else {
        // Second click within same strand → select this cone
        _mode = 'cone'
        _highlightCone(hitCone)
        const { fromNuc, toNuc } = hitCone
        store.setState({
          selectedObject: {
            type: 'cone',
            id:   `${fromNuc.helix_id}:${fromNuc.bp_index}:${fromNuc.direction}→${toNuc.helix_id}:${toNuc.bp_index}:${toNuc.direction}`,
            data: { fromNuc, toNuc, strand_id: hitStrandId },
          },
        })
      }
    } else {
      // ── Bead hit ────────────────────────────────────────────────────────
      const hitEntry = selBackbone.find(e => e.instMesh === beadHit0.object && e.id === beadHit0.instanceId)
      if (!hitEntry) return
      const hitStrandId = hitEntry.nuc.strand_id

      if (_mode === 'none' || hitStrandId !== _strandId) {
        // New strand → select strand
        _mode      = 'strand'
        _strandId  = hitStrandId
        _coneEntry = null
        _highlightStrand(backboneEntries, coneEntries, hitStrandId)
        store.setState({
          selectedObject: {
            type: 'strand',
            id:   hitStrandId ?? `unassigned:${hitEntry.nuc.helix_id}:${hitEntry.nuc.direction}`,
            data: { strand_id: hitStrandId, helix_id: hitEntry.nuc.helix_id },
          },
        })
      } else if (_mode === 'strand') {
        // Second click on same strand → select individual nucleotide
        _mode = 'bead'
        _highlightBead(hitEntry)
        store.setState({
          selectedObject: {
            type: 'nucleotide',
            id:   `${hitEntry.nuc.helix_id}:${hitEntry.nuc.bp_index}:${hitEntry.nuc.direction}`,
            data: hitEntry.nuc,
          },
        })
      } else if (
        _mode === 'bead' && _beadEntry &&
        _beadEntry.nuc.helix_id  === hitEntry.nuc.helix_id &&
        _beadEntry.nuc.bp_index  === hitEntry.nuc.bp_index &&
        _beadEntry.nuc.direction === hitEntry.nuc.direction
      ) {
        // Same bead clicked while already in bead mode → deselect
        _clearAll()
      } else {
        // Different bead in bead mode → select that bead
        _mode = 'bead'
        _highlightBead(hitEntry)
        store.setState({
          selectedObject: {
            type: 'nucleotide',
            id:   `${hitEntry.nuc.helix_id}:${hitEntry.nuc.bp_index}:${hitEntry.nuc.direction}`,
            data: hitEntry.nuc,
          },
        })
      }
    }
  })

  // ── Right-click ──────────────────────────────────────────────────────────

  let _rightDownPos = null

  canvas.addEventListener('pointerdown', e => {
    if (e.button === 2) _rightDownPos = { x: e.clientX, y: e.clientY }
  })

  canvas.addEventListener('contextmenu', e => {
    e.preventDefault()
    if (!_rightDownPos) return
    const moved = Math.hypot(e.clientX - _rightDownPos.x, e.clientY - _rightDownPos.y)
    _rightDownPos = null
    if (moved > 4) return

    // Multi-selection right-click — show multi-strand menu
    if (_multiStrandIds.length > 0) {
      _showMultiMenu(e.clientX, e.clientY, _multiStrandIds, designRenderer)
      return
    }

    // Cast ray to check for a cone hit first.
    _setNdc(e.clientX, e.clientY)
    raycaster.setFromCamera(_ndc, camera)

    const coneEntries = designRenderer.getConeEntries()
    const coneMeshes  = [...new Set(coneEntries.map(e => e.instMesh))]
    const coneHits    = raycaster.intersectObjects(coneMeshes)

    // In bead mode, skip cone/arc checks — always show loop/skip menu for the selected bead.
    // (In domain mode we fall through to the color/isolate menu below.)
    if (_mode === 'bead' && _beadEntry?.nuc && onLoopSkip) {
      _showLoopSkipMenu(e.clientX, e.clientY, _beadEntry.nuc, onLoopSkip)
      return
    }

    // Check overhang arrow hit before cones (arrows are intentional targets).
    if (onOverhangArrow) {
      const ol = getOverhangLocations?.()
      if (ol?.isVisible()) {
        const arrowEntry = ol.hitTest(raycaster)
        if (arrowEntry) {
          onOverhangArrow(arrowEntry, e.clientX, e.clientY)
          return
        }
      }
    }

    if (coneHits.length) {
      const hitCone = coneEntries.find(c => c.instMesh === coneHits[0].object && c.id === coneHits[0].instanceId)
      if (hitCone) {
        // In strand or bead mode, right-clicking the selected strand shows the color/isolate menu
        if ((_mode === 'strand' || _mode === 'bead') && hitCone.strandId === _strandId) {
          _showColorMenu(e.clientX, e.clientY, _strandId, designRenderer)
          return
        }
        _showNickMenu(e.clientX, e.clientY, hitCone, onNick)
        return
      }
    }

    // No visible cone hit — check arc proximity (cross-helix connections).
    const rect3 = canvas.getBoundingClientRect()
    const arcHit = _findArcAt(e.clientX - rect3.left, e.clientY - rect3.top)
    if (arcHit?.fromNuc) {
      // In strand or bead mode, right-clicking the selected strand's arc shows the color/isolate menu
      if ((_mode === 'strand' || _mode === 'bead') && arcHit.strandId === _strandId) {
        _showColorMenu(e.clientX, e.clientY, _strandId, designRenderer)
        return
      }
      _showNickMenu(e.clientX, e.clientY, { fromNuc: arcHit.fromNuc, toNuc: arcHit.toNuc }, onNick)
      return
    }

    // No cone/arc hit
    if (_mode === 'none' || !_strandId) return
    _showColorMenu(e.clientX, e.clientY, _strandId, designRenderer)
  })

  // ── Re-apply highlights after scene rebuild ──────────────────────────────

  store.subscribe((newState, prevState) => {
    // strandGroups changes trigger a 3D scene rebuild in design_renderer, which
    // replaces all InstancedMesh objects — treat it the same as a geometry change
    // so cached entry references are refreshed and highlights stay correct.
    if (newState.currentGeometry === prevState.currentGeometry &&
        newState.strandGroups    === prevState.strandGroups) return
    _strandEntries     = []
    _strandConeEntries = []
    _strandArcEntries  = []
    _beadEntry         = null
    _coneEntry         = null
    // Re-apply multi-selection highlight after rebuild
    _multiEntries      = []
    _multiConeEntries  = []
    if (_multiStrandIds.length > 0) _applyMultiHighlight(_multiStrandIds)
    // Ctrl-selected beads become stale after a rebuild — clear them
    if (_ctrlBeads.length > 0) { _ctrlBeads = []; _notifyCtrlBeadsChange() }

    const backboneEntries = designRenderer.getBackboneEntries()
    const coneEntries     = designRenderer.getConeEntries()

    if (_mode === 'strand' && _strandId) {
      _highlightStrand(backboneEntries, coneEntries, _strandId)

    } else if (_mode === 'bead' && _strandId) {
      _highlightStrand(backboneEntries, coneEntries, _strandId)
      const sel = newState.selectedObject?.data
      if (sel) {
        const found = backboneEntries.find(e =>
          e.nuc.helix_id  === sel.helix_id  &&
          e.nuc.bp_index  === sel.bp_index  &&
          e.nuc.direction === sel.direction
        )
        if (found) _highlightBead(found)
        else {
          _mode = 'strand'
          store.setState({ selectedObject: { type: 'strand', id: _strandId, data: { strand_id: _strandId } } })
        }
      }

    } else if (_mode === 'cone' && _strandId) {
      _highlightStrand(backboneEntries, coneEntries, _strandId)
      const sel = newState.selectedObject?.data
      if (sel?.fromNuc) {
        const found = coneEntries.find(e =>
          e.fromNuc.helix_id  === sel.fromNuc.helix_id  &&
          e.fromNuc.bp_index  === sel.fromNuc.bp_index  &&
          e.fromNuc.direction === sel.fromNuc.direction
        )
        if (found) _highlightCone(found)
        else {
          _mode = 'strand'
          store.setState({ selectedObject: { type: 'strand', id: _strandId, data: { strand_id: _strandId } } })
        }
      }

    } else {
      _mode = 'none'
      store.setState({ selectedObject: null })
    }
  })

  return {
    /** Programmatically select a strand by ID, applying the same 3D highlight
     *  as a manual bead click (white beads at 1.3× scale). */
    selectStrand(strandId) {
      const backboneEntries = designRenderer.getBackboneEntries()
      const coneEntries     = designRenderer.getConeEntries()
      _mode     = 'strand'
      _strandId = strandId
      _coneEntry = null
      _highlightStrand(backboneEntries, coneEntries, strandId)
      store.setState({ selectedObject: { type: 'strand', id: strandId, data: { strand_id: strandId } } })
    },

    /** Returns a copy of the current ctrl-click nucleotide selection. */
    getCtrlBeads() { return [..._ctrlBeads] },

    /** Returns the world-space THREE.Vector3 for the nth ctrl-selected bead (0-indexed). */
    getCtrlBeadPos(n) { return _ctrlBeads[n]?.entry.pos.clone() ?? null },

    /** Register a callback fired whenever _ctrlBeads changes. */
    onCtrlBeadsChange(fn) { _ctrlBeadsChangeCb = fn },

    /** Programmatically clear all ctrl-selected beads. */
    clearCtrlBeads() { _clearCtrlBeads() },
  }
}
