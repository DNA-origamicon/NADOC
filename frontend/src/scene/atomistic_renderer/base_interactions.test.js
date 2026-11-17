import { describe, it, expect, afterEach } from 'vitest'
import * as THREE from 'three'
import { makeAtomTable } from '../atom_table.js'
import { interactionResidues, findBaseInteractions, singleInteractionBase } from './base_interactions.js'
import { initAtomisticRenderer } from '../atomistic_renderer.js'
import { setBaseInteractionsEnabled } from './interaction_overlay.js'

// Minimal planar cytosine rings, test data only; never saved as NADOC structures.
function atoms(z = 0, bp = 0) {
  const positions = { N1: [-.14, 0], C2: [-.07, -.12], N3: [.07, -.12], C4: [.14, 0], C5: [.07, .12], C6: [-.07, .12], O2: [-.07, -.24], N4: [.28, 0] }
  return Object.entries(positions).map(([name, [x, y]], i) => ({ serial: bp * 10 + i, name, element: name[0], x, y, z, helix_id: 'h', bp_index: bp, direction: 'fwd' }))
}
function residues(data) { return interactionResidues(makeAtomTable({ atoms: data }), i => [data[i].x, data[i].y, data[i].z]) }
afterEach(() => setBaseInteractionsEnabled(false))

describe('base interaction geometry', () => {
  it('detects parallel stacking, rejecting distant, coplanar and offset rings', () => {
    expect(findBaseInteractions(residues([...atoms(), ...atoms(.34, 1)]))).toMatchObject([{ type: 'stacking' }])
    for (const z of [0, .6]) expect(findBaseInteractions(residues([...atoms(), ...atoms(z, 1)]))).toEqual([])
    expect(findBaseInteractions(residues([...atoms(), ...atoms(.34, 1).map(a => ({ ...a, x: a.x + .4 }))]))).toEqual([])
  })
  it('detects directional donor/acceptor contacts without asserting base pairing', () => {
    const partner = atoms(0, 1).map(a => ({ ...a, x: .63 + a.x, y: .24 + a.y }))
    const found = findBaseInteractions(residues([...atoms(), ...partner]))
    expect(found.some(c => c.type === 'hydrogen' && Math.abs(c.start.distanceTo(c.end) - .28) < 1e-6)).toBe(true)
    expect(found.every(c => c.type !== 'stacking')).toBe(true)
  })
  it('skips incomplete, unnamed and modified bases', () => {
    for (const first of [atoms().filter(a => a.name !== 'N1'), atoms().map(a => ({ ...a, name: '' })), atoms().map(a => ({ ...a, is_modified: true }))]) {
      expect(findBaseInteractions(residues([...first, ...atoms(.34, 1)]))).toEqual([])
    }
  })
  it('restricts automatic display to exactly one base and supports copy identity', () => {
    const b = { helix_id: 'h', bp_index: 1, direction: 'fwd', copy: 2 }
    expect(singleInteractionBase({ bases: [b] }, 'stick')).toBe('h:1:fwd:2')
    for (const selection of [{ bases: [b, b] }, { bases: [b], strandIds: ['s'] }, null]) expect(singleInteractionBase(selection, 'ballstick')).toBeNull()
    expect(singleInteractionBase({ bases: [b] }, 'vdw')).toBeNull()
    const found = findBaseInteractions(residues([...atoms(), ...atoms(.34, 1), ...atoms(.68, 2)]), 'h:0:fwd')
    expect(found).toHaveLength(1)
    expect(found[0].keys).toEqual(['h:0:fwd', 'h:1:fwd'])
  })
})

it('renders dashed selection contacts, updates live positions and cleans up', () => {
  const scene = new THREE.Scene(), renderer = initAtomisticRenderer(scene)
  const data = [...atoms(), ...atoms(.34, 1)]
  renderer.update({ atoms: data, bonds: [] }); renderer.setMode('stick')
  expect(scene.getObjectByName('base-interactions')).toBeUndefined()
  renderer.highlight({ bases: [{ helix_id: 'h', bp_index: 0, direction: 'fwd' }] })
  const line = scene.getObjectByName('base-interactions-stacking')
  expect(line.material.isLineDashedMaterial).toBe(true)
  expect(line.geometry.getAttribute('lineDistance').array[1]).toBeCloseTo(.34)
  renderer.setMode('vdw')
  expect(scene.getObjectByName('base-interactions')).toBeUndefined()
  renderer.setMode('ballstick')
  expect(scene.getObjectByName('base-interactions-stacking')).toBeDefined()
  renderer.highlight({ bases: [
    { helix_id: 'h', bp_index: 0, direction: 'fwd' },
    { helix_id: 'h', bp_index: 1, direction: 'fwd' },
  ] })
  expect(scene.getObjectByName('base-interactions')).toBeUndefined()
  renderer.highlight(null)
  expect(scene.getObjectByName('base-interactions')).toBeUndefined()
  setBaseInteractionsEnabled(true)
  expect(scene.getObjectByName('base-interactions-stacking')).toBeDefined()
  renderer.setUniformOpacity(0)
  expect(scene.getObjectByName('base-interactions')).toBeUndefined()
  renderer.setUniformOpacity(1)
  expect(scene.getObjectByName('base-interactions-stacking')).toBeDefined()
  renderer.applyResiduesMatrix([{ helix_id: 'h', bp_index: 1, direction: 'fwd' }], new THREE.Matrix4().makeTranslation(0, 0, 1))
  expect(scene.getObjectByName('base-interactions')).toBeUndefined()
  renderer.setMode('off')
  renderer.dispose()
  setBaseInteractionsEnabled(true)
  expect(scene.children).toHaveLength(0)
})
