import { expect, it, vi } from 'vitest'
import { createDeferredRecovery } from './deferred_recovery.js'

it('keeps complete writes after paint, coalesces by document and flushes on pagehide', () => {
  vi.useFakeTimers()
  const frames = []
  vi.stubGlobal('requestAnimationFrame', fn => frames.push(fn))
  const target = new EventTarget()
  const recovery = createDeferredRecovery({ target })
  try {
    const old = vi.fn(), current = vi.fn(), other = vi.fn()
    recovery.schedule('a', old)
    recovery.schedule('a', current)
    recovery.schedule('b', other)
    expect(current).not.toHaveBeenCalled()
    while (frames.length) frames.shift()()
    expect(current).not.toHaveBeenCalled()
    recovery.cancel('b')
    target.dispatchEvent(new Event('pagehide'))
    expect(old).not.toHaveBeenCalled()
    expect(other).not.toHaveBeenCalled()
    expect(current).toHaveBeenCalledOnce()
    vi.runAllTimers()
    expect(current).toHaveBeenCalledOnce()
  } finally { recovery.dispose(); vi.useRealTimers(); vi.unstubAllGlobals() }
})
