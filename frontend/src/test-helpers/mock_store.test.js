import { describe, it, expect, vi } from 'vitest'
import { createMockStore } from './mock_store.js'

describe('createMockStore', () => {
  it('seeds initial state and returns it from getState', () => {
    const store = createMockStore({ a: 1, b: 'x' })
    expect(store.getState()).toEqual({ a: 1, b: 'x' })
  })

  it('defaults to an empty state object', () => {
    expect(createMockStore().getState()).toEqual({})
  })

  it('setState shallow-merges and notifies subscribers with (new, prev)', () => {
    const store = createMockStore({ n: 0 })
    const cb = vi.fn()
    store.subscribe(cb)
    store.setState({ n: 1 })
    expect(store.getState()).toEqual({ n: 1 })
    expect(cb).toHaveBeenCalledWith({ n: 1 }, { n: 0 })
  })

  it('_emit behaves identically to setState', () => {
    const store = createMockStore({ n: 0 })
    const cb = vi.fn()
    store.subscribe(cb)
    store._emit({ n: 2 })
    expect(store.getState()).toEqual({ n: 2 })
    expect(cb).toHaveBeenCalledWith({ n: 2 }, { n: 0 })
  })

  it('fires subscribers in registration order', () => {
    const store = createMockStore()
    const order = []
    store.subscribe(() => order.push('first'))
    store.subscribe(() => order.push('second'))
    store.setState({ x: 1 })
    expect(order).toEqual(['first', 'second'])
  })

  it('subscribe returns an unsubscribe that stops further notifications', () => {
    const store = createMockStore()
    const cb = vi.fn()
    const off = store.subscribe(cb)
    store.setState({ x: 1 })
    off()
    store.setState({ x: 2 })
    expect(cb).toHaveBeenCalledTimes(1)
  })

  it('does not mutate the previous state object handed to subscribers', () => {
    const store = createMockStore({ n: 0 })
    let captured
    store.subscribe((_n, p) => { captured = p })
    store.setState({ n: 1 })
    expect(captured).toEqual({ n: 0 })       // prev snapshot intact
    expect(captured).not.toBe(store.getState())
  })
})
