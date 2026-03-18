/**
 * Selection manager — raycaster-based click-to-select with two-click model.
 *
 * Click model (beads and cones both participate):
 *   First click on a bead/cone → select the entire strand.
 *   Second click on a bead in the same strand → select that individual bead.
 *   Third click on the same bead (bead mode) → deselect (clear selection).
 *   Click on a different bead in the same strand (bead mode) → select that bead.
 *   Second click on a cone in the same strand → select that individual cone.
 *   Click on empty space → clear selection.
 *
 * Right-click behaviour:
 *   On a cone (any mode) → "Nick here" context menu.
 *   On a bead (strand selected) → colour-picker menu.
 *
 * Selection state is stored in the store as selectedObject:
 *   { type: 'strand',     id, data: { strand_id } }
 *   { type: 'nucleotide', id, data: nuc }
 *   { type: 'cone',       id, data: { fromNuc, toNuc, strand_id } }
 *   null — nothing selected
 */

import * as THREE from 'three'
import { store } from '../state/store.js'

// ── Colour constants ───────────────────────────────────────────────────────────

const C_SELECT_STRAND        = 0xffffff
const C_SELECT_BEAD          = 0xffffff
const C_SELECT_CONE          = 0xffffff
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
 * @param {{ onNick?: Function, onLoopSkip?: Function, getUnfoldView?: () => object, controls?: object }} [opts]
 */
export function initSelectionManager(canvas, camera, designRenderer, opts = {}) {
  const { onNick, onLoopSkip, getUnfoldView, controls } = opts

  // ── State ────────────────────────────────────────────────────────────────
  let _mode            = 'none'   // 'none' | 'strand' | 'bead' | 'cone'
  let _strandId        = null
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
    _strandEntries     = []
    _strandConeEntries = []
    _strandArcEntries  = []
    _beadEntry         = null
    _coneEntry         = null
  }

  function _highlightStrand(backboneEntries, coneEntries, strandId) {
    _restoreStrand()
    _strandEntries     = backboneEntries.filter(e => e.nuc.strand_id === strandId)
    _strandConeEntries = coneEntries.filter(e => e.strandId === strandId)
    _strandArcEntries  = (getUnfoldView?.()?.getArcEntries() ?? []).filter(e => e.strandId === strandId)
    for (const e of _strandEntries) {
      designRenderer.setEntryColor(e, C_SELECT_STRAND)
      designRenderer.setBeadScale(e, 1.3)
    }
    for (const e of _strandConeEntries) {
      designRenderer.setEntryColor(e, C_SELECT_STRAND)
    }
    for (const e of _strandArcEntries) {
      e.setColor(C_SELECT_STRAND)
    }
    // Scaffold 5′/3′ glow — red for 5′ start, blue for 3′ end
    const isScaffold = _strandEntries.length > 0 && _strandEntries[0].nuc.strand_type === 'scaffold'
    if (isScaffold) {
      for (const e of _strandEntries) {
        if (e.nuc.is_five_prime)  { designRenderer.setEntryColor(e, C_SCAFFOLD_FIVE_PRIME);  designRenderer.setBeadScale(e, 2.0) }
        if (e.nuc.is_three_prime) { designRenderer.setEntryColor(e, C_SCAFFOLD_THREE_PRIME); designRenderer.setBeadScale(e, 2.0) }
      }
    }
  }

  function _highlightBead(entry) {
    for (const e of _strandEntries) {
      designRenderer.setBeadScale(e, e === entry ? 1.6 : 1.2)
    }
    _beadEntry = entry
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

  let _downPos = null

  canvas.addEventListener('pointerdown', e => {
    if (e.button !== 0) return
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

  canvas.addEventListener('pointerup', e => {
    if (controls) controls.enabled = true
    if (e.button !== 0) return
    if (_downPos && Math.hypot(e.clientX - _downPos.x, e.clientY - _downPos.y) > 4) return
    if (e.clientX > window.innerWidth - 300) return

    _dismissMenu()

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
        _mode     = 'strand'
        _strandId = hitStrandId
        _coneEntry = null
        _highlightStrand(backboneEntries, coneEntries, hitStrandId)
        store.setState({
          selectedObject: {
            type: 'strand',
            id:   hitStrandId ?? `unassigned:${hitEntry.nuc.helix_id}:${hitEntry.nuc.direction}`,
            data: { strand_id: hitStrandId, helix_id: hitEntry.nuc.helix_id },
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
        // Same strand, bead not yet selected (or different bead) → select this bead
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

    // Cast ray to check for a cone hit first.
    _setNdc(e.clientX, e.clientY)
    raycaster.setFromCamera(_ndc, camera)

    const coneEntries = designRenderer.getConeEntries()
    const coneMeshes  = [...new Set(coneEntries.map(e => e.instMesh))]
    const coneHits    = raycaster.intersectObjects(coneMeshes)

    // In bead mode, skip cone/arc checks — always show loop/skip menu for the selected bead.
    if (_mode === 'bead' && _beadEntry?.nuc && onLoopSkip) {
      _showLoopSkipMenu(e.clientX, e.clientY, _beadEntry.nuc, onLoopSkip)
      return
    }

    if (coneHits.length) {
      const hitCone = coneEntries.find(c => c.instMesh === coneHits[0].object && c.id === coneHits[0].instanceId)
      if (hitCone) {
        // In strand mode, right-clicking the selected strand shows the color/isolate menu
        if (_mode === 'strand' && hitCone.strandId === _strandId) {
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
      // In strand mode, right-clicking the selected strand's arc shows the color/isolate menu
      if (_mode === 'strand' && arcHit.strandId === _strandId) {
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
    if (newState.currentGeometry === prevState.currentGeometry) return
    _strandEntries     = []
    _strandConeEntries = []
    _strandArcEntries  = []
    _beadEntry         = null
    _coneEntry         = null

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
  }
}
