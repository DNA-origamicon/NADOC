import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createAssemblyAnnotationTargets } from './assembly_annotation_targets.js'
import { assemblyAnnotationSelection, normalizeAssemblyAnnotationRef } from './assembly_annotation_refs.js'
import { matchTargetEntries } from './annotation_targets.js'
import { annotationFromWire, annotationToWire, normalizeAnnotation } from './annotation_model.js'

describe('assembly annotations', () => {
  it('accepts only scoped parts and overhangs, preserving distinct copies on round trip', () => {
    expect(normalizeAssemblyAnnotationRef({ kind: 'strand', id: 's' })).toBeNull()
    expect(normalizeAssemblyAnnotationRef({ kind: 'assembly-overhang', instanceId: 'a' })).toBeNull()
    const refs = ['a', 'b'].map(instanceId => ({ kind: 'assembly-overhang', instanceId, overhangId: 'oh' }))
    const a = normalizeAnnotation({ refs: [...refs, refs[0]] })
    expect(annotationFromWire(annotationToWire(a)).refs).toEqual(refs)
  })
  it('captures selected individual copies and gives scoped overhang selection priority', () => {
    const s = { currentAssembly: { instances: [{ id: 'a' }, { id: 'b' }] }, activeInstanceId: 'a', selection: { items: [{ kind: 'strand', id: 'wrong' }] } }
    expect(assemblyAnnotationSelection(s)).toEqual([{ kind: 'assembly-part', instanceId: 'a' }])
    expect(assemblyAnnotationSelection({ ...s, activeGroupId: 'group' })).toEqual([])
    expect(assemblyAnnotationSelection({ ...s, multiSelectedInstanceIds: ['a', 'b'] })).toHaveLength(2)
    expect(assemblyAnnotationSelection({ ...s, assemblyOverhangSelection: [{ instanceId: 'b', overhangId: 'oh' }] })).toEqual([{ kind: 'assembly-overhang', instanceId: 'b', overhangId: 'oh' }])
  })
  it('matches the same overhang beads as parts, follows live transforms, and handles hidden/deleted copies', () => {
    const design = { strands: [{ id: 's', domains: [{ overhang_id: 'oh' }, {}] }], overhangs: [{ id: 'oh', strand_id: 's' }] }
    const entries = [0, 1].map(domain_index => ({ nuc: { strand_id: 's', domain_index }, pos: new THREE.Vector3(domain_index, 2, 3) }))
    const matrices = { a: new THREE.Matrix4(), b: new THREE.Matrix4().makeTranslation(20, 0, 0) }
    const store = createMockStore({ currentAssembly: { instances: [{ id: 'a' }, { id: 'b' }] } })
    const renderer = { getInstanceDesign: () => design, getInstanceBackboneEntries: id => ({ entries, matrixWorld: matrices[id] }), getInstanceCenters: () => [] }
    const adapter = createAssemblyAnnotationTargets({ store, getRenderer: () => renderer })
    const refs = [{ kind: 'assembly-overhang', instanceId: 'b', overhangId: 'oh' }]
    const result = adapter.resolve(refs)
    expect(result.map(e => e.nuc)).toEqual(matchTargetEntries([{ kind: 'overhang', id: 'oh' }], design, entries).map(e => e.nuc))
    expect(result[0].pos.toArray()).toEqual([20, 2, 3])
    matrices.b.makeTranslation(40, 0, 0)
    expect(adapter.resolve(refs)).toBe(result)
    expect(result[0].pos.x).toBe(40)
    expect(entries[0].pos.x).toBe(0)
    store.setState({ currentAssembly: { instances: [{ id: 'b', visible: false }] } })
    expect(adapter.resolve(refs)).toEqual([])
    store.setState({ currentAssembly: { instances: [] } })
    expect(adapter.resolve(refs)).toEqual([])
  })
  it('resolves targets from source geometry when hull/cylinder representations allocate no beads', () => {
    const nuc = { strand_id: 's', domain_index: 0, backbone_position: [1, 2, 3] }
    const nucleotides = [nuc]
    const design = { strands: [{ id: 's', domains: [{ overhang_id: 'oh' }] }], overhangs: [{ id: 'oh', strand_id: 's' }] }
    const store = createMockStore({ currentAssembly: { instances: [{ id: 'copy' }] } })
    const renderer = { getInstanceBackboneEntries: () => ({ entries: [], nucleotides }), getInstanceDesign: () => design, getLiveTransform: () => new THREE.Matrix4().makeTranslation(10, 0, 0) }
    const adapter = createAssemblyAnnotationTargets({ store, getRenderer: () => renderer })
    const refs = [{ kind: 'assembly-overhang', instanceId: 'copy', overhangId: 'oh' }]
    expect(adapter.resolve(refs).map(e => e.pos.toArray())).toEqual([[11, 2, 3]])
    expect(adapter.resolve([{ kind: 'assembly-part', instanceId: 'copy' }])).toHaveLength(1)
  })

})
