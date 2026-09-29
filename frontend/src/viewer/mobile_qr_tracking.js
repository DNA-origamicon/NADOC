import './mobile_qr_tracking.css'
import jsQR from 'jsqr'
import { estimateQRPose } from './qr_pose.js'

/** Opt-in local camera diagnostic. No camera images or poses leave this browser. */
export function mountMobileQRTracking({ document: doc = document, invitation, mediaDevices = doc.defaultView.navigator.mediaDevices, decode = jsQR, repeat = setInterval, cancel = clearInterval }) {
  const root = doc.createElement('details'); root.className = 'mobile-qr-tracking'
  root.style.cssText = 'position:fixed;bottom:12px;left:12px;z-index:15;background:#17232f;color:white;padding:10px;border-radius:8px;width:min(360px,calc(100vw - 44px));max-height:70vh;overflow:auto'
  root.innerHTML = '<summary>Phone tracking · prototype</summary><p>Point the rear camera at this meeting’s printed QR. Keep it visible. Estimates are relative to the QR, not yet to the headset.</p><label>Printed QR width including white border (mm) <input data-size type="number" min="20" max="1000" value="40"></label><label>Approximate vertical camera angle (degrees) <input data-fov type="number" min="20" max="120" value="60"></label><p><button type="button" data-start>Start camera tracking</button> <button type="button" data-stop disabled>Stop</button></p><canvas hidden style="width:100%;height:auto"></canvas><output style="display:block" data-state>Camera off. Camera permission is needed; images stay on this device.</output><p>Use the large tracking QR sheet for easier detection. Its width is 150 mm; the small QR on the combined sheet is 40 mm. A larger print is easier to track: enter its measured width. Position estimates need camera calibration; do not use for collision avoidance.</p>'
  doc.body.append(root)
  const start = root.querySelector('[data-start]'), stopButton = root.querySelector('[data-stop]'), state = root.querySelector('[data-state]'), canvas = root.querySelector('canvas')
  const video = doc.createElement('video'); video.muted = true; video.playsInline = true
  let stream = null, timer = null, disposed = false, generation = 0, lastVideoTime = -1, lastFrameAt = 0
  const expected = new URL(invitation)
  const specifiedSize = Number(new URLSearchParams(expected.hash.slice(1)).get('qrmm'))
  if (specifiedSize >= 20 && specifiedSize <= 1000) root.querySelector('[data-size]').value = String(specifiedSize)
  function matches(data) {
    try {
      const candidate = new URL(data), a = new URLSearchParams(candidate.hash.slice(1)), b = new URLSearchParams(expected.hash.slice(1))
      return candidate.origin === expected.origin && candidate.pathname === expected.pathname && ['room', 'invite', 'entry'].every(k => a.get(k) === b.get(k))
    } catch { return false }
  }
  function stop(message = 'Camera off.') {
    generation++
    if (timer !== null) cancel(timer)
    timer = null; stream?.getTracks().forEach(track => track.stop()); stream = null
    video.srcObject = null; canvas.hidden = true; delete root.dataset.position
    start.disabled = false; stopButton.disabled = true; state.textContent = message
  }
  function frame() {
    if (disposed || !stream || !video.videoWidth || !video.videoHeight) return
    if (video.currentTime === lastVideoTime) {
      if (Date.now() - lastFrameAt > 750) { delete root.dataset.position; state.textContent = 'Camera stalled. Position unavailable.' }
      return
    }
    lastVideoTime = video.currentTime; lastFrameAt = Date.now()
    const ratio = Math.min(1, 720 / Math.max(video.videoWidth, video.videoHeight))
    canvas.width = Math.round(video.videoWidth * ratio); canvas.height = Math.round(video.videoHeight * ratio)
    const context = canvas.getContext('2d', { willReadFrequently: true })
    try {
      context.drawImage(video, 0, 0, canvas.width, canvas.height)
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height)
      const code = decode(pixels.data, pixels.width, pixels.height, { inversionAttempts: 'dontInvert' })
      delete root.dataset.position
      const printedSize = Number(root.querySelector('[data-size]').value) / 1000
      const pose = code && matches(code.data) && printedSize >= .02 && printedSize <= 1 ? estimateQRPose(code, canvas.width, canvas.height, { printedSize, verticalFov: Number(root.querySelector('[data-fov]').value) }) : null
      if (!pose) { state.textContent = code && !matches(code.data) ? 'Different invitation. Point at this meeting’s QR.' : 'Searching — keep the whole QR visible, closer and well lit. Position unavailable.'; return }
      context.strokeStyle = '#39ff91'; context.lineWidth = 3; context.beginPath()
      pose.corners.forEach((p, i) => i ? context.lineTo(p.x, p.y) : context.moveTo(p.x, p.y)); context.closePath(); context.stroke()
      root.dataset.position = JSON.stringify(pose.position)
      const [x, y, z] = pose.position.map(v => (v * 100).toFixed(1))
      state.textContent = `Tracking · approximate phone position: right ${x} cm, up ${y} cm, out from paper ${z} cm.`
    } catch { stop('Camera processing failed. Stop and retry camera tracking.') }
  }
  start.onclick = async () => {
    if (disposed || start.disabled) return
    if (!mediaDevices?.getUserMedia) { state.textContent = 'Camera unavailable. Open the HTTPS invitation in a browser that supports camera access.'; return }
    const attempt = ++generation; start.disabled = true; stopButton.disabled = false; state.textContent = 'Waiting for camera permission…'
    try {
      const acquired = await mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } } })
      if (disposed || attempt !== generation) { acquired.getTracks().forEach(track => track.stop()); return }
      lastVideoTime = -1; lastFrameAt = Date.now()
      stream = acquired; video.srcObject = stream
      stream.getTracks().forEach(track => track.addEventListener('ended', () => { if (attempt === generation) stop('Camera disconnected. Start again to retry.') }))
      await video.play()
      if (disposed || attempt !== generation) return
      canvas.hidden = false; state.textContent = 'Searching for this meeting’s QR…'; timer = repeat(frame, 150)
    } catch { if (attempt === generation) stop('Camera could not start. Allow camera access in browser settings, then retry.') }
  }
  stopButton.onclick = () => stop()
  const visibility = () => { if (doc.hidden) stop('Camera paused while the page is hidden. Start again to resume.') }
  const toggle = () => { if (!root.open) stop() }
  const pagehide = () => stop()
  doc.addEventListener('visibilitychange', visibility); root.addEventListener('toggle', toggle); doc.defaultView.addEventListener('pagehide', pagehide)
  return { dispose() { disposed = true; stop(); doc.removeEventListener('visibilitychange', visibility); doc.defaultView.removeEventListener('pagehide', pagehide); root.removeEventListener('toggle', toggle); root.remove() } }
}
