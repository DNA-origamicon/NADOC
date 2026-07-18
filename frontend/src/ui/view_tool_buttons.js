// View tool buttons — the right-panel `.vt-btn` row: length heatmap, sequences,
// undefined-base highlight, grid, overhang names, expanded spacing, deform,
// unfold, cadnano2d.
//
// Extracted verbatim from main.js (banner `// ── View tool buttons`). The block
// owns its own state (length-heatmap on/off + legend, the scene grid helper);
// everything else is injected. The shared `_undefinedHighlightOn` mutable lives
// in main.js (owned by the "Highlight Undefined Bases toggle" region) and is
// reached through get/set shims — block B only flips it from deferred click
// handlers, so the shim closures are TDZ-safe by deferral (same as the inline
// code they replace).

import * as THREE from 'three'
import { heatmapHex } from '../scene/color_util.js'
import { strandDomainNt } from '../scene/strand_length.js'

/**
 * Pure: build the per-strand length-heatmap colour map (staple strands only;
 * scaffold is skipped). Keyed by strand id → packed hex int.
 */
export function buildLengthHeatmapColors(strands) {
  const colorMap = new Map()
  for (const s of strands ?? []) {
    if (s.strand_type === 'scaffold') continue
    colorMap.set(s.id, heatmapHex(strandDomainNt(s)))
  }
  return colorMap
}

export function initViewToolButtons({
  store,
  scene,
  designRenderer,
  expandedSpacing,
  setMenuToggle,
  refreshUndefinedHighlight,
  getUndefinedHighlightOn,
  setUndefinedHighlightOn,
  toggleDeformView,
  toggleUnfold,
  toggleCadnano,
  toggleClashes,
  getClashesOn,
}) {
  // Length heatmap
  let _lengthHeatmapOn = false
  const _lenLegend = document.getElementById('length-heatmap-legend')

  function _applyLengthHeatmap() {
    const design = store.getState().currentDesign
    if (!design) return
    const colorMap = buildLengthHeatmapColors(design.strands)
    // backbone + slab entries expose strand_id via nuc; cone entries expose it directly
    for (const e of designRenderer.getBackboneEntries?.() ?? []) {
      const c = colorMap.get(e.nuc?.strand_id)
      if (c !== undefined) designRenderer.setEntryColor(e, c)
    }
    for (const e of designRenderer.getSlabEntries?.() ?? []) {
      const c = colorMap.get(e.nuc?.strand_id)
      if (c !== undefined) designRenderer.setEntryColor(e, c)
    }
    for (const e of designRenderer.getConeEntries?.() ?? []) {
      const c = colorMap.get(e.strandId)
      if (c !== undefined) designRenderer.setEntryColor(e, c)
    }
    _lenLegend?.classList.add('visible')
  }
  function _clearLengthHeatmap() {
    for (const e of designRenderer.getBackboneEntries?.() ?? []) {
      designRenderer.setEntryColor(e, e.defaultColor)
    }
    for (const e of designRenderer.getSlabEntries?.() ?? []) {
      designRenderer.setEntryColor(e, e.defaultColor)
    }
    for (const e of designRenderer.getConeEntries?.() ?? []) {
      designRenderer.setEntryColor(e, e.defaultColor)
    }
    _lenLegend?.classList.remove('visible')
  }

  // Grid helper — the View "grid" toggle AND the hard-surface visualization. When
  // a hard surface is enabled in the oxDNA panel, the same grid is turned on and
  // re-placed at that surface plane (so the grid the user sees is the wall the
  // simulation uses); the View button still toggles it independently.
  const _gridHelper = new THREE.GridHelper(500, 50, 0x21262d, 0x1a1f27)
  _gridHelper.visible = false
  scene.add(_gridHelper)
  let _surfaceDriven = false      // grid currently positioned by a hard surface
  const _GRID_DEFAULT_NORMAL = new THREE.Vector3(0, 1, 0)   // GridHelper lies in XZ
  // Outward normals per floor side (same convention as the Hard surface card).
  const _AXIS_NORMALS = {
    '-y': [0, 1, 0], '+y': [0, -1, 0], '-x': [1, 0, 0],
    '+x': [-1, 0, 0], '-z': [0, 0, 1], '+z': [0, 0, -1],
  }

  function _designBBox() {
    const box = new THREE.Box3()
    let any = false
    for (const e of designRenderer.getBackboneEntries?.() ?? []) {
      // Exclude injected surface capture strands ('cap<i>') — the surface grid must sit at
      // the design's extent, not follow the strands that are placed relative to it.
      if (e.pos && !String(e.nuc?.strand_id).startsWith('cap')) {
        box.expandByPoint(new THREE.Vector3(e.pos.x, e.pos.y, e.pos.z)); any = true
      }
    }
    return any ? box : null
  }

  function _placeSurfaceGrid(axis, offsetNm, positionNm = null) {
    const box = _designBBox()
    if (!box) return false
    const p = box.getCenter(new THREE.Vector3())
    const off = Number(offsetNm) || 0
    if (positionNm != null && positionNm !== '' && Number.isFinite(Number(positionNm))) {
      const coord = Number(positionNm)
      if (axis.endsWith('x')) p.x = coord
      else if (axis.endsWith('y')) p.y = coord
      else if (axis.endsWith('z')) p.z = coord
      else return false
    } else switch (axis) {
      case '-y': p.y = box.min.y - off; break
      case '+y': p.y = box.max.y + off; break
      case '-x': p.x = box.min.x - off; break
      case '+x': p.x = box.max.x + off; break
      case '-z': p.z = box.min.z - off; break
      case '+z': p.z = box.max.z + off; break
      default: return false
    }
    const n = _AXIS_NORMALS[axis] || _AXIS_NORMALS['-y']
    _gridHelper.quaternion.setFromUnitVectors(_GRID_DEFAULT_NORMAL, new THREE.Vector3(n[0], n[1], n[2]))
    _gridHelper.position.copy(p)
    return true
  }

  // Public: the Hard surface card drives this on enable / axis / offset change.
  function setSurfaceGrid({ enabled, axis = '-y', offsetNm = 0, positionNm = null } = {}) {
    if (enabled) {
      _surfaceDriven = true
      _placeSurfaceGrid(axis, offsetNm, positionNm)
      _gridHelper.visible = true
    } else if (_surfaceDriven) {
      // The surface that was driving the grid was turned off → reset to the plain
      // origin reference grid and hide it (it was the surface viz).
      _surfaceDriven = false
      _gridHelper.visible = false
      _gridHelper.position.set(0, 0, 0)
      _gridHelper.quaternion.identity()
    }
    _syncVtButtons()
  }

  function _syncVtButtons() {
    const { showSequences, showOverhangNames, showLoopSkips, unfoldActive, cadnanoActive, deformVisuActive } = store.getState()
    document.querySelector('.vt-btn[data-vt="lengthHeatmap"]')?.classList.toggle('active', _lengthHeatmapOn)
    document.querySelector('.vt-btn[data-vt="sequences"]')?.classList.toggle('active', showSequences)
    document.querySelector('.vt-btn[data-vt="undefinedBases"]')?.classList.toggle('active', getUndefinedHighlightOn())
    document.querySelector('.vt-btn[data-vt="loopSkips"]')?.classList.toggle('active', showLoopSkips)
    document.querySelector('.vt-btn[data-vt="grid"]')?.classList.toggle('active', _gridHelper.visible)
    document.querySelector('.vt-btn[data-vt="overhangNames"]')?.classList.toggle('active', showOverhangNames)
    document.querySelector('.vt-btn[data-vt="clashes"]')?.classList.toggle('active', getClashesOn?.() ?? false)
    document.querySelector('.vt-btn[data-vt="expanded"]')?.classList.toggle('active', expandedSpacing.isActive())
    document.querySelector('.vt-btn[data-vt="deform"]')?.classList.toggle('active', deformVisuActive)
    document.querySelector('.vt-btn[data-vt="unfold"]')?.classList.toggle('active', unfoldActive)
    document.querySelector('.vt-btn[data-vt="cadnano2d"]')?.classList.toggle('active', cadnanoActive)
  }

  document.querySelector('.vt-btn[data-vt="lengthHeatmap"]')?.addEventListener('click', () => {
    _lengthHeatmapOn = !_lengthHeatmapOn
    if (_lengthHeatmapOn) _applyLengthHeatmap()
    else _clearLengthHeatmap()
    _syncVtButtons()
  })

  document.querySelector('.vt-btn[data-vt="sequences"]')?.addEventListener('click', () => {
    const { showSequences } = store.getState()
    store.setState({ showSequences: !showSequences })
    setMenuToggle('menu-view-sequences', !showSequences)
  })

  document.querySelector('.vt-btn[data-vt="undefinedBases"]')?.addEventListener('click', () => {
    const next = !getUndefinedHighlightOn()
    setUndefinedHighlightOn(next)
    setMenuToggle('menu-view-undefined-bases', next)
    if (next) refreshUndefinedHighlight()
    else designRenderer.clearUndefinedHighlight()
    _syncVtButtons()
  })

  document.querySelector('.vt-btn[data-vt="loopSkips"]')?.addEventListener('click', () => {
    // Flip the shared store key; view_legends' subscriber applies the actual
    // scene/legend/menu-pill changes, and the store.subscribe below re-syncs this pill.
    store.setState({ showLoopSkips: !store.getState().showLoopSkips })
  })

  document.querySelector('.vt-btn[data-vt="grid"]')?.addEventListener('click', () => {
    _gridHelper.visible = !_gridHelper.visible
    _syncVtButtons()
  })

  document.querySelector('.vt-btn[data-vt="overhangNames"]')?.addEventListener('click', () => {
    const { showOverhangNames } = store.getState()
    store.setState({ showOverhangNames: !showOverhangNames })
    setMenuToggle('menu-view-overhang-names', !showOverhangNames)
  })

  document.querySelector('.vt-btn[data-vt="clashes"]')?.addEventListener('click', () => {
    toggleClashes?.()
    _syncVtButtons()
  })

  document.querySelector('.vt-btn[data-vt="expanded"]')?.addEventListener('click', () => {
    expandedSpacing.toggle()
    _syncVtButtons()
  })

  document.querySelector('.vt-btn[data-vt="deform"]')?.addEventListener('click', () => {
    toggleDeformView()
  })

  document.querySelector('.vt-btn[data-vt="unfold"]')?.addEventListener('click', () => {
    toggleUnfold()
  })

  document.querySelector('.vt-btn[data-vt="cadnano2d"]')?.addEventListener('click', () => {
    toggleCadnano()
  })

  // Keep vt buttons in sync when store changes (menu or other code toggling them)
  store.subscribe((newState, prevState) => {
    if (newState.showSequences !== prevState.showSequences ||
        newState.showOverhangNames !== prevState.showOverhangNames ||
        newState.showLoopSkips !== prevState.showLoopSkips ||
        newState.unfoldActive !== prevState.unfoldActive ||
        newState.cadnanoActive !== prevState.cadnanoActive ||
        newState.deformVisuActive !== prevState.deformVisuActive) {
      _syncVtButtons()
    }
  })

  // Re-apply length heatmap when design changes
  store.subscribe((newState, prevState) => {
    if (_lengthHeatmapOn && newState.currentDesign !== prevState.currentDesign) {
      _applyLengthHeatmap()
    }
  })

  return {
    syncButtons: _syncVtButtons,
    applyLengthHeatmap: _applyLengthHeatmap,
    clearLengthHeatmap: _clearLengthHeatmap,
    isLengthHeatmapOn: () => _lengthHeatmapOn,
    setSurfaceGrid,
    isGridOn: () => _gridHelper.visible,
  }
}
