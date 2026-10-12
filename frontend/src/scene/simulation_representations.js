import { createSimulationAtomistic } from './simulation_atomistic.js'
import * as THREE from 'three'
import { initMdOverlay } from './md_overlay.js'
import { initMrdnaConnections } from './mrdna_connections.js'
import { initOxdnaInputOverlay } from './oxdna_input_overlay.js'
import { buildMrdnaInputPreview } from '../ui/mrdna_input_preview.js'
import { activeDesignGeometry, buildOxdnaInputPreview, applySimulationToOxdnaFrames } from '../ui/oxdna_input_preview.js'

export const SIMULATION_REPRESENTATIONS = Object.freeze(['full', 'vdw', 'ballstick', 'stick', 'oxdna', 'mrdna-coarse', 'mrdna-fine'])
export const simulationRepresentationAllowed = repr => SIMULATION_REPRESENTATIONS.includes(repr)
const comparison = repr => repr === 'oxdna' || repr.startsWith('mrdna-')
const key = n => `${n.helix_id}:${n.bp_index}:${n.direction}:${n.copy ?? 0}`
const colorKey = n => `${n.helix_id}:${n.bp_index}:${n.direction}`

// Reuse the canonical abstraction builders with Physical-layer coordinates.
// The geometry and job topology remain read-only.
export function simulationGeometry(geometry, updates) {
  const byKey = new Map(updates.map(n => [key(n), n]))
  return geometry.map(n => {
    const u = byKey.get(key(n))
    if (!u) return n
    return { ...n, ...u, axis_position: u.axis_position ?? u.cm_position ?? u.backbone_position,
      base_normal: u.base_normal ?? (Number.isFinite(u.nx) ? [u.nx,u.ny,u.nz] : n.base_normal),
      axis_tangent: u.axis_tangent ?? (Number.isFinite(u.tx) ? [u.tx,u.ty,u.tz] : n.axis_tangent) }
  })
}

export function createSimulationRepresentations({ scene, store, designRenderer, setCGVisible, getRepresentation, prepareSource = async () => {}, clearPreview = () => {}, atomisticRenderer, heavyOwner = () => false, onError = console.error, restoreRepresentation = () => {}, restoreAtoms = () => {} }) {
  const beads = initMdOverlay(scene), connections = initMrdnaConnections(scene), oxdna = initOxdnaInputOverlay(scene)
  const atoms = atomisticRenderer && createSimulationAtomistic({ renderer: atomisticRenderer, getDesign: () => designRenderer.getSimulationDesign?.() ?? store.getState().currentDesign, setCGVisible })
  let queued = false, representation = null, atomic = false, disposed = false
  const active = () => designRenderer.hasFemPositions?.() ?? !!designRenderer.getFemPositions()?.length
  const clear = () => { beads.update([]); connections.clear(); oxdna.clear(); representation = null }
  function apply(repr = getRepresentation()) {
    const updates = designRenderer.getFemPositions()
    if (!updates?.length || !comparison(repr)) { if (representation) clear(); return false }
    clearPreview()
    const state = store.getState(), geometry = activeDesignGeometry(designRenderer.getSimulationGeometry?.() ?? state.currentGeometry, designRenderer.getSimulationDesign?.() ?? state.currentDesign)
    const colors = designRenderer.getScalarColors()
    if (repr === 'oxdna') {
      beads.update([]); connections.clear()
      const preview = buildOxdnaInputPreview(geometry)
      const frames = applySimulationToOxdnaFrames(preview.frames, updates)
      oxdna.update(frames, preview.edges, state.coloringMode, state.currentDesign, { ...state, scalarColors: colors })
    } else {
      oxdna.clear()
      const projected = simulationGeometry(geometry, updates)
      const preview = buildMrdnaInputPreview(projected, repr === 'mrdna-coarse' ? 'coarse' : 'fine')
      beads.update(preview.points, repr === 'mrdna-coarse' ? .55 : .28, .95)
      const mesh = beads.mesh()
      if (mesh) {
        mesh.material.color.setHex(0xffffff)
        const color = new THREE.Color()
        for (let i = 0; i < preview.points.length; i++) {
          const values = preview.members[i].map(n => colors instanceof Map ? colors.get(colorKey(n)) : colors?.[colorKey(n)]).filter(v => v != null)
          color.setHex(values[0] ?? 0x58a6ff)
          if (values.length > 1) { color.setRGB(0,0,0); for (const value of values) color.add(new THREE.Color(value)); color.multiplyScalar(1 / values.length) }
          mesh.setColorAt(i, color)
        }
        mesh.instanceColor.needsUpdate = true
      }
      connections.update(preview.points, preview.edges)
    }
    representation = repr
    setCGVisible(false)
    return true
  }
  async function refresh(repr = getRepresentation()) {
    if (!active()) {
      const restore = representation != null; clear(); atoms?.cancel()
      if (atomic) { atomic = false; await restoreAtoms() }
      if (restore) await restoreRepresentation()
      return
    }
    if (["vdw","ballstick","stick"].includes(repr) && active() && !heavyOwner()) { atomic = true; await atoms?.apply(designRenderer.getFemPositions(), designRenderer.getScalarColors()) }
    else { atoms?.cancel(); apply(repr) }
  }
  const unsubscribe = designRenderer.subscribeSimulation?.(() => {
    if (queued) return
    queued = true
    queueMicrotask(() => { queued = false; if (disposed) return; void refresh().catch(error => onError(error.message)); window.dispatchEvent(new Event('nadoc:simulation-display')) })
  })
  let preparing = null
  function prepare() {
    if (!preparing) {
      window.dispatchEvent(new CustomEvent('nadoc:md-heavy-status', { detail: { kind: 'atomistic', building: true, mode: 'simulation' } }))
      preparing = Promise.resolve().then(prepareSource).finally(() => {
        preparing = null
        window.dispatchEvent(new CustomEvent('nadoc:md-heavy-status', { detail: { kind: 'atomistic', building: false, mode: 'simulation' } }))
      })
    }
    return preparing
  }
  const sourceChanged = () => {
    if (getRepresentation() !== 'full') void prepare().then(() => { if (!disposed) return refresh() }).catch(error => onError(error.message))
  }
  window.addEventListener('nadoc:simulation-source', sourceChanged)
  return { active, apply, refresh, clear, prepare,
    beforeChange() { atoms?.cancel(); if (representation) clear() },
    dispose() { disposed = true; unsubscribe?.(); window.removeEventListener('nadoc:simulation-source', sourceChanged); atoms?.cancel(); clear() } }
}
