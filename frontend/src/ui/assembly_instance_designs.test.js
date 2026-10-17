import { describe, it, expect, vi } from 'vitest'
import { initInstanceDesignCache } from './assembly_instance_designs.js'

describe('initInstanceDesignCache', () => {
  it('resolve: renderer fast-path, then inline fallback, caching hits', () => {
    const rendererDesigns = { a: { overhangs: [{ id: 'oa' }] } }
    const c = initInstanceDesignCache({ getInstanceDesign: (id) => rendererDesigns[id] ?? null })
    expect(c.resolve({ id: 'a' })).toBe(rendererDesigns.a)
    // inline fallback for an instance the renderer doesn't know
    const inlineDesign = { overhangs: [] }
    expect(c.resolve({ id: 'b', source: { design: inlineDesign } })).toBe(inlineDesign)
    expect(c.designFor('b')).toBe(inlineDesign)
    expect(c.overhangsFor('a').map(o => o.id)).toEqual(['oa'])
  })

  it('ensure: fetches only unresolved instances once; onReady after fetch', async () => {
    const fetched = { z: { design: { overhangs: [{ id: 'oz' }] } } }
    const fetchInstanceDesign = vi.fn((id) => Promise.resolve(fetched[id] ?? {}))
    const c = initInstanceDesignCache({ getInstanceDesign: () => null, fetchInstanceDesign })
    const onReady = vi.fn()
    const assembly = { instances: [{ id: 'z' }] }
    await c.ensure(assembly, onReady)
    expect(fetchInstanceDesign).toHaveBeenCalledTimes(1)
    expect(c.overhangsFor('z').map(o => o.id)).toEqual(['oz'])
    expect(onReady).toHaveBeenCalledTimes(1)
    // second ensure: nothing missing → no fetch, no onReady
    await c.ensure(assembly, onReady)
    expect(fetchInstanceDesign).toHaveBeenCalledTimes(1)
  })

  it('ensure: a failed fetch is not retried (attempted guard)', async () => {
    const fetchInstanceDesign = vi.fn(() => Promise.reject(new Error('nope')))
    const c = initInstanceDesignCache({ getInstanceDesign: () => null, fetchInstanceDesign })
    const assembly = { instances: [{ id: 'q' }] }
    await c.ensure(assembly)
    await c.ensure(assembly)
    expect(fetchInstanceDesign).toHaveBeenCalledTimes(1)   // no retry
  })

  it('prune: drops entries for instances no longer present', () => {
    const c = initInstanceDesignCache({ getInstanceDesign: (id) => ({ overhangs: [] }) })
    c.resolve({ id: 'a' }); c.resolve({ id: 'b' })
    c.prune(['a'])
    expect(c.designFor('a')).not.toBeNull()
    expect(c.designFor('b')).toBeNull()
  })

  it('set: overwrites a cached design', () => {
    const c = initInstanceDesignCache({})
    const d = { overhangs: [{ id: 'x' }] }
    c.set('a', d)
    expect(c.designFor('a')).toBe(d)
  })

  it('invalidates changed sources and ignores the superseded fetch', async () => {
    const finish = []
    const fetchInstanceDesign = vi.fn(() => new Promise(resolve => finish.push(resolve)))
    const c = initInstanceDesignCache({ fetchInstanceDesign })
    const first = { id: 'a', source: { type: 'file', path: '/a' }, geometrySourceKey: 'f:/a:100:' }
    const second = { ...first, geometrySourceKey: 'f:/a:101:' }
    const old = c.ensure({ instances: [first] })
    const fresh = c.ensure({ instances: [second] })
    finish[1]({ design: { id: 'new' } }); await fresh
    finish[0]({ design: { id: 'stale' } }); await old
    expect(c.designFor('a').id).toBe('new')
  })

  it('waits for renderer source readiness and consumes its version-matched Design without a base GET', async () => {
    let finish, rendered = null
    const waitForAssemblyReady = vi.fn(() => new Promise(resolve => { finish = resolve }))
    const fetchInstanceDesign = vi.fn()
    const getInstanceDesign = vi.fn(() => rendered)
    const c = initInstanceDesignCache({ waitForAssemblyReady, fetchInstanceDesign, getInstanceDesign })
    const instance = { id: 'a', source: { type: 'file', path: '/a' }, geometrySourceKey: 'f:/a:100:' }
    const assembly = { instances: [instance] }, onReady = vi.fn()
    const pending = c.ensure(assembly, onReady)
    expect(c.ensure(assembly, onReady)).toBe(pending)
    expect(fetchInstanceDesign).not.toHaveBeenCalled()
    rendered = { id: 'display', overhangs: [{ id: 'rendered-overhang' }] }
    finish(); await pending
    expect(fetchInstanceDesign).not.toHaveBeenCalled()
    expect(getInstanceDesign).toHaveBeenLastCalledWith('a', 'f:/a:100:')
    expect(c.designFor('a')).toBe(rendered)
    expect(onReady).toHaveBeenCalledOnce()
  })

  it('cancels superseded source waits and never starts their fallback reads', async () => {
    const waits = []
    const waitForAssemblyReady = vi.fn((assembly, { signal }) => new Promise(resolve => waits.push({ assembly, signal, resolve })))
    const fetchInstanceDesign = vi.fn(async () => ({ design: { id: 'fresh' } }))
    const c = initInstanceDesignCache({ waitForAssemblyReady, fetchInstanceDesign })
    const source = { type: 'file', path: '/a' }
    const old = c.ensure({ instances: [{ id: 'a', source, geometrySourceKey: 'f:/a:100:' }] })
    const next = c.ensure({ instances: [{ id: 'a', source, geometrySourceKey: 'f:/a:101:' }] })
    expect(waits[0].signal.aborted).toBe(true)
    waits[0].resolve(); await old
    expect(fetchInstanceDesign).not.toHaveBeenCalled()
    waits[1].resolve(); await next
    expect(fetchInstanceDesign).toHaveBeenCalledOnce()
    expect(c.designFor('a').id).toBe('fresh')
  })

  it('preserves per-source fallback deduplication and explicit authoring updates', async () => {
    let finish
    const fetchInstanceDesign = vi.fn(() => new Promise(resolve => { finish = resolve }))
    const c = initInstanceDesignCache({ fetchInstanceDesign })
    const pending = c.ensure({ instances: ['a', 'b'].map(id => ({ id, source: { type: 'file', path: '/shared' } })) })
    const authored = { id: 'authored' }, base = { id: 'base' }
    c.set('a', authored)
    finish({ design: base }); await pending
    expect(fetchInstanceDesign).toHaveBeenCalledOnce()
    expect(c.designFor('a')).toBe(authored)
    expect(c.designFor('b')).toBe(base)
  })

  it('does not fall back after a failed render or a cleared document', async () => {
    const fetchInstanceDesign = vi.fn()
    const failed = initInstanceDesignCache({ fetchInstanceDesign, waitForAssemblyReady: () => Promise.reject(new Error('failed')) })
    await failed.ensure({ instances: [{ id: 'a' }] })
    let finish, signal
    const cleared = initInstanceDesignCache({ fetchInstanceDesign, waitForAssemblyReady: (_, options) => {
      signal = options.signal
      return new Promise(resolve => { finish = resolve })
    } })
    const pending = cleared.ensure({ instances: [{ id: 'a' }] })
    cleared.prune([])
    expect(signal.aborted).toBe(true)
    finish(); await pending
    expect(fetchInstanceDesign).not.toHaveBeenCalled()
  })
})
