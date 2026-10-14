import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { buildHelixObjects } from './helix_renderer.js'
import { repaintAssemblySourceColors } from './assembly_source_colors.js'

function fixture() {
  const ids = ['straight', 'curved', 'overhang', 'binder']
  const helices = ids.map((id, i) => ({ id, bp_start: 0, length_bp: 4,
    axis_start: { x: i * 5, y: 0, z: 0 }, axis_end: { x: i * 5, y: 0, z: 1 } }))
  const axes = Object.fromEntries(ids.map((id, i) => [id, { start: [i * 5, 0, 0], end: [i * 5, 0, 1],
    ...(id === 'curved' ? { samples: [[5, 0, 0], [5.4, 0, .5], [5, 0, 1]] } : {}) }]))
  const domain = (helix_id, extra = {}) => ({ helix_id, start_bp: 0, end_bp: 3, direction: 'FORWARD', ...extra })
  const strands = [
    { id: 'staple', strand_type: 'staple', sequence: 'ATGCATGC', domains: [domain('straight'), domain('curved')] },
    { id: 'scaffold', strand_type: 'scaffold', sequence: 'GCAT', domains: [domain('straight', { direction: 'REVERSE', start_bp: 3, end_bp: 0 })] },
    { id: 'tail', strand_type: 'staple', sequence: 'CATG', domains: [domain('overhang', { overhang_id: 'oh' })] },
    { id: 'binder', strand_type: 'oh_binder', sequence: 'TGCA', domains: [domain('binder')] },
  ]
  const design = { id: 'assembly-color-parity', helices, strands, crossovers: [],
    cluster_transforms: [
      { id: 'body', helix_ids: ['straight'], color: '#00ff99' },
      { id: 'bend-domain', domain_ids: [{ strand_id: 'staple', domain_index: 1 }], color: '#9944ee' },
      { id: 'tail', helix_ids: ['overhang'], color: '#3366ff' },
    ] }
  const nucleotides = strands.flatMap(strand => strand.domains.flatMap((dom, domain_index) =>
    [0, 1, 2, 3].map(bp_index => {
      const x = ids.indexOf(dom.helix_id) * 5 + 1, z = bp_index / 3
      return { helix_id: dom.helix_id, direction: dom.direction, bp_index, domain_index,
        strand_id: strand.id, strand_type: strand.strand_type, overhang_id: dom.overhang_id,
        is_five_prime: bp_index === (dom.direction === 'FORWARD' ? 0 : 3),
        backbone_position: [x, 0, z], base_position: [x - .5, 0, z],
        placement_source: 'native-full-o5-v1', slab_position: [x - .33, 0, z],
        slab_quaternion: [0, Math.SQRT1_2, Math.SQRT1_2, 0], base_normal: [-1, 0, 0], axis_tangent: [0, 0, 1] }
    })))
  const build = custom => buildHelixObjects(nucleotides, design, new THREE.Group(), custom, [], axes, 'full')
  return { design, nucleotides, build }
}

function sharedSource(f, custom) {
  const helixCtrl = f.build(custom), activeMeshes = []
  const names = new Set(['backboneSpheres', 'backboneCubes', 'strandCones', 'baseSlabs', 'slabBackboneConnectors', 'extensionFluorophores'])
  helixCtrl.root.traverse(mesh => {
    if (!mesh.isInstancedMesh || !mesh.count || !names.has(mesh.name) || !mesh.instanceColor) return
    const bpColorData = new Float32Array(mesh.count * 4)
    for (let i = 0; i < mesh.count; i++) bpColorData.set([...mesh.instanceColor.array.slice(i * 3, i * 3 + 3), 1], i * 4)
    activeMeshes.push({ mesh, baseCount: mesh.count, bpColorData, bpColorTex: new THREE.DataTexture(bpColorData, mesh.count, 1) })
    mesh.instanceColor = null
  })
  const intervals = helixCtrl.domainCylData.map(domain => ({ domains: [domain] }))
  const midLod = { intervals, segColorData: new Float32Array(intervals.length * 4), segColorTex: new THREE.Texture() }
  const overhangLod = { numSegments: helixCtrl.overhangCylData.length, fullCylinder: false,
    segColorData: new Float32Array(helixCtrl.overhangCylData.length * 4), segColorTex: new THREE.Texture() }
  const curvedColorRanges = []
  let start = 0
  helixCtrl.root.traverse(mesh => {
    if (!['curvedCylGroup', 'curvedOvhgGroup'].includes(mesh.parent?.name)) return
    const count = mesh.geometry.index?.count ?? mesh.geometry.attributes.position.count
    curvedColorRanges.push({ start, count, domain: { ...mesh.userData }, overhang: mesh.parent.name === 'curvedOvhgGroup' })
    start += count
  })
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(new Float32Array(start * 3), 3))
  const curvedCylLod = { mesh: new THREE.Mesh(geometry) }
  return { ...f, helixCtrl, customColors: custom, activeMeshes, midLod, overhangLod, curvedColorRanges, curvedCylLod }
}

function dispose(ctrl) {
  ctrl.root.traverse(obj => {
    if (obj.geometry && !obj.geometry.userData?.shared) obj.geometry.dispose()
    for (const material of Array.isArray(obj.material) ? obj.material : obj.material ? [obj.material] : []) material.dispose()
  })
}

describe('assembly color texture parity', () => {
  it.each(['strand', 'base', 'cluster', 'overhang-only'])('matches the actual helix renderer in %s mode without rewriting meshes', mode => {
    const f = fixture(), custom = { staple: 0x885511 }
    const source = sharedSource(f, custom)
    source.activeMeshes[0].bpColorData[3] = .25
    const matrices = source.activeMeshes.map(active => active.mesh.instanceMatrix.array.slice())
    const geometries = source.activeMeshes.map(active => active.mesh.geometry)
    const reference = f.build(custom)
    if (mode !== 'strand') reference.applyColoring(mode, f.design, custom, new Set())
    repaintAssemblySourceColors(source, mode)
    expect(source.activeMeshes[0].bpColorData[3]).toBe(.25)
    for (let m = 0; m < source.activeMeshes.length; m++) {
      const active = source.activeMeshes[m], expected = reference.root.getObjectByName(active.mesh.name)
      expect(active.mesh.instanceColor).toBeNull()
      expect(active.mesh.instanceMatrix.array).toEqual(matrices[m])
      expect(active.mesh.geometry).toBe(geometries[m])
      for (let i = 0; i < active.baseCount; i++) {
        expect([...active.bpColorData.slice(i * 4, i * 4 + 3)]).toEqual([...expected.instanceColor.array.slice(i * 3, i * 3 + 3)])
      }
    }
    for (let i = 0; i < source.midLod.intervals.length; i++) {
      const index = source.midLod.intervals[i].domains[0].cylIdx
      expect([...source.midLod.segColorData.slice(i * 4, i * 4 + 3)])
        .toEqual([...reference.getCylinderMesh().instanceColor.array.slice(index * 3, index * 3 + 3)])
    }
    for (const domain of source.helixCtrl.overhangCylData) {
      const index = domain.cylIdx
      expect([...source.overhangLod.segColorData.slice(index * 4, index * 4 + 3)])
        .toEqual([...reference.getOverhangCylinderMesh().instanceColor.array.slice(index * 3, index * 3 + 3)])
    }
    expect(source.curvedColorRanges.length).toBeGreaterThan(0)
    const tubes = []
    reference.root.traverse(mesh => { if (['curvedCylGroup', 'curvedOvhgGroup'].includes(mesh.parent?.name)) tubes.push(mesh) })
    const colors = source.curvedCylLod.mesh.geometry.attributes.color.array
    source.curvedColorRanges.forEach((range, index) => {
      const expected = new Float32Array(tubes[index].material.color.toArray())
      for (let i = range.start; i < range.start + range.count; i++) expect([...colors.slice(i * 3, i * 3 + 3)]).toEqual([...expected])
    })
    dispose(source.helixCtrl); dispose(reference)
    source.curvedCylLod.mesh.geometry.dispose()
  })

  it('restores strand colors after another mode and applies live custom colors', () => {
    const f = fixture(), source = sharedSource(f, {})
    repaintAssemblySourceColors(source, 'cluster')
    source.customColors.staple = 0x1177ff
    repaintAssemblySourceColors(source, 'strand')
    const reference = f.build(source.customColors)
    const active = source.activeMeshes.find(item => item.mesh.name === 'baseSlabs')
    const expected = reference.root.getObjectByName('baseSlabs').instanceColor.array
    for (let i = 0; i < active.baseCount; i++) {
      expect([...active.bpColorData.slice(i * 4, i * 4 + 3)]).toEqual([...expected.slice(i * 3, i * 3 + 3)])
    }
    dispose(source.helixCtrl); dispose(reference)
    source.curvedCylLod.mesh.geometry.dispose()
  })
})
