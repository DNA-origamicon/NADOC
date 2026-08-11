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
import { buildCrossoverConnections, updateExtraBaseInstances, setExtraBaseInstanceFromSim, simBeadIndex, partitionExtraBaseUpdates, setExtraBaseConnectors, setExtraBaseSlabConnectors, hideExtraBaseConnectors, extraBaseConnectorScalarColors } from './crossover_connections.js'
import { buildCrossoverExtraPlacements, crossoverControlPoint as arcControlPoint } from './crossover_extra_placement.js'
import { auditRenderedBonds, inventoryRenderedElements } from './render_bond_audit.js'
import { createGlowLayer, createMultiColorGlowLayer } from './glow_layer.js'
import { clusterAlphaForNuc, clusterAlphaKeys, clusterDisplaySignature } from './cluster_entries.js'
import { buildClusterColorLookup } from './helix_renderer/palette.js'
import { installInstanceAlpha, setInstanceAlpha } from './instance_alpha.js'
import { markOperationTiming, finishOperationAfterRender } from '../perf/operation_timing.js'

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
  // Last simulation/FEM displacement applied to the shared design model.  Keeping
  // the source payload here lets non-rendering consumers (notably PDB export) use
  // exactly the positions currently on screen without coupling to every engine.
  let _activeFemUpdates = null
  let _designVisible    = true   // controlled by setDesignVisible(); re-applied after every _rebuild
  // VISIBILITY RULE: design_renderer has ONE scene object — _helixCtrl.root.
  // Extra-base beads+slabs (from buildCrossoverConnections) are children of root,
  // so _helixCtrl.root.visible covers them automatically.
  // Arc LINE geometry lives in unfold_view._arcGroup (separate module — see main.js SCENE GEOMETRY RULE).
  let _xoverArcData     = null   // arc metadata for extra-base crossovers
  let _xoverBeadsMesh   = null   // InstancedMesh for extra-base beads
  let _xoverSlabsMesh   = null   // InstancedMesh for extra-base slabs
  let _xoverConnMesh    = null   // InstancedMesh for extra-base backbone connector cones
  let _xoverSlabConnMesh = null  // InstancedMesh for extra-base bead→slab rods
  let _xoverArcDataMap  = null   // Map<xoId, arcDataEntry> for O(1) lookup during animation
  let _xoverGlowLive    = []     // {pos: THREE.Vector3, arcData, localIdx} — live positions for selection glow
  // Extra-base inserts driven by a simulation frame (oxDNA/MD relaxed or trajectory):
  // Map<crossover_id, Map<k, {pos:THREE.Vector3, normal:[nx,ny,nz]}>>.  When an arc
  // is present here, its beads are placed at the REAL simulated positions and the
  // geometric Bezier interpolation is skipped for it.  Null/empty → all arcs Bezier.
  let _simXbByCrossover = null
  let _detailLevel      = 0      // current LOD (0=full,1=beads,2=cylinders); re-applied to xover extras after _rebuild
  // Base-pair slab display tuning from the sidebar (Full representation). Held
  // here — not in the helix controller — so it survives a rebuild; it is
  // re-applied in the post-rebuild block. 0.06 nm is the build-time default
  // (slab thickness = the plate's smallest dimension). Slab OPACITY is gone —
  // the slider was removed and the slabs are built opaque (2026-08-02).
  let _slabThickness    = 0.06
  let _currentMode      = 'normal'
  // External (job-snapshot) render: while a CanDo display mode is active, the scene is
  // rebuilt from a job's OWN design snapshot (its topology at solve time) instead of the
  // live store design, so FEM overlays land on matching beads.  While true, the store
  // subscription ignores live-design changes; clearExternalGeometry() restores the live
  // model.  Purely a display swap — the active design in the store is never mutated.
  let _externalActive   = false
  // Selection halo: 2.1 is 25% smaller than the original 2.8× bead radius.
  const _glowLayer         = createGlowLayer(scene, 0x3fb950, 2.1)
  // Undefined-bases highlight: red, ~2× the selection glow size
  const _undefinedGlowLayer = createGlowLayer(scene, 0xff3030, 5.6)
  // oxDNA anchor highlight: purple, distinct from the green selection glow — marks the
  // strands/clusters pinned as FIXED during an E-field (or other) run.
  const _anchorGlowLayer    = createGlowLayer(scene, 0xb14aff, 3.6, 'anchorGlow')
  // Steric-clash highlight: bright red, marks backbone beads that collide once the
  // design is posed (clash_overlay drives it). Named so gesture e2e can detect it.
  const _clashGlowLayer     = createGlowLayer(scene, 0xff2b2b, 5.6, 'clashGlow')
  // Surface capture-strand emphasis: a bright additive halo (brightens any strand colour)
  // when the "Highlight strands" toggle is on. The strands ALWAYS render; this only emphasises.
  const _captureGlowLayer   = createGlowLayer(scene, 0xffffff, 4.4, 'captureGlow')
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
  // Per-cluster opacity — same nucKey format as _hiddenNucKeys, and the same
  // "persists across rebuilds" contract (a rebuild makes fresh meshes, so it is
  // re-pushed below). Empty for every design where nobody has faded a cluster.
  let _clusterAlphaKeys   = new Map()
  let _clusterDisplaySig  = ''         // guards the repaint against gizmo-drag thrash

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

  /**
   * Push a design's per-cluster display fields at the renderer: the opacity fade
   * and, when the viewer is actually in cluster-coloring mode, a recolour so a new
   * swatch shows up immediately. Repaints in place — never rebuilds.
   *
   * BOTH halves are O(nucleotides) sweeps, and the popover calls this live on every
   * pointer move while a slider or the colour map is dragged. So each half is opt-out:
   * dragging the colour map must not re-walk every cluster's membership to rebuild an
   * alpha map that did not change, and dragging the opacity slider must not repaint
   * every instance colour. The store-driven path (a PATCH landing) passes neither
   * flag and does both.
   *
   * @param {object} design
   * @param {{color?: boolean, opacity?: boolean}} [what]
   */
  function _refreshClusterDisplay(design, what = null) {
    if (!_helixCtrl) return
    const doColor   = what?.color   !== false
    const doOpacity = what?.opacity !== false
    if (doOpacity) {
      _clusterAlphaKeys = clusterAlphaKeys(design)
      _helixCtrl.setClusterAlphas(_clusterAlphaKeys)
      _applyXoverClusterAlpha()   // separate meshes; setClusterAlphas can't reach them
    }
    if (!doColor) return
    const st = storeRef.getState()
    if (st.coloringMode === 'cluster') {
      _helixCtrl.applyColoring(
        'cluster', design,
        _effectiveColors(st.strandColors, st.strandGroups),
        new Set(st.loopStrandIds ?? []))
      // Extra-base crossover beads live in their own mesh and are not touched by
      // applyColoring — they need the cluster colour pushed separately.
      _applyXoverColoring('cluster', design)
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  /**
   * Re-skin extra-base crossover beads + slabs to honor the current global
   * coloringMode.  'overhang-only' and 'cluster' override — for every other
   * mode (including 'strand') we restore the build-time bead/slab colors
   * captured by buildCrossoverConnections.  Crossovers that bridge an overhang
   * (either endpoint nuc has overhang_id != null) keep their strand color.
   *
   * The inserted bases live in their own instanced meshes, so applyColoring (which
   * walks the helix renderer's entries) never reaches them — without the 'cluster'
   * branch here they stayed at their build-time strand colour while the helices they
   * bridge took the cluster colour.  An extra base belongs to whichever cluster owns
   * the crossover's A-side nucleotide, falling back to the B side.
   *
   * @param {string} mode
   * @param {object} [design]  required for 'cluster'; defaults to the store's design
   */
  function _applyXoverColoring(mode, design = null) {
    if (!_xoverArcData || !_xoverBeadsMesh || !_xoverSlabsMesh) return
    const _col = new THREE.Color()
    const ovhgOnly = (mode === 'overhang-only')
    const DIM_GRAY = 0xbbbbbb
    const clusterColorFn = (mode === 'cluster')
      ? buildClusterColorLookup(design ?? storeRef.getState().currentDesign)
      : null
    for (const ad of _xoverArcData) {
      const isOvhg = (ad.nucA?.overhang_id != null) || (ad.nucB?.overhang_id != null)
      const cc = clusterColorFn
        ? (clusterColorFn(ad.nucA) ?? clusterColorFn(ad.nucB))
        : undefined
      const bc = cc ?? ((ovhgOnly && !isOvhg) ? DIM_GRAY : ad.beadBaseColor)
      const sc = cc ?? ((ovhgOnly && !isOvhg) ? DIM_GRAY : ad.slabBaseColor)
      for (let i = 0; i < ad.beadCount; i++) {
        const idx = ad.beadStartIdx + i
        _xoverBeadsMesh.setColorAt(idx, _col.setHex(bc))
        _xoverSlabsMesh.setColorAt(idx, _col.setHex(sc))
        _xoverSlabConnMesh?.setColorAt(idx, _col.setHex(sc))
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
    if (_xoverSlabConnMesh?.instanceColor) _xoverSlabConnMesh.instanceColor.needsUpdate = true
  }

  /**
   * Recolour the extra-base crossover beads/slabs by a scalar map (the RMSF / deviation
   * flexibility overlay).  The helix renderer's applyScalarColors only touches real-helix
   * nucleotides; the inserted crossover bases live in a separate instanced mesh and were
   * left at their strand colour, so a flexibility map ignored them.  The map keys inserts
   * as `"__xb__:<crossoverId>:<insertIndex>"` (the same key rmsfColorMap builds from an MD
   * frame's `{helix_id:"__xb__", bp_index:<crossoverId>, direction:<k>}` entries).
   */
  function _applyExtraBaseScalarColors(colorByKey) {
    if (!colorByKey || !_xoverArcData || !_xoverBeadsMesh || !_xoverSlabsMesh) return
    const get = colorByKey instanceof Map ? (k) => colorByKey.get(k) : (k) => colorByKey[k]
    const _col = new THREE.Color()
    let dirty = false
    for (const ad of _xoverArcData) {
      for (let k = 0; k < ad.beadCount; k++) {
        const hex = get(`__xb__:${ad.xoId}:${k}`)
        if (hex == null) continue
        // Same 5′→3′-vs-A→B mismatch as the position path: key by simulated k,
        // paint the bead that k actually occupies.
        const idx = ad.beadStartIdx + simBeadIndex(k, ad.beadCount, ad.simReversed)
        _xoverBeadsMesh.setColorAt(idx, _col.setHex(hex))
        _xoverSlabsMesh.setColorAt(idx, _col.setHex(hex))
        _xoverSlabConnMesh?.setColorAt(idx, _col.setHex(hex))
        dirty = true
      }
      // The backbone bond cones live in their OWN InstancedMesh, so they need the
      // same treatment or they stay at the build-time strand colour under a flex map.
      if (_xoverConnMesh) {
        const segHex = extraBaseConnectorScalarColors(ad, get)
        for (let s = 0; s < segHex.length; s++) {
          if (segHex[s] == null) continue
          _xoverConnMesh.setColorAt(ad.connStartIdx + s, _col.setHex(segHex[s]))
          dirty = true
        }
      }
    }
    if (dirty) {
      if (_xoverBeadsMesh.instanceColor) _xoverBeadsMesh.instanceColor.needsUpdate = true
      if (_xoverSlabsMesh.instanceColor) _xoverSlabsMesh.instanceColor.needsUpdate = true
      if (_xoverConnMesh?.instanceColor) _xoverConnMesh.instanceColor.needsUpdate = true
      if (_xoverSlabConnMesh?.instanceColor) _xoverSlabConnMesh.instanceColor.needsUpdate = true
    }
  }

  /** Restore extra-base beads/slabs to their build-time strand colours (leaving a scalar
   *  flexibility map) — the insert counterpart of helix_renderer.clearScalarColors. */
  function _restoreExtraBaseColors() {
    if (!_xoverArcData || !_xoverBeadsMesh || !_xoverSlabsMesh) return
    const _col = new THREE.Color()
    for (const ad of _xoverArcData) {
      for (let k = 0; k < ad.beadCount; k++) {
        const idx = ad.beadStartIdx + k
        _xoverBeadsMesh.setColorAt(idx, _col.setHex(ad.beadBaseColor))
        _xoverSlabsMesh.setColorAt(idx, _col.setHex(ad.slabBaseColor))
        _xoverSlabConnMesh?.setColorAt(idx, _col.setHex(ad.slabBaseColor))
      }
      // Cones too — _applyExtraBaseScalarColors recoloured them, so leaving them out
      // here would strand them in viridis after the flex map is switched off.
      if (_xoverConnMesh) {
        for (let s = 0; s < ad.beadCount + 1; s++) {
          _xoverConnMesh.setColorAt(ad.connStartIdx + s, _col.setHex(ad.beadBaseColor))
        }
      }
    }
    if (_xoverBeadsMesh.instanceColor) _xoverBeadsMesh.instanceColor.needsUpdate = true
    if (_xoverSlabsMesh.instanceColor) _xoverSlabsMesh.instanceColor.needsUpdate = true
    if (_xoverConnMesh?.instanceColor) _xoverConnMesh.instanceColor.needsUpdate = true
    if (_xoverSlabConnMesh?.instanceColor) _xoverSlabConnMesh.instanceColor.needsUpdate = true
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
    if (_xoverSlabConnMesh) _xoverSlabConnMesh.visible = show
  }

  /**
   * Per-cluster opacity for the crossover extra-base beads/slabs/connectors.
   *
   * These are their own InstancedMeshes, so the helix renderer's alpha channel never
   * reaches them — an inserted base stayed fully opaque inside a faded cluster. The
   * alpha channel is installed LAZILY (it flips the material to transparent) and only
   * once something is actually faded. An extra base takes the alpha of whichever
   * cluster owns the crossover's A-side nucleotide, falling back to the B side — the
   * same owner its colour uses, so the two can't disagree.
   *
   * Photo mode carries this across for free: `applyInstanceAlphaMaterial` stamps the
   * userData marker that `swapToFlatMaterials` re-installs the patch from.
   */
  function _applyXoverClusterAlpha() {
    if (!_xoverArcData || !_xoverBeadsMesh || !_xoverSlabsMesh) return
    if (!_clusterAlphaKeys.size && !_xoverBeadsMesh._instanceAlpha) return
    installInstanceAlpha(_xoverBeadsMesh)
    installInstanceAlpha(_xoverSlabsMesh)
    if (_xoverConnMesh) installInstanceAlpha(_xoverConnMesh)
    if (_xoverSlabConnMesh) installInstanceAlpha(_xoverSlabConnMesh)
    for (const ad of _xoverArcData) {
      const a = _clusterAlphaKeys.size
        ? Math.min(clusterAlphaForNuc(_clusterAlphaKeys, ad.nucA),
                   clusterAlphaForNuc(_clusterAlphaKeys, ad.nucB))
        : 1
      for (let i = 0; i < ad.beadCount; i++) {
        setInstanceAlpha(_xoverBeadsMesh, ad.beadStartIdx + i, a)
        setInstanceAlpha(_xoverSlabsMesh, ad.beadStartIdx + i, a)
        if (_xoverSlabConnMesh) setInstanceAlpha(_xoverSlabConnMesh, ad.beadStartIdx + i, a)
      }
      if (_xoverConnMesh) {
        for (let s = 0; s < ad.beadCount + 1; s++) {
          setInstanceAlpha(_xoverConnMesh, ad.connStartIdx + s, a)
        }
      }
    }
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
          posA, _clusterXoverCtrl, posB, ad.avgAx,
          ad.simReversed, ad.localFrameReversed, ad.savedTransforms, ad.sequence,
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
    if (!_xoverArcData || !_xoverBeadsMesh) return
    const design = storeRef.getState().currentDesign
    const refIds = new Set((design?.strands ?? []).filter(s => s.is_reference).map(s => s.id))
    const refHidden = storeRef.getState().showReferenceGeometry === false
    if (_xoverConnMesh) for (const ad of _xoverArcData) {
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
    if (_xoverConnMesh) _xoverConnMesh.instanceMatrix.needsUpdate = true
    if (_xoverSlabConnMesh && _xoverSlabsMesh) {
      for (const ad of _xoverArcData) {
        setExtraBaseSlabConnectors(
          _xoverBeadsMesh, _xoverSlabsMesh, _xoverSlabConnMesh,
          ad.beadStartIdx, ad.beadCount, null,
        )
      }
      _xoverSlabConnMesh.instanceMatrix.needsUpdate = true
    }
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

  // Extra (non-design) nucleotides injected into every CG rep — oxDNA surface capture
  // strands.  They render exactly like origami strands (beads/slab/cylinders/hull) and
  // move with applyFemPositions, following the __ext_/__lnk__ synthetic-nuc precedent.
  let _extraNucs = []          // plain nucleotide dicts (unique high bp_index; cap<i> ids)
  let _extraColor = null       // hex int applied to the capture strands
  let _captureHighlight = false // "Highlight strands" toggle → additive glow (not visibility)
  let _rebuildSerial = 0
  let _lastRebuildStack = null
  let _structuralOverlay = null
  let _structuralConsolidateTimer = null

  function _clearStructuralOverlay({ restoreBase = false } = {}) {
    if (_structuralConsolidateTimer !== null) {
      clearTimeout(_structuralConsolidateTimer)
      _structuralConsolidateTimer = null
    }
    if (!_structuralOverlay) return
    scene.remove(_structuralOverlay.ctrl.root)
    _disposeRoot(_structuralOverlay.ctrl.root)
    if (restoreBase && _helixCtrl) {
      _helixCtrl.setHiddenNucs(_hiddenNucKeys)
      _helixCtrl.setStructuralHelicesSuppressed?.(new Set())
    }
    _structuralOverlay = null
  }

  // Re-apply the capture-strand highlight glow after a rebuild (glow layers are cleared on
  // every rebuild).  Glows the injected cap<i> backbone beads; a no-op when off/absent.
  function _applyCaptureGlow() {
    if (!_captureHighlight || !_extraNucs.length) { _captureGlowLayer.clear(); return }
    const caps = (_helixCtrl?.backboneEntries || [])
      .filter(e => e.nuc && typeof e.nuc.strand_id === 'string' && e.nuc.strand_id.startsWith('cap'))
    _captureGlowLayer.setEntries(caps)
  }

  // ── Geometric scene rebuild ───────────────────────────────────────────────

  function _rebuild(geometry, design, helixAxes) {
    _clearStructuralOverlay()
    markOperationTiming('scene-rebuild-start', { nucleotides: geometry?.length ?? 0 })
    _rebuildSerial++
    _lastRebuildStack = new Error('design renderer rebuild').stack
    // Merge capture strands into the geometry so every CG consumer renders them.
    if (_extraNucs.length && geometry && geometry.length) geometry = geometry.concat(_extraNucs)
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
    markOperationTiming('old-scene-disposed')

    _glowLayer.clear()          // stale entries after rebuild; selection_manager re-applies if needed
    _undefinedGlowLayer.clear() // caller must re-apply undefined highlight after rebuild
    _anchorGlowLayer.clear()    // caller (anchor_glow) re-applies after a rebuild
    _clashGlowLayer.clear()     // caller (clash_overlay) re-applies after a rebuild
    _captureGlowLayer.clear()   // re-applied below via _applyCaptureGlow after the build
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
    _xoverSlabConnMesh = null
    _xoverArcDataMap = null
    _xoverGlowLive   = []
    _simXbByCrossover = null   // drop stale simulation-driven insert positions

    if (!geometry || !design || geometry.length === 0) {
      _helixCtrl = null
      return
    }

    const { strandColors, strandGroups, loopStrandIds, staplesHidden, isolatedStrandId, coloringMode } = storeRef.getState()
    const _eff = _effectiveColors(strandColors, strandGroups)
    // Colour the capture strands (cyan by default) so they read as a distinct set.
    if (_extraNucs.length && _extraColor) for (const n of _extraNucs) _eff[n.strand_id] = _extraColor
    _helixCtrl = buildHelixObjects(geometry, design, scene, _eff, loopStrandIds ?? [], helixAxes)
    markOperationTiming('helix-meshes-built')
    _helixCtrl.setMode(_currentMode)
    if (coloringMode && coloringMode !== 'strand') {
      _helixCtrl.applyColoring(coloringMode, design, _eff, new Set(loopStrandIds ?? []))
    }
    _applyCaptureGlow()   // re-emphasise the capture strands if "Highlight" is on

    // Draw explicit crossover connections from design.crossovers.
    // Each connection is a line between the backbone beads of the two linked nucleotides.
    // Extra-base beads + slabs for crossovers with extra bases.
    // Line rendering (straight + arc) is handled exclusively by unfold_view.js.
    // Hidden when unfold or cadnano view is active.
    const colorMap    = buildStapleColorMap(geometry, design)
    const effectiveCols = _effectiveColors(strandColors, strandGroups)
    const xoverResult = buildCrossoverConnections(design, geometry, colorMap, effectiveCols)
    markOperationTiming('crossovers-built')
    if (xoverResult) {
      _xoverArcData    = xoverResult.arcData
      _xoverBeadsMesh  = xoverResult.beadsMesh
      _xoverSlabsMesh  = xoverResult.slabsMesh
      _xoverConnMesh   = xoverResult.connMesh
      _xoverSlabConnMesh = xoverResult.slabConnMesh
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
    if (_slabThickness !== 0.06) _helixCtrl.setSlabThickness(_slabThickness)
    if (staplesHidden) _helixCtrl.setStapleVisibility(false)
    if (isolatedStrandId) _helixCtrl.setIsolatedStrand(isolatedStrandId)
    if (_hiddenNucKeys.size) _helixCtrl.setHiddenNucs(_hiddenNucKeys)
    if (_clusterAlphaKeys.size) {
      _helixCtrl.setClusterAlphas(_clusterAlphaKeys)
      _applyXoverClusterAlpha()
    }
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
    if (!_helixCtrl || _ghostOpacity !== null) {
      markOperationTiming('partial-patch-rejected', { reason: !_helixCtrl ? 'no-controller' : 'ghost-active' })
      return false
    }
    const realIds = changedHelixIds.filter(id => !id.startsWith('__'))
    if (realIds.length === 0) {
      markOperationTiming('partial-patch-rejected', { reason: 'synthetic-only' })
      return false
    }

    // 1. Check nucleotide counts match for every real changed helix.
    for (const hid of realIds) {
      if (_countHelixNucs(newGeo, hid) !== _countHelixNucs(prevGeo ?? [], hid)) {
        markOperationTiming('partial-patch-rejected', { reason: 'nucleotide-count-changed', helixId: hid })
        return false
      }
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
      if (existing && existing.nuc.is_five_prime !== !!nuc.is_five_prime) {
        markOperationTiming('partial-patch-rejected', { reason: 'five-prime-mesh-changed', helixId: nuc.helix_id })
        return false
      }
      if (existing && existing.nuc.is_three_prime !== !!nuc.is_three_prime) {
        markOperationTiming('partial-patch-rejected', { reason: 'three-prime-mesh-changed', helixId: nuc.helix_id })
        return false
      }
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

  function _sameCrossoverTopology(a, b) {
    const signature = (design) => JSON.stringify((design?.crossovers ?? []).map(x => [
      x.id, x.half_a?.helix_id, x.half_a?.index, x.half_a?.strand,
      x.half_b?.helix_id, x.half_b?.index, x.half_b?.strand, x.extra_bases,
    ]))
    return signature(a) === signature(b)
  }

  /** Render a small topology-changing partial response without rebuilding the
   * fixed-capacity whole-design InstancedMeshes. The old affected helices are
   * suppressed and a compact authoritative controller is layered over them.
   * A delayed idle consolidation restores the single-controller steady state.
   */
  function _tryStructuralOverlay(changedHelixIds, newGeo, prevState, newState) {
    if (!_helixCtrl || _structuralOverlay || _ghostOpacity !== null) return false
    const realIds = changedHelixIds.filter(id => !id.startsWith('__'))
    if (!realIds.length || realIds.length > 12) return false
    if (!_sameCrossoverTopology(prevState.currentDesign, newState.currentDesign)) return false
    if ((newState.currentDesign?.deformations ?? []).length) return false
    // The overlay suppresses resident bead/slab/axis instances. Cylinder and
    // mixed-representation buffers have independent visibility channels, so
    // retain the full rebuild whenever either is currently in use.
    if (_detailLevel !== 0) return false
    if ((newState.currentDesign?.representation_overrides ?? []).length) return false

    const changedSet = new Set(changedHelixIds)
    const realSet = new Set(realIds)
    const patchGeometry = newGeo.filter(n => changedSet.has(n.helix_id))
    if (!patchGeometry.length) return false
    const fullDesign = newState.currentDesign
    const patchDesign = {
      ...fullDesign,
      helices: (fullDesign.helices ?? []).filter(h => realSet.has(h.id)),
      strands: (fullDesign.strands ?? []).map(s => ({
        ...s, domains: (s.domains ?? []).filter(d => realSet.has(d.helix_id)),
      })).filter(s => s.domains.length),
      cluster_transforms: (fullDesign.cluster_transforms ?? []).map(c => ({
        ...c, helix_ids: (c.helix_ids ?? []).filter(id => realSet.has(id)),
      })).filter(c => c.helix_ids.length),
    }
    const patchAxes = {}
    for (const id of realIds) {
      const axis = newState.currentHelixAxes?.[id]
      if (axis) patchAxes[id] = axis
    }
    const customColors = _effectiveColors(newState.strandColors, newState.strandGroups)

    // Hide resident instances before adding the authoritative replacement.
    _helixCtrl.setHiddenNucs(new Set([
      ..._hiddenNucKeys, ...changedHelixIds.map(id => `h:${id}`),
    ]))
    _helixCtrl.setStructuralHelicesSuppressed?.(realSet)
    const ctrl = buildHelixObjects(
      patchGeometry, patchDesign, scene, customColors,
      newState.loopStrandIds ?? [], patchAxes,
    )
    ctrl.setMode(_currentMode)
    ctrl.setDetailLevel(_detailLevel)
    if (_slabThickness !== 0.06) ctrl.setSlabThickness(_slabThickness)
    if (newState.staplesHidden) ctrl.setStapleVisibility(false)
    if (newState.isolatedStrandId) ctrl.setIsolatedStrand(newState.isolatedStrandId)
    if (_hiddenNucKeys.size) ctrl.setHiddenNucs(_hiddenNucKeys)
    if (_clusterAlphaKeys.size) ctrl.setClusterAlphas(_clusterAlphaKeys)
    const referenceIds = new Set(
      (fullDesign.strands ?? []).filter(s => s.is_reference).map(s => s.id))
    if (referenceIds.size) {
      ctrl.setReferenceStrands(referenceIds)
      ctrl.setReferenceHidden(newState.showReferenceGeometry === false)
    }
    const { columnRep } = resolveRepOverrides(fullDesign)
    ctrl.applyRepOverrides(columnRep)
    if (newState.coloringMode && newState.coloringMode !== 'strand') {
      ctrl.applyColoring(
        newState.coloringMode, fullDesign, customColors,
        new Set(newState.loopStrandIds ?? []),
      )
    }
    if (!_designVisible) ctrl.root.visible = false
    _structuralOverlay = { ctrl, geometry: newGeo, design: fullDesign }
    markOperationTiming('structural-partial-render', {
      helices: realIds.length, nucleotides: patchGeometry.length,
    })

    // Consolidate only after the immediate interaction and its paint have had
    // time to finish. A newer store update cancels this through _rebuild.
    _structuralConsolidateTimer = setTimeout(() => {
      _structuralConsolidateTimer = null
      if (!_structuralOverlay) return
      const st = storeRef.getState()
      if (st.currentGeometry !== newGeo || st.currentDesign !== fullDesign) return
      const run = () => {
        if (!_structuralOverlay) return
        const latest = storeRef.getState()
        if (latest.currentGeometry === newGeo && latest.currentDesign === fullDesign) {
          _rebuild(newGeo, fullDesign, latest.currentHelixAxes)
        }
      }
      const idle = globalThis.requestIdleCallback
      if (idle) idle(run, { timeout: 2500 }); else setTimeout(run, 0)
    }, 750)
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
    // While an external (job-snapshot) render owns the scene, ignore live-store
    // changes — the CanDo display controller rebuilds the live model on teardown.
    if (_externalActive) return
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

    // Per-cluster colour + opacity are visual-only design fields too, so the
    // structural early-return below skips them. Repaint here instead.
    //
    // Guarded by a cheap signature rather than by array identity: cluster_transforms
    // gets a NEW array on every gizmo-drag patch (~60/s) while only the pose moves,
    // and repainting means an O(nucleotides) applyColoring sweep. The signature is
    // stable across a pose-only change.
    if (designChanged && _helixCtrl) {
      const sig = clusterDisplaySignature(newState.currentDesign)
      if (sig !== _clusterDisplaySig) {
        _clusterDisplaySig = sig
        _refreshClusterDisplay(newState.currentDesign)
      }
    }

    // Strand and group colours are presentation-only. Repaint the existing mesh
    // materials in place before the structural-change early return below; this
    // keeps loaded simulation positions intact and avoids geometry reconstruction.
    if ((newState.strandColors !== prevState.strandColors ||
         newState.strandGroups !== prevState.strandGroups) && _helixCtrl) {
      const prevEff = _effectiveColors(prevState.strandColors ?? {}, prevState.strandGroups)
      const newEff  = _effectiveColors(newState.strandColors  ?? {}, newState.strandGroups)
      const palette = _helixCtrl.getPaletteColors()
      const allIds  = new Set([...Object.keys(prevEff), ...Object.keys(newEff), ...palette.keys()])
      for (const sid of allIds) {
        const oldColor = prevEff[sid] ?? palette.get(sid)
        const newColor = newEff[sid]  ?? palette.get(sid)
        if (newColor != null && newColor !== oldColor) _helixCtrl.setStrandColor(sid, newColor)
      }
      if (newState.coloringMode && newState.coloringMode !== 'strand') {
        _helixCtrl.applyColoring(
          newState.coloringMode, newState.currentDesign, newEff,
          new Set(newState.loopStrandIds ?? []))
      }
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
      if (_coverageChanged) {
        markOperationTiming('partial-patch-rejected', { reason: 'scaffold-coverage-changed' })
      }
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
      if (!_coverageChanged && _tryStructuralOverlay(
        newState.lastPartialChangedHelixIds,
        newState.currentGeometry,
        prevState,
        newState,
      )) return
    }

    if (window._cnDebug && storeRef.getState().cadnanoActive) {
      console.warn(`[CN f${window._cnFrame}] design_renderer._rebuild() geo:${geoChanged} des:${designChanged} loop:${loopChanged}`,
        new Error().stack.split('\n').slice(2, 8).join('\n'))
    }
    _rebuild(newState.currentGeometry, newState.currentDesign, newState.currentHelixAxes)
    markOperationTiming('scene-rebuilt')
    finishOperationAfterRender()
    // Re-apply visibility after rebuild — root covers extra-base beads/slabs as children.
    if (!_designVisible) {
      if (_helixCtrl?.root) _helixCtrl.root.visible = false
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

    residueTransformInfo(target) {
      return _helixCtrl?.residueTransformInfo?.(target) ?? null
    },

    applyResidueTransformMatrix(info, matrix) {
      return _helixCtrl?.applyResidueTransformMatrix?.(info, matrix) ?? false
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
    /** Active anchor glow-sprite count (e2e/console use it to confirm the purple halo
     *  actually rendered — mirrors clashGlowCount/fluoroGlowCount). */
    anchorGlowCount()      { return _anchorGlowLayer.count() },

    /** Show red glow over backbone entries flagged as steric clashes. */
    setClashHighlight(entries) { _clashGlowLayer.setEntries(entries) },
    clearClashHighlight()      { _clashGlowLayer.clear() },
    /** Active clash glow-sprite count (e2e uses it to confirm the clash toggle rendered). */
    clashGlowCount()           { return _clashGlowLayer.count() },

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
     * Call each frame during unfold animation, and on every simulation frame
     * (applyFemPositions), after bead positions are mutated in place.
     *
     * MUST list every layer created at :60-106 — pinned by design_renderer.test.js.
     * A layer omitted here keeps drawing its halo at the previous positions until
     * the next full rebuild.  (_captureGlowLayer was missing until 2026-08-01.)
     */
    refreshAllGlow() {
      _glowLayer.refresh()
      _undefinedGlowLayer.refresh()
      _anchorGlowLayer.refresh()
      _clashGlowLayer.refresh()
      _captureGlowLayer.refresh()
      _previewGlowLayer.refresh()
      _fluoroGlowLayer.refresh()
    },

    setStrandColor(strandId, hexColor) {
      const { strandColors } = storeRef.getState()
      storeRef.setState({ strandColors: { ...strandColors, [strandId]: hexColor } })
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
      if (_structuralOverlay?.ctrl.root) _structuralOverlay.ctrl.root.visible = visible
    },

    /**
     * Render an EXTERNAL design's geometry (e.g. a CanDo job's own snapshot — the
     * topology the design had when the analysis ran) in place of the live store
     * design, so FEM overlays land on beads that actually match the solved topology.
     * Display-only, mirrors the reactive rebuild path but from provided data; the
     * store's active design is untouched.  While active the store subscription is
     * suppressed — call clearExternalGeometry() to restore the live model.
     *
     * @param {object} design     the snapshot Design object
     * @param {Array}  geometry   its nucleotide positions (as GET /design/geometry)
     * @param {object} helixAxes  map helix_id → {start,end,samples?,ovhgAxes?,segments?}
     */
    renderExternalGeometry(design, geometry, helixAxes) {
      _externalActive = true
      _rebuild(geometry, design, helixAxes)
      if (!_designVisible && _helixCtrl?.root) _helixCtrl.root.visible = false
    },

    /** Restore the live store design after a renderExternalGeometry() overlay.
     *  No-op (no rebuild) when no external render is active. */
    clearExternalGeometry() {
      if (!_externalActive) return
      _externalActive = false
      const { currentGeometry, currentDesign, currentHelixAxes } = storeRef.getState()
      _rebuild(currentGeometry, currentDesign, currentHelixAxes)
      if (!_designVisible && _helixCtrl?.root) _helixCtrl.root.visible = false
    },

    /**
     * Apply mrDNA-relaxed backbone positions as a scene overlay.
     * @param {Array<{helix_id, bp_index, direction, backbone_position}>} updates
     */
    applyFemPositions(updates, amp = 1.0) {
      _activeFemUpdates = Array.isArray(updates)
        ? updates.map(u => ({ ...u, backbone_position: [...u.backbone_position] }))
        : null
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
      // Simulation frames mutate the existing backbone entry positions rather than
      // replacing currentGeometry. Refresh position-backed overlays on every frame;
      // the store subscriber cannot observe these playback/scrub mutations.
      this.refreshAllGlow()
    },

    /** Snapshot of the simulation/FEM positions currently driving the model. */
    getFemPositions() {
      return _activeFemUpdates?.map(u => ({ ...u, backbone_position: [...u.backbone_position] })) ?? null
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
      _applyExtraBaseScalarColors(colorByKey)
    },
    /** Inject non-design nucleotides (oxDNA surface capture strands) into every CG rep.
     *  `nucs` = plain nucleotide dicts (unique high bp_index, `cap<i>` helix/strand ids);
     *  `colorHex` colours them.  Pass [] to remove them.  Triggers a rebuild. */
    setExtraNucleotides(nucs, colorHex = null, highlight = undefined) {
      _extraNucs = Array.isArray(nucs) ? nucs : []
      // nucColor → setColorAt(setHex(color)) needs an INTEGER; the store's strand colours are
      // ints too, so parse a '#rrggbb' string to an int.
      if (colorHex != null) {
        _extraColor = (typeof colorHex === 'string')
          ? parseInt(colorHex.replace(/^#/, ''), 16)
          : colorHex
      }
      if (highlight !== undefined) _captureHighlight = !!highlight
      const { currentGeometry, currentDesign, currentHelixAxes } = storeRef.getState()
      if (currentGeometry && currentDesign) {
        _rebuild(currentGeometry, currentDesign, currentHelixAxes)
        // _rebuild allocates a FRESH root with visible=true. Without this the CG model pops
        // back on under an active atomistic/surface rep — and stays up until the oxDNA
        // overlay's (multi-second) atom build lands, which reads as "NADOC is broken".
        if (!_designVisible && _helixCtrl?.root) _helixCtrl.root.visible = false
      } else {
        _applyCaptureGlow()   // no geometry to rebuild (setup w/o design) — still sync glow
      }
    },
    /** DEV diagnostics for the capture-strand injection: how many cap beads rendered and
     *  the colour they actually got (read back from the built entries). */
    debugCaptureRender() {
      const entries = _helixCtrl?.backboneEntries || []
      const caps = entries.filter(e => e.nuc && typeof e.nuc.strand_id === 'string' && e.nuc.strand_id.startsWith('cap'))
      const slabs = (_helixCtrl?.slabEntries || []).filter(e => e.nuc && String(e.nuc.strand_id).startsWith('cap'))
      const cones = (_helixCtrl?.coneEntries || []).filter(e => String(e.strandId).startsWith('cap'))
      const hex = (c) => c == null ? null : '#' + ((c >>> 0) & 0xffffff).toString(16).padStart(6, '0')
      return {
        extraNucs: _extraNucs.length, extraColor: hex(_extraColor),
        capBeads: caps.length, capBeadColor: caps.length ? hex(caps[0].defaultColor) : null,
        capSlabs: slabs.length, capSlabAxis: slabs.length ? slabs[0].nuc.axis_tangent : null,
        capCones: cones.length,
        capCrossCones: cones.filter(e => e.isCrossHelix).length,
        highlight: _captureHighlight, glowCount: _captureGlowLayer.count(),
      }
    },
    /** Exact live Three.js inventory + connector-length audit for RMSF/trajectory debugging. */
    debugRenderedAudit(thresholdNm = 2) {
      const bb = _helixCtrl?.backboneEntries || []
      const slabs = _helixCtrl?.slabEntries || []
      const cones = _helixCtrl?.coneEntries || []
      const color = new THREE.Color()
      const coneMatrix = new THREE.Matrix4()
      const conePos = new THREE.Vector3(), coneQuat = new THREE.Quaternion(), coneScale = new THREE.Vector3()
      const drawnConeLength = (e) => {
        e.instMesh.getMatrixAt(e.id, coneMatrix)
        coneMatrix.decompose(conePos, coneQuat, coneScale)
        return Math.abs(coneScale.y)
      }
      let scalarChanged = 0, scalarChangedScaffold = 0, scalarChangedCapture = 0
      const currentColors = new Set()
      for (const e of bb) {
        e.instMesh.getColorAt?.(e.id, color)
        const hex = color.getHex()
        currentColors.add(hex)
        if (hex !== e.defaultColor) {
          scalarChanged++
          if (e.nuc?.strand_type === 'scaffold') scalarChangedScaffold++
          if (e.nuc?.is_surface_capture) scalarChangedCapture++
        }
      }
      return {
        inventory: inventoryRenderedElements(bb, slabs, cones),
        bond_audit: auditRenderedBonds(bb, cones, thresholdNm, drawnConeLength),
        fem_updates: _activeFemUpdates?.length ?? 0,
        colors: {
          distinct_bead_colors: currentColors.size,
          changed_from_default: scalarChanged,
          changed_scaffold: scalarChangedScaffold,
          changed_surface_capture: scalarChangedCapture,
        },
        rebuild: { serial: _rebuildSerial, stack: _lastRebuildStack },
      }
    },
    clearScalarColors() {
      _helixCtrl?.clearScalarColors()
      _scalarArcUpdater?.(null)
      _restoreExtraBaseColors()
    },

    setDetailLevel(level) {
      _detailLevel = level
      _helixCtrl?.setDetailLevel(level)
      _applyXoverExtrasLod()
    },

    setBeadRadius(r)     { _helixCtrl?.setBeadRadius(r) },
    setCylinderRadius(r) { _helixCtrl?.setCylinderRadius(r) },

    /** Base-pair slab plate thickness in nm (the slab's smallest dimension). */
    setSlabThickness(nm) {
      _slabThickness = nm
      _helixCtrl?.setSlabThickness(nm)
    },

    /** Current GLOBAL LOD level: 0=full, 1=beads, 2=cylinders. Use this — not the
     *  cylinder mesh's .visible — to decide "are beads globally hidden", since
     *  mixed-representation overrides make the cylinder mesh visible at full LOD. */
    getDetailLevel()                 { return _detailLevel },

    getCylinderMesh()                { return _helixCtrl?.getCylinderMesh() ?? null },
    getOverhangCylinderMesh()        { return _helixCtrl?.getOverhangCylinderMesh() ?? null },
    getOverhangFullCylinderMesh()    { return _helixCtrl?.getOverhangFullCylinderMesh() ?? null },
    getCylinderDomainData()          { return _helixCtrl?.getCylinderDomainData() ?? [] },
    getCylinderDomainAt(id)          { return _helixCtrl?.getCylinderDomainAt(id) ?? null },
    getOverhangCylinderDomainAt(id)  { return _helixCtrl?.getOverhangCylinderDomainAt(id) ?? null },
    getOverhangFullCylinderDomainAt(id) { return _helixCtrl?.getOverhangFullCylinderDomainAt(id) ?? null },
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
     * Every extra-base crossover bead as a base-level PICK candidate.
     *
     * `i` is the geometric bead slot (what a click resolves to, laid out A→B); `simK` is
     * the simulation insert index (5′→3′), which is what `__xb__:<xoId>:<k>` means
     * everywhere else in the app and in the backend. On a B→A crossover those run
     * opposite ways — `simBeadIndex` is its own inverse, so it maps both directions.
     *
     * Computed fresh per call and deliberately NOT sharing `_xoverGlowLive`:
     * getXoverBeadGlowEntries overwrites that array and three live-update loops read it,
     * so a second consumer would fight them.
     */
    getXoverBeadEntries() {
      if (!_xoverBeadsMesh || !_xoverArcData) return []
      const out = []
      for (const ad of _xoverArcData) {
        for (let i = 0; i < ad.beadCount; i++) {
          out.push({
            xoId: ad.xoId,
            i,
            simK: simBeadIndex(i, ad.beadCount, ad.simReversed),
            instMesh: _xoverBeadsMesh,
            id: ad.beadStartIdx + i,
          })
        }
      }
      return out
    },

    /** Snapshot one crossover-insert residue for independent transform preview. */
    xoverResidueInfo(target) {
      if (target?.helix_id !== '__xb__' || !_xoverBeadsMesh || !_xoverSlabsMesh) return null
      const entry = this.getXoverBeadEntries().find(e => e.xoId === target.crossover_id && e.simK === target.k)
      if (!entry) return null
      const beadMatrix = new THREE.Matrix4(), slabMatrix = new THREE.Matrix4()
      _xoverBeadsMesh.getMatrixAt(entry.id, beadMatrix)
      _xoverSlabsMesh.getMatrixAt(entry.id, slabMatrix)
      const slabConnectorMatrix = _xoverSlabConnMesh ? new THREE.Matrix4() : null
      if (slabConnectorMatrix) _xoverSlabConnMesh.getMatrixAt(entry.id, slabConnectorMatrix)
      const arcData = _xoverArcDataMap?.get(entry.xoId) ?? null
      const beadMatrices = []
      if (arcData) {
        for (let i = 0; i < arcData.beadCount; i++) {
          const m = new THREE.Matrix4()
          _xoverBeadsMesh.getMatrixAt(arcData.beadStartIdx + i, m)
          beadMatrices.push(m)
        }
      }
      return {
        entry, beadMatrix, slabMatrix, slabConnectorMatrix, arcData, beadMatrices,
        centroid: new THREE.Vector3().setFromMatrixPosition(beadMatrix),
      }
    },

    /** Preview a world-space delta from an xoverResidueInfo source snapshot. */
    applyXoverResidueMatrix(info, matrix) {
      if (!info?.entry || !_xoverBeadsMesh || !_xoverSlabsMesh) return false
      _xoverBeadsMesh.setMatrixAt(info.entry.id, matrix.clone().multiply(info.beadMatrix))
      _xoverSlabsMesh.setMatrixAt(info.entry.id, matrix.clone().multiply(info.slabMatrix))
      if (info.arcData && _xoverConnMesh) {
        const points = [info.arcData.pointA.clone()]
        const m = new THREE.Matrix4()
        for (let i = 0; i < info.beadMatrices.length; i++) {
          m.copy(info.beadMatrices[i])
          if (i === info.entry.i) m.premultiply(matrix)
          points.push(new THREE.Vector3().setFromMatrixPosition(m))
        }
        points.push(info.arcData.pointB.clone())
        setExtraBaseConnectors(
          _xoverConnMesh, info.arcData.connStartIdx, points,
          info.arcData.beadCount + 1, null,
        )
        _xoverConnMesh.instanceMatrix.needsUpdate = true
      }
      if (_xoverSlabConnMesh) {
        setExtraBaseSlabConnectors(
          _xoverBeadsMesh, _xoverSlabsMesh, _xoverSlabConnMesh,
          info.entry.id, 1, null,
        )
        _xoverSlabConnMesh.instanceMatrix.needsUpdate = true
      }
      _xoverBeadsMesh.instanceMatrix.needsUpdate = true
      _xoverSlabsMesh.instanceMatrix.needsUpdate = true
      return true
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
     * Re-read the per-cluster display fields (`color`, `opacity`) off a design and
     * push them to the renderer. Two callers: the store subscriber above (after a
     * PATCH lands) and the sidebar's swatch popover, which passes a locally-patched
     * design for a zero-latency live preview while the slider is dragged.
     * @param {object} [design]  defaults to the store's current design
     */
    refreshClusterDisplay(design = null, what = null) {
      _refreshClusterDisplay(design ?? storeRef.getState().currentDesign, what)
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
     * @param {Map<string, THREE.Vector3>} straightBaseMap key "hid:bp:dir" → straight base_position
     * @param {number} t  lerp factor 0=straight, 1=deformed
     */
    applyDeformLerp(straightPosMap, straightAxesMap, straightBnMap, straightBaseMap, t) {
      _helixCtrl?.applyDeformLerp(straightPosMap, straightAxesMap, straightBnMap, straightBaseMap, t)
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
            // Simulated k is 5′→3′ from the strand's exit half; beads run A→B.
            const bi = simBeadIndex(k, ad.beadCount, ad.simReversed)
            setExtraBaseInstanceFromSim(
              _xoverBeadsMesh, _xoverSlabsMesh, ad.beadStartIdx + bi, s.pos, s.normal, ad.avgAx)
            for (const g of _xoverGlowLive) {
              if (g.arcData === ad && g.localIdx === bi) g.pos.set(s.pos[0], s.pos[1], s.pos[2])
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
          posA, _clusterXoverCtrl, posB, ad.avgAx,
          ad.simReversed, ad.localFrameReversed, ad.savedTransforms, ad.sequence,
        )
        const placements = buildCrossoverExtraPlacements({
          xoId: ad.xoId, count: ad.beadCount, pointA: posA,
          control: _clusterXoverCtrl, pointB: posB, helixAxis: ad.avgAx,
          sequence: ad.sequence, simReversed: ad.simReversed,
          localFrameReversed: ad.localFrameReversed,
          savedTransforms: ad.savedTransforms,
        })
        for (const g of _xoverGlowLive) {
          if (g.arcData === ad) g.pos.copy(placements[g.localIdx].center)
        }
        dirty = true
      }
      if (dirty) this.flushExtraBaseMeshes()
    },

    /**
     * Reposition extra-base beads+slabs for a single crossover arc.
     * Called per-arc per-frame by unfold_view animation loops.
     */
    updateExtraBaseArc(crossoverId, posA, _lineControl, posB) {
      if (!_xoverArcDataMap || !_xoverBeadsMesh || !_xoverSlabsMesh) return
      if (_hiddenCrossoverIds.has(crossoverId)) return
      const ad = _xoverArcDataMap.get(crossoverId)
      if (!ad) return
      // Arc lines are emitted in strand traversal order, which is B→A for half of
      // crossovers. Placement identity is always geometric half_a→half_b. Normalize
      // the two live points before they enter the residue placement core.
      const direct = posA.distanceToSquared(ad.pointA) + posB.distanceToSquared(ad.pointB)
      const swapped = posA.distanceToSquared(ad.pointB) + posB.distanceToSquared(ad.pointA)
      const liveA = swapped < direct ? posB : posA
      const liveB = swapped < direct ? posA : posB
      ad.pointA.copy(liveA)
      ad.pointB.copy(liveB)
      // Regular crossover lines have their own view-animation control point (historically
      // a global-Z bow). It is not a residue placement input. Recompute the canonical
      // insert control from the live endpoints so no caller can re-place extra bases.
      arcControlPoint(liveA, liveB, ad.nucA, ad.nucB, _clusterXoverCtrl)
      // Simulation overlay active: pin the extra-base beads to their REAL relaxed
      // positions, NOT this arc's (native/geometric) Bezier.  Without this, any arc-layout
      // pass that drives a native Bezier — refreshArcVisibility on a rep switch, unfold,
      // deform — snaps the __xb__ beads back to native while the rest of the structure
      // stays simulated.  Mirrors applyClusterCrossoverUpdate's sim branch.
      const sim = _simXbByCrossover?.get(ad.xoId)
      if (sim) {
        for (let k = 0; k < ad.beadCount; k++) {
          const s = sim.get(k)
          if (!s) continue
          const bi = simBeadIndex(k, ad.beadCount, ad.simReversed)
          setExtraBaseInstanceFromSim(
            _xoverBeadsMesh, _xoverSlabsMesh, ad.beadStartIdx + bi, s.pos, s.normal, ad.avgAx)
          for (const g of _xoverGlowLive) {
            if (g.arcData === ad && g.localIdx === bi) g.pos.set(s.pos[0], s.pos[1], s.pos[2])
          }
        }
        return
      }
      updateExtraBaseInstances(
        _xoverBeadsMesh, _xoverSlabsMesh,
        ad.beadStartIdx, ad.beadCount,
        liveA, _clusterXoverCtrl, liveB, ad.avgAx,
        ad.simReversed, ad.localFrameReversed, ad.savedTransforms, ad.sequence,
      )
      // Keep selection glow positions on the exact same placement records as the meshes.
      const placements = buildCrossoverExtraPlacements({
        xoId: ad.xoId, count: ad.beadCount, pointA: liveA, control: _clusterXoverCtrl,
        pointB: liveB, helixAxis: ad.avgAx, simReversed: ad.simReversed,
        localFrameReversed: ad.localFrameReversed,
        sequence: ad.sequence, savedTransforms: ad.savedTransforms,
      })
      for (const g of _xoverGlowLive) {
        if (g.arcData === ad) g.pos.copy(placements[g.localIdx].center)
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
