import { describe, it, expect, vi } from 'vitest'
import { initAssemblyInstanceDesignCache, versionedAssemblySourceKey } from './assembly_instance_design_cache.js'

const instance = (id, version = '100', path = '/part.nadoc') => ({
  id, name: `Part ${id}`, source: { type: 'file', path }, geometrySourceKey: `f:${path}:${version}:`,
})
function fixture(instances = [instance('a'), instance('b')]) {
  let context = { docId: 'doc-a', assembly: { id: 'assembly', instances } }
  const fetchDesign = vi.fn(async () => ({ design: { id: 'source', animations: [] }, instance_name: 'old name' }))
  const cache = initAssemblyInstanceDesignCache({ getContext: () => context, fetchDesign })
  return { cache, fetchDesign, context: () => context, set: value => { context = value } }
}

describe('versionedAssemblySourceKey', () => {
  it('accepts live file keys and rejects inline/saved keys without mtime', () => {
    expect(versionedAssemblySourceKey(instance('a'))).toBe('f:/part.nadoc:100:')
    expect(versionedAssemblySourceKey({ ...instance('a'), geometrySourceKey: 'f:/part.nadoc:deadbeef' })).toBeNull()
    expect(versionedAssemblySourceKey({ ...instance('a'), source: { type: 'inline' } })).toBeNull()
  })
})

describe('assembly base-design reads', () => {
  it('coalesces concurrent same-source reads and reuses them for later selections', async () => {
    const f = fixture()
    const [a, b] = await Promise.all([f.cache.get('a'), f.cache.get('b')])
    expect(f.fetchDesign).toHaveBeenCalledExactlyOnceWith('a', { docId: 'doc-a' })
    expect(a.design).toBe(b.design)
    expect([a.instance_name, b.instance_name]).toEqual(['Part a', 'Part b'])
    expect((await f.cache.get('a')).design).toBe(a.design)
    expect(f.fetchDesign).toHaveBeenCalledOnce()
  })

  it('retains versioned base data across placement snapshots and refetches edited files', async () => {
    const f = fixture()
    await f.cache.get('a')
    f.set({ ...f.context(), assembly: { id: 'assembly', instances: [instance('a'), instance('b')] } })
    await f.cache.get('b')
    expect(f.fetchDesign).toHaveBeenCalledOnce()
    f.set({ ...f.context(), assembly: { id: 'assembly', instances: [instance('a', '101')] } })
    await f.cache.get('a')
    expect(f.fetchDesign).toHaveBeenCalledTimes(2)
  })

  it('isolates documents and assembly identities', async () => {
    const f = fixture()
    await f.cache.get('a')
    f.set({ ...f.context(), docId: 'doc-b' }); await f.cache.get('a')
    f.set({ ...f.context(), assembly: { ...f.context().assembly, id: 'other' } }); await f.cache.get('a')
    expect(f.fetchDesign).toHaveBeenCalledTimes(3)
    expect(f.fetchDesign.mock.calls[1][1]).toEqual({ docId: 'doc-b' })
  })

  it('drops a late response after source replacement or document retirement', async () => {
    for (const changed of ['source', 'document']) {
      const f = fixture()
      let finish
      f.fetchDesign.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      const pending = f.cache.get('a'); await Promise.resolve()
      f.set(changed === 'source'
        ? { ...f.context(), assembly: { id: 'assembly', instances: [instance('a', '102')] } }
        : { docId: 'doc-b', assembly: null })
      finish({ design: { id: 'stale' } })
      expect(await pending).toBeNull()
    }
  })

  it('uses current inline data directly and treats legacy snapshots conservatively', async () => {
    const inline = { id: 'a', name: 'Inline', source: { type: 'inline', design: { id: 'd' } } }
    const f = fixture([inline])
    expect((await f.cache.get('a')).design).toBe(inline.source.design)
    expect(f.fetchDesign).not.toHaveBeenCalled()
    const legacy = () => ({ id: 'a', source: { type: 'file', path: '/legacy.nadoc' } })
    f.set({ ...f.context(), assembly: { id: 'assembly', instances: [legacy()] } })
    await f.cache.get('a'); await f.cache.get('a')
    expect(f.fetchDesign).toHaveBeenCalledOnce()
    f.set({ ...f.context(), assembly: { id: 'assembly', instances: [legacy()] } })
    await f.cache.get('a')
    expect(f.fetchDesign).toHaveBeenCalledTimes(2)
  })

  it('retries failed reads and supports calls before the assembly store is populated', async () => {
    const f = fixture()
    f.set({ docId: 'doc-a', assembly: null })
    f.fetchDesign.mockRejectedValueOnce(new Error('offline'))
    await expect(f.cache.get('a')).rejects.toThrow('offline')
    expect((await f.cache.get('a')).design.id).toBe('source')
    expect(f.fetchDesign).toHaveBeenCalledTimes(2)
  })
})
