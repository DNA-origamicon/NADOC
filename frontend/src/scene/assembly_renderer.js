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
import { buildHelixObjects, buildStapleColorMap } from './helix_renderer.js'
import { buildCrossoverConnections, arcControlPoint, updateExtraBaseInstances } from './crossover_connections.js'
import { initAtomisticRenderer } from './atomistic_renderer.js'
import { BDNA_RISE_PER_BP } from '../constants.js'
import {
  buildBundleGeometry, buildPrismGeometry, buildPanelSurface,
  buildSpineSections, buildSweptHullGeometry, buildHullMeshPhong,
  HULL_OPACITY, CROSS_MARGIN, AXIAL_MARGIN, MIN_HC_FACES,
} from './joint_renderer.js'

// Maps representation name → setDetailLevel argument (CG reprs only).
const _CG_LOD = { full: 0, beads: 1, cylinders: 2 }

// bp-texture tile width.  Per-bp matrices and colors are packed into a 2D
// DataTexture of width = 4*W (matrices) or W (colors), height = ceil(N/W).
// At W=256 a single texture row holds 256 bp slots, so even a 65k-bp source
// fits in 256 texture rows — well under WebGL's 16384 MAX_TEXTURE_SIZE.
const _BP_TEX_TILE_W = 256

// Per-instance representation → shared-renderer LOD floor.  Returns the
// MINIMUM bucket an instance may occupy regardless of camera distance:
//   0 — close (bp-detail) ok
//   1 — mid (cylinders) min — cylinders rep never draws bp meshes
//   2 — far (billboard) min — non-CG reprs (vdw/ballstick/surface/hull-prism)
//       aren't yet supported on the shared path, demote to billboard so they
//       stay rendered as a placeholder until that work lands.
function _repToLodCap(repr) {
  if (repr === 'cylinders') return 1
  if (repr === 'full' || repr === 'beads') return 0
  return 2
}

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

// Amber overhang-name labels. Matches overhang_name_overlay.js for the
// per-design popup so the assembly view's overhang labels look identical.
const _OVHG_LABEL_COLOR        = '#f5a623'
const _OVHG_SPRITE_HEIGHT_BASE = 1.5    // nm
const _OVHG_RADIAL_OFFSET      = 0.55   // nm — push outward from backbone

function _makeOverhangNameTexture(text) {
  const fontSize = 64
  const padding  = 16
  const tmp = document.createElement('canvas')
  const tmpCtx = tmp.getContext('2d')
  tmpCtx.font = `bold ${fontSize}px monospace`
  const w = Math.ceil(tmpCtx.measureText(text).width) + padding * 2
  const h = fontSize + padding * 2
  const canvas = document.createElement('canvas')
  canvas.width  = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  ctx.font         = `bold ${fontSize}px monospace`
  ctx.textAlign    = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle    = _OVHG_LABEL_COLOR
  ctx.fillText(text, w / 2, h / 2)
  return new THREE.CanvasTexture(canvas)
}

/**
 * Per-instance sprite group of OverhangSpec.label billboards. Mirrors the
 * per-design overhang_name_overlay so the assembly view shows the same
 * amber labels when the user toggles "Show overhang labels". One sprite per
 * overhang that has a non-empty `label`, positioned at the midpoint nuc of
 * the overhang's domain and offset radially out from the backbone.
 *
 * The group is attached to the instance's local Three.js group, so the
 * PartInstance placement transform applies automatically.
 */
function _buildInstanceOverhangNameGroup(design, nucleotides, showOverhangNames) {
  const group = new THREE.Group()
  group.visible = !!showOverhangNames
  group.name = 'overhangNameLabels'
  if (!design?.overhangs?.length || !nucleotides?.length) return group

  const labelMap = new Map()
  for (const ovhg of design.overhangs) {
    if (ovhg.label) labelMap.set(ovhg.id, ovhg.label)
  }
  if (labelMap.size === 0) return group

  const byOverhang = new Map()
  for (const nuc of nucleotides) {
    if (!nuc.overhang_id) continue
    if (!byOverhang.has(nuc.overhang_id)) byOverhang.set(nuc.overhang_id, [])
    byOverhang.get(nuc.overhang_id).push(nuc)
  }

  for (const [ovhgId, label] of labelMap) {
    const nucs = byOverhang.get(ovhgId)
    if (!nucs?.length) continue
    nucs.sort((a, b) =>
      a.direction === 'FORWARD' ? a.bp_index - b.bp_index : b.bp_index - a.bp_index,
    )
    const mid = nucs[Math.floor(nucs.length / 2)]
    const [x, y, z] = mid.backbone_position

    let ox = 0, oy = 0
    if (mid.base_normal) {
      const [nx, ny] = mid.base_normal
      const len = Math.hypot(nx, ny)
      if (len > 1e-6) {
        ox = (nx / len) * _OVHG_RADIAL_OFFSET
        oy = (ny / len) * _OVHG_RADIAL_OFFSET
      }
    }

    const tex    = _makeOverhangNameTexture(label)
    const aspect = tex.image.width / tex.image.height
    const mat    = new THREE.SpriteMaterial({
      map:         tex,
      depthTest:   false,
      transparent: true,
    })
    const sprite = new THREE.Sprite(mat)
    sprite.scale.set(_OVHG_SPRITE_HEIGHT_BASE * aspect, _OVHG_SPRITE_HEIGHT_BASE, 1)
    sprite.position.set(x + ox, y + oy, z)
    sprite.renderOrder = 12
    sprite.userData.overhangId    = ovhgId
    sprite.userData.overhangLabel = label
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
function _buildInstanceCrossoverArcs(connections) {
  if (!connections?.length) return null

  const scaffoldConns = connections.filter(c => c.fromNuc?.strand_type === 'scaffold')
  const stapleConns   = connections.filter(c => c.fromNuc?.strand_type !== 'scaffold')

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
  if (scaffoldLine) group.add(scaffoldLine)
  if (stapleLine)   group.add(stapleLine)
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
      posA, _xoverCtrl, posB, ad.avgAx, ad.zOffset,
    )
    dirty = true
  }
  if (dirty) {
    if (xr.beadsMesh) xr.beadsMesh.instanceMatrix.needsUpdate = true
    if (xr.slabsMesh) xr.slabsMesh.instanceMatrix.needsUpdate = true
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

function _clusterMemberFilter(cluster, design) {
  if (!cluster?.helix_ids?.length) return null
  if (cluster.domain_ids?.length) {
    const domainKeySet = new Set(cluster.domain_ids.map(d => `${d.strand_id}:${d.domain_index}`))
    const strandMap = new Map((design?.strands ?? []).map(s => [s.id, s]))
    const bridgeHelixIds = new Set()
    for (const dr of cluster.domain_ids) {
      const dom = strandMap.get(dr.strand_id)?.domains?.[dr.domain_index]
      if (dom) bridgeHelixIds.add(dom.helix_id)
    }
    const exclusiveHelixSet = new Set(cluster.helix_ids.filter(hid => !bridgeHelixIds.has(hid)))
    return nuc =>
      domainKeySet.has(`${nuc.strand_id}:${nuc.domain_index}`) ||
      exclusiveHelixSet.has(nuc.helix_id)
  }
  const helixSet = new Set(cluster.helix_ids)
  return nuc => helixSet.has(nuc.helix_id)
}

export function initAssemblyRenderer(scene, store, api) {
  // instId → { group, transformKey, sourceKey, reprKey, helixCtrl, atomisticRenderer,
  //            hullGroups, design, helixAxes }
  const _cache        = new Map()
  let _boxHelper      = null
  let _boxHelperGroup = null   // which group the box helper currently tracks
  let _activeInstanceId = null
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

  // Linker geometry group (linker helices + VSC dashed lines)
  const _linkerGroup = new THREE.Group()
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
    const lod = _CG_LOD[repr]

    // Always dispose previous non-CG renderers when switching away from them.
    if (repr !== 'vdw' && repr !== 'ballstick' && entry.atomisticRenderer) {
      entry.atomisticRenderer.dispose()
      entry.atomisticRenderer = null
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

    } else if (repr === 'hull-prism') {
      // Hull-prism — hide CG beads, build hull meshes from cluster data.
      if (entry.helixCtrl?.root) entry.helixCtrl.root.visible = false
      _disposeHullGroups(entry)
      entry.hullGroups = _buildHullGroupsForDesign(entry.design, entry.helixAxes, entry.group)

    } else {
      // Atomistic repr ('vdw' | 'ballstick') — fetch geometry and build renderer.
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
        }
      }
      if (xr.beadsMesh.instanceColor) xr.beadsMesh.instanceColor.needsUpdate = true
      if (xr.slabsMesh.instanceColor) xr.slabsMesh.instanceColor.needsUpdate = true
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
          existing.group.visible = inst.visible !== false
          continue
        }
      }

      // Invisible instances that don't exist yet can be deferred
      if (!inst.visible && !existing) continue

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
      const arcGroup = _buildInstanceCrossoverArcs(helixCtrl.getCrossHelixConnections())
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

      instanceGroup.visible = inst.visible !== false

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
        helixCtrl, atomisticRenderer: null, hullGroups: [],
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
    // Clear previous linker objects
    _linkerGroup.traverse(obj => {
      // Skip module-level template geometries shared across instances.
      if (obj.geometry && !obj.geometry.userData?.shared) obj.geometry.dispose()
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
        mats.forEach(m => m.dispose())
      }
    })
    while (_linkerGroup.children.length) _linkerGroup.remove(_linkerGroup.children[0])

    if (!assembly) return

    // ── Linker helices — full nucleotide geometry from backend ─────────────────
    // Cross-part linker strands reference world-space alias helices keyed
    // by '<instance_id>::<original_helix_id>'; the backend returns them in
    // `aliased_helices` so the synthetic design used by buildHelixObjects
    // can resolve those domain.helix_id lookups.
    const linkerHelices = assembly.assembly_helices ?? []
    const linkerStrands = assembly.assembly_strands ?? []
    if (linkerHelices.length > 0 || linkerStrands.length > 0) {
      let geoData = null
      try { geoData = await api.getLinkerGeometry() } catch (_) {}
      if (geoData?.nucleotides?.length) {
        const syntheticDesign = {
          helices:    [...linkerHelices, ...(geoData.aliased_helices ?? [])],
          strands:    linkerStrands,
          crossovers: [],
          lattice_type: 'honeycomb',
        }
        buildHelixObjects(
          geoData.nucleotides, syntheticDesign, _linkerGroup, {}, [],
          _axesArrayToMap(geoData.helix_axes),
        )
      }
    }

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
      out.push({ id, center, radius })
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

  /**
   * Return world-space blunt-end connector data for all visible, cached instances.
   * A blunt end is a free helix endpoint — not touching any other helix in the same design.
   * Each entry has the same shape as a connector in assembly_joint_renderer's _connectorDataMap,
   * plus localPos/localNorm (instance-local frame) for InterfacePoint auto-registration.
   */
  function getInstanceBluntEnds() {
    const TOL      = 0.001
    const assembly = store.getState().currentAssembly
    if (!assembly) return []
    const results = []

    for (const [instId, entry] of _cache) {
      if (!entry.design?.helices?.length) continue
      const inst = assembly.instances?.find(i => i.id === instId)
      if (!inst || inst.visible === false) continue
      const instName  = inst.name ?? instId.slice(0, 6)
      const helices   = entry.design.helices
      const helixAxes = entry.helixAxes ?? {}
      const tv        = _instTransformCache.get(instId)
      const mat4      = (tv?.length === 16)
        ? new THREE.Matrix4().fromArray(tv).transpose()
        : new THREE.Matrix4()

      // Build local endpoint positions for all helices
      const localEps = {}
      for (const h of helices) {
        const ax = helixAxes[h.id]
        localEps[h.id] = {
          start: ax
            ? new THREE.Vector3(ax.start[0], ax.start[1], ax.start[2])
            : new THREE.Vector3(h.axis_start.x, h.axis_start.y, h.axis_start.z),
          end: ax
            ? new THREE.Vector3(ax.end[0], ax.end[1], ax.end[2])
            : new THREE.Vector3(h.axis_end.x, h.axis_end.y, h.axis_end.z),
        }
      }

      function _isFree(hId, testPos) {
        for (const h of helices) {
          if (h.id === hId) continue
          const ep = localEps[h.id]
          if (ep.start.distanceTo(testPos) < TOL) return false
          if (ep.end.distanceTo(testPos)   < TOL) return false
        }
        return true
      }

      const helixById = new Map(helices.map(h => [h.id, h]))
      const clusterIdsForHelix = helixId => {
        const clusters = entry.design?.cluster_transforms ?? []
        const jointClusterIds = new Set((entry.design?.cluster_joints ?? []).map(j => j.cluster_id).filter(Boolean))
        return clusters
          .filter(c => c.helix_ids?.includes(helixId))
          .sort((a, b) => {
            const aj = jointClusterIds.has(a.id) ? 0 : 1
            const bj = jointClusterIds.has(b.id) ? 0 : 1
            if (aj !== bj) return aj - bj
            const ad = a.is_default ? 1 : 0
            const bd = b.is_default ? 1 : 0
            if (ad !== bd) return ad - bd
            return (a.helix_ids?.length ?? 0) - (b.helix_ids?.length ?? 0)
          })
          .map(c => c.id)
      }

      function _physLen(h) {
        const ax = helixAxes[h.id]
        let nm
        if (ax) {
          const dx = ax.end[0] - ax.start[0], dy = ax.end[1] - ax.start[1], dz = ax.end[2] - ax.start[2]
          nm = Math.sqrt(dx * dx + dy * dy + dz * dz)
        } else {
          const dx = h.axis_end.x - h.axis_start.x, dy = h.axis_end.y - h.axis_start.y, dz = h.axis_end.z - h.axis_start.z
          nm = Math.sqrt(dx * dx + dy * dy + dz * dz)
        }
        return Math.max(1, Math.round(nm / BDNA_RISE_PER_BP) + 1)
      }

      function _posAlongHelix(h, tFrac) {
        const ax = helixAxes[h.id]
        if (ax?.samples?.length >= 2) {
          const n   = ax.samples.length - 1
          const sf  = tFrac * n
          const si  = Math.min(Math.floor(sf), n - 1)
          const sfr = sf - si
          const sA  = new THREE.Vector3(...ax.samples[si])
          const sB  = new THREE.Vector3(...ax.samples[si + 1])
          return { pos: sA.clone().lerp(sB, sfr), dir: sB.clone().sub(sA).normalize() }
        }
        const start3 = ax ? new THREE.Vector3(...ax.start) : new THREE.Vector3(h.axis_start.x, h.axis_start.y, h.axis_start.z)
        const end3   = ax ? new THREE.Vector3(...ax.end)   : new THREE.Vector3(h.axis_end.x,   h.axis_end.y,   h.axis_end.z)
        return { pos: start3.clone().lerp(end3, tFrac), dir: end3.clone().sub(start3).normalize() }
      }

      // For shared-inline overhang stubs, _apply_ovhg_rotations_to_axes populates
      // ovhgAxes per-domain without updating ax.start/ax.end on the parent stub.
      // Build a lookup from (helixId:bp) → rotated {pos, dir} for both bp endpoints
      // of every per-domain ovhgAx entry, so connector positions use the rotated tip.
      const ovhgBpToPos = new Map()
      for (const [hid, ax] of Object.entries(helixAxes)) {
        if (!ax?.ovhgAxes) continue
        for (const ovhgAx of Object.values(ax.ovhgAxes)) {
          const s3  = new THREE.Vector3(...ovhgAx.start)
          const e3  = new THREE.Vector3(...ovhgAx.end)
          const d   = e3.clone().sub(s3)
          const dl  = d.length()
          const dir = dl > 0.001 ? d.clone().divideScalar(dl) : new THREE.Vector3(0, 1, 0)
          // isBpMin: outward direction at bp_min is -dir (strand exits toward lower bp),
          // at bp_max it is +dir (strand exits toward higher bp).
          ovhgBpToPos.set(`${hid}:${ovhgAx.bp_min}`, { pos: s3, dir, isBpMin: true })
          ovhgBpToPos.set(`${hid}:${ovhgAx.bp_max}`, { pos: e3, dir, isBpMin: false })
        }
      }
      // Patch localEps for stubs whose physical endpoints coincide with an ovhgAx bp endpoint
      for (const h of helices) {
        const ax = helixAxes[h.id]
        if (!ax?.ovhgAxes) continue
        const bpStart = h.bp_start ?? 0
        const bpEnd   = bpStart + _physLen(h) - 1
        const sOvhg = ovhgBpToPos.get(`${h.id}:${bpStart}`)
        const eOvhg = ovhgBpToPos.get(`${h.id}:${bpEnd}`)
        if (sOvhg) localEps[h.id].start = sOvhg.pos.clone()
        if (eOvhg) localEps[h.id].end   = eOvhg.pos.clone()
      }

      for (const h of helices) {
        const ep = localEps[h.id]
        for (const [localPos, isStart] of [[ep.start, true], [ep.end, false]]) {
          if (!_isFree(h.id, localPos)) continue

          const ax = helixAxes[h.id]
          let localAxisDir
          if (ax?.samples?.length >= 2) {
            const n = ax.samples.length
            const s0 = isStart ? ax.samples[0] : ax.samples[n - 2]
            const s1 = isStart ? ax.samples[1] : ax.samples[n - 1]
            localAxisDir = new THREE.Vector3(s1[0] - s0[0], s1[1] - s0[1], s1[2] - s0[2]).normalize()
          } else {
            localAxisDir = ep.end.clone().sub(ep.start).normalize()
          }
          // Outward normal: start → negate (away from helix body), end → along axis
          const localNorm  = isStart ? localAxisDir.clone().negate() : localAxisDir.clone()
          const worldPos   = localPos.clone().applyMatrix4(mat4)
          const worldNorm  = localNorm.clone().transformDirection(mat4).normalize()

          results.push({
            instanceId:   instId,
            instanceName: instName,
            label:        `blunt:${h.id}:${isStart ? 'start' : 'end'}`,
            worldPos:     [worldPos.x,  worldPos.y,  worldPos.z],
            worldNorm:    [worldNorm.x, worldNorm.y, worldNorm.z],
            localPos:     [localPos.x,  localPos.y,  localPos.z],
            localNorm:    [localNorm.x, localNorm.y, localNorm.z],
            clusterId:    clusterIdsForHelix(h.id)[0] ?? null,
            clusterIds:   clusterIdsForHelix(h.id),
            isBluntEnd:   true,
          })
        }
      }

      // ── Interior overhang strand termini ──────────────────────────────────
      const strands      = entry.design.strands ?? []
      const seenInterior = new Set()

      // Coverage map for nick suppression: helixId → Set<bp>
      const _covMap = new Map()
      for (const strand of strands) {
        for (const d of strand.domains ?? []) {
          let s = _covMap.get(d.helix_id)
          if (!s) { s = new Set(); _covMap.set(d.helix_id, s) }
          const lo = Math.min(d.start_bp, d.end_bp)
          const hi = Math.max(d.start_bp, d.end_bp)
          for (let b = lo; b <= hi; b++) s.add(b)
        }
      }

      for (const strand of strands) {
        const checks = [
          { helixId: strand.domains?.[0]?.helix_id, bp: strand.domains?.[0]?.start_bp },
          { helixId: strand.domains?.at(-1)?.helix_id, bp: strand.domains?.at(-1)?.end_bp },
        ]
        for (const { helixId, bp } of checks) {
          if (helixId == null || bp == null) continue
          const h = helixById.get(helixId)
          if (!h) continue
          const key = `${helixId}:${bp}`
          if (seenInterior.has(key)) continue
          const physLen = _physLen(h)
          const localBp = bp - (h.bp_start ?? 0)
          const tArc    = physLen > 1 ? localBp / (physLen - 1) : 0
          if (tArc <= 0 || tArc >= 1) continue
          seenInterior.add(key)
          // Nick suppression: skip if both adjacent bps are covered — no gap between strands.
          const _cov = _covMap.get(helixId)
          if (_cov?.has(bp - 1) && _cov?.has(bp + 1)) continue

          const _ovhgPos = ovhgBpToPos.get(`${helixId}:${bp}`)
          const { pos: localPos, dir: localAxisDir } = _ovhgPos
            ? { pos: _ovhgPos.pos.clone(), dir: _ovhgPos.dir.clone() }
            : _posAlongHelix(h, tArc)
          // At bp_min the free strand exits in -dir (away from helix body toward lower bp);
          // at bp_max it exits in +dir. Matches the isStart convention in the endpoint section.
          const localNorm = (_ovhgPos?.isBpMin) ? localAxisDir.clone().negate() : localAxisDir.clone()
          const worldPos  = localPos.clone().applyMatrix4(mat4)
          const worldNorm = localNorm.clone().transformDirection(mat4).normalize()
          results.push({
            instanceId:   instId,
            instanceName: instName,
            label:        `blunt:${helixId}:bp${bp}`,
            worldPos:     [worldPos.x,  worldPos.y,  worldPos.z],
            worldNorm:    [worldNorm.x, worldNorm.y, worldNorm.z],
            localPos:     [localPos.x,  localPos.y,  localPos.z],
            localNorm:    [localNorm.x, localNorm.y, localNorm.z],
            clusterId:    clusterIdsForHelix(helixId)[0] ?? null,
            clusterIds:   clusterIdsForHelix(helixId),
            isBluntEnd:   true,
          })
        }
      }

      // ── Overhang crossover junctions on the main helix ────────────────────
      const seenXover = new Set()

      for (const strand of strands) {
        const doms = strand.domains ?? []
        for (let i = 0; i < doms.length - 1; i++) {
          const d0 = doms[i], d1 = doms[i + 1]
          if (d0.helix_id === d1.helix_id) continue
          const d0IsOH = d0.overhang_id != null
          const d1IsOH = d1.overhang_id != null
          let mainHelixId = null, crossBp = null
          if (!d0IsOH && d1IsOH) { mainHelixId = d0.helix_id; crossBp = d0.end_bp }
          else if (d0IsOH && !d1IsOH) { mainHelixId = d1.helix_id; crossBp = d1.start_bp }
          if (mainHelixId == null) continue
          const key = `${mainHelixId}:${crossBp}`
          if (seenXover.has(key) || seenInterior.has(key)) continue
          const h = helixById.get(mainHelixId)
          if (!h) continue
          const physLen = _physLen(h)
          const localBp = crossBp - (h.bp_start ?? 0)
          const tX      = physLen > 1 ? localBp / (physLen - 1) : 0
          if (tX < 0 || tX > 1) continue
          seenXover.add(key)

          const { pos: localPos, dir: localAxisDir } = _posAlongHelix(h, tX)
          const localNorm = localAxisDir.clone()
          const worldPos  = localPos.clone().applyMatrix4(mat4)
          const worldNorm = localNorm.clone().transformDirection(mat4).normalize()
          results.push({
            instanceId:   instId,
            instanceName: instName,
            label:        `blunt:${mainHelixId}:bp${crossBp}`,
            worldPos:     [worldPos.x,  worldPos.y,  worldPos.z],
            worldNorm:    [worldNorm.x, worldNorm.y, worldNorm.z],
            localPos:     [localPos.x,  localPos.y,  localPos.z],
            localNorm:    [localNorm.x, localNorm.y, localNorm.z],
            clusterId:    clusterIdsForHelix(mainHelixId)[0] ?? null,
            clusterIds:   clusterIdsForHelix(mainHelixId),
            isBluntEnd:   true,
          })
        }
      }
    }

    return results
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
    setLiveTransform,
    getLiveTransform,
    getInstanceDesign,
    getInstanceRenderData,
    captureInstanceClusterBase,
    applyInstanceClusterTransform,
    pickInstanceCluster,
    pickInstance,
    dispose,
    getBoundingBox,
    getInstanceCenters,
    auditInstanceBox,
    invalidateInstance,
    applyInlineGeometry,
    pickPartJoint,
    getInstanceBluntEnds,
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

// ── Phase 3a seam: factory + shared-instancing stub ─────────────────────────
//
// Public method list — mirrors the `return { … }` object of
// `initAssemblyRenderer` above. When the shared-instancing path lands in
// Phase 3b/3c it MUST expose exactly this set of methods.
const _ASSEMBLY_RENDERER_METHODS = [
  'rebuild',
  'rebuildLinkers',
  'setActiveInstance',
  'setLiveTransform',
  'getLiveTransform',
  'getInstanceDesign',
  'getInstanceRenderData',
  'captureInstanceClusterBase',
  'applyInstanceClusterTransform',
  'pickInstanceCluster',
  'pickInstance',
  'dispose',
  'getBoundingBox',
  'getInstanceCenters',
  'auditInstanceBox',
  'invalidateInstance',
  'applyInlineGeometry',
  'pickPartJoint',
  'getInstanceBluntEnds',
  'getConnectorClusterId',
  'getConnectorClusterIds',
  'getLabelTable',
  'getInstanceBackboneEntries',
  'setPhotoMode',
  'onRebuildComplete',
  'updateStrandColor',
  'updateColoringMode',
]

// Methods that intentionally throw "out of plan scope" on the shared-instancing
// path. Pickers, joint-drag at scale, debug introspection, hull / linker /
// photo paths are deferred until later phases or until the user toggles the
// flag OFF.
/**
 * Methods on the shared-instancing path that aren't implemented yet. Each
 * maps to a default-return factory (called per invocation) so callers get a
 * benign value instead of a thrown error. The shared path is rAF-hot and the
 * old behavior — throw on every call — turned every per-frame call site or
 * pointerdown into a stack trace. Now: silent fallback + one-time console.warn
 * per method name so a developer notices what's missing without spamming.
 *
 * Phase 3d / 3e will replace specific entries with real implementations
 * (visibility / color / joint picking / linker rendering). Until then, the
 * feature degrades gracefully: no linker meshes, no per-instance pick, etc.
 */
const _SHARED_RENDERER_STUB_DEFAULTS = {
  setLiveTransform:               () => undefined,
  getLiveTransform:               () => null,
  pickInstance:                   () => null,
  pickInstanceCluster:            () => null,
  pickPartJoint:                  () => null,
  captureInstanceClusterBase:     () => null,
  applyInstanceClusterTransform:  () => undefined,
  getInstanceDesign:              () => null,
  getInstanceRenderData:          () => null,
  getInstanceBackboneEntries:     () => ({ entries: [], matrixWorld: null }),
  getLabelTable:                  () => [],
  getInstanceBluntEnds:           () => [],
  getConnectorClusterId:          () => null,
  getConnectorClusterIds:         () => [],
  auditInstanceBox:               () => undefined,
  rebuildLinkers:                 () => Promise.resolve(),
  setPhotoMode:                   () => undefined,
}
const _SHARED_RENDERER_STUB_METHODS = new Set(Object.keys(_SHARED_RENDERER_STUB_DEFAULTS))

/**
 * Shared-instancing assembly renderer (Phase 3b + 3c).
 *
 * Architectural shift:
 *  - Old path: one helixCtrl per PartInstance → ~4 InstancedMesh trees per
 *    instance → for 500 copies of one source = ~2000+ draw calls/frame.
 *  - New path: one helixCtrl per UNIQUE SOURCE. Each per-bp InstancedMesh.count
 *    is multiplied by num_instances_of_this_source (e.g. 60000 bp × 500
 *    = 30 M slots, but still ONE draw call per mesh). The vertex shader
 *    composes `world = instTransform[gl_InstanceID / num_bp] × instanceMatrix
 *    × position` by sampling a DataTexture of per-instance transforms.
 *
 * Tradeoffs honoured by this implementation:
 *  - Pickers (raycast / cluster picking) are intentionally not supported at
 *    scale (the per-instance-on-the-cpu data isn't kept). User toggles the
 *    flag OFF if they need to pick.
 *  - applyInlineGeometry → re-derives the affected instances' transforms
 *    and dirties their texture rows.
 *  - invalidateInstance → triggers a full rebuild on the next external
 *    rebuild call (acceptable per the spec).
 *
 * @param {object} opts
 * @param {THREE.Scene} opts.scene
 * @param {object}      opts.store
 * @param {object}      opts.api
 */
function _createSharedInstancingRenderer({ scene, store, api }) {
  // ── Per-source render data ─────────────────────────────────────────────────
  // key  = source_key (mirrors `/assembly/geometry`'s sources map; computed
  //         from PartInstance.source via `_sharedSourceKey`).
  // value = {
  //   helixCtrl,                 // returned by buildHelixObjects (count multiplied)
  //   design,                    // shared Design dict
  //   nucleotides,               // decoded nucleotide list
  //   helixAxes,                 // helix axes dict
  //   numBpPerInstance,          // count divisor used by the shader
  //   instanceIds,               // ordered [id, id, ...] — index = row in texture
  //   instanceIndex,             // id → row index
  //   visibility,                // Float32Array (one per instance, 0 or 1)
  //   xformTex,                  // THREE.DataTexture (4 × N RGBA32F)
  //   xformData,                 // backing Float32Array (4 texels × 4 channels × N)
  //   activeMeshes,              // InstancedMesh[] whose materials carry our uniforms
  //   uActiveIdxUniform,         // shared { value: -1 } object across activeMeshes
  //   dirtyRows,                 // Set<number> of instance indices needing GPU re-upload
  //   instBoundingBox,           // THREE.Box3 (per-source local bbox)
  // }
  const _sources = new Map()

  // id → source_key (lookup for setActiveInstance / applyInlineGeometry)
  const _instToSrc = new Map()

  // Stash for applyInlineGeometry (mirrors the old path)
  const _prefetchedByPath = new Map()

  // Rebuild-complete subscribers (parity with old path).
  const _onRebuildCompleteCbs = []

  // The active instance id — surfaced as a per-source uniform so the shader
  // can brighten the matching instance's slots.
  let _activeInstanceId = null

  // ── Source-key helper (mirror of `_sourceKey` in initAssemblyRenderer) ────
  function _sharedSourceKey(inst) {
    if (!inst?.source) return 'none'
    const ov = JSON.stringify(inst.cluster_transform_overrides ?? [])
    if (inst.source.type === 'file') return `file:${inst.source.path ?? ''}:ct:${ov}`
    return `inline:${inst.source.design?.id ?? ''}:ct:${ov}`
  }

  // ── Transform helper: row-major 16-float → THREE.Matrix4 (column-major) ───
  function _instMat4(values) {
    const m = new THREE.Matrix4()
    if (values?.length === 16) {
      m.fromArray(values)
      m.transpose()
    }
    return m
  }

  // ── Pack a Matrix4 into 16 floats (row-major), write into rowOut ──────────
  // Texture layout: width=4 texels, height=N rows. Texel (j, i) holds
  // (m[i*16 + j*4 + 0..3]) — i.e. row j of instance i's matrix in row-major.
  // The shader reads with `texelFetch(u_instanceXform, ivec2(j, i), 0)` and
  // composes mat4(r0, r1, r2, r3) which in GLSL is COLUMN-major. So when we
  // sample row-major rows and put them into a `mat4()` whose arguments are
  // columns, GLSL produces the TRANSPOSE of what we want. To compensate we
  // store the matrix's COLUMNS as the texel rows. Concretely we want, for a
  // row-major matrix M:
  //   texel(0, i) = column 0 of M = [M[0], M[4], M[8],  M[12]]
  //   texel(1, i) = column 1 of M = [M[1], M[5], M[9],  M[13]]
  //   texel(2, i) = column 2 of M = [M[2], M[6], M[10], M[14]]
  //   texel(3, i) = column 3 of M = [M[3], M[7], M[11], M[15]]
  // Then `mat4(c0, c1, c2, c3)` in GLSL gives us the right matrix.
  function _packMatrixIntoRow(m, rowOut, offset) {
    const e = m.elements  // THREE stores column-major: e[0..3] = col0, etc.
    // Texel 0 = col 0
    rowOut[offset + 0]  = e[0]
    rowOut[offset + 1]  = e[1]
    rowOut[offset + 2]  = e[2]
    rowOut[offset + 3]  = e[3]
    // Texel 1 = col 1
    rowOut[offset + 4]  = e[4]
    rowOut[offset + 5]  = e[5]
    rowOut[offset + 6]  = e[6]
    rowOut[offset + 7]  = e[7]
    // Texel 2 = col 2
    rowOut[offset + 8]  = e[8]
    rowOut[offset + 9]  = e[9]
    rowOut[offset + 10] = e[10]
    rowOut[offset + 11] = e[11]
    // Texel 3 = col 3
    rowOut[offset + 12] = e[12]
    rowOut[offset + 13] = e[13]
    rowOut[offset + 14] = e[14]
    rowOut[offset + 15] = e[15]
  }

  // ── Build / resize a per-source transform texture ─────────────────────────
  // Float32 RGBA, width=4, height=N. One row of texels per instance.
  function _makeXformTexture(N) {
    const w = 4
    const h = Math.max(1, N)
    const data = new Float32Array(w * h * 4)
    const tex = new THREE.DataTexture(
      data, w, h, THREE.RGBAFormat, THREE.FloatType,
    )
    tex.minFilter = THREE.NearestFilter
    tex.magFilter = THREE.NearestFilter
    tex.generateMipmaps = false
    tex.needsUpdate = true
    return { tex, data }
  }

  // ── Shader injection ──────────────────────────────────────────────────────
  // Patch a material's onBeforeCompile so the vertex stage applies BOTH the
  // per-instance source transform (from one per-source DataTexture) AND the
  // per-bp local transform (from one per-mesh DataTexture). Also adds a
  // fragment brightening for the selected instance.
  //
  // Two textures so per-bp matrices are stored ONCE per source (not N tiles):
  //   - u_instanceXform: per-source-instance 4×4 matrix (N rows).
  //   - u_bpXform:       per-bp 4×4 matrix (bp_count rows).
  // World position: `world = instTransform * bpMat * position`. The standard
  // `<project_vertex>` chunk still runs `instanceMatrix * mvPosition`, but
  // we've collapsed `instanceMatrix` to a single identity row via
  // meshPerAttribute (see `_patchSharedMeshes`) so that multiply is a no-op.
  //
  // `numBpPerInstance` is set as a uniform (so the divisor varies per mesh).
  // `u_activeInstanceIdx` is shared so a single `.value = N` write per
  // selection change updates every mesh in the source.
  // `u_bpXform` is PER-MESH (each InstancedMesh has its own bp count and
  // bp matrix set), supplied via `uBpTex` in the uniforms bundle.
  function _attachInstanceShader(material, uniformsBundle, numBpPerInstance) {
    material.onBeforeCompile = (shader) => {
      shader.uniforms.u_instanceXform   = uniformsBundle.uXform
      shader.uniforms.u_numBpPerInstance = { value: numBpPerInstance }
      shader.uniforms.u_activeInstanceIdx = uniformsBundle.uActiveIdx
      shader.uniforms.u_visibilityTex   = uniformsBundle.uVis
      shader.uniforms.u_bpXform         = uniformsBundle.uBpTex
      if (uniformsBundle.hasBpColor) {
        shader.uniforms.u_bpColor = uniformsBundle.uBpColorTex
      }
      // Diagnostic: confirm both vertex-shader replaces actually matched. If
      // `<begin_vertex>` is absent (e.g. material uses a custom shader instead
      // of Three.js's standard chunks), the bp meshes will render at the
      // source origin without per-instance positioning — exactly the symptom
      // we're seeing in dev. One-time log per material kind.
      const hadCommon = shader.vertexShader.includes('#include <common>')
      const hadBeginVertex = shader.vertexShader.includes('#include <begin_vertex>')
      if (!hadCommon || !hadBeginVertex) {
        console.warn(
          `[shared_renderer] shader patch FAILED — material ${material.type ?? '(unknown)'} ` +
          `(name=${material.name ?? '(none)'}) missing chunks: ` +
          `common=${hadCommon} begin_vertex=${hadBeginVertex}. ` +
          `bp mesh will render at source origin without per-instance transforms.`,
        )
      }

      // Vertex: prepend uniform + varying; compose final `transformed` via
      // full chunk replacement of `<begin_vertex>` (option (a) from the
      // chunk spec). `instanceMatrix` is collapsed to identity via
      // meshPerAttribute, so the auto-injection in `<project_vertex>`
      // becomes a no-op without further patching there.
      shader.vertexShader = shader.vertexShader
        .replace(
          '#include <common>',
          `
          #include <common>
          #define BP_TILE_W ${_BP_TEX_TILE_W}
          uniform sampler2D u_instanceXform;
          uniform sampler2D u_visibilityTex;
          uniform sampler2D u_bpXform;
          uniform float u_numBpPerInstance;
          uniform float u_activeInstanceIdx;
          flat varying int v_instanceIdx;
          varying float v_visible;
          ${uniformsBundle.hasBpColor ? 'uniform sampler2D u_bpColor;\n          varying vec3 v_bpColor;' : ''}
          `,
        )
        .replace(
          '#include <begin_vertex>',
          `
          // Compute instance index from the InstancedMesh's gl_InstanceID:
          // every group of u_numBpPerInstance consecutive instances belongs
          // to one source-instance.
          int instanceIdx = int(floor(float(gl_InstanceID) / max(u_numBpPerInstance, 1.0)));
          int bpIdx       = gl_InstanceID - instanceIdx * int(u_numBpPerInstance);
          int bpCol       = bpIdx % BP_TILE_W;
          int bpRow       = bpIdx / BP_TILE_W;
          v_instanceIdx = instanceIdx;
          v_visible = texelFetch(u_visibilityTex, ivec2(0, instanceIdx), 0).r;
          // Per-source instance matrix. 4 RGBA texels (4 floats each) = one
          // mat4. Texture layout: column-major (texel j of row i = column j
          // of matrix i). mat4(c0,c1,c2,c3) is column-major in GLSL.
          mat4 instTransform = mat4(
            texelFetch(u_instanceXform, ivec2(0, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(1, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(2, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(3, instanceIdx), 0)
          );
          // Per-bp local matrix from the 2D-tiled bp texture: bpIdx packs
          // along the row (4 RGBA texels per matrix) and wraps every
          // BP_TILE_W slots to a new row.
          mat4 bpMat = mat4(
            texelFetch(u_bpXform, ivec2(bpCol * 4 + 0, bpRow), 0),
            texelFetch(u_bpXform, ivec2(bpCol * 4 + 1, bpRow), 0),
            texelFetch(u_bpXform, ivec2(bpCol * 4 + 2, bpRow), 0),
            texelFetch(u_bpXform, ivec2(bpCol * 4 + 3, bpRow), 0)
          );
          vec3 transformed = (instTransform * bpMat * vec4(position, 1.0)).xyz;
          ${uniformsBundle.hasBpColor ? 'v_bpColor = texelFetch(u_bpColor, ivec2(bpCol, bpRow), 0).rgb;' : ''}
          `,
        )

      // Fragment: discard if instance is hidden; brighten if active.
      shader.fragmentShader = shader.fragmentShader
        .replace(
          '#include <common>',
          `
          #include <common>
          uniform float u_activeInstanceIdx;
          flat varying int v_instanceIdx;
          varying float v_visible;
          ${uniformsBundle.hasBpColor ? 'varying vec3 v_bpColor;' : ''}
          `,
        )
        .replace(
          '#include <dithering_fragment>',
          `
          if (v_visible < 0.5) discard;
          ${uniformsBundle.hasBpColor ? 'gl_FragColor.rgb *= v_bpColor;' : ''}
          if (u_activeInstanceIdx >= 0.0 && abs(float(v_instanceIdx) - u_activeInstanceIdx) < 0.5) {
            gl_FragColor.rgb = mix(gl_FragColor.rgb, vec3(1.0, 1.0, 1.0), 0.35);
          }
          #include <dithering_fragment>
          `,
        )
    }
    // Each material gets a UNIQUE cache key so Three.js's program cache
    // doesn't make 13 materials share the first material's compiled program.
    // With a static key, only the first material's `onBeforeCompile` ran;
    // the rest had their custom uniforms (`u_bpXform`, etc.) never bound,
    // so their bp meshes rendered as if unpatched (all stacked at the
    // source origin — symptom: "only one hinge visible / only axis lines").
    // material.uuid is unique per material instance and stable for cache.
    const cacheKey = 'sharedInstanced_' + material.uuid
    material.customProgramCacheKey = () => cacheKey
    // Stash the patched shader on userData for future diagnostics (Three.js
    // doesn't auto-stash this for stock materials).
    const userBeforeCompile = material.onBeforeCompile
    material.onBeforeCompile = (shader) => {
      userBeforeCompile(shader)
      material.userData.shader = shader
    }
  }

  // Build a per-mesh "bp transform" DataTexture from the original per-bp
  // instanceMatrix data. Width=4 RGBA texels (one per matrix column),
  // height=bp_count. Texel (j, i) holds column j of the bp-i local matrix.
  // THREE stores `instanceMatrix.array` column-major (consecutive 16 floats
  // per slot are c0|c1|c2|c3), so we can do a direct typed-array copy.
  function _makeBpXformTexture(srcArray, bpCount) {
    // 2D tiling: pack bp slots in a 4*W × ceil(N/W) texture so even sources
    // with > MAX_TEXTURE_SIZE bp slots fit.  Byte layout is preserved because
    // each row holds W bp matrices = 16*W floats, so bp i still lives at
    // float offset i*16 in the underlying typed array.  The shader recovers
    // (col, row) via `ivec2((bpIdx % W) * 4 + col, bpIdx / W)`.
    const tileW = _BP_TEX_TILE_W
    const h = Math.max(1, Math.ceil(bpCount / tileW))
    const texW = 4 * tileW
    const data = new Float32Array(texW * h * 4)  // = 16 * tileW * h floats
    const n = Math.min(srcArray.length, bpCount * 16)
    data.set(srcArray.subarray(0, n), 0)
    const tex = new THREE.DataTexture(
      data, texW, h, THREE.RGBAFormat, THREE.FloatType,
    )
    tex.minFilter = THREE.NearestFilter
    tex.magFilter = THREE.NearestFilter
    tex.generateMipmaps = false
    tex.needsUpdate = true
    return { tex, data }
  }

  // Walk a helixCtrl.root and patch every InstancedMesh's material with the
  // shader. The per-bp local matrices written by `buildHelixObjects` into
  // `instanceMatrix` are EXTRACTED into a per-mesh DataTexture (one bp's
  // matrix per row) and then `instanceMatrix` is collapsed to a single
  // identity row via `meshPerAttribute = mesh.count`. The mesh's `count`
  // is set to `bp_count × num_instances`; `gl_InstanceID` indexes both
  // dimensions, decomposed in the shader as
  //     instanceIdx = gl_InstanceID / bp_count
  //     bpIdx       = gl_InstanceID % bp_count
  // and `world = instTransform[instanceIdx] * bpMat[bpIdx] * position`.
  //
  // Memory: per InstancedMesh, per-bp data is now stored ONCE per source
  // (64 × bp bytes), not N times. At bp=61k, N=500 that's ~4 MB vs ~1.9 GB.
  // Cylinder-LOD meshes built by buildHelixObjects.  At 'full' rep these
  // still get allocated with count=helixCount (for downstream setDetailLevel
  // toggling on the per-instance path) but are invisible.  The shared path
  // serves mid LOD via the dedicated `sharedLodMid` InstancedMesh, so we
  // skip patching these — otherwise close-LOD bucketing would render bp
  // meshes AND cylinders on top of each other (the "Full + Cylinders both
  // render" double-draw + slowdown observed at rep='full').
  const _SKIP_MESH_NAMES = new Set([
    'helixCylinders',
    'overhangCylinders',
    'curvedHelixCylindersProxy',
    'curvedOverhangCylindersProxy',
  ])

  function _patchSharedMeshes(helixCtrl, numInstances, uniformsBundle, activeMeshes, source) {
    if (!helixCtrl?.root) return
    helixCtrl.root.traverse(obj => {
      if (!(obj instanceof THREE.InstancedMesh)) return
      if (_SKIP_MESH_NAMES.has(obj.name)) {
        // Hide outright so the un-patched cylinder mesh doesn't render at
        // its baseCount with stock material at the source origin.
        obj.visible = false
        obj.count = 0
        return
      }
      const baseCount = obj.count
      if (baseCount === 0) return
      const newCount = baseCount * numInstances

      // ── Extract per-bp matrices into a per-mesh DataTexture ──────────────
      const { tex: bpTex, data: bpData } = _makeBpXformTexture(
        obj.instanceMatrix.array, baseCount,
      )

      // ── Collapse `instanceMatrix` to a single identity row ───────────────
      // Three.js's `<project_vertex>` auto-applies `instanceMatrix * mvPosition`
      // when USE_INSTANCING is on. With `meshPerAttribute = mesh.count`, the
      // vertex-attribute divisor is `count`, so every rendered instance reads
      // the SAME single matrix slot. We make that slot identity → no-op.
      const identityArr = new Float32Array(16)
      identityArr[0]  = 1
      identityArr[5]  = 1
      identityArr[10] = 1
      identityArr[15] = 1
      const idAttr = new THREE.InstancedBufferAttribute(identityArr, 16, false, newCount)
      idAttr.setUsage(THREE.StaticDrawUsage)
      obj.instanceMatrix = idAttr
      obj.instanceMatrix.needsUpdate = true

      // ── Extract per-bp colors into a per-mesh DataTexture ──────────────
      // Same pattern as bp matrices: pull the per-bp colors out of
      // instanceColor.array into a 1×bpCount RGBA Float texture so the
      // shader can sample them by bpIdx. Memory: 16 bytes × bpCount per
      // mesh, identical across all source-instances (the strand color
      // pattern is part of the source, not per-instance).
      let bpColorTex = null
      if (obj.instanceColor) {
        const colorArr = obj.instanceColor.array  // bpCount × 3 floats RGB
        // 2D tile layout mirrors _makeBpXformTexture: W texels per row, one
        // RGBA texel per bp.  Each row holds 4*W floats = W bp colors, so
        // bp i still lives at float offset i*4 in the typed array.
        const tileW = _BP_TEX_TILE_W
        const h = Math.max(1, Math.ceil(baseCount / tileW))
        const colorData = new Float32Array(tileW * h * 4)
        for (let i = 0; i < baseCount; i++) {
          colorData[i * 4 + 0] = colorArr[i * 3 + 0]
          colorData[i * 4 + 1] = colorArr[i * 3 + 1]
          colorData[i * 4 + 2] = colorArr[i * 3 + 2]
          colorData[i * 4 + 3] = 1.0
        }
        bpColorTex = new THREE.DataTexture(
          colorData, tileW, h, THREE.RGBAFormat, THREE.FloatType,
        )
        bpColorTex.minFilter = THREE.NearestFilter
        bpColorTex.magFilter = THREE.NearestFilter
        bpColorTex.generateMipmaps = false
        bpColorTex.needsUpdate = true
        obj.instanceColor = null  // drop the tiled buffer; colors live in texture now
      }

      obj.count = newCount

      // Frustum culling reads the geometry's bounding sphere/box only — for
      // an instanced shared source it's wildly wrong. Disable it.
      obj.frustumCulled = false

      // `buildHelixObjects` allocates multiple LOD-specific InstancedMeshes
      // (bead/cone/slab for full; helixCylinders/overhangCylinders for
      // cylinders rep) and relies on a downstream `setDetailLevel(rep)` call
      // to flip `visible` per LOD. The shared path never runs setDetailLevel,
      // so even cylinder rep meshes with valid count stay invisible.
      // Force-enable any mesh that we just sized up — count > 0 here means
      // buildHelixObjects allocated real geometry for it under the requested
      // LOD, so it MUST render.
      obj.visible = true

      // Track-B instrumentation: when window.NADOC_DBG_RENDER_TRACE is true,
      // every shared-renderer InstancedMesh increments a counter via its
      // onBeforeRender callback. `__NADOC_DBG__.traceFrame()` reads + prints
      // the counts plus renderer.info totals so we can SEE whether these
      // meshes are actually being drawn vs silently culled.
      const _prevOnBefore = obj.onBeforeRender
      obj.onBeforeRender = function (renderer, scene, camera, geometry, mat, group) {
        if (_prevOnBefore) _prevOnBefore.call(this, renderer, scene, camera, geometry, mat, group)
        if (typeof window !== 'undefined' && window.NADOC_DBG_RENDER_TRACE) {
          if (!renderer._nadocTrace) renderer._nadocTrace = new Map()
          const id = (obj.name || 'unnamed') + '#' + obj.id
          renderer._nadocTrace.set(id, (renderer._nadocTrace.get(id) || 0) + 1)
        }
      }

      // Attach the per-source + per-mesh uniforms to this material.
      // `uBpTex` is a NEW per-mesh sampler2D pointing at this mesh's bp
      // matrix texture. `uBpColorTex` is the optional per-bp color texture
      // (only present if the original mesh had instanceColor). The other
      // uniforms (xform, vis, active) are shared across the source.
      const uBpTex      = { value: bpTex }
      const uBpColorTex = { value: bpColorTex }  // null when no per-bp colors
      const meshUniforms = {
        uXform:      uniformsBundle.uXform,
        uActiveIdx:  uniformsBundle.uActiveIdx,
        uVis:        uniformsBundle.uVis,
        uBpTex,
        uBpColorTex,
        hasBpColor:  bpColorTex !== null,
      }
      const mat = obj.material
      const mats = Array.isArray(mat) ? mat : [mat]
      for (const m of mats) {
        _attachInstanceShader(m, meshUniforms, baseCount)
      }

      // Stash bp-texture handles on the source's render-data list so
      // `_disposeSource` can release them.
      if (source) {
        source.bpTextures.push(bpTex)
        if (bpColorTex) source.bpTextures.push(bpColorTex)
      }

      // Record bpColorTex/bpColorData on the activeMeshes entry so
      // `updateStrandColor` can rewrite them after a UI color change.
      // bpColorData is the backing Float32Array (baseCount × 4 RGBA floats).
      const bpColorData = bpColorTex ? bpColorTex.image.data : null
      activeMeshes.push({ mesh: obj, baseCount, bpTex, bpData, bpColorTex, bpColorData })
    })
  }

  // ── Local-bbox helper for one source ──────────────────────────────────────
  // Walks the helixCtrl.root and unions every InstancedMesh's per-bp instance
  // matrix into a local AABB. Per-bp matrices are the SAME across all
  // source-instances (only the outer instTransform differs), so we only need
  // to iterate baseCount-many slots.
  function _computeSourceLocalBox(helixCtrl) {
    const out = new THREE.Box3()
    if (!helixCtrl?.root) return out
    const tmpMat = new THREE.Matrix4()
    const tmpBox = new THREE.Box3()
    helixCtrl.root.traverse(obj => {
      if (!(obj instanceof THREE.InstancedMesh)) return
      if (obj.count === 0) return
      if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox()
      const baseBox = obj.geometry.boundingBox
      // baseCount per source-instance — but per-bp slots are pattern-tiled,
      // so iterating any one tile is enough. We assume baseCount = count /
      // num_instances and read it from `userData.sharedBase` set by patching;
      // fallback: read the first `count` slots.
      const baseCount = obj.userData.sharedBase ?? obj.count
      for (let i = 0; i < baseCount; i++) {
        obj.getMatrixAt(i, tmpMat)
        if (tmpMat.elements[15] < 0.5) continue
        tmpBox.copy(baseBox).applyMatrix4(tmpMat)
        out.union(tmpBox)
      }
    })
    return out
  }

  // ── Build one source entry ────────────────────────────────────────────────
  async function _buildSource(srcKey, srcDesignData, instancesForKey) {
    const { nucleotides, helix_axes, design } = srcDesignData
    if (!nucleotides || !design) return null

    // Build at the most-detailed LOD that any instance in this source needs.
    // Per-instance ``representation`` selects which LOD draws via
    // _updateLodForSource's lodCap mapping, but the underlying InstancedMeshes
    // must exist (non-zero count) — _patchSharedMeshes early-returns on
    // count==0 (L2428).  Choosing 'full' indiscriminately would allocate
    // backbone-bead DataTextures of size 1×baseCount per LOD mesh, which
    // overflows WebGL's MAX_TEXTURE_SIZE on large origami sources (~16k+ bp).
    //   Strategy: pick the deepest LOD any instance needs (`full` < `beads` <
    //   `cylinders`), so cylinders-only sources still avoid the bp-texture
    //   cost.  If the source's bp count exceeds GPU texture limits, cap the
    //   build at 'cylinders' regardless of per-instance rep — those instances
    //   will fall to the mid bucket via the LOD cap below.
    let rep = 'cylinders'
    for (const inst of instancesForKey) {
      const r = inst.representation
      if (r === 'full' || r === 'beads') { rep = 'full'; break }
    }
    const numInstances = instancesForKey.length

    // Build a single helixCtrl with the canonical bp matrices.
    const helixGroup = new THREE.Group()
    helixGroup.userData.sharedSource = srcKey
    const customColors = {}
    for (const strand of design.strands ?? []) {
      if (strand.color) customColors[strand.id] = parseInt(strand.color.replace(/^#/, ''), 16)
    }
    const helixCtrl = buildHelixObjects(
      nucleotides, design, helixGroup, customColors, [], helix_axes ?? null, rep,
    )

    // Per-source uniforms (xform texture + active-instance index + visibility).
    const { tex: xformTex,  data: xformData  } = _makeXformTexture(numInstances)
    const { tex: visTex,    data: visData    } = _makeXformTexture(numInstances)
    const uActiveIdx = { value: -1 }
    const uXform     = { value: xformTex }
    const uVis       = { value: visTex }
    const uniformsBundle = { uXform, uActiveIdx, uVis }

    // Tag InstancedMeshes with baseCount BEFORE patching so the bbox walker
    // can find the per-bp tile size after patching multiplies it.
    helixCtrl.root.traverse(obj => {
      if (obj instanceof THREE.InstancedMesh) obj.userData.sharedBase = obj.count
    })

    // Compute per-source local bbox BEFORE we patch (count is still baseCount).
    const instBoundingBox = _computeSourceLocalBox(helixCtrl)

    // Patch shader + collapse InstancedMesh.instanceMatrix + extract per-bp
    // matrices into per-mesh DataTextures. We pass a transient holder so the
    // patch helper can register textures for disposal.
    const activeMeshes = []
    const sourceCollector = { bpTextures: [] }
    _patchSharedMeshes(helixCtrl, numInstances, uniformsBundle, activeMeshes, sourceCollector)

    // ── Memory-savings probe (debug visibility into the per-source budget) ──
    // Compute the byte count of the per-bp DataTextures (NEW) + the
    // per-instance transform texture (also Phase 3c). Compare with what the
    // OLD instanceMatrix-tile path would have cost (16 × baseCount × N × 4
    // per InstancedMesh).
    let bpBytes = 0
    let oldTileBytes = 0
    for (const m of activeMeshes) {
      bpBytes += m.bpData.byteLength
      oldTileBytes += 16 * m.baseCount * numInstances * 4
    }
    const xformBytes = xformData.byteLength + visData.byteLength
    if (typeof console !== 'undefined' && console.info) {
      console.info(
        `[shared_renderer] source=${srcKey} N=${numInstances} ` +
        `bp-texture=${(bpBytes/1024/1024).toFixed(2)} MB, ` +
        `inst-texture=${(xformBytes/1024).toFixed(1)} KB ` +
        `(was ${(oldTileBytes/1024/1024).toFixed(2)} MB tiled in instanceMatrix; ` +
        `saved ${((oldTileBytes - bpBytes)/1024/1024).toFixed(2)} MB)`,
      )
    }

    // Per-instance bookkeeping.
    const instanceIds  = instancesForKey.map(i => i.id)
    const instanceIndex = new Map(instanceIds.map((id, idx) => [id, idx]))
    const visibility = new Float32Array(numInstances)
    // Per-instance LOD cap (Int8: 0 = close ok, 1 = no close, 2 = far only).
    // Read at every _updateLodForSource frame to bias bucketing by the
    // per-instance ``representation`` field.  ``buildRepCap`` floors the
    // cap when the source was built at 'cylinders' (close LOD meshes don't
    // exist) — without it, an instance with rep='full' would still bucket
    // close but find empty bp meshes.
    const buildRepCap = (rep === 'full') ? 0 : 1
    const instanceLodCap = new Int8Array(numInstances)
    // Fill xform + visibility texture data.
    for (let i = 0; i < numInstances; i++) {
      const inst = instancesForKey[i]
      const m = _instMat4(inst.transform?.values)
      _packMatrixIntoRow(m, xformData, i * 16)
      visibility[i] = (inst.visible !== false) ? 1.0 : 0.0
      visData[i * 16 + 0] = visibility[i]
      instanceLodCap[i] = Math.max(buildRepCap, _repToLodCap(inst.representation))
      // Other channels unused; leave zero.
      _instToSrc.set(inst.id, srcKey)
    }
    xformTex.needsUpdate = true
    visTex.needsUpdate   = true

    scene.add(helixGroup)

    const srcEntry = {
      group: helixGroup,
      helixCtrl,
      design,
      nucleotides,
      helixAxes: helix_axes ?? null,
      rep,                    // representation/LOD — needed to re-run buildHelixObjects
      customColors,           // strandId → hex (live, mutated by updateStrandColor)
      numBpPerInstance: 0,    // not used directly — each mesh carries its baseCount in userData
      instanceIds,
      instanceIndex,
      visibility,
      instanceLodCap,
      xformTex,
      xformData,
      visTex,
      visData,
      activeMeshes,
      bpTextures: sourceCollector.bpTextures,
      uActiveIdxUniform: uActiveIdx,
      uXformUniform: uXform,
      uVisUniform: uVis,
      dirtyRows: new Set(),
      dirtyVisRows: new Set(),
      instBoundingBox,
    }

    // ── Phase 3f: build mid-LOD + far-LOD meshes for this source ─────────────
    // Find the legacy iHelixCylinders + iOverhangCylinders meshes that
    // buildHelixObjects populated.  _patchSharedMeshes's skip filter zeroed
    // their `count` but their `instanceMatrix`/`instanceColor` arrays survive
    // (and `userData.sharedBase` retains the original segment counts).
    let legacyOvhgMesh = null
    let legacyHelixCylMesh = null
    helixCtrl.root.traverse(obj => {
      if (!(obj instanceof THREE.InstancedMesh)) return
      if (obj.name === 'overhangCylinders') legacyOvhgMesh = obj
      if (obj.name === 'helixCylinders')    legacyHelixCylMesh = obj
    })
    console.info(
      `[shared_renderer] source=${srcKey} legacy meshes: ` +
      `helix=${legacyHelixCylMesh ? (legacyHelixCylMesh.userData.sharedBase ?? legacyHelixCylMesh.count) : 'missing'} ` +
      `overhang=${legacyOvhgMesh ? (legacyOvhgMesh.userData.sharedBase ?? legacyOvhgMesh.count) : 'missing'}`,
    )

    // Mid LOD: per-strand-domain helix cylinders — matches legacy detail
    // (multiple short cylinders per helix, with gaps where overhangs/nicks
    // fall), not the previous "one continuous cylinder per helix axis"
    // simplification.
    if (legacyHelixCylMesh && (legacyHelixCylMesh.userData.sharedBase ?? 0) > 0) {
      const origCount = legacyHelixCylMesh.userData.sharedBase
      legacyHelixCylMesh.count = origCount
      const midLod = _buildMidLodMesh(srcEntry, legacyHelixCylMesh, helixGroup)
      legacyHelixCylMesh.count = 0
      if (midLod) {
        srcEntry.midLod = midLod
        console.info(`[shared_renderer]   mid LOD built: numSegments=${midLod.numSegments}`)
      } else {
        console.warn('[shared_renderer]   _buildMidLodMesh returned null')
      }
    }

    // Overhang LOD: per-segment half-cylinders for protruding overhangs.
    // Same architecture as mid LOD, just half-cylinder geometry.
    if (legacyOvhgMesh && (legacyOvhgMesh.userData.sharedBase ?? 0) > 0) {
      const origCount = legacyOvhgMesh.userData.sharedBase
      legacyOvhgMesh.count = origCount
      const ovhgLod = _buildOverhangLodMesh(srcEntry, legacyOvhgMesh, helixGroup)
      legacyOvhgMesh.count = 0
      if (ovhgLod) {
        srcEntry.overhangLod = ovhgLod
        console.info(`[shared_renderer]   overhang LOD built: numSegments=${ovhgLod.numSegments}`)
      } else {
        console.warn('[shared_renderer]   _buildOverhangLodMesh returned null')
      }
    }
    // Far LOD: billboard sized to the source's mean half-extent so it
    // approximates the actual silhouette.  Half-diagonal (the prior choice)
    // dramatically over-sizes elongated parts — e.g. a 200 × 5 × 5 hinge
    // has diagonal ≈ 200 but visible cross-section ≈ ~10.  Mean half-side
    // tracks the silhouette better than max-side AND than diagonal.
    const bboxSize = new THREE.Vector3()
    instBoundingBox.getSize(bboxSize)
    const meanHalfSide = (bboxSize.x + bboxSize.y + bboxSize.z) / 6
    const billboardRadius = Math.max(0.5, meanHalfSide)
    const billboardColor = _averageStrandColorRGB(design)
    const farLod = _buildFarLodMesh(srcEntry, billboardRadius, billboardColor, helixGroup)
    if (farLod) srcEntry.farLod = farLod

    // Seed per-helix colours from the current coloringMode.  Pre-per-helix
    // implementation tinted the mid-LOD by an averaged flat colour, which
    // dimmed cylinder rendering (scaffold's dark navy dominated the
    // average).  Now the seed populates a per-helix texture instead, so
    // each cylinder picks up its own strand colour and the legacy
    // per-instance look is preserved on the shared path.
    try { _applyColorsToSource(srcEntry, null) }
    catch (err) { console.warn('[shared_renderer] initial colour seed failed:', err) }

    return srcEntry
  }

  // ── Dispose one source entry ──────────────────────────────────────────────
  function _disposeSource(srcEntry) {
    if (!srcEntry) return
    srcEntry.group.traverse(obj => {
      if (obj.geometry && !obj.geometry.userData?.shared) obj.geometry.dispose()
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
        mats.forEach(m => m.dispose())
      }
    })
    scene.remove(srcEntry.group)
    srcEntry.xformTex?.dispose()
    srcEntry.visTex?.dispose()
    if (srcEntry.bpTextures) {
      for (const t of srcEntry.bpTextures) t.dispose()
    }
    // Phase 3f — release per-source LOD textures (mid-LOD per-segment
    // matrix + colour textures, plus the same pair for overhang LOD; far-
    // LOD has no extra texture beyond xformTex which is released above).
    srcEntry.midLod?.segXformTex?.dispose()
    srcEntry.midLod?.segColorTex?.dispose()
    srcEntry.overhangLod?.segXformTex?.dispose()
    srcEntry.overhangLod?.segColorTex?.dispose()
    for (const id of srcEntry.instanceIds) _instToSrc.delete(id)
  }

  // ╔══════════════════════════════════════════════════════════════════════════╗
  // ║  Phase 3f — three-tier LOD ladder                                        ║
  // ║                                                                          ║
  // ║  Per source, the close-LOD path (already in place above) is augmented   ║
  // ║  by two additional InstancedMesh sets that share the same per-source    ║
  // ║  `xformTex` (per-instance world transforms):                             ║
  // ║                                                                          ║
  // ║    • Mid LOD  — one unit-cylinder InstancedMesh.                         ║
  // ║                 count = numHelices × numInstances.                       ║
  // ║                 Pre-baked per-helix transform stored in a per-source     ║
  // ║                 `helixXformTex` (4 RGBA texels × numHelices rows).       ║
  // ║                 Shader composes  world = instTransform × helixCylMat ×   ║
  // ║                 position. `gl_InstanceID` decomposes as                  ║
  // ║                   instanceIdx = gl_InstanceID / numHelices              ║
  // ║                   helixIdx    = gl_InstanceID % numHelices              ║
  // ║                                                                          ║
  // ║    • Far LOD — one quad InstancedMesh.                                   ║
  // ║                 count = numInstances. Vertex shader reads the instance   ║
  // ║                 transform's translation column from u_instanceXform and  ║
  // ║                 expands the quad as a camera-facing billboard sized to   ║
  // ║                 the source bbox radius.                                  ║
  // ║                                                                          ║
  // ║  Each frame, `_updateLod(camera)` runs ONCE per source (hooked via       ║
  // ║  `onBeforeRender` on one mesh per source) and:                           ║
  // ║    1. counts how many instances fall into close / mid / far buckets;    ║
  // ║    2. sets each LOD InstancedMesh's `.count` to that bucket size ×       ║
  // ║       per-LOD multiplier;                                                ║
  // ║    3. sets `.visible = true` on any mesh whose count > 0.                ║
  // ║                                                                          ║
  // ║  STAGE 2 (sort-to-front) shipped: each frame, instances are SORTED by    ║
  // ║  camera distance and the per-source `xformTex` + `visTex` are PERMUTED   ║
  // ║  so row 0 holds the nearest visible instance, row 1 the next-nearest,    ║
  // ║  etc. Then bucket counts (N_close × baseCount on close-LOD InstancedMesh,║
  // ║  N_mid × numHelices on mid, N_far on far) are written to `mesh.count`.   ║
  // ║  Because rows 0..N_close-1 are now the actually-nearest, the close-LOD   ║
  // ║  mesh's first N_close slots render the actually-nearest N_close          ║
  // ║  instances.                                                              ║
  // ║                                                                          ║
  // ║  `srcEntry.instanceIds` and `srcEntry.instanceIndex` are kept in sync    ║
  // ║  with the permutation: `instanceIds[row]` always names the instance      ║
  // ║  currently at that row, and `instanceIndex.get(id)` returns the CURRENT  ║
  // ║  row of `id`. Any external API that today writes by stable insertion-    ║
  // ║  order index MUST look up the live row via `instanceIndex.get(id)`.     ║
  // ║  `setActiveInstance` does this lookup; `applyInlineGeometry` rebuilds.   ║
  // ║  `getInstanceCenters` / `getBoundingBox` iterate `instanceIds` so they   ║
  // ║  stay correct regardless of row order.                                   ║
  // ║                                                                          ║
  // ║  Per-frame cost at N=200: ~50 µs sort + ~30 µs full texture re-upload.   ║
  // ║  Negligible at this scale. (If profiling later shows dominance, switch   ║
  // ║  to partial `texSubImage2D` for changed rows only.)                      ║
  // ╚══════════════════════════════════════════════════════════════════════════╝

  // Default thresholds in scene units (nm). Calibrated for typical assemblies
  // — a ~30-nm origami source's bbox ≈ 30 nm wide, polymerized chain ≈
  // hundreds of nm long. close < 100 nm catches what's filling the viewport;
  // mid < 500 nm picks up most of an extended chain; far is everything else.
  // Angular-size LOD thresholds in screen-pixels.  Bucketing reads the
  // source's local bbox diagonal, projects it to screen-space using the
  // camera's vertical FoV + viewport height, and compares to these pixel
  // thresholds:
  //   instance pixel size >= _lodClosePx → close (bp detail)
  //   instance pixel size >= _lodFarPx   → mid (cylinder)
  //   instance pixel size <  _lodFarPx   → far (billboard)
  let _lodClosePx = 60.0
  let _lodFarPx   = 8.0

  function setLodThresholds(opts) {
    if (typeof opts?.closePx === 'number') _lodClosePx = opts.closePx
    if (typeof opts?.farPx   === 'number') _lodFarPx   = opts.farPx
  }

  // ── Mid-LOD: per-helix transform texture ─────────────────────────────────
  // Same column-major layout as the per-source xformTex: width = 4 texels,
  // height = numHelices. Each row holds one mat4 (columns as texels).
  function _makeHelixXformTexture(helixIds, helix_axes) {
    const n = helixIds.length
    const w = 4
    const h = Math.max(1, n)
    const data = new Float32Array(w * h * 4)  // 16 floats per helix
    const tmpM = new THREE.Matrix4()
    const tmpQ = new THREE.Quaternion()
    const tmpV = new THREE.Vector3()
    const tmpS = new THREE.Vector3()
    const yAxis = new THREE.Vector3(0, 1, 0)
    const dirV  = new THREE.Vector3()
    const HELIX_CYL_RADIUS = 1.0  // nm — matches the cylinder LOD rendering
    for (let i = 0; i < n; i++) {
      const ax = helix_axes?.[helixIds[i]]
      if (!ax || !ax.start || !ax.end) {
        // No axis: write a degenerate (zero-scale) matrix. Renders nothing.
        for (let k = 0; k < 16; k++) data[i * 16 + k] = 0
        continue
      }
      const sx = ax.start[0], sy = ax.start[1], sz = ax.start[2]
      const ex = ax.end[0],   ey = ax.end[1],   ez = ax.end[2]
      const dx = ex - sx, dy = ey - sy, dz = ez - sz
      const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
      if (len < 1e-6) {
        for (let k = 0; k < 16; k++) data[i * 16 + k] = 0
        continue
      }
      tmpV.set((sx + ex) * 0.5, (sy + ey) * 0.5, (sz + ez) * 0.5)
      dirV.set(dx / len, dy / len, dz / len)
      tmpQ.setFromUnitVectors(yAxis, dirV)
      tmpS.set(HELIX_CYL_RADIUS, len, HELIX_CYL_RADIUS)
      tmpM.compose(tmpV, tmpQ, tmpS)
      const e = tmpM.elements
      // THREE stores column-major (e[0..3] = col0, etc.). Direct copy.
      for (let k = 0; k < 16; k++) data[i * 16 + k] = e[k]
    }
    const tex = new THREE.DataTexture(
      data, w, h, THREE.RGBAFormat, THREE.FloatType,
    )
    tex.minFilter = THREE.NearestFilter
    tex.magFilter = THREE.NearestFilter
    tex.generateMipmaps = false
    tex.needsUpdate = true
    return { tex, data }
  }

  // Average per-strand color → vec3 for billboard tint. Falls back to grey.
  function _averageStrandColorRGB(design) {
    let r = 0, g = 0, b = 0, n = 0
    for (const s of design?.strands ?? []) {
      if (!s.color) continue
      const v = parseInt(s.color.replace(/^#/, ''), 16)
      r += ((v >> 16) & 0xff) / 255
      g += ((v >>  8) & 0xff) / 255
      b += ( v        & 0xff) / 255
      n++
    }
    if (n === 0) return [0.6, 0.6, 0.6]
    return [r / n, g / n, b / n]
  }

  // ── Mid-LOD InstancedMesh + shader ───────────────────────────────────────
  // Shared cylinder geometry (radius 1.125 nm to match the legacy
  // helix_renderer's GEO_UNIT_CYL; the per-segment matrices we copy from
  // iHelixCylinders assume that radius).  Unit height — matrix scale.y
  // sizes the cylinder to the domain it represents.  Reused across sources
  // so we don't dispose it in _disposeSource; tag userData.shared = true.
  const _LOD_CYL_GEO = new THREE.CylinderGeometry(1.125, 1.125, 1, 12, 1, false)
  _LOD_CYL_GEO.userData.shared = true
  // Half-cylinder for overhang segments — wall of a 180° arc at the legacy
  // helix radius (matches helix_renderer.js:GEO_HALF_CYL's wall component).
  // Visually distinguishes overhang protrusions from full helix cylinders
  // so the user can spot overhang domains / mate-point candidates at the
  // cylinders LOD.
  const _LOD_HALF_CYL_GEO = new THREE.CylinderGeometry(
    1.125, 1.125, 1, 12, 1, false, 0, Math.PI,
  )
  _LOD_HALF_CYL_GEO.userData.shared = true

  // Generic per-segment InstancedMesh builder.  Both helix and overhang
  // mid-LOD meshes use the same pattern: copy per-segment matrices + colors
  // from a legacy InstancedMesh built by buildHelixObjects (iHelixCylinders
  // / iOverhangCylinders), pack into 2D-tiled DataTextures, and patch the
  // material's shader to sample them per `gl_InstanceID`.
  //
  // The per-instance world transform comes from the shared per-source
  // xform texture (already set up by `_buildSource`).  Total mesh count =
  // numSegments × numInstances; the shader decomposes gl_InstanceID via
  // `u_numSegments` to recover (instanceIdx, segmentIdx).
  function _buildSegmentLodMesh({
    srcEntry, legacyMesh, geometry, meshName, sourceGroup, side = THREE.FrontSide,
  }) {
    const numSegments  = legacyMesh?.count ?? 0
    const numInstances = srcEntry.instanceIds.length
    if (numSegments === 0 || numInstances === 0) return null

    const { tex: segXformTex, data: segXformData } = _makeBpXformTexture(
      legacyMesh.instanceMatrix.array, numSegments,
    )

    const tileW = _BP_TEX_TILE_W
    const h = Math.max(1, Math.ceil(numSegments / tileW))
    const colorData = new Float32Array(tileW * h * 4)
    const srcColor = legacyMesh.instanceColor?.array
    if (srcColor) {
      for (let i = 0; i < numSegments; i++) {
        colorData[i * 4 + 0] = srcColor[i * 3 + 0]
        colorData[i * 4 + 1] = srcColor[i * 3 + 1]
        colorData[i * 4 + 2] = srcColor[i * 3 + 2]
        colorData[i * 4 + 3] = 1.0
      }
    } else {
      for (let i = 0; i < numSegments; i++) {
        colorData[i * 4 + 0] = 1
        colorData[i * 4 + 1] = 1
        colorData[i * 4 + 2] = 1
        colorData[i * 4 + 3] = 1
      }
    }
    const segColorTex = new THREE.DataTexture(
      colorData, tileW, h, THREE.RGBAFormat, THREE.FloatType,
    )
    segColorTex.minFilter = THREE.NearestFilter
    segColorTex.magFilter = THREE.NearestFilter
    segColorTex.generateMipmaps = false
    segColorTex.needsUpdate = true

    const mat = new THREE.MeshLambertMaterial({ color: 0xffffff, side })
    // Per-material cache key so each source's program is independent
    // (avoids the static-cache-key trap from earlier worktree gotchas).
    const _cacheKey = meshName + '_' + mat.uuid
    mat.customProgramCacheKey = () => _cacheKey
    const u_instanceOffset = { value: 0 }
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.u_instanceXform   = srcEntry.uXformUniform
      shader.uniforms.u_visibilityTex   = srcEntry.uVisUniform
      shader.uniforms.u_segXform        = { value: segXformTex }
      shader.uniforms.u_segColor        = { value: segColorTex }
      shader.uniforms.u_numSegments     = { value: numSegments }
      shader.uniforms.u_instanceOffset  = u_instanceOffset
      shader.vertexShader = shader.vertexShader
        .replace(
          '#include <common>',
          `
          #include <common>
          #define BP_TILE_W ${_BP_TEX_TILE_W}
          uniform sampler2D u_instanceXform;
          uniform sampler2D u_visibilityTex;
          uniform sampler2D u_segXform;
          uniform float u_numSegments;
          uniform float u_instanceOffset;
          varying float v_visible;
          flat varying int v_segIdx;
          `,
        )
        .replace(
          '#include <begin_vertex>',
          `
          // Decompose gl_InstanceID = instanceIdx * numSegments + segmentIdx,
          // then bias instanceIdx by u_instanceOffset so this mesh reads
          // texture rows starting AFTER the close-LOD's bucket range
          // (sort-to-front packs rows by bucket).
          int instanceIdx = int(floor(float(gl_InstanceID) / max(u_numSegments, 1.0))) + int(u_instanceOffset);
          int segIdx      = gl_InstanceID - (instanceIdx - int(u_instanceOffset)) * int(u_numSegments);
          int segCol      = segIdx % BP_TILE_W;
          int segRow      = segIdx / BP_TILE_W;
          v_visible = texelFetch(u_visibilityTex, ivec2(0, instanceIdx), 0).r;
          v_segIdx = segIdx;
          mat4 instTransform = mat4(
            texelFetch(u_instanceXform, ivec2(0, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(1, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(2, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(3, instanceIdx), 0)
          );
          // Per-segment matrix from the 2D-tiled texture (4 RGBA texels per
          // mat4, packed along the row, wrapping every BP_TILE_W slots).
          mat4 segMat = mat4(
            texelFetch(u_segXform, ivec2(segCol * 4 + 0, segRow), 0),
            texelFetch(u_segXform, ivec2(segCol * 4 + 1, segRow), 0),
            texelFetch(u_segXform, ivec2(segCol * 4 + 2, segRow), 0),
            texelFetch(u_segXform, ivec2(segCol * 4 + 3, segRow), 0)
          );
          vec3 transformed = (instTransform * segMat * vec4(position, 1.0)).xyz;
          `,
        )
      shader.fragmentShader = shader.fragmentShader
        .replace(
          '#include <common>',
          `
          #include <common>
          #define BP_TILE_W ${_BP_TEX_TILE_W}
          uniform sampler2D u_segColor;
          varying float v_visible;
          flat varying int v_segIdx;
          `,
        )
        .replace(
          '#include <dithering_fragment>',
          `
          if (v_visible < 0.5) discard;
          int scol = v_segIdx % BP_TILE_W;
          int srow = v_segIdx / BP_TILE_W;
          gl_FragColor.rgb *= texelFetch(u_segColor, ivec2(scol, srow), 0).rgb;
          #include <dithering_fragment>
          `,
        )
    }

    const capacity = numSegments * numInstances
    const mesh = new THREE.InstancedMesh(geometry, mat, Math.max(1, capacity))
    // Collapse instanceMatrix to identity (bp-path pattern); per-instance
    // and per-segment transforms ride in textures sampled by the shader.
    const identityArr = new Float32Array(16)
    identityArr[0] = 1; identityArr[5] = 1; identityArr[10] = 1; identityArr[15] = 1
    const idAttr = new THREE.InstancedBufferAttribute(identityArr, 16, false, Math.max(1, capacity))
    idAttr.setUsage(THREE.StaticDrawUsage)
    mesh.instanceMatrix = idAttr
    mesh.instanceMatrix.needsUpdate = true
    mesh.instanceColor = null
    mesh.count = 0
    mesh.frustumCulled = false
    // visible=true so onBeforeRender hooks fire even before _updateLod's
    // first pass (Three.js short-circuits at visible=false BEFORE the
    // callback).  drawElementsInstanced with count=0 is a no-op.
    mesh.visible = true
    mesh.name = meshName
    sourceGroup.add(mesh)
    return {
      mesh,
      numSegments,
      segXformTex, segXformData,
      segColorTex, segColorData: colorData,
      u_instanceOffset,
    }
  }

  // Backwards-compat wrapper for the helix mid-LOD.  Takes the legacy
  // iHelixCylinders mesh and builds a per-domain InstancedMesh — gives the
  // legacy per-strand-domain look (multiple short cylinders per helix, with
  // gaps where overhangs / nicks fall) instead of the previous "one cylinder
  // spanning the whole helix" simplification.
  function _buildMidLodMesh(srcEntry, legacyHelixCylMesh, sourceGroup) {
    return _buildSegmentLodMesh({
      srcEntry,
      legacyMesh: legacyHelixCylMesh,
      geometry: _LOD_CYL_GEO,
      meshName: 'sharedLodMid',
      sourceGroup,
    })
  }

  // ── Overhang-LOD InstancedMesh + shader ──────────────────────────────────
  // Mirrors the sharedLodMid pattern but draws ONE half-cylinder per overhang
  // segment (where the legacy iOverhangCylinders mesh draws individual
  // overhang domains).  This restores the visual cue that overhangs poke
  // out from the helix axis — important for identifying mate points at
  // the cylinders LOD.  Each source-instance replicates the same per-segment
  // set, so total mesh count = numOverhangs × numInstances.  Drawn alongside
  // sharedLodMid in the mid bucket.
  //
  // legacyOverhangMesh: the iOverhangCylinders InstancedMesh from buildHelixObjects.
  // Carries per-segment matrices (instanceMatrix) + colors (instanceColor) in
  // source-local space.  We copy them into our own DataTextures so the shared
  // shader can sample per-segment without needing the source iHelixCtrl alive.
  function _buildOverhangLodMesh(srcEntry, legacyOverhangMesh, sourceGroup) {
    return _buildSegmentLodMesh({
      srcEntry,
      legacyMesh: legacyOverhangMesh,
      geometry: _LOD_HALF_CYL_GEO,
      meshName: 'sharedLodOverhangs',
      sourceGroup,
      side: THREE.DoubleSide,
    })
  }

  // ── Far-LOD InstancedMesh + shader ───────────────────────────────────────
  // A camera-facing quad per instance. Quad geometry: 2 triangles in the XY
  // plane, size [-0.5, 0.5]. The vertex shader rebuilds the world position
  // from the instance transform's translation column and offsets by a
  // camera-aligned right/up basis scaled to `u_billboardRadius`.
  //
  // Shared geometry across sources — tagged shared so dispose-walk skips it.
  const _LOD_QUAD_GEO = new THREE.PlaneGeometry(1.0, 1.0)
  _LOD_QUAD_GEO.userData.shared = true

  function _buildFarLodMesh(srcEntry, billboardRadius, billboardColor, sourceGroup) {
    const numInstances = srcEntry.instanceIds.length
    if (numInstances === 0) return null

    const mat = new THREE.MeshBasicMaterial({ color: 0xffffff })
    // Phase 3f stage 2 follow-up: per-material cache key + u_instanceOffset
    // so this far-LOD mesh reads texture rows starting after close+mid range.
    const _farCacheKey = 'sharedLodFar_' + mat.uuid
    mat.customProgramCacheKey = () => _farCacheKey
    const u_instanceOffset = { value: 0 }
    // u_billboardColor: out-of-closure so coloringMode changes can update
    // the per-source tint in lockstep with the mid-LOD u_sourceColor.
    const u_billboardColor = { value: new THREE.Vector3(...billboardColor) }
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.u_instanceXform   = srcEntry.uXformUniform
      shader.uniforms.u_visibilityTex   = srcEntry.uVisUniform
      shader.uniforms.u_billboardRadius = { value: billboardRadius }
      shader.uniforms.u_billboardColor  = u_billboardColor
      shader.uniforms.u_instanceOffset  = u_instanceOffset
      shader.vertexShader = shader.vertexShader
        .replace(
          '#include <common>',
          `
          #include <common>
          uniform sampler2D u_instanceXform;
          uniform sampler2D u_visibilityTex;
          uniform float u_billboardRadius;
          uniform float u_instanceOffset;
          varying float v_visible;
          `,
        )
        .replace(
          '#include <begin_vertex>',
          `
          int instanceIdx = gl_InstanceID + int(u_instanceOffset);
          v_visible = texelFetch(u_visibilityTex, ivec2(0, instanceIdx), 0).r;
          // Translation column of the instance transform (column 3).
          vec4 col3 = texelFetch(u_instanceXform, ivec2(3, instanceIdx), 0);
          vec3 worldPos = col3.xyz;
          // Camera-aligned billboard basis from the inverse view matrix.
          // viewMatrix is world → view; its inverse columns 0/1 are world-
          // space camera right/up.
          mat4 invView = inverse(viewMatrix);
          vec3 camRight = vec3(invView[0][0], invView[0][1], invView[0][2]);
          vec3 camUp    = vec3(invView[1][0], invView[1][1], invView[1][2]);
          // Quad geometry is unit-PlaneGeometry (position.xy ∈ [-0.5, 0.5]),
          // so total span = u_billboardRadius after this multiply.  Earlier
          // the shader used "* 2.0" — combined with the diagonal-based
          // u_billboardRadius this drew billboards ~4× the actual source
          // silhouette ("oversized greenish rectangles").
          vec3 transformed = worldPos
            + camRight * position.x * u_billboardRadius
            + camUp    * position.y * u_billboardRadius;
          `,
        )
      shader.fragmentShader = shader.fragmentShader
        .replace(
          '#include <common>',
          `
          #include <common>
          uniform vec3 u_billboardColor;
          varying float v_visible;
          `,
        )
        .replace(
          '#include <dithering_fragment>',
          `
          if (v_visible < 0.5) discard;
          gl_FragColor.rgb = u_billboardColor;
          #include <dithering_fragment>
          `,
        )
    }

    const mesh = new THREE.InstancedMesh(_LOD_QUAD_GEO, mat, Math.max(1, numInstances))
    // Collapse instanceMatrix to a single identity row.
    const identityArr = new Float32Array(16)
    identityArr[0] = 1; identityArr[5] = 1; identityArr[10] = 1; identityArr[15] = 1
    const idAttr = new THREE.InstancedBufferAttribute(identityArr, 16, false, Math.max(1, numInstances))
    idAttr.setUsage(THREE.StaticDrawUsage)
    mesh.instanceMatrix = idAttr
    mesh.instanceMatrix.needsUpdate = true
    mesh.instanceColor = null
    mesh.count = 0
    mesh.frustumCulled = false
    // Same lesson as sharedLodMid: keep visible=true so onBeforeRender
    // hooks fire even before _updateLod's first run.  drawElementsInstanced
    // with count=0 is a zero-cost no-op.
    mesh.visible = true
    mesh.name = 'sharedLodFar'
    sourceGroup.add(mesh)
    return { mesh, u_instanceOffset, u_billboardColor }
  }

  // ── Per-frame LOD assignment + sort-to-front (Phase 3f stage 2) ──────────
  // Each frame, for every source:
  //   1. Compute squared distance from camera to each instance's translation
  //      (read from column-3 texels of `xformData`).
  //   2. Sort row indices by ascending distance² → permutation `perm` where
  //      `perm[newRow] = oldRow`.
  //   3. If the permutation differs from identity (i.e. the current order),
  //      permute `xformData`, `visData`, `visibility`, `instanceIds`, and
  //      `instanceIndex` so row 0 holds the nearest visible instance, row 1
  //      the next-nearest, etc. Visible instances precede hidden ones;
  //      hidden instances retain a stable relative order at the tail.
  //   4. Mark both textures `needsUpdate = true` (simple full re-upload; the
  //      data lives in CPU-side typed arrays, so this is one PBO copy).
  //   5. Refresh `u_activeInstanceIdx` from `_activeInstanceId` against the
  //      new `instanceIndex` so selection brightening tracks the moved row.
  //   6. Bucket count: walk the now-sorted rows, count close/mid/far. Because
  //      rows are sorted nearest-first and the bucket thresholds are pure
  //      distance comparisons, the close bucket occupies rows 0..N_close-1.
  //   7. Set each LOD mesh's `count` (multiplied by per-LOD multiplier) and
  //      `visible = (count > 0)`.
  //
  // Scratch typed arrays are reused across frames (one allocation per source
  // at first use) to avoid GC pressure.
  // Reused scratch for bbox diagonal lookup so we don't allocate per frame.
  const _tmpBboxSize = new THREE.Vector3()

  function _updateLodForSource(srcEntry, camera, renderer) {
    if (!srcEntry || !camera) return
    const N = srcEntry.instanceIds.length
    if (N === 0) return

    // Angular-size LOD: compute on-screen pixel size of the source's bbox
    // diagonal at the camera's distance, then bucket by pixel thresholds.
    // pixelSize = bboxDiag × focalPx / distance, where
    // focalPx = viewport_height_px / (2 × tan(fov/2)).  Falls back to
    // distance-only bucketing for orthographic / no-renderer cases.
    let pxFactor = 0
    if (camera.isPerspectiveCamera && renderer?.domElement) {
      const bboxDiag = (() => {
        const box = srcEntry.instBoundingBox
        if (!box || box.isEmpty()) return 0
        box.getSize(_tmpBboxSize)
        return _tmpBboxSize.length()
      })()
      if (bboxDiag > 0) {
        const fovRad = camera.fov * Math.PI / 180
        const viewportH = renderer.domElement.height || window.innerHeight
        const focalPx = viewportH / (2 * Math.tan(fovRad / 2))
        pxFactor = bboxDiag * focalPx
      }
    }
    const closePxSq = _lodClosePx * _lodClosePx
    const farPxSq   = _lodFarPx   * _lodFarPx

    const cx = camera.position.x, cy = camera.position.y, cz = camera.position.z
    const data = srcEntry.xformData
    const vis  = srcEntry.visibility

    // ── 1. Build (row, distance²) array; hidden rows get +Infinity so they
    //      sort to the tail and never enter the close/mid bucket count.
    // Reuse scratch arrays across frames.
    let scratch = srcEntry._lodScratch
    if (!scratch || scratch.dist2.length !== N) {
      scratch = srcEntry._lodScratch = {
        dist2: new Float64Array(N),
        perm:  new Int32Array(N),       // perm[newRow] = oldRow
        bucket: new Int8Array(N),       // per-instance LOD bucket (0/1/2) or 3=hidden
        tmpXform: new Float32Array(N * 16),
        tmpVis:   new Float32Array(N * 16),
        tmpVisibility: new Float32Array(N),
        tmpLodCap: new Int8Array(N),
        tmpIds: new Array(N),
      }
    }
    const dist2 = scratch.dist2
    const perm  = scratch.perm
    const bucket = scratch.bucket
    const lodCap = srcEntry.instanceLodCap
    for (let i = 0; i < N; i++) {
      perm[i] = i
      if (vis[i] < 0.5) {
        dist2[i] = Number.POSITIVE_INFINITY
        bucket[i] = 3  // hidden — sinks to tail
        continue
      }
      // Translation column = column 3. xformData layout (per instance, 16
      // floats): c0(4) | c1(4) | c2(4) | c3(4). col3.xyz at offset i*16+12.
      const off = i * 16 + 12
      const dx = data[off + 0] - cx
      const dy = data[off + 1] - cy
      const dz = data[off + 2] - cz
      const d2 = dx * dx + dy * dy + dz * dz
      dist2[i] = d2
      // Compute effective bucket from (cap, angular size).  Sorting by
      // (bucket, dist²) keeps per-LOD row ranges contiguous, which the
      // mid/far shaders rely on via u_instanceOffset.
      const cap = lodCap ? lodCap[i] : 0
      // pxSq = (pxFactor / distance)² = pxFactor² / d2.  Compare pxSq to
      // threshold² to avoid the sqrt in the hot loop.
      const pxSq = (pxFactor > 0) ? (pxFactor * pxFactor) / Math.max(d2, 1) : 1e12
      if      (cap === 0 && pxSq >= closePxSq) bucket[i] = 0
      else if (cap <= 1 && pxSq >= farPxSq)    bucket[i] = 1
      else                                     bucket[i] = 2
    }

    // ── 2. Sort perm by (bucket, dist²) ascending.  Bucket comes first so
    //      every LOD's rows are a contiguous range — mid/far shaders read
    //      via a single u_instanceOffset.
    const permArr = Array.from(perm)
    permArr.sort((a, b) => {
      const ba = bucket[a], bb = bucket[b]
      if (ba !== bb) return ba - bb
      return dist2[a] - dist2[b]
    })

    // ── 3. Detect "already sorted" — if perm equals identity (every entry
    //      is at its own index), short-circuit the permute step. Most steady-
    //      state frames after the first sort will be near-identity, so we
    //      avoid the texture re-upload in that common case.
    let isIdentity = true
    for (let i = 0; i < N; i++) {
      if (permArr[i] !== i) { isIdentity = false; break }
    }

    if (!isIdentity) {
      // Permute xformData, visData, visibility, instanceIds, instanceIndex.
      // We read from the ORIGINAL arrays via perm[newRow] = oldRow, write to
      // scratch buffers, then swap-copy back.
      const tmpX = scratch.tmpXform
      const tmpV = scratch.tmpVis
      const tmpVisFlag = scratch.tmpVisibility
      const tmpLodCap = scratch.tmpLodCap
      const tmpIds = scratch.tmpIds
      const visData = srcEntry.visData
      const ids = srcEntry.instanceIds
      const lodCap = srcEntry.instanceLodCap
      for (let newRow = 0; newRow < N; newRow++) {
        const oldRow = permArr[newRow]
        const srcOff = oldRow * 16
        const dstOff = newRow * 16
        // Copy 16-float xform row.
        for (let k = 0; k < 16; k++) tmpX[dstOff + k] = data[srcOff + k]
        // Copy 16-float vis row (only channel 0 carries the flag, but copy
        // the whole row to preserve any future-use channels).
        for (let k = 0; k < 16; k++) tmpV[dstOff + k] = visData[srcOff + k]
        tmpVisFlag[newRow] = vis[oldRow]
        tmpLodCap[newRow]  = lodCap ? lodCap[oldRow] : 0
        tmpIds[newRow] = ids[oldRow]
      }
      // Write scratch → live arrays.
      data.set(tmpX)
      visData.set(tmpV)
      vis.set(tmpVisFlag)
      if (lodCap) lodCap.set(tmpLodCap)
      for (let i = 0; i < N; i++) ids[i] = tmpIds[i]
      // Rebuild instanceIndex (id → currentRow). instanceIndex is the live
      // map every external API must use to look up an id's current slot.
      srcEntry.instanceIndex.clear()
      for (let i = 0; i < N; i++) srcEntry.instanceIndex.set(ids[i], i)

      // Mark textures dirty for full re-upload next frame's draw. Clear any
      // pending partial-upload dirty-row sets: their indices refer to the
      // OLD row order and would now corrupt the texture if applied.
      srcEntry.xformTex.needsUpdate = true
      srcEntry.visTex.needsUpdate   = true
      srcEntry.dirtyRows.clear()
      srcEntry.dirtyVisRows.clear()
    }

    // ── 4. Refresh u_activeInstanceIdx for the active id (if any belongs to
    //      this source). This MUST run every frame, not just on permute-
    //      change, because `setActiveInstance` is permutation-safe by lookup.
    if (_activeInstanceId == null) {
      srcEntry.uActiveIdxUniform.value = -1
    } else {
      const row = srcEntry.instanceIndex.get(_activeInstanceId)
      srcEntry.uActiveIdxUniform.value = (row == null) ? -1 : row
    }

    // ── 5. Bucket count.  Bucket was computed pre-sort using the
    //      per-instance LOD cap (from ``representation``), so we just walk
    //      the now-sorted perm and tally.  Buckets are guaranteed
    //      contiguous: rows 0..nClose-1 are close, the next nMid are mid,
    //      the next nFar are far, and hidden rows (bucket=3) fall after.
    let nClose = 0, nMid = 0, nFar = 0
    for (let i = 0; i < N; i++) {
      const b = bucket[permArr[i]]
      if (b === 3) break                // hidden tail — done
      if      (b === 0) nClose++
      else if (b === 1) nMid++
      else              nFar++
    }

    // ── 6. Apply counts. Multiplier per LOD:
    //        close: baseCount per close-LOD InstancedMesh
    //        mid:   numHelices
    //        far:   1
    for (const am of srcEntry.activeMeshes) {
      const c = nClose * am.baseCount
      am.mesh.count = c
      // Phase 3f stage 2 follow-up: keep `visible = true` unconditionally so
      // the onBeforeRender hook chain keeps firing even when count=0. Three.js
      // short-circuits at `object.visible === false` BEFORE invoking
      // onBeforeRender (WebGLRenderer.js#L1327), which would freeze the LOD
      // state the first time nClose hits zero. drawElementsInstanced with
      // count=0 is a zero-cost no-op.
      am.mesh.visible = true
    }
    // Phase 3f stage 2 follow-up: with rows sorted by distance, mid-LOD
    // reads texture rows starting at nClose, far-LOD starting at nClose+nMid.
    // Without these offsets, the shaders would read rows 0..nMid-1 / 0..nFar-1
    // — i.e. the SAME nearest instances close-LOD already drew (triple-render
    // bug from stage 1, surfaced by the stage-1 evaluator FAIL at 8f185bb).
    if (srcEntry.midLod) {
      const c = nMid * srcEntry.midLod.numSegments
      srcEntry.midLod.mesh.count = c
      srcEntry.midLod.mesh.visible = true  // see comment above re: stuck-LOD trap
      if (srcEntry.midLod.u_instanceOffset) {
        srcEntry.midLod.u_instanceOffset.value = nClose
      }
    }
    // Overhang LOD draws alongside mid LOD — same instance offset (after
    // close bucket).  Skipping when no overhangs exist avoids spurious draws.
    if (srcEntry.overhangLod) {
      const c = nMid * srcEntry.overhangLod.numSegments
      srcEntry.overhangLod.mesh.count = c
      srcEntry.overhangLod.mesh.visible = true
      if (srcEntry.overhangLod.u_instanceOffset) {
        srcEntry.overhangLod.u_instanceOffset.value = nClose
      }
    }
    if (srcEntry.farLod) {
      const c = nFar
      srcEntry.farLod.mesh.count = c
      srcEntry.farLod.mesh.visible = true  // see comment above re: stuck-LOD trap
      if (srcEntry.farLod.u_instanceOffset) {
        srcEntry.farLod.u_instanceOffset.value = nClose + nMid
      }
    }
    srcEntry._lastLodCounts = { close: nClose, mid: nMid, far: nFar }
    // Debug: stash per-frame state so `probeLod()` + the HUD can read it
    // without re-doing the heavy bucket pass.  Compute min/max pixel size
    // over visible instances in a single cheap loop.
    let minPx = Infinity, maxPx = -Infinity
    if (pxFactor > 0) {
      for (let i = 0; i < N; i++) {
        if (vis[i] < 0.5) continue
        const d2 = dist2[i]
        if (!isFinite(d2) || d2 <= 0) continue
        const px = pxFactor / Math.sqrt(d2)
        if (px < minPx) minPx = px
        if (px > maxPx) maxPx = px
      }
    }
    srcEntry._lastLodDebug = {
      pxFactor,
      bboxDiag: pxFactor > 0 ? pxFactor / (renderer?.domElement?.height
        ? renderer.domElement.height / (2 * Math.tan((camera.fov * Math.PI / 180) / 2))
        : 1) : 0,
      closePx: _lodClosePx,
      farPx: _lodFarPx,
      minPxSize: isFinite(minPx) ? minPx : null,
      maxPxSize: isFinite(maxPx) ? maxPx : null,
    }
  }

  // Install a SECOND onBeforeRender hook for LOD updates. It piggybacks on
  // the first active mesh, which already carries the dirty-row uploader; we
  // chain them. Three.js calls onBeforeRender(renderer, scene, camera, ...).
  function _installLodUpdater(srcEntry) {
    // Find ANY mesh that's reliably scene-resident every frame so the
    // onBeforeRender hook actually fires.  Cylinders-rep builds leave
    // activeMeshes empty (only bp meshes go in there, and bp meshes have
    // baseCount==0 at that rep), so we fall back to sharedLodMid / sharedLodFar.
    // Without this fallback _updateLodForSource never runs → sharedLodMid.count
    // stays 0 → only helix axes draw (regression from 26f9df1).
    const hookHost =
      srcEntry.activeMeshes[0]?.mesh
      ?? srcEntry.midLod?.mesh
      ?? srcEntry.farLod?.mesh
    if (!hookHost) return
    const prevHook = hookHost.onBeforeRender
    hookHost.onBeforeRender = function (renderer, scn, camera, geom, mat, group) {
      if (typeof prevHook === 'function') {
        prevHook.call(this, renderer, scn, camera, geom, mat, group)
      }
      _updateLodForSource(srcEntry, camera, renderer)
    }
  }

  // ── Public: dispose ───────────────────────────────────────────────────────
  function dispose() {
    for (const srcEntry of _sources.values()) _disposeSource(srcEntry)
    _sources.clear()
    _instToSrc.clear()
    _prefetchedByPath.clear()
    _activeInstanceId = null
  }

  // ── Texture upload — dirty rows only ──────────────────────────────────────
  // Uses an onBeforeRender hook on each source's InstancedMesh to upload only
  // the dirty rows via gl.texSubImage2D (Three.js exposes the gl context via
  // the renderer arg). We attach the hook to one mesh per source (the first
  // active mesh); the others share the same texture so one upload suffices.
  function _installDirtyUploader(srcEntry) {
    if (!srcEntry.activeMeshes.length) return
    const firstMesh = srcEntry.activeMeshes[0].mesh
    firstMesh.onBeforeRender = function (renderer /*, scene, camera, geom, mat, group */) {
      const dirty    = srcEntry.dirtyRows
      const dirtyVis = srcEntry.dirtyVisRows
      if (dirty.size === 0 && dirtyVis.size === 0) return

      const gl = renderer.getContext()
      const props = renderer.properties
      function _uploadRows(texture, srcData, rowSet) {
        if (rowSet.size === 0) return
        const texProps = props.get(texture)
        if (!texProps.__webglTexture) {
          // Texture hasn't been uploaded yet — let Three.js do the initial
          // full upload via needsUpdate.
          texture.needsUpdate = true
          rowSet.clear()
          return
        }
        const prevBinding = gl.getParameter(gl.TEXTURE_BINDING_2D)
        gl.bindTexture(gl.TEXTURE_2D, texProps.__webglTexture)
        // Each row = 4 RGBA texels = 16 floats. We could batch contiguous
        // runs of dirty rows; for now, one texSubImage2D per dirty row.
        // 2000 dirty rows × the upload cost is still bounded; if it bites
        // we'll coalesce.
        for (const rowIdx of rowSet) {
          const offset = rowIdx * 16
          const view = srcData.subarray(offset, offset + 16)
          gl.texSubImage2D(
            gl.TEXTURE_2D, 0,
            /* x */ 0, /* y */ rowIdx,
            /* width */ 4, /* height */ 1,
            gl.RGBA, gl.FLOAT, view,
          )
        }
        gl.bindTexture(gl.TEXTURE_2D, prevBinding)
        rowSet.clear()
      }
      _uploadRows(srcEntry.xformTex, srcEntry.xformData, dirty)
      _uploadRows(srcEntry.visTex,   srcEntry.visData,   dirtyVis)
    }
  }

  // ── Public: rebuild ───────────────────────────────────────────────────────
  async function rebuild(assembly /*, opts */) {
    if (!assembly) { dispose(); return }

    const instances = assembly.instances ?? []
    if (!instances.length) {
      dispose()
      _fireRebuildComplete()
      return
    }

    // Group instances by source_key.
    const groups = new Map() // srcKey → PartInstance[]
    for (const inst of instances) {
      const key = _sharedSourceKey(inst)
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(inst)
    }

    // Fetch geometry for any source we haven't built yet (or one that the
    // user invalidated). For simplicity (and per spec for invalidateInstance),
    // we tear down all current sources and rebuild. Future optimization: only
    // rebuild sources whose membership / source_key set changed.
    dispose()  // wipes everything; we'll rebuild from scratch each time.

    let batchGeo = null
    try {
      batchGeo = await api.getAssemblyGeometry()
    } catch (err) {
      console.warn('[shared_renderer] batch geometry fetch failed:', err)
      _fireRebuildComplete()
      return
    }
    const perInst = batchGeo?.instances ?? {}

    for (const [srcKey, instList] of groups) {
      // Pick the first instance's geometry record — every instance of the
      // same source shares the same nucleotides/design references (client.js
      // dedup is already in place).
      const firstId = instList[0].id
      const rec = perInst[firstId]
      let srcData = rec
      if (!srcData || srcData.error) {
        // Per-instance fallback.
        try {
          const geo = await api.getInstanceGeometry(firstId)
          srcData = {
            nucleotides: geo?.nucleotides ?? [],
            helix_axes: _convertHelixAxesArray(geo?.helix_axes),
            design: geo?.design ?? null,
          }
        } catch (err) {
          console.warn(`[shared_renderer] geometry fetch failed for ${firstId}:`, err)
          continue
        }
      }
      // The client's `getAssemblyGeometry` projects helix_axes through as the
      // raw map (already dict-shape after _expandCompactNucleotides). When
      // we fall back to getInstanceGeometry the shape is array-of-axis so we
      // convert it.
      if (Array.isArray(srcData.helix_axes)) {
        srcData = { ...srcData, helix_axes: _convertHelixAxesArray(srcData.helix_axes) }
      }
      const entry = await _buildSource(srcKey, srcData, instList)
      if (!entry) continue
      _sources.set(srcKey, entry)
      _installDirtyUploader(entry)
      _installLodUpdater(entry)
    }

    _fireRebuildComplete()
  }

  function _convertHelixAxesArray(arr) {
    if (!arr) return null
    if (!Array.isArray(arr)) return arr   // already dict
    const map = {}
    for (const ax of arr) {
      map[ax.helix_id] = {
        start: ax.start,
        end: ax.end,
        samples: ax.samples ?? null,
        ovhgAxes: ax.ovhg_axes ?? null,
      }
    }
    return map
  }

  // ── Public: applyInlineGeometry ───────────────────────────────────────────
  // Stash the prefetched geometry and trigger a full rebuild. The simplest
  // correct behaviour at scale: the geometry pertains to a file source so
  // every instance referencing that path needs the new geometry — easiest
  // is a rebuild that re-fetches via api (which the seek endpoint already
  // has invalidated). For now this matches the old path's contract.
  async function applyInlineGeometry(filePath, design, nucleotides, helixAxes) {
    const assembly = store?.getState?.()?.currentAssembly
    if (!assembly || !filePath) return
    // Same trigger as the old path — rebuild will refetch.
    await rebuild(assembly)
  }

  // ── Public: invalidateInstance ────────────────────────────────────────────
  function invalidateInstance(/* instanceId */) {
    // Per the spec: a full rebuild is acceptable for representation changes.
    const assembly = store?.getState?.()?.currentAssembly
    if (assembly) {
      // Don't await — fire-and-forget; matches old path semantics.
      rebuild(assembly).catch(err =>
        console.warn('[shared_renderer] invalidate-triggered rebuild failed:', err),
      )
    }
  }

  // ── Public: setActiveInstance ─────────────────────────────────────────────
  // Phase 3f stage 2: row indices are sort-to-front-permuted every frame, so
  // an id's row is not stable across frames. We stash the active id in
  // `_activeInstanceId` and rely on `_updateLodForSource` to refresh
  // `uActiveIdxUniform.value` from `instanceIndex.get(_activeInstanceId)`
  // each frame after the permutation. To keep the highlight visible BEFORE
  // the next frame's onBeforeRender (e.g. a still-image render after a
  // selection click), we also write the CURRENT row here.
  function setActiveInstance(id) {
    // Clear previous highlight (every source) — the per-frame refresh will
    // re-light the matching source's uniform on the next draw.
    for (const srcEntry of _sources.values()) {
      srcEntry.uActiveIdxUniform.value = -1
    }
    _activeInstanceId = id ?? null
    if (!id) return
    const srcKey = _instToSrc.get(id)
    if (!srcKey) return
    const srcEntry = _sources.get(srcKey)
    if (!srcEntry) return
    // instanceIndex is the LIVE id-to-row map (permuted by sort-to-front).
    const idx = srcEntry.instanceIndex.get(id)
    if (idx == null) return
    srcEntry.uActiveIdxUniform.value = idx
  }

  // ── Public: updateStrandColor ─────────────────────────────────────────────
  // Live UI strand-color change. For each source we:
  //   1. Update the source's `customColors` dict (strandId → hex int).
  //   2. Re-run `buildHelixObjects` with the updated colors into a throwaway
  //      Group, producing fresh InstancedMeshes whose `instanceColor.array`
  //      already encodes the new per-bp colors (helix_renderer.js owns the
  //      bp-slot → strand mapping).
  //   3. Walk the temp helixCtrl + the patched activeMeshes IN PARALLEL
  //      (traverse order is deterministic from buildHelixObjects), copying
  //      each temp InstancedMesh's `instanceColor.array` into the matching
  //      activeMeshes entry's `bpColorData` Float32Array. Mark
  //      `bpColorTex.needsUpdate = true` for a full re-upload on the next
  //      frame (bp color textures are 1 × bp_count × RGBA32F, typically a
  //      few KB per mesh — full re-upload is cheap relative to per-row
  //      `texSubImage2D` bookkeeping, and the user-visible UI click already
  //      cost the buildHelixObjects rebuild).
  //   4. Dispose the temp helixCtrl group (its InstancedMeshes + geometries
  //      + materials).
  //
  // The bp-color mapping is implicit inside helix_renderer.js (option C in
  // the Phase 3d-A spec); we never inspect it directly.
  // Re-paint one source's bp-color texture by running `buildHelixObjects`
  // against a throwaway Group (option C from the 3d-A spec). When
  // `modeOverride` is non-null OR the store's coloringMode is not 'strand',
  // also invoke `helixCtrl.applyColoring(mode, ...)` on the throwaway —
  // mirrors the per-instance path's `_applyColoringToEntry`.
  function _applyColorsToSource(srcEntry, modeOverride) {
    if (!srcEntry?.design || !srcEntry?.nucleotides) return
    const tmpGroup = new THREE.Group()
    let tmpHelixCtrl
    try {
      tmpHelixCtrl = buildHelixObjects(
        srcEntry.nucleotides,
        srcEntry.design,
        tmpGroup,
        srcEntry.customColors,
        [],                  // loopStrandIds — assemblies don't track this
        srcEntry.helixAxes,
        srcEntry.rep,
      )
    } catch (err) {
      console.warn('[shared_renderer] _applyColorsToSource: buildHelixObjects threw:', err)
      return
    }

    // Apply coloring-mode transform on the temp helixCtrl. buildHelixObjects
    // always paints strand colors; non-strand modes need a follow-up
    // `applyColoring` call. Old per-instance path does the same.
    const mode = modeOverride ?? (store.getState().coloringMode || 'strand')
    if (mode !== 'strand' && typeof tmpHelixCtrl.applyColoring === 'function') {
      try {
        tmpHelixCtrl.applyColoring(mode, srcEntry.design, srcEntry.customColors, new Set())
      } catch (err) {
        console.warn('[shared_renderer] _applyColorsToSource: applyColoring threw:', err)
      }
    }

    // Collect temp InstancedMeshes in traverse order (matches the order in
    // `_patchSharedMeshes`, which uses the same .traverse() over the SAME
    // helixCtrl.root structure). Skip count=0 meshes.
    // Also stash the temp iHelixCylinders mesh by name so we can pull its
    // per-segment instanceColor into the mid-LOD per-helix colour texture.
    const tmpMeshes = []
    let tmpHelixCyl = null
    let tmpOvhgCyl  = null
    tmpHelixCtrl.root.traverse(obj => {
      if (!(obj instanceof THREE.InstancedMesh)) return
      if (obj.name === 'helixCylinders')    tmpHelixCyl = obj
      if (obj.name === 'overhangCylinders') tmpOvhgCyl  = obj
      if (obj.count === 0) return
      tmpMeshes.push(obj)
    })

    const pairs = Math.min(tmpMeshes.length, srcEntry.activeMeshes.length)
    // Per-bp colour copy into activeMeshes' bpColorTex (full-rep path).
    for (let i = 0; i < pairs; i++) {
      const tmp = tmpMeshes[i]
      const am  = srcEntry.activeMeshes[i]
      if (!tmp.instanceColor) continue
      if (!am.bpColorTex || !am.bpColorData) continue
      const src = tmp.instanceColor.array
      const n   = Math.min(am.baseCount, Math.floor(src.length / 3))
      const dst = am.bpColorData
      for (let j = 0; j < n; j++) {
        dst[j * 4 + 0] = src[j * 3 + 0]
        dst[j * 4 + 1] = src[j * 3 + 1]
        dst[j * 4 + 2] = src[j * 3 + 2]
      }
      am.bpColorTex.needsUpdate = true
    }

    // Per-segment colour updates for mid + overhang LODs.  Both share the
    // same shape: copy the legacy mesh's instanceColor (3 floats per
    // segment, populated by helixCtrl.applyColoring during the temp build)
    // into our 2D-tiled per-segment colour texture (4 floats per segment).
    function _copySegmentColors(lod, tmpMesh) {
      if (!lod?.segColorTex || !tmpMesh?.instanceColor) return
      const src = tmpMesh.instanceColor.array
      const dst = lod.segColorData
      const n = Math.min(lod.numSegments, Math.floor(src.length / 3))
      for (let i = 0; i < n; i++) {
        dst[i * 4 + 0] = src[i * 3 + 0]
        dst[i * 4 + 1] = src[i * 3 + 1]
        dst[i * 4 + 2] = src[i * 3 + 2]
        dst[i * 4 + 3] = 1
      }
      lod.segColorTex.needsUpdate = true
    }
    _copySegmentColors(srcEntry.midLod, tmpHelixCyl)
    _copySegmentColors(srcEntry.overhangLod, tmpOvhgCyl)

    // Far-LOD billboard tint: source-average of the mid-LOD per-segment
    // colours we just wrote, so the far rectangle still tracks coloringMode.
    if (srcEntry.midLod?.segColorData && srcEntry.farLod?.u_billboardColor) {
      const data = srcEntry.midLod.segColorData
      const numSegments = srcEntry.midLod.numSegments
      let r = 0, g = 0, b = 0
      for (let i = 0; i < numSegments; i++) {
        r += data[i * 4 + 0]
        g += data[i * 4 + 1]
        b += data[i * 4 + 2]
      }
      if (numSegments > 0) {
        srcEntry.farLod.u_billboardColor.value.set(r / numSegments, g / numSegments, b / numSegments)
      }
    }

    // Dispose: skip module-level shared template geometries (still in use
    // by the live helixCtrl); dispose the fresh-per-call materials.
    tmpHelixCtrl.root.traverse(obj => {
      if (obj.geometry && !obj.geometry.userData?.shared) obj.geometry.dispose()
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
        mats.forEach(m => m.dispose())
      }
    })
  }

  function updateStrandColor(strandId, hexColor) {
    if (strandId == null || hexColor == null) return
    for (const srcEntry of _sources.values()) {
      srcEntry.customColors[strandId] = hexColor
      _applyColorsToSource(srcEntry, null)  // null = pick current mode from store
    }
  }

  function updateColoringMode(mode) {
    if (mode == null) return
    for (const srcEntry of _sources.values()) {
      _applyColorsToSource(srcEntry, mode)
    }
  }

  // Subscribe to coloringMode changes. Mirrors the per-instance path's
  // subscriber (assembly_renderer.js:1936 in `initAssemblyRenderer`) which
  // doesn't fire when the shared path is active.
  store.subscribe?.((newState, prevState) => {
    if (newState.coloringMode !== prevState.coloringMode) {
      updateColoringMode(newState.coloringMode)
    }
  })

  // ── Public: getBoundingBox ────────────────────────────────────────────────
  function getBoundingBox() {
    const out = new THREE.Box3()
    const tmpInst = new THREE.Matrix4()
    const tmpBox  = new THREE.Box3()
    for (const srcEntry of _sources.values()) {
      const baseBox = srcEntry.instBoundingBox
      if (!baseBox || baseBox.isEmpty()) continue
      for (let i = 0; i < srcEntry.instanceIds.length; i++) {
        if (srcEntry.visibility[i] < 0.5) continue
        // Reconstruct the row-major matrix from xformData. Recall the texel
        // layout stores columns, so reading column-major is direct.
        const o = i * 16
        const e = tmpInst.elements
        for (let k = 0; k < 16; k++) e[k] = srcEntry.xformData[o + k]
        tmpBox.copy(baseBox).applyMatrix4(tmpInst)
        out.union(tmpBox)
      }
    }
    return out
  }

  /**
   * Per-instance world centers + radii. Called every frame by nav_controller's
   * fly-mode threshold check; must NOT throw or the rAF loop spams the console.
   * Returns `Array<{id, center: THREE.Vector3, radius: number}>`, same shape
   * as the old path's `getInstanceCenters()`.
   */
  function getInstanceCenters() {
    const out = []
    const tmpInst = new THREE.Matrix4()
    const tmpBox  = new THREE.Box3()
    for (const srcEntry of _sources.values()) {
      const baseBox = srcEntry.instBoundingBox
      if (!baseBox || baseBox.isEmpty()) continue
      for (let i = 0; i < srcEntry.instanceIds.length; i++) {
        if (srcEntry.visibility[i] < 0.5) continue
        const o = i * 16
        const e = tmpInst.elements
        for (let k = 0; k < 16; k++) e[k] = srcEntry.xformData[o + k]
        tmpBox.copy(baseBox).applyMatrix4(tmpInst)
        if (tmpBox.isEmpty()) continue
        const center = tmpBox.getCenter(new THREE.Vector3())
        const size   = tmpBox.getSize(new THREE.Vector3())
        const radius = Math.max(size.x, size.y, size.z) * 0.5
        out.push({ id: srcEntry.instanceIds[i], center, radius })
      }
    }
    return out
  }

  // ── Public: onRebuildComplete ─────────────────────────────────────────────
  function onRebuildComplete(fn) { _onRebuildCompleteCbs.push(fn) }
  function _fireRebuildComplete() {
    for (const fn of _onRebuildCompleteCbs) {
      try { fn() } catch (e) { console.warn('[shared_renderer] cb threw:', e) }
    }
  }

  // ── Public: stubs for out-of-plan-scope methods ───────────────────────────
  // No-op with a one-time console.warn so a missing implementation is visible
  // in DevTools without spamming the rAF loop / pointerdown handlers / load
  // pipeline. Each stub returns the type the per-instance path would return,
  // so callers fall through their `if (!result) return` guards naturally.
  const _stubWarned = new Set()
  function _outOfScope(name) {
    const fallback = _SHARED_RENDERER_STUB_DEFAULTS[name]
    return (...args) => {
      if (!_stubWarned.has(name)) {
        _stubWarned.add(name)
        console.warn(
          `[shared_renderer] '${name}' not implemented; returning default. ` +
          `Phase 3d/3e/etc. will wire it up. ` +
          `Toggle window.NADOC_SHARED_RENDERER = false for the per-instance path.`,
        )
      }
      return fallback(...args)
    }
  }

  const out = {
    rebuild,
    dispose,
    setActiveInstance,
    getBoundingBox,
    getInstanceCenters,
    invalidateInstance,
    applyInlineGeometry,
    onRebuildComplete,
    updateStrandColor,
    updateColoringMode,
    // Phase 3f — three-tier LOD ladder
    setLodThresholds,
    // Phase 3f test/instrumentation hook: drive the per-source LOD bucketing
    // from a test environment without a real render loop. Iterates every
    // active source and applies the same bucketing the onBeforeRender hook
    // would apply each frame.
    _updateLod(camera, renderer) {
      for (const srcEntry of _sources.values()) _updateLodForSource(srcEntry, camera, renderer)
    },
    _sourcesForTest() { return _sources },
    // Debug: snapshot every source's last-frame LOD bucket counts + pixel
    // thresholds + min/max pixel size.  Stashed by _updateLodForSource each
    // frame; this helper formats it into a plain object DevTools can pretty-
    // print.  Use to diagnose "why isn't bp showing when I zoom in?" —
    // compare maxPxSize against closePx to see if the angular threshold
    // is being crossed.
    probeLod() {
      const snap = { closePx: _lodClosePx, farPx: _lodFarPx, sources: [] }
      for (const [srcKey, srcEntry] of _sources.entries()) {
        const dbg = srcEntry._lastLodDebug ?? null
        const counts = srcEntry._lastLodCounts ?? null
        snap.sources.push({
          srcKey,
          numInstances: srcEntry.instanceIds.length,
          counts,
          bboxDiag: dbg?.bboxDiag ?? null,
          pxFactor: dbg?.pxFactor ?? null,
          minPxSize: dbg?.minPxSize ?? null,
          maxPxSize: dbg?.maxPxSize ?? null,
          activeMeshes: srcEntry.activeMeshes.length,
          midLodCount: srcEntry.midLod?.mesh.count ?? null,
          farLodCount: srcEntry.farLod?.mesh.count ?? null,
        })
      }
      return snap
    },
  }
  for (const name of _SHARED_RENDERER_STUB_METHODS) out[name] = _outOfScope(name)
  return out
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
  console.info('[assembly_renderer] useShared=', useShared)
  if (useShared) return _createSharedInstancingRenderer({ scene, store, api })
  return initAssemblyRenderer(scene, store, api)
}
