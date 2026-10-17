/** Private, complete native Full display. All mutable renderer inputs and
 * companions belong to this pane; no canonical renderer/store is installed. */
import * as THREE from 'three'
import { validateTransformPreviewComponent } from '../features/transform_preview_display.js'
import { buildHelixObjects } from './helix_renderer.js'
import { _resetStapleColorPins, buildStapleColorMap } from './helix_renderer/palette.js'
import { buildCrossoverConnections, simBeadIndex } from './crossover_connections.js'
import { createCpdSlabBonds } from './cpd_slab_bonds.js'
import { initPhotoproductOverlay } from './photoproduct_overlay.js'
import { initFlexibleArcs } from './flexible_arcs.js'
import { initOverhangLinkArcs, linkerLengthToBases } from './overhang_link_arcs.js'
import { buildNativeConnectionLines, writeNativeConnectionArc } from './native_connection_lines.js'
import { createDeformationPreviewCamera } from './deformation_preview_camera.js'
import { baseKey, xbKey } from './base_ref.js'

const fail = message => { throw new Error(`Transform display incomplete: ${message}`) }
const pair = (a, b) => JSON.stringify([baseKey(a), baseKey(b)].sort())
const endNuc = (c, p) => ({ helix_id: c[`${p}_helix_id`], bp_index: c[`${p}_bp`], direction: c[`${p}_direction`] })
const halfNuc = h => ({ helix_id: h.helix_id, bp_index: h.index, direction: h.strand })
const junctionPair = c => c.half_a ? pair(halfNuc(c.half_a), halfNuc(c.half_b)) : pair(endNuc(c, 'three_prime'), endNuc(c, 'five_prime'))

function disposeRoot(root) {
  const geometries = new Set(), materials = new Set(), instances = new Set()
  root.traverse(node => {
    if (node._instanceAlpha && node.geometry?.getAttribute('instanceAlpha') === node._instanceAlpha)
      node.geometry.userData = { ...node.geometry.userData, shared: false }
    if (node.geometry && !node.geometry.userData?.shared) geometries.add(node.geometry)
    for (const m of Array.isArray(node.material) ? node.material : [node.material]) if (m) materials.add(m)
    if (node.isInstancedMesh) instances.add(node)
  })
  for (const mesh of instances) mesh.dispose()
  for (const g of geometries) g.dispose()
  for (const m of materials) m.dispose()
  root.removeFromParent(); root.clear()
}

export function buildTransformPreviewLayer(component, scene) {
  validateTransformPreviewComponent(component)
  const root = new THREE.Group(); root.name = 'privateTransformPreview'
  const paletteToken = Symbol('private transform palette'), companions = []
  let disposed = false
  function dispose() {
    if (disposed) return
    disposed = true
    for (const companion of companions.reverse()) companion.dispose()
    disposeRoot(root); _resetStapleColorPins(paletteToken)
  }
  try {
    const design = structuredClone(component.display_topology), records = structuredClone(component.nucleotides)
    design.id = paletteToken
    const axes = Object.fromEntries(structuredClone(component.helix_axes).map(a => [a.helix_id,
      { start: a.start, end: a.end, samples: a.samples, segments: a.segments, ovhgAxes: a.ovhg_axes ?? null }]))
    const privateState = { currentDesign: design, currentGeometry: records, currentHelixAxes: axes,
      coloringMode: 'strand', showReferenceGeometry: true, simulationTabActive: false }
    const privateStore = { getState: () => privateState, subscribe: () => () => {} }
    const native = buildHelixObjects(records, design, root, {}, [], axes, 'full')
    native.setAxisShaftMode('deformed')
    const fluoroEntries = native.getFluoroEntries()
    const rigid = records.filter(n => !n.is_flexible_segment && !n.is_modification)
    const slabs = rigid.filter(n => n.slab_position !== null)
    for (const [actual, expected] of [[native.backboneEntries, rigid], [native.slabEntries, slabs],
      [fluoroEntries, records.filter(n => n.is_modification)]]) {
      const set = new Set(actual.map(e => e.nuc))
      if (actual.length !== expected.length || set.size !== expected.length || expected.some(n => !set.has(n))) fail('occupied native records were omitted')
    }
    const xovers = buildCrossoverConnections(design, records, buildStapleColorMap(records, design), {})
    if (xovers) root.add(xovers.group)
    const extra = [...design.crossovers, ...design.forced_ligations].filter(c => c.extra_bases?.length)
    if ((xovers?.arcData.length ?? 0) !== extra.length || extra.some(c => !xovers.arcData.some(a => a.xoId === c.id && a.beadCount === c.extra_bases.length))) fail('inserted junction bases were omitted')
    const extraPairs = new Set(extra.map(junctionPair))
    const connections = native.getCrossHelixConnections().filter(c => !extraPairs.has(pair(c.fromNuc, c.toNuc)))
    const shown = new Set([...native.coneEntries, ...connections].map(c => pair(c.fromNuc, c.toNuc)))
    for (const c of [...design.crossovers, ...design.forced_ligations])
      if (!c.extra_bases?.length && !shown.has(junctionPair(c))) fail('authored junction connection was omitted')
    const lines = buildNativeConnectionLines(connections, 'transformPreview')
    if (lines) {
      root.add(lines.line)
      for (const arc of connections) writeNativeConnectionArc(lines.positions, arc.vertIdx, arc.from,
        arc.from.clone().add(arc.to).multiplyScalar(.5), arc.to)
      lines.geo.attributes.position.needsUpdate = true
    }
    const positions = new Map([...native.backboneEntries, ...fluoroEntries].map(e => [baseKey(e.nuc, e.nuc.copy_k ?? 0), e.pos]))
    const slabRefs = new Map(native.slabEntries.map(e => [baseKey(e.nuc, e.nuc.copy_k ?? 0), { mesh: e.instMesh, index: e.id }]))
    if (xovers) for (const arc of xovers.arcData) for (let k = 0; k < arc.beadCount; k++) {
      const index = arc.beadStartIdx + simBeadIndex(k, arc.beadCount, arc.simReversed), matrix = new THREE.Matrix4()
      xovers.beadsMesh.getMatrixAt(index, matrix)
      positions.set(xbKey(arc.xoId, k), new THREE.Vector3().setFromMatrixPosition(matrix))
      slabRefs.set(xbKey(arc.xoId, k), { mesh: xovers.slabsMesh, index })
    }
    if (design.photoproduct_junctions.length) {
      const entries = [...slabRefs.entries()], ordinal = new Map(entries.map(([k], i) => [k, i]))
      for (const lesion of design.photoproduct_junctions) {
        const converted = Object.keys(lesion.design_coordinates).length > 0
        for (const k of [lesion.base_key_1, lesion.base_key_2]) if (!(converted ? slabRefs : positions).has(k)) fail('photoproduct endpoint was omitted')
      }
      const matrixSource = { visible: true, getMatrixAt(i, target) { const e = entries[i][1]; e.mesh.getMatrixAt(e.index, target) } }
      const bonds = createCpdSlabBonds(design, matrixSource, target => {
        if (!target) return null
        return ordinal.get(target.crossover_id != null ? xbKey(target.crossover_id, target.k) : baseKey(target, target.copy ?? 0))
      })
      const converted = design.photoproduct_junctions.filter(p => Object.keys(p.design_coordinates).length)
      if ((bonds?.mesh.count ?? 0) !== converted.length * 2) fail('converted photoproduct crosslinks were omitted')
      if (bonds) root.add(bonds.mesh)
      const overlay = initPhotoproductOverlay({ scene: root, THREE, store: privateStore, getBasePosition: k => positions.get(k) })
      companions.push(overlay)
      if (overlay.root.children.length !== design.photoproduct_junctions.length - converted.length) fail('formed photoproduct markers were omitted')
    }
    if (design.flexible_connections.length) {
      const flexible = initFlexibleArcs(root, { getBackboneEntries: () => native.backboneEntries }, () => axes, { storeRef: privateStore })
      companions.push(flexible); flexible.rebuild(design)
      for (const c of design.flexible_connections) {
        const beads = flexible.group.children.find(n => n.name === 'flexSegmentBeads' && n.userData.connectionId === c.id)
        const slabs = flexible.group.children.find(n => n.name === 'flexSegmentSlabs' && n.userData.connectionId === c.id)
        if (!beads || beads.count !== c.n_ss_bases || !slabs || slabs.count !== c.n_ss_bases) fail('flexible segment records were omitted')
      }
    }
    if (design.overhang_connections.length) {
      const links = initOverhangLinkArcs(root, { storeRef: privateStore, staticLookup: true })
      companions.push(links); links.rebuild(design, records)
      if (links.group.children.length !== design.overhang_connections.length) fail('linker connection was omitted')
      for (const c of design.overhang_connections) {
        const child = links.group.children.find(n => n.userData.connId === c.id)
        if (!child) fail('linker identity was omitted')
        if (c.linker_type === 'ss' && linkerLengthToBases(c) > 0) {
          if (child.getObjectByName('overhangSsLinkerBeads')?.count !== linkerLengthToBases(c)
              || child.getObjectByName('overhangSsLinkerSlabs')?.count !== linkerLengthToBases(c)) fail('ss linker beads/slabs were omitted')
        }
      }
      root.userData.linkerLookup = links.group.userData.linkerLookup
    }
    root.traverse(node => { if (node.userData.setupOnly) node.visible = false })
    const geometry = { design, records, helixAxes: axes, backboneEntries: native.backboneEntries,
      slabEntries: native.slabEntries, fluoroEntries, native, extraBases: xovers }
    scene.add(root)
    return { root, geometry, dispose }
  } catch (error) { dispose(); throw error }
}

export function createTransformHistoryPreview({ scene, camera }) {
  if (!scene || !camera) throw new Error('Transform preview requires an isolated camera viewport')
  let before = null, candidate = null, viewport = null, disposed = false, mode = 'candidate'
  const active = () => { if (disposed) throw new Error('Transform preview is disposed') }
  function display() { if (before) before.root.visible = mode === 'before'; if (candidate) candidate.root.visible = mode === 'candidate' }
  function clear() {
    before?.dispose(); candidate?.dispose(); before = null; candidate = null
    viewport?.dispose(); viewport = null
  }
  return {
    open(packet) {
      active()
      let nextBefore, nextCandidate
      try {
        nextBefore = buildTransformPreviewLayer(packet.before, scene)
        if (!packet.candidate) fail('missing initial candidate')
        nextCandidate = buildTransformPreviewLayer(packet.candidate, scene)
      } catch (error) { nextBefore?.dispose(); nextCandidate?.dispose(); throw error }
      clear()
      try {
        viewport = createDeformationPreviewCamera({ scene, camera })
        viewport.include(nextBefore.root); viewport.include(nextCandidate.root)
      } catch (error) { nextBefore.dispose(); nextCandidate.dispose(); viewport?.dispose(); viewport = null; throw error }
      before = nextBefore; candidate = nextCandidate; mode = 'candidate'; display()
    },
    replaceCandidate(component) {
      active(); if (!before) throw new Error('Transform preview is not open')
      const next = component === null ? null : buildTransformPreviewLayer(component, scene)
      if (next) viewport.include(next.root)
      candidate?.dispose(); candidate = next; display()
    },
    candidateGeometry() { return candidate?.geometry ?? null },
    show(value) {
      active(); if (!['before', 'candidate', 'off'].includes(value)) throw new Error('Unknown transform view')
      mode = value; display()
    },
    dispose() { if (!disposed) { clear(); disposed = true } },
  }
}
