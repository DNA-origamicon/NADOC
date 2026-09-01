/**
 * 3D preview overlay for oxDNA surface capture strands.  Renders, coplanar with the
 * hard-surface plane:
 *   • a translucent coverage patch (circle / square) showing where strands will seed,
 *   • small dots at each capture-strand anchor point (the seeded dispersion), and
 *   • a TransformControls handle (constrained to the plane) to drag the patch centre;
 *     the drag pushes the new in-plane (X, Y) offset back to the setup fields.
 *
 * The in-plane basis (u, v) mirrors backend plane_basis() so a dot sits where the strand
 * is actually built.  Scene units are nm (1:1 world↔design), so no scaling is needed.
 *
 * Factory: initSurfaceStrandsOverlay({ scene, camera, canvas, controls, getStructureBounds,
 *   onCenterMove }) → { setPlane, update, clear, dispose }.
 *   setPlane({ axis, positionNm }) — from the floor card's grid push.
 *   update(spec, enabled) — redraw from the current surfaceStrandsSpec (null/false → hide).
 *   onCenterMove(xNm, yNm) — called on drag with the new in-plane offset.
 */

import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'
import { surfaceStrandPlacements, captureStrandLocalBeads } from './surface_strands_math.js'
import { floorNormal } from './oxdna_floor_math.js'

const PATCH_OPACITY = 0.12
const MAX_BEADS = 24000            // total emitted beads cap (strands × beads/strand)
const PREVIEW_BEADS_DEFAULT = 8    // strand length used when no sequence is entered yet
const DEFAULT_COLOR = 0x00ffff     // cyan — the surface-strand colour (user-controllable)

/** Idempotent bridge into designRenderer.setExtraNucleotides. Full renderer rebuilds are
 * expensive and destructive to active physical overlays, so identical results are a no-op.
 * Results arrays keep stable identity, so identity is the right test for them — but _draw
 * builds a FRESH `[]` on every call for the no-strands case, which identity never matches.
 * Empty→empty is therefore compared by emptiness, so a job with no capture strands doesn't
 * trigger a full CG rebuild (and un-hide the CG root) on every displayJob.
 *
 * PREVIEW chains have no stable identity at all — _previewChains rebuilds the array on
 * every _draw — so identity would re-emit on every redraw. One card edit calls _draw three
 * times (setHighlight, setShapePreview, update), which cost three full rebuilds of the whole
 * design. Preview passes a `key` describing everything the chains are derived from; equal
 * keys mean identical geometry and are a no-op. */
export function createSurfaceStrandEmitter(onStrands) {
  let lastChains = null, lastHighlight = null, lastKey = null
  return (chains, highlight, key = null) => {
    const bothEmpty = !chains?.length && !lastChains?.length && lastChains !== null
    const sameChains = (key != null && lastKey != null)
      ? key === lastKey
      : (chains === lastChains || bothEmpty)
    if (sameChains && highlight === lastHighlight) return false
    lastChains = chains; lastHighlight = highlight; lastKey = key
    onStrands?.(chains, highlight)
    return true
  }
}

// Replicate backend plane_basis(normal): d = normal; ref = X unless d≈±X, then Y.
function _planeBasis(axis) {
  const n = floorNormal(axis) || [0, 1, 0]
  const d = new THREE.Vector3(n[0], n[1], n[2]).normalize()
  const ref = Math.abs(d.x) < 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0)
  const u = new THREE.Vector3().crossVectors(d, ref).normalize()
  const v = new THREE.Vector3().crossVectors(d, u).normalize()
  return { d, u, v }
}

export function initSurfaceStrandsOverlay({
  scene, camera, canvas, controls, getStructureBounds = null, onCenterMove = null,
  // Emits the current world-nm strand bead lists (or [] when hidden) so the caller can
  // render them NATIVELY in the representations (designRenderer.setExtraNucleotides).
  onStrands = null,
} = {}) {
  if (!scene || !camera) {
    return {
      setPlane: () => {}, update: () => {}, setResults: () => {}, setHighlight: () => {},
      setShapePreview: () => {}, setColor: () => {}, clear: () => {}, dispose: () => {}, debug: () => ({}),
    }
  }

  const group = new THREE.Group()
  group.visible = false
  scene.add(group)

  // Translucent coverage patch (geometry rebuilt per shape/size change).  The strands
  // themselves render through the representation system, not here.
  const patchMat = new THREE.MeshBasicMaterial({
    color: DEFAULT_COLOR, transparent: true, opacity: PATCH_OPACITY,
    side: THREE.DoubleSide, depthWrite: false,
  })
  let patchMesh = null
  let _patchKey = ''   // "shape:size" so we only rebuild geometry when it changes

  // Centre gizmo (plane-constrained translate).
  const dummy = new THREE.Object3D()
  scene.add(dummy)
  const tc = new TransformControls(camera, canvas)
  tc.setMode('translate')
  tc.setSpace('world')
  tc.setSize(0.8)
  const helper = tc.getHelper ? tc.getHelper() : tc
  scene.add(helper)
  // Unlike a normal scene mesh, TransformControls owns DOM listeners and may
  // change its helper visibility internally. It must not be attached merely
  // because the overlay exists; attachment is reserved for an actionable preview.
  tc.enabled = false
  helper.visible = false

  // Constrain the handle to the surface plane: hide the world axis along the (axis-aligned)
  // surface normal so only the two in-plane DOF remain (arrows + the in-plane square handle).
  function _constrainGizmoToPlane() {
    const w = (_axis[1] || 'y')   // '-y' → 'y'
    tc.showX = w !== 'x'
    tc.showY = w !== 'y'
    tc.showZ = w !== 'z'
  }

  let _axis = '-y'
  let _sceneVisible = true
  let _positionNm = null
  let _basis = _planeBasis(_axis)
  let _baseCenter = new THREE.Vector3()    // patch centre at zero offset (design centre on plane)
  let _dragging = false
  let _gizmoAttached = false
  let _lastSpec = null
  let _lastEnabled = false
  let _results = null   // real simulated strands (world nm bead lists) — set once a job is displayed
  let _highlight = true      // strand beads/chains visible
  let _shapePreview = true   // coverage patch visible
  let _color = null          // requested strand colour — the caller re-reads it on emit,
                             // so it belongs to the preview identity (see _previewKey)
  const _emitStrands = createSurfaceStrandEmitter(onStrands)
  _constrainGizmoToPlane()   // default (-y) → in-plane (X,Z) only

  function _deactivateGizmo() {
    if (_dragging) {
      _dragging = false
      if (controls) controls.enabled = true
    }
    tc.enabled = false
    if (_gizmoAttached) {
      tc.detach()
      _gizmoAttached = false
    }
    helper.visible = false
  }

  function _activateGizmo(centre) {
    if (!_dragging && centre) dummy.position.copy(centre)
    if (!_gizmoAttached) {
      tc.attach(dummy)
      _gizmoAttached = true
    }
    tc.enabled = true
    helper.visible = true
  }

  // Bbox centre with the normal-axis coordinate replaced by the plane's absolute position
  // (mirrors view_tool_buttons._placeSurfaceGrid absolute mode).
  function _computeBaseCenter() {
    const b = getStructureBounds?.()
    const c = new THREE.Vector3()
    if (b?.min && b?.max) {
      c.set((b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2)
    }
    if (_positionNm != null && Number.isFinite(_positionNm)) {
      if (_axis.endsWith('x')) c.x = _positionNm
      else if (_axis.endsWith('y')) c.y = _positionNm
      else c.z = _positionNm
    } else if (b?.min && b?.max) {
      const [mn, mx] = [b.min, b.max]
      if (_axis === '-y') c.y = mn[1]; else if (_axis === '+y') c.y = mx[1]
      else if (_axis === '-x') c.x = mn[0]; else if (_axis === '+x') c.x = mx[0]
      else if (_axis === '-z') c.z = mn[2]; else if (_axis === '+z') c.z = mx[2]
    }
    return c
  }

  // Orient a patch (built in local XY, +Z normal) onto the (u, v, d) surface frame.
  function _orient(mesh) {
    const m = new THREE.Matrix4().makeBasis(_basis.u, _basis.v, _basis.d)
    mesh.quaternion.setFromRotationMatrix(m)
  }

  function _rebuildPatch(shape, sizeNm) {
    const key = `${shape}:${sizeNm}`
    if (key === _patchKey && patchMesh) return
    _patchKey = key
    if (patchMesh) { group.remove(patchMesh); patchMesh.geometry.dispose(); patchMesh = null }
    const geo = shape === 'square'
      ? new THREE.PlaneGeometry(sizeNm, sizeNm)
      : new THREE.CircleGeometry(sizeNm / 2, 64)
    patchMesh = new THREE.Mesh(geo, patchMat)
    group.add(patchMesh)
  }

  // Seed-placement strands (preview) as framed beads {p,a1,a3} — the actual B-form standing
  // strand per placement.  a3 = helix axis (surface normal); a1 = backbone→base = inward
  // radial (so the base slab orients like B-form DNA).  Uses the current plane basis + centre.
  function _previewChains(spec) {
    const pts = surfaceStrandPlacements({
      shape: spec.shape, sizeNm: spec.sizeNm, densityPerUm2: spec.densityPerUm2,
      seed: spec.seed, offsetXNm: spec.offsetXNm, offsetYNm: spec.offsetYNm,
    })
    const L = Math.max(1, (spec.sequence?.length || PREVIEW_BEADS_DEFAULT))
    const local = captureStrandLocalBeads(L)
    const nStrands = Math.min(pts.length, Math.floor(MAX_BEADS / L))
    const bead = new THREE.Vector3(), radial = new THREE.Vector3()
    const a3 = [_basis.d.x, _basis.d.y, _basis.d.z]   // helix axis = surface normal
    const out = []
    for (let s = 0; s < nStrands; s++) {
      const ax = pts[s].x, ay = pts[s].y
      const chain = []
      for (let m = 0; m < L; m++) {
        bead.copy(_baseCenter)
          .addScaledVector(_basis.u, ax + local[m].du)
          .addScaledVector(_basis.v, ay + local[m].dv)
          .addScaledVector(_basis.d, local[m].axial)
        // inward radial = backbone→axis: -(du·u + dv·v), normalized
        radial.set(0, 0, 0).addScaledVector(_basis.u, local[m].du).addScaledVector(_basis.v, local[m].dv)
        if (radial.lengthSq() > 1e-9) radial.normalize().negate(); else radial.copy(_basis.u)
        chain.push({ p: [bead.x, bead.y, bead.z], a1: [radial.x, radial.y, radial.z], a3 })
      }
      out.push(chain)
    }
    return out
  }

  // Everything _previewChains derives its beads from: the spec fields it reads, the
  // plane frame, and the anchor centre. Same key ⇒ byte-identical chains ⇒ no rebuild.
  function _previewKey(spec) {
    if (!spec) return 'preview:none'
    const c = _baseCenter
    return [
      'preview', spec.shape, spec.sizeNm, spec.densityPerUm2, spec.seed,
      spec.offsetXNm, spec.offsetYNm, spec.sequence?.length || PREVIEW_BEADS_DEFAULT,
      _axis, _positionNm, _color,
      Math.round(c.x * 1e4), Math.round(c.y * 1e4), Math.round(c.z * 1e4),
    ].join('|')
  }

  function _draw() {
    const spec = _lastSpec
    const inResults = !!(_results && _results.length)
    const haveSpec = !!(spec && spec.sizeNm > 0)
    const active = inResults || (_lastEnabled && haveSpec)
    group.visible = _sceneVisible && active

    // Coverage patch — positioned from the spec + plane; shown per the shape toggle (in
    // results too, so the coverage area can overlay the real strands for a figure).
    let centre = null
    if (active && haveSpec) {
      _basis = _planeBasis(_axis)
      _baseCenter = _computeBaseCenter()
      centre = _baseCenter.clone()
        .addScaledVector(_basis.u, spec.offsetXNm || 0)
        .addScaledVector(_basis.v, spec.offsetYNm || 0)
      _rebuildPatch(spec.shape, spec.sizeNm)
      _orient(patchMesh)
      patchMesh.position.copy(centre)
      patchMesh.visible = _shapePreview
    } else if (patchMesh) { patchMesh.visible = false }

    // Strands render NATIVELY in the reps and are ALWAYS shown. The setup "Highlight"
    // emphasis belongs to the seed PREVIEW only: carrying that duplicate glow geometry into
    // results mode makes every real cap look selected, creates an apparent second strand at
    // each site, and obscures which bead the selection ray actually hit.
    let chains = []
    let key = null
    if (active) chains = inResults ? _results : (haveSpec ? _previewChains(spec) : [])
    if (!inResults) key = _previewKey(active && haveSpec ? spec : null)
    const emittedHighlight = !inResults && _highlight
    // setExtraNucleotides is a full renderer rebuild. Plane/patch/setup refreshes can call
    // _draw repeatedly while the SAME simulation-result array is active; rebuilding again
    // after RMSF applies its positions/colors wipes that overlay. Results keep stable array
    // identity, so emit only when chains or effective highlight actually changed.
    _emitStrands(chains, emittedHighlight, key)

    // Centre gizmo — only while setting up an actionable preview. Detaching is
    // part of hiding: a merely invisible TransformControls still owns listeners
    // and can re-show its helper or intercept input.
    const gizmoActive = _sceneVisible && active && !inResults
      && _lastEnabled && haveSpec && _shapePreview
    if (gizmoActive) _activateGizmo(centre)
    else _deactivateGizmo()
  }

  // ── Drag: read the dummy back onto the plane basis → new (X,Y) offset ──
  tc.addEventListener('dragging-changed', (e) => {
    if (!_gizmoAttached && e.value) return
    _dragging = !!e.value
    if (controls) controls.enabled = !e.value
  })
  tc.addEventListener('objectChange', () => {
    if (!_gizmoAttached || !_dragging) return
    const rel = dummy.position.clone().sub(_baseCenter)
    onCenterMove?.(rel.dot(_basis.u), rel.dot(_basis.v))
  })

  // ── Public API ──
  function setPlane({ axis = '-y', positionNm = null } = {}) {
    _axis = axis || '-y'
    _positionNm = positionNm
    _constrainGizmoToPlane()
    _draw()
  }
  function update(spec, enabled) {
    _lastSpec = spec || null
    _lastEnabled = !!enabled
    _draw()
  }
  // Real simulated strands from a displayed job → results mode (preview suppressed). Pass
  // null/empty to drop back to the seed preview (e.g. the display was turned off).
  function setResults(strands) {
    _results = (Array.isArray(strands) && strands.length) ? strands : null
    _draw()
  }
  function setHighlight(on) { _highlight = !!on; _draw() }
  function setShapePreview(on) { _shapePreview = !!on; _draw() }
  // The strands are coloured by the renderer (setExtraNucleotides); here we only tint the
  // coverage patch to match.
  function setColor(hex) {
    if (hex == null || hex === '') return
    _color = String(hex)
    patchMat.color.setHex((typeof hex === 'string') ? new THREE.Color(hex).getHex() : hex)
  }
  // Surface strands are design-only. _draw owns both visual visibility and the
  // TransformControls attachment lifecycle, so every exit path is identical.
  function setVisible(on) {
    _sceneVisible = !!on
    _draw()
  }
  function clear() { _lastSpec = null; _lastEnabled = false; _results = null; _draw() }
  function dispose() {
    _deactivateGizmo()
    helper.parent?.remove(helper); tc.dispose?.()
    dummy.parent?.remove(dummy)
    if (patchMesh) patchMesh.geometry.dispose()
    patchMat.dispose()
    group.parent?.remove(group)
  }

  const debug = () => ({
    visible: group.visible, hasPatch: !!patchMesh,
    patchVisible: !!(patchMesh && patchMesh.visible), mode: _results ? 'results' : 'preview',
    highlight: _highlight, shapePreview: _shapePreview, patchColor: '#' + patchMat.color.getHexString(),
    gizmoVisible: helper.visible, gizmoAttached: _gizmoAttached, gizmoEnabled: tc.enabled,
    baseCenter: [Math.round(_baseCenter.x * 100) / 100, Math.round(_baseCenter.y * 100) / 100, Math.round(_baseCenter.z * 100) / 100],
    patchPos: patchMesh ? [Math.round(patchMesh.position.x * 100) / 100, Math.round(patchMesh.position.y * 100) / 100, Math.round(patchMesh.position.z * 100) / 100] : null,
  })
  return { setPlane, update, setResults, setHighlight, setShapePreview, setColor, setVisible, clear, dispose, debug }
}
