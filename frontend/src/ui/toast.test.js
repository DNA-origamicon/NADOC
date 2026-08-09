import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearDom } from '../test-helpers/factory_dom.js'
import { dismissToast, showPersistentToast } from './toast.js'

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
})
