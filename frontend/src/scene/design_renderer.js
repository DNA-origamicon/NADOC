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
import { buildCrossoverConnections, bezierAt, arcControlPoint, updateExtraBaseInstances } from './crossover_connections.js'
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
  let _designVisible    = true   // controlled by setDesignVisible(); re-applied after every _rebuild
  // VISIBILITY RULE: design_renderer has ONE scene object — _helixCtrl.root.
  // Extra-base beads+slabs (from buildCrossoverConnections) are children of root,
  // so _helixCtrl.root.visible covers them automatically.
  // Arc LINE geometry lives in unfold_view._arcGroup (separate module — see main.js SCENE GEOMETRY RULE).
  let _xoverArcData     = null   // arc metadata for extra-base crossovers
  let _xoverBeadsMesh   = null   // InstancedMesh for extra-base beads
  let _xoverSlabsMesh   = null   // InstancedMesh for extra-base slabs
  let _xoverArcDataMap  = null   // Map<xoId, arcDataEntry> for O(1) lookup during animation
  let _xoverGlowLive    = []     // {pos: THREE.Vector3, arcData, localIdx} — live positions for selection glow
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
  let _hiddenNucKeys      = new Set()  // persists across rebuilds; set by cluster visibility toggle
  let _hiddenCrossoverIds = new Set()  // extra-base bead/slab instances to suppress
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

  // ── Helpers ───────────────────────────────────────────────────────────────

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
        // Normal disposal (ghost is managed separately).
        // Extra-base beads+slabs are children of root — disposed here automatically.
        _disposeRoot(oldRoot)
      }
    }

    _glowLayer.clear()          // stale entries after rebuild; selection_manager re-applies if needed
    _undefinedGlowLayer.clear() // caller must re-apply undefined highlight after rebuild
    _fluoroGlowLayer.clear()    // caller must re-apply fluorescence glow after rebuild

    // Clear stale xover refs — the old meshes were children of oldRoot, already disposed above.
    _xoverArcData    = null
    _xoverBeadsMesh  = null
    _xoverSlabsMesh  = null
    _xoverArcDataMap = null
    _xoverGlowLive   = []

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
      _xoverArcDataMap = new Map()
      for (const ad of _xoverArcData) _xoverArcDataMap.set(ad.xoId, ad)
      // Extra-base beads+slabs are children of root — no separate scene.add() needed.
      // root.visible covers them automatically; no extra VISIBILITY RULE required.
      _helixCtrl.root.add(xoverResult.group)
    }

    // Re-apply post-rebuild visibility state
    if (staplesHidden) _helixCtrl.setStapleVisibility(false)
    if (isolatedStrandId) _helixCtrl.setIsolatedStrand(isolatedStrandId)
    if (_hiddenNucKeys.size) _helixCtrl.setHiddenNucs(_hiddenNucKeys)
    _applyXoverVisibility()

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
    if (newState.coloringMode && newState.coloringMode !== 'strand') {
      _helixCtrl.applyColoring(newState.coloringMode, newState.currentDesign, customColors, loopSet)
    }
    return true
  }

  // Subscribe to store changes and rebuild when geometry or design changes.
  storeRef.subscribe((newState, prevState) => {
    const geoChanged    = newState.currentGeometry  !== prevState.currentGeometry ||
                          newState.currentHelixAxes !== prevState.currentHelixAxes
    const designChanged = newState.currentDesign    !== prevState.currentDesign
    const loopChanged   = newState.loopStrandIds    !== prevState.loopStrandIds

    // Coloring-mode toggle: pure color update, no rebuild needed.
    if (newState.coloringMode !== prevState.coloringMode && _helixCtrl) {
      const eff = _effectiveColors(newState.strandColors ?? {}, newState.strandGroups)
      _helixCtrl.applyColoring(
        newState.coloringMode || 'strand',
        newState.currentDesign,
        eff,
        new Set(newState.loopStrandIds ?? []),
      )
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
     * Apply FEM equilibrium-shape positions as a scene overlay.
     * @param {Array<{helix_id, bp_index, direction, backbone_position}>} updates
     */
    applyFemPositions(updates, amp = 1.0) {
      _helixCtrl?.applyFemPositions(updates, amp)
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

      // Support both Crossover (half_a/half_b) and ForcedLigation (three_prime_*/five_prime_*)
      const isFl = !!xo.three_prime_helix_id
      const keyA = isFl
        ? `${xo.three_prime_helix_id}:${xo.three_prime_bp}:${xo.three_prime_direction}`
        : `${xo.half_a.helix_id}:${xo.half_a.index}:${xo.half_a.strand}`
      const keyB = isFl
        ? `${xo.five_prime_helix_id}:${xo.five_prime_bp}:${xo.five_prime_direction}`
        : `${xo.half_b.helix_id}:${xo.half_b.index}:${xo.half_b.strand}`
      const nucA = nucMap.get(keyA)
      const nucB = nucMap.get(keyB)
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
