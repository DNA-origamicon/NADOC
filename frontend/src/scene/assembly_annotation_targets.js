/** Assembly-owned annotation identity and live target resolution. */
import { normalizeAssemblyAnnotationRef } from './assembly_annotation_refs.js'
import { Vector3 } from 'three'
import { computeGroupHiddenInstanceIds } from './assembly_groups_util.js'
import { matchTargetEntries } from './annotation_targets.js'

export function createAssemblyAnnotationTargets({ store, getRenderer }) {
  const cache = new Map()
  const empty = []
  const sourceEntries = new WeakMap()
  function resolve(ref) {
    const state = store.getState(), renderer = getRenderer()
    const inst = state.currentAssembly?.instances?.find(i => i.id === ref.instanceId)
    if (!inst || inst.visible === false || computeGroupHiddenInstanceIds(state.currentAssembly).has(inst.id)) return empty
    let data = renderer?.getInstanceBackboneEntries?.(inst.id)
    const design = renderer?.getInstanceDesign?.(inst.id)
    // Hull/cylinder sources deliberately omit bead meshes. Target identity and
    // positions must not depend on those display allocations.
    if (!data?.entries?.length && data?.nucleotides?.length) {
      const nucs = data.nucleotides
      let entries = sourceEntries.get(nucs)
      if (!entries) {
        entries = nucs.filter(n => n.strand_id && n.backbone_position).map(nuc => ({ nuc, pos: new Vector3(...nuc.backbone_position) }))
        sourceEntries.set(nucs, entries)
      }
      data = { entries, matrixWorld: renderer.getLiveTransform?.(inst.id) ?? data?.matrixWorld }
    }
    if (!data?.entries?.length || !data.matrixWorld) return empty
    const key = JSON.stringify(ref)
    let row = cache.get(key)
    if (!row || row.src !== data.entries || row.design !== design) {
      const entries = ref.kind === 'assembly-part' ? data.entries
        : matchTargetEntries([{ kind: 'overhang', id: ref.overhangId }], design, data.entries)
      row = { src: data.entries, design, local: entries, world: entries.map(e => ({ nuc: e.nuc, pos: e.pos.clone() })) }
      cache.set(key, row)
    }
    row.local.forEach((e, i) => row.world[i].pos.copy(e.pos).applyMatrix4(data.matrixWorld))
    return row.world
  }
  const targetCache = new WeakMap()
  return {
    resolve(refs) {
      const parts = refs.map(ref => normalizeAssemblyAnnotationRef(ref) ? resolve(ref) : empty)
      let row = targetCache.get(refs)
      if (!row || parts.some((p, i) => row.parts[i] !== p)) {
        row = { parts, entries: parts.flat() }; targetCache.set(refs, row)
      }
      return row.entries
    },
    // Occupancy uses one bounding sphere per visible part, avoiding expansion of
    // every source bead across large assemblies merely to place a text box.
    occluders() {
      return (getRenderer()?.getInstanceCenters?.() ?? []).map(p => ({ x: p.center.x, y: p.center.y, z: p.center.z, radius: p.radius ?? 1 }))
    },
    clear() { cache.clear() },
  }
}
