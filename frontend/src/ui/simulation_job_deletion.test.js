import { describe, it, expect, vi } from 'vitest'
import { createOptimisticJobDeletion } from './simulation_job_deletion.js'

const job = (id, engine = 'oxdna') => ({ job_id: id, engine })
function setup() {
  let nodes = [job('parent'), job('child'), job('other'), job('parent', 'namd')]
  const deselect = vi.fn(), onError = vi.fn()
  const deletion = createOptimisticJobDeletion({ getNodes: () => nodes,
    update: next => { nodes = next }, deselect, onError })
  let finish, reject
  const request = new Promise((resolve, fail) => { finish = resolve; reject = fail })
  const panel = { deleteSelected: vi.fn(({ onDeleting }) => {
    onDeleting(['parent', 'child'])
    return request
  }) }
  return { deletion, panel, finish, reject, deselect, onError, nodes: () => nodes }
}

describe('optimistic simulation deletion', () => {
  it('removes a subtree before the request settles and suppresses stale polls after success', async () => {
    const s = setup()
    const original = s.nodes()
    const pending = s.deletion.remove(original[0], s.panel)
    expect(s.nodes()).toEqual([job('other'), job('parent', 'namd')])
    expect(s.deletion.filter(original)).toEqual(s.nodes())
    await s.deletion.remove(original[0], s.panel)
    expect(s.panel.deleteSelected).toHaveBeenCalledTimes(1)
    s.finish(true)
    await pending
    expect(s.deletion.filter(original)).toEqual(s.nodes())
  })
  it.each([false, 'throw'])('restores the removed jobs on failure (%s)', async failure => {
    const s = setup()
    const pending = s.deletion.remove(s.nodes()[0], s.panel)
    if (failure === 'throw') s.reject(new Error('offline'))
    else s.finish(false)
    await pending
    expect(s.nodes()).toHaveLength(4)
    expect(s.deletion.filter(s.nodes())).toHaveLength(4)
    if (failure === 'throw') expect(s.onError).toHaveBeenCalledOnce()
  })
  it('leaves the list and selection alone when confirmation is cancelled', async () => {
    const s = setup(), original = s.nodes()
    await s.deletion.remove(original[0], { deleteSelected: async () => false })
    expect(s.nodes()).toBe(original)
    expect(s.deselect).not.toHaveBeenCalled()
  })
  it('does not restore old rows into a different document on failure', async () => {
    const s = setup()
    const pending = s.deletion.remove(s.nodes()[0], s.panel)
    s.deletion.reset()
    s.finish(false)
    await pending
    expect(s.nodes()).toHaveLength(2)
  })
})
