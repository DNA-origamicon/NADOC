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
})
