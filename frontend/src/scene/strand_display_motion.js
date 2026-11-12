import * as THREE from 'three'
import { baseKey } from './base_ref.js'

const nativeIndexes = new WeakMap()
const sceneListeners = new WeakMap()
function beforeSceneRender(scene, sync) {
  let listeners = sceneListeners.get(scene)
  if (!listeners) {
    const previous = scene.onBeforeRender, callbacks = new Set()
    const hook = function (...args) {
      previous?.apply(this, args)
      for (const callback of callbacks) callback()
    }
    listeners = { previous, hook, callbacks }
    sceneListeners.set(scene, listeners); scene.onBeforeRender = hook
  }
  listeners.callbacks.add(sync)
  return () => {
    listeners.callbacks.delete(sync)
    if (!listeners.callbacks.size) {
      if (scene.onBeforeRender === listeners.hook) scene.onBeforeRender = listeners.previous
      sceneListeners.delete(scene)
    }
  }
}
const families = ['backboneEntries', 'slabEntries', 'coneEntries']
const identity = (entry, copies) => entry.nuc
  ? baseKey(entry.nuc, entry._copy ?? entry.nuc.copy_k ?? 0)
  : JSON.stringify([baseKey(entry.fromNuc, copies.get(entry.fromNuc) ?? 0), baseKey(entry.toNuc, copies.get(entry.toNuc) ?? 0)])
function index(ctrl) {
  if (nativeIndexes.has(ctrl)) return nativeIndexes.get(ctrl)
  const copies = new Map((ctrl.backboneEntries ?? []).map(e => [e.nuc, e._copy ?? e.nuc.copy_k ?? 0]))
  const result = Object.fromEntries(families.map(name => [name,
    new Map((ctrl[name] ?? []).map(e => [identity(e, copies), e])),
  ]))
  result.fluoros = new Map((ctrl.getFluoroEntries?.() ?? []).map(e => [identity(e, copies), e]))
  nativeIndexes.set(ctrl, result)
  return result
}

/** Follow the authoritative live display buffers, including rotations and rods.
 * Never copy native alpha/color: native instances yield visibility to this layer.
 * Bind once per native rebuild, then update immediately before drawing so all
 * animation callbacks have finished, including when a layer is created mid-view.
 */
export function bindStrandDisplayMotion(entry, getSource, scene) {
  let sourceCG, sourceArcs, pairs = []
  const matrix = new THREE.Matrix4()
  const copies = new Map((entry.cg.backboneEntries ?? []).map(e => [e.nuc, e._copy ?? e.nuc.copy_k ?? 0]))
  function bind(source) {
    sourceCG = source.cg; sourceArcs = source.extras?.arcData
    pairs = []
    if (!sourceCG) return
    const lookup = index(sourceCG)
    for (const family of families) for (const target of entry.cg[family] ?? []) {
      const origin = lookup[family].get(identity(target, copies))
      if (origin) pairs.push([origin, target])
    }
    for (const target of entry.cg.getFluoroEntries?.() ?? []) {
      const origin = lookup.fluoros.get(identity(target, copies))
      if (origin) pairs.push([origin, target])
    }
    const arcs = new Map((sourceArcs ?? []).map(a => [a.xoId, a]))
    for (const target of entry.extras?.arcData ?? []) {
      const origin = arcs.get(target.xoId)
      if (!origin) continue
      for (const mesh of ['beadsMesh', 'slabsMesh', 'slabConnMesh', 'connMesh']) {
        const connector = mesh === 'connMesh'
        for (let i = 0; i < target.beadCount + (connector ? 1 : 0); i++) {
          pairs.push([
            { instMesh: source.extras[mesh], id: (connector ? origin.connStartIdx : origin.beadStartIdx) + i },
            { instMesh: entry.extras[mesh], id: (connector ? target.connStartIdx : target.beadStartIdx) + i },
          ])
        }
      }
    }
  }
  function copyMesh(origin, sourceId, target, targetId) {
    if (!origin || !target) return
    origin.getMatrixAt(sourceId, matrix)
    target.setMatrixAt(targetId, matrix)
    target.instanceMatrix.needsUpdate = true
    target.boundingBox = target.boundingSphere = null
  }
  function sync() {
    const source = getSource()
    if (source?.cg !== sourceCG || source?.extras?.arcData !== sourceArcs) bind(source ?? {})
    for (const [origin, target] of pairs) {
      copyMesh(origin.instMesh, origin.id, target.instMesh, target.id)
      copyMesh(origin.connectorMesh, origin.connectorId, target.connectorMesh, target.connectorId)
      for (const field of ['pos', 'center', 'bbPos', 'midPos', 'quat', 'bnDir']) {
        if (origin[field] && target[field]) target[field].copy(origin[field])
      }
    }
  }
  // Scene hook runs before WebGLObjects uploads instance buffers. A mesh hook
  // runs after that upload and would leave the visible GPU pose one frame late.
  const unsubscribe = beforeSceneRender(scene, sync)
  sync()
  return { sync, dispose() { unsubscribe(); pairs = [] } }
}
