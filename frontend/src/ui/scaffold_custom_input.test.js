import { afterEach, beforeEach, expect, it } from 'vitest'
import { scaffoldSequenceError, scaffoldSequenceChoice, validateScaffoldSequenceChoice, wireScaffoldCustomInput } from './scaffold_custom_input.js'
let root
beforeEach(() => {
  root = document.createElement('div')
  root.innerHTML = `<input type="radio" name="asc-scaffold" value="M13mp18">
    <input type="radio" name="asc-scaffold" value="custom" checked>
    <div id="asc-custom-panel"><textarea id="asc-custom-seq"></textarea></div>
    <span id="asc-custom-char-count"></span><span id="asc-custom-error"></span>`
  document.body.append(root)
  wireScaffoldCustomInput(root, () => {})
})
afterEach(() => {
  document.querySelector('.scaffold-sequence-error .modal__actions button')?.click()
  document.body.replaceChildren()
})
it.each(['ATGCN', 'ACGU', 'ATGC1', '>header\nATGC', 'A-C', ''])('rejects %s with a popup before assignment', value => {
  root.querySelector('textarea').value = value // Deliberately bypass input events.
  expect(validateScaffoldSequenceChoice(root)).toBeNull()
  expect(document.querySelector('.scaffold-sequence-error')).not.toBeNull()
  expect(root.querySelector('textarea').value).toBe(value)
})
it('normalizes pasted case and formatting without replacing non-ATGC characters', () => {
  root.querySelector('textarea').value = ' a t\nG\tc '
  expect(validateScaffoldSequenceChoice(root)).toEqual({ scaffoldName: 'custom', customRaw: 'ATGC' })
  expect(scaffoldSequenceError('atgc')).toBeNull()
  expect(scaffoldSequenceError('atgn')).toContain('"N"')
})
it('opens a popup on invalid paste and preserves the editor when dismissed', () => {
  const input = root.querySelector('textarea')
  input.value = 'ATGN'
  input.dispatchEvent(new InputEvent('input', { inputType: 'insertFromPaste', bubbles: true }))
  expect(document.querySelector('.scaffold-sequence-error').textContent).toContain('"N"')
  document.querySelector('.scaffold-sequence-error .modal__actions button').click()
  expect(input.value).toBe('ATGN')
  expect(document.activeElement).toBe(input)
})
it('preset selection ignores leftover custom text and hides its editor', () => {
  root.querySelector('textarea').value = 'INVALID'
  const preset = root.querySelector('input[value=M13mp18]')
  preset.checked = true
  preset.dispatchEvent(new Event('change'))
  expect(root.querySelector('#asc-custom-panel').hidden).toBe(true)
  expect(scaffoldSequenceChoice(root)).toEqual({ scaffoldName: 'M13mp18', customRaw: '' })
  expect(validateScaffoldSequenceChoice(root)).not.toBeNull()
  expect(document.querySelector('.scaffold-sequence-error')).toBeNull()
})
