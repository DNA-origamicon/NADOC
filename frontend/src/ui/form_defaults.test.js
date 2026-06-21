import { describe, it, expect, beforeEach } from 'vitest'
import { resetControlToDefault, resetControlsToDefaults } from './form_defaults.js'

describe('resetControlToDefault', () => {
  beforeEach(() => { document.body.innerHTML = '' })

  it('restores a number input to its HTML value attribute', () => {
    document.body.innerHTML = '<input id="a" type="number" value="0.5">'
    const el = document.getElementById('a')
    el.value = '999'
    resetControlToDefault(el)
    expect(el.value).toBe('0.5')
  })

  it('restores a text input to its HTML value attribute', () => {
    document.body.innerHTML = '<input id="a" value="CUDA">'
    const el = document.getElementById('a')
    el.value = 'edited'
    resetControlToDefault(el)
    expect(el.value).toBe('CUDA')
  })

  it('restores a checkbox to its default checked state', () => {
    document.body.innerHTML = '<input id="a" type="checkbox" checked>'
    const el = document.getElementById('a')
    el.checked = false
    resetControlToDefault(el)
    expect(el.checked).toBe(true)
  })

  it('restores a select to the option marked selected', () => {
    document.body.innerHTML =
      '<select id="a"><option>CPU</option><option selected>CUDA</option></select>'
    const el = document.getElementById('a')
    el.selectedIndex = 0
    resetControlToDefault(el)
    expect(el.value).toBe('CUDA')
  })

  it('falls back to the first option for a select with no default', () => {
    document.body.innerHTML =
      '<select id="a"><option>CPU</option><option>CUDA</option></select>'
    const el = document.getElementById('a')
    el.selectedIndex = 1
    resetControlToDefault(el)
    expect(el.selectedIndex).toBe(0)
  })

  it('is a no-op for null', () => {
    expect(() => resetControlToDefault(null)).not.toThrow()
  })
})

describe('resetControlsToDefaults', () => {
  it('resets every control and skips nulls', () => {
    document.body.innerHTML =
      '<input id="a" value="x"><input id="b" type="checkbox" checked>'
    const a = document.getElementById('a'), b = document.getElementById('b')
    a.value = 'edited'; b.checked = false
    resetControlsToDefaults([a, null, b])
    expect(a.value).toBe('x')
    expect(b.checked).toBe(true)
  })
})
