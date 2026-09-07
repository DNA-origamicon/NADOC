import { describe, it, expect, vi } from 'vitest'
import { initTrajectoryPreparationCache } from './trajectory_preparation_cache.js'

const spec = { scope: 'job' }
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function fixture() {
  let repr = 'vdw'
  const gates = []
  const sessions = []
  const download = vi.fn(async () => ({ n_frames: 3 }))
  const cache = initTrajectoryPreparationCache({ context: () => repr, download,
    createSession: () => {
      const gate = deferred(); gates.push(gate)
      const session = { loadTrajectory: vi.fn(async () => ({ ok: true })),
        prebuildHeavy: vi.fn(async progress => { progress(1, 3); await gate.promise; return { ok: true, frames: 3 } }),
        trajectoryPreparationState: () => session, cancelPendingLoad: vi.fn(), setPlaying: vi.fn() }
      sessions.push(session); return session
    },
  })
  return { cache, gates, sessions, download, setRepr: r => { repr = r } }
}

describe('background trajectory preparation cache', () => {
  it('joins identical work and prepares the first job before downloading the next', async () => {
    const f = fixture(), progress = vi.fn()
    const a = f.cache.prepare('a', spec), joined = f.cache.prepare('a', spec, { onProgress: progress })
    const b = f.cache.prepare('b', spec)
    await vi.waitFor(() => expect(f.gates).toHaveLength(1))
    expect(f.download).toHaveBeenCalledTimes(1)
    f.gates[0].resolve(); await Promise.all([a, joined])
    await vi.waitFor(() => expect(f.gates).toHaveLength(2))
    f.gates[1].resolve(); await b
    await f.cache.prepare('a', spec)
    expect(f.sessions).toHaveLength(2)
    expect(progress).toHaveBeenCalledWith(expect.objectContaining({ phase: 'ready' }))
    expect(f.cache.snapshot('a', spec)).toBe(f.sessions[0])
  })
  it('cancels unfinished work, preserves ready entries and rejects stale completion', async () => {
    const f = fixture(), a = f.cache.prepare('a', spec)
    await vi.waitFor(() => expect(f.gates).toHaveLength(1)); f.gates[0].resolve(); await a
    const b = f.cache.prepare('b', spec)
    const rejected = expect(b).rejects.toMatchObject({ name: 'AbortError' })
    await vi.waitFor(() => expect(f.gates).toHaveLength(2))
    f.cache.cancel(); await rejected
    // UI cancellation does not wait for the in-flight backend response.
    f.gates[1].resolve()
    expect(f.sessions[1].cancelPendingLoad).toHaveBeenCalled()
    expect(f.cache.snapshot('a', spec)).toBe(f.sessions[0])
    expect(f.cache.snapshot('b', spec)).toBeUndefined()
    f.setRepr('surface'); f.cache.retain([{ jobId: 'a', ...spec }])
    expect(f.cache.snapshot('a', spec)).toBeUndefined()
  })
})
