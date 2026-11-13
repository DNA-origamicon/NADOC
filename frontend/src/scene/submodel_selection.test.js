import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { assemblyInsertPositions, hasSubmodelSelection, submodelBounds, submodelFromSelection } from './submodel_selection.js'

const geometry = [
  { helix_id: 'h0', bp_index: 0, direction: 'FORWARD', strand_id: 's1', domain_index: 0, backbone_position: [0, 0, 0] },
  { helix_id: 'h0', bp_index: 1, direction: 'FORWARD', strand_id: 's1', domain_index: 0, backbone_position: [1, 3, 2] },
  { helix_id: 'h1', bp_index: 1, direction: 'REVERSE', strand_id: 's1', domain_index: 1, backbone_position: [8, 0, 0] },
  { helix_id: 'h2', bp_index: 2, direction: 'FORWARD', strand_id: 's2', domain_index: 0, backbone_position: [40, 40, 40] },
]
const design = { cluster_transforms: [{ id: 'c', domain_ids: [{ strand_id: 's1', domain_index: 1 }] }] }
const state = items => ({ currentDesign: design, currentGeometry: geometry, selection: { items } })

describe('selection-derived submodel bounds', () => {
  it('gives a single base a finite 2 nm box, without including an unrelated base', () => {
    expect(submodelFromSelection(state([{ kind: 'base', key: 'h0:1:FORWARD' }]))).toMatchObject({ min_corner: [0, 2, 1], max_corner: [2, 4, 3] })
  })
  it.each([
    [[{ kind: 'domain', strandId: 's1', domainIndex: 0 }], [-1, -1, -1], [2, 4, 3]],
    [[{ kind: 'strand', id: 's1' }], [-1, -1, -1], [9, 4, 3]],
    [[{ kind: 'cluster', id: 'c' }], [7, -1, -1], [9, 1, 1]],
    [[{ kind: 'base', key: 'h0:0:FORWARD' }, { kind: 'cluster', id: 'c' }], [-1, -1, -1], [9, 1, 1]],
    [[{ kind: 'bond', fromKey: 'h0:0:FORWARD', toKey: 'h0:1:FORWARD' }], [-1, -1, -1], [2, 4, 3]],
  ])('bounds the complete selection %j', (refs, min, max) => {
    expect(submodelFromSelection(state(refs))).toMatchObject({ min_corner: min, max_corner: max })
  })
  it('uses live positions and never mutates them', () => {
    const pos = new THREE.Vector3(9, 10, 11)
    const result = submodelFromSelection(state([{ kind: 'base', key: 'h0:0:FORWARD' }]), { designRenderer: { getBackboneEntries: () => [{ nuc: geometry[0], pos }] } })
    expect(result.min_corner).toEqual([8, 9, 10]); expect(pos.toArray()).toEqual([9, 10, 11])
  })
  it('includes crossover inserts outside the ordinary backbone bounds', () => {
    const s = state([{ kind: 'crossover', id: 'xo', subtype: 'crossover' }])
    s.currentDesign = { crossovers: [{ id: 'xo', extra_bases: 'TT', half_a: { helix_id: 'h0', index: 1, strand: 'FORWARD' }, half_b: { helix_id: 'h1', index: 1, strand: 'REVERSE' } }] }
    const result = submodelFromSelection(s, { resolveBasePosition: key => new THREE.Vector3(4, key.endsWith(':0') ? -8 : -6, 0) })
    expect(result.min_corner).toEqual([0, -9, -1]); expect(result.max_corner).toEqual([9, 4, 3])
    expect(() => submodelFromSelection(s)).toThrow('positions are not available')
    expect(submodelFromSelection(state([{ kind: 'base', key: '__xb__:xo:0' }]), { resolveBasePosition: () => new THREE.Vector3(0, 5, 0) }).min_corner).toEqual([-1, 4, -1])
  })
  it('rejects empty, stale, non-DNA and invalid selections instead of making a default box', () => {
    for (const refs of [[], [{ kind: 'strand', id: 'missing' }], [{ kind: 'protein', id: 'p' }]]) expect(() => submodelFromSelection(state(refs))).toThrow()
    expect(submodelBounds([new THREE.Vector3(NaN, 0, 0)])).toBeNull()
    expect(submodelBounds([], 1)).toBeNull()
    expect(hasSubmodelSelection(state([]))).toBe(false)
    expect(hasSubmodelSelection(state([{ kind: 'strand', id: 's1' }]))).toBe(true)
  })
  it('bounds assembly group members in world space with geometry fallback and nested-group cycles', () => {
    const s = { assemblyActive: true, activeGroupId: 'g', currentAssembly: { groups: [{ id: 'g', instance_ids: ['a'], subgroup_ids: ['nested'] }, { id: 'nested', instance_ids: ['b'], subgroup_ids: ['g'] }] } }
    const renderer = { getInstanceBackboneEntries: id => ({ nucleotides: [geometry[0]], matrixWorld: new THREE.Matrix4().makeTranslation(id === 'a' ? 10 : 20, 2, 3) }) }
    expect(hasSubmodelSelection(s)).toBe(true)
    expect(submodelFromSelection(s, { assemblyRenderer: renderer })).toMatchObject({ min_corner: [9, 1, 2], max_corner: [21, 3, 4] })
  })
  it('limits assembly cluster bounds to the chosen domains', () => {
    const s = { assemblyActive: true, activeInstanceId: 'a' }
    const assemblyRenderer = { getInstanceDesign: () => design, getInstanceBackboneEntries: () => ({ nucleotides: geometry, matrixWorld: new THREE.Matrix4().makeTranslation(10, 0, 0) }) }
    expect(submodelFromSelection(s, { assemblyRenderer, getAssemblyCluster: () => ({ instanceId: 'a', clusterId: 'c' }) })).toMatchObject({ min_corner: [17, -1, -1], max_corner: [19, 1, 1] })
  })
  it('resolves assembly insert indices and mesh transforms without double-transforming positions', () => {
    const parent = new THREE.Group(); parent.position.x = 10
    const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(), new THREE.MeshBasicMaterial(), 2)
    mesh.position.y = 3; parent.add(mesh); parent.updateMatrixWorld(true)
    mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(1, 0, 0)); mesh.setMatrixAt(1, new THREE.Matrix4().makeTranslation(2, 0, 0))
    const result = assemblyInsertPositions({ matrixWorld: parent.matrixWorld, extraBaseGeometry: { beadsMesh: mesh, arcData: [{ xoId: 'x', beadStartIdx: 0, beadCount: 2, simReversed: true }] } })
    expect(result.get('__xb__:x:1').toArray()).toEqual([1, 3, 0])
    mesh.geometry.dispose(); mesh.material.dispose()
  })
})
