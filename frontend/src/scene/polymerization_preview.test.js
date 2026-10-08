import { it, expect } from 'vitest'
import * as THREE from 'three'
import { createPolymerizationPreview, polymerizationPreviewEnds, POLYMER_PREVIEW_ALPHA } from './polymerization_preview.js'
import { installInstanceAlpha } from './instance_alpha.js'

function fixture() {
  const root = new THREE.Group()
  const beads = new THREE.InstancedMesh(new THREE.SphereGeometry(.1), new THREE.MeshPhongMaterial(), 10)
  const slabs = new THREE.InstancedMesh(new THREE.BoxGeometry(), new THREE.MeshPhongMaterial(), 10)
  const entries = [], plates = []
  for (let bp = 0; bp < 10; bp++) {
    const angle = bp * Math.PI * 2 / 10.5
    const pos = new THREE.Vector3(Math.cos(angle), Math.sin(angle), bp * .334)
    const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1), angle)
    const matrix = new THREE.Matrix4().compose(pos, q, new THREE.Vector3(1,1,1))
    beads.setMatrixAt(bp, matrix); slabs.setMatrixAt(bp, matrix)
    beads.setColorAt(bp, new THREE.Color(0x7cfc00)); slabs.setColorAt(bp, new THREE.Color(0xff8800))
    const nuc = { helix_id: 'h', bp_index: bp, direction: 'FORWARD', strand_id: 's', domain_index: 0, slab_quaternion: q.toArray() }
    entries.push({ instMesh: beads, id: bp, nuc }); plates.push({ instMesh: slabs, id: bp, nuc })
  }
  root.add(beads, slabs)
  const seam = { is_periodic_seam: true, three_prime_helix_id: 'h', three_prime_bp: 9, three_prime_direction: 'FORWARD', five_prime_helix_id: 'h', five_prime_bp: 0, five_prime_direction: 'FORWARD' }
  const design = { forced_ligations: [seam] }
  return { root, beads, slabs, entries, plates, design, seam }
}

it('adds exactly three progressively fading bases at each seam, continuing the helix outside both faces', () => {
  const f = fixture(), before = JSON.stringify(f.design)
  const preview = createPolymerizationPreview(f.root, f.design, f.entries, f.plates)
  const [beads, slabs, bonds] = preview.group.children
  expect(beads.count).toBe(6); expect(slabs.count).toBe(6); expect(bonds.count).toBe(6)
  const matrix = new THREE.Matrix4(), pos = new THREE.Vector3()
  for (let i = 0; i < 6; i++) {
    beads.getMatrixAt(i, matrix); pos.setFromMatrixPosition(matrix)
    const bp = i < 3 ? 10 + i : -(i - 2)
    expect(pos.z).toBeCloseTo(bp * .334, 5)
    expect(pos.x).toBeCloseTo(Math.cos(bp * Math.PI * 2 / 10.5), 5)
    expect(pos.y).toBeCloseTo(Math.sin(bp * Math.PI * 2 / 10.5), 5)
    expect(beads._instanceAlpha.getX(i)).toBeCloseTo(POLYMER_PREVIEW_ALPHA[i % 3])
  }
  expect(JSON.stringify(f.design)).toBe(before)
  expect(f.entries).toHaveLength(10)
  const hits = []; beads.raycast(new THREE.Raycaster(), hits); expect(hits).toEqual([])
})

it('ignores ordinary ligations and missing neighbours; deduplicates repeated seams', () => {
  const f = fixture()
  expect(createPolymerizationPreview(f.root, { forced_ligations: [{ ...f.seam, is_periodic_seam: false }] }, f.entries, f.plates)).toBeNull()
  expect(polymerizationPreviewEnds(f.design, [f.entries[0]])).toEqual([])
  expect(polymerizationPreviewEnds({ forced_ligations: [f.seam, f.seam] }, f.entries)).toHaveLength(2)
})

it('follows live transforms, visibility and opacity without rebuilding or idle uploads', () => {
  const f = fixture(), preview = createPolymerizationPreview(f.root, f.design, f.entries, f.plates)
  const [beads, slabs] = preview.group.children, geometry = beads.geometry, attribute = beads.instanceMatrix
  const version = attribute.version
  f.root.updateMatrixWorld(true); f.root.updateMatrixWorld(true)
  expect(attribute.version).toBe(version)
  const matrix = new THREE.Matrix4(), move = new THREE.Matrix4().makeTranslation(5, 2, 1)
  for (const mesh of [f.beads, f.slabs]) {
    for (let i = 0; i < 10; i++) { mesh.getMatrixAt(i, matrix); mesh.setMatrixAt(i, matrix.premultiply(move)) }
    mesh.instanceMatrix.needsUpdate = true
  }
  f.root.updateMatrixWorld(true)
  beads.getMatrixAt(0, matrix)
  expect(new THREE.Vector3().setFromMatrixPosition(matrix).z).toBeCloseTo(4.34)
  expect(beads.geometry).toBe(geometry); expect(beads.instanceMatrix).toBe(attribute)
  installInstanceAlpha(f.beads); f.beads._instanceAlpha.setX(9, .5); f.beads._instanceAlpha.needsUpdate = true
  f.slabs.visible = false; f.root.updateMatrixWorld(true)
  expect(beads._instanceAlpha.getX(0)).toBeCloseTo(.275)
  expect(slabs._instanceAlpha.getX(0)).toBe(0)
  f.beads.visible = false; f.root.updateMatrixWorld(true)
  expect([...beads._instanceAlpha.array]).toEqual([0,0,0,0,0,0])
})

it('is installed by the real helix renderer without adding selectable nucleotides', async () => {
  const { buildHelixObjects } = await import('./helix_renderer.js')
  const f = fixture(), matrix = new THREE.Matrix4(), p = new THREE.Vector3()
  const geometry = f.entries.map(e => {
    e.instMesh.getMatrixAt(e.id, matrix); p.setFromMatrixPosition(matrix)
    return { ...e.nuc, strand_type: 'staple', backbone_position: p.toArray(),
      base_position: p.clone().multiply(new THREE.Vector3(.7, .7, 1)).toArray(),
      slab_position: p.clone().multiply(new THREE.Vector3(.7, .7, 1)).toArray(),
      placement_source: 'native-full-o5-v1', base_normal: [1,0,0], axis_tangent: [0,0,1] }
  })
  const scene = new THREE.Scene()
  const ctrl = buildHelixObjects(geometry, { ...f.design, helices: [], strands: [{ id: 's', strand_type: 'staple', domains: [] }] }, scene)
  scene.updateMatrixWorld(true)
  expect(ctrl.root.getObjectByName('polymerizationPreviewBeads').count).toBe(6)
  expect(ctrl.backboneEntries).toHaveLength(10)
})
