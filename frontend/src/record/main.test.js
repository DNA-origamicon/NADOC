import html from '../../record.html?raw'
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve() }
let track, blobs, recorder, channels
const sourceId = 'nadoc-capture-v1:12345678-1234-1234-1234-123456789abc'
beforeEach(async () => {
  vi.resetModules()
  vi.useFakeTimers()
  channels = []
  vi.stubGlobal('BroadcastChannel', class {
    constructor(name) { this.name = name; this.postMessage = vi.fn(); this.close = vi.fn(); channels.push(this) }
  })
  document.body.innerHTML = html.split('<body>')[1].split('</body>')[0]
  location.hash = 'nadoc-test'
  track = { getSettings: () => ({ displaySurface: 'browser' }), getCaptureHandle: () => ({ handle: sourceId, origin: location.origin }), stop: vi.fn(), addEventListener: vi.fn() }
  const media = { getVideoTracks: () => [track], getTracks: () => [track] }
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getDisplayMedia: vi.fn().mockResolvedValue(media) } })
  vi.stubGlobal('MediaStreamTrack', class { getCaptureHandle() {} })
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  vi.spyOn(HTMLVideoElement.prototype, 'videoWidth', 'get').mockReturnValue(1600)
  vi.spyOn(HTMLVideoElement.prototype, 'videoHeight', 'get').mockReturnValue(900)
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ fillRect() {}, drawImage() {} })
  HTMLCanvasElement.prototype.captureStream = vi.fn(() => ({ getTracks: () => [{ stop: vi.fn() }] }))
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(cb => cb(new Blob(['png'], { type: 'image/png' })))
  blobs = []
  URL.createObjectURL = vi.fn(blob => { blobs.push(blob); return 'blob:capture' })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  vi.stubGlobal('MediaRecorder', class {
    static isTypeSupported() { return true }
    constructor() { recorder = this; this.state = 'inactive' }
    start() { this.state = 'recording' }
    stop() { this.state = 'inactive'; this.ondataavailable({ data: new Blob(['video']) }); void this.onstop() }
  })
  await import('./main.js')
})
afterEach(() => { document.getElementById('stop').click(); vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
it('records and saves video, then takes a screenshot from the same source', async () => {
  document.getElementById('start').click(); await settle()
  expect(recorder.state).toBe('recording')
  expect(document.getElementById('resolution').disabled).toBe(true)
  document.getElementById('stop').click(); await settle()
  expect(blobs[0].type).toContain('video/webm')
  document.getElementById('screenshot').click(); await settle()
  expect(blobs[1].type).toBe('image/png')
  expect(navigator.mediaDevices.getDisplayMedia).toHaveBeenCalledTimes(1)
  expect(document.querySelectorAll('#files a')).toHaveLength(2)
})
it('rejects and releases a screen capture before saving anything', async () => {
  track.getSettings = () => ({ displaySurface: 'monitor' })
  document.getElementById('screenshot').click(); await settle()
  expect(track.stop).toHaveBeenCalled()
  expect(blobs).toHaveLength(0)
  expect(document.getElementById('status').textContent).toContain('NADOC 3D viewer')
})
it('preserves a recovery link when saving to a directory fails', async () => {
  window.showDirectoryPicker = vi.fn().mockResolvedValue({ name: 'Captures', getFileHandle: vi.fn().mockRejectedValue(new Error('Disk full')) })
  document.getElementById('directory').click(); await settle()
  document.getElementById('screenshot').click(); await settle()
  expect(document.getElementById('status').textContent).toContain('Disk full')
  expect(document.querySelector('#files a').download).toMatch(/\.png$/)
  delete window.showDirectoryPicker
})
it('enables annotations on the selected tab and disables them on disconnect', async () => {
  const toggle = document.getElementById('annotations')
  toggle.checked = true
  toggle.dispatchEvent(new Event('change'))
  expect(channels).toHaveLength(0)
  document.getElementById('start').click(); await settle()
  expect(channels[0].name).toBe(sourceId)
  expect(channels[0].postMessage).toHaveBeenLastCalledWith({ type: 'annotations', enabled: true })
  toggle.checked = false
  toggle.dispatchEvent(new Event('change'))
  expect(channels[0].postMessage.mock.lastCall[0].enabled).toBe(false)
  document.getElementById('stop').click(); await settle()
  document.getElementById('release').click()
  expect(channels[0].postMessage.mock.lastCall[0].enabled).toBe(false)
  expect(channels[0].close).toHaveBeenCalled()
})
it('selects a tab before recording without a second browser chooser', async () => {
  document.getElementById('select-tab').click(); await settle()
  expect(document.getElementById('source-name').textContent).toBe('NADOC tab selected')
  document.getElementById('start').click(); await settle()
  expect(navigator.mediaDevices.getDisplayMedia).toHaveBeenCalledTimes(1)
  expect(recorder.state).toBe('recording')
})
it('switches source during one continuous recording and transfers annotations', async () => {
  document.getElementById('annotations').checked = true
  document.getElementById('start').click(); await settle()
  const originalRecorder = recorder
  const oldMedia = document.getElementById('preview').srcObject
  const replacementTrack = { ...track, stop: vi.fn(), label: 'NADOC cadnano editor', getCaptureHandle: () => ({ handle: 'nadoc-capture-v1:abcdefab-1234-1234-1234-123456789abc', origin: location.origin }) }
  const replacement = { getVideoTracks: () => [replacementTrack], getTracks: () => [replacementTrack] }
  navigator.mediaDevices.getDisplayMedia.mockResolvedValueOnce(replacement)
  document.getElementById('select-tab').click(); await settle()
  expect(recorder).toBe(originalRecorder)
  expect(recorder.state).toBe('recording')
  expect(document.getElementById('preview').srcObject).toBe(replacement)
  expect(oldMedia.getTracks()[0].stop).toHaveBeenCalled()
  expect(channels[0].postMessage.mock.lastCall[0].enabled).toBe(false)
  expect(channels[1].postMessage.mock.lastCall[0].enabled).toBe(true)
  expect(document.getElementById('source-name').textContent).toContain('cadnano')
})
it('preserves the current recording on chooser cancellation, wrong source or playback failure', async () => {
  document.getElementById('start').click(); await settle()
  const originalMedia = document.getElementById('preview').srcObject
  navigator.mediaDevices.getDisplayMedia.mockRejectedValueOnce(new DOMException('Canceled', 'NotAllowedError'))
  document.getElementById('select-tab').click(); await settle()
  expect(document.getElementById('preview').srcObject).toBe(originalMedia)
  const rejectedTrack = { ...track, stop: vi.fn(), getSettings: () => ({ displaySurface: 'monitor' }) }
  navigator.mediaDevices.getDisplayMedia.mockResolvedValueOnce({ getVideoTracks: () => [rejectedTrack], getTracks: () => [rejectedTrack] })
  document.getElementById('select-tab').click(); await settle()
  expect(rejectedTrack.stop).toHaveBeenCalled()
  expect(track.stop).not.toHaveBeenCalled()
  expect(document.getElementById('preview').srcObject).toBe(originalMedia)
  const failedTrack = { ...track, stop: vi.fn() }
  navigator.mediaDevices.getDisplayMedia.mockResolvedValueOnce({ getVideoTracks: () => [failedTrack], getTracks: () => [failedTrack] })
  HTMLMediaElement.prototype.play.mockRejectedValueOnce(new Error('Playback failed'))
  document.getElementById('select-tab').click(); await settle()
  expect(failedTrack.stop).toHaveBeenCalled()
  expect(track.stop).not.toHaveBeenCalled()
  expect(recorder.state).toBe('recording')
  expect(document.getElementById('preview').srcObject).toBe(originalMedia)
})
