import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { createExternalTargets, isExternalRef } from './annotation_external.js'

const design = {
  nanoparticles: [{ id: 'n1', kind: 'gold_nanosphere', diameter_nm: 10 }],
  protein_attachments: [{ id: 'p1' }],
}

function make({ proteinExtent = { x: 1, y: 2, z: 3, radius: 2.5 } } = {}) {
  const mesh = new THREE.Mesh(); mesh.position.set(5, 6, 7); mesh.updateMatrixWorld(true)
  let t = 0, calls = 0
  const ext = createExternalTargets({
    getDesign: () => design,
    getNanoparticleSubsystem: () => ({ meshes: new Map([['n1', mesh]]) }),
    getProteinRenderer: () => ({ extentOf: pred => { calls++; return pred({ helix_id: '__protein__p1' }) && !pred({ helix_id: '__protein__zz' }) ? proteinExtent : null } }),
    now: () => t,
  })
  return { ext, mesh, calls: () => calls, advance: ms => { t += ms } }
}

describe('external targets', () => {
  it('recognises the kinds', () => {
    expect(isExternalRef({ kind: 'protein' })).toBe(true)
    expect(isExternalRef({ kind: 'nanoparticle' })).toBe(true)
    expect(isExternalRef({ kind: 'strand' })).toBe(false)
  })
  it('resolves a nanoparticle to its live world position and design radius', () => {
    const { ext, mesh } = make()
    expect(ext.resolve({ kind: 'nanoparticle', id: 'n1' })).toEqual({ x: 5, y: 6, z: 7, radius: 5 })
    mesh.position.set(9, 9, 9); mesh.updateMatrixWorld(true)
    expect(ext.resolve({ kind: 'nanoparticle', id: 'n1' }).x).toBe(9)
  })
  it('resolves a protein to its atoms\' bounding sphere, scoped to that attachment', () => {
    const { ext } = make()
    expect(ext.resolve({ kind: 'protein', id: 'p1' })).toEqual({ x: 1, y: 2, z: 3, radius: 2.5 })
  })
  it('throttles the protein atom scan but refreshes after the interval', () => {
    const { ext, calls, advance } = make()
    ext.resolve({ kind: 'protein', id: 'p1' }); ext.resolve({ kind: 'protein', id: 'p1' })
    expect(calls()).toBe(1)
    advance(500)
    ext.resolve({ kind: 'protein', id: 'p1' })
    expect(calls()).toBe(2)
  })
  it('is null for unknown ids / missing renderers and lists every element as an occluder', () => {
    const { ext } = make()
    expect(ext.resolve({ kind: 'nanoparticle', id: 'nope' })).toBeNull()
    expect(ext.resolve({ kind: 'protein', id: 'nope' })).toBeNull()
    expect(ext.listAll()).toHaveLength(2)
    const bare = createExternalTargets({ getDesign: () => design, getNanoparticleSubsystem: () => null, getProteinRenderer: () => null })
    expect(bare.resolve({ kind: 'protein', id: 'p1' })).toBeNull()
    expect(bare.listAll()).toEqual([])
  })
})
