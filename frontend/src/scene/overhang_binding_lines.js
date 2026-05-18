/**
 * Overhang binding lines — dashed 3D connectors between overhang pairs that
 * have an OverhangBinding record on the design.
 *
 * Visual:
 *   - bound       → solid green dashed line
 *   - not bound   → translucent amber dashed line (the "pre-bind" affordance)
 *
 * Endpoints are the world-space backbone position of any nucleotide on each
 * overhang (the first one we find for that overhang_id). Geometry comes from
 * the standard store.currentGeometry — same source the overhang locations
 * module uses, so design moves keep these lines in sync as long as rebuild()
 * is invoked when the geometry changes.
 *
 * Scoped to per-part (design.overhang_bindings). Assembly-level
 * AssemblyOverhangBinding (cross-part) is a follow-up.
 *
 * Picking:
 *   hitTest(raycaster) → { bindingId, line } | null
 *
 * Wiring:
 *   const ovhgBindLines = initOverhangBindingLines(scene)
 *   ovhgBindLines.rebuild(design, geometry)
 *   ovhgBindLines.setVisible(true)
 *   const hit = ovhgBindLines.hitTest(raycaster)
 */

import * as THREE from 'three'

const COLOR_BOUND     = 0x3fb950   // green — matches success token
const COLOR_PREBIND   = 0xd29922   // amber — matches warning token
const OPACITY_BOUND   = 0.95
const OPACITY_PREBIND = 0.55
const DASH_SIZE       = 0.35       // nm
const GAP_SIZE        = 0.22       // nm
const LINE_THRESHOLD  = 0.18       // raycaster line picker tolerance (nm)

export function initOverhangBindingLines(scene) {
  const _group = new THREE.Group()
  _group.name = 'overhangBindingLines'
  _group.renderOrder = 11
  scene.add(_group)

  /** Map line.uuid → bindingId for hitTest lookup. */
  const _bindingByLine = new Map()
  let _visible = true

  function _firstPositionForOverhang(geometry, overhangId) {
    if (!geometry || !overhangId) return null
    for (const n of geometry) {
      if (n.overhang_id === overhangId) {
        const p = n.backbone_position
        if (p) return new THREE.Vector3(p[0], p[1], p[2])
      }
    }
    return null
  }

  function _disposeChildren() {
    for (const child of [..._group.children]) {
      child.geometry?.dispose?.()
      const mat = child.material
      if (Array.isArray(mat)) for (const m of mat) m.dispose?.()
      else mat?.dispose?.()
      _group.remove(child)
    }
    _bindingByLine.clear()
  }

  function rebuild(design, geometry) {
    _disposeChildren()
    if (!design || !geometry) return
    const bindings = design.overhang_bindings ?? []
    for (const b of bindings) {
      const pa = _firstPositionForOverhang(geometry, b.overhang_a_id)
      const pb = _firstPositionForOverhang(geometry, b.overhang_b_id)
      if (!pa || !pb) continue
      const bound = !!b.bound
      const geo = new THREE.BufferGeometry().setFromPoints([pa, pb])
      const mat = new THREE.LineDashedMaterial({
        color:       bound ? COLOR_BOUND : COLOR_PREBIND,
        dashSize:    DASH_SIZE,
        gapSize:     GAP_SIZE,
        linewidth:   1,
        transparent: true,
        opacity:     bound ? OPACITY_BOUND : OPACITY_PREBIND,
        depthWrite:  false,
      })
      const line = new THREE.Line(geo, mat)
      line.computeLineDistances()
      line.userData.bindingId = b.id
      line.userData.bound     = bound
      line.userData.tag       = 'overhang-binding-line'
      _group.add(line)
      _bindingByLine.set(line.uuid, b.id)
    }
  }

  function setVisible(v) {
    _visible = !!v
    _group.visible = _visible
  }
  function isVisible() { return _visible }

  /**
   * Raycast against the binding lines. Returns the closest hit's bindingId
   * (the same id passed to patchOverhangBinding etc.) or null.
   */
  function hitTest(raycaster) {
    if (!_visible || _group.children.length === 0) return null
    const savedThreshold = raycaster.params.Line?.threshold
    if (raycaster.params.Line) raycaster.params.Line.threshold = LINE_THRESHOLD
    try {
      const hits = raycaster.intersectObjects(_group.children, false)
      if (!hits.length) return null
      const line = hits[0].object
      const bindingId = _bindingByLine.get(line.uuid) ?? null
      return bindingId ? { bindingId, line } : null
    } finally {
      if (raycaster.params.Line) raycaster.params.Line.threshold = savedThreshold
    }
  }

  function dispose() {
    _disposeChildren()
    scene.remove(_group)
  }

  return { rebuild, setVisible, isVisible, hitTest, dispose }
}
