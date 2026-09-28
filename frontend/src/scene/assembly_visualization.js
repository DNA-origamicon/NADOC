import * as THREE from 'three'
import { createAssemblyRenderer } from './assembly_renderer.js'
import { computeGroupHiddenInstanceIds } from './assembly_groups_util.js'
import { initViewVolumeDisplays } from './view_volume_displays.js'
import { _hullGeoForSource } from './assembly_hull_geometry.js'
import { applyHullCutouts, hullCutoutSpec } from './hull_volume_cutouts.js'
import { initMrdnaDisplay } from '../ui/mrdna_display.js'
import { initMdOverlay } from './md_overlay.js'
import { initMrdnaConnections } from './mrdna_connections.js'
import { initOxdnaInputOverlay } from './oxdna_input_overlay.js'
import { segmentsForKeys, resolveViewVolumeLayers, activeViewVolumes } from './view_volumes.js'
import { withSkippedColumnPoints } from './view_volume_points.js'

const preview = rep => ['mrdna-coarse', 'mrdna-fine', 'oxdna'].includes(rep)
const prefix = id => `${encodeURIComponent(id)}|`
export function assemblyVolumePoints(assembly, renderer) {
  const hidden = computeGroupHiddenInstanceIds(assembly), points = []
  for (const inst of assembly?.instances ?? []) {
    if (inst.visible === false || hidden.has(inst.id)) continue
    const data = renderer.getInstanceRenderData(inst.id)
    const matrix = renderer.getLiveTransform(inst.id)
    if (!data || !matrix) continue
    const local = withSkippedColumnPoints((data.nucleotides ?? []).map(n => ({ key: `${n.helix_id}:${n.bp_index}`, position: n.backbone_position })), data.design?.helices)
    for (const p of local) if (p.position) points.push({ key: prefix(inst.id) + p.key, position: new THREE.Vector3(...p.position).applyMatrix4(matrix).toArray() })
  }
  return points
}

/** Independent display scenes: never change authored instance representations or the part store. */
export async function buildAssemblyVisualization({ state, api, sourceScene, representation, coloring = state.coloringMode ?? 'strand', layers = null }) {
  const scene = new THREE.Scene(), disposers = []
  scene.name = 'assembly-visualization'
  scene.background = sourceScene?.background?.clone?.() ?? null
  if (sourceScene) for (const o of sourceScene.children) if (o.isLight) scene.add(o.clone())
  scene.disposeVisualization = () => { for (const dispose of disposers) dispose(); scene.clear() }
  const hidden = computeGroupHiddenInstanceIds(state.currentAssembly)
  const assembly = { ...state.currentAssembly, instances: (state.currentAssembly?.instances ?? []).map(i => ({ ...i, visible: i.visible !== false && !hidden.has(i.id), representation: representation ?? i.representation })) }
  const localState = { ...state, currentAssembly: assembly, coloringMode: coloring }
  const localStore = { getState: () => localState, subscribe: () => () => {} }
  try {
    let data = null
    if (layers || activeViewVolumes(assembly.view_volumes).length) {
      data = await api.getAssemblyGeometry()
      const byId = new Map(assembly.instances.map(i => [i.id, i]))
      const points = assemblyVolumePoints(assembly, {
        getInstanceRenderData: id => data.instances?.[id],
        getLiveTransform: id => new THREE.Matrix4().fromArray(byId.get(id).transform.values).transpose(),
      })
      const bounds = new THREE.Box3().setFromPoints(points.map(p => new THREE.Vector3(...p.position)))
      if (!bounds.isEmpty()) scene.visualizationBounds = bounds.expandByScalar(2)
      layers ??= resolveViewVolumeLayers(activeViewVolumes(assembly.view_volumes), points).map(({ volume, keys }) => ({
        ...volume, volume, keys: [...keys],
      }))
      scene.visualizationLayers = layers.map(({ id, representation }) => ({ id, representation }))
    }
    const outlines = sourceScene?.getObjectByName('view-volumes')?.clone(true)
    if (outlines) {
      outlines.traverse(o => {
        if (o.geometry) { o.geometry = o.geometry.clone(); disposers.push(() => o.geometry.dispose()) }
        if (o.material) { o.material = o.material.clone(); disposers.push(() => o.material.dispose()) }
      })
      scene.add(outlines)
    }

    if (!layers && !preview(representation)) {
      const renderer = createAssemblyRenderer({ scene, store: localStore, api, useShared: true })
      disposers.push(() => renderer.dispose())
      await renderer.rebuild(assembly); await renderer.rebuildLinkers(assembly)
      scene.visualizationBounds = renderer.getBoundingBox()?.clone()
      return scene
    }
    if (layers && !preview(representation)) {
      const affected = new Set(layers.flatMap(l => l.keys).map(k => k.slice(0, k.indexOf('|'))))
      for (const inst of assembly.instances) if (inst.representation === 'hull-prism') affected.add(encodeURIComponent(inst.id))
      const untouched = { ...assembly, instances: assembly.instances.filter(i => !affected.has(encodeURIComponent(i.id))) }
      const renderer = createAssemblyRenderer({ scene, store: { getState: () => ({ ...localState, currentAssembly: untouched }), subscribe: () => () => {} }, api: { ...api, getAssemblyGeometry: async () => data }, useShared: true })
      disposers.push(() => renderer.dispose())
      await renderer.rebuild(untouched); await renderer.rebuildLinkers(assembly)
      assembly.instances = assembly.instances.filter(i => affected.has(encodeURIComponent(i.id)))
    }
    data ??= await api.getAssemblyGeometry()
    for (const inst of assembly.instances) {
      if (!inst.visible) continue
      const record = data.instances?.[inst.id]
      if (!record?.design) throw new Error(record?.error ?? `No geometry for ${inst.name ?? inst.id}`)
      const group = new THREE.Group(); group.name = `assembly-view-${inst.id}`
      group.matrixAutoUpdate = false
      if (inst.transform?.values) group.matrix.fromArray(inst.transform.values).transpose()
      scene.add(group)
      const sourceState = { ...localState, assemblyActive: false, currentDesign: record.design, currentGeometry: record.nucleotides, currentHelixAxes: record.helix_axes }
      const sourceStore = { getState: () => sourceState, subscribe: () => () => {} }
      const allKeys = new Set(withSkippedColumnPoints((record.nucleotides ?? []).map(n => ({ key: `${n.helix_id}:${n.bp_index}`, position: n.backbone_position })), record.design.helices).map(p => p.key))
      const selected = (layers ?? []).map(layer => ({ ...layer, keys: layer.keys.filter(k => k.startsWith(prefix(inst.id))).map(k => k.slice(prefix(inst.id).length)) }))
      const covered = new Set(selected.flatMap(layer => layer.keys)), baseKeys = [...allKeys].filter(k => !covered.has(k))
      const rep = inst.representation ?? 'full'
      if (preview(rep)) {
        const beads = initMdOverlay(group), bonds = initMrdnaConnections(group), oxdna = initOxdnaInputOverlay(group)
        const display = initMrdnaDisplay({ beadOverlay: beads, connectionOverlay: bonds, oxdnaInputOverlay: oxdna, designRenderer: {}, api: {}, setDesignVisible: () => {} })
        const geometry = record.nucleotides.filter(n => !covered.has(`${n.helix_id}:${n.bp_index}`))
        if (rep === 'oxdna') display.showOxdnaInputPreview(geometry, record.design, coloring, false, sourceState)
        else display.showInputPreview(geometry, rep === 'mrdna-coarse' ? 'coarse' : 'fine')
        disposers.push(() => { beads.dispose(); bonds.clear(); oxdna.dispose() })
      } else if (rep === 'hull-prism') {
        const hull = _hullGeoForSource(record.design, record.nucleotides, record.helix_axes)
        if (hull?.solid) {
          const material = new THREE.MeshLambertMaterial({ color: 0x9a9a9a, side: THREE.DoubleSide })
          const spec = hullCutoutSpec((layers ?? []).map(l => l.volume)).map(v => ({ ...v, inverse: new THREE.Matrix4().fromArray(v.inverse).multiply(group.matrix).toArray() }))
          applyHullCutouts(material, spec)
          group.add(new THREE.Mesh(hull.solid, material)); disposers.push(() => { hull.solid.dispose(); hull.markers?.dispose(); material.dispose() })
          if (hull.markers) {
            const markers = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 })
            applyHullCutouts(markers, spec)
            group.add(new THREE.Mesh(hull.markers, markers)); disposers.push(() => markers.dispose())
          }
        }
      } else selected.unshift({ id: 'base', keys: baseKeys, representation: rep, coloring, opacity: 1 })
      const displays = initViewVolumeDisplays({ scene: group, store: sourceStore,
        api: { getRegionSurface: (segments, opts) => api.getInstanceRegionSurface(inst.id, segments, opts) },
        ensureAtoms: () => api.getInstanceAtomisticGeometry(inst.id), onError: error => { throw error } })
      disposers.push(() => displays.dispose())
      await displays.update(selected.map(layer => ({ ...layer, allColumnKeys: [...allKeys], segments: segmentsForKeys(layer.keys) })))
    }
    return scene
  } catch (error) { scene.disposeVisualization(); throw error }
}

/** Assembly display ownership: reveal instances/groups without writing a part. */
export async function unhideAssemblyVisualization({ store, api }) {
  const assembly = store.getState().currentAssembly
  const hidden = (assembly?.instances ?? []).filter(i => i.visible === false)
  if (hidden.length) await api.batchPatchInstances(hidden.map(i => ({ id: i.id, visible: true })))
  for (const group of assembly?.groups ?? []) if (group.visible === false) await api.patchGroup(group.id, { visible: true })
}
