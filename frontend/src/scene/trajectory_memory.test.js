import { expect, it } from 'vitest'
import { createTrajectoryMemory, TrajectoryMemoryMap, trajectoryStorageBytes } from './trajectory_memory.js'

it('charges a shared backing buffer once, including bytes outside each view', () => {
  const memory = createTrajectoryMemory(1024)
  const a = new TrajectoryMemoryMap({ memory }), b = new TrajectoryMemoryMap({ memory })
  const buffer = new ArrayBuffer(768)
  a.set(0, new Float32Array(buffer, 0, 3))
  b.set(0, { dense: new Float64Array(buffer, 64, 3), serialMap: new Uint32Array(buffer, 32, 3) })
  expect(trajectoryStorageBytes(a)).toBe(768)
  expect(memory.stats().bytes).toBe(768)
  a.clear()
  expect(memory.stats().bytes).toBe(768)
  b.clear()
  expect(memory.stats().bytes).toBe(0)
})

it('evicts owning references across independent controllers and never exceeds the aggregate ceiling', () => {
  const memory = createTrajectoryMemory(1024)
  const maps = Array.from({ length: 4 }, () => new TrajectoryMemoryMap({ memory }))
  for (let i = 0; i < 1000; i++) {
    maps[i % maps.length].set(i, new Float64Array(48))
    expect(memory.stats().bytes).toBeLessThanOrEqual(1024)
  }
  expect(maps.reduce((n, map) => n + map.size, 0)).toBe(2)
  expect(memory.stats().evictions).toBe(998)
  maps.forEach(map => map.clear())
  expect(memory.stats().bytes).toBe(0)
})

it('fails closed on an oversized frame and pinned ownership, without evicting pinned frames', () => {
  const memory = createTrajectoryMemory(512), map = new TrajectoryMemoryMap({ memory })
  const pinned = Symbol('export')
  memory.retain(pinned, new Uint8Array(400), null, { pinned: true })
  expect(() => map.set(0, new Uint8Array(600))).toThrow('memory budget')
  expect(() => map.set(0, new Uint8Array(200))).toThrow('budget is in use')
  expect(map.size).toBe(0)
  expect(memory.stats().bytes).toBe(400)
  memory.release(pinned)
  expect(memory.stats().bytes).toBe(0)
})

it('keeps a pinned payload accounted when its replacement cannot be admitted', () => {
  const memory = createTrajectoryMemory(512), a = Symbol(), b = Symbol()
  memory.retain(a, new Uint8Array(200), null, { pinned: true })
  memory.retain(b, new Uint8Array(200), null, { pinned: true })
  expect(() => memory.retain(a, new Uint8Array(400), null, { pinned: true })).toThrow('budget is in use')
  expect(memory.stats().bytes).toBe(400)
  memory.release(a); memory.release(b)
  expect(memory.stats().bytes).toBe(0)
})
