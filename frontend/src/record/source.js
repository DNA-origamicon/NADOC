import { createInputAnnotations } from './input_annotations.js'

// Only NADOC application entry points register a capturable identity.
export function registerRecordingSource() {
  const handle = `nadoc-capture-v1:${crypto.randomUUID()}`
  navigator.mediaDevices?.setCaptureHandleConfig?.({ handle, exposeOrigin: true, permittedOrigins: [location.origin] })
  const annotations = createInputAnnotations()
  const channel = new BroadcastChannel(handle)
  let expiry
  channel.onmessage = ({ data }) => {
    if (data?.type !== 'annotations') return
    clearTimeout(expiry)
    annotations.setEnabled(data.enabled === true)
    if (data.enabled === true) expiry = setTimeout(() => annotations.dispose(), 6000)
  }
  window.addEventListener('pagehide', () => { clearTimeout(expiry); annotations.dispose(); channel.close() })
  return handle
}
