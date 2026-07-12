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
})
