import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { coarseSelectionGeometry, coarseConnectionVisible } from './selection_representation.js'

function fixture() {
  const root = new THREE.Group()
  const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(0.1), new THREE.MeshBasicMaterial(), 1)
  root.add(mesh)
  const entry = { instMesh: mesh, id: 0, nuc: { helix_id: 'h', bp_index: 1, strand_id: 's', domain_index: 0 } }
  let rep = 'full'
  const renderer = { getHelixCtrl: () => ({ root }), columnRepAt: () => rep,
    isDomainCylinder: () => rep === 'cylinders' }
  return { root, mesh, entry, renderer, setRep: r => { rep = r } }
}

describe('representation-aware selection composition', () => {
  it.each(['strand', 'domain', 'base', 'end', 'overhang', 'extension', 'measurement'])('%s cannot reintroduce hidden coarse entries on recomposition', () => {
    const f = fixture()
    expect(coarseSelectionGeometry([f.entry], f.renderer).beads).toEqual([f.entry])
    f.root.visible = false
    expect(coarseSelectionGeometry([f.entry, { pos: new THREE.Vector3() }], f.renderer)).toEqual({ beads: [], cylinders: [] })
    f.root.visible = true
    expect(coarseSelectionGeometry([f.entry], f.renderer).beads).toEqual([f.entry])
  })
  it.each(['vdw', 'ballstick', 'stick', 'surface'])('excludes %s regions, including position-only crossover adapters', rep => {
    const f = fixture(); f.setRep(rep)
    expect(coarseSelectionGeometry([f.entry, { arcData: { nucA: f.entry.nuc } }], f.renderer).beads).toEqual([])
  })
  it('deduplicates cylinder domains and ignores hidden source instances', () => {
    const f = fixture(); f.setRep('cylinders')
    expect(coarseSelectionGeometry([f.entry, f.entry], f.renderer)).toEqual({ beads: [], cylinders: [{ strandId: 's', domainIndex: 0 }] })
    f.setRep('full'); f.mesh.visible = false
    expect(coarseSelectionGeometry([f.entry], f.renderer).beads).toEqual([])
  })
})

it('keeps actual coarse connection arcs in cylinder views and excludes heavy replacements', () => {
  const f = fixture(), arc = { fromNuc: f.entry.nuc, toNuc: f.entry.nuc }
  for (const rep of ['full', 'beads', 'cylinders']) {
    f.setRep(rep); expect(coarseConnectionVisible(arc, f.renderer)).toBe(true)
  }
  for (const rep of ['vdw', 'ballstick', 'stick', 'surface']) {
    f.setRep(rep); expect(coarseConnectionVisible(arc, f.renderer)).toBe(false)
  }
  f.setRep('full'); f.root.visible = false
  expect(coarseConnectionVisible(arc, f.renderer)).toBe(false)
})
