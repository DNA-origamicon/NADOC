/**
 * Assembly-view periodic-seam arrows — glowing yellow arrows marking forced
 * ligations flagged is_periodic_seam, drawn per instance in assembly world space.
 *
 * Renderer-agnostic (works with both the shared-instancing and legacy assembly
 * renderers) because it is a standalone scene overlay, modeled on
 * assembly_joint_renderer.js: it fetches per-instance geometry (nucleotides +
 * design) and transforms each instance's local arrows into world space via the
 * instance transform — the same `_instMat4` pattern joint indicators use.
 *
 * Arrow geometry/colors are owned by seam_arrows.buildSeamArrows (shared with the
 * single-design view). Per-instance arrows are built in local coords, then the
 * whole group is moved by the instance transform.
 */

import * as THREE from 'three'
import { buildSeamArrows } from './seam_arrows.js'

export function initAssemblySeamArrows(scene, store, api) {
  const _group = new THREE.Group()
  _group.name = 'assemblySeamArrows'
  scene.add(_group)
  let _visible = store.getState().showSeamArrows !== false
  let _rebuildToken = 0   // guards against overlapping async rebuilds

  function _instMat4(inst) {
    const m = new THREE.Matrix4()
    if (inst?.transform?.values) m.fromArray(inst.transform.values).transpose()
    return m
  }

  function _clear() {
    for (const child of [..._group.children]) {
      child.traverse(o => {
        o.geometry?.dispose?.()
        if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => m.dispose())
      })
      _group.remove(child)
    }
  }

  async function rebuild(assembly) {
    const token = ++_rebuildToken
    _clear()
    const insts = assembly?.instances ?? []
    if (!insts.length) return

    let batch = null
    try { batch = await api.getAssemblyGeometry() } catch { /* fall back to per-instance */ }
    if (token !== _rebuildToken) return   // a newer rebuild superseded us

    for (const inst of insts) {
      let geo = batch?.instances?.[inst.id]
      if (!geo || geo.error) {
        try { geo = await api.getInstanceGeometry(inst.id) } catch { continue }
        if (token !== _rebuildToken) return
      }
      const arrows = buildSeamArrows(geo?.design, geo?.nucleotides ?? [])
      if (!arrows) continue
      arrows.applyMatrix4(_instMat4(inst))   // instance-local → assembly world
      _group.add(arrows)
    }
    _group.visible = _visible
  }

  function setVisible(v) {
    _visible = v
    _group.visible = v
  }

  function dispose() {
    _rebuildToken++
    _clear()
    scene.remove(_group)
  }

  return { rebuild, setVisible, dispose }
}
