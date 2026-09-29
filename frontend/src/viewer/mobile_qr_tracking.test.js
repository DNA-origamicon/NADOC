import { it, expect, vi, afterEach } from 'vitest'
import { mountMobileQRTracking } from './mobile_qr_tracking.js'
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })
const invitation = 'https://example.test/viewer.html#room=default&invite=secret&entry=qr'
it('explains camera unavailability and removes UI on disposal', () => {
  const ui = mountMobileQRTracking({ invitation, mediaDevices: {} })
  document.querySelector('[data-start]').click()
  expect(document.querySelector('[data-state]').textContent).toContain('HTTPS')
  ui.dispose(); expect(document.querySelector('.mobile-qr-tracking')).toBeNull()
})
it('stops a late permission result after disposal without starting a camera loop', async () => {
  let grant
  const getUserMedia = vi.fn(() => new Promise(resolve => { grant = resolve })), repeat = vi.fn(), stop = vi.fn()
  const ui = mountMobileQRTracking({ invitation, mediaDevices: { getUserMedia }, repeat })
  document.querySelector('[data-start]').click(); ui.dispose()
  grant({ getTracks: () => [{ stop }] }); await Promise.resolve()
  expect(stop).toHaveBeenCalledOnce(); expect(repeat).not.toHaveBeenCalled()
})
it('clears position and stops the camera on Stop', async () => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  const stop = vi.fn(), cancel = vi.fn(), repeat = vi.fn(() => 23)
  const ui = mountMobileQRTracking({ invitation, repeat, cancel, mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop, addEventListener() {} }] }) } })
  const root = document.querySelector('details'); root.open = true
  document.querySelector('[data-start]').click()
  await vi.waitFor(() => expect(repeat).toHaveBeenCalledOnce())
  root.dataset.position = '[0,0,1]'; document.querySelector('[data-stop]').click()
  expect(root.dataset.position).toBeUndefined(); expect(stop).toHaveBeenCalledOnce(); expect(cancel).toHaveBeenCalledWith(23)
  ui.dispose()
})
