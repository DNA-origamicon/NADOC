/**
 * Design renderer — reactive Three.js scene builder.
 *
 * Wraps the helix renderer logic and rebuilds the scene whenever the store's
 * currentDesign or currentGeometry changes.  Exposes getBackboneEntries() for
 * the selection manager to raycast against.
 *
 * Usage:
 *   const dr = initDesignRenderer(scene, store)
 *   dr.setMode('V1.2')
 *   dr.getBackboneEntries()  // → [{ mesh, nuc }, ...]
 */

import * as THREE from 'three'
import { buildHelixObjects, buildStapleColorMap } from './helix_renderer.js'
import { resolveRepOverrides } from './representation_overrides.js'
import { buildCrossoverConnections, bezierAt, arcControlPoint, updateExtraBaseInstances, setExtraBaseInstanceFromSim, partitionExtraBaseUpdates, setExtraBaseConnectors, hideExtraBaseConnectors } from './crossover_connections.js'
import { createGlowLayer, createMultiColorGlowLayer } from './glow_layer.js'

/**
 * Initialise the design renderer.
 *
 * @param {THREE.Scene} scene
 * @param {import('../state/store.js').store} storeRef
 * @returns {{ setMode, getBackboneEntries, setStrandColor, getHelixCtrl, dispose }}
 */
export function initDesignRenderer(scene, storeRef) {
  let _helixCtrl        = null
  let _femArcUpdater    = null   // unfold_view.applyFemArcs — keeps arcs synced with applyFemPositions
  let _scalarArcUpdater = null   // unfold_view.applyFemArcColors — recolours arcs with the RMSF scalar map
  let _designVisible    = true   // controlled by setDesignVisible(); re-applied after every _rebuild
  // VISIBILITY RULE: design_renderer has ONE scene object — _helixCtrl.root.
  // Extra-base beads+slabs (from buildCrossoverConnections) are children of root,
  // so _helixCtrl.root.visible covers them automatically.
  // Arc LINE geometry lives in unfold_view._arcGroup (separate module — see main.js SCENE GEOMETRY RULE).
  let _xoverArcData     = null   // arc metadata for extra-base crossovers
  let _xoverBeadsMesh   = null   // InstancedMesh for extra-base beads
  let _xoverSlabsMesh   = null   // InstancedMesh for extra-base slabs
  let _xoverConnMesh    = null   // InstancedMesh for extra-base backbone connector cones
  let _xoverArcDataMap  = null   // Map<xoId, arcDataEntry> for O(1) lookup during animation
  let _xoverGlowLive    = []     // {pos: THREE.Vector3, arcData, localIdx} — live positions for selection glow
  // Extra-base inserts driven by a simulation frame (oxDNA/MD relaxed or trajectory):
  // Map<crossover_id, Map<k, {pos:THREE.Vector3, normal:[nx,ny,nz]}>>.  When an arc
  // is present here, its beads are placed at the REAL simulated positions and the
  // geometric Bezier interpolation is skipped for it.  Null/empty → all arcs Bezier.
  let _simXbByCrossover = null
  let _detailLevel      = 0      // current LOD (0=full,1=beads,2=cylinders); re-applied to xover extras after _rebuild
  let _currentMode      = 'normal'
  const _glowLayer         = createGlowLayer(scene)
  // Undefined-bases highlight: red, ~2× the selection glow size
  const _undefinedGlowLayer = createGlowLayer(scene, 0xff3030, 5.6)
  // oxDNA anchor highlight: purple, distinct from the green selection glow — marks the
  // strands/clusters pinned as FIXED during an E-field (or other) run.
  const _anchorGlowLayer    = createGlowLayer(scene, 0xb14aff, 3.6, 'anchorGlow')
  // Drill-v2 hover preview: yellow glow on the would-be-selected leaf (vs the green
  // selection glow). Larger than the green so its halo reads yellow over a selected
  // (green-glowing) strand. Named so gesture e2e can detect it.
  const _previewGlowLayer = createGlowLayer(scene, 0xffe000, 4.2, 'previewGlow')   // yellow hover preview
  // Drill-v2 hover preview for a crossover ARC: a yellow additive glow TUBE traced
  // along the arc polyline (the arc is a thin line — a midpoint sphere reads wrong).
  const PREVIEW_ARC_RADIUS = 0.147  // nm — tube radius (0.21 then −30% again, 2026-06-07)
  const SELECTION_ARC_RADIUS = PREVIEW_ARC_RADIUS   // green selection tube matches the yellow preview
  // Tube tessellation, doubled 2026-06-07 (user: "twice the polygons/resolution")
  // so the crossover tube reads as a smooth full cylinder, not a low-poly hex prism.
  const ARC_TUBE_RADIAL = 12                          // radial segments (was 6)
  const _arcTubeSegs = (n) => Math.max(16, n * 4)     // tubular segments (was max(8, n*2))
  let _previewArcTube = null
  // depthTest:false so the whole tube draws on top — otherwise segments behind the
  // DNA beads/slabs are occluded and the tube looks broken from some angles.
  const _previewArcMat = new THREE.MeshBasicMaterial({
    color: 0xffe000, transparent: true, opacity: 0.6,   // yellow hover preview
    blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false,
    side: THREE.DoubleSide,   // render the far wall too — FrontSide-only read as a hollow/partial tube
  })
  // Crossover SELECTION highlight: a green glow TUBE traced along the arc polyline,
  // unifying it with the yellow preview tube (user feedback 2026-06-06 — the old
  // endpoint-sphere glow read inconsistently for the thin inter-helix arc).
  let _selectionArcTube = null
  // Lasso / additive multi-crossover selection: a POOL of the same green tubes
  // (user feedback 2026-06-07 — multi-select now matches the single-click form
  // instead of the old cyan arc recolor + glow spheres).
  let _selectionArcTubes = []
  const _selectionArcMat = new THREE.MeshBasicMaterial({
    color: 0x3fb950, transparent: true, opacity: 0.75,
    blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false,
    side: THREE.DoubleSide,   // render the far wall too — FrontSide-only read as a hollow/partial tube
  })
  // Fluorescence-mode: per-fluorophore emission color glow
  const _fluoroGlowLayer = createMultiColorGlowLayer(scene)

  let _hiddenNucKeys      = new Set()  // persists across rebuilds; set by cluster visibility toggle
  let _hiddenCrossoverIds = new Set()  // extra-base bead/slab instances to suppress

  // ── Deform preview overlay ────────────────────────────────────────────────
  // While the bend/twist tool previews a deformation we show BOTH:
  //   _frozenRoot   — the committed design (before this op), kept SOLID in the
  //                   scene as the "where the design is now" reference.
  //   live preview  — the deformed RESULT (the live _helixCtrl.root), rendered at
  //                   `_ghostOpacity` as a translucent "ghost of where it will be".
  // Both null/false when not previewing. (Opacity is flipped vs the old before-
  // ghost: the reference is now solid and the result is the ghost.)
  let _frozenRoot          = null   // committed design kept solid during a preview
  let _ghostOpacity        = null   // opacity for the live (result) preview, or null
  let _captureNextAsFrozen = false  // on the NEXT rebuild, freeze the old root

  function _disposeRoot(root) {
    root.traverse(obj => {
      if (obj.geometry) obj.geometry.dispose()
      if (obj.material) {
        if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose())
        else obj.material.dispose()
      }
    })
  }

  function _traverseSetOpacity(root, opacity) {
    root.traverse(obj => {
      if (!obj.material) return
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
      for (const m of mats) {
        // Materials owned by deform_view's lerp cross-fade (helix shaft +
        // straightShaft) opt out so the dim/restore path doesn't clobber
        // their t-dependent opacity values.
        if (m.userData?.skipOpacityRestore) continue
        m.transparent = opacity < 1.0
        m.opacity     = opacity
      }
    })
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  /** Merge strandColors (hex numbers) with group color overrides (hex strings). */
  function _effectiveColors(strandColors, strandGroups) {
    const result = { ...strandColors }
    for (const group of strandGroups ?? []) {
      if (group.color) {
        const hex = parseInt(group.color.replace('#', ''), 16)
        for (const sid of group.strandIds) result[sid] = hex
      }
    }
    return result
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  /**
   * Re-skin extra-base crossover beads + slabs to honor the current global
   * coloringMode.  Only 'overhang-only' actually overrides — for every other
   * mode (including 'strand') we restore the build-time bead/slab colors
   * captured by buildCrossoverConnections.  Crossovers that bridge an overhang
   * (either endpoint nuc has overhang_id != null) keep their strand color.
   */
  function _applyXoverColoring(mode) {
    if (!_xoverArcData || !_xoverBeadsMesh || !_xoverSlabsMesh) return
    const _col = new THREE.Color()
    const ovhgOnly = (mode === 'overhang-only')
    const DIM_GRAY = 0xbbbbbb
    for (const ad of _xoverArcData) {
      const isOvhg = (ad.nucA?.overhang_id != null) || (ad.nucB?.overhang_id != null)
      const bc = (ovhgOnly && !isOvhg) ? DIM_GRAY : ad.beadBaseColor
      const sc = (ovhgOnly && !isOvhg) ? DIM_GRAY : ad.slabBaseColor
      for (let i = 0; i < ad.beadCount; i++) {
        const idx = ad.beadStartIdx + i
        _xoverBeadsMesh.setColorAt(idx, _col.setHex(bc))
        _xoverSlabsMesh.setColorAt(idx, _col.setHex(sc))
      }
      if (_xoverConnMesh) {
        for (let s = 0; s < ad.beadCount + 1; s++) {
          _xoverConnMesh.setColorAt(ad.connStartIdx + s, _col.setHex(bc))
        }
      }
    }
    if (_xoverBeadsMesh.instanceColor) _xoverBeadsMesh.instanceColor.needsUpdate = true
    if (_xoverSlabsMesh.instanceColor) _xoverSlabsMesh.instanceColor.needsUpdate = true
    if (_xoverConnMesh?.instanceColor) _xoverConnMesh.instanceColor.needsUpdate = true
  }

  /** Crossover extra-base beads/slabs are children of root, NOT part of the helix
   *  LOD meshes, so _helixCtrl.setDetailLevel() doesn't touch them — they'd stay
   *  visible in the coarse cylinders/sticks rep and poke through empty domain gaps.
   *  Hide the whole InstancedMeshes at LOD >= 2 (independent of the per-instance
   *  hide done by _applyXoverVisibility). */
  function _applyXoverExtrasLod() {
    const show = _detailLevel < 2
    if (_xoverBeadsMesh) _xoverBeadsMesh.visible = show
    if (_xoverSlabsMesh) _xoverSlabsMesh.visible = show
    if (_xoverConnMesh)  _xoverConnMesh.visible  = show
  }

  /** Zero the InstancedMesh scale for every extra-base bead/slab whose crossover
   *  ID is in _hiddenCrossoverIds.  Called after rebuild and after setHiddenCrossovers. */
  function _applyXoverVisibility() {
    if (!_xoverArcData || !_xoverBeadsMesh || !_xoverSlabsMesh) return
    if (!_hiddenCrossoverIds.size) return
    const m4   = new THREE.Matrix4()
    const pos  = new THREE.Vector3()
    const qid  = new THREE.Quaternion()
    const zero = new THREE.Vector3(0, 0, 0)
    let dirty = false
    for (const ad of _xoverArcData) {
      if (!_hiddenCrossoverIds.has(ad.xoId)) continue
      for (let i = 0; i < ad.beadCount; i++) {
        const bi = ad.beadStartIdx + i
        _xoverBeadsMesh.getMatrixAt(bi, m4)
        pos.setFromMatrixPosition(m4)
        _xoverBeadsMesh.setMatrixAt(bi, m4.compose(pos, qid, zero))
        _xoverSlabsMesh.getMatrixAt(bi, m4)
        pos.setFromMatrixPosition(m4)
        _xoverSlabsMesh.setMatrixAt(bi, m4.compose(pos, qid, zero))
        dirty = true
      }
    }
    if (dirty) {
      _xoverBeadsMesh.instanceMatrix.needsUpdate = true
      _xoverSlabsMesh.instanceMatrix.needsUpdate = true
    }
    _syncExtraBaseConnectors()
  }

  /** Hide (zero-scale) or restore (reposition) extra-base beads/slabs for
   *  crossovers whose BOTH endpoints are reference strands — so reference
   *  crossover geometry tracks the reference View toggle. */
  function _applyReferenceXoverVisibility() {
    if (!_xoverArcData || !_xoverBeadsMesh || !_xoverSlabsMesh) return
    const design = storeRef.getState().currentDesign
    const refIds = new Set((design?.strands ?? []).filter(s => s.is_reference).map(s => s.id))
    if (!refIds.size) return
    const hidden = storeRef.getState().showReferenceGeometry === false
    const m4 = new THREE.Matrix4()
    const pos = new THREE.Vector3()
    const qid = new THREE.Quaternion()
    const zero = new THREE.Vector3(0, 0, 0)
    let dirty = false
    for (const ad of _xoverArcData) {
      if (!(refIds.has(ad.nucA?.strand_id) && refIds.has(ad.nucB?.strand_id))) continue
      if (_hiddenCrossoverIds.has(ad.xoId)) continue   // already hidden by a cluster toggle
      if (hidden) {
        for (let i = 0; i < ad.beadCount; i++) {
          const bi = ad.beadStartIdx + i
          _xoverBeadsMesh.getMatrixAt(bi, m4); pos.setFromMatrixPosition(m4)
          _xoverBeadsMesh.setMatrixAt(bi, m4.compose(pos, qid, zero))
          _xoverSlabsMesh.getMatrixAt(bi, m4); pos.setFromMatrixPosition(m4)
          _xoverSlabsMesh.setMatrixAt(bi, m4.compose(pos, qid, zero))
        }
        dirty = true
      } else {
        const posA = _liveXoverPos(ad.nucA, _clusterXoverPosA)
        const posB = _liveXoverPos(ad.nucB, _clusterXoverPosB)
        if (!posA || !posB) continue
        arcControlPoint(posA, posB, ad.nucA, ad.nucB, _clusterXoverCtrl)
        updateExtraBaseInstances(
          _xoverBeadsMesh, _xoverSlabsMesh,
          ad.beadStartIdx, ad.beadCount,
          posA, _clusterXoverCtrl, posB, ad.avgAx, ad.zOffset,
        )
        dirty = true
      }
    }
    if (dirty) {
      _xoverBeadsMesh.instanceMatrix.needsUpdate = true
      _xoverSlabsMesh.instanceMatrix.needsUpdate = true
    }
    _syncExtraBaseConnectors()
  }

  const _clusterXoverPosA = new THREE.Vector3()
  const _clusterXoverPosB = new THREE.Vector3()
  const _clusterXoverCtrl = new THREE.Vector3()

  function _liveXoverPos(nuc, out) {
    const live = _helixCtrl?.getNucLivePos?.(nuc)
    if (live) return out.copy(live)
    const bp = nuc?.backbone_position
    return bp ? out.set(bp[0], bp[1], bp[2]) : null
  }

  // Reusable point buffer for connector threading (grown on demand, never freed).
  const _connPts = []
  const _connBeadMat = new THREE.Matrix4()
  function _connPoint(i) {
    while (_connPts.length <= i) _connPts.push(new THREE.Vector3())
    return _connPts[i]
  }

  function _xoverArcHidden(ad, refIds, refHidden) {
    if (_hiddenCrossoverIds.has(ad.xoId)) return true
    if (refHidden && refIds.has(ad.nucA?.strand_id) && refIds.has(ad.nucB?.strand_id)) return true
    return false
  }

  /** Re-thread the extra-base backbone connector cones through the CURRENT bead
   *  positions (read from the bead InstancedMesh) and the two live real endpoints.
   *  Derived from the already-correct beads, so it is mode-agnostic (sim / Bezier /
   *  cluster). Hidden arcs get zero-scale cones. */
  function _syncExtraBaseConnectors() {
    if (!_xoverConnMesh || !_xoverArcData || !_xoverBeadsMesh) return
    const design = storeRef.getState().currentDesign
    const refIds = new Set((design?.strands ?? []).filter(s => s.is_reference).map(s => s.id))
    const refHidden = storeRef.getState().showReferenceGeometry === false
    for (const ad of _xoverArcData) {
      const segCount = ad.beadCount + 1
      if (_xoverArcHidden(ad, refIds, refHidden)) {
        hideExtraBaseConnectors(_xoverConnMesh, ad.connStartIdx, segCount)
        continue
      }
      const posA = _liveXoverPos(ad.nucA, _clusterXoverPosA)
      const posB = _liveXoverPos(ad.nucB, _clusterXoverPosB)
      if (!posA || !posB) continue
      _connPoint(0).copy(posA)
      for (let k = 0; k < ad.beadCount; k++) {
        _xoverBeadsMesh.getMatrixAt(ad.beadStartIdx + k, _connBeadMat)
        _connPoint(k + 1).setFromMatrixPosition(_connBeadMat)
      }
      _connPoint(ad.beadCount + 1).copy(posB)
      setExtraBaseConnectors(_xoverConnMesh, ad.connStartIdx, _connPts, segCount, null)
    }
    _xoverConnMesh.instanceMatrix.needsUpdate = true
  }

  /**
   * Mixed representation: resolve the design's per-region representation
   * overrides against the current geometry and push them to the helix renderer.
   * Pure visibility (no rebuild). Clears when there are no overrides.
   */
  function _applyRepresentationOverrides(design) {
    if (!_helixCtrl?.applyRepOverrides) return
    // A rebuild always rebuilds the helix meshes at FULL detail, and the tick only
    // re-applies the global LOD when _lastDetailLevel changes — so after e.g. an
    // override save (which refetches geometry → rebuild) the fresh helixCtrl is at
    // level 0 even though the global rep is cylinders. Re-sync it here so the
    // override's notion of the global rep ("baseCyl") is correct; otherwise every
    // non-overridden column would resolve to full. No-op when already in sync.
    _helixCtrl.setDetailLevel(_detailLevel)
    const { columnRep } = resolveRepOverrides(design)
    _helixCtrl.applyRepOverrides(columnRep)
  }

  // ── Geometric scene rebuild ───────────────────────────────────────────────

  function _rebuild(geometry, design, helixAxes) {
    // Dispose previous scene objects (or freeze the committed design as the
    // solid deform-preview reference).  Extra-base beads+slabs are children of
    // root — disposed with it automatically.
    if (_helixCtrl?.root) {
      const oldRoot = _helixCtrl.root
      scene.remove(oldRoot)
      if (_captureNextAsFrozen) {
        // First preview rebuild: keep the committed design as the "where the
        // design is now" reference; the new (deformed) root below renders as the
        // translucent ghost.  Do NOT dispose it.  Force FULL opacity — the old
        // root was dimmed to 0.15 by the tool-active branch while placing planes,
        // and the solid reference must read at full strength.
        if (_frozenRoot) { _disposeRoot(_frozenRoot); scene.remove(_frozenRoot) }
        _frozenRoot = oldRoot
        _traverseSetOpacity(_frozenRoot, 1.0)
        scene.add(_frozenRoot)
        _captureNextAsFrozen = false
      } else if (oldRoot !== _frozenRoot) {
        _disposeRoot(oldRoot)
      }
    }

    _glowLayer.clear()          // stale entries after rebuild; selection_manager re-applies if needed
    _undefinedGlowLayer.clear() // caller must re-apply undefined highlight after rebuild
    _anchorGlowLayer.clear()    // caller (anchor_glow) re-applies after a rebuild
    _previewGlowLayer.clear()   // hover preview is transient; never survives a rebuild
    if (_previewArcTube) _previewArcTube.visible = false
    if (_selectionArcTube) _selectionArcTube.visible = false
    for (const t of _selectionArcTubes) { t.geometry.dispose(); scene.remove(t) }
    _selectionArcTubes = []   // multi-select tubes are children of the scene, not oldRoot
    _fluoroGlowLayer.clear()    // caller must re-apply fluorescence glow after rebuild

    // Clear stale xover refs — the old meshes were children of oldRoot, already disposed above.
    _xoverArcData    = null
    _xoverBeadsMesh  = null
    _xoverSlabsMesh  = null
    _xoverConnMesh   = null
    _xoverArcDataMap = null
    _xoverGlowLive   = []
    _simXbByCrossover = null   // drop stale simulation-driven insert positions

    if (!geometry || !design || geometry.length === 0) {
      _helixCtrl = null
      return
    }

    const { strandColors, strandGroups, loopStrandIds, staplesHidden, isolatedStrandId, coloringMode } = storeRef.getState()
    const _eff = _effectiveColors(strandColors, strandGroups)
    _helixCtrl = buildHelixObjects(geometry, design, scene, _eff, loopStrandIds ?? [], helixAxes)
    _helixCtrl.setMode(_currentMode)
    if (coloringMode && coloringMode !== 'strand') {
      _helixCtrl.applyColoring(coloringMode, design, _eff, new Set(loopStrandIds ?? []))
    }

    // Draw explicit crossover connections from design.crossovers.
    // Each connection is a line between the backbone beads of the two linked nucleotides.
    // Extra-base beads + slabs for crossovers with extra bases.
    // Line rendering (straight + arc) is handled exclusively by unfold_view.js.
    // Hidden when unfold or cadnano view is active.
    const colorMap    = buildStapleColorMap(geometry, design)
    const effectiveCols = _effectiveColors(strandColors, strandGroups)
    const xoverResult = buildCrossoverConnections(design, geometry, colorMap, effectiveCols)
    if (xoverResult) {
      _xoverArcData    = xoverResult.arcData
      _xoverBeadsMesh  = xoverResult.beadsMesh
      _xoverSlabsMesh  = xoverResult.slabsMesh
      _xoverConnMesh   = xoverResult.connMesh
      _xoverArcDataMap = new Map()
      for (const ad of _xoverArcData) _xoverArcDataMap.set(ad.xoId, ad)
      // Extra-base beads+slabs are children of root — no separate scene.add() needed.
      // root.visible covers them automatically; no extra VISIBILITY RULE required.
      _helixCtrl.root.add(xoverResult.group)
      // Re-skin extra-base meshes if a non-strand coloring mode is active —
      // build emitted strand colors, applyColoring covers helix meshes, this
      // covers the xover extras.
      if (coloringMode && coloringMode !== 'strand') _applyXoverColoring(coloringMode)
    }


    // Re-apply post-rebuild visibility state
    if (staplesHidden) _helixCtrl.setStapleVisibility(false)
    if (isolatedStrandId) _helixCtrl.setIsolatedStrand(isolatedStrandId)
    if (_hiddenNucKeys.size) _helixCtrl.setHiddenNucs(_hiddenNucKeys)
    // Reference geometry: translucent, hidden when the View toggle is off.
    const _refIds = new Set((design?.strands ?? []).filter(s => s.is_reference).map(s => s.id))
    if (_refIds.size) {
      _helixCtrl.setReferenceStrands(_refIds)
      _helixCtrl.setReferenceHidden(storeRef.getState().showReferenceGeometry === false)
    }
    // Mixed representation: pin per-region reps (must run after reference alpha,
    // since override visibility multiplies over reference alpha).
    _applyRepresentationOverrides(design)
    _applyXoverVisibility()
    _applyReferenceXoverVisibility()   // hide reference crossover extra-bases when ref toggle off
    _applyXoverExtrasLod()             // hide extra-base beads/slabs in coarse rep (survives rebuild)

    // Deform preview: the live (result) geometry is the translucent ghost over
    // the solid frozen reference.  Otherwise dim the whole scene while placing
    // the bend/twist planes.
    if (_ghostOpacity !== null) {
      _traverseSetOpacity(_helixCtrl.root, _ghostOpacity)
    } else if (storeRef.getState().deformToolActive) {
      _traverseSetOpacity(_helixCtrl.root, 0.15)
    }
  }

  // ── Fix B part 2 — in-place metadata fast path ───────────────────────────
  // When a partial geometry update arrives with a small number of changed helices
  // and the nucleotide count for those helices is unchanged (e.g. nick: same
  // positions, different strand assignment), patch entries in-place and skip
  // the full dispose+rebuild.
  //
  // Falls through to _rebuild when:
  //   • scaffold domain boundaries changed — helix axis cylinders depend on
  //     _scaffoldIntervals() which reads design.strands; patch only updates beads
  //   • is_five_prime flag changes (sphere→cube mesh-type swap needs rebuild)
  //   • a ghost/preview root is active (too complex to patch safely)
  //   • _helixCtrl is null (first load or after clear)

  function _countHelixNucs(geo, helixId) {
    let c = 0
    for (const n of geo) { if (n.helix_id === helixId) c++ }
    return c
  }

  // Returns true if any scaffold domain on the changed helices has a different
  // start_bp or end_bp between two designs.  Used to force a full rebuild when
  // strand-end-resize moves a 3' end: nuc count stays constant (geometry arrays
  // cover every helix bp regardless of strand coverage) and is_five_prime never
  // flips at a 3' boundary, so without this check _tryPatchInPlace would succeed
  // and the axis cylinders (built from _scaffoldIntervals) would not update.
  function _scaffoldCoverageChanged(changedHelixSet, prevDesign, newDesign) {
    if (!prevDesign || !newDesign) return true
    const extract = (design) => {
      const map = {}
      for (const s of design.strands) {
        if (s.strand_type !== 'scaffold') continue
        for (const d of s.domains) {
          if (!changedHelixSet.has(d.helix_id)) continue
          map[`${d.helix_id}:${d.direction}`] = `${d.start_bp},${d.end_bp}`
        }
      }
      return map
    }
    const prev = extract(prevDesign)
    const next = extract(newDesign)
    const keys = new Set([...Object.keys(prev), ...Object.keys(next)])
    for (const k of keys) {
      if (prev[k] !== next[k]) return true
    }
    return false
  }

  function _tryPatchInPlace(changedHelixIds, newGeo, prevGeo, newState) {
    if (!_helixCtrl || _ghostOpacity !== null) return false   // never patch during a deform preview
    const realIds = changedHelixIds.filter(id => !id.startsWith('__'))
    if (realIds.length === 0) return false   // only synthetic purges — nothing to patch

    // 1. Check nucleotide counts match for every real changed helix.
    for (const hid of realIds) {
      if (_countHelixNucs(newGeo, hid) !== _countHelixNucs(prevGeo ?? [], hid)) return false
    }

    // 2. Check that no nuc flips is_five_prime or is_three_prime.
    //    is_five_prime: sphere↔cube mesh-type change needs full rebuild.
    //    is_three_prime: a new strand terminal means cone topology changed
    //    (a nick was placed), requiring a full rebuild to re-sort strands
    //    and rebuild cross-helix connections.
    const helixSet = new Set(realIds)
    for (const nuc of newGeo) {
      if (!helixSet.has(nuc.helix_id)) continue
      const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
      const existing = _helixCtrl.lookupEntry(key)
      if (existing && existing.nuc.is_five_prime !== !!nuc.is_five_prime) return false
      if (existing && existing.nuc.is_three_prime !== !!nuc.is_three_prime) return false
    }

    // 3. Eligible for in-place patch.
    const partialNucs = newGeo.filter(n => helixSet.has(n.helix_id))
    const customColors = _effectiveColors(newState.strandColors, newState.strandGroups)
    const loopSet = new Set(newState.loopStrandIds ?? [])
    _helixCtrl.patchNucleotides(partialNucs, customColors, loopSet)
    _helixCtrl.setMode(_currentMode)
    if (newState.coloringMode && newState.coloringMode !== 'strand') {
      _helixCtrl.applyColoring(newState.coloringMode, newState.currentDesign, customColors, loopSet)
    }
    return true
  }

  // ── Domain Designer modal — defer rebuilds while open ──────────────────────
  // While the DD modal is active, the user is making lots of small edits
  // (rename / Tm / sequence override / sub-domain split). We don't want each
  // PATCH to trigger a full main-scene rebuild. The flag is set/cleared by
  // `setDomainDesignerModalActive` from the popup. On flip True→False we
  // perform ONE rebuild against the latest design + geometry.
  let _ddDeferredPending = false
  let _ddPrevModalActive = !!storeRef.getState().domainDesigner?.modalActive

  // Subscribe to store changes and rebuild when geometry or design changes.
  storeRef.subscribe((newState, prevState) => {
    const geoChanged    = newState.currentGeometry  !== prevState.currentGeometry ||
                          newState.currentHelixAxes !== prevState.currentHelixAxes
    const designChanged = newState.currentDesign    !== prevState.currentDesign
    const loopChanged   = newState.loopStrandIds    !== prevState.loopStrandIds

    // Detect modal-active transitions FIRST so the True→False flush still
    // honours pending deferred rebuilds.
    const ddActive = !!newState.domainDesigner?.modalActive
    const ddJustClosed = (_ddPrevModalActive === true && ddActive === false)
    _ddPrevModalActive = ddActive

    if (ddActive && (geoChanged || designChanged || loopChanged)) {
      // Stash the rebuild for when the modal closes.
      _ddDeferredPending = true
      return
    }
    if (ddJustClosed && _ddDeferredPending) {
      _ddDeferredPending = false
      _rebuild(newState.currentGeometry, newState.currentDesign, newState.currentHelixAxes)
      if (!_designVisible && _helixCtrl?.root) _helixCtrl.root.visible = false
      return
    }

    // Coloring-mode toggle: pure color update, no rebuild needed.
    if (newState.coloringMode !== prevState.coloringMode && _helixCtrl) {
      const eff = _effectiveColors(newState.strandColors ?? {}, newState.strandGroups)
      _helixCtrl.applyColoring(
        newState.coloringMode || 'strand',
        newState.currentDesign,
        eff,
        new Set(newState.loopStrandIds ?? []),
      )
      _applyXoverColoring(newState.coloringMode || 'strand')
    }

    // Reference-geometry View toggle: pure visibility change, no rebuild. Must run
    // BEFORE the no-geo-change early-return below. Hides strand beads/cones/slabs/
    // fluoros/extensions + helical axis (helix_renderer) and crossover extra-bases.
    // Arc lines live in unfold_view and react to the same store key there.
    if (newState.showReferenceGeometry !== prevState.showReferenceGeometry && _helixCtrl) {
      _helixCtrl.setReferenceHidden(newState.showReferenceGeometry === false)
      _applyReferenceXoverVisibility()
    }

    // Mixed-representation overrides are a visual-only design field: editing them
    // changes no topology array, so the rebuild is skipped below. Apply them here
    // as a pure visibility update (no rebuild) whenever the design changed.
    if (designChanged && _helixCtrl &&
        newState.currentDesign?.representation_overrides !== prevState.currentDesign?.representation_overrides) {
      _applyRepresentationOverrides(newState.currentDesign)
    }

    if (!geoChanged && !designChanged && !loopChanged) return

    // Skip rebuild when only visual-only design fields changed (cluster_transforms,
    // configurations, camera_poses, animations) — topology arrays are unchanged.
    // This prevents a spurious full-scene rebuild after patchCluster, which would
    // reset visual cluster positions and trigger an unnecessary geometry refetch.
    if (designChanged && !geoChanged && !loopChanged) {
      const p = prevState.currentDesign, n = newState.currentDesign
      if (p && n &&
          p.helices.length      === n.helices.length      &&
          p.strands.length      === n.strands.length      &&
          p.crossovers.length   === n.crossovers.length   &&
          p.crossovers.every((xo, i) => xo.extra_bases === n.crossovers[i]?.extra_bases) &&
          p.deformations.length === n.deformations.length &&
          p.extensions.length   === n.extensions.length   &&
          p.overhangs.length    === n.overhangs.length) {
        return
      }
    }

    // Fix B part 2: try in-place patch before committing to full rebuild.
    if (geoChanged && newState.lastPartialChangedHelixIds?.length) {
      const _changedSet = new Set(
        newState.lastPartialChangedHelixIds.filter(id => !id.startsWith('__')))
      const _coverageChanged = _scaffoldCoverageChanged(
        _changedSet, prevState.currentDesign, newState.currentDesign)
      if (!_coverageChanged && _tryPatchInPlace(
        newState.lastPartialChangedHelixIds,
        newState.currentGeometry,
        prevState.currentGeometry,
        newState,
      )) {
        // In-place patch succeeded — no rebuild needed.
        // Still run post-rebuild side-effects that depend on design state.
        if (newState.staplesHidden !== prevState.staplesHidden) {
          _helixCtrl?.setStapleVisibility(!newState.staplesHidden)
        }
        if (newState.isolatedStrandId !== prevState.isolatedStrandId) {
          _helixCtrl?.setIsolatedStrand(newState.isolatedStrandId)
        }
        return
      }
    }

    if (window._cnDebug && storeRef.getState().cadnanoActive) {
      console.warn(`[CN f${window._cnFrame}] design_renderer._rebuild() geo:${geoChanged} des:${designChanged} loop:${loopChanged}`,
        new Error().stack.split('\n').slice(2, 8).join('\n'))
    }
    _rebuild(newState.currentGeometry, newState.currentDesign, newState.currentHelixAxes)
    // Re-apply visibility after rebuild — root covers extra-base beads/slabs as children.
    if (!_designVisible) {
      if (_helixCtrl?.root) _helixCtrl.root.visible = false
    }

    // Group membership/color changes are color-only — no geometry rebuild needed.
    // Compute per-strand effective color diff and apply live via setStrandColor.
    if (newState.strandGroups !== prevState.strandGroups && _helixCtrl) {
      const prevEff = _effectiveColors(prevState.strandColors ?? {}, prevState.strandGroups)
      const newEff  = _effectiveColors(newState.strandColors  ?? {}, newState.strandGroups)
      const palette = _helixCtrl.getPaletteColors()  // unmodified build-time palette
      // Union of all strand IDs that appear in either effective map or the palette.
      const allIds  = new Set([...Object.keys(prevEff), ...Object.keys(newEff), ...palette.keys()])
      for (const sid of allIds) {
        const oldColor = prevEff[sid] ?? palette.get(sid)
        const newColor = newEff[sid]  ?? palette.get(sid)
        if (newColor != null && newColor !== oldColor) {
          _helixCtrl.setStrandColor(sid, newColor)
        }
      }
      // In non-strand modes, restore the active coloring on top of the per-strand updates.
      if (newState.coloringMode && newState.coloringMode !== 'strand') {
        _helixCtrl.applyColoring(
          newState.coloringMode, newState.currentDesign, newEff, new Set(newState.loopStrandIds ?? []))
      }
    }

    // Thicken axis arrows when the bend/twist deformation tool is active.
    if (newState.deformToolActive !== prevState.deformToolActive) {
      _helixCtrl?.setDeformMode(!!newState.deformToolActive)
    }

    // Hide/show all staple strands.
    if (newState.staplesHidden !== prevState.staplesHidden) {
      _helixCtrl?.setStapleVisibility(!newState.staplesHidden)
    }

    // Isolate a single staple strand (dim all others).
    if (newState.isolatedStrandId !== prevState.isolatedStrandId) {
      _helixCtrl?.setIsolatedStrand(newState.isolatedStrandId)
    }

    // Extra-base beads+slabs now track arc positions during all transitions
    // (unfold, cadnano, deform) via updateExtraBaseArc() — no need to hide.
  })

  // Build immediately if the store already has data (e.g. on hot reload).
  const { currentGeometry, currentDesign, currentHelixAxes } = storeRef.getState()
  if (currentGeometry && currentDesign) {
    _rebuild(currentGeometry, currentDesign, currentHelixAxes)
    // Re-apply visibility after rebuild — root covers extra-base beads/slabs as children.
    if (!_designVisible) {
      if (_helixCtrl?.root) _helixCtrl.root.visible = false
    }
  }

  return {
    setMode(mode) {
      _currentMode = mode
      _helixCtrl?.setMode(mode)
    },

    getBackboneEntries() {
      return _helixCtrl?.backboneEntries ?? []
    },

    getConeEntries() {
      return _helixCtrl?.coneEntries ?? []
    },

    getSlabEntries() {
      return _helixCtrl?.slabEntries ?? []
    },

    // ── Instance update delegates (used by selection_manager) ─────────────
    setEntryColor(entry, hex)  { _helixCtrl?.setEntryColor(entry, hex) },
    setBeadScale(entry, s)     { _helixCtrl?.setBeadScale(entry, s) },
    setConeXZScale(entry, r)   { _helixCtrl?.setConeXZScale(entry, r) },

    /**
     * Apply a custom colour to a strand and persist it in the store so it
     * survives scene rebuilds.
     */
    /** Show green additive-blend glow spheres over the given backbone entries. */
    setGlowEntries(entries) { _glowLayer.setEntries(entries) },
    clearGlow()              { _glowLayer.clear() },

    // Drill-v2 hover preview (yellow glow on the would-be-selected leaf).
    setPreviewGlow(entries)  { _previewGlowLayer.setEntries(entries) },
    clearPreviewGlow()       { _previewGlowLayer.clear() },

    // Yellow glow tube traced through a crossover arc's polyline (world-space points).
    setPreviewArc(points) {
      if (!points || points.length < 2) return
      const curve = new THREE.CatmullRomCurve3(points)
      const geo   = new THREE.TubeGeometry(curve, _arcTubeSegs(points.length), PREVIEW_ARC_RADIUS, ARC_TUBE_RADIAL, false)
      if (_previewArcTube) {
        _previewArcTube.geometry.dispose()
        _previewArcTube.geometry = geo
        _previewArcTube.visible  = true
      } else {
        _previewArcTube = new THREE.Mesh(geo, _previewArcMat)
        _previewArcTube.renderOrder   = 1
        _previewArcTube.frustumCulled = false
        _previewArcTube.name          = 'previewArcTube'
        scene.add(_previewArcTube)
      }
    },
    clearPreviewArc() { if (_previewArcTube) _previewArcTube.visible = false },

    // Green selection glow tube along a crossover arc's polyline (world-space points).
    setSelectionArc(points) {
      if (!points || points.length < 2) return
      const curve = new THREE.CatmullRomCurve3(points)
      const geo   = new THREE.TubeGeometry(curve, _arcTubeSegs(points.length), SELECTION_ARC_RADIUS, ARC_TUBE_RADIAL, false)
      if (_selectionArcTube) {
        _selectionArcTube.geometry.dispose()
        _selectionArcTube.geometry = geo
        _selectionArcTube.visible  = true
      } else {
        _selectionArcTube = new THREE.Mesh(geo, _selectionArcMat)
        _selectionArcTube.renderOrder   = 1
        _selectionArcTube.frustumCulled = false
        _selectionArcTube.name          = 'selectionArcTube'
        scene.add(_selectionArcTube)
      }
    },
    clearSelectionArc() { if (_selectionArcTube) _selectionArcTube.visible = false },

    // Green selection glow tubes for MULTIPLE crossover arcs (lasso / additive
    // multi-select). Mirrors setSelectionArc but pools one tube mesh per arc,
    // reusing the same green material so multi-select reads identically to a
    // single click (user feedback 2026-06-07). Pass [] to clear.
    setSelectionArcs(arcsPoints) {
      for (const t of _selectionArcTubes) { t.geometry.dispose(); scene.remove(t) }
      _selectionArcTubes = []
      for (const points of arcsPoints ?? []) {
        if (!points || points.length < 2) continue
        const curve = new THREE.CatmullRomCurve3(points)
        const geo   = new THREE.TubeGeometry(curve, _arcTubeSegs(points.length), SELECTION_ARC_RADIUS, ARC_TUBE_RADIAL, false)
        const tube  = new THREE.Mesh(geo, _selectionArcMat)
        tube.renderOrder   = 1
        tube.frustumCulled = false
        tube.name          = 'selectionArcTubeMulti'
        scene.add(tube)
        _selectionArcTubes.push(tube)
      }
    },
    clearSelectionArcs() {
      for (const t of _selectionArcTubes) { t.geometry.dispose(); scene.remove(t) }
      _selectionArcTubes = []
    },

    // DEBUG metric — inspect the LIVE crossover tubes' actual rendered geometry so
    // "how many sides / is it complete" is measurable, not eyeballed. Reachable via
    // window.__NADOC_DBG__.tubeStats() after selecting a crossover.
    getSelectionArcTubeStats() {
      const inspect = (mesh, label) => {
        if (!mesh) return null
        const g = mesh.geometry
        const pos = g.attributes?.position
        let nan = 0
        for (let i = 0; pos && i < pos.count; i++) {
          if (!Number.isFinite(pos.getX(i)) || !Number.isFinite(pos.getY(i)) || !Number.isFinite(pos.getZ(i))) nan++
        }
        g.computeBoundingBox()
        const size = g.boundingBox && !g.boundingBox.isEmpty()
          ? g.boundingBox.getSize(new THREE.Vector3()).toArray().map(v => +v.toFixed(3))
          : [0, 0, 0]
        const p = g.parameters ?? {}
        return {
          label,
          visible: mesh.visible,
          sides: p.radialSegments,            // ← the "number of sides" validation metric
          tubularSegments: p.tubularSegments,
          radius: p.radius,
          doubleSided: mesh.material?.side === THREE.DoubleSide,
          vertexCount: pos?.count ?? 0,
          triangleCount: g.index ? g.index.count / 3 : 0,
          nanVertices: nan,
          bboxSize: size,
          complete: nan === 0 && size.every(v => v > 0),
        }
      }
      return [
        inspect(_selectionArcTube, 'single'),
        ..._selectionArcTubes.map((t, i) => inspect(t, `multi[${i}]`)),
        inspect(_previewArcTube, 'preview'),
      ].filter(Boolean)
    },

    /** Show red oversized glow over backbone entries with undefined sequence. */
    setUndefinedHighlight(entries) { _undefinedGlowLayer.setEntries(entries) },
    clearUndefinedHighlight()      { _undefinedGlowLayer.clear() },

    /** Show purple glow over the backbone entries of oxDNA anchor (fixed) elements. */
    setAnchorGlow(entries) { _anchorGlowLayer.setEntries(entries) },
    clearAnchorGlow()      { _anchorGlowLayer.clear() },

    /**
     * Show emission-color glows for fluorophore beads.
     * @param {Array<{pos: THREE.Vector3, emissionColor: number}>} entries
     */
    setFluorescenceGlow(entries)  { _fluoroGlowLayer.setEntries(entries) },
    clearFluorescenceGlow()       { _fluoroGlowLayer.clear() },
    /** Active fluorophore glow-sprite count (e2e uses it to confirm the View ▸
     *  Fluorescence toggle actually rendered the glows). */
    fluoroGlowCount()             { return _fluoroGlowLayer.count() },

    /**
     * Re-read current entry.pos values for all active glow layers.
     * Call each frame during unfold animation after bead positions are mutated.
     */
    refreshAllGlow() {
      _glowLayer.refresh()
      _undefinedGlowLayer.refresh()
      _anchorGlowLayer.refresh()
      _previewGlowLayer.refresh()
      _fluoroGlowLayer.refresh()
    },

    setStrandColor(strandId, hexColor) {
      const { strandColors } = storeRef.getState()
      storeRef.setState({ strandColors: { ...strandColors, [strandId]: hexColor } })
      _helixCtrl?.setStrandColor(strandId, hexColor)
    },

    getHelixCtrl() {
      return _helixCtrl
    },

    /**
     * Show or hide ALL design geometry (used by assembly mode and CG/atomistic toggle).
     *
     * design_renderer has ONE scene object: _helixCtrl.root.
     * Extra-base beads+slabs (from buildCrossoverConnections) are children of root,
     * so setting root.visible covers them automatically.
     * Arc LINE geometry lives in unfold_view._arcGroup — call unfoldView.setArcsVisible()
     * separately (see main.js _setDesignGeometryVisible for the coordinated entry point).
     */
    setDesignVisible(visible) {
      _designVisible = visible
      if (_helixCtrl?.root) _helixCtrl.root.visible = visible
    },

    /**
     * Apply mrDNA-relaxed backbone positions as a scene overlay.
     * @param {Array<{helix_id, bp_index, direction, backbone_position}>} updates
     */
    applyFemPositions(updates, amp = 1.0) {
      // Split off crossover extra-base inserts (helix_id "__xb__"): the simulation
      // frame carries their REAL positions, which the helix renderer can't place
      // (no design key). Route them to the extra-base bead/slab instances below.
      // simXb is null when the frame has no inserts or updates===null → Bezier.
      const { real: realUpdates, simXb } = partitionExtraBaseUpdates(updates)
      _simXbByCrossover = simXb

      _helixCtrl?.applyFemPositions(realUpdates, amp)
      // Keep crossover arc lines (owned by unfold_view) in sync — applyFemPositions
      // moves beads/cones/slabs but not the arcs, which otherwise lag at the
      // original design positions during an mrDNA/oxDNA display overlay.
      _femArcUpdater?.(realUpdates, amp)
      // Extra-base crossover beads live in a separate group and are not touched
      // by the helix renderer's FEM/MD overlay. Drive them from the simulation
      // frame when present, else re-interpolate from the now-live endpoint
      // positions (reverted-to-geometry when updates===null).
      this.applyClusterCrossoverUpdate([])
    },

    /** Register unfold_view's applyFemArcs so the arcs follow applyFemPositions. */
    setFemArcUpdater(fn) { _femArcUpdater = fn },

    /** Register unfold_view's applyFemArcColors so crossover arcs follow the
     *  scalar (RMSF) recolour. */
    setScalarArcUpdater(fn) { _scalarArcUpdater = fn },

    /**
     * Recolour by a scalar (e.g. per-base RMSF) — the oxDNA flexibility map.
     * `colorByKey` maps "helix_id:bp_index:direction" → hex int.  Recolours the
     * backbone beads + base slabs + direction cones (helix_renderer) AND the
     * crossover arcs (unfold_view, via the registered arc updater).  The previous
     * colours are captured and restored by clearScalarColors().
     */
    applyScalarColors(colorByKey) {
      _helixCtrl?.applyScalarColors(colorByKey)
      _scalarArcUpdater?.(colorByKey)
    },
    clearScalarColors() {
      _helixCtrl?.clearScalarColors()
      _scalarArcUpdater?.(null)
    },

    setDetailLevel(level) {
      _detailLevel = level
      _helixCtrl?.setDetailLevel(level)
      _applyXoverExtrasLod()
    },

    setBeadRadius(r)     { _helixCtrl?.setBeadRadius(r) },
    setCylinderRadius(r) { _helixCtrl?.setCylinderRadius(r) },

    /** Current GLOBAL LOD level: 0=full, 1=beads, 2=cylinders. Use this — not the
     *  cylinder mesh's .visible — to decide "are beads globally hidden", since
     *  mixed-representation overrides make the cylinder mesh visible at full LOD. */
    getDetailLevel()                 { return _detailLevel },

    getCylinderMesh()                { return _helixCtrl?.getCylinderMesh() ?? null },
    getOverhangCylinderMesh()        { return _helixCtrl?.getOverhangCylinderMesh() ?? null },
    getCylinderDomainData()          { return _helixCtrl?.getCylinderDomainData() ?? [] },
    getCylinderDomainAt(id)          { return _helixCtrl?.getCylinderDomainAt(id) ?? null },
    getOverhangCylinderDomainAt(id)  { return _helixCtrl?.getOverhangCylinderDomainAt(id) ?? null },
    getLinkerBridgeCylinderMesh()    { return _helixCtrl?.getLinkerBridgeCylinderMesh() ?? null },
    getLinkerBridgeCylinderAt(id)    { return _helixCtrl?.getLinkerBridgeCylinderAt(id) ?? null },
    highlightCylinderStrands(sids)   { _helixCtrl?.highlightCylinderStrands(sids) },
    clearCylinderHighlight()         { _helixCtrl?.clearCylinderHighlight() },
    // Per-domain cylinder selection glow + cylinder-rep predicates (mixed rep).
    glowCylinderDomains(refs)        { _helixCtrl?.glowCylinderDomains(refs) },
    clearCylinderDomainGlow()        { _helixCtrl?.clearCylinderDomainGlow() },
    refreshCylinderDomainGlow()      { _helixCtrl?.refreshCylinderDomainGlow() },
    isColumnCylinder(helixId, bp)    { return _helixCtrl?.isColumnCylinder(helixId, bp) ?? false },
    columnRepAt(helixId, bp)         { return _helixCtrl?.columnRepAt(helixId, bp) ?? 'full' },
    isColumnAtomistic(helixId, bp)   { const r = _helixCtrl?.columnRepAt(helixId, bp); return r === 'vdw' || r === 'ballstick' },
    isColumnSurface(helixId, bp)     { return _helixCtrl?.columnRepAt(helixId, bp) === 'surface' },
    isDomainCylinder(strandId, di)   { return _helixCtrl?.isDomainCylinder(strandId, di) ?? false },

    /**
     * Return live {pos} glow entries for extra-base crossover beads on the given strand IDs.
     * The pos vectors are updated in-place by updateExtraBaseArc so that
     * refreshAllGlow() keeps the glow aligned during expanded-spacing animation.
     * Used by selection_manager to include xover beads in the selection glow.
     */
    getXoverBeadGlowEntries(strandIds) {
      if (!_xoverBeadsMesh || !_xoverArcData) return []
      const ids = new Set(strandIds)
      _xoverGlowLive = []
      const m = new THREE.Matrix4()
      for (const ad of _xoverArcData) {
        if (!ids.has(ad.nucA.strand_id)) continue
        for (let i = 0; i < ad.beadCount; i++) {
          _xoverBeadsMesh.getMatrixAt(ad.beadStartIdx + i, m)
          _xoverGlowLive.push({ pos: new THREE.Vector3().setFromMatrixPosition(m), arcData: ad, localIdx: i })
        }
      }
      return _xoverGlowLive
    },

    /**
     * Scale extra-base crossover beads for the given strand IDs.
     * Pass scale=1.0 to restore default size.
     */
    setXoverBeadScale(strandIds, scale) {
      if (!_xoverBeadsMesh || !_xoverArcData) return
      const ids = new Set(strandIds)
      const m4  = new THREE.Matrix4()
      const pos = new THREE.Vector3()
      const idq = new THREE.Quaternion()
      const scl = new THREE.Vector3(scale, scale, scale)
      let dirty = false
      for (const ad of _xoverArcData) {
        if (!ids.has(ad.nucA.strand_id)) continue
        for (let i = 0; i < ad.beadCount; i++) {
          const idx = ad.beadStartIdx + i
          _xoverBeadsMesh.getMatrixAt(idx, m4)
          pos.setFromMatrixPosition(m4)
          _xoverBeadsMesh.setMatrixAt(idx, m4.compose(pos, idq, scl))
          dirty = true
        }
      }
      if (dirty) _xoverBeadsMesh.instanceMatrix.needsUpdate = true
    },

    /**
     * Remove the mrDNA relaxed-position overlay: revert beads to design geometry.
     * Skip revertToGeometry when cadnano or unfold modes own bead positions —
     * those modes will restore positions themselves on deactivation.
     */
    clearFemOverlay() {
      const { cadnanoActive, unfoldActive } = storeRef.getState()
      if (!cadnanoActive && !unfoldActive) {
        _helixCtrl?.revertToGeometry()
      }
    },

    /**
     * Apply per-helix translation offsets for the 2D unfold animation.
     * Delegates to helixCtrl; returns cross-helix connections for arc drawing.
     *
     * @param {Map<string, THREE.Vector3>} helixOffsets
     * @param {number} t  lerp factor 0→1
     * @returns {Array<{from, to}>|[]}
     */
    applyUnfoldOffsets(helixOffsets, t, straightPosMap, straightAxesMap) {
      return _helixCtrl?.applyUnfoldOffsets(helixOffsets, t, straightPosMap, straightAxesMap) ?? []
    },

    applyUnfoldOffsetsExtensions(extArcMap, t, straightPosMap = null) {
      _helixCtrl?.applyUnfoldOffsetsExtensions(extArcMap, t, straightPosMap)
    },

    applyCadnanoPositions(cadnanoPosMap, t, unfoldPosMap) {
      _helixCtrl?.applyCadnanoPositions(cadnanoPosMap, t, unfoldPosMap)
    },

    snapshotPositions() {
      return _helixCtrl?.snapshotPositions() ?? new Map()
    },

    getFluoroEntries() {
      return _helixCtrl?.getFluoroEntries() ?? []
    },

    setExtensionsVisible(visible) {
      _helixCtrl?.setExtensionsVisible(visible)
    },

    /**
     * Hide/show nucleotides by domain-aware key set.  Keys are either:
     *   'h:<helix_id>'                 — hide whole helix (helix-level cluster)
     *   'd:<strand_id>:<domain_index>' — hide specific domain (domain-level cluster)
     * Persists across geometry rebuilds.
     * @param {Set<string>} keys
     */
    setHiddenNucs(keys) {
      _hiddenNucKeys = keys instanceof Set ? keys : new Set(keys)
      _helixCtrl?.setHiddenNucs(_hiddenNucKeys)
    },

    /**
     * Hide extra-base crossover beads/slabs for the given crossover IDs.
     * Persists across geometry rebuilds (re-applied after _rebuild).
     * @param {Set<string>} ids  Crossover IDs whose extra bases should be hidden.
     */
    setHiddenCrossovers(ids) {
      _hiddenCrossoverIds = ids instanceof Set ? ids : new Set(ids)
      _applyXoverVisibility()
    },

    /**
     * Lerp all geometry between straight and deformed positions.
     * @param {Map<string, THREE.Vector3>} straightPosMap  key "hid:bp:dir" → straight pos
     * @param {Map<string, {start,end}>} straightAxesMap   key helix_id → straight axis anchors
     * @param {Map<string, THREE.Vector3>} straightBnMap   key "hid:bp:dir" → straight base_normal
     * @param {number} t  lerp factor 0=straight, 1=deformed
     */
    applyDeformLerp(straightPosMap, straightAxesMap, straightBnMap, t) {
      _helixCtrl?.applyDeformLerp(straightPosMap, straightAxesMap, straightBnMap, t)
    },

    /** Binary curved-vs-straight axis shaft toggle for curved helices.
     *  Called by deform_view at the start of activate/deactivate so the
     *  axis line switches immediately to the destination state. */
    setAxisShaftMode(active) {
      _helixCtrl?.setAxisShaftMode(active)
    },

    /**
     * Return cross-helix backbone connections at current world positions.
     * Called by unfold_view.js when geometry is loaded/changed.
     */
    getCrossHelixConnections() {
      return _helixCtrl?.getCrossHelixConnections() ?? []
    },

    /**
     * Find the crossover whose 3D midpoint is closest to (sx, sy) in screen
     * pixels, within `thresholdPx`.  Returns the matching Crossover object from
     * design.crossovers, or null.
     *
     * @param {number} sx  Screen X (relative to canvas left).
     * @param {number} sy  Screen Y (relative to canvas top).
     * @param {THREE.Camera} cam  The active render camera.
     * @param {HTMLCanvasElement} cvs  The canvas element (for size).
     * @param {number} [thresholdPx=14]
     * @returns {object|null}  The matched crossover object, or null.
     */
    getCrossoverAt(sx, sy, cam, cvs, thresholdPx = 14) {
      const design = storeRef.getState().currentDesign
      const geo    = storeRef.getState().currentGeometry
      if (!design?.crossovers?.length || !geo?.length) return null

      const nucMap = new Map()
      for (const nuc of geo) {
        nucMap.set(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`, nuc)
      }

      const w = cvs.clientWidth, h = cvs.clientHeight
      const _p = new THREE.Vector3()
      let best = null, bestDist = thresholdPx

      for (const xo of design.crossovers) {
        const nucA = nucMap.get(`${xo.half_a.helix_id}:${xo.half_a.index}:${xo.half_a.strand}`)
        const nucB = nucMap.get(`${xo.half_b.helix_id}:${xo.half_b.index}:${xo.half_b.strand}`)
        if (!nucA || !nucB) continue
        // Midpoint of the crossover in world space
        _p.set(
          (nucA.backbone_position[0] + nucB.backbone_position[0]) * 0.5,
          (nucA.backbone_position[1] + nucB.backbone_position[1]) * 0.5,
          (nucA.backbone_position[2] + nucB.backbone_position[2]) * 0.5,
        )
        _p.project(cam)
        const px = ( _p.x * 0.5 + 0.5) * w
        const py = (-_p.y * 0.5 + 0.5) * h
        const d = Math.hypot(px - sx, py - sy)
        if (d < bestDist) { bestDist = d; best = xo }
      }
      return best
    },

    /**
     * Update extra-base crossover meshes after a cluster drag frame.
     * Line rendering is handled by unfold_view.js (applyClusterArcUpdate),
     * but extra-base beads/slabs are owned by this renderer and need to track
     * the live nucleotide positions immediately.
     *
     * @param {string[]} helixIds  IDs of helices that just moved.
     */
    applyClusterCrossoverUpdate(helixIds) {
      if (!_xoverArcData || !_xoverBeadsMesh || !_xoverSlabsMesh) return
      const moved = new Set(helixIds ?? [])
      let dirty = false
      for (const ad of _xoverArcData) {
        if (_hiddenCrossoverIds.has(ad.xoId)) continue
        if (moved.size && !moved.has(ad.nucA?.helix_id) && !moved.has(ad.nucB?.helix_id)) continue

        // Simulation-driven: place each extra base at its REAL simulated position.
        const sim = _simXbByCrossover?.get(ad.xoId)
        if (sim) {
          for (let k = 0; k < ad.beadCount; k++) {
            const s = sim.get(k)
            if (!s) continue
            setExtraBaseInstanceFromSim(
              _xoverBeadsMesh, _xoverSlabsMesh, ad.beadStartIdx + k, s.pos, s.normal, ad.avgAx)
            for (const g of _xoverGlowLive) {
              if (g.arcData === ad && g.localIdx === k) g.pos.copy(s.pos)
            }
          }
          dirty = true
          continue
        }

        // Geometric fallback: Bezier-interpolate from the live endpoint positions.
        const posA = _liveXoverPos(ad.nucA, _clusterXoverPosA)
        const posB = _liveXoverPos(ad.nucB, _clusterXoverPosB)
        if (!posA || !posB) continue
        arcControlPoint(posA, posB, ad.nucA, ad.nucB, _clusterXoverCtrl)
        updateExtraBaseInstances(
          _xoverBeadsMesh, _xoverSlabsMesh,
          ad.beadStartIdx, ad.beadCount,
          posA, _clusterXoverCtrl, posB, ad.avgAx, ad.zOffset,
        )
        for (const g of _xoverGlowLive) {
          if (g.arcData !== ad) continue
          bezierAt(posA, _clusterXoverCtrl, posB, (g.localIdx + 1) / (ad.beadCount + 1), g.pos)
        }
        dirty = true
      }
      if (dirty) this.flushExtraBaseMeshes()
    },

    /**
     * Reposition extra-base beads+slabs for a single crossover arc.
     * Called per-arc per-frame by unfold_view animation loops.
     */
    updateExtraBaseArc(crossoverId, posA, ctrl, posB) {
      if (!_xoverArcDataMap || !_xoverBeadsMesh || !_xoverSlabsMesh) return
      if (_hiddenCrossoverIds.has(crossoverId)) return
      const ad = _xoverArcDataMap.get(crossoverId)
      if (!ad) return
      updateExtraBaseInstances(
        _xoverBeadsMesh, _xoverSlabsMesh,
        ad.beadStartIdx, ad.beadCount,
        posA, ctrl, posB, ad.avgAx, ad.zOffset,
      )
      // Keep selection glow live-positions in sync with the bead positions.
      // bezierAt uses t = i/(n+1), which is identical to updateExtraBaseInstances.
      for (const g of _xoverGlowLive) {
        if (g.arcData !== ad) continue
        bezierAt(posA, ctrl, posB, (g.localIdx + 1) / (ad.beadCount + 1), g.pos)
      }
    },

    /**
     * Flush extra-base InstancedMesh matrices to GPU.
     * Call once after batching all updateExtraBaseArc() calls for a frame.
     */
    flushExtraBaseMeshes() {
      if (_xoverBeadsMesh) _xoverBeadsMesh.instanceMatrix.needsUpdate = true
      if (_xoverSlabsMesh) _xoverSlabsMesh.instanceMatrix.needsUpdate = true
      _syncExtraBaseConnectors()
    },

    getAxisArrows() {
      return _helixCtrl?.getAxisArrows() ?? []
    },

    setAxisArrowsVisible(visible) {
      _helixCtrl?.setAxisArrowsVisible(visible)
    },

    getDistLabelInfo() {
      return _helixCtrl?.getDistLabelInfo() ?? null
    },

    /**
     * Fade all geometry to `opacity` (0–1).  Used by the deformation editor
     * to dim the scene when the bend/twist tool is active.  Skipped during a
     * deform preview (the begin/endDeformPreview pair owns opacity then).
     */
    setToolOpacity(opacity) {
      if (_ghostOpacity !== null) return
      if (!_helixCtrl?.root) return
      _traverseSetOpacity(_helixCtrl.root, opacity)
    },

    /**
     * Begin a deform preview overlay: freeze the committed design as the SOLID
     * reference and render every subsequent (deformed) rebuild at `ghostOpacity`
     * as a translucent "ghost of where it will be".  Call once per preview
     * session, BEFORE the first preview op changes the geometry.
     */
    beginDeformPreview(ghostOpacity) {
      if (!_helixCtrl?.root) return
      _captureNextAsFrozen = true
      _ghostOpacity = ghostOpacity
    },

    /**
     * End the deform preview overlay: dispose the frozen reference and restore
     * the live geometry to the right opacity (solid, or the 0.15 tool dim if the
     * bend/twist tool is still active placing planes).  Idempotent.
     */
    endDeformPreview() {
      if (_frozenRoot) { _disposeRoot(_frozenRoot); scene.remove(_frozenRoot); _frozenRoot = null }
      _ghostOpacity = null
      _captureNextAsFrozen = false
      if (_helixCtrl?.root) {
        _traverseSetOpacity(_helixCtrl.root, storeRef.getState().deformToolActive ? 0.15 : 1.0)
      }
    },

    dispose() {
      if (_frozenRoot) { scene.remove(_frozenRoot); _frozenRoot = null }
      if (_helixCtrl?.root) scene.remove(_helixCtrl.root)
      _helixCtrl = null
    },
  }
}
