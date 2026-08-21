import { beforeEach, describe, expect, it, vi } from 'vitest'
import { initReverseComplement, reverseComplement } from './reverse_complement.js'

describe('reverseComplement', () => {
  it('reverses and complements DNA while ignoring whitespace and case', () => {
    expect(reverseComplement('aa cg\nt')).toBe('ACGTT')
  })

  it('supports ambiguous IUPAC bases', () => {
    expect(reverseComplement('ARYN')).toBe('NRYT')
  })

  it('rejects unsupported characters', () => {
    expect(() => reverseComplement('ACGT-')).toThrow(/DNA\/IUPAC/)
  })
})

describe('initReverseComplement', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <h2 id="reverse-complement-heading" aria-expanded="true"></h2>
      <span id="reverse-complement-arrow"></span>
      <div id="reverse-complement-body">
      <textarea id="reverse-complement-input"></textarea>
      <textarea id="reverse-complement-output"></textarea>
      <button id="reverse-complement-copy"></button>
      <span id="reverse-complement-status"></span></div>`
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) },
    })
  })

  it('updates live and copies the complete output', async () => {
    initReverseComplement()
    const input = document.getElementById('reverse-complement-input')
    const output = document.getElementById('reverse-complement-output')
    input.value = 'AAGC'
    input.dispatchEvent(new Event('input'))
    expect(output.value).toBe('GCTT')
    expect(document.getElementById('reverse-complement-status').textContent).toBe('4 nt')
    document.getElementById('reverse-complement-copy').click()
    await Promise.resolve()
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('GCTT')
  })

  it('collapses from the header and remains keyboard accessible', () => {
    initReverseComplement()
    const heading = document.getElementById('reverse-complement-heading')
    const body = document.getElementById('reverse-complement-body')
    heading.click()
    expect(body.hidden).toBe(true)
    expect(heading.getAttribute('aria-expanded')).toBe('false')
    heading.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    expect(body.hidden).toBe(false)
  })
})
