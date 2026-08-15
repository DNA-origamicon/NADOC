import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearDom } from '../test-helpers/factory_dom.js'
import { dismissToast, showPersistentToast, showToast } from './toast.js'

describe('persistent loading toast', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    dismissToast()
    vi.runAllTimers()
    clearDom()
  })

  it('shows an accessible animated spinner until dismissed', () => {
    showPersistentToast('Generating PDB…', { loading: true })
    const toast = document.querySelector('.toast')
    expect(toast?.textContent).toContain('Generating PDB…')
    expect(toast?.querySelector('.nadoc-spinner')).not.toBeNull()
    expect(toast?.getAttribute('role')).toBe('status')

    dismissToast()
    vi.advanceTimersByTime(200)
    expect(document.querySelector('.toast')).toBeNull()
  })

  it('announces ordinary notifications and errors through live regions', () => {
    showToast('Saved')
    showToast('Save failed', { severity: 'error' })
    const [status, alert] = document.querySelectorAll('.toast')
    expect(status.getAttribute('role')).toBe('status')
    expect(status.getAttribute('aria-live')).toBe('polite')
    expect(alert.getAttribute('role')).toBe('alert')
    expect(alert.getAttribute('aria-live')).toBe('assertive')
  })

  it('replaces the action when an existing persistent toast is repurposed', () => {
    const oldAction = vi.fn()
    const returnToLatest = vi.fn()
    showPersistentToast('Working…', {
      loading: true,
      action: { label: 'Cancel', onClick: oldAction },
    })

    showPersistentToast('Design rolled back.', {
      action: { label: '↩ Return to latest', onClick: returnToLatest },
    })

    const toast = document.querySelector('.toast')
    const buttons = [...toast.querySelectorAll('button')]
    const action = buttons.find((button) => button.getAttribute('aria-label') !== 'Dismiss')
    expect(action?.textContent).toBe('↩ Return to latest')

    action?.click()
    expect(returnToLatest).toHaveBeenCalledOnce()
    expect(oldAction).not.toHaveBeenCalled()
  })

  it('emits a synchronous caller trace for the atomistic loading diagnostic', () => {
    const calls = []
    window.__nadocAtomisticLoadingProbeCount = 1
    window.addEventListener('nadoc:atomistic-loading-toast-call', event => calls.push(event.detail), {
      once: true,
    })

    showPersistentToast('Loading atomistic model…', {
      diagnostic: { owner: 'unit-test-owner' },
    })

    expect(calls).toHaveLength(1)
    expect(calls[0].diagnostic).toEqual({ owner: 'unit-test-owner' })
    expect(calls[0].stack).toContain('showPersistentToast')
    window.__nadocAtomisticLoadingProbeCount = 0
  })
})
