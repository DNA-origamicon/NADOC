// @vitest-environment jsdom
import { it, expect, vi, afterEach } from 'vitest'
import { createVRTextKeyboard } from './vr_text_keyboard.js'
afterEach(() => document.body.replaceChildren())
const mount = (tag = 'input') => { const input = document.createElement(tag); document.body.append(input); return input }
it('edits at the caret, replaces selections, deletes whole Unicode characters and emits input', () => {
  const input = mount(), keyboard = createVRTextKeyboard(), changed = vi.fn()
  input.addEventListener('input', changed); input.value = 'hello'; input.setSelectionRange(1, 4)
  const key = name => keyboard.controls(input).find(c => c.id === 'text-key-' + name).run()
  key('a'); expect(input.value).toBe('hao'); expect(input.selectionStart).toBe(2)
  key('delete'); expect(input.value).toBe('ho')
  input.value = 'a😀'; key('delete'); expect(input.value).toBe('a')
  expect(changed).toHaveBeenCalledTimes(3)
})
it('shares Shift and symbol entry, resets between fields and guards detached/readonly targets', () => {
  const keyboard = createVRTextKeyboard(), a = mount(), b = mount('textarea')
  const key = (input, name) => keyboard.controls(input).find(c => c.id === 'text-key-' + name)
  key(a, 'shift').run(); key(a, 'a').run(); key(a, 'symbols').run(); key(a, 'w').run()
  expect(a.value).toBe('A@')
  key(b, 'a').run(); expect(b.value).toBe('a')
  const stale = key(a, 'b'); a.remove(); stale.run(); expect(a.value).toBe('A@')
  b.readOnly = true; expect(key(b, 'q').enabled).toBe(false)
})
it('respects host length and alphabet restrictions without changing numeric widgets', () => {
  const input = mount('textarea'), keyboard = createVRTextKeyboard()
  const controls = () => keyboard.controls(input, { maxLength: 2, transform: s => s.toUpperCase(), accepts: s => /^[ACGTN]$/.test(s) })
  controls().find(c => c.id === 'text-key-c').run()
  controls().find(c => c.id === 'text-key-a').run()
  controls().find(c => c.id === 'text-key-g').run()
  expect(input.value).toBe('CA'); expect(controls().find(c => c.id === 'text-key-b').enabled).toBe(false)
  input.setSelectionRange(0, 2); controls().find(c => c.id === 'text-key-t').run(); expect(input.value).toBe('T')
})
it('provides standard shifted numbers and all symbol-page punctuation', () => {
  const input = mount(), keyboard = createVRTextKeyboard()
  const key = name => keyboard.controls(input).find(c => c.id === 'text-key-' + name).run()
  key('shift'); key('1'); key('2'); key('symbols'); key('r'); key('dot'); key('dash'); key('underscore')
  expect(input.value).toBe('!@$+`~')
})
it('edits nonnumeric input types that do not expose a selection API', () => {
  const input = mount(), keyboard = createVRTextKeyboard(), changed = vi.fn()
  input.type = 'email'; input.value = 'a'; input.addEventListener('input', changed)
  keyboard.controls(input).find(c => c.id === 'text-key-b').run()
  expect(input.value).toBe('ab'); expect(changed).toHaveBeenCalledOnce()
})
