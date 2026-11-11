// @vitest-environment jsdom
import { beforeEach, it, expect, vi } from 'vitest'
import { registerShortcut, clearShortcuts, dispatchKeyEvent } from './shortcuts.js'

beforeEach(() => { clearShortcuts(); document.body.replaceChildren() })
const press = (target = document.body) => dispatchKeyEvent({ key: '2', target, preventDefault: vi.fn() })
it('blocks numeric commands in open dialogs even when focus remains on the canvas', async () => {
  const handler = vi.fn();registerShortcut({ key: '2', handler })
  const popup = document.createElement('div');popup.setAttribute('role', 'dialog');document.body.append(popup)
  await press();expect(handler).not.toHaveBeenCalled()
  popup.hidden = true;await press();expect(handler).toHaveBeenCalledOnce()
  popup.hidden = false;popup.style.display = 'none';await press();expect(handler).toHaveBeenCalledTimes(2)
  popup.remove();await press();expect(handler).toHaveBeenCalledTimes(3)
})
it.each(['number', 'text'])('protects focused %s fields even for retargeted events and unguarded registrations', async type => {
  const handler = vi.fn();registerShortcut({ key: '2', handler })
  const input = document.createElement('input');input.type = type;document.body.append(input);input.focus()
  await press(input);await press();expect(handler).not.toHaveBeenCalled()
  input.blur();await press();expect(handler).toHaveBeenCalledOnce()
})
it('protects contenteditable text, including plaintext-only names', async () => {
  const handler = vi.fn();registerShortcut({ key: '2', handler })
  const input = document.createElement('div');input.setAttribute('contenteditable', 'plaintext-only');document.body.append(input)
  await press(input);expect(handler).not.toHaveBeenCalled()
})
