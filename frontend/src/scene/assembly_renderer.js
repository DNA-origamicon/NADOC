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
import { buildHelixObjects } from './helix_renderer.js'

export function initAssemblyRenderer(scene, store, api) {
  // instId → { group: THREE.Group, transformKey: string, sourceKey: string }
  const _cache        = new Map()
  let _boxHelper      = null
  let _boxHelperGroup = null   // which group the box helper currently tracks

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
    entry.group.traverse(obj => {
      if (obj.geometry) obj.geometry.dispose()
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
        mats.forEach(m => m.dispose())
      }
    })
    scene.remove(entry.group)
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
    //   - transform-only changes (fast path: no fetch needed)
    //   - geometry changes (need batch fetch)
    const needsGeometry = []
    for (const inst of instances) {
      const transformKey = JSON.stringify(inst.transform?.values ?? null)
      const sourceKey    = _sourceKey(inst)
      const existing     = _cache.get(inst.id)

      if (existing) {
        // Fast path: only transform changed
        if (existing.sourceKey === sourceKey && existing.transformKey !== transformKey) {
          _applyTransform(existing.group, inst.transform?.values)
          existing.transformKey = transformKey
          _instTransformCache.set(inst.id, inst.transform?.values ?? null)
          if (_boxHelperGroup === existing.group) {
            _attachBoxHelper(existing.group)
          }
        }
        existing.group.visible = inst.visible !== false
        if (existing.sourceKey === sourceKey) continue
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
      buildHelixObjects(geoData.nucleotides ?? [], design, instanceGroup, customColors, [], helixAxes)

      instanceGroup.visible = inst.visible !== false
      scene.add(instanceGroup)

      if (helixAxes) _helixAxesCache.set(inst.id, helixAxes)
      _instTransformCache.set(inst.id, inst.transform?.values ?? null)

      _cache.set(inst.id, { group: instanceGroup, transformKey, sourceKey })
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

  return { rebuild, rebuildLinkers, setActiveInstance, dispose, getBoundingBox, invalidateInstance }
}
