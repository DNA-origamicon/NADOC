import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createInputAnnotations, inputLabel } from './input_annotations.js'
let annotations
const overlay = () => document.querySelector('[data-nadoc-input-annotations]')?.shadowRoot
beforeEach(() => { vi.useFakeTimers(); annotations = createInputAnnotations(); document.body.innerHTML = '' })
afterEach(() => { annotations.dispose(); vi.useRealTimers() })
it('formats modifiers, special keys and mouse buttons', () => {
  expect(inputLabel({ type: 'keydown', key: 's', ctrlKey: true, shiftKey: true })).toBe('Ctrl + Shift + S')
  expect(inputLabel({ type: 'keydown', key: ' ', altKey: true })).toBe('Alt + Space')
  expect(inputLabel({ type: 'keydown', key: 'Shift', shiftKey: true })).toBe('Shift')
  expect(inputLabel({ type: 'pointerdown', button: 2, shiftKey: true })).toBe('Shift + Right click')
})
it('shows bounded, expiring annotations and correctly positioned click markers', () => {
  annotations.setEnabled(true)
  for (const key of ['a', 'b', 'c', 'd', 'e']) document.dispatchEvent(new KeyboardEvent('keydown', { key }))
  expect(overlay().querySelectorAll('.key')).toHaveLength(4)
  document.dispatchEvent(new MouseEvent('pointerdown', { button: 1, clientX: 123, clientY: 456 }))
  expect(overlay().querySelector('.click').style.left).toBe('123px')
  expect(overlay().querySelector('.click').style.top).toBe('456px')
  expect(overlay().textContent).toContain('Middle click')
  vi.advanceTimersByTime(700)
  expect(overlay().querySelector('.click')).toBeNull()
  vi.advanceTimersByTime(1600)
  expect(overlay().querySelectorAll('.key')).toHaveLength(0)
})
it('omits field typing, password input, IME and auto-repeat', () => {
  annotations.setEnabled(true)
  document.body.insertAdjacentHTML('beforeend', '<input><input type="password"><textarea></textarea><div contenteditable="true"><span>edit</span></div>')
  for (const target of document.querySelectorAll('input,textarea,[contenteditable] span')) {
    target.dispatchEvent(new KeyboardEvent('keydown', { key: 'secret', bubbles: true }))
  }
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', repeat: true }))
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', isComposing: true }))
  expect(overlay().querySelectorAll('.key')).toHaveLength(0)
})
it('clears on focus loss and removes listeners and markers when disabled', () => {
  annotations.setEnabled(true)
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }))
  window.dispatchEvent(new Event('blur'))
  expect(overlay().querySelectorAll('.key')).toHaveLength(0)
  annotations.setEnabled(false)
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'b' }))
  expect(overlay()).toBeUndefined()
  expect(vi.getTimerCount()).toBe(0)
})
