/**
 * Cadnano Mode — two-track flat 2D view with orthographic camera.
 *
 * Builds on top of unfold view: requires unfold to be active (auto-activates it),
 * then animates each bead from its unfolded position to a cadnano flat position:
 *   - scaffold nucleotides: top track on FORWARD helices, bottom on REVERSE helices
 *   - staple nucleotides:   opposite side to scaffold on the same helix
 *   - all beads at uniform x-axis spacing (x = bp_index × RISE_PER_BP)
 *
 * Animation is two-stage:
 *   1. 250 ms — unfold animation (helices translate to stacked rows)
 *   2. 250 ms — bead lerp from unfolded → flat two-track cadnano positions
 *      Then: seamless swap to orthographic camera (copies perspective camera exactly)
 *
 * Additional features:
 *   - orthographic camera (pan + zoom only, no rotation)
 *   - alternating translucent row-band background planes
 *   - slice plane shown in YZ read-only mode as a BP position indicator
 *   - auto-enables sequences overlay and crossover locations tool on entry,
 *     restores them on exit
 *
 * Usage:
 *   const cadnanoView = initCadnanoView(sceneCtx, designRenderer,
 *     getUnfoldView, getSequenceOverlay, getCrossoverLocations, getSlicePlane)
 *   cadnanoView.toggle()
 *   cadnanoView.isActive()   // → boolean
 */

import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { store } from '../state/store.js'
import { BDNA_RISE_PER_BP } from '../constants.js'

const ANIM_STAGE1_MS       = 250   // ms for unfold-equivalent stage
const ANIM_STAGE2_MS       = 250   // ms for cadnano flat-lerp + camera pan stage
const TRACK_OFFSET         = 0.5   // nm half-gap between scaffold/staple tracks
const ROW_BAND_COLOR_A     = 0x131d2e  // even rows
const ROW_BAND_COLOR_B     = 0x1a2740  // odd rows
const ROW_BAND_OPACITY     = 0.60
const PERSP_FOV_DEG        = 55    // must match scene.js default perspective camera FOV

export function initCadnanoView(sceneCtx, designRenderer, getUnfoldView, getSequenceOverlay, getCrossoverLocations, getSlicePlane) {
  let _active        = false
  let _inTransition  = false
  let _animFrame     = null

  // Ortho camera + controls
  let _orthoCamera   = null
  let _orthoControls = null

  // Background row bands
  let _bandGroup     = null

  // Saved state restored on exit
  let _savedShowSeq         = null
  let _savedCrossoverFilter = null
  let _savedSliceWasVisible = false
  let _savedSlicePlane      = 'XY'
  let _savedSliceOffset     = 0
  let _wasUnfoldActive      = false  // was unfold already active when cadnano was entered?

  // Position maps for the lerp animation
  let _cadnanoPosMap = null   // Map<"hid:bp:dir", Vector3>  — cadnano targets
  let _unfoldPosMap  = null   // Map<"hid:bp:dir", Vector3>  — snapshot at stage-2 start

  // Design bounds (populated by _computeCadnanoPosMap)
  let _midZ  = 0   // Z midpoint of the design (from unfold_view.getMidZ)
  let _midX  = 0   // X centre of helix bundle — all cadnano beads are at this X
  let _minBp = 0
  let _maxBp = 0

  // ── Position computation ─────────────────────────────────────────────────────

  function _computeCadnanoPosMap() {
    const { currentGeometry, currentDesign, unfoldHelixOrder, unfoldSpacing } = store.getState()
    if (!currentGeometry || !currentDesign) return new Map()

    const spacing  = unfoldSpacing ?? 2.5
    const allIds   = currentDesign.helices.map(h => h.id)
    const base     = unfoldHelixOrder ?? allIds
    const baseSet  = new Set(base)
    const order    = [...base, ...allIds.filter(id => !baseSet.has(id))]
    const rowMap   = new Map(order.map((id, i) => [id, i]))

    _midZ = getUnfoldView?.()?.getMidZ() ?? 0

    // Cadnano is viewed from the X- direction (same as the X- view-cube face).
    // Helix rows stack in Y; bp position varies along Z (the helix axis direction).
    // All beads share the same X = _midX (mean of helix axis X positions).
    // This matches the unfold-view camera orientation so no jarring view flip occurs.
    let sumX = 0, nHelices = 0
    for (const h of currentDesign.helices) {
      if (h.id.startsWith('__')) continue
      sumX += (h.axis_start.x + h.axis_end.x) / 2
      nHelices++
    }
    _midX = nHelices > 0 ? sumX / nHelices : 0

    // Determine per-helix scaffold direction from the first scaffold nucleotide found.
    // FORWARD helix: scaffold on top (+TRACK_OFFSET), staple on bottom (−TRACK_OFFSET).
    // REVERSE helix: scaffold on bottom (−TRACK_OFFSET), staple on top (+TRACK_OFFSET).
    const helixScaffoldDir = new Map()
    for (const nuc of currentGeometry) {
      if (nuc.strand_type !== 'scaffold') continue
      if (nuc.helix_id.startsWith('__')) continue
      if (!helixScaffoldDir.has(nuc.helix_id)) helixScaffoldDir.set(nuc.helix_id, nuc.direction)
    }

    let minBp = Infinity, maxBp = -Infinity
    const posMap = new Map()

    for (const nuc of currentGeometry) {
      if (nuc.helix_id.startsWith('__xb_'))  continue
      if (nuc.helix_id.startsWith('__ext_')) continue
      const row = rowMap.get(nuc.helix_id)
      if (row == null) continue

      const z            = nuc.bp_index * BDNA_RISE_PER_BP  // bp position along Z (helix axis)
      const scaffoldDir  = helixScaffoldDir.get(nuc.helix_id) ?? 'FORWARD'
      const isScaffold   = nuc.strand_type === 'scaffold'
      // Same sign → top track (+TRACK_OFFSET): scaffold on a FORWARD helix, staple on a REVERSE helix.
      const trackOffset  = (isScaffold === (scaffoldDir === 'FORWARD')) ? +TRACK_OFFSET : -TRACK_OFFSET
      const y            = -row * spacing + trackOffset
      const key          = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
      posMap.set(key, new THREE.Vector3(_midX, y, z))

      if (nuc.bp_index < minBp) minBp = nuc.bp_index
      if (nuc.bp_index > maxBp) maxBp = nuc.bp_index
    }

    _minBp = minBp === Infinity  ? 0 : minBp
    _maxBp = maxBp === -Infinity ? 0 : maxBp
    return posMap
  }

  // ── Layout helpers ───────────────────────────────────────────────────────────

  /** Returns design-layout values used by both the ortho camera and row bands. */
  function _layoutInfo() {
    const { currentDesign, unfoldHelixOrder, unfoldSpacing } = store.getState()
    const allIds  = currentDesign?.helices?.map(h => h.id) ?? []
    const base    = unfoldHelixOrder ?? allIds
    const baseSet = new Set(base)
    const order   = [...base, ...allIds.filter(id => !baseSet.has(id))]
    const nRows   = order.length || 1
    const spacing = unfoldSpacing ?? 2.5
    // In cadnano mode the view is from X-.  Z is the bp axis (horizontal), Y is vertical.
    const centerZ = (_minBp + _maxBp) / 2 * BDNA_RISE_PER_BP
    const centerY = -(nRows - 1) * spacing / 2
    const designH = nRows * spacing
    const designW = (_maxBp - _minBp + 1) * BDNA_RISE_PER_BP
    return { nRows, spacing, centerZ, centerY, designH, designW }
  }

  // ── Orthographic camera ──────────────────────────────────────────────────────

  function _activateOrthoCamera() {
    const canvas  = sceneCtx.renderer.domElement
    const w       = canvas.clientWidth  || canvas.width
    const h       = canvas.clientHeight || canvas.height
    const aspect  = w / h

    // Match the current perspective camera exactly so the switch is visually seamless.
    const persp  = sceneCtx.camera
    const target = sceneCtx.controls.target.clone()
    const dist   = persp.position.distanceTo(target)
    const fovRad = PERSP_FOV_DEG * Math.PI / 180
    const fh     = dist * 2 * Math.tan(fovRad / 2)
    const fw     = fh * aspect

    // Frustum centred in camera space — OrbitControls handles world-space panning.
    _orthoCamera = new THREE.OrthographicCamera(-fw / 2, fw / 2, fh / 2, -fh / 2, 0.01, 500)
    _orthoCamera.position.copy(persp.position)
    _orthoCamera.quaternion.copy(persp.quaternion)
    _orthoCamera.up.copy(persp.up)
    _orthoCamera.updateProjectionMatrix()

    // OrbitControls for the ortho camera — pan and zoom only.
    _orthoControls = new OrbitControls(_orthoCamera, canvas)
    _orthoControls.enableRotate  = false
    _orthoControls.enableDamping = false
    _orthoControls.target.copy(target)
    _orthoControls.update()

    // Resize handler: preserve halfH (vertical zoom level), adjust horizontal.
    sceneCtx.setResizeCallback((nw, nh) => {
      if (!_orthoCamera) return
      const na    = nw / nh
      const halfH = (_orthoCamera.top - _orthoCamera.bottom) / 2
      _orthoCamera.left  = -na * halfH
      _orthoCamera.right =  na * halfH
      _orthoCamera.updateProjectionMatrix()
    })

    // Push to scene: render with ortho camera, use ortho controls for input.
    sceneCtx.setRenderCamera(_orthoCamera)
    sceneCtx.pushControls(_orthoControls)
  }

  function _deactivateOrthoCamera() {
    sceneCtx.clearResizeCallback()
    sceneCtx.restoreRenderCamera()
    sceneCtx.popControls()
    if (_orthoControls) {
      _orthoControls.dispose()
      _orthoControls = null
    }
    _orthoCamera = null
  }

  // ── Row background bands ─────────────────────────────────────────────────────

  function _buildRowBands() {
    const { currentDesign, unfoldHelixOrder, unfoldSpacing } = store.getState()
    const allIds   = currentDesign?.helices?.map(h => h.id) ?? []
    const base     = unfoldHelixOrder ?? allIds
    const baseSet  = new Set(base)
    const order    = [...base, ...allIds.filter(id => !baseSet.has(id))]
    const spacing  = unfoldSpacing ?? 2.5

    // Bands lie in the YZ plane (camera looks from X-).
    // PlaneGeometry is in XY by default — rotate 90° around Y to make it YZ.
    const designWidth = (_maxBp - _minBp + 1) * BDNA_RISE_PER_BP + 4.0  // Z extent (+4nm padding)
    const centerZ     = (_minBp + _maxBp) / 2 * BDNA_RISE_PER_BP

    _bandGroup = new THREE.Group()

    for (let row = 0; row < order.length; row++) {
      const rowY  = -row * spacing
      const color = row % 2 === 0 ? ROW_BAND_COLOR_A : ROW_BAND_COLOR_B
      const geo   = new THREE.PlaneGeometry(designWidth, spacing * 0.90)
      const mat   = new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: ROW_BAND_OPACITY,
        side: THREE.DoubleSide,
        depthWrite: false,
      })
      const mesh  = new THREE.Mesh(geo, mat)
      mesh.rotation.y = Math.PI / 2        // XY → YZ plane (normal now points along X)
      mesh.position.set(_midX + 1.5, rowY, centerZ)  // slightly behind beads (+X = behind camera)
      _bandGroup.add(mesh)
    }

    sceneCtx.scene.add(_bandGroup)
  }

  function _removeRowBands() {
    if (!_bandGroup) return
    sceneCtx.scene.remove(_bandGroup)
    for (const child of _bandGroup.children) {
      child.geometry.dispose()
      child.material.dispose()
    }
    _bandGroup = null
  }

  // ── Slice plane as BP position indicator ─────────────────────────────────────

  function _showSlicePlane() {
    const sp = getSlicePlane?.()
    if (!sp) return

    _savedSliceWasVisible = sp.isVisible()
    _savedSlicePlane      = sp.getPlane()
    _savedSliceOffset     = sp.getPlaneOffset()

    const { nRows, spacing } = _layoutInfo()

    // In the YZ layout, bp position is along Z.  The slice indicator is an XY plane
    // (perpendicular to Z) that marks a specific bp column.
    //   width  → world X extent (covers _midX ± 1.5 nm — beads are all at _midX)
    //   height → world Y extent (spans all rows + one row of padding each side)
    //   cx     → X centre of beads (_midX)
    //   cy     → Y centre of rows
    const cadnanoDims = {
      width:  3.0,
      height: (nRows - 1) * spacing + spacing * 2,
      cx:     _midX,                          // X centre
      cy:     -(nRows - 1) * spacing / 2,     // Y centre of rows
    }
    sp.setCadnanoDimensions(cadnanoDims)
    sp.setCamera(_orthoCamera)

    // Initial Z position: midpoint of the design in BP coordinates.
    const midBpOffset = Math.round((_minBp + _maxBp) / 2) * BDNA_RISE_PER_BP
    sp.show('XY', midBpOffset, false, true)   // readOnly — no lattice, no extrude
  }

  function _hideSlicePlane() {
    const sp = getSlicePlane?.()
    if (!sp) return
    sp.clearCadnanoDimensions()
    sp.setCamera(sceneCtx.camera)
    if (_savedSliceWasVisible) {
      sp.show(_savedSlicePlane, _savedSliceOffset, false, true)
    } else {
      sp.hide()
    }
    _savedSliceWasVisible = false
  }

  // ── Animation ────────────────────────────────────────────────────────────────

  function _animate(fromMap, toMap, onDone, duration) {
    if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null }
    const startTime = performance.now()

    function frame(now) {
      const raw = Math.min((now - startTime) / duration, 1)

      designRenderer.applyCadnanoPositions(toMap, raw, fromMap)
      // Sequence overlay: interpolated positions as the straightPosMap with t=1.
      const frameMap = raw < 1 ? _interpMap(fromMap, toMap, raw) : toMap
      getSequenceOverlay?.()?.applyUnfoldOffsets(new Map(), 1.0, frameMap, null)
      // Crossover locations and arcs follow cadnano positions.
      getCrossoverLocations?.()?.applyCadnanoPositions(toMap, raw, fromMap)
      getUnfoldView?.()?.applyCadnanoPositions(toMap, raw, fromMap)

      if (raw >= 1) {
        _animFrame = null
        onDone?.()
      } else {
        _animFrame = requestAnimationFrame(frame)
      }
    }

    _animFrame = requestAnimationFrame(frame)
  }

  function _interpMap(fromMap, toMap, t) {
    const result = new Map()
    for (const [key, toPos] of toMap) {
      const fromPos = fromMap.get(key)
      if (!fromPos) { result.set(key, toPos); continue }
      result.set(key, new THREE.Vector3(
        fromPos.x + (toPos.x - fromPos.x) * t,
        fromPos.y + (toPos.y - fromPos.y) * t,
        fromPos.z + (toPos.z - fromPos.z) * t,
      ))
    }
    return result
  }

  // ── Side-effect helpers ──────────────────────────────────────────────────────

  function _enableSideEffects() {
    const state = store.getState()
    _savedShowSeq = state.showSequences
    if (!state.showSequences) store.setState({ showSequences: true })
    _savedCrossoverFilter = state.toolFilters.crossoverLocations
    if (!state.toolFilters.crossoverLocations) {
      store.setState({ toolFilters: { ...state.toolFilters, crossoverLocations: true } })
    }
  }

  function _restoreSideEffects() {
    const state = store.getState()
    if (_savedShowSeq !== null) {
      store.setState({ showSequences: _savedShowSeq })
      _savedShowSeq = null
    }
    if (_savedCrossoverFilter !== null) {
      store.setState({ toolFilters: { ...state.toolFilters, crossoverLocations: _savedCrossoverFilter } })
      _savedCrossoverFilter = null
    }
  }

  // ── Public API ───────────────────────────────────────────────────────────────

  async function activate() {
    if (_active || _inTransition) return
    _inTransition = true

    // ── Stage 1 (250 ms): unfold animation ──────────────────────────────────
    const unfoldView = getUnfoldView?.()
    _wasUnfoldActive = unfoldView?.isActive() ?? false
    if (unfoldView && !unfoldView.isActive()) {
      await unfoldView.activateWithDuration(ANIM_STAGE1_MS)
    }

    // Compute cadnano target positions and snapshot current (unfolded) positions.
    _cadnanoPosMap = _computeCadnanoPosMap()
    if (_cadnanoPosMap.size === 0) { _inTransition = false; return }
    _unfoldPosMap = designRenderer.snapshotPositions()

    // ── Stage 2 (250 ms): bead lerp + camera orbit to X- view, simultaneously ──
    // Camera orbits around the current target to look from X-, keeping the same
    // distance and orbit centre — no translation, only orientation change.
    const orbitTarget = sceneCtx.controls.target.clone()
    const orbitDist   = sceneCtx.camera.position.distanceTo(orbitTarget)
    const beadsPromise  = new Promise(resolve => _animate(_unfoldPosMap, _cadnanoPosMap, resolve, ANIM_STAGE2_MS))
    const cameraPromise = sceneCtx.animateCameraTo({
      position: [orbitTarget.x - orbitDist, orbitTarget.y, orbitTarget.z],
      target:   orbitTarget.toArray(),
      up:       [0, 1, 0],
      duration: ANIM_STAGE2_MS,
    })
    await Promise.all([beadsPromise, cameraPromise])

    // Hide axis arrows — they have no meaning in the flat cadnano layout.
    designRenderer.setAxisArrowsVisible(false)

    // Build row bands now that beads are at cadnano positions.
    _buildRowBands()

    // Switch to ortho camera — copies perspective camera exactly so the swap is seamless.
    _activateOrthoCamera()
    getCrossoverLocations?.()?.setCamera(_orthoCamera)
    _showSlicePlane()

    _active = true
    _inTransition = false
    store.setState({ cadnanoActive: true })
    // Enable side effects AFTER _active = true so the reapplyIfActive guard in
    // main.js (which checks cadnanoView.isActive()) correctly skips reapply.
    _enableSideEffects()
  }

  async function deactivate() {
    if (!_active || _inTransition) return
    _inTransition = true

    // Remove UI elements and restore settings while still in ortho mode.
    _restoreSideEffects()
    _hideSlicePlane()
    getCrossoverLocations?.()?.setCamera(sceneCtx.camera)
    // Remove row bands immediately so they don't look wrong during the reverse
    // camera pan (oblique perspective again after ortho camera is restored).
    _removeRowBands()

    // Capture ortho camera state before deactivating it.
    const orthoTarget = _orthoControls.target.clone()
    const orthoHalfH  = (_orthoCamera.top - _orthoCamera.bottom) / 2
    const camDir      = new THREE.Vector3()
    _orthoCamera.getWorldDirection(camDir)
    const camUp       = _orthoCamera.up.clone()

    // Compute equivalent perspective position: same look direction and target,
    // backed out to match the ortho zoom level — no visual jump.
    const perspFovRad = PERSP_FOV_DEG * Math.PI / 180
    const perspDist   = Math.max(orthoHalfH / Math.tan(perspFovRad / 2), 5)

    // Restore axis arrows before the bead reverse animation.
    designRenderer.setAxisArrowsVisible(true)

    _deactivateOrthoCamera()
    sceneCtx.camera.position.copy(orthoTarget).addScaledVector(camDir, -perspDist)
    sceneCtx.camera.up.copy(camUp)
    sceneCtx.camera.lookAt(orthoTarget)
    sceneCtx.controls.target.copy(orthoTarget)
    sceneCtx.controls.update()

    // ── Stage 2 reverse (250 ms): bead reverse — camera position does not change ──
    await new Promise(resolve => _animate(_cadnanoPosMap, _unfoldPosMap, resolve, ANIM_STAGE2_MS))

    // Reapply unfold offsets so all overlays snap back cleanly.
    const unfoldView = getUnfoldView?.()
    if (unfoldView?.isActive()) {
      unfoldView.setSpacing(store.getState().unfoldSpacing)
    }

    _active = false
    _inTransition = false
    _cadnanoPosMap = null
    _unfoldPosMap  = null
    store.setState({ cadnanoActive: false })

    // If unfold was auto-activated on entry, also deactivate it on exit.
    if (!_wasUnfoldActive) {
      unfoldView?.deactivate()
    }
  }

  async function toggle() {
    if (_active) return deactivate()
    else         return activate()
  }

  function isActive() { return _active }

  /**
   * Synchronous hard-exit used when a new design is loaded.
   * Cancels any running animation, restores all visual state (camera, controls,
   * axis arrows, row bands, slice plane), and resets all internal flags.
   * No-op if neither active nor in transition.
   */
  function forceExit() {
    if (!_active && !_inTransition) return
    if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null }
    _restoreSideEffects()
    _hideSlicePlane()
    getCrossoverLocations?.()?.setCamera(sceneCtx.camera)
    designRenderer.setAxisArrowsVisible(true)
    _removeRowBands()
    if (_orthoCamera) _deactivateOrthoCamera()
    _active       = false
    _inTransition = false
    _cadnanoPosMap = null
    _unfoldPosMap  = null
  }

  /**
   * Re-apply cadnano flat positions to all overlays (crossover locations, sequence
   * overlay) after they rebuild while cadnano mode is active.  Safe to call at t=1.
   */
  function reapplyPositions() {
    if (!_active || !_cadnanoPosMap || !_unfoldPosMap) return
    designRenderer.applyCadnanoPositions(_cadnanoPosMap, 1, _unfoldPosMap)
    getCrossoverLocations?.()?.applyCadnanoPositions(_cadnanoPosMap, 1, _unfoldPosMap)
    getSequenceOverlay?.()?.applyUnfoldOffsets(new Map(), 1.0, _cadnanoPosMap, null)
    getUnfoldView?.()?.applyCadnanoPositions(_cadnanoPosMap, 1, _unfoldPosMap)
  }

  return { activate, deactivate, toggle, isActive, reapplyPositions, forceExit }
}
