/**
 * Design renderer — reactive Three.js scene builder.
 *
 * Wraps the helix renderer logic and rebuilds the scene whenever the store's
 * currentDesign or currentGeometry changes.  Exposes getBackboneEntries() for
 * the selection manager to raycast against.
 *
 * Physics mode (Phase 5):
 *   When store.physicsPositions is non-null, the actual backbone beads, cones,
 *   and slabs are moved to the XPBD-relaxed positions in-place via
 *   helixCtrl.applyPhysicsPositions().  Toggling off calls revertToGeometry()
 *   which snaps everything back to designed (B-DNA ideal) positions exactly
 *   (V5.3 toggle requirement).
 *
 * Usage:
 *   const dr = initDesignRenderer(scene, store)
 *   dr.setMode('V1.2')
 *   dr.getBackboneEntries()  // → [{ mesh, nuc }, ...]
 */

import * as THREE from 'three'
import { buildHelixObjects, buildStapleColorMap } from './helix_renderer.js'
import { buildCrossoverConnections, bezierAt, arcControlPoint, updateExtraBaseInstances } from './crossover_connections.js'
import { createGlowLayer, createMultiColorGlowLayer } from './glow_layer.js'

/**
 * Initialise the design renderer.
 *
 * @param {THREE.Scene} scene
 * @param {import('../state/store.js').store} storeRef
 * @returns {{ setMode, getBackboneEntries, setStrandColor, getHelixCtrl,
 *             applyPhysicsPositions, dispose }}
 */
export function initDesignRenderer(scene, storeRef) {
  let _helixCtrl        = null
  let _crossoverGroup   = null   // THREE.Group from buildCrossoverConnections (extra-base beads+slabs only)
  let _xoverArcData     = null   // arc metadata for extra-base crossovers
  let _xoverBeadsMesh   = null   // InstancedMesh for extra-base beads
  let _xoverSlabsMesh   = null   // InstancedMesh for extra-base slabs
  let _xoverArcDataMap  = null   // Map<xoId, arcDataEntry> for O(1) lookup during animation
  let _currentMode      = 'normal'
  const _glowLayer         = createGlowLayer(scene)
  // Undefined-bases highlight: red, ~2× the selection glow size
  const _undefinedGlowLayer = createGlowLayer(scene, 0xff3030, 5.6)
  // Fluorescence-mode: per-fluorophore emission color glow
  const _fluoroGlowLayer = createMultiColorGlowLayer(scene)

  // ── Preview ghost state ───────────────────────────────────────────────────
  // When a bend/twist preview is active:
  //   _ghostRoot  — the original (pre-bend) geometry group kept in the scene
  //   _previewOpacity — opacity applied to each newly rebuilt preview geometry
  // Both are null when not in preview mode.

  let _ghostRoot       = null   // saved pre-preview root (not disposed)
  let _previewOpacity  = null   // opacity for the bent preview geometry
  // Flag: on the NEXT _rebuild, save the old root as ghost instead of disposing
  let _captureNextAsGhost    = null   // ghost opacity value, or null
  let _captureNextPreviewOp  = null   // preview opacity value

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
      for (const m of mats) { m.transparent = opacity < 1.0; m.opacity = opacity }
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

  // ── Geometric scene rebuild ───────────────────────────────────────────────

  function _rebuild(geometry, design, helixAxes) {
    // Dispose or save previous scene objects.
    if (_helixCtrl?.root) {
      const oldRoot = _helixCtrl.root
      scene.remove(oldRoot)

      if (_captureNextAsGhost !== null) {
        // Save old geometry as ghost — do NOT dispose
        if (_ghostRoot) { _disposeRoot(_ghostRoot); scene.remove(_ghostRoot) }
        _ghostRoot = oldRoot
        _traverseSetOpacity(_ghostRoot, _captureNextAsGhost)
        scene.add(_ghostRoot)
        _previewOpacity = _captureNextPreviewOp
        _captureNextAsGhost   = null
        _captureNextPreviewOp = null
      } else if (oldRoot !== _ghostRoot) {
        // Normal disposal (ghost is managed separately)
        _disposeRoot(oldRoot)
      }
    }

    _glowLayer.clear()          // stale entries after rebuild; selection_manager re-applies if needed
    _undefinedGlowLayer.clear() // caller must re-apply undefined highlight after rebuild
    _fluoroGlowLayer.clear()    // caller must re-apply fluorescence glow after rebuild

    // Dispose crossover connections from previous build.
    if (_crossoverGroup) {
      scene.remove(_crossoverGroup)
      _crossoverGroup.traverse(obj => {
        if (obj.geometry) obj.geometry.dispose()
        if (obj.material) {
          if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose())
          else obj.material.dispose()
        }
      })
      _crossoverGroup  = null
      _xoverArcData    = null
      _xoverBeadsMesh  = null
      _xoverSlabsMesh  = null
      _xoverArcDataMap = null
    }

    if (!geometry || !design || geometry.length === 0) {
      _helixCtrl = null
      return
    }

    const { strandColors, strandGroups, loopStrandIds, staplesHidden, isolatedStrandId } = storeRef.getState()
    _helixCtrl = buildHelixObjects(geometry, design, scene, _effectiveColors(strandColors, strandGroups), loopStrandIds ?? [], helixAxes)
    _helixCtrl.setMode(_currentMode)

    // Draw explicit crossover connections from design.crossovers.
    // Each connection is a line between the backbone beads of the two linked nucleotides.
    // Extra-base beads + slabs for crossovers with extra bases.
    // Line rendering (straight + arc) is handled exclusively by unfold_view.js.
    // Hidden when unfold or cadnano view is active.
    const colorMap = buildStapleColorMap(geometry, design)
    const xoverResult = buildCrossoverConnections(design, geometry, colorMap)
    if (xoverResult) {
      _crossoverGroup  = xoverResult.group
      _xoverArcData    = xoverResult.arcData
      _xoverBeadsMesh  = xoverResult.beadsMesh
      _xoverSlabsMesh  = xoverResult.slabsMesh
      _xoverArcDataMap = new Map()
      for (const ad of _xoverArcData) _xoverArcDataMap.set(ad.xoId, ad)
      scene.add(_crossoverGroup)
    }

    // Re-apply post-rebuild visibility state
    if (staplesHidden) _helixCtrl.setStapleVisibility(false)
    if (isolatedStrandId) _helixCtrl.setIsolatedStrand(isolatedStrandId)

    // Apply opacity for preview or tool-dim modes
    if (_previewOpacity !== null) {
      _traverseSetOpacity(_helixCtrl.root, _previewOpacity)
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
    if (!_helixCtrl || _ghostRoot !== null) return false
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
    return true
  }

  // Subscribe to store changes and rebuild when geometry or design changes.
  storeRef.subscribe((newState, prevState) => {
    const geoChanged    = newState.currentGeometry  !== prevState.currentGeometry ||
                          newState.currentHelixAxes !== prevState.currentHelixAxes
    const designChanged = newState.currentDesign    !== prevState.currentDesign
    const loopChanged   = newState.loopStrandIds    !== prevState.loopStrandIds

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
    }

    // React to physicsPositions changes: move actual beads/cones/slabs.
    if (newState.physicsPositions !== prevState.physicsPositions) {
      if (!newState.physicsPositions) {
        _helixCtrl?.revertToGeometry()
      } else {
        _helixCtrl?.applyPhysicsPositions(newState.physicsPositions)
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

    /** Show red oversized glow over backbone entries with undefined sequence. */
    setUndefinedHighlight(entries) { _undefinedGlowLayer.setEntries(entries) },
    clearUndefinedHighlight()      { _undefinedGlowLayer.clear() },

    /**
     * Show emission-color glows for fluorophore beads.
     * @param {Array<{pos: THREE.Vector3, emissionColor: number}>} entries
     */
    setFluorescenceGlow(entries)  { _fluoroGlowLayer.setEntries(entries) },
    clearFluorescenceGlow()       { _fluoroGlowLayer.clear() },

    /**
     * Re-read current entry.pos values for all active glow layers.
     * Call each frame during unfold animation after bead positions are mutated.
     */
    refreshAllGlow() {
      _glowLayer.refresh()
      _undefinedGlowLayer.refresh()
      _fluoroGlowLayer.refresh()
    },

    setStrandColor(strandId, hexColor) {
      const { strandColors } = storeRef.getState()
      storeRef.setState({ strandColors: { ...strandColors, [strandId]: hexColor } })
      _helixCtrl?.setStrandColor(strandId, hexColor)
    },

    /**
     * Drive physics from WebSocket position updates.
     * Moves the actual scene objects; null reverts everything to geometry.
     *
     * @param {Array<{helix_id, bp_index, direction, backbone_position}>|null} updates
     */
    applyPhysicsPositions(updates) {
      if (!updates) {
        _helixCtrl?.revertToGeometry()
        storeRef.setState({ physicsPositions: null })
      } else {
        storeRef.setState({ physicsPositions: updates })
      }
    },

    getHelixCtrl() {
      return _helixCtrl
    },

    /**
     * Apply FEM equilibrium-shape positions as a scene overlay.
     * @param {Array<{helix_id, bp_index, direction, backbone_position}>} updates
     */
    applyFemPositions(updates) {
      _helixCtrl?.applyFemPositions(updates)
    },

    /**
     * Colour beads and slabs by RMSF value (stiff=blue, flexible=red).
     * @param {Object} rmsfMap  "{helix_id}:{bp}:{dir}" → float 0-1
     */
    applyFemRmsf(rmsfMap) {
      _helixCtrl?.applyFemRmsf(rmsfMap)
    },

    setDetailLevel(level) {
      _helixCtrl?.setDetailLevel(level)
    },

    setBeadRadius(r)     { _helixCtrl?.setBeadRadius(r) },
    setCylinderRadius(r) { _helixCtrl?.setCylinderRadius(r) },

    getCylinderMesh()                { return _helixCtrl?.getCylinderMesh() ?? null },
    getCylinderDomainData()          { return _helixCtrl?.getCylinderDomainData() ?? [] },
    getCylinderDomainAt(id)          { return _helixCtrl?.getCylinderDomainAt(id) ?? null },
    highlightCylinderStrands(sids)   { _helixCtrl?.highlightCylinderStrands(sids) },
    clearCylinderHighlight()         { _helixCtrl?.clearCylinderHighlight() },

    /**
     * Remove FEM overlay: revert geometry positions and restore strand colours.
     * Skip revertToGeometry when cadnano or unfold modes own bead positions —
     * those modes will restore positions themselves on deactivation.
     */
    clearFemOverlay() {
      const { cadnanoActive, unfoldActive } = storeRef.getState()
      if (!cadnanoActive && !unfoldActive) {
        _helixCtrl?.revertToGeometry()
      }
      _helixCtrl?.clearFemColors()
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
     * Lerp all geometry between straight and deformed positions.
     * @param {Map<string, THREE.Vector3>} straightPosMap  key "hid:bp:dir" → straight pos
     * @param {Map<string, {start,end}>} straightAxesMap   key helix_id → straight axis anchors
     * @param {Map<string, THREE.Vector3>} straightBnMap   key "hid:bp:dir" → straight base_normal
     * @param {number} t  lerp factor 0=straight, 1=deformed
     */
    applyDeformLerp(straightPosMap, straightAxesMap, straightBnMap, t) {
      _helixCtrl?.applyDeformLerp(straightPosMap, straightAxesMap, straightBnMap, t)
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
     * Generate glow entries (sampled positions) along a crossover path.
     * Returns an array of { pos: THREE.Vector3 } compatible with the glow layer.
     */
    getCrossoverGlowEntries(xo) {
      const geo = storeRef.getState().currentGeometry
      if (!geo?.length) return []

      const nucMap = new Map()
      for (const nuc of geo) {
        nucMap.set(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`, nuc)
      }

      const nucA = nucMap.get(`${xo.half_a.helix_id}:${xo.half_a.index}:${xo.half_a.strand}`)
      const nucB = nucMap.get(`${xo.half_b.helix_id}:${xo.half_b.index}:${xo.half_b.strand}`)
      if (!nucA || !nucB) return []

      const posA = new THREE.Vector3(...nucA.backbone_position)
      const posB = new THREE.Vector3(...nucB.backbone_position)
      const entries = []

      if (xo.extra_bases?.length > 0) {
        // Arc crossover — sample 10 points along the Bezier
        const ctrl = new THREE.Vector3()
        arcControlPoint(posA, posB, nucA, nucB, ctrl)
        const N = 10
        const pt = new THREE.Vector3()
        for (let i = 0; i <= N; i++) {
          bezierAt(posA, ctrl, posB, i / N, pt)
          entries.push({ pos: pt.clone() })
        }
      } else {
        // Straight crossover — sample 6 points along the line
        const N = 5
        for (let i = 0; i <= N; i++) {
          const t = i / N
          entries.push({
            pos: new THREE.Vector3(
              posA.x + (posB.x - posA.x) * t,
              posA.y + (posB.y - posA.y) * t,
              posA.z + (posB.z - posA.z) * t,
            ),
          })
        }
      }
      return entries
    },

    /**
     * Update extra-base crossover meshes after a cluster drag frame.
     * Line rendering is handled by unfold_view.js (applyClusterArcUpdate).
     * Extra-base beads/slabs are rebuilt on full scene rebuild after drag
     * completes, so this is a no-op for now.
     *
     * @param {string[]} _helixIds  IDs of helices that just moved.
     */
    applyClusterCrossoverUpdate(_helixIds) {
      // Extra-base beads/slabs now track via updateExtraBaseArc() in the
      // animation loop — no special handling needed for cluster drag.
    },

    /**
     * Reposition extra-base beads+slabs for a single crossover arc.
     * Called per-arc per-frame by unfold_view animation loops.
     */
    updateExtraBaseArc(crossoverId, posA, ctrl, posB) {
      if (!_xoverArcDataMap || !_xoverBeadsMesh || !_xoverSlabsMesh) return
      const ad = _xoverArcDataMap.get(crossoverId)
      if (!ad) return
      updateExtraBaseInstances(
        _xoverBeadsMesh, _xoverSlabsMesh,
        ad.beadStartIdx, ad.beadCount,
        posA, ctrl, posB, ad.avgAx, ad.zOffset,
      )
    },

    /**
     * Flush extra-base InstancedMesh matrices to GPU.
     * Call once after batching all updateExtraBaseArc() calls for a frame.
     */
    flushExtraBaseMeshes() {
      if (_xoverBeadsMesh) _xoverBeadsMesh.instanceMatrix.needsUpdate = true
      if (_xoverSlabsMesh) _xoverSlabsMesh.instanceMatrix.needsUpdate = true
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
     * to dim the scene when the bend/twist tool is active.
     * Skipped when preview ghost mode is active (opacity managed by _previewOpacity).
     */
    setToolOpacity(opacity) {
      if (_previewOpacity !== null) return   // preview mode manages its own opacity
      if (!_helixCtrl?.root) return
      _traverseSetOpacity(_helixCtrl.root, opacity)
    },

    /**
     * Save the current geometry as a ghost overlay at `ghostOpacity`, and mark
     * that the next rebuilt geometry (the bent preview) should appear at
     * `previewOpacity`.  Call before triggering the API deformation.
     */
    captureGhost(ghostOpacity, previewOpacity) {
      if (!_helixCtrl?.root) return
      _captureNextAsGhost   = ghostOpacity
      _captureNextPreviewOp = previewOpacity
    },

    /**
     * Remove the ghost overlay and exit preview opacity mode.
     * The next rebuild will use the normal tool dim (0.15) if the tool is active.
     */
    clearGhost() {
      if (_ghostRoot) { _disposeRoot(_ghostRoot); scene.remove(_ghostRoot); _ghostRoot = null }
      _previewOpacity       = null
      _captureNextAsGhost   = null
      _captureNextPreviewOp = null
    },

    dispose() {
      if (_ghostRoot) { scene.remove(_ghostRoot); _ghostRoot = null }
      if (_helixCtrl?.root) scene.remove(_helixCtrl.root)
      _helixCtrl = null
    },
  }
}
