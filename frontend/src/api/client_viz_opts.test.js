/**
 * Guards against the align/signal positional hazard.
 *
 * History: the visualization fetchers were briefly `(id, align = true, signal)` — `align`
 * was inserted BEFORE `signal`. Any caller still on the older `(id, signal)` shape then
 * bound its AbortSignal to `align`, so the request became un-abortable (stale responses
 * raced the display) and `?align=[object AbortSignal]` went on the wire. Nothing threw at
 * the call site. That is exactly how md_viz_adapter silently broke NAMD trajectory + RMSF.
 *
 * The fix is an options object — `(id, { align, signal })` — plus these two tripwires, so
 * the mistake can never be silent again.
 */
import { describe, it, expect } from 'vitest'
import {
  getOxdnaTrajectory, getOxdnaRmsf, getOxdnaDeviation, getOxdnaDisplay,
  getOxdnaRmsfAtomistic, getOxdnaRmsfSurface, getOxdnaOccupancy,
  getLammpsTrajectory, getLammpsRmsf, getLammpsDeviation, getLammpsDisplay,
  getMdTrajectory,
} from './client.js'

const VIZ = {
  getOxdnaTrajectory, getOxdnaRmsf, getOxdnaDeviation, getOxdnaDisplay,
  getLammpsTrajectory, getLammpsRmsf, getLammpsDeviation, getLammpsDisplay,
  getOxdnaRmsfAtomistic, getOxdnaOccupancy,
}

describe('viz fetchers reject the legacy positional forms LOUDLY', () => {
  const signal = new AbortController().signal

  for (const [name, fn] of Object.entries(VIZ)) {
    it(`${name}(id, signal) throws instead of dropping the signal`, () => {
      // The old (id, signal) shape. Must not be mistaken for options.
      expect(() => fn('J1', signal)).toThrow(TypeError)
      expect(() => fn('J1', signal)).toThrow(/options object/i)
    })

    it(`${name}(id, true) throws instead of taking a positional align`, () => {
      expect(() => fn('J1', true)).toThrow(/options object/i)
    })
  }

  it('getOxdnaRmsfSurface guards its third arg too (id, params, opts)', () => {
    expect(() => getOxdnaRmsfSurface('J1', {}, true)).toThrow(/options object/i)
    expect(() => getOxdnaRmsfSurface('J1', {}, signal)).toThrow(TypeError)
  })

  it('a wrong-typed option is rejected rather than coerced onto the wire', () => {
    // `?align=[object Object]` used to reach the backend as a 422; and a truthy non-boolean
    // silently read as "aligned". Neither should be possible now.
    expect(() => getOxdnaTrajectory('J1', { align: 'yes' })).toThrow(/must be a boolean/i)
    expect(() => getOxdnaTrajectory('J1', { align: 1 })).toThrow(/must be a boolean/i)
    expect(() => getOxdnaTrajectory('J1', { signal: true })).toThrow(/must be an AbortSignal/i)
    expect(() => getOxdnaTrajectory('J1', { signal: 'abc' })).toThrow(/must be an AbortSignal/i)
  })

  it('the valid forms do NOT throw (bare, align-only, signal-only, both)', () => {
    // These reach fetch; we only care that the guard lets them through. Swallow the
    // network rejection — jsdom has no server.
    const ok = (p) => { if (p && typeof p.catch === 'function') p.catch(() => {}) }
    expect(() => ok(getOxdnaTrajectory('J1'))).not.toThrow()
    expect(() => ok(getOxdnaTrajectory('J1', {}))).not.toThrow()
    expect(() => ok(getOxdnaTrajectory('J1', { align: false }))).not.toThrow()
    expect(() => ok(getOxdnaTrajectory('J1', { signal }))).not.toThrow()
    expect(() => ok(getOxdnaTrajectory('J1', { align: true, signal }))).not.toThrow()
  })
})

describe('_oxdnaJSON choke point: a non-AbortSignal signal never reaches fetch', () => {
  it('rejects with a named, actionable TypeError', async () => {
    // getMdTrajectory takes a positional (id, signal, opts) — it has no align — so this
    // is the backstop for every fetcher of that shape, not just the viz ones above.
    await expect(getMdTrajectory('J1', true)).rejects.toThrow(TypeError)
    await expect(getMdTrajectory('J1', true)).rejects.toThrow(/must be an AbortSignal/i)
    // The message names the route so the bad call site is findable.
    await expect(getMdTrajectory('J1', true)).rejects.toThrow(/\/md\/jobs\/J1\/trajectory/)
  })

  it('the frame interval reaches the URL, and only when it is usable', async () => {
    // The guard above names the full path, so it doubles as a cheap probe of the query
    // string. Omitting ?stride is what preserves the legacy 200-frame budget server-side,
    // so "no interval" must produce a BARE url, not `?stride=undefined`.
    const bad = (opts) => getMdTrajectory('J1', true, opts).then(() => null, e => String(e.message))
    expect(await bad({ stride: 20 })).toMatch(/\/md\/jobs\/J1\/trajectory\?stride=20\b/)
    expect(await bad({ stride: 2.9 })).toMatch(/\?stride=2\b/)      // floored, never fractional
    expect(await bad({})).toMatch(/\/md\/jobs\/J1\/trajectory\)/)   // bare — no query at all
    expect(await bad({ stride: 0 })).toMatch(/\/md\/jobs\/J1\/trajectory\)/)
    expect(await bad({ stride: NaN })).toMatch(/\/md\/jobs\/J1\/trajectory\)/)
  })

  it('a real AbortSignal passes the guard untouched', async () => {
    // Can't assert the abort round-trip here: jsdom's fetch rejects on the relative
    // `/api/...` URL before the signal is ever consulted. So assert the guard specifically
    // — whatever this rejects with, it must NOT be the signal TypeError.
    const c = new AbortController()
    const err = await getMdTrajectory('J1', c.signal).then(() => null, e => e)
    expect(String(err?.message ?? '')).not.toMatch(/must be an AbortSignal/i)
  })
})

describe('getOxdnaOccupancy option passthrough', () => {
  it('defaults to the frame budget the trajectory route uses', async () => {
    // Any other max_frames misses the shared _ALIGNED_CACHE and silently re-reads the
    // whole trajectory.
    let url = null
    global.fetch = async (u) => { url = u; return { ok: true, status: 200, json: async () => ({}) } }
    await getOxdnaOccupancy('J1')
    expect(url).toMatch(/max_frames=200/)
    expect(url).toMatch(/scope=lineage/)
    expect(url).toMatch(/n_clusters=0/)
    expect(url).toMatch(/basis=nt/)
  })

  it('puts the caller\'s parameters on the wire', async () => {
    let url = null
    global.fetch = async (u) => { url = u; return { ok: true, status: 200, json: async () => ({}) } }
    await getOxdnaOccupancy('J1', { nClusters: 3, basis: 'bp', refetch: true, maxFrames: 500 })
    expect(url).toMatch(/n_clusters=3/)
    expect(url).toMatch(/basis=bp/)
    expect(url).toMatch(/refetch=true/)
    expect(url).toMatch(/max_frames=500/)
  })
})

describe('_vizOpts defaults scope even with no options object', () => {
  it('never puts the literal scope=undefined on the wire', async () => {
    let url = null
    global.fetch = async (u) => { url = u; return { ok: true, status: 200, json: async () => ({}) } }
    await getOxdnaTrajectory('J1')
    expect(url).toMatch(/scope=lineage/)
    expect(url).not.toMatch(/undefined/)
  })
})
