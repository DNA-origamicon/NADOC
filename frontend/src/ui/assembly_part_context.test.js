import { describe, it, expect, vi } from 'vitest'
import { initAssemblyPartContext } from './assembly_part_context.js'

function fixture() {
  const api = { getInstanceDesign: vi.fn(async () => ({ design: { id: 'd', animations: [] } })), patchInstanceDesign: vi.fn() }
  const onChange = vi.fn(), beforePatch = vi.fn()
  return { api, onChange, beforePatch, context: initAssemblyPartContext({ api, onChange, beforePatch }) }
}

describe('selected assembly part context', () => {
  it('selection only reads and no-op modifiers neither patch nor rebuild', async () => {
    const f = fixture()
    await f.context.select('a')
    expect(f.api.patchInstanceDesign).not.toHaveBeenCalled()
    await f.onChange.mock.calls[0][2](design => { design.animations = [] })
    expect(f.api.patchInstanceDesign).not.toHaveBeenCalled()
    expect(f.beforePatch).not.toHaveBeenCalled()
  })

  it('explicit edits clone the source, patch once, and publish the canonical result', async () => {
    const f = fixture(), original = { id: 'd', animations: [] }, canonical = { id: 'd', animations: [{ id: 'new', name: 'Canonical' }] }
    f.api.getInstanceDesign.mockResolvedValueOnce({ design: original }).mockResolvedValueOnce({ design: canonical })
    await f.context.select('a')
    await f.onChange.mock.calls[0][2](design => { design.animations.push({ id: 'new', name: 'animation 1' }) })
    expect(original.animations).toEqual([])
    expect(f.api.patchInstanceDesign).toHaveBeenCalledExactlyOnceWith('a', JSON.stringify({ id: 'd', animations: [{ id: 'new', name: 'animation 1' }] }))
    expect(f.beforePatch).toHaveBeenCalledExactlyOnceWith('a')
    expect(f.onChange.mock.lastCall[1]).toBe(canonical)
  })

  it('rejects stale A→B→A responses and failures', async () => {
    const f = fixture(), completions = []
    f.api.getInstanceDesign.mockImplementation(() => new Promise((resolve, reject) => completions.push({ resolve, reject })))
    const a1 = f.context.select('a'), b = f.context.select('b'), a2 = f.context.select('a')
    completions[2].resolve({ design: { id: 'current' } }); await a2
    completions[0].resolve({ design: { id: 'old' } }); await a1
    completions[1].reject(new Error('old failure')); await b
    expect(f.onChange).toHaveBeenCalledOnce()
    expect(f.onChange.mock.lastCall.slice(0, 2)).toEqual(['a', { id: 'current' }])
  })

  it('does not republish an unchanged cached design or allow old patch callbacks after reselect', async () => {
    const f = fixture(), design = { id: 'd', animations: [] }
    f.api.getInstanceDesign.mockResolvedValue({ design })
    await f.context.select('a')
    const stalePatch = f.onChange.mock.lastCall[2]
    await f.context.select('a', { force: true })
    expect(f.onChange).toHaveBeenCalledOnce()
    await f.context.select('b'); await f.context.select('a')
    await stalePatch(value => { value.animations.push({ id: 'unwanted' }) })
    expect(f.api.patchInstanceDesign).not.toHaveBeenCalled()
  })

  it('blocks stale authoring during refresh and shares completion with a repeated same-ID selection', async () => {
    const f = fixture(), original = { id: 'd', sourceRevision: 1, animations: [] }
    const fresh = { id: 'd', sourceRevision: 2, animations: [{ id: 'external' }] }
    let finish
    f.api.getInstanceDesign.mockResolvedValueOnce({ design: original })
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await f.context.select('a')
    const retainedPatch = f.onChange.mock.lastCall[2]
    const refreshing = f.context.select('a', { force: true })
    let selectionFinished = false
    const repeated = f.context.select('a').then(() => { selectionFinished = true })
    await retainedPatch(design => { design.animations.push({ id: 'stale' }) })
    expect(selectionFinished).toBe(false)
    expect(f.api.getInstanceDesign).toHaveBeenCalledTimes(2)
    expect(f.api.patchInstanceDesign).not.toHaveBeenCalled()
    expect(f.beforePatch).not.toHaveBeenCalled()

    finish({ design: fresh })
    await Promise.all([refreshing, repeated])
    expect(selectionFinished).toBe(true)
    expect(f.onChange.mock.lastCall[1]).toBe(fresh)
    await f.onChange.mock.lastCall[2](design => { design.animations.push({ id: 'authored' }) })
    expect(f.api.patchInstanceDesign).toHaveBeenCalledExactlyOnceWith('a', JSON.stringify({
      id: 'd', sourceRevision: 2, animations: [{ id: 'external' }, { id: 'authored' }],
    }))
    expect(original.animations).toEqual([])
    expect(fresh.animations).toEqual([{ id: 'external' }])
  })

  it('does not unlock a stale callback when an obsolete forced refresh finishes first', async () => {
    const f = fixture(), finishes = []
    await f.context.select('a')
    const retainedPatch = f.onChange.mock.lastCall[2]
    f.api.getInstanceDesign.mockImplementation(() => new Promise(resolve => { finishes.push(resolve) }))
    const oldRefresh = f.context.select('a', { force: true })
    const latestRefresh = f.context.select('a', { force: true })
    finishes[0]({ design: { id: 'old', animations: [] } })
    await oldRefresh
    await retainedPatch(design => { design.animations.push({ id: 'stale' }) })
    expect(f.api.patchInstanceDesign).not.toHaveBeenCalled()
    finishes[1]({ design: { id: 'latest', animations: [] } })
    await latestRefresh
    expect(f.onChange.mock.lastCall[1].id).toBe('latest')
  })

  it('retires an unresolved refresh and permits a later same-ID retry', async () => {
    const f = fixture()
    await f.context.select('a')
    const retainedPatch = f.onChange.mock.lastCall[2]
    f.api.getInstanceDesign.mockResolvedValueOnce(null)
    await f.context.select('a', { force: true })
    expect(f.onChange.mock.lastCall).toEqual([null, null, null])
    await retainedPatch(design => { design.animations.push({ id: 'stale' }) })
    expect(f.api.patchInstanceDesign).not.toHaveBeenCalled()
    f.api.getInstanceDesign.mockResolvedValueOnce({ design: { id: 'retried', animations: [] } })
    await f.context.select('a')
    expect(f.onChange.mock.lastCall[1].id).toBe('retried')
  })
})
