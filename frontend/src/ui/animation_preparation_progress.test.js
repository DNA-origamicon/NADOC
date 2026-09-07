import { afterEach, describe, expect, it, vi } from 'vitest'
import { initAnimationPreparationProgress } from './animation_preparation_progress.js'

afterEach(() => { vi.useRealTimers(); document.body.innerHTML = '' })
describe('inline animation preparation', () => {
  it('reports measured progress without an overlay or moving focus, and remains cancellable', () => {
    vi.useFakeTimers()
    document.body.innerHTML = '<input id="other"><div id="host"></div>'
    const other = document.getElementById('other'); other.focus()
    const initialTimers = vi.getTimerCount()
    const cancel = vi.fn()
    const ui = initAnimationPreparationProgress({ host: document.getElementById('host'), onCancel: cancel })
    ui.start()
    expect(document.activeElement).toBe(other)
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    const progress = document.querySelector('progress')
    expect(progress.hasAttribute('value')).toBe(false)
    ui.update({ phase: 'frames', done: 7, total: 20 })
    expect(progress.value).toBe(0.35)
    expect(document.body.textContent).toContain('7 / 20')
    document.querySelector('button').click()
    expect(cancel).toHaveBeenCalledOnce()
    ui.ready()
    expect(document.body.textContent).toContain('Preview ready')
    expect(progress.value).toBe(1)
    expect(document.querySelector('button').hidden).toBe(true)
    ui.clear()
    expect(vi.getTimerCount()).toBe(initialTimers)
  })
})
