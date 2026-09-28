import { describe, it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { decodeCandoView, initCandoLargeView } from './cando_large_view.js'

export function packedView(kind = 'flex') {
  const meta = { count: 2, identities: true, kind, min: 1, max: 3, helix_ids: ['part:h'] }
  const header = new TextEncoder().encode(JSON.stringify(meta))
  const offset = Math.ceil((12 + header.length) / 4) * 4
  const buffer = new ArrayBuffer(offset + 64)
  const dv = new DataView(buffer)
  ;[0x5A495643, 1, header.length].forEach((v, i) => dv.setUint32(4*i, v, true))
  new Uint8Array(buffer, 12, header.length).set(header)
  new Float32Array(buffer, offset, 6).set([1,2,3,4,5,6])
  new Float32Array(buffer, offset + 24, 2).set([1,3])
  new Int32Array(buffer, offset + 32, 8).set([0,7,0,0,0,7,1,2])
  return buffer
}

describe('compact CanDo visualization', () => {
  it('retains every coordinate and exact direction/loop-copy identity without copying columns', () => {
    const buffer = packedView(), data = decodeCandoView(buffer)
    expect([...data.positions]).toEqual([1,2,3,4,5,6])
    expect(data.positions.buffer).toBe(buffer)
    const scene = new THREE.Scene(), view = initCandoLargeView(scene)
    view.update(data)
    expect(view.coloringInfo().values[1]).toEqual({ helix_id: 'part:h', bp_index: 7, direction: 'REVERSE', copy: 2, value: 3 })
    const geometry = scene.children[0].children[0].geometry
    const dispose = vi.spyOn(geometry, 'dispose')
    view.recolor(0, 10, 'viridis')
    expect(scene.children[0].children[0].geometry).toBe(geometry)
    expect(view.coloringInfo()).toMatchObject({ lo: 0, hi: 10, colormap: 'viridis' })
    view.clear()
    expect(scene.children).toHaveLength(0)
    expect(dispose).toHaveBeenCalledOnce()
    expect(view.coloringInfo()).toBeNull()
  })
  it('rejects truncated and oversized declarations before creating GPU data', () => {
    expect(() => decodeCandoView(packedView().slice(0, -4))).toThrow('Incomplete')
    const buffer = packedView(); new DataView(buffer).setUint32(8, 0xffffffff, true)
    expect(() => decodeCandoView(buffer)).toThrow('header')
  })
  it('uses line segments for all cylinder endpoints and disposes replaced geometry', () => {
    const scene = new THREE.Scene(), view = initCandoLargeView(scene)
    view.update(decodeCandoView(packedView('cando')))
    expect(scene.children[0].children[0].isLineSegments).toBe(true)
    expect(scene.children[0].children[0].geometry.attributes.position.count).toBe(2)
    view.update(decodeCandoView(packedView()))
    expect(scene.children).toHaveLength(1)
    expect(scene.children[0].children[0].isPoints).toBe(true)
    view.clear()
  })
})

it('progressive detail retains every coordinate, every endpoint pair, and increases with zoom', async () => {
  const { progressiveIndices, projectedDrawCount } = await import('./cando_large_view.js')
  for (const lines of [false, true]) {
    const indices = [...progressiveIndices(4096, lines)]
    expect(new Set(indices).size).toBe(4096)
    expect(Math.max(...indices)).toBe(4095)
    expect(indices.slice(0, lines ? 4 : 2)).toEqual(lines ? [0,1,4094,4095] : [0,4095])
    if (lines) for (let i=0; i<indices.length; i+=2) expect(indices[i+1]).toBe(indices[i]+1)
    expect(projectedDrawCount(2, 4096, lines)).toBeLessThan(projectedDrawCount(8, 4096, lines))
    expect(projectedDrawCount(1000, 4096, lines)).toBe(4096)
  }
})
it('reveals full tile detail on zoom without rebuilding or changing positions', () => {
  const scene = new THREE.Scene(), view = initCandoLargeView(scene)
  const positions = new Float32Array(4096 * 3)
  for (let i=0; i<4096; i++) { positions[3*i] = (i % 64) / 64; positions[3*i+1] = Math.floor(i / 64) / 64 }
  view.update({ meta: { count: 4096, kind: 'deform', min: 0, max: 1 }, positions, scalars: new Float32Array(4096) })
  const tile = scene.children[0].children[0], geometry = tile.geometry
  const camera = new THREE.PerspectiveCamera(60, 1, .1, 10000)
  camera.position.set(0,0,1000)
  tile.onBeforeRender({ domElement: { height: 720 } }, scene, camera)
  expect(geometry.drawRange.count).toBeLessThan(4096)
  camera.position.set(.5,.5,.1)
  tile.onBeforeRender({ domElement: { height: 720 } }, scene, camera)
  expect(geometry.drawRange.count).toBe(4096)
  expect(tile.geometry).toBe(geometry)
  expect(geometry.attributes.position.array.buffer).toBe(positions.buffer)
  view.clear()
})

it('trajectory updates preserve GPU geometry and refresh camera bounds', () => {
  const scene = new THREE.Scene(), view = initCandoLargeView(scene)
  const data = { meta: { kind: 'deform', count: 2, min: 0, max: 0 },
    positions: new Float32Array([0,0,0,1,1,1]), scalars: new Float32Array([-1,-1]) }
  view.update(data)
  const geometry = scene.children[0].children[0].geometry
  view.updatePositions({ ...data, positions: new Float32Array([10,10,10,20,20,20]) })
  expect(scene.children[0].children[0].geometry).toBe(geometry)
  expect(view.getBoundingBox().max.x).toBe(20)
  expect([...geometry.attributes.position.array]).toEqual([10,10,10,20,20,20])
  view.clear()
})
