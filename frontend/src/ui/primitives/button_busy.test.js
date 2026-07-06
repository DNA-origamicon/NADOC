/**
 * Unit tests for the busy-guard used on Start/Stop job buttons.
 *
 * Focus: a press fires the action exactly once even under a spam of clicks
 * (the re-entrancy guard), shows an immediate spinner + disabled state, and
 * restores the original label/disabled state when the action settles.
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { runExclusive, isButtonBusy, onClickExclusive } from './button_busy.js'

const flush = () => new Promise((r) => setTimeout(r, 0))
// A promise you resolve by hand, to hold an action "in flight".
function deferred() {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

afterEach(() => { document.body.innerHTML = '' })

function makeButton(label = 'Stop') {
  const btn = document.createElement('button')
  btn.textContent = label
  document.body.appendChild(btn)
  return btn
}

describe('runExclusive — spam guard', () => {
  it('runs the action once and ignores concurrent presses while in flight', async () => {
    const btn = makeButton()
    const d = deferred()
    const action = vi.fn(() => d.promise)

    const p1 = runExclusive(btn, action)   // starts it
    const p2 = runExclusive(btn, action)   // spam — swallowed
    const p3 = runExclusive(btn, action)   // spam — swallowed
    expect(action).toHaveBeenCalledTimes(1)
    expect(await p2).toBeUndefined()
    expect(await p3).toBeUndefined()

    d.resolve('done')
    expect(await p1).toBe('done')
  })

  it('allows a fresh press once the previous action settled', async () => {
    const btn = makeButton()
    const action = vi.fn(async () => 'ok')
    await runExclusive(btn, action)
    await runExclusive(btn, action)
    expect(action).toHaveBeenCalledTimes(2)
  })
})

describe('runExclusive — visual busy state', () => {
  it('immediately disables + spins, then restores label + enabled on settle', async () => {
    const btn = makeButton('Stop')
    const d = deferred()
    const p = runExclusive(btn, () => d.promise, { label: 'Stopping…' })

    // Mid-flight: disabled, busy class, spinner present, label swapped.
    expect(btn.disabled).toBe(true)
    expect(btn.classList.contains('is-busy')).toBe(true)
    expect(btn.getAttribute('aria-busy')).toBe('true')
    expect(btn.querySelector('.nadoc-spinner')).not.toBeNull()
    expect(btn.textContent).toContain('Stopping…')
    expect(isButtonBusy(btn)).toBe(true)

    d.resolve()
    await p
    // Restored: original label, enabled, no spinner/busy markers.
    expect(btn.disabled).toBe(false)
    expect(btn.classList.contains('is-busy')).toBe(false)
    expect(btn.hasAttribute('aria-busy')).toBe(false)
    expect(btn.querySelector('.nadoc-spinner')).toBeNull()
    expect(btn.textContent).toBe('Stop')
    expect(isButtonBusy(btn)).toBe(false)
  })

  it('restores state even when the action throws', async () => {
    const btn = makeButton('Stop')
    await expect(runExclusive(btn, async () => { throw new Error('boom') }))
      .rejects.toThrow('boom')
    expect(btn.disabled).toBe(false)
    expect(btn.textContent).toBe('Stop')
    expect(btn.classList.contains('is-busy')).toBe(false)
    expect(isButtonBusy(btn)).toBe(false)
  })

  it('preserves a pre-existing disabled state on restore', async () => {
    const btn = makeButton('Stop')
    btn.disabled = true
    await runExclusive(btn, async () => {})
    expect(btn.disabled).toBe(true)
  })
})

describe('runExclusive — null button', () => {
  it('still runs the action when no button is given', async () => {
    const action = vi.fn(async () => 'ran')
    expect(await runExclusive(null, action)).toBe('ran')
    expect(action).toHaveBeenCalledTimes(1)
  })
})

describe('onClickExclusive', () => {
  it('guards clicks so the handler fires once while in flight', async () => {
    const btn = makeButton()
    const d = deferred()
    const handler = vi.fn(() => d.promise)
    onClickExclusive(btn, handler, { label: 'Working…' })

    btn.click()
    btn.click()
    btn.click()
    expect(handler).toHaveBeenCalledTimes(1)
    expect(btn.disabled).toBe(true)

    d.resolve()
    await flush()
    expect(btn.disabled).toBe(false)
    btn.click()
    expect(handler).toHaveBeenCalledTimes(2)
  })
})
