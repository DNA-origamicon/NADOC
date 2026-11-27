import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
const owner = vi.hoisted(() => ({ options: null, clear: vi.fn(), full: vi.fn() }))
vi.mock('./corner_preview.js', () => ({ createCornerPreview: options => { owner.options = options; return owner } }))
import { createBevelPreview } from './bevel_preview.js'
it('masks whole residues, both bond endpoints and inserts; restores the identical private matrices', () => {
  const a = { helix_id: 'h', bp_index: 1 }, b = { helix_id: 'h', bp_index: 2 }
  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial(), 4)
  for (let i = 0; i < 4; i++) mesh.setMatrixAt(i, new THREE.Matrix4().makeTranslation(i, 2, 3))
  const original = mesh.instanceMatrix.array.slice(), root = new THREE.Group()
  const preview = createBevelPreview({})
  owner.options.onFullBuilt({ root, native: { backboneEntries: [{ instMesh: mesh, id: 0, nuc: a }], slabEntries: [],
    coneEntries: [{ instMesh: mesh, id: 1, fromNuc: a, toNuc: b }] },
    extras: { arcData: [{ nucA: a, nucB: b, beadCount: 1, beadStartIdx: 2, connStartIdx: 0 }], beadsMesh: mesh }, connections: [], lines: null })
  preview.mask(n => n.bp_index < 2)
  expect(mesh.instanceMatrix.array[0]).toBe(1)
  expect(mesh.instanceMatrix.array[16]).toBe(0)
  expect(mesh.instanceMatrix.array[32]).toBe(0)
  preview.mask(() => true)
  expect(mesh.instanceMatrix.array).toEqual(original)
  preview.dispose(); expect(owner.clear).toHaveBeenCalledOnce()
  mesh.geometry.dispose(); mesh.material.dispose(); mesh.dispose()
})
