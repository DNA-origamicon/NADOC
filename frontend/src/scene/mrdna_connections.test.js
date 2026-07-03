import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { initMrdnaConnections } from './mrdna_connections.js'

function fakeScene() {
  const objs = []
  return {
    add: (o) => objs.push(o),
    remove: (o) => { const i = objs.indexOf(o); if (i >= 0) objs.splice(i, 1) },
    objs,
  }
}

describe('initMrdnaConnections', () => {
  it('adds an InstancedMesh with one stick per valid edge', () => {
    const s = fakeScene()
    initMrdnaConnections(s).update(
      [{ x: 0, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }, { x: 1, y: 1, z: 0 }],
      [[0, 1], [1, 2]],
    )
    expect(s.objs).toHaveLength(1)
    expect(s.objs[0]).toBeInstanceOf(THREE.InstancedMesh)
    expect(s.objs[0].count).toBe(2)
  })

  it('clear removes and disposes the mesh', () => {
    const s = fakeScene()
    const c = initMrdnaConnections(s)
    c.update([{ x: 0, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }], [[0, 1]])
    c.clear()
    expect(s.objs).toHaveLength(0)
  })

  it('update replaces the previous mesh (no leak)', () => {
    const s = fakeScene()
    const c = initMrdnaConnections(s)
    c.update([{ x: 0, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }], [[0, 1]])
    c.update([{ x: 0, y: 0, z: 0 }, { x: 2, y: 0, z: 0 }], [[0, 1]])
    expect(s.objs).toHaveLength(1)
  })

  it('no edges → nothing added', () => {
    const s = fakeScene()
    initMrdnaConnections(s).update([{ x: 0, y: 0, z: 0 }], [])
    expect(s.objs).toHaveLength(0)
  })

  it('skips degenerate zero-length bonds', () => {
    const s = fakeScene()
    initMrdnaConnections(s).update(
      [{ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 0 }],   // coincident → length 0
      [[0, 1]],
    )
    expect(s.objs[0].count).toBe(0)
  })
})
