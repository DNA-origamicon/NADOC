/**
 * Selection manager — raycaster-based click-to-select with two-click model.
 *
 * Click model:
 *   First click on a bead  → select the entire strand (all beads highlighted).
 *   Second click on a bead in the same strand → select that single bead.
 *   Click on empty space   → clear selection.
 *
 * Right-click (contextmenu) when a strand is selected:
 *   Shows a colour-picker menu with 12 preset colours.
 *   Selecting a colour applies it persistently via designRenderer.setStrandColor().
 *
 * Selection state is stored in the Vuex-style store as selectedObject:
 *   { type: 'strand',     id: strandId, data: { strand_id } }
 *   { type: 'nucleotide', id: 'helixId:bp:dir', data: nuc }
 *   null — nothing selected
 */

import * as THREE from 'three'
import { store } from '../state/store.js'

// ── Colour constants ───────────────────────────────────────────────────────────

const C_SELECT_STRAND = 0xffffff   // strand-selected bead colour
const C_SELECT_BEAD   = 0xffffff   // single-bead selected colour

// 12-colour picker palette (must match STAPLE_PALETTE in helix_renderer for consistency)
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

const raycaster = new THREE.Raycaster()
const _ndc      = new THREE.Vector2()

// ── Context menu ──────────────────────────────────────────────────────────────

let _menuEl = null   // currently shown menu element

function _dismissMenu() {
  if (_menuEl) {
    _menuEl.remove()
    _menuEl = null
  }
}

function _showColorMenu(x, y, strandId, designRenderer) {
  _dismissMenu()

  const menu = document.createElement('div')
  menu.style.cssText = `
    position: fixed; left: ${x}px; top: ${y}px;
    background: #1e2a3a; border: 1px solid #3a4a5a; border-radius: 6px;
    padding: 6px 0; min-width: 120px; z-index: 9999;
    box-shadow: 0 4px 16px rgba(0,0,0,0.5); font-family: monospace; font-size: 12px;
  `

  // "Color" header row
  const header = document.createElement('div')
  header.textContent = 'Color'
  header.style.cssText = `
    padding: 4px 12px; color: #8899aa; font-size: 11px; letter-spacing: 0.05em;
    text-transform: uppercase; border-bottom: 1px solid #3a4a5a; margin-bottom: 4px;
  `
  menu.appendChild(header)

  // Colour swatches grid
  const grid = document.createElement('div')
  grid.style.cssText = `
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 4px; padding: 4px 8px;
  `
  for (const { hex, css, label } of PICKER_COLORS) {
    const swatch = document.createElement('div')
    swatch.title = label
    swatch.style.cssText = `
      width: 20px; height: 20px; border-radius: 3px; cursor: pointer;
      background: ${css}; border: 2px solid transparent;
      transition: border-color 0.1s;
    `
    swatch.addEventListener('mouseenter', () => {
      swatch.style.borderColor = '#ffffff'
    })
    swatch.addEventListener('mouseleave', () => {
      swatch.style.borderColor = 'transparent'
    })
    swatch.addEventListener('click', e => {
      e.stopPropagation()
      designRenderer.setStrandColor(strandId, hex)
      _dismissMenu()
    })
    grid.appendChild(swatch)
  }
  menu.appendChild(grid)

  document.body.appendChild(menu)
  _menuEl = menu

  // Dismiss on outside click or Escape
  const _outsideClick = e => {
    if (!menu.contains(e.target)) {
      _dismissMenu()
      document.removeEventListener('pointerdown', _outsideClick)
      document.removeEventListener('keydown', _escKey)
    }
  }
  const _escKey = e => {
    if (e.key === 'Escape') {
      _dismissMenu()
      document.removeEventListener('pointerdown', _outsideClick)
      document.removeEventListener('keydown', _escKey)
    }
  }
  // Slight delay so the pointerdown that opened the menu doesn't instantly close it
  setTimeout(() => {
    document.addEventListener('pointerdown', _outsideClick)
    document.addEventListener('keydown', _escKey)
  }, 0)
}

// ── Main initialiser ──────────────────────────────────────────────────────────

/**
 * @param {HTMLCanvasElement} canvas
 * @param {THREE.Camera} camera
 * @param {import('./design_renderer.js').initDesignRenderer} designRenderer
 */
export function initSelectionManager(canvas, camera, designRenderer) {
  // Selection state
  let _mode       = 'none'    // 'none' | 'strand' | 'bead'
  let _strandId   = null      // selected strand_id (in both 'strand' and 'bead' modes)
  let _beadEntry  = null      // selected single bead entry (in 'bead' mode only)
  let _strandEntries = []     // all bead entries of the current strand

  // ── Highlight helpers ────────────────────────────────────────────────────

  function _restoreStrand() {
    for (const e of _strandEntries) {
      e.mesh.material.color.setHex(e.defaultColor)
      e.mesh.scale.setScalar(1.0)
    }
    _strandEntries = []
  }

  function _highlightStrand(entries, strandId) {
    _restoreStrand()
    _strandEntries = entries.filter(e => e.nuc.strand_id === strandId)
    for (const e of _strandEntries) {
      e.mesh.material.color.setHex(C_SELECT_STRAND)
      e.mesh.scale.setScalar(1.3)
    }
  }

  function _highlightBead(entry) {
    // Keep all strand beads white/scaled-1.3, but emphasise the chosen bead.
    for (const e of _strandEntries) {
      e.mesh.scale.setScalar(e === entry ? 1.6 : 1.2)
    }
    _beadEntry = entry
  }

  function _clearAll() {
    _restoreStrand()
    _mode     = 'none'
    _strandId = null
    _beadEntry = null
    store.setState({ selectedObject: null })
  }

  // ── Pointer click (left button) ──────────────────────────────────────────

  let _downPos = null

  canvas.addEventListener('pointerdown', e => {
    if (e.button === 0) _downPos = { x: e.clientX, y: e.clientY }
  })

  canvas.addEventListener('pointerup', e => {
    if (e.button !== 0) return
    // Ignore if pointer moved (OrbitControls drag)
    if (_downPos && Math.hypot(e.clientX - _downPos.x, e.clientY - _downPos.y) > 4) return
    // Ignore clicks in right panel area
    if (e.clientX > window.innerWidth - 300) return

    _dismissMenu()

    const rect = canvas.getBoundingClientRect()
    _ndc.set(
      ((e.clientX - rect.left) / rect.width)  * 2 - 1,
      -((e.clientY - rect.top)  / rect.height) * 2 + 1,
    )
    raycaster.setFromCamera(_ndc, camera)

    const entries = designRenderer.getBackboneEntries()
    const hits    = raycaster.intersectObjects(entries.map(e => e.mesh))

    if (!hits.length) {
      _clearAll()
      return
    }

    const hitEntry  = entries.find(e => e.mesh === hits[0].object)
    if (!hitEntry) return
    const hitStrandId = hitEntry.nuc.strand_id

    if (_mode === 'none' || hitStrandId !== _strandId) {
      // ── First click (or click on a different strand) → select whole strand ──
      _mode     = 'strand'
      _strandId = hitStrandId
      _beadEntry = null
      _highlightStrand(entries, hitStrandId)
      store.setState({
        selectedObject: {
          type: 'strand',
          id:   hitStrandId ?? `unassigned:${hitEntry.nuc.helix_id}:${hitEntry.nuc.direction}`,
          data: { strand_id: hitStrandId, helix_id: hitEntry.nuc.helix_id },
        },
      })

    } else if (_mode === 'strand') {
      // ── Second click within same strand → select individual bead ──
      _mode = 'bead'
      _highlightBead(hitEntry)
      store.setState({
        selectedObject: {
          type: 'nucleotide',
          id:   `${hitEntry.nuc.helix_id}:${hitEntry.nuc.bp_index}:${hitEntry.nuc.direction}`,
          data: hitEntry.nuc,
        },
      })

    } else {
      // Already in bead mode within same strand → re-select a different bead
      _highlightBead(hitEntry)
      store.setState({
        selectedObject: {
          type: 'nucleotide',
          id:   `${hitEntry.nuc.helix_id}:${hitEntry.nuc.bp_index}:${hitEntry.nuc.direction}`,
          data: hitEntry.nuc,
        },
      })
    }
  })

  // ── Right-click colour menu ──────────────────────────────────────────────

  let _rightDownPos = null

  canvas.addEventListener('pointerdown', e => {
    if (e.button === 2) _rightDownPos = { x: e.clientX, y: e.clientY }
  })

  canvas.addEventListener('contextmenu', e => {
    e.preventDefault()
    if (!_rightDownPos) return
    const moved = Math.hypot(e.clientX - _rightDownPos.x, e.clientY - _rightDownPos.y)
    _rightDownPos = null
    if (moved > 4) return   // was a camera-pan drag, not a click
    if (_mode === 'none' || !_strandId) return
    _showColorMenu(e.clientX, e.clientY, _strandId, designRenderer)
  })

  // ── Re-apply highlights after scene rebuild ──────────────────────────────

  store.subscribe((newState, prevState) => {
    if (newState.currentGeometry === prevState.currentGeometry) return
    // Scene rebuilt — re-apply highlight state from scratch.
    _strandEntries = []
    _beadEntry     = null
    const entries  = designRenderer.getBackboneEntries()

    if (_mode === 'strand' && _strandId) {
      _highlightStrand(entries, _strandId)
    } else if (_mode === 'bead' && _strandId) {
      _highlightStrand(entries, _strandId)
      const sel  = newState.selectedObject?.data
      if (sel) {
        const found = entries.find(e =>
          e.nuc.helix_id  === sel.helix_id  &&
          e.nuc.bp_index  === sel.bp_index  &&
          e.nuc.direction === sel.direction
        )
        if (found) _highlightBead(found)
        else {
          _mode = 'strand'
          store.setState({
            selectedObject: {
              type: 'strand',
              id:   _strandId,
              data: { strand_id: _strandId },
            },
          })
        }
      }
    } else {
      _mode = 'none'
      store.setState({ selectedObject: null })
    }
  })
}
