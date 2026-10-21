import { registerRecordingSource } from '../record/source.js'

// Each NADOC tab registers separately; the recorder explicitly selects its source.
export function initRecordLauncher({ onError = () => {} } = {}) {
  const handle = registerRecordingSource()
  let controls
  document.getElementById('menu-tools-record')?.addEventListener('click', () => {
    if (!navigator.mediaDevices?.setCaptureHandleConfig) {
      onError('Recording requires Chrome or Edge on HTTPS or localhost.')
      return
    }
    navigator.mediaDevices.setCaptureHandleConfig({ handle, exposeOrigin: true, permittedOrigins: [location.origin] })
    if (controls && !controls.closed) { controls.focus(); return }
    controls = window.open(`./record.html#${encodeURIComponent(handle)}`, '_blank')
    if (!controls) onError('Allow pop-ups for NADOC to open recording controls.')
  })
}
