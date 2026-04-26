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
 * Usage:
 *   const ar = initAssemblyRenderer(scene, store, api)
 *   ar.rebuild(assembly)          // call whenever currentAssembly changes
 *   ar.setActiveInstance(id)      // adds white BoxHelper around selected part
 *   ar.dispose()                  // removes all instance groups from scene
 */

import * as THREE from 'three'
import { buildHelixObjects, buildStapleColorMap } from './helix_renderer.js'
import { buildCrossoverConnections } from './crossover_connections.js'
import { initAtomisticRenderer } from './atomistic_renderer.js'
import { BDNA_RISE_PER_BP } from '../constants.js'
import {
  buildBundleGeometry, buildPrismGeometry, buildPanelSurface,
  buildSpineSections, buildSweptHullGeometry, buildHullMeshPhong,
  HULL_OPACITY, CROSS_MARGIN, AXIAL_MARGIN, MIN_HC_FACES,
} from './joint_renderer.js'

// Maps representation name → setDetailLevel argument (CG reprs only).
const _CG_LOD = { full: 0, beads: 1, cylinders: 2 }

// Arc vertex count — matches unfold_view.js for visual consistency.
const _ARC_SEGS = 20

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
    return line
  }

  const group        = new THREE.Group()
  const scaffoldLine = _buildMerged(scaffoldConns, 'scaffold')
  const stapleLine   = _buildMerged(stapleConns, 'staple')
  if (scaffoldLine) group.add(scaffoldLine)
  if (stapleLine)   group.add(stapleLine)
  if (!group.children.length) return null
  return group
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
  //            hullGroups, design, helixAxes }
  const _cache        = new Map()
  let _boxHelper      = null
  let _boxHelperGroup = null   // which group the box helper currently tracks
  const _rc           = new THREE.Raycaster()

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
    for (const ax of raw) map[ax.helix_id] = { start: ax.start, end: ax.end, samples: ax.samples ?? null }
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
      grp.traverse(o => { o.geometry?.dispose(); o.material?.dispose() })
    }
    entry.group.traverse(obj => {
      if (obj.geometry) obj.geometry.dispose()
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
        mats.forEach(m => m.dispose())
      }
    })
    scene.remove(entry.group)
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
      grp.traverse(o => { o.geometry?.dispose(); o.material?.dispose() })
      entry.group.remove(grp)
    }
    entry.hullGroups = []
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
      entry.helixCtrl?.setDetailLevel(lod)

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

  /** Cheap string key to detect source changes without deep-comparing designs. */
  function _sourceKey(inst) {
    if (!inst?.source) return 'none'
    if (inst.source.type === 'file') return `file:${inst.source.path ?? ''}`
    // inline: use embedded design id — changes if user swaps the design
    return `inline:${inst.source.design?.id ?? ''}`
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
   */
  function _computeGroupBox(group) {
    const box = new THREE.Box3()
    group.traverse(obj => {
      if (!obj.visible) return
      if (obj instanceof THREE.InstancedMesh && obj.count > 0) {
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

  // ── Public: setActiveInstance ─────────────────────────────────────────────

  function setActiveInstance(id) {
    _attachBoxHelper(id ? (_cache.get(id)?.group ?? null) : null)
  }

  // ── Public: rebuild ───────────────────────────────────────────────────────

  async function rebuild(assembly) {
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

    // Batch-fetch geometry for all instances that need it (one HTTP request)
    let batchGeo = null
    if (needsGeometry.length > 0) {
      try {
        batchGeo = await api.getAssemblyGeometry()
      } catch (err) {
        console.warn('[assembly_renderer] batch geometry fetch failed:', err)
        // Fall back to per-instance fetches so a single server error doesn't black-out everything
        batchGeo = null
      }
    }

    for (const inst of needsGeometry) {
      const transformKey = JSON.stringify(inst.transform?.values ?? null)
      const sourceKey    = _sourceKey(inst)
      const existing     = _cache.get(inst.id)

      let geoData, design
      if (batchGeo?.instances?.[inst.id] && !batchGeo.instances[inst.id].error) {
        const entry = batchGeo.instances[inst.id]
        geoData = { nucleotides: entry.nucleotides, helix_axes: _axesArrayToMap(entry.helix_axes) }
        design  = entry.design ?? null
      } else {
        // Per-instance fallback
        try {
          const [geo, designJson] = await Promise.all([
            api.getInstanceGeometry(inst.id),
            api.getInstanceDesign(inst.id),
          ])
          geoData = { nucleotides: geo?.nucleotides, helix_axes: _axesArrayToMap(geo?.helix_axes) }
          design  = designJson?.design ?? null
        } catch (err) {
          console.warn(`[assembly_renderer] failed to load instance ${inst.id}:`, err)
          continue
        }
      }

      if (!geoData || !design) continue

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
      const helixCtrl    = buildHelixObjects(nucleotides, design, instanceGroup, customColors, [], helixAxes)

      // Crossover arc lines — straight colored lines in instance-local space.
      // Added to helixCtrl.root so they hide/show with the CG representation.
      const arcGroup = _buildInstanceCrossoverArcs(helixCtrl.getCrossHelixConnections())
      if (arcGroup) helixCtrl.root.add(arcGroup)

      // Extra-base bead/slab meshes for crossovers with extra bases.
      const colorMap    = buildStapleColorMap(nucleotides, design)
      const xoverResult = buildCrossoverConnections(design, nucleotides, colorMap, customColors)
      if (xoverResult) helixCtrl.root.add(xoverResult.group)

      instanceGroup.visible = inst.visible !== false
      scene.add(instanceGroup)

      if (helixAxes) _helixAxesCache.set(inst.id, helixAxes)
      _instTransformCache.set(inst.id, inst.transform?.values ?? null)

      const reprKey = inst.representation ?? 'full'
      const entry   = {
        group: instanceGroup, transformKey, sourceKey, reprKey,
        helixCtrl, atomisticRenderer: null, hullGroups: [],
        design, helixAxes,
      }
      _cache.set(inst.id, entry)

      // Apply representation (async for atomistic — fire-and-forget; CG is synchronous)
      _applyRepresentation(entry, inst.id, reprKey)
    }

    // Restore box helper if active instance group was just rebuilt
    const activeId = store.getState().activeInstanceId
    if (activeId && _cache.has(activeId)) {
      _attachBoxHelper(_cache.get(activeId).group)
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
      if (obj.geometry) obj.geometry.dispose()
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
        mats.forEach(m => m.dispose())
      }
    })
    while (_linkerGroup.children.length) _linkerGroup.remove(_linkerGroup.children[0])

    if (!assembly) return

    // ── Linker helices — full nucleotide geometry from backend ─────────────────
    const linkerHelices = assembly.assembly_helices ?? []
    if (linkerHelices.length > 0) {
      let geoData = null
      try { geoData = await api.getLinkerGeometry() } catch (_) {}
      if (geoData?.nucleotides?.length) {
        const syntheticDesign = {
          helices:    linkerHelices,
          strands:    assembly.assembly_strands ?? [],
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
    if (_boxHelper) {
      scene.remove(_boxHelper)
      _boxHelper.geometry?.dispose()
      _boxHelper.material?.dispose()
      _boxHelper = null
      _boxHelperGroup = null
    }
    for (const entry of _cache.values()) _disposeGroup(entry)
    _cache.clear()
    _helixAxesCache.clear()
    _instTransformCache.clear()
    // Clear linker group
    _linkerGroup.traverse(obj => {
      if (obj.geometry) obj.geometry.dispose()
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

  function invalidateInstance(id) {
    const entry = _cache.get(id)
    if (!entry) return
    _disposeGroup(entry)
    _cache.delete(id)
    _helixAxesCache.delete(id)
    _instTransformCache.delete(id)
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

          const { pos: localPos, dir: localAxisDir } = _posAlongHelix(h, tArc)
          const localNorm = localAxisDir.clone()
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
            isBluntEnd:   true,
          })
        }
      }
    }

    return results
  }

  return { rebuild, rebuildLinkers, setActiveInstance, setLiveTransform, pickInstance, dispose, getBoundingBox, invalidateInstance, getInstanceBluntEnds }
}
