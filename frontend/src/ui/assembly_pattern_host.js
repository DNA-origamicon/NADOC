import * as THREE from 'three'
import { clusterLattice } from './circular_pattern_math.js'
import { matrixFromInstance } from '../scene/assembly_diff.js'
import { createAssemblyPattern, refreshAssemblyPatternContext, assemblyPatternRevision, capturePatternContext } from '../api/client.js'

/** Read-only preview adapter: instance geometry becomes a selectable whole-origami target.
 * This view model is never serialized or used as a part-authoring document. */
export function assemblyPatternView(state, renderer) {
  const assembly = state.currentAssembly
  const clusters = [], helices = [], geometry = []
  for (const instance of assembly?.instances ?? []) {
    const design = renderer?.getInstanceDesign(instance.id) ?? instance.source?.design
    const data = renderer?.getInstanceBackboneEntries(instance.id)
    if (!design || !data) continue
    const id = instance.id
    const points = data.nucleotides?.map(n => new THREE.Vector3(...n.backbone_position))
      ?? data.entries.map(e => e.pos.clone())
    if (!points.length) continue
    const matrix = instance.transform ? matrixFromInstance(instance) : data.matrixWorld
    const center = points.reduce((sum, point) => sum.addScaledVector(point, 1 / points.length), new THREE.Vector3())
    const lattice = clusterLattice({ currentDesign: design, currentHelixAxes: data.helixAxes },
      { cluster: { helix_ids: design.helices.map(h => h.id) }, center: center.toArray() })
    if (lattice) {
      lattice.u.transformDirection(matrix); lattice.v.transformDirection(matrix); lattice.normal.transformDirection(matrix)
      lattice.origin.add(center).applyMatrix4(matrix).sub(center.clone().applyMatrix4(matrix))
    }
    clusters.push({ id, name: instance.name, helix_ids: [id], patternLattice: lattice })
    helices.push({ id, length_bp: (design.helices ?? []).reduce((sum, h) => sum + h.length_bp, 0) })
    for (const point of points) geometry.push({ helix_id: id, backbone_position: point.applyMatrix4(matrix).toArray() })
  }
  // Do not display partial targets or misleading totals while sources are loading.
  if (clusters.length !== (assembly?.instances.length ?? 0)) { clusters.length = 0; geometry.length = 0 }
  return { currentDesign: { id: assembly?.id, cluster_transforms: clusters, helices }, currentGeometry: geometry }
}

export function createAssemblyPatternHost({ store, getAssemblyRenderer, kind, commitPattern }) {
  let source, view
  function getState() {
    const state = store.getState()
    if (!state.assemblyActive) return state
    if (source !== state.currentAssembly || !view?.currentGeometry.length) {
      source = state.currentAssembly
      view = assemblyPatternView(state, getAssemblyRenderer?.())
    }
    return { ...state, ...view, assemblyActive: false, patternAssembly: source,
      activeClusterId: state.activeInstanceId, currentHelixAxes: null,
      selection: { context: 'design', level: 'cluster', items: [] } }
  }
  return {
    prepare: () => store.getState().assemblyActive ? refreshAssemblyPatternContext(store.getState().currentAssembly) : true,
    isAssembly: () => !!store.getState().assemblyActive,
    store: { getState, setState: patch => store.setState(patch), subscribe: fn => store.subscribe(() => fn(getState())) },
    capture(state) {
      return state.patternAssembly ? { source: state.currentDesign, assembly: state.patternAssembly, revision: assemblyPatternRevision() } : capturePatternContext(state)
    },
    commit(body, context) {
      if (!context?.assembly) return commitPattern(body, context)
      if (!store.getState().assemblyActive || store.getState().currentAssembly !== context.assembly)
        throw new Error('The assembly changed. Reopen the pattern tool.')
      const { cluster_ids, cluster_id, ...parameters } = body
      return createAssemblyPattern(kind, { instance_ids: cluster_ids ?? [cluster_id], parameters,
        expected_assembly_id: context.assembly.id, expected_revision: context.revision,
        expected_feature_ids: (context.assembly.feature_log ?? []).map(e => e.id) })
    },
  }
}
