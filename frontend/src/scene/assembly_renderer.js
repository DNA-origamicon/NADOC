/**
 * Assembly renderer — adds PartInstance geometry to the Three.js scene.
 *
 * Each PartInstance is rendered as a THREE.Group whose matrix is set from the
 * instance's Mat4x4 placement transform (row-major → transpose for Three.js
 * column-major). Groups are rebuilt only when an instance's source or
 * transform changes; visibility changes are applied in-place.
 *
 * Linker rendering (rebuildLinkers):
 *   - Linker helices:  fetches nucleotide geometry from /assembly/linker-geometry,
 *     renders using buildHelixObjects into a dedicated _linkerGroup.
 *   - Virtual scaffold connections (strand.id starts with "__vsc__"):
 *     draws a dashed green THREE.Line between the two helix end positions,
 *     looked up from cached instance helix_axes and transformed by the instance
 *     placement matrix.
 *
 * Usage (factory — preferred):
 *   const ar = createAssemblyRenderer({
 *     scene, store, api,
 *     useShared: window.NADOC_SHARED_RENDERER === true,
 *   })
 *   ar.rebuild(assembly)          // call whenever currentAssembly changes
 *   ar.setActiveInstance(id)      // adds white BoxHelper around selected part
 *   ar.dispose()                  // removes all instance groups from scene
 *
 * Legacy entry point `initAssemblyRenderer(scene, store, api)` is still
 * exported for tests / external callers and is what the factory delegates to
 * on the default (old) path.
 *
 * ──────────────────────────────────────────────────────────────────────────
 * AssemblyRenderer interface (path-to-thousands Phase 3a seam)
 * ──────────────────────────────────────────────────────────────────────────
 * Both the existing per-instance renderer and the future shared-instancing
 * renderer (Phase 3b/3c) MUST satisfy this contract:
 *
 *   rebuild(assembly, opts?)                  → Promise<void>
 *   rebuildLinkers(assembly)                  → void | Promise<void>
 *   setActiveInstance(instanceId)             → void
 *   setLiveTransform(instanceId, matrix4)     → void
 *   getLiveTransform(instanceId)              → THREE.Matrix4 | null
 *   getInstanceDesign(instanceId)             → Design | null
 *   getInstanceRenderData(instanceId)         → { … } | null
 *   captureInstanceClusterBase(instId, cluster)         → void
 *   applyInstanceClusterTransform(instId, cluster, m4)  → void
 *   pickInstanceCluster(ndc, camera, opts?)   → hit | null
 *   pickInstance(ndc, camera)                 → hit | null
 *   pickPartJoint(ndc, camera)                → hit | null
 *   dispose()                                 → void
 *   getBoundingBox()                          → THREE.Box3 | null
 *   getInstanceCenters()                      → Array<{ id, center, group }>
 *   auditInstanceBox(instanceId?)             → void
 *   invalidateInstance(instanceId)            → void
 *   applyInlineGeometry(path, design, nucs, helixAxes) → Promise<void>
 *   getInstanceBluntEnds()                    → Array<{…}>
 *   getConnectorClusterId(instId, label)      → string | null
 *   getConnectorClusterIds(instId, label)     → Array<string>
 *   getLabelTable()                           → Array<{…}>
 *   getInstanceBackboneEntries(instanceId)    → { entries, matrixWorld }
 *   setPhotoMode(on)                          → void
 *   onRebuildComplete(callback)               → void
 */

import * as THREE from 'three'
import { buildHelixObjects, buildStapleColorMap, CG_LOD } from './helix_renderer.js'
import { buildCrossoverConnections, updateExtraBaseInstances, setExtraBaseSlabConnectors } from './crossover_connections.js'
import { crossoverControlPoint as arcControlPoint } from './crossover_extra_placement.js'
import { initAtomisticRenderer } from './atomistic_renderer.js'
import { initSurfaceRenderer } from './surface_renderer.js'
import { initProteinTraceRenderer } from './protein_trace_renderer.js'
import {
  computeInstanceBluntEnds as _computeInstanceBluntEnds,
  bendCenterRecordToWorld as _bendCenterRecordToWorld,
} from './blunt_end_connectors.js'
import { clusterMemberFilter as _clusterMemberFilter } from './cluster_entries.js'
import { _rebuildLinkerHelices } from './assembly_linker_render.js'
import {
  _OVHG_SPRITE_HEIGHT_BASE, _makeOverhangNameTexture, _overhangLabelAnchorsLocal,
} from './assembly_overhang_labels.js'
import { _createSharedInstancingRenderer } from './assembly_renderer_shared.js'
import {
  buildBundleGeometry, buildPrismGeometry, buildPanelSurface,
  buildSpineSections, buildSweptHullGeometry, buildHullMeshPhong,
  HULL_OPACITY, CROSS_MARGIN, AXIAL_MARGIN, MIN_HC_FACES,
} from './joint_renderer.js'

// Arc vertex count — matches unfold_view.js for visual consistency.
const _ARC_SEGS = 20

const _LABEL_OPACITY = 0.72

function _makeHelixLabelSprite(num) {
  const size = 128, cv = document.createElement('canvas')
  cv.width = size; cv.height = size
  const ctx = cv.getContext('2d'), r = size / 2
  ctx.beginPath(); ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
  ctx.fillStyle = 'rgba(13,17,23,0.80)'; ctx.fill()
  ctx.beginPath(); ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
  ctx.strokeStyle = 'rgba(88,166,255,0.65)'; ctx.lineWidth = r * 0.13; ctx.stroke()
  const str = String(num)
  ctx.fillStyle = '#e6edf3'
  ctx.font = `bold ${str.length > 2 ? r * 0.68 : r * 0.84}px monospace`
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText(str, r, r + 1)
  const tex = new THREE.CanvasTexture(cv)
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false })
  const spr = new THREE.Sprite(mat)
  spr.scale.set(0.90, 0.90, 1)
  return spr
}

const _BDNA_RISE   = 0.334  // nm per bp — matches BDNA_RISE_PER_BP in constants.js
const _LABEL_GAP   = 1.0    // nm outward offset from helix/overhang tip

function _addLabelSprite(group, pos, label, helixId, tag) {
  const spr = _makeHelixLabelSprite(label)
  spr.position.copy(pos)
  spr.material.opacity  = _LABEL_OPACITY
  spr.material.depthTest = false
  spr.renderOrder = 5
  spr.userData.helixId    = helixId
  spr.userData.helixLabel = label
  spr.userData.tag        = tag   // 'near' | 'far' | 'ovhg'
  spr.userData.pos        = pos.toArray()
  group.add(spr)
}

function _buildInstanceOverhangNameGroup(design, nucleotides, showOverhangNames) {
  const group = new THREE.Group()
  group.visible = !!showOverhangNames
  group.name = 'overhangNameLabels'

  for (const a of _overhangLabelAnchorsLocal(design, nucleotides)) {
    const tex    = _makeOverhangNameTexture(a.label)
    const aspect = tex.image.width / tex.image.height
    const mat    = new THREE.SpriteMaterial({
      map:         tex,
      depthTest:   false,
      transparent: true,
    })
    const sprite = new THREE.Sprite(mat)
    sprite.scale.set(_OVHG_SPRITE_HEIGHT_BASE * aspect, _OVHG_SPRITE_HEIGHT_BASE, 1)
    sprite.position.set(a.x, a.y, a.z)
    sprite.renderOrder = 12
    sprite.userData.overhangId    = a.overhangId
    sprite.userData.overhangLabel = a.label
    sprite.userData.tag           = 'overhang-name'
    group.add(sprite)
  }
  return group
}

function _buildInstanceLabelGroup(design, helixAxes, showLabels) {
  const group = new THREE.Group()
  group.visible = showLabels
  if (!design?.helices?.length) return group

  design.helices.forEach((h, i) => {
    const ax       = helixAxes?.[h.id]
    const startArr = ax?.start ?? (h.axis_start ? [h.axis_start.x, h.axis_start.y, h.axis_start.z] : null)
    const endArr   = ax?.end   ?? (h.axis_end   ? [h.axis_end.x,   h.axis_end.y,   h.axis_end.z]   : null)
    if (!startArr || !endArr) return

    const label = h.label ?? i
    const start = new THREE.Vector3(...startArr)
    const end   = new THREE.Vector3(...endArr)
    const dir   = end.clone().sub(start)
    const unit  = dir.length() > 0 ? dir.clone().normalize() : new THREE.Vector3(0, 0, 1)

    // Near end: 1 bp outside axis_start
    _addLabelSprite(group, start.clone().addScaledVector(unit, -_BDNA_RISE),  label, h.id, 'near')
    // Far end: 1 bp outside axis_end
    _addLabelSprite(group, end.clone().addScaledVector(unit,   _BDNA_RISE),   label, h.id, 'far')

    // Overhang tips: one label per overhang at the free-tip end
    const ovhgAxes = ax?.ovhgAxes ?? null
    if (ovhgAxes) {
      for (const [ovhgId, ovhgAx] of Object.entries(ovhgAxes)) {
        if (!ovhgAx?.start || !ovhgAx?.end) continue
        const os    = new THREE.Vector3(...ovhgAx.start)
        const oe    = new THREE.Vector3(...ovhgAx.end)
        const odir  = oe.clone().sub(os)
        const ounit = odir.length() > 0 ? odir.clone().normalize() : unit.clone()
        // end is already one bp beyond bp_max; add LABEL_GAP outward from tip
        _addLabelSprite(group, oe.clone().addScaledVector(ounit, _LABEL_GAP), label, h.id, 'ovhg')
      }
    }
  })
  return group
}

/**
 * Build a Three.js Group containing merged LineSegments for all crossover
 * connections in an instance.  Lines are straight (bow=0) for the 3D view.
 * Returns null when there are no connections.
 *
 * @param {Array<{from, to, color, fromNuc}>} connections
 * @returns {THREE.Group|null}
 */
function _buildInstanceCrossoverArcs(connections, showPeriodic = false) {
  if (!connections?.length) return null

  // End-to-end (periodic-seam) connectors are segregated into their own line so
  // the View toggle hides them by default without affecting the real crossovers.
  const periodicConns = connections.filter(c => c.isPeriodicSeam)
  const normalConns   = connections.filter(c => !c.isPeriodicSeam)
  const scaffoldConns = normalConns.filter(c => c.fromNuc?.strand_type === 'scaffold')
  const stapleConns   = normalConns.filter(c => c.fromNuc?.strand_type !== 'scaffold')

  function _buildMerged(conns, arcType) {
    if (!conns.length) return null
    const N         = conns.length
    const vertCount = N * (_ARC_SEGS + 1)
    const positions = new Float32Array(vertCount * 3)
    const colors    = new Float32Array(vertCount * 3)
    const idxCount  = N * _ARC_SEGS * 2
    const idx       = vertCount > 65535 ? new Uint32Array(idxCount) : new Uint16Array(idxCount)
    const tc        = new THREE.Color()

    for (let a = 0; a < N; a++) {
      const { from, to, color } = conns[a]
      const base = a * (_ARC_SEGS + 1)
      for (let s = 0; s < _ARC_SEGS; s++) {
        idx[(a * _ARC_SEGS + s) * 2]     = base + s
        idx[(a * _ARC_SEGS + s) * 2 + 1] = base + s + 1
      }
      tc.setHex(color ?? 0x00ccff)
      for (let v = 0; v <= _ARC_SEGS; v++) {
        const t  = v / _ARC_SEGS
        const bi = (base + v) * 3
        positions[bi]     = from.x + (to.x - from.x) * t
        positions[bi + 1] = from.y + (to.y - from.y) * t
        positions[bi + 2] = from.z + (to.z - from.z) * t
        colors[bi] = tc.r; colors[bi + 1] = tc.g; colors[bi + 2] = tc.b
      }
    }

    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    geo.setAttribute('color',    new THREE.BufferAttribute(colors,    3))
    geo.setIndex(new THREE.BufferAttribute(idx, 1))
    const mat  = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.85 })
    const line = new THREE.LineSegments(geo, mat)
    line.frustumCulled = false
    line.name = `instanceXoverArc_${arcType}`
    line.userData.arcConnections = conns
    return line
  }

  const group        = new THREE.Group()
  const scaffoldLine = _buildMerged(scaffoldConns, 'scaffold')
  const stapleLine   = _buildMerged(stapleConns, 'staple')
  const periodicLine = _buildMerged(periodicConns, 'periodic')
  if (scaffoldLine) group.add(scaffoldLine)
  if (stapleLine)   group.add(stapleLine)
  if (periodicLine) {
    periodicLine.userData.isPeriodicSeam = true
    periodicLine.visible = showPeriodic        // default hidden (toggle in View menu)
    group.add(periodicLine)
  }
  if (!group.children.length) return null
  group.userData.arcLines = group.children.slice()
  return group
}

const _xoverTmpA = new THREE.Vector3()
const _xoverTmpB = new THREE.Vector3()
const _xoverCtrl = new THREE.Vector3()

function _liveNucPos(helixCtrl, nuc, out) {
  const live = helixCtrl?.getNucLivePos?.(nuc)
  if (live) return out.copy(live)
  const bp = nuc?.backbone_position
  return bp ? out.set(bp[0], bp[1], bp[2]) : null
}

function _updateInstanceCrossoverArcs(entry) {
  if (!entry?.arcGroup || !entry.helixCtrl) return
  const lines = entry.arcGroup.userData.arcLines ?? entry.arcGroup.children ?? []
  for (const line of lines) {
    const conns = line.userData.arcConnections ?? []
    const attr = line.geometry?.getAttribute?.('position')
    if (!attr) continue
    const arr = attr.array
    for (let a = 0; a < conns.length; a++) {
      const conn = conns[a]
      const from = _liveNucPos(entry.helixCtrl, conn.fromNuc, _xoverTmpA) ?? conn.from
      const to   = _liveNucPos(entry.helixCtrl, conn.toNuc, _xoverTmpB) ?? conn.to
      const base = a * (_ARC_SEGS + 1)
      for (let v = 0; v <= _ARC_SEGS; v++) {
        const t  = v / _ARC_SEGS
        const bi = (base + v) * 3
        arr[bi]     = from.x + (to.x - from.x) * t
        arr[bi + 1] = from.y + (to.y - from.y) * t
        arr[bi + 2] = from.z + (to.z - from.z) * t
      }
    }
    attr.needsUpdate = true
    line.geometry?.computeBoundingSphere?.()
  }
}

function _updateInstanceExtraBaseCrossovers(entry) {
  const xr = entry?.xoverResult
  if (!xr || !entry.helixCtrl) return
  let dirty = false
  for (const ad of xr.arcData ?? []) {
    const posA = _liveNucPos(entry.helixCtrl, ad.nucA, _xoverTmpA)
    const posB = _liveNucPos(entry.helixCtrl, ad.nucB, _xoverTmpB)
    if (!posA || !posB) continue
    arcControlPoint(posA, posB, ad.nucA, ad.nucB, _xoverCtrl)
    updateExtraBaseInstances(
      xr.beadsMesh, xr.slabsMesh,
      ad.beadStartIdx, ad.beadCount,
      posA, _xoverCtrl, posB, ad.avgAx,
      ad.simReversed, ad.localFrameReversed, ad.savedTransforms, ad.sequence,
    )
    setExtraBaseSlabConnectors(
      xr.beadsMesh, xr.slabsMesh, xr.slabConnMesh,
      ad.beadStartIdx, ad.beadCount, null,
    )
    dirty = true
  }
  if (dirty) {
    if (xr.beadsMesh) xr.beadsMesh.instanceMatrix.needsUpdate = true
    if (xr.slabsMesh) xr.slabsMesh.instanceMatrix.needsUpdate = true
    if (xr.slabConnMesh) xr.slabConnMesh.instanceMatrix.needsUpdate = true
  }
}

/**
 * Build Three.js hull Groups for every cluster in a design and add them to
 * a target group (typically the instance group so they inherit its transform).
 * Returns an array of the Groups added, for later disposal.
 */
function _buildHullGroupsForDesign(design, helixAxes, targetGroup) {
  const groups = []
  if (!design?.cluster_transforms?.length || !helixAxes) return groups

  for (const cluster of design.cluster_transforms) {
    const bg = buildBundleGeometry(
      cluster, helixAxes, null, MIN_HC_FACES,
      CROSS_MARGIN, AXIAL_MARGIN,
      design.lattice_type ?? null,
    )
    if (!bg) continue

    const group   = new THREE.Group()
    const isCurved = cluster.helix_ids.some(hid => (helixAxes[hid]?.samples?.length ?? 0) > 2)

    if (isCurved) {
      const sections = buildSpineSections(cluster, helixAxes, CROSS_MARGIN, AXIAL_MARGIN)
      if (sections) {
        const curvedGeo  = buildSweptHullGeometry(sections)
        const curvedMesh = new THREE.Mesh(curvedGeo, buildHullMeshPhong(HULL_OPACITY))
        curvedMesh.renderOrder = 100
        const curvedEdges = new THREE.LineSegments(
          new THREE.EdgesGeometry(curvedGeo, 15),
          new THREE.LineBasicMaterial({ color: 0x000000, linewidth: 1, transparent: true, opacity: 1 }),
        )
        curvedEdges.renderOrder = 101
        group.add(curvedMesh, curvedEdges)
        targetGroup.add(group)
        groups.push(group)
        continue
      }
    }

    // Straight (or fallback) hull
    const geo  = bg.panels
      ? buildPanelSurface(bg.panels, bg.corners, bg.halfLen)
      : buildPrismGeometry(bg.corners, bg.halfLen)
    const mesh = new THREE.Mesh(geo, buildHullMeshPhong(HULL_OPACITY))
    mesh.quaternion.copy(bg.rotQ)
    mesh.position.copy(bg.bundleMid)
    mesh.renderOrder = 100
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geo, 15),
      new THREE.LineBasicMaterial({ color: 0x000000, linewidth: 1 }),
    )
    edges.quaternion.copy(bg.rotQ)
    edges.position.copy(bg.bundleMid)
    edges.renderOrder = 101
    group.add(mesh, edges)
    targetGroup.add(group)
    groups.push(group)
  }
  return groups
}

export function initAssemblyRenderer(scene, store, api) {
  // instId → { group, transformKey, sourceKey, reprKey, helixCtrl, atomisticRenderer,
  //            surfaceRenderer,
  //            hullGroups, design, helixAxes }
  const _cache        = new Map()
  let _boxHelper      = null
  let _boxHelperGroup = null   // which group the box helper currently tracks
  let _activeInstanceId = null
  // PartGroup visibility overlay — instance ids that should render as hidden
  // because their owning PartGroup has `visible=false`. Per-instance
  // `inst.visible` is left untouched (the overlay is read-only on instance
  // state); restoring the group reveals each member at its prior visibility.
  let _groupHiddenInstanceIds = new Set()
  // Photo mode: suppress annotation overlays (per-instance helix axis arrows,
  // helix-id labels, overhang-name sprites, active-instance BoxHelper). The
  // mate-mode blunt-end disks + orange joint indicators are toggled separately
  // through assemblyJointRenderer.setVisible() in main.js. We persist the
  // flag so rebuilds that happen WHILE photo mode is active (e.g. user
  // polymerizes mid-photo) apply the same hides to new instances.
  let _photoMode = false
  const _partJointMeshes = new Map()
  const _rc           = new THREE.Raycaster()
  // All instance groups currently in the scene — includes orphans from concurrent
  // rebuild races that are no longer referenced by _cache.
  const _allSceneGroups = new Set()

  // Scratch objects for _computeGroupBox — allocated once to avoid GC pressure
  const _instanceMat = new THREE.Matrix4()
  const _instanceBox = new THREE.Box3()

  // Per-instance helix_axes cache (local frame) for VSC endpoint lookups
  const _helixAxesCache    = new Map()  // instId → { [helixId]: { start, end } }
  const _instTransformCache = new Map() // instId → values[] (16-element row-major)
  // Backend-computed bend center-of-curvature connectors per instance, in
  // instance-LOCAL frame. Populated lazily by getInstanceBendCenters() on
  // Define-Mate; evicted when the instance is invalidated.
  const _bendCentersLocalCache = new Map() // instId → Array<{label, position, normal, ...}>

  // Linker geometry group (linker helices + VSC dashed lines)
  const _linkerGroup = new THREE.Group()
  _linkerGroup.name = 'assembly_linkers'
  scene.add(_linkerGroup)

  // ── Helpers ───────────────────────────────────────────────────────────────

  /**
   * Convert the API helix_axes array [{helix_id, start, end, samples}]
   * to the dict {[helixId]: {start, end, samples}} that buildHelixObjects expects.
   * Mirrors the same conversion in client.js getGeometry().
   */
  function _axesArrayToMap(raw) {
    if (!raw?.length) return null
    const map = {}
    for (const ax of raw) map[ax.helix_id] = { start: ax.start, end: ax.end, samples: ax.samples ?? null, ovhgAxes: ax.ovhg_axes ?? null }
    return map
  }

  function _disposeGroup(entry) {
    if (_boxHelperGroup === entry.group) {
      scene.remove(_boxHelper)
      _boxHelper.geometry?.dispose()
      _boxHelper.material?.dispose()
      _boxHelper = null
      _boxHelperGroup = null
    }
    entry.atomisticRenderer?.dispose()
    entry.surfaceRenderer?.dispose()
    entry.proteinTraceRenderer?.dispose()
    for (const grp of (entry.hullGroups ?? [])) {
      grp.traverse(o => {
        if (o.geometry && !o.geometry.userData?.shared) o.geometry.dispose()
        o.material?.dispose()
      })
    }
    entry.group.traverse(obj => {
      // helix_renderer template geometries (GEO_SPHERE etc.) are
      // module-level singletons shared by every helix in every instance.
      // Calling dispose() on them here would free their GPU buffers for
      // EVERY other instance using them too. The templates are tagged
      // with userData.shared = true at construction; skip those.
      if (obj.geometry && !obj.geometry.userData?.shared) obj.geometry.dispose()
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
        mats.forEach(m => { m.map?.dispose(); m.dispose() })
      }
    })
    scene.remove(entry.group)
    _allSceneGroups.delete(entry.group)
  }

  function _orientToAxis(axis) {
    const dir = axis.clone().normalize()
    return new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir)
  }

  function _clearPartJointIndicators() {
    for (const grp of _partJointMeshes.values()) {
      grp.parent?.remove(grp)
      grp.traverse(obj => {
        if (obj.geometry && !obj.geometry.userData?.shared) obj.geometry.dispose()
        if (obj.material) {
          const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
          mats.forEach(m => m.dispose())
        }
      })
    }
    _partJointMeshes.clear()
  }

  function _rebuildPartJointIndicators() {
    _clearPartJointIndicators()
    const assembly = store.getState().currentAssembly
    if (!assembly) return

    for (const [instanceId, entry] of _cache) {
      if (!entry.design?.cluster_joints?.length) continue
      const inst = assembly.instances?.find(i => i.id === instanceId)
      if (!inst) continue

      // Only render part-joint axis indicators on instances where the user
      // explicitly opted into interactive part-joints (right-click menu).
      // Otherwise the orange shaft/ring permanently floats inside every part —
      // it reads as a mystery "origin gizmo" rather than a joint affordance.
      if (inst.allow_part_joints !== true) continue

      const scale      = 2.0
      const baseColor  = 0xffff88
      const tipColor   = 0xffffcc

      for (const joint of entry.design.cluster_joints) {
        const origin = new THREE.Vector3(...(joint.axis_origin ?? [0, 0, 0]))
        const axis = new THREE.Vector3(...(joint.axis_direction ?? [0, 1, 0])).normalize()
        const q = _orientToAxis(axis)
        const grp = new THREE.Group()
        grp.userData.partJoint = { instanceId, jointId: joint.id, clusterId: joint.cluster_id }
        grp.position.copy(origin)
        grp.quaternion.copy(q)

        const shaft = new THREE.Mesh(
          new THREE.CylinderGeometry(0.08 * scale, 0.08 * scale, 1.8 * scale, 16),
          new THREE.MeshBasicMaterial({ color: baseColor, transparent: true, opacity: 0.9 }),
        )
        const tip = new THREE.Mesh(
          new THREE.ConeGeometry(0.22 * scale, 0.48 * scale, 20),
          new THREE.MeshBasicMaterial({ color: tipColor, transparent: true, opacity: 0.95 }),
        )
        tip.position.y = 1.12 * scale
        const ring = new THREE.Mesh(
          new THREE.TorusGeometry(1.18 * scale, 0.06 * scale, 10, 48),
          new THREE.MeshBasicMaterial({ color: baseColor, transparent: true, opacity: 0.95 }),
        )
        ring.rotation.x = Math.PI / 2
        ring.userData.isPartJointRing = true
        ring.userData.partJoint = grp.userData.partJoint
        // Exclude indicator geometry from selection bounding box + centroid math.
        // Without this, the joint axis (which can sit far from the part's
        // visible geometry, e.g. at a cluster centroid for an off-axis hinge)
        // bloats the BoxHelper and pulls the gizmo anchor away from the part.
        shaft.userData.skipBounds = true
        tip.userData.skipBounds   = true
        ring.userData.skipBounds  = true
        grp.add(shaft, tip, ring)
        entry.group.add(grp)
        _partJointMeshes.set(`${instanceId}:${joint.id}`, grp)
      }
    }
  }

  // ── Representation helpers ────────────────────────────────────────────────

  /**
   * Apply a representation to a cached instance entry.
   * For CG reprs: adjusts detail level and disposes any atomistic renderer.
   * For atomistic reprs: fetches geometry, creates an atomistic renderer in the
   * instance group (so it moves with the instance's placement transform), and
   * hides the CG root.
   */
  function _disposeHullGroups(entry) {
    for (const grp of (entry.hullGroups ?? [])) {
      grp.traverse(o => {
        if (o.geometry && !o.geometry.userData?.shared) o.geometry.dispose()
        o.material?.dispose()
      })
      entry.group.remove(grp)
    }
    entry.hullGroups = []
  }

  /**
   * Swap an entry's helixCtrl in place when going cheap LOD → richer LOD.
   *
   * The Phase-1 skip-allocate path means a 'cylinders'-built instance has
   * no bead / cone / slab buffers — upgrading to 'beads' or 'full' needs
   * a fresh buildHelixObjects call. This helper avoids the cost of a
   * full instance teardown (which re-fetches geometry over the network
   * and re-creates labels / arcs / xovers / overhang names / hull groups
   * even though only the helix LOD changed).
   *
   * Returns true on success; caller assumes side effects on entry.helixCtrl.
   */
  function _inPlaceHelixLodRebuild(entry, repr) {
    if (!entry?.helixCtrl?.root || !entry.nucleotides || !entry.design) return false

    // Detach arc + xover groups so the dispose-traversal doesn't wipe them.
    // They were added as children of helixCtrl.root in the original build
    // path. After the swap we re-parent them onto the new helixCtrl.root.
    const oldRoot = entry.helixCtrl.root
    const stash = []
    if (entry.arcGroup && entry.arcGroup.parent === oldRoot) {
      oldRoot.remove(entry.arcGroup)
      stash.push(entry.arcGroup)
    }
    if (entry.xoverResult?.group && entry.xoverResult.group.parent === oldRoot) {
      oldRoot.remove(entry.xoverResult.group)
      stash.push(entry.xoverResult.group)
    }

    // Dispose the old helix meshes' geometries + materials (skipping
    // module-level shared singletons — same rule as _disposeGroup).
    oldRoot.traverse(o => {
      if (o.geometry && !o.geometry.userData?.shared) o.geometry.dispose()
      if (o.material) {
        const mats = Array.isArray(o.material) ? o.material : [o.material]
        mats.forEach(m => { m.map?.dispose(); m.dispose() })
      }
    })
    entry.group.remove(oldRoot)

    // Rebuild helix meshes at the new LOD from the cached nucleotide list.
    const customColors = _buildCustomColors(entry.design)
    const newHelixCtrl = buildHelixObjects(
      entry.nucleotides, entry.design, entry.group,
      customColors, [], entry.helixAxes, repr,
    )

    // Re-parent the surviving sub-groups onto the new helixCtrl.root.
    for (const grp of stash) newHelixCtrl.root.add(grp)

    entry.helixCtrl = newHelixCtrl
    entry.reprKey   = repr
    _applyColoringToEntry(entry)
    return true
  }

  async function _applyRepresentation(entry, instId, repr) {
    const lod = CG_LOD[repr]

    // Always dispose previous non-CG renderers when switching away from them.
    if (repr !== 'vdw' && repr !== 'ballstick' && repr !== 'stick' && entry.atomisticRenderer) {
      entry.atomisticRenderer.dispose()
      entry.atomisticRenderer = null
    }
    if (repr !== 'surface' && entry.surfaceRenderer) {
      entry.surfaceRenderer.dispose()
      entry.surfaceRenderer = null
    }
    if (repr !== 'full' && repr !== 'cylinders' && entry.proteinTraceRenderer) {
      entry.proteinTraceRenderer.dispose()
      entry.proteinTraceRenderer = null
    }
    if (repr !== 'hull-prism') {
      _disposeHullGroups(entry)
    }

    if (lod !== undefined) {
      // CG repr (full / beads / cylinders)
      if (entry.helixCtrl?.root) entry.helixCtrl.root.visible = true
      const res = entry.helixCtrl?.setDetailLevel(lod)
      if (res?.needsRebuild) {
        // Stepping up to a level whose meshes weren't allocated at build
        // time (e.g. 'cylinders' → 'full'). Rebuild ONLY the helixCtrl
        // sub-tree using the entry's cached nucleotides — no network
        // round-trip, no rebuild of labels / overhang names / hull
        // groups / arcs / crossover meshes. Saves seconds per instance
        // for batch rep changes.
        _inPlaceHelixLodRebuild(entry, repr)
      }
      if (repr === 'full' || repr === 'cylinders') {
        try {
          const proteinData = await api.getInstanceProteinGeometry(instId)
          entry.proteinTraceRenderer?.dispose()
          if (proteinData?.atoms?.length) {
            const trace = initProteinTraceRenderer(entry.group)
            trace.setMode(repr === 'full' ? 'trace' : 'ovoid')
            trace.update(proteinData)
            entry.proteinTraceRenderer = trace
          }
        } catch (err) {
          console.warn(`[assembly_renderer] protein trace fetch failed for ${instId}:`, err)
        }
      }

    } else if (repr === 'hull-prism') {
      // Hull-prism — hide CG beads, build hull meshes from cluster data.
      if (entry.helixCtrl?.root) entry.helixCtrl.root.visible = false
      _disposeHullGroups(entry)
      entry.hullGroups = _buildHullGroupsForDesign(entry.design, entry.helixAxes, entry.group)

    } else if (repr === 'surface') {
      let surfaceData
      try {
        surfaceData = await api.getInstanceSurfaceGeometry(instId)
      } catch (err) {
        console.warn(`[assembly_renderer] surface geometry fetch failed for ${instId}:`, err)
        return
      }
      entry.surfaceRenderer?.dispose()
      if (entry.helixCtrl?.root) entry.helixCtrl.root.visible = false
      const sr = initSurfaceRenderer(entry.group)
      sr.update(surfaceData, 'strand')
      entry.surfaceRenderer = sr
    } else {
      // Atomistic repr ('vdw' | 'ballstick' | 'stick') — fetch geometry and build renderer.
      let atomData
      try {
        atomData = await api.getInstanceAtomisticGeometry(instId)
      } catch (err) {
        console.warn(`[assembly_renderer] atomistic geometry fetch failed for ${instId}:`, err)
        return
      }

      if (entry.atomisticRenderer) {
        entry.atomisticRenderer.dispose()
        entry.atomisticRenderer = null
      }

      // Hide CG geometry — atomistic renderer takes over.
      if (entry.helixCtrl?.root) entry.helixCtrl.root.visible = false

      // Create a per-instance atomistic renderer that adds meshes to the
      // instance group, so they inherit the group's placement transform.
      const ar = initAtomisticRenderer(entry.group)
      ar.update(atomData)
      ar.setMode(repr)
      entry.atomisticRenderer = ar
    }
  }

  /**
   * Build the customColors plain-object from a part Design's strand.color fields.
   * strand.color is "#RRGGBB"; we convert to an integer so nucColor() can use it
   * directly (same format as store.strandColors in the main design view).
   * Strands without an explicit color are left out — they fall back to the
   * internal palette built by buildHelixObjects.
   */
  function _buildCustomColors(design) {
    const colors = {}
    for (const strand of design?.strands ?? []) {
      if (strand.color) colors[strand.id] = parseInt(strand.color.replace(/^#/, ''), 16)
    }
    return colors
  }

  /**
   * Re-skin one cached instance to honor the current global coloringMode.
   * Build paths always produce strand-colored helixCtrls (buildHelixObjects
   * has no coloringMode parameter), so callers that just produced a fresh
   * helixCtrl must call this to catch up the visual.  No-op when mode is
   * 'strand' since the build output already matches.  Pass force=true after
   * a swap when you also need to repaint back to strand explicitly.
   */
  function _applyColoringToEntry(entry, { force = false } = {}) {
    if (!entry?.helixCtrl?.applyColoring) return
    const mode = store.getState().coloringMode || 'strand'
    if (!force && mode === 'strand') return
    const customColors = _buildCustomColors(entry.design)
    entry.helixCtrl.applyColoring(mode, entry.design, customColors, new Set())
    _applyXoverColoringToEntry(entry, mode)
  }

  /**
   * Re-skin crossover arc lines + extra-base bead/slab meshes for one instance
   * according to `mode`.  'overhang-only' dims non-overhang crossovers to gray;
   * an arc is overhang when either endpoint nuc has overhang_id != null.  All
   * other modes restore build-time strand colors stored on each arc/connection.
   */
  function _applyXoverColoringToEntry(entry, mode) {
    const ovhgOnly = (mode === 'overhang-only')
    const DIM_GRAY = 0xbbbbbb

    // ── Arc LineSegments (one merged buffer per strand-type per instance) ──
    const lines = entry?.arcGroup?.userData?.arcLines
      ?? entry?.arcGroup?.children
      ?? []
    const _tc = new THREE.Color()
    for (const line of lines) {
      const conns = line.userData?.arcConnections
      const colorsAttr = line.geometry?.attributes?.color
      if (!conns || !colorsAttr) continue
      const colors = colorsAttr.array
      for (let a = 0; a < conns.length; a++) {
        const c = conns[a]
        const isOvhg = (c.fromNuc?.overhang_id != null) || (c.toNuc?.overhang_id != null)
        const hex = (ovhgOnly && !isOvhg) ? DIM_GRAY : (c.color ?? 0x00ccff)
        _tc.setHex(hex)
        const base = a * (_ARC_SEGS + 1)
        for (let v = 0; v <= _ARC_SEGS; v++) {
          const ci = (base + v) * 3
          colors[ci] = _tc.r; colors[ci + 1] = _tc.g; colors[ci + 2] = _tc.b
        }
      }
      colorsAttr.needsUpdate = true
    }

    // ── Extra-base bead + slab InstancedMesh ─────────────────────────────────
    const xr = entry?.xoverResult
    if (xr?.arcData && xr.beadsMesh && xr.slabsMesh) {
      for (const ad of xr.arcData) {
        const isOvhg = (ad.nucA?.overhang_id != null) || (ad.nucB?.overhang_id != null)
        const bc = (ovhgOnly && !isOvhg) ? DIM_GRAY : ad.beadBaseColor
        const sc = (ovhgOnly && !isOvhg) ? DIM_GRAY : ad.slabBaseColor
        for (let i = 0; i < ad.beadCount; i++) {
          const idx = ad.beadStartIdx + i
          xr.beadsMesh.setColorAt(idx, _tc.setHex(bc))
          xr.slabsMesh.setColorAt(idx, _tc.setHex(sc))
          xr.slabConnMesh?.setColorAt(idx, _tc.setHex(sc))
        }
      }
      if (xr.beadsMesh.instanceColor) xr.beadsMesh.instanceColor.needsUpdate = true
      if (xr.slabsMesh.instanceColor) xr.slabsMesh.instanceColor.needsUpdate = true
      if (xr.slabConnMesh?.instanceColor) xr.slabConnMesh.instanceColor.needsUpdate = true
    }
  }

  /** Cheap string key to detect source changes without deep-comparing designs. */
  function _sourceKey(inst) {
    if (!inst?.source) return 'none'
    const overridesKey = JSON.stringify(inst.cluster_transform_overrides ?? [])
    if (inst.source.type === 'file') return `file:${inst.source.path ?? ''}:ct:${overridesKey}`
    // inline: use embedded design id — changes if user swaps the design
    return `inline:${inst.source.design?.id ?? ''}:ct:${overridesKey}`
  }

  /**
   * Apply a row-major Mat4x4 to a THREE.Group whose matrixAutoUpdate is false.
   * Three.js Matrix4.fromArray() reads column-major, so we transpose afterward
   * to reinterpret the array as row-major.
   */
  function _applyTransform(group, transformValues) {
    const m = new THREE.Matrix4()
    if (transformValues?.length === 16) {
      m.fromArray(transformValues)
      m.transpose()
    }
    group.matrix.copy(m)
    group.matrixWorldNeedsUpdate = true
  }

  // ── Box-helper management ─────────────────────────────────────────────────

  /**
   * Compute the world-space AABB of a group that may contain InstancedMesh.
   * THREE.Box3.setFromObject() only reads the template geometry for InstancedMesh
   * (ignoring per-instance matrices), so we must iterate instance matrices manually.
   *
   * Visibility: walks the parent chain up to (but not including) `group.parent`.
   * Skipping only the leaf's `.visible` flag would incorrectly include geometry
   * whose ancestor group is hidden (e.g. curved-cyl TubeGeometry meshes whose
   * parent `_curvedCylGroup` is `visible=false` in the straight LOD).
   *
   * Empty InstancedMesh: when `count === 0` the mesh draws nothing, but it is
   * still `isMesh`-true, so naive code falls through and unions the TEMPLATE
   * geometry box (e.g. an un-positioned fluorophore at the instance origin).
   * We bail explicitly in that case.
   */
  function _isVisibleUnder(obj, stopAt) {
    let cur = obj
    while (cur && cur !== stopAt) {
      if (cur.visible === false) return false
      cur = cur.parent
    }
    return true
  }

  function _computeGroupBox(group) {
    const box = new THREE.Box3()
    const stopAt = group.parent
    group.traverse(obj => {
      if (!_isVisibleUnder(obj, stopAt)) return
      if (obj instanceof THREE.InstancedMesh) {
        if (obj.count === 0) return   // empty — never fall through to the template-bbox branch
        if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox()
        const baseBox = obj.geometry.boundingBox
        for (let i = 0; i < obj.count; i++) {
          obj.getMatrixAt(i, _instanceMat)
          // Skip instances with uninitialized (all-zero) matrices — the default
          // Float32Array for a new InstancedMesh is zero, not identity, and
          // applyMatrix4(zeroMatrix) produces NaN coords that corrupt the box.
          if (_instanceMat.elements[15] < 0.5) continue
          _instanceMat.premultiply(obj.matrixWorld)
          _instanceBox.copy(baseBox).applyMatrix4(_instanceMat)
          box.union(_instanceBox)
        }
      } else if (obj.isMesh && !obj.userData.skipBounds) {
        if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox()
        _instanceBox.copy(obj.geometry.boundingBox).applyMatrix4(obj.matrixWorld)
        box.union(_instanceBox)
      }
    })
    return box
  }

  function _attachBoxHelper(group) {
    if (_boxHelper) {
      scene.remove(_boxHelper)
      _boxHelper.geometry?.dispose()
      _boxHelper.material?.dispose()
      _boxHelper = null
      _boxHelperGroup = null
    }
    if (!group) return
    group.updateMatrixWorld(true)
    const box = _computeGroupBox(group)
    if (box.isEmpty()) return
    _boxHelper = new THREE.Box3Helper(box, 0xffffff)
    // The selection-outline BoxHelper is an annotation overlay; suppress
    // it in photo mode so the user's publication render stays clean.
    _boxHelper.visible = !_photoMode
    scene.add(_boxHelper)
    _boxHelperGroup = group
  }

  // ── Public: setLiveTransform ──────────────────────────────────────────────

  function setLiveTransform(instanceId, matrix4) {
    const entry = _cache.get(instanceId)
    if (!entry) return
    entry.group.matrix.copy(matrix4)
    entry.group.matrixWorldNeedsUpdate = true
  }

  function getLiveTransform(instanceId) {
    const entry = _cache.get(instanceId)
    if (!entry) return null
    entry.group.updateMatrixWorld(true)
    return entry.group.matrixWorld.clone()
  }

  function getInstanceDesign(instanceId) {
    return _cache.get(instanceId)?.design ?? null
  }

  /**
   * Return the cached render data (design, nucleotides, group) for an instance,
   * or null if the instance hasn't been rendered yet. Used by overhang-locations
   * to build per-instance arrows in the instance's local frame.
   */
  function getInstanceRenderData(instanceId) {
    const entry = _cache.get(instanceId)
    if (!entry) return null
    return {
      design:      entry.design ?? null,
      nucleotides: entry.nucleotides ?? null,
      group:       entry.group ?? null,
    }
  }

  function captureInstanceClusterBase(instanceId, cluster) {
    const entry = _cache.get(instanceId)
    if (!entry || !cluster) return
    entry.helixCtrl?.captureClusterBase(
      cluster.helix_ids,
      cluster.domain_ids?.length ? cluster.domain_ids : null,
    )
  }

  function applyInstanceClusterTransform(instanceId, cluster, centerVec, dummyPosVec, incrRotQuat) {
    const entry = _cache.get(instanceId)
    if (!entry || !cluster) return
    entry.helixCtrl?.applyClusterTransform(
      cluster.helix_ids,
      centerVec,
      dummyPosVec,
      incrRotQuat,
      cluster.domain_ids?.length ? cluster.domain_ids : null,
    )
    _updateInstanceCrossoverArcs(entry)
    _updateInstanceExtraBaseCrossovers(entry)
  }

  /**
   * Pick the cluster whose beads are at (or nearest to) the click position.
   *
   * opts.scopeInstId  — limit fallback search to this instance (pass when the
   *                     calling instance is already known to avoid false picks
   *                     from overlapping parts).
   * opts.threshold    — NDC-space radius for the nearest-bead fallback (default
   *                     0.06, roughly 50–60 px on a typical viewport).
   */
  function pickInstanceCluster(ndc, camera, { scopeInstId = null, threshold = 0.06 } = {}) {
    if (!_cache.size) return null

    // ── Exact raycast pass ────────────────────────────────────────────────────
    _rc.setFromCamera(ndc, camera)
    const groups = []
    for (const entry of _cache.values()) {
      if (entry.group.visible) groups.push(entry.group)
    }
    const hits = _rc.intersectObjects(groups, true)
    for (const hit of hits) {
      let obj = hit.object
      let instId = null
      while (obj) {
        if (obj.userData.assemblyInstance) {
          instId = obj.userData.assemblyInstance
          break
        }
        obj = obj.parent
      }
      if (!instId) continue
      const entry = _cache.get(instId)
      const bead = entry?.helixCtrl?.backboneEntries?.find(be =>
        be.instMesh === hit.object && be.id === hit.instanceId)
      if (!entry || !bead) continue
      const clusters = entry.design?.cluster_transforms ?? []
      const joints = entry.design?.cluster_joints ?? []
      for (const joint of joints) {
        const cluster = clusters.find(c => c.id === joint.cluster_id)
        const filter = _clusterMemberFilter(cluster, entry.design)
        if (filter?.(bead.nuc)) {
          const assembly = store.getState().currentAssembly
          const inst = assembly?.instances?.find(i => i.id === instId)
          return { inst, design: entry.design, cluster, joint, entry: bead }
        }
      }
    }

    // ── Nearest-bead fallback ─────────────────────────────────────────────────
    // When no bead was hit exactly, find the cluster with the closest projected
    // bead within `threshold` NDC units of the click.
    const assembly = store.getState().currentAssembly
    const checkIds = scopeInstId ? [scopeInstId] : [..._cache.keys()]
    let bestDist   = threshold
    let bestResult = null
    const _proj    = new THREE.Vector3()

    for (const instId of checkIds) {
      const entry = _cache.get(instId)
      if (!entry?.group.visible) continue
      entry.group.updateMatrixWorld(true)
      const mw   = entry.group.matrixWorld
      const inst = assembly?.instances?.find(i => i.id === instId)
      if (!inst) continue

      const clusters = entry.design?.cluster_transforms ?? []
      const joints   = entry.design?.cluster_joints ?? []

      for (const joint of joints) {
        const cluster = clusters.find(c => c.id === joint.cluster_id)
        const filter  = _clusterMemberFilter(cluster, entry.design)
        if (!filter) continue

        for (const bead of (entry.helixCtrl?.backboneEntries ?? [])) {
          if (!filter(bead.nuc)) continue
          _proj.copy(bead.pos).applyMatrix4(mw).project(camera)
          const d = Math.hypot(_proj.x - ndc.x, _proj.y - ndc.y)
          if (d < bestDist) {
            bestDist   = d
            bestResult = { inst, design: entry.design, cluster, joint, entry: bead }
          }
        }
      }
    }

    return bestResult
  }

  // ── Public: setActiveInstance ─────────────────────────────────────────────

  function setActiveInstance(id) {
    _activeInstanceId = id ?? null
    _attachBoxHelper(id ? (_cache.get(id)?.group ?? null) : null)
    _rebuildPartJointIndicators()
  }

  // ── PartGroup visibility overlay ──────────────────────────────────────────
  // Hide every cached instance group whose id is in `hiddenInstanceIds`,
  // restore the others to their per-instance `visible` flag. Cheap O(N)
  // walk over the cache — call after each group visibility toggle.
  function applyGroupVisibilityOverlay(hiddenInstanceIds) {
    const next = new Set(hiddenInstanceIds || [])
    _groupHiddenInstanceIds = next
    const instances = store.getState().currentAssembly?.instances ?? []
    const instById = new Map(instances.map(i => [i.id, i]))
    for (const [id, entry] of _cache) {
      const inst = instById.get(id)
      const baseVisible = inst ? inst.visible !== false : true
      entry.group.visible = _externallyVisible && baseVisible && !next.has(id)
    }
  }

  let _externallyVisible = true

  /** Hide/restore the complete native assembly without mutating authored visibility. */
  function setVisible(visible) {
    _externallyVisible = !!visible
    _linkerGroup.visible = _externallyVisible
    applyGroupVisibilityOverlay(_groupHiddenInstanceIds)
  }

  function pickPartJoint(ndc, camera) {
    if (!_partJointMeshes.size) return null
    _rc.setFromCamera(ndc, camera)
    const rings = []
    for (const grp of _partJointMeshes.values()) {
      grp.traverse(obj => { if (obj.userData.isPartJointRing) rings.push(obj) })
    }
    const hits = _rc.intersectObjects(rings, false)
    if (!hits.length) return null
    const meta = hits[0].object.userData.partJoint
    const entry = _cache.get(meta.instanceId)
    const inst = store.getState().currentAssembly?.instances?.find(i => i.id === meta.instanceId)
    const joint = entry?.design?.cluster_joints?.find(j => j.id === meta.jointId)
    const cluster = entry?.design?.cluster_transforms?.find(c => c.id === meta.clusterId)
    return inst && joint && cluster ? { inst, design: entry.design, joint, cluster } : null
  }

  // ── Public: rebuild ───────────────────────────────────────────────────────

  async function rebuild(assembly, { onProgress } = {}) {
    if (!assembly) { dispose(); return }

    const instances  = assembly.instances ?? []
    const currentIds = new Set(instances.map(i => i.id))

    // Remove groups for instances no longer in the assembly
    for (const [id, entry] of _cache) {
      if (!currentIds.has(id)) {
        _disposeGroup(entry)
        _cache.delete(id)
      }
    }

    // Separate instances into:
    //   - transform-only or repr-only changes (fast path: no fetch needed)
    //   - geometry changes (need batch fetch)
    const needsGeometry = []
    for (const inst of instances) {
      const transformKey = JSON.stringify(inst.transform?.values ?? null)
      const sourceKey    = _sourceKey(inst)
      const reprKey      = inst.representation ?? 'full'
      const existing     = _cache.get(inst.id)

      if (existing) {
        if (existing.sourceKey === sourceKey) {
          // Fast path: only transform changed
          if (existing.transformKey !== transformKey) {
            _applyTransform(existing.group, inst.transform?.values)
            existing.transformKey = transformKey
            _instTransformCache.set(inst.id, inst.transform?.values ?? null)
            if (_boxHelperGroup === existing.group) _attachBoxHelper(existing.group)
          }
          // Fast path: only representation changed
          if (existing.reprKey !== reprKey) {
            existing.reprKey = reprKey
            _applyRepresentation(existing, inst.id, reprKey)
          }
          existing.group.visible = (inst.visible !== false) && !_groupHiddenInstanceIds.has(inst.id)
          continue
        }
      }

      // Invisible instances that don't exist yet can be deferred — same
      // applies when a PartGroup overlay has hidden the instance.
      if ((!inst.visible || _groupHiddenInstanceIds.has(inst.id)) && !existing) continue

      needsGeometry.push(inst)
    }

    // Batch-fetch geometry for all instances that need it (one HTTP request).
    // Only use the batch endpoint when 3+ instances need geometry — for 1–2 it is
    // cheaper to fetch per-instance so the backend only recomputes what changed.
    let batchGeo = null
    if (needsGeometry.length >= 3) {
      onProgress?.({ stage: 'fetching', done: 0, total: needsGeometry.length })
      try {
        batchGeo = await api.getAssemblyGeometry()
        onProgress?.({ stage: 'fetched', done: 0, total: needsGeometry.length })
      } catch (err) {
        console.warn('[assembly_renderer] batch geometry fetch failed:', err)
        onProgress?.({ stage: 'fetch_error', done: 0, total: needsGeometry.length })
        batchGeo = null
      }
    } else if (needsGeometry.length > 0) {
      onProgress?.({ stage: 'fetching', done: 0, total: needsGeometry.length })
    }

    let _builtCount = 0
    for (const inst of needsGeometry) {
      const transformKey = JSON.stringify(inst.transform?.values ?? null)
      const sourceKey    = _sourceKey(inst)
      const existing     = _cache.get(inst.id)

      let geoData, design
      const instError = batchGeo?.instances?.[inst.id]?.error
      const prefetched = inst.source?.type === 'file'
        ? _prefetchedByPath.get(inst.source.path)
        : null
      if (prefetched) {
        // Inline geometry from a recent seek — no fetch needed. Shared
        // across every instance referencing the same file path.
        geoData = {
          nucleotides: prefetched.nucleotides,
          helix_axes:  _axesArrayToMap(prefetched.helixAxes),
        }
        design = prefetched.design ?? null
      } else if (batchGeo?.instances?.[inst.id] && !instError) {
        const entry = batchGeo.instances[inst.id]
        geoData = { nucleotides: entry.nucleotides, helix_axes: _axesArrayToMap(entry.helix_axes) }
        design  = entry.design ?? null
      } else {
        // Per-instance fallback
        try {
          const geo = await api.getInstanceGeometry(inst.id)
          geoData = { nucleotides: geo?.nucleotides, helix_axes: _axesArrayToMap(geo?.helix_axes) }
          design  = geo?.design ?? null
        } catch (err) {
          console.warn(`[assembly_renderer] failed to load instance ${inst.id}:`, err)
          onProgress?.({ stage: 'instance_error', done: ++_builtCount, total: needsGeometry.length, name: inst.name, error: err?.message ?? String(err) })
          continue
        }
      }

      if (!geoData || !design) {
        onProgress?.({ stage: 'instance_error', done: ++_builtCount, total: needsGeometry.length, name: inst.name, error: instError ?? 'no geometry data' })
        continue
      }

      // Dispose old group before rebuilding
      if (existing) {
        _disposeGroup(existing)
        _cache.delete(inst.id)
      }

      // Build instance group
      const instanceGroup = new THREE.Group()
      instanceGroup.userData.assemblyInstance = inst.id
      instanceGroup.matrixAutoUpdate = false
      _applyTransform(instanceGroup, inst.transform?.values)

      const helixAxes    = geoData.helix_axes  ?? null
      const customColors = _buildCustomColors(design)
      const nucleotides  = geoData.nucleotides ?? []
      // Pass the instance's current representation as the build-time LOD so
      // cheap reps don't allocate the bead/cone/slab/fluoro InstancedMesh
      // buffers (which would otherwise waste ~25 MB per heavy-origami
      // instance even when hidden — the source of the 2D polymerize OOM).
      const buildLod     = inst.representation ?? 'full'
      const helixCtrl    = buildHelixObjects(nucleotides, design, instanceGroup, customColors, [], helixAxes, buildLod)

      // Crossover arc lines — straight colored lines in instance-local space.
      // Added to helixCtrl.root so they hide/show with the CG representation.
      const arcGroup = _buildInstanceCrossoverArcs(
        helixCtrl.getCrossHelixConnections(), store.getState().showPeriodicSeamArcs === true,
      )
      if (arcGroup) helixCtrl.root.add(arcGroup)

      // Extra-base bead/slab meshes for crossovers with extra bases.
      const colorMap    = buildStapleColorMap(nucleotides, design)
      const xoverResult = buildCrossoverConnections(design, nucleotides, colorMap, customColors)
      if (xoverResult) helixCtrl.root.add(xoverResult.group)

      const labelGroup = _buildInstanceLabelGroup(design, helixAxes, store.getState().showHelixLabels)
      instanceGroup.add(labelGroup)

      const overhangNameGroup = _buildInstanceOverhangNameGroup(
        design, nucleotides, store.getState().showOverhangNames,
      )
      instanceGroup.add(overhangNameGroup)

      instanceGroup.visible = (inst.visible !== false) && !_groupHiddenInstanceIds.has(inst.id)

      // Remove any orphan group for this instance left by a concurrent rebuild race.
      for (const grp of _allSceneGroups) {
        if (grp.userData.assemblyInstance === inst.id) {
          grp.traverse(o => {
            if (o.geometry && !o.geometry.userData?.shared) o.geometry.dispose()
            if (o.material) {
              const mats = Array.isArray(o.material) ? o.material : [o.material]
              mats.forEach(m => { m.map?.dispose(); m.dispose() })
            }
          })
          scene.remove(grp)
          _allSceneGroups.delete(grp)
        }
      }
      scene.add(instanceGroup)
      _allSceneGroups.add(instanceGroup)

      if (helixAxes) _helixAxesCache.set(inst.id, helixAxes)
      _instTransformCache.set(inst.id, inst.transform?.values ?? null)

      const reprKey = inst.representation ?? 'full'
      const entry   = {
        group: instanceGroup, transformKey, sourceKey, reprKey,
        helixCtrl, atomisticRenderer: null, surfaceRenderer: null,
        proteinTraceRenderer: null, hullGroups: [],
        design, helixAxes, nucleotides, labelGroup, overhangNameGroup, arcGroup, xoverResult,
      }
      _cache.set(inst.id, entry)

      // Carry photo-mode annotation hides onto newly built instances so a
      // polymerize / add-part action mid-photo doesn't surface fresh
      // helix-axis lines and labels.
      if (_photoMode) _applyPhotoModeToEntry(entry, true)

      // Honor the current global coloringMode on this fresh helixCtrl.
      _applyColoringToEntry(entry)

      onProgress?.({ stage: 'instance_built', done: ++_builtCount, total: needsGeometry.length, name: inst.name })

      // Apply representation (async for atomistic — fire-and-forget; CG is synchronous)
      _applyRepresentation(entry, inst.id, reprKey)
    }

    // Restore box helper if active instance group was just rebuilt
    const activeId = store.getState().activeInstanceId
    if (activeId && _cache.has(activeId)) {
      _attachBoxHelper(_cache.get(activeId).group)
    }
    _rebuildPartJointIndicators()
    _fireRebuildComplete()
  }

  // ── Rebuild-complete subscribers ──────────────────────────────────────────
  // Modules that render INTO instance groups (e.g. overhang_locations arrows)
  // need to know when the underlying group has just been re-created, so they
  // can re-parent their geometry. Without this, each rebuild leaves their
  // content orphaned on the old group that's about to be disposed.
  const _onRebuildCompleteCbs = []
  function onRebuildComplete(fn) { _onRebuildCompleteCbs.push(fn) }
  function _fireRebuildComplete() {
    for (const fn of _onRebuildCompleteCbs) {
      try { fn() } catch (e) { console.warn('[assembly_renderer] onRebuildComplete cb threw', e) }
    }
  }

  // ── Public: rebuildLinkers ────────────────────────────────────────────────

  /**
   * Rebuild linker helix meshes and virtual scaffold connection (VSC) lines.
   * Called after rebuild() so that instance helix_axes caches are populated.
   */
  async function rebuildLinkers(assembly) {
    // Linker helix meshes (shared module-level builder; also clears the group).
    await _rebuildLinkerHelices({
      assembly, api, linkerGroup: _linkerGroup, axesToMap: _axesArrayToMap,
    })
    if (!assembly) return

    // ── Virtual scaffold connections — dashed green lines ─────────────────────
    const vscStrands = (assembly.assembly_strands ?? []).filter(s => s.id?.startsWith('__vsc__'))
    for (const strand of vscStrands) {
      if (!strand.notes) continue
      let meta
      try { meta = JSON.parse(strand.notes) } catch (_) { continue }
      if (!meta?.vsc || !meta.src || !meta.dst) continue

      const srcPos = _helixEndWorld(meta.src.inst_id, meta.src.helix_id, meta.src.end)
      const dstPos = _helixEndWorld(meta.dst.inst_id, meta.dst.helix_id, meta.dst.end)
      if (!srcPos || !dstPos) continue

      const geo = new THREE.BufferGeometry().setFromPoints([srcPos, dstPos])
      const mat = new THREE.LineDashedMaterial({
        color: 0x00e676, dashSize: 0.5, gapSize: 0.3, linewidth: 1,
      })
      const line = new THREE.Line(geo, mat)
      line.computeLineDistances()
      line.userData.vscStrandId = strand.id
      _linkerGroup.add(line)
    }
  }

  /**
   * Compute the world-space position of a helix end for a given instance.
   * end: 'start' | 'end'  (corresponding to axis_start / axis_end of the helix)
   */
  function _helixEndWorld(instId, helixId, end) {
    const axes = _helixAxesCache.get(instId)
    if (!axes || !axes[helixId]) return null
    const localPos = end === 'end' ? axes[helixId].end : axes[helixId].start
    if (!localPos) return null

    const tv = _instTransformCache.get(instId)
    const pt = new THREE.Vector3(localPos[0], localPos[1], localPos[2])
    if (tv?.length === 16) {
      // Apply row-major Mat4x4: fromArray reads column-major → transpose
      const mat = new THREE.Matrix4().fromArray(tv).transpose()
      pt.applyMatrix4(mat)
    }
    return pt
  }

  // ── Public: dispose ───────────────────────────────────────────────────────

  function dispose() {
    _clearPartJointIndicators()
    if (_boxHelper) {
      scene.remove(_boxHelper)
      _boxHelper.geometry?.dispose()
      _boxHelper.material?.dispose()
      _boxHelper = null
      _boxHelperGroup = null
    }
    for (const entry of _cache.values()) _disposeGroup(entry)
    _cache.clear()
    // Remove any orphan instance groups not tracked in _cache (from rebuild races).
    for (const grp of _allSceneGroups) {
      grp.traverse(o => {
        if (o.geometry && !o.geometry.userData?.shared) o.geometry.dispose()
        if (o.material) {
          const mats = Array.isArray(o.material) ? o.material : [o.material]
          mats.forEach(m => { m.map?.dispose(); m.dispose() })
        }
      })
      scene.remove(grp)
    }
    _allSceneGroups.clear()
    _helixAxesCache.clear()
    _instTransformCache.clear()
    _bendCentersLocalCache.clear()
    // Clear linker group
    _linkerGroup.traverse(obj => {
      // Skip module-level template geometries shared across instances.
      if (obj.geometry && !obj.geometry.userData?.shared) obj.geometry.dispose()
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
        mats.forEach(m => m.dispose())
      }
    })
    while (_linkerGroup.children.length) _linkerGroup.remove(_linkerGroup.children[0])
  }

  function getBoundingBox() {
    const box = new THREE.Box3()
    for (const entry of _cache.values()) {
      if (entry.group.visible) box.expandByObject(entry.group)
    }
    return box
  }

  /**
   * Debug: dump every Mesh / InstancedMesh contribution to the group's bounding
   * box, sorted by extent. Highlights outliers that don't visually belong (e.g.
   * meshes far from the rest of the part bloating the BoxHelper). Call from
   * console with `window.__nadocBoxAudit(instanceId)` or `window.__nadocBoxAudit()`
   * for the active instance. Returns the same data it logs, for further poking.
   */
  function auditInstanceBox(instanceId = null) {
    const id = instanceId ?? _activeInstanceId
    if (!id) { console.warn('[box-audit] no instance id (none active, none passed)'); return null }
    const entry = _cache.get(id)
    if (!entry) { console.warn('[box-audit] no cached entry for', id); return null }
    entry.group.updateMatrixWorld(true)
    const totalBox = new THREE.Box3()
    const rows = []
    const stopAt = entry.group.parent
    entry.group.traverse(obj => {
      if (!_isVisibleUnder(obj, stopAt)) return
      let kind = null, count = 0
      if (obj instanceof THREE.InstancedMesh) {
        if (obj.count === 0) return   // empty — would otherwise contribute its template box
        kind = 'instanced'; count = obj.count
      } else if (obj.isMesh && !obj.userData.skipBounds) {
        kind = 'mesh'
      }
      if (!kind) return
      const box = new THREE.Box3()
      if (kind === 'instanced') {
        if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox()
        const base = obj.geometry.boundingBox
        for (let i = 0; i < obj.count; i++) {
          obj.getMatrixAt(i, _instanceMat)
          if (_instanceMat.elements[15] < 0.5) continue
          _instanceMat.premultiply(obj.matrixWorld)
          _instanceBox.copy(base).applyMatrix4(_instanceMat)
          box.union(_instanceBox)
        }
      } else {
        if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox()
        _instanceBox.copy(obj.geometry.boundingBox).applyMatrix4(obj.matrixWorld)
        box.copy(_instanceBox)
      }
      if (box.isEmpty()) return
      totalBox.union(box)
      const size = box.getSize(new THREE.Vector3())
      const center = box.getCenter(new THREE.Vector3())
      const chain = []
      let cur = obj.parent
      while (cur && cur !== entry.group.parent) { chain.push(cur.name || `(${cur.type})`); cur = cur.parent }
      rows.push({
        name:    obj.name || `(${obj.type})`,
        kind,
        count,
        skip:    !!obj.userData.skipBounds,
        minX:    +box.min.x.toFixed(2),
        maxX:    +box.max.x.toFixed(2),
        minY:    +box.min.y.toFixed(2),
        maxY:    +box.max.y.toFixed(2),
        minZ:    +box.min.z.toFixed(2),
        maxZ:    +box.max.z.toFixed(2),
        extent:  +Math.max(size.x, size.y, size.z).toFixed(2),
        parents: chain.join(' → '),
        ref:     obj,
      })
    })
    const total = totalBox.getSize(new THREE.Vector3())
    const center = totalBox.getCenter(new THREE.Vector3())
    // Outliers: rows whose box reaches the global min/max along any axis.
    const outliers = []
    const eps = 0.5
    for (const r of rows) {
      const reasons = []
      if (Math.abs(r.minX - totalBox.min.x) < eps) reasons.push(`minX=${r.minX}`)
      if (Math.abs(r.maxX - totalBox.max.x) < eps) reasons.push(`maxX=${r.maxX}`)
      if (Math.abs(r.minY - totalBox.min.y) < eps) reasons.push(`minY=${r.minY}`)
      if (Math.abs(r.maxY - totalBox.max.y) < eps) reasons.push(`maxY=${r.maxY}`)
      if (Math.abs(r.minZ - totalBox.min.z) < eps) reasons.push(`minZ=${r.minZ}`)
      if (Math.abs(r.maxZ - totalBox.max.z) < eps) reasons.push(`maxZ=${r.maxZ}`)
      if (reasons.length) outliers.push({ name: r.name, count: r.count, kind: r.kind, reaches: reasons.join(' '), parents: r.parents })
    }
    rows.sort((a, b) => b.extent - a.extent)
    console.group(`%c[box-audit] instance ${id}`, 'color:#58a6ff;font-weight:bold')
    console.log(`total box: size = ${total.x.toFixed(2)} × ${total.y.toFixed(2)} × ${total.z.toFixed(2)}; center = (${center.x.toFixed(2)}, ${center.y.toFixed(2)}, ${center.z.toFixed(2)})`)
    console.log(`total box: x=[${totalBox.min.x.toFixed(2)}, ${totalBox.max.x.toFixed(2)}]  y=[${totalBox.min.y.toFixed(2)}, ${totalBox.max.y.toFixed(2)}]  z=[${totalBox.min.z.toFixed(2)}, ${totalBox.max.z.toFixed(2)}]`)
    console.log(`%c↓ outliers: rows touching the global min/max (these define the BoxHelper edges)`, 'color:#ff8c00;font-weight:bold')
    console.table(outliers)
    console.log(`↓ full list (${rows.length} rows) sorted by extent`)
    console.table(rows.map(r => ({ ...r, ref: undefined })))
    console.log('rows[] (with .ref) available on returned array')
    console.groupEnd()
    return rows
  }

  /**
   * World-space center + bounding radius for every visible instance.
   * Used by the nav controller to snap the orbit pivot to the nearest part
   * and to gauge fly-mode distance thresholds. Returns `[{id, center, radius}]`.
   */
  function getInstanceCenters() {
    const out = []
    for (const [id, entry] of _cache) {
      if (!entry.group.visible) continue
      entry.group.updateMatrixWorld(true)
      const box = _computeGroupBox(entry.group)
      if (box.isEmpty()) continue
      const center = box.getCenter(new THREE.Vector3())
      const size   = box.getSize(new THREE.Vector3())
      const radius = Math.max(size.x, size.y, size.z) * 0.5
      out.push({ id, center, radius, size })
    }
    return out
  }

  function invalidateInstance(id) {
    if (id === _activeInstanceId) _clearPartJointIndicators()
    const entry = _cache.get(id)
    if (!entry) return
    _disposeGroup(entry)
    _cache.delete(id)
    _helixAxesCache.delete(id)
    _instTransformCache.delete(id)
    _bendCentersLocalCache.delete(id)
  }

  // Pre-fetched geometry stash, consumed by the next rebuild() call.
  // Keyed by file source path so a seek on one instance updates every
  // instance referencing the same .nadoc file in a single rebuild pass
  // without any HTTP roundtrip. Cleared after the rebuild finishes.
  const _prefetchedByPath = new Map()

  /**
   * Apply pre-fetched geometry to every instance with the given file path.
   *
   * Used by the assembly-instance feature-log seek path: the seek endpoint
   * ships ``nucleotides`` + ``helix_axes`` + ``design`` inline, and we feed
   * them straight into rebuild() so no follow-up GET geometry call fires.
   * Without this the watchdog SSE echo triggers a full invalidate+rebuild
   * cycle, re-running the 2-3 s per-instance geometry pipeline on every
   * slider tick.
   *
   * @param {string}  filePath    — the inst.source.path the data belongs to
   * @param {object}  design      — the post-seek Design dict
   * @param {Array}   nucleotides — decoded (non-compact) nucleotide list
   * @param {Array}   helixAxes   — array form, as returned by the endpoint
   */
  async function applyInlineGeometry(filePath, design, nucleotides, helixAxes) {
    const assembly = store?.getState?.()?.currentAssembly
    if (!assembly || !filePath) return
    const affected = (assembly.instances ?? []).filter(
      i => i.source?.type === 'file' && i.source.path === filePath,
    )
    if (!affected.length) return
    // Invalidate each affected instance's cache so the rebuild loop's
    // sourceKey check decides it needs geometry (then finds it in the
    // stash). The file mtime is bumped on every seek; without invalidation
    // the existing sourceKey would still match and the fast path would
    // render stale DNA.
    for (const inst of affected) invalidateInstance(inst.id)
    _prefetchedByPath.set(filePath, { design, nucleotides, helixAxes })
    try { await rebuild(assembly) }
    finally { _prefetchedByPath.delete(filePath) }
  }

  function pickInstance(ndc, camera) {
    if (!_cache.size) return null
    _rc.setFromCamera(ndc, camera)
    const groups = []
    for (const entry of _cache.values()) {
      if (entry.group.visible) groups.push(entry.group)
    }
    const hits = _rc.intersectObjects(groups, true)
    if (!hits.length) return null
    let obj = hits[0].object
    while (obj) {
      if (obj.userData.assemblyInstance) {
        const id = obj.userData.assemblyInstance
        const assembly = store.getState().currentAssembly
        return assembly?.instances?.find(i => i.id === id) ?? null
      }
      obj = obj.parent
    }
    return null
  }

  // Raycast the linker group; return the overhang-connection id under the
  // cursor, or null. Mirrors the shared path's pickLinker (right-click → Relax).
  function pickLinker(ndc, camera) {
    if (!_linkerGroup.children.length) return null
    _rc.setFromCamera(ndc, camera)
    const hits = _rc.intersectObject(_linkerGroup, true)
    if (!hits.length) return null
    for (let o = hits[0].object; o && o !== _linkerGroup; o = o.parent) {
      if (o.userData?.connId) return o.userData.connId
    }
    const nucs = _linkerGroup.userData.linkerNucs ?? []
    const hp = hits[0].point
    let best = null, bestD = Infinity
    for (const n of nucs) {
      const dx = hp.x - n.pos[0], dy = hp.y - n.pos[1], dz = hp.z - n.pos[2]
      const d = dx * dx + dy * dy + dz * dz
      if (d < bestD) { bestD = d; best = n }
    }
    return best?.connId ?? null
  }

  /**
   * Return world-space blunt-end connector data for all visible, cached instances.
   * A blunt end is a free helix endpoint — not touching any other helix in the same design.
   * Each entry has the same shape as a connector in assembly_joint_renderer's _connectorDataMap,
   * plus localPos/localNorm (instance-local frame) for InterfacePoint auto-registration.
   */
  function getInstanceBluntEnds() {
    const assembly = store.getState().currentAssembly
    if (!assembly) return []
    const results = []

    for (const [instId, entry] of _cache) {
      if (!entry.design?.helices?.length) continue
      const inst = assembly.instances?.find(i => i.id === instId)
      if (!inst || inst.visible === false) continue
      const instName  = inst.name ?? instId.slice(0, 6)
      const helixAxes = entry.helixAxes ?? {}
      const tv        = _instTransformCache.get(instId)
      const mat4      = (tv?.length === 16)
        ? new THREE.Matrix4().fromArray(tv).transpose()
        : new THREE.Matrix4()

      for (const be of _computeInstanceBluntEnds(entry.design, helixAxes, mat4, instId, instName)) {
        results.push(be)
      }
    }

    return results
  }

  // Bend center-of-curvature connectors per visible instance for Define-Mate.
  // Fetched lazily from the backend (the math wants ``_frame_at_bp``'s
  // upstream-op composition; reimplementing in JS would be a maintenance
  // trap). Cached per instance; entries are evicted when the instance is
  // invalidated. Returns Array<{... same shape as getInstanceBluntEnds ...,
  // isBendCenter: true, bendIndex, radiusNm}>.
  async function getInstanceBendCenters() {
    const assembly = store.getState().currentAssembly
    if (!assembly) return []
    const instances = (assembly.instances ?? []).filter(i => i.visible !== false)
    const out = []
    await Promise.all(instances.map(async inst => {
      let local = _bendCentersLocalCache.get(inst.id)
      if (!local) {
        try {
          const resp = await api.getInstanceBendCenters(inst.id)
          local = resp?.bend_centers ?? []
          _bendCentersLocalCache.set(inst.id, local)
        } catch { local = [] }
      }
      if (!local.length) return
      const tv = _instTransformCache.get(inst.id)
      const mat4 = (tv?.length === 16)
        ? new THREE.Matrix4().fromArray(tv).transpose()
        : new THREE.Matrix4()
      const instName = inst.name ?? inst.id.slice(0, 6)
      for (const bc of local) {
        out.push(_bendCenterRecordToWorld(bc, mat4, inst.id, instName))
      }
    }))
    return out
  }

  function getConnectorClusterId(instanceId, label) {
    if (!instanceId || !label) return null
    const connector = getInstanceBluntEnds().find(c =>
      c.instanceId === instanceId && c.label === label)
    return connector?.clusterId ?? null
  }

  function getConnectorClusterIds(instanceId, label) {
    if (!instanceId || !label) return []
    const connector = getInstanceBluntEnds().find(c =>
      c.instanceId === instanceId && c.label === label)
    return connector?.clusterIds?.length ? connector.clusterIds : (connector?.clusterId ? [connector.clusterId] : [])
  }

  function getInstanceBackboneEntries(instanceId) {
    const entry = _cache.get(instanceId)
    if (!entry) return { entries: [], matrixWorld: new THREE.Matrix4() }
    entry.group.updateMatrixWorld(true)
    return {
      entries:     entry.helixCtrl?.backboneEntries ?? [],
      matrixWorld: entry.group.matrixWorld.clone(),
    }
  }

  store.subscribe((newState, prevState) => {
    if (newState.showHelixLabels !== prevState.showHelixLabels) {
      for (const entry of _cache.values()) {
        // In photo mode the labels are force-hidden regardless of the
        // toolbar toggle. Don't fight the photo override here.
        if (entry.labelGroup && !_photoMode) {
          entry.labelGroup.visible = newState.showHelixLabels
        }
      }
    }
    if (newState.showOverhangNames !== prevState.showOverhangNames) {
      for (const entry of _cache.values()) {
        if (entry.overhangNameGroup && !_photoMode) {
          entry.overhangNameGroup.visible = newState.showOverhangNames
        }
      }
    }
    if (newState.coloringMode !== prevState.coloringMode) {
      // force=true so switching back to 'strand' re-skins instances that
      // were previously painted by a non-strand mode.
      for (const entry of _cache.values()) _applyColoringToEntry(entry, { force: true })
    }
    if (newState.showPeriodicSeamArcs !== prevState.showPeriodicSeamArcs) {
      const show = newState.showPeriodicSeamArcs === true
      for (const entry of _cache.values()) {
        for (const line of (entry.arcGroup?.userData?.arcLines ?? entry.arcGroup?.children ?? [])) {
          if (line.userData?.isPeriodicSeam) line.visible = show
        }
      }
    }
  })

  /**
   * Apply photo-mode annotation overrides to one cached entry. Idempotent;
   * called both when toggling photo mode globally and when rebuild()
   * creates a new entry while photo mode is active (e.g. user polymerizes
   * mid-photo). When photo mode turns off we restore visibility from the
   * current store toggles instead of forcing them on.
   */
  function _applyPhotoModeToEntry(entry, on) {
    if (!entry) return
    entry.helixCtrl?.setAxisArrowsVisible?.(!on)
    if (entry.labelGroup) {
      entry.labelGroup.visible = on ? false : !!store.getState().showHelixLabels
    }
    if (entry.overhangNameGroup) {
      entry.overhangNameGroup.visible = on ? false : !!store.getState().showOverhangNames
    }
  }

  /**
   * Toggle photo mode. Hides annotation overlays on every cached instance:
   * - per-instance helix axis arrows ('helix axis lines')
   * - helix-id labels + overhang-name sprites
   * - the active-instance BoxHelper (selection outline)
   *
   * The orange joint indicators + mate-mode blunt-end disks rendered by
   * assemblyJointRenderer are toggled separately at the photo-mode entry
   * site through assemblyJointRenderer.setVisible(false).
   */
  function setPhotoMode(on) {
    _photoMode = !!on
    for (const entry of _cache.values()) _applyPhotoModeToEntry(entry, _photoMode)
    if (_boxHelper) _boxHelper.visible = !_photoMode
  }

  /**
   * Return a flat array of {instId, instName, helixId, helixLabel, localPos, worldPos}
   * for every helix-label sprite currently in the scene.  Useful for console debugging.
   * Call after rebuild(); requires the assembly to have been loaded.
   */
  function getLabelTable() {
    const assembly = store.getState().currentAssembly
    const rows = []
    for (const [instId, entry] of _cache) {
      if (!entry.labelGroup) continue
      const instName = assembly?.instances?.find(i => i.id === instId)?.name ?? instId.slice(0, 8)
      for (const child of entry.labelGroup.children) {
        const ud = child.userData
        const worldVec = child.getWorldPosition(new THREE.Vector3())
        rows.push({
          instId,
          instName,
          helixId:    ud.helixId    ?? '?',
          helixLabel: ud.helixLabel ?? '?',
          tag:        ud.tag        ?? '?',
          localPos:   ud.pos?.map(v => +v.toFixed(3)) ?? null,
          worldPos:   worldVec.toArray().map(v => +v.toFixed(3)),
        })
      }
    }
    return rows
  }

  // Per-instance renderer never observed strandColors (assembly strand-color
  // changes were silent on this path historically). The shared path implements
  // a live-update for Phase 3d-A; main.js calls `updateStrandColor` on the
  // assembly renderer regardless of which path is active, so we expose a
  // no-op here to keep the interface uniform.
  function updateStrandColor(/* strandId, hexColor */) { /* no-op — old path repaints via coloringMode subscriber at L1936 */ }
  function updateColoringMode(/* mode */) { /* no-op — old path repaints via coloringMode subscriber at L1936 */ }

  return {
    rebuild,
    rebuildLinkers,
    setActiveInstance,
    setVisible,
    applyGroupVisibilityOverlay,
    setLiveTransform,
    getLiveTransform,
    getInstanceDesign,
    getInstanceRenderData,
    captureInstanceClusterBase,
    applyInstanceClusterTransform,
    pickInstanceCluster,
    pickInstance,
    pickLinker,
    dispose,
    getBoundingBox,
    getInstanceCenters,
    auditInstanceBox,
    invalidateInstance,
    applyInlineGeometry,
    pickPartJoint,
    getInstanceBluntEnds,
    getInstanceBendCenters,
    getConnectorClusterId,
    getConnectorClusterIds,
    getLabelTable,
    getInstanceBackboneEntries,
    setPhotoMode,
    onRebuildComplete,
    updateStrandColor,
    updateColoringMode,
  }
}

/**
 * Factory for the assembly renderer. Returns an object satisfying the
 * AssemblyRenderer interface documented at the top of this file.
 *
 * @param {object} opts
 * @param {THREE.Scene} opts.scene
 * @param {object}      opts.store
 * @param {object}      opts.api
 * @param {boolean}     [opts.useShared=false] — when true, returns the
 *   Phase 3b/3c shared-instancing renderer. When false (default), returns
 *   the existing per-instance renderer via `initAssemblyRenderer`.
 */
export function createAssemblyRenderer(opts) {
  const { scene, store, api, useShared = false } = opts ?? {}
  if (globalThis.__nadocAssemblyDebug) {
    console.debug('[assembly_renderer] useShared=', useShared)
  }
  if (useShared) return _createSharedInstancingRenderer({ scene, store, api })
  return initAssemblyRenderer(scene, store, api)
}
