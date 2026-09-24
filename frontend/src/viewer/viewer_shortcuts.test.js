import { it, expect, vi } from 'vitest'
import { mountViewerShortcuts } from './viewer_shortcuts.js'
it('opens metrics with Ctrl+P instead of the print dialog and cleans up', () => {
  const panel = { open: false, showModal: vi.fn() }, dispose = mountViewerShortcuts({ performancePanel: panel })
  const press = () => { const event = new KeyboardEvent('keydown', { key: 'p', ctrlKey: true, cancelable: true }); document.dispatchEvent(event); return event }
  expect(press().defaultPrevented).toBe(true); expect(panel.showModal).toHaveBeenCalledOnce()
  panel.open = true; press(); expect(panel.showModal).toHaveBeenCalledOnce()
  dispose(); expect(press().defaultPrevented).toBe(false)
})
