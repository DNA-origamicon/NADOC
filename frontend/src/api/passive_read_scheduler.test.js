import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPassiveReadScheduler } from './passive_read_scheduler.js'
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

it('serializes passive reads and gives waiting foreground work priority', async () => {
  const lane = createPassiveReadScheduler(), first = deferred(), foreground = deferred(), order = []
  const a = lane.run('a', () => { order.push('a'); return first.promise }, { passive: true })
  await vi.advanceTimersByTimeAsync(0)
  const b = lane.run('b', () => { order.push('b'); return 2 }, { passive: true })
  const f = lane.run('f', () => { order.push('f'); return foreground.promise })
  first.resolve(1); await a; await vi.advanceTimersByTimeAsync(0)
  expect(order).toEqual(['a', 'f'])
  foreground.resolve(3); await f; await vi.advanceTimersByTimeAsync(0)
  expect(await b).toBe(2); expect(order).toEqual(['a', 'f', 'b'])
})
it('coalesces queued equivalents without coupling subscriber cancellation', async () => {
  const lane = createPassiveReadScheduler(), hold = deferred(), ctrl = new AbortController(), task = vi.fn(() => 4)
  const fg = lane.run('f', () => hold.promise)
  const a = lane.run('p', task, { passive: true, signal: ctrl.signal }).catch(e => e.name)
  const b = lane.run('p', task, { passive: true })
  ctrl.abort(); expect(await a).toBe('AbortError')
  hold.resolve(); await fg; await vi.advanceTimersByTimeAsync(0)
  expect(await b).toBe(4); expect(task).toHaveBeenCalledTimes(1)
})
it('retains the lane until an abandoned in-flight transport actually drains', async () => {
  const lane = createPassiveReadScheduler(), hold = deferred(), ctrl = new AbortController(), next = vi.fn()
  const a = lane.run('p', () => hold.promise, { passive: true, signal: ctrl.signal }).catch(e => e.name)
  await vi.advanceTimersByTimeAsync(0); ctrl.abort(); expect(await a).toBe('AbortError')
  const b = lane.run('f', next); await vi.advanceTimersByTimeAsync(0); expect(next).not.toHaveBeenCalled()
  hold.resolve(); await vi.advanceTimersByTimeAsync(0); await b; expect(next).toHaveBeenCalledOnce()
})
it('bounds queued keys and retires stale reads before dispatch and adoption', async () => {
  const lane = createPassiveReadScheduler({ maxPending: 1 }), hold = deferred(), task = vi.fn(), active = deferred()
  const fg = lane.run('f', () => hold.promise)
  let current = true
  const a = lane.run('p', task, { passive: true, current: () => current }).catch(e => e.name)
  await expect(lane.run('q', task, { passive: true })).rejects.toThrow('queue is full')
  current = false; hold.resolve(); await fg; await vi.advanceTimersByTimeAsync(0)
  expect(await a).toBe('AbortError'); expect(task).not.toHaveBeenCalled()
  current = true
  const b = lane.run('r', () => active.promise, { passive: true, current: () => current }).catch(e => e.name)
  await vi.advanceTimersByTimeAsync(0); current = false; active.resolve(1)
  expect(await b).toBe('AbortError')
})
it('releases on failure and reset removes queued reads without cancelling writes', async () => {
  const lane = createPassiveReadScheduler(), hold = deferred(), task = vi.fn()
  const fg = lane.run('f', () => hold.promise)
  const pending = lane.run('p', task, { passive: true }).catch(e => e.name)
  lane.reset(); expect(await pending).toBe('AbortError'); hold.resolve(); await fg
  const failed = lane.run('r', () => { throw Error('network') }, { passive: true }).catch(e => e.message)
  await vi.advanceTimersByTimeAsync(0); expect(await failed).toBe('network')
  expect(await lane.run('f', () => 7)).toBe(7); expect(task).not.toHaveBeenCalled()
})

it('never dispatches a cancelled foreground waiter and bounds duplicate subscribers', async () => {
  const lane = createPassiveReadScheduler({ maxSubscribers: 1 }), hold = deferred(), ctrl = new AbortController(), task = vi.fn()
  const active = lane.run('p', () => hold.promise, { passive: true })
  await vi.advanceTimersByTimeAsync(0)
  const foreground = lane.run('f', task, { signal: ctrl.signal }).catch(e => e.name)
  const queued = lane.run('q', () => 1, { passive: true })
  await expect(lane.run('q', task, { passive: true })).rejects.toThrow('queue is full')
  ctrl.abort(); expect(await foreground).toBe('AbortError')
  hold.resolve(); await active; expect(await queued).toBe(1); expect(task).not.toHaveBeenCalled()
})

it('lets one history gesture pass a passive read without releasing its lane or fanning out writes', async () => {
  const lane = createPassiveReadScheduler(), read = deferred(), undo = deferred(), order = []
  const background = lane.run('read', () => read.promise, { passive: true })
  await vi.advanceTimersByTimeAsync(0)
  const first = lane.run('undo', () => { order.push('undo'); return undo.promise }, { interactive: true })
  const second = lane.run('redo', () => { order.push('redo'); return 2 }, { interactive: true })
  const pending = lane.run('next-read', () => { order.push('read'); return 3 }, { passive: true })
  expect(order).toEqual(['undo'])
  undo.resolve(1); await first; await vi.advanceTimersByTimeAsync(0)
  expect(await second).toBe(2)
  expect(order).toEqual(['undo', 'redo'])
  read.resolve(); await background; await vi.advanceTimersByTimeAsync(0)
  expect(await pending).toBe(3)
})
