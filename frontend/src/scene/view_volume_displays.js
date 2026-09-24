import { coarseVolumePicker } from './volume_render_adapter.js'
import { baseKey } from './base_ref.js'
import { clusterAlphaKeys } from './cluster_entries.js'
import * as THREE from 'three'
import { buildHelixObjects, buildStapleColorMap, buildNucLetterMap } from './helix_renderer.js'
import { initAtomisticRenderer } from './atomistic_renderer.js'
import { initSurfaceRenderer } from './surface_renderer.js'
import { filterAtomData } from './atom_filter.js'
import { atomColorsFromLetters, computeAtomStrandColors, computeAtomNucColors, computeAtomNucAlphas, computeAtomStrandAlphas } from './color_util.js'
import { coloringFallbackMode } from './coloring_modes.js'

/** A volume is a display layer with its own coloring and opacity, even on overlap. */
export function initViewVolumeDisplays({ scene, store, api, ensureAtoms, getHiddenNucs = () => new Set(), onError = console.error }) {
  const entries = new Map()
  let generation = 0, layers = []
  const stage = (kind, phase, revision) => window.dispatchEvent(new CustomEvent('nadoc:view-volume-stage', {
    detail: { stage: `${kind}-${phase}`, revision, viewVolume: true },
  }))
  function remove(entry) {
    entry.abort.abort()
    if (entry.renderer) entry.renderer.dispose()
    else entry.root.traverse(o => {
      if (o.geometry && !o.geometry.userData?.shared) o.geometry.dispose()
      for (const m of Array.isArray(o.material) ? o.material : o.material ? [o.material] : []) m.dispose()
      if (o.isInstancedMesh) o.dispose()
    })
    entry.root.removeFromParent()
  }
  function paint(entry, layer) {
    const original = store.getState(), mode = coloringFallbackMode(layer.representation, layer.coloring ?? 'strand') ?? layer.coloring ?? 'strand'
    const state = { ...original, coloringMode: mode }, design = state.currentDesign, geometry = state.currentGeometry ?? []
    const strands = computeAtomStrandColors(state, buildStapleColorMap(geometry, design))
    const nucColors = computeAtomNucColors(state), nucAlphas = computeAtomNucAlphas(design)
    const hidden = getHiddenNucs(), hideReference = state.showReferenceGeometry === false || state.simulationTabActive === true
    const references = new Set((design.strands ?? []).filter(s => s.is_reference).map(s => s.id))
    for (const n of geometry) {
      if (hidden.has(baseKey(n, n.copy_k ?? 0)) || hidden.has(`h:${n.helix_id}`) || hidden.has(`d:${n.strand_id}:${n.domain_index}`) || (hideReference && references.has(n.strand_id))) {
        nucAlphas.set(`${n.helix_id}:${n.bp_index}:${n.direction}`, 0)
      }
    }
    if (entry.cg) {
      entry.cg.setReferenceStrands(references)
      entry.cg.setReferenceHidden(hideReference)
      entry.cg.setHiddenNucs(hidden)
      entry.cg.applyColoring(mode, design, Object.fromEntries(strands), state.loopStrandIds)
      entry.cg.setClusterAlphas(clusterAlphaKeys(design))
      entry.cg.applyRepOverrides(entry.columns)
      entry.root.traverse(o => {
        for (const m of Array.isArray(o.material) ? o.material : o.material ? [o.material] : []) {
          m.opacity = layer.opacity; m.transparent = true
        }
      })
    } else if (entry.kind === 'surface') {
      entry.renderer.applyStrandColors(strands)
      entry.renderer.applyClusterDisplay({ nucColors, nucAlphas, strandColors: mode === 'cluster' ? strands : null, strandAlphas: computeAtomStrandAlphas(design) })
      entry.renderer.setOpacity(layer.opacity)
    } else {
      const bases = mode === 'base' ? atomColorsFromLetters(buildNucLetterMap(design, geometry), geometry) : null
      entry.renderer.setColorMode(mode === 'cluster' ? 'strand' : mode, strands, bases)
      entry.renderer.setClusterDisplay(nucAlphas, nucColors)
      entry.root.traverse(o => {
        for (const m of Array.isArray(o.material) ? o.material : o.material ? [o.material] : []) { m.opacity = layer.opacity; m.transparent = true }
      })
    }
  }
  async function update(next = layers) {
    layers = next
    const revision = ++generation, state = store.getState(), design = state.currentDesign
    if (state.assemblyActive || !design) layers = []
    const ids = new Set(layers.map(layer => layer.id))
    for (const [id, entry] of entries) if (!ids.has(id)) { remove(entry); entries.delete(id) }
    const pending = { atom: [], surface: [] }
    for (const layer of layers) {
      const kind = layer.representation === 'surface' ? 'surface' : ['vdw', 'ballstick', 'stick'].includes(layer.representation) ? 'atom' : 'cg'
      const signature = JSON.stringify([layer.representation, layer.keys])
      let entry = entries.get(layer.id)
      if (entry && (entry.signature !== signature || entry.geometry !== state.currentGeometry || entry.axes !== state.currentHelixAxes)) {
        remove(entry); entries.delete(layer.id); entry = null
      }
      if (entry?.ready) { paint(entry, layer); continue }
      if (entry) { remove(entry); entries.delete(layer.id) }
      if (!design || !layer.keys?.length) continue
      const root = new THREE.Group(); root.name = `view-volume-display-${layer.id}`; scene.add(root)
      entry = { root, signature, geometry: state.currentGeometry, axes: state.currentHelixAxes, abort: new AbortController(), kind, representation: layer.representation, ready: false }
      entries.set(layer.id, entry)
      const keys = new Set(layer.keys)
      const current = () => !entry.abort.signal.aborted && entries.get(layer.id) === entry
      if (kind === 'cg') {
        const geometry = state.currentGeometry ?? []
        entry.cg = buildHelixObjects(geometry, design, root, {}, state.loopStrandIds, state.currentHelixAxes, layer.representation)
        const columns = new Map(geometry.map(n => [`${n.helix_id}:${n.bp_index}`, 'surface']))
        for (const key of keys) columns.set(key, layer.representation === 'cylinders' ? 'cylinders' : 'full')
        entry.cg.setReferenceStrands(new Set((design.strands ?? []).filter(s => s.is_reference).map(s => s.id)))
        entry.cg.setDetailLevel(layer.representation === 'cylinders' ? 2 : layer.representation === 'beads' ? 1 : 0)
        entry.columns = columns
        entry.cg.applyRepOverrides(columns)
        entry.ready = true; paint(entry, layer)
        entry.picker = coarseVolumePicker(entry, keys, geometry)
      } else {
        const work = (async () => {
          if (kind === 'atom') {
            const data = await ensureAtoms()
            if (!data || !current()) return
            entry.renderer = initAtomisticRenderer(root, { independentColors: true })
            entry.renderer.update(filterAtomData(data, keys, layer.representation !== 'vdw'))
            entry.renderer.setMode(layer.representation)
          } else {
            const mesh = await api.getRegionSurface(layer.segments, { colorMode: 'strand', signal: entry.abort.signal, suppressBusy: true })
            if (!current()) return
            entry.renderer = initSurfaceRenderer(root)
            entry.renderer.update(mesh, 'strand', `volume-surface-${layer.id}`)
          }
          entry.ready = true; paint(entry, layer)
        })()
        pending[kind].push(work)
      }
    }
    await Promise.all(Object.entries(pending).map(async ([kind, work]) => {
      stage(kind, work.length ? 'scheduled' : 'cleared', revision)
      try { await Promise.all(work); if (work.length && revision === generation) stage(kind, 'applied', revision) }
      catch (error) { if (revision === generation && error.name !== 'AbortError') { stage(kind, 'failed', revision); onError(error) } }
    }))
  }
  const unsubscribe = store.subscribe((n, p) => {
    if (n.assemblyActive !== p.assemblyActive || !n.currentDesign) { void update(n.assemblyActive ? [] : layers); return }
    if (n.strandColors !== p.strandColors || n.strandGroups !== p.strandGroups || n.loopStrandIds !== p.loopStrandIds || n.showReferenceGeometry !== p.showReferenceGeometry || n.simulationTabActive !== p.simulationTabActive) {
      for (const layer of layers) { const entry = entries.get(layer.id); if (entry?.ready) paint(entry, layer) }
    }
  })
  return { update, entries,
    atomRenderers: rep => [...entries.values()].filter(e => e.ready && (e.representation === rep || (rep === 'vdw' && e.cg))).map(e => e.renderer ?? e.picker),
    surfaceRenderers: () => [...entries.values()].filter(e => e.ready && e.kind === 'surface').map(e => e.renderer),
    highlight(selection) { for (const entry of entries.values()) entry.renderer?.highlight?.(selection) },
    repaint() { for (const layer of layers) { const entry = entries.get(layer.id); if (entry?.ready) paint(entry, layer) } }, dispose() { generation++; unsubscribe?.(); for (const entry of entries.values()) remove(entry); entries.clear() } }
}
