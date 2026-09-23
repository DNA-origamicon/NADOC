import { it, expect, vi, afterEach } from 'vitest'
import { mountMeetingStatus } from './meeting_status.js'
afterEach(() => { document.body.innerHTML = '' })
it('shows measured loading then terminates the scene and blocks stale loading after End', () => {
  document.body.innerHTML = '<main><canvas></canvas></main><p id="status"></p>'
  const viewer = { clear: vi.fn() }, ui = mountMeetingStatus({ viewer })
  ui.progress({ fraction: .42 }); expect(document.querySelector('#meeting-loading').hidden).toBe(false)
  expect(document.querySelector('progress').value).toBe(.42)
  ui.progress(null); expect(document.querySelector('#meeting-loading').hidden).toBe(true)
  ui.end(); expect(viewer.clear).toHaveBeenCalledOnce()
  expect(document.querySelector('#presentation-ended').hidden).toBe(false)
  expect(document.querySelector('main').inert).toBe(true)
  ui.progress({ fraction: .9 }); expect(document.querySelector('#meeting-loading').hidden).toBe(true)
  ui.dispose()
})
