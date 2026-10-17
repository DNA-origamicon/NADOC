import { describe, expect, it, vi } from 'vitest'
import { createAssemblyRebuildQueue } from './assembly_rebuild_queue.js'

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

describe('assembly rebuild queue', () => {
  it('shares one build for concurrent requests of the same snapshot', async () => {
    const wait = deferred(), snapshot = {}
    const run = vi.fn(() => wait.promise)
    const queue = createAssemblyRebuildQueue(run)
    const first = queue.request(snapshot)
    expect(queue.request(snapshot)).toBe(first)
    await Promise.resolve()
    expect(queue.request(snapshot)).toBe(first)
    expect(run).toHaveBeenCalledOnce()
    wait.resolve()
    await first
    await queue.request(snapshot)
    expect(run).toHaveBeenCalledTimes(2)
  })

  it('serializes work, drops superseded pending snapshots and waits for the latest', async () => {
    const wait = deferred(), committed = []
    const run = vi.fn(async (value, current) => {
      if (value === 'first') await wait.promise
      if (current()) committed.push(value)
    })
    const queue = createAssemblyRebuildQueue(run)
    const first = queue.request('first')
    await Promise.resolve()
    queue.request('middle')
    const last = queue.request('last')
    expect(run).toHaveBeenCalledTimes(1)
    wait.resolve()
    await Promise.all([first, last])
    expect(run.mock.calls.map(call => call[0])).toEqual(['first', 'last'])
    expect(committed).toEqual(['last'])
  })

  it('reruns a snapshot invalidated while its fetch is in flight', async () => {
    const wait = deferred(), snapshot = {}
    const run = vi.fn().mockImplementationOnce(() => wait.promise).mockResolvedValue()
    const queue = createAssemblyRebuildQueue(run)
    const result = queue.request(snapshot, 1)
    await Promise.resolve()
    queue.request(snapshot, 2)
    wait.resolve()
    await result
    expect(run).toHaveBeenCalledTimes(2)
  })

  it('prevents cancelled work from publishing and allows a later scene', async () => {
    const wait = deferred(), committed = []
    const queue = createAssemblyRebuildQueue(async (value, current) => {
      await wait.promise
      if (current()) committed.push(value)
    })
    const result = queue.request('closed')
    await Promise.resolve()
    queue.cancel()
    wait.resolve()
    await result
    expect(committed).toEqual([])
    await queue.request('reopened')
    expect(committed).toEqual(['reopened'])
  })

  it('recovers after an obsolete request fails while newer work is queued', async () => {
    const wait = deferred(), run = vi.fn().mockImplementationOnce(() => wait.promise).mockResolvedValue()
    const queue = createAssemblyRebuildQueue(run)
    const result = queue.request('old')
    await Promise.resolve()
    queue.request('new')
    wait.reject(new Error('old request failed'))
    await result
    expect(run.mock.calls.map(call => call[0])).toEqual(['old', 'new'])
  })
})
