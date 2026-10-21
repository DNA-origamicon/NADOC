import { verifySource, selectedSourceHandle, outputSize, drawFrame } from './capture.js'

const $ = id => document.getElementById(id)
const handle = decodeURIComponent(location.hash.slice(1))
let preview = $('preview')
let sourceHandle, annotationChannel
let source, recorder, output, timer, directory, busy = false, finalizing = false
const urls = []
const status = message => { $('status').textContent = message }
const active = () => recorder && recorder.state !== 'inactive'
const verify = () => verifySource(source?.getVideoTracks()[0], sourceHandle, location.origin)
function syncAnnotations() {
  annotationChannel?.postMessage({ type: 'annotations', enabled: !!source && $('annotations').checked })
}
function releaseAnnotations() {
  annotationChannel?.postMessage({ type: 'annotations', enabled: false })
  annotationChannel?.close()
  annotationChannel = null
}
const annotationTimer = setInterval(syncAnnotations, 2000)
$('annotations').onchange = syncAnnotations
function update() {
  for (const id of ['start', 'resolution', 'fps', 'directory']) $(id).disabled = busy || finalizing || !!active()
  $('select-tab').disabled = busy || finalizing
  $('stop').disabled = !active() || finalizing
  $('screenshot').disabled = busy || finalizing
  $('release').disabled = !source || busy || finalizing || !!active()
}
function stop() {
  if (active()) { finalizing = true; recorder.stop(); status('Finishing recording…') }
  clearInterval(timer)
  output?.getTracks().forEach(track => track.stop())
  output = null
  update()
}
function disconnect() {
  stop()
  source?.getTracks().forEach(track => track.stop())
  source = null
  sourceHandle = null
  releaseAnnotations()
  $('source-name').textContent = 'No tab selected'
  preview.srcObject = null
  update()
}
async function connect(reselect = false) {
  if (source && !reselect) { verify(); return }
  if (!navigator.mediaDevices?.getDisplayMedia || !globalThis.MediaStreamTrack?.prototype.getCaptureHandle || !handle) {
    throw new Error('Open Tools → Record in NADOC using Chrome or Edge on HTTPS or localhost.')
  }
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: { displaySurface: 'browser', frameRate: { ideal: Number($('fps').value) } },
    audio: false, monitorTypeSurfaces: 'exclude', selfBrowserSurface: 'exclude', surfaceSwitching: 'exclude',
  })
  const track = stream.getVideoTracks()[0]
  let selected, candidate
  try {
    selected = selectedSourceHandle(track, location.origin)
    // Prepare the replacement before touching the current recording source.
    candidate = document.createElement('video')
    candidate.muted = true; candidate.autoplay = true; candidate.playsInline = true
    candidate.srcObject = stream
    await candidate.play()
    verifySource(track, selected, location.origin)
    if (track.readyState === 'ended') throw new Error('The selected tab stopped sharing. Select it again.')
  } catch (error) { stream.getTracks().forEach(t => t.stop()); throw error }
  const previous = source
  releaseAnnotations()
  source = stream
  sourceHandle = selected
  annotationChannel = new BroadcastChannel(selected)
  candidate.id = 'preview'
  candidate.setAttribute('aria-label', 'NADOC capture preview')
  preview.replaceWith(candidate)
  preview = candidate
  previous?.getTracks().forEach(t => t.stop())
  $('source-name').textContent = track.label || 'NADOC tab selected'
  track.addEventListener('ended', () => {
    if (source !== stream) return
    disconnect(); status('Capture ended. Any recording is being saved.')
  })
  track.addEventListener('capturehandlechange', () => {
    if (source !== stream) return
    try { verify() } catch { disconnect(); status('Capture stopped: the selected tab changed identity. Select a NADOC tab again.') }
  })
  syncAnnotations()
}

function frame(canvas) {
  verify()
  if (!preview.videoWidth || !preview.videoHeight) throw new Error('The NADOC capture is not ready. Try again.')
  drawFrame(canvas.getContext('2d'), preview, canvas.width, canvas.height)
}
function canvasForCapture() {
  const canvas = document.createElement('canvas')
  ;[canvas.width, canvas.height] = outputSize(preview.videoWidth, preview.videoHeight, $('resolution').value)
  frame(canvas)
  return canvas
}
async function save(blob, extension) {
  if (!blob?.size) throw new Error('The capture was empty. Please try again.')
  const name = `NADOC-${new Date().toISOString().replace(/[:.]/g, '-')}-${crypto.randomUUID().slice(0, 8)}.${extension}`
  // Keep a recovery link even when directory access is revoked or the disk is full.
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob); urls.push(link.href)
  link.download = name; link.textContent = name
  const item = document.createElement('li'); item.append(link); $('files').prepend(item)
  if (directory) {
    try {
      const file = await directory.getFileHandle(name, { create: true })
      const writable = await file.createWritable()
      try { await writable.write(blob); await writable.close() }
      catch (error) { await writable.abort().catch(() => {}); throw error }
      status(`Saved ${name} to ${directory.name}.`)
    } catch (error) { status(`Directory save failed: ${error.message}. Use the download link below to save your capture.`) }
  } else { link.click(); status(`Downloaded ${name}.`) }
}
async function run(action) {
  busy = true; update()
  try { await action() }
  catch (error) { status(error.name === 'NotAllowedError' || error.name === 'AbortError' ? 'Capture or directory selection canceled.' : error.message) }
  finally { busy = false; update() }
}
$('select-tab').onclick = () => run(async () => {
  await connect(true)
  status(active() ? 'Recording continues with the selected NADOC tab.' : 'Tab selected. Ready to record or take a screenshot.')
})
$('directory').onclick = () => run(async () => {
  if (!window.showDirectoryPicker) { status('Directory selection is unavailable. Captures use your browser’s download location.'); return }
  directory = await window.showDirectoryPicker({ mode: 'readwrite' })
  $('destination').textContent = directory.name
})
$('start').onclick = () => run(async () => {
  if (!globalThis.MediaRecorder) throw new Error('Video recording is unavailable in this browser.')
  const mimeType = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find(type => MediaRecorder.isTypeSupported(type))
  if (!mimeType) throw new Error('This browser cannot record WebM video.')
  await connect()
  const canvas = canvasForCapture(), fps = Number($('fps').value)
  output = canvas.captureStream(fps)
  const chunks = []
  try { recorder = new MediaRecorder(output, { mimeType }) }
  catch (error) { stop(); throw error }
  recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
  recorder.onerror = event => { status(`Recording error: ${event.error?.message || 'encoder failed'}`); stop() }
  recorder.onstop = async () => {
    finalizing = true; update()
    try { await save(new Blob(chunks, { type: mimeType }), 'webm') }
    catch (error) { status(error.message) }
    finally { chunks.length = 0; recorder = null; finalizing = false; update() }
  }
  try { recorder.start(1000) } catch (error) { recorder = null; stop(); throw error }
  const started = performance.now()
  timer = setInterval(() => {
    try { frame(canvas); status(`Recording • ${Math.floor((performance.now() - started) / 1000)} seconds`) }
    catch (error) { disconnect(); status(error.message) }
  }, 1000 / fps)
  status('Recording. Return to the NADOC tab to work; use Stop & save here when finished.')
})
$('stop').onclick = stop
$('release').onclick = () => { disconnect(); status('Capture disconnected.') }
$('screenshot').onclick = () => run(async () => {
  await connect()
  const canvas = canvasForCapture()
  const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'))
  await save(blob, 'png')
})
window.addEventListener('beforeunload', event => {
  if (active() || finalizing || busy) { event.preventDefault(); event.returnValue = '' }
})
window.addEventListener('pagehide', () => { clearInterval(annotationTimer); disconnect(); urls.forEach(url => URL.revokeObjectURL(url)) })
update()
