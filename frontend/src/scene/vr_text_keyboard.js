/** Shared VR text entry. Hosts retain validation, submission and cancellation. */
export const TEXT_KEY_ROWS = [
  [...'1234567890', 'delete'], [...'qwertyuiop'], [...'asdfghjkl'],
  ['shift', ...'zxcvbnm', 'dot', 'dash', 'underscore'], ['space', 'symbols'],
]
const punctuation = [...'!@#$%^&*()[]{}<>/\\|:;"\'?,=']
const letters = [...'qwertyuiopasdfghjklzxcvbnm']
const shiftedCharacters = { ...Object.fromEntries([...'1234567890'].map((n, i) => [n, '!@#$%^&*()'[i]])), dot: '>', dash: '_' }

export function createVRTextKeyboard() {
  let upper = false, symbols = false, target = null
  function reset() { upper = symbols = false; target = null }
  function controls(input, { prefix = 'text-key-', maxLength = input.maxLength >= 0 ? input.maxLength : Infinity,
    transform = value => value, accepts = () => true } = {}) {
    if (target !== input) { reset(); target = input }
    const editable = () => target === input && input.isConnected && !input.disabled && !input.readOnly
    const edit = character => {
      if (!editable()) return
      const value = input.value, end = input.selectionEnd ?? value.length
      let start = input.selectionStart ?? value.length
      if (character === null && start === end) start = Math.max(0, start - ([...value.slice(0, start)].at(-1)?.length || 0))
      const insertion = character ?? ''
      const next = value.slice(0, start) + insertion + value.slice(end)
      if (next.length > maxLength) return
      input.value = next
      if (input.selectionStart !== null) input.setSelectionRange(start + insertion.length, start + insertion.length)
      input.dispatchEvent(new input.ownerDocument.defaultView.Event('input', { bubbles: true }))
    }
    return TEXT_KEY_ROWS.flat().map(key => {
      const special = ['shift', 'delete', 'symbols'].includes(key)
      const shifted = upper && !symbols ? shiftedCharacters[key] : undefined
      const character = transform(shifted ?? (symbols ? { dot: '+', dash: '`', underscore: '~' }[key] : undefined)
        ?? ({ space: ' ', dot: '.', dash: '-', underscore: '_' })[key]
        ?? (symbols && letters.includes(key) ? punctuation[letters.indexOf(key)] : upper ? key.toUpperCase() : key))
      const enabled = editable() && (special || accepts(character))
      return { id: prefix + key, label: ({ shift: 'Shift', delete: 'Backspace', symbols: symbols ? 'ABC' : '#+=', space: 'Space' })[key] ?? character,
        enabled, active: key === 'shift' && upper || key === 'symbols' && symbols,
        run() {
          if (!enabled || !editable()) return
          if (key === 'shift') upper = !upper
          else if (key === 'symbols') symbols = !symbols
          else edit(key === 'delete' ? null : character)
        } }
    })
  }
  return { controls, reset }
}
