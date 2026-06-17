import { describe, it, expect, afterEach } from 'vitest'
import { isUndefinedSequenceError, showSequenceWarningModal } from './sequence_warning_modal.js'

describe('isUndefinedSequenceError', () => {
  it('is false for empty / unrelated errors', () => {
    expect(isUndefinedSequenceError(null)).toBe(false)
    expect(isUndefinedSequenceError(undefined)).toBe(false)
    expect(isUndefinedSequenceError('')).toBe(false)
    expect(isUndefinedSequenceError('oxDNA binary not found.')).toBe(false)
    expect(isUndefinedSequenceError('Unknown backend: "FOO"')).toBe(false)
  })

  it('matches the backend undefined-base / unsequenced messages', () => {
    expect(isUndefinedSequenceError('Design has 17 undefined bases — oxDNA needs …'))
      .toBe(true)
    expect(isUndefinedSequenceError('Design has 1 undefined base — finish assigning.'))
      .toBe(true)
    expect(isUndefinedSequenceError('Design has no sequence assigned — oxDNA needs …'))
      .toBe(true)
  })
})

describe('showSequenceWarningModal', () => {
  afterEach(() => {
    document.querySelectorAll('.seq-warning-overlay').forEach((n) => n.remove())
  })

  it('renders the backend message and dismisses on OK', () => {
    const overlay = showSequenceWarningModal({ message: 'Design has 3 undefined bases — fix it.' })
    expect(document.querySelector('.seq-warning-overlay')).toBe(overlay)
    expect(overlay.textContent).toContain('3 undefined bases')
    const ok = [...overlay.querySelectorAll('button')].find((b) => b.textContent === 'OK')
    ok.click()
    expect(document.querySelector('.seq-warning-overlay')).toBe(null)
  })

  it('invokes onClose when dismissed', () => {
    let closed = false
    const overlay = showSequenceWarningModal({ message: 'x', onClose: () => { closed = true } })
    overlay.querySelector('button').click()   // ✕ close button
    expect(closed).toBe(true)
  })
})
