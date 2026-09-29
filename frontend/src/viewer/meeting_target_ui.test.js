import { it, expect, vi, afterEach } from 'vitest'
import { initMeetingTarget } from './meeting_target_ui.js'
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })
const share = { url: 'https://example.test/#invite=guest&password=required', expiresAt: 2000 }
function setup() {
  document.body.innerHTML = '<dialog><div data-links></div></dialog>'
  const onError = vi.fn(), ui = initMeetingTarget({ parent: document.querySelector('dialog'), now: () => 1000, onError })
  return { ui, onError, root: document.querySelector('.meeting-target'), button: document.querySelector('[data-print-meeting-target]') }
}
it('shows only a current invitation, keeps QR stable on polling and clears it on revocation', () => {
  const { ui, root, button } = setup()
  expect(root.hidden).toBe(true)
  ui.setShare(share)
  expect(root.hidden).toBe(false)
  const svg = root.querySelector('svg'); expect(svg).not.toBeNull()
  ui.setShare({ ...share }); expect(root.querySelector('svg')).toBe(svg)
  ui.setBusy(true); expect(button.disabled).toBe(true)
  ui.setBusy(false); expect(button.disabled).toBe(false)
  ui.setShare({ ...share, expiresAt: 999 }); expect(root.hidden).toBe(true)
  ui.setShare(null); expect(root.querySelector('svg')).toBeNull()
  ui.dispose(); expect(document.querySelector('.meeting-target')).toBeNull()
})
it('reports blocked printing and never prints an expired invitation', () => {
  const { ui, onError, button } = setup(), open = vi.spyOn(window, 'open').mockReturnValue(null)
  ui.setShare(share); button.click()
  expect(onError.mock.calls[0][0].message).toContain('Allow the print window')
  ui.setShare({ ...share, expiresAt: 999 }); button.click(); expect(open).toHaveBeenCalledOnce()
})
it('uses the separate QR credential and exposes the larger tracking print only for QR-enabled hosts', () => {
  const { ui, root } = setup()
  ui.setShare(share)
  expect(root.querySelector('[data-print-mobile-target]').hidden).toBe(true)
  const old = root.querySelector('svg').outerHTML
  ui.setShare({ ...share, qrUrl: 'https://example.test/#invite=qr-only&entry=qr' })
  expect(root.querySelector('svg').outerHTML).not.toBe(old)
  expect(root.querySelector('[data-print-mobile-target]').hidden).toBe(false)
  expect(root.textContent).toContain('guest name')
  ui.dispose()
})
