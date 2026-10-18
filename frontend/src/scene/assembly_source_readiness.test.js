import { describe, expect, it, vi } from 'vitest'
import { initAssemblySourceReadiness } from './assembly_source_readiness.js'

describe('assembly source readiness', () => {
  it('accepts subscriptions before rebuild and resolves only matching source data', async () => {
    const ready = new Set()
    const gate = initAssemblySourceReadiness({ isReady: assembly => ready.has(assembly) })
    const first = {}, second = {}, complete = vi.fn()
    const pending = gate.whenReady(first).then(complete)
    ready.add(second)
    gate.notify()
    await Promise.resolve()
    expect(complete).not.toHaveBeenCalled()
    ready.add(first)
    gate.notify()
    await pending
    expect(complete).toHaveBeenCalledOnce()
    await expect(gate.whenReady(first)).resolves.toBeUndefined()
  })

  it('cancels only the aborted document waiter', async () => {
    let ready = false
    const gate = initAssemblySourceReadiness({ isReady: () => ready })
    const controller = new AbortController()
    const old = gate.whenReady({}, { signal: controller.signal })
    const fresh = gate.whenReady({})
    const rejected = expect(old).rejects.toMatchObject({ name: 'AbortError' })
    controller.abort()
    await rejected
    ready = true
    gate.notify()
    await fresh
    await expect(gate.whenReady({}, { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('reports build failure and cancels disposal without poisoning future loads', async () => {
    const gate = initAssemblySourceReadiness({ isReady: () => false })
    const error = new Error('Geometry unavailable')
    const failed = expect(gate.whenReady({})).rejects.toBe(error)
    gate.fail(error)
    await failed
    await expect(gate.whenReady({})).rejects.toBe(error)
    gate.begin()
    const disposed = expect(gate.whenReady({})).rejects.toMatchObject({ name: 'AbortError' })
    gate.reset()
    await disposed
    const retry = expect(gate.whenReady({})).rejects.toBe(error)
    gate.fail(error)
    await retry
  })

  it('keeps failures observable until an explicit retry, then publishes only ready data', async () => {
    let ready = false
    const gate = initAssemblySourceReadiness({ isReady: () => ready })
    const error = new Error('Source unavailable')
    gate.fail(error)
    await expect(gate.whenReady({})).rejects.toBe(error)
    await expect(gate.whenReady({})).rejects.toBe(error)
    gate.begin()
    const complete = vi.fn(), retry = gate.whenReady({}).then(complete)
    gate.notify()
    await Promise.resolve()
    expect(complete).not.toHaveBeenCalled()
    ready = true
    gate.notify()
    await retry
    expect(complete).toHaveBeenCalledOnce()
  })
})
