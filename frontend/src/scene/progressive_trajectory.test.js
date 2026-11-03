import { expect, it, vi } from 'vitest'
import { loadProgressiveTrajectory } from './progressive_trajectory.js'

function dependencies(budgetBytes) {
  return {
    jobId: 'large', spec: {}, budgetBytes, live: () => true,
    metadata: async () => ({ n_frames: 64 }), heavy: async () => 0, evict: vi.fn(),
    downloads: {
      get: vi.fn(async (_id, spec) => ({ ready: true, keys: [['h', 0, 'FORWARD']],
        frames: Array.from({ length: spec.frameEnd - spec.frameStart + 1 }, () => new Float32Array(6)) })),
      consumed: vi.fn(),
    },
  }
}

it('evicts old pages and reloads exact frames while staying within the budget', async () => {
  const options = dependencies(512)
  const stream = await loadProgressiveTrajectory(options)
  await stream.ensure(0)
  expect(stream.status().bytes).toBe(192)
  await stream.ensure(8)
  expect(stream.status().bytes).toBe(384)
  expect(stream.resp.frames[0]).toBeUndefined()
  expect(options.evict).toHaveBeenCalledWith(0)
  await stream.ensure(0)
  expect(stream.resp.frames[0]).toBeInstanceOf(Float32Array)
  expect(stream.resp.frames[8]).toBeUndefined()
  expect(stream.status().bytes).toBeLessThanOrEqual(512)
})

it('rejects a page that cannot fit and rejects unsafe frame counts', async () => {
  await expect(loadProgressiveTrajectory(dependencies(100))).rejects.toThrow('memory budget')
  const options = dependencies(512)
  options.metadata = async () => ({ n_frames: 10_000_000 })
  await expect(loadProgressiveTrajectory(options)).rejects.toThrow('Too many trajectory frames')
})

it('shares its budget with another trajectory, reloads evicted pages and releases on abort', async () => {
  const { createTrajectoryMemory } = await import('./trajectory_memory.js')
  const memory = createTrajectoryMemory(512)
  const abort = new AbortController()
  const a = await loadProgressiveTrajectory({ ...dependencies(512), memory, signal: abort.signal })
  await a.ensure(0)
  const b = await loadProgressiveTrajectory({ ...dependencies(512), memory })
  await b.ensure(8)
  expect(a.resp.frames[0]).toBeUndefined()
  expect(a.status().buffered).toBe(0)
  await a.ensure(0)
  expect(a.resp.frames[0]).toBeInstanceOf(Float32Array)
  expect(b.resp.frames[8]).toBeUndefined()
  expect(memory.stats().peakBytes).toBeLessThanOrEqual(512)
  abort.abort(); b.dispose()
  expect(memory.stats().bytes).toBe(0)
})

it('does not retain a response that finishes after cancellation', async () => {
  const { createTrajectoryMemory } = await import('./trajectory_memory.js')
  const memory = createTrajectoryMemory(512), abort = new AbortController()
  const options = dependencies(512)
  const a = await loadProgressiveTrajectory({ ...options, memory, signal: abort.signal })
  await a.ensure(0)
  let finish
  options.downloads.get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const pending = a.ensure(8)
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  abort.abort()
  finish({ ready: true, frames: Array.from({ length: 16 }, () => new Float32Array(6)) })
  expect(await pending).toBe(false)
  expect(memory.stats().bytes).toBe(0)
  expect(a.status().buffered).toBe(0)
})
