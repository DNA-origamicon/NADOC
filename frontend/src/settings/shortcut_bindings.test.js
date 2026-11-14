import { expect, it } from 'vitest'
import { parseShortcut, formatShortcut, shortcutId, validateShortcutConflicts } from './shortcut_bindings.js'
it('parses portable shortcuts and rejects malformed key names', () => {
  expect(parseShortcut('Ctrl+Shift+K')).toEqual({ key: 'k', ctrl: true, shift: true, alt: false })
  expect(formatShortcut(parseShortcut('Alt+Space'))).toBe('Alt+Space')
  expect(() => parseShortcut('Control+wat')).toThrow()
})
it('detects remapped collisions including wildcard modifiers', () => {
  const a = { key: 'a', description: 'Action A' }, b = { key: 'b', ctrl: true, description: 'Action B' }
  expect(() => validateShortcutConflicts({ [shortcutId(a)]: 'Ctrl+B' }, [a, b])).toThrow('conflict')
  expect(validateShortcutConflicts({ [shortcutId(a)]: 'Ctrl+K' }, [a, b])).toEqual({ [shortcutId(a)]: 'Ctrl+K' })
})

import { clearShortcuts, registerShortcut, getShortcuts, dispatchKeyEvent } from '../input/shortcuts.js'
import { writePreferences } from './preferences.js'
it('updates both shortcut help and dispatch while retaining input guards', async () => {
  localStorage.clear(); clearShortcuts()
  let calls = 0
  const spec = { key: 'k', ctrl: true, description: 'Test command', blockedInInput: true, handler: () => { calls++ } }
  registerShortcut(spec)
  writePreferences({ shortcutBindings: { [shortcutId(spec)]: 'Ctrl+Shift+J' } })
  expect(getShortcuts()[0]).toMatchObject({ key: 'j', ctrl: true, shift: true })
  const press = target => dispatchKeyEvent({ key: 'j', ctrlKey: true, shiftKey: true, altKey: false, target })
  await press(document.createElement('input')); expect(calls).toBe(0)
  await press(document.body); expect(calls).toBe(1)
  clearShortcuts(); localStorage.clear()
})
