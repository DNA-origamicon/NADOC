/**
 * Client-side video / GIF export for NADOC animations.
 *
 * Drives the animation player frame-by-frame (seekTo per frame) so output is
 * deterministic regardless of machine speed.
 *
 * Formats
 *   'webm' — canvas.captureStream(0) + MediaRecorder (VP9 → VP8 → default)
 *   'gif'  — gifenc (pure-JS quantizer, no worker required)
 *
 * @param {object} opts
 * @param {object}   opts.animation    — DesignAnimation object
 * @param {object}   opts.renderer     — THREE.WebGLRenderer
 * @param {object}   opts.scene        — THREE.Scene
 * @param {object}   opts.camera       — THREE.PerspectiveCamera
 * @param {object}   opts.player       — initAnimationPlayer instance
 * @param {object}   [opts.options]    — { format, resolution, fps }
 * @param {function} [opts.onProgress] — called with fraction (0–1) each frame
 * @param {function} [opts.onPhase]    — (phaseKey, {done, total}) for the phase-weighted
 *   export bar (see scene/export_progress.js). Every long step reports through this;
 *   `onProgress` remains the per-frame-only callback it always was.
 */
export async function exportVideo({ animation, renderer, scene, camera, player, options = {}, onProgress, onPhase, signal }) {
  const { format = 'webm', fps: fpsOpt, resolution = 'current' } = options
  const fps = Math.max(1, Math.min(60, fpsOpt ?? animation.fps ?? 30))

  // Ensure schedule is built without visible playback.
  // play() is async (bakes geometry); await it so _totalDur is set before we read it.
  // Everything inside play() — geometry batch, trajectory download, heavy-frame
  // prebuild — reports its own phases through the player's bake events, which the
  // panel routes into the same bar; this call is opaque from here.
  onPhase?.('prepare')
  await player.play(animation)
  if (signal?.aborted) {
    player.stop()
    const e = new Error('Aborted'); e.name = 'AbortError'; throw e
  }
  player.pause()
  const totalDur = player.getTotalDuration()
  if (totalDur <= 0) throw new Error('Animation has no duration — check keyframe timings.')

  const canvas = renderer.domElement

  // ── Resize renderer for target resolution ───────────────────────────────────
  const origW    = canvas.width
  const origH    = canvas.height
  const origAspect = camera.aspect

  let targetW = origW, targetH = origH
  if (resolution === '720p')  { targetW = 1280; targetH = 720  }
  if (resolution === '1080p') { targetW = 1920; targetH = 1080 }

  const needsResize = targetW !== origW || targetH !== origH
  onPhase?.('session')
  if (needsResize) {
    renderer.setSize(targetW, targetH, false)
    camera.aspect = targetW / targetH
    camera.updateProjectionMatrix()
  }

  try {
    if (format === 'gif') {
      await _captureGIF({ animation, canvas, renderer, scene, camera, player, fps, totalDur, onProgress, onPhase, signal })
    } else {
      await _captureWebM({ animation, canvas, renderer, scene, camera, player, fps, totalDur, onProgress, onPhase, signal })
    }
  } finally {
    player.stop()
    if (needsResize) {
      renderer.setSize(origW, origH, false)
      camera.aspect = origAspect
      camera.updateProjectionMatrix()
    }
  }
}

// ── Photo-mode video: high-res frames via photoRenderer.renderToBlob ─────────

/**
 * Render an animation as a video using the photo-mode renderer for each
 * frame. Mirrors `exportVideo` but uses `photoRenderer.renderToBlob(w, h)`
 * to produce tiled high-resolution frames (same path as the Export PNG
 * button), then encodes them with MediaRecorder (WebM) or gifenc (GIF).
 *
 * Path-traced quality is intentionally NOT used per-frame — PT can take
 * minutes per still, which is impractical for a video. Rasterised photo
 * mode (SSAO + HDRI + lights + materials) is used.
 *
 * @param {object} opts
 * @param {object}   opts.animation     — DesignAnimation
 * @param {object}   opts.player        — initAnimationPlayer instance
 * @param {object}   opts.photoRenderer — createPhotoRenderer instance
 * @param {number}   opts.width         — output pixel width
 * @param {number}   opts.height        — output pixel height
 * @param {object}   [opts.options]     — { format, fps }
 * @param {function} [opts.onProgress]  — (frac, {frame, frames}) => void
 * @param {AbortSignal} [opts.signal]
 */
export async function exportPhotoVideo({ animation, player, photoRenderer, width, height, options = {}, onProgress, onPhase, signal }) {
  const { format = 'webm', fps: fpsOpt } = options
  const fps = Math.max(1, Math.min(60, fpsOpt ?? animation.fps ?? 30))

  onPhase?.('prepare')
  await player.play(animation)
  if (signal?.aborted) { player.stop(); const e = new Error('Aborted'); e.name = 'AbortError'; throw e }
  player.pause()
  const totalDur = player.getTotalDuration()
  if (totalDur <= 0) throw new Error('Animation has no duration — check keyframe timings.')

  // Open a single export session — ONE offscreen WebGL context shared by
  // every frame. Calling photoRenderer.renderToBlob() per frame instead
  // would create a fresh context each call and the browser blocks new
  // contexts after ~30 ("Web page caused context loss and was blocked").
  if (typeof photoRenderer.beginFrameSession !== 'function') {
    throw new Error('photoRenderer.beginFrameSession() is required for video export.')
  }
  // followMotion: the animation moves clusters and drives binding hinges, which
  // shifts the bounding box while every mesh stays the same — the session's
  // cheap "did the meshes change" fingerprint cannot see that, so the shadow
  // frustum has to be refitted per frame or it stays where the structure was.
  //
  // Not free and not instant: it probes a throwaway WebGL context for
  // maxTextureSize, allocates the tiled offscreen renderer, enables the shadow
  // map, and builds the RenderPass/FigurePass(silhouette)/SMAA/Output chain —
  // all synchronous, and on a large scene with shadows on it is seconds.
  onPhase?.('session')
  const session = photoRenderer.beginFrameSession(width, height, { followMotion: true })

  try {
    // Photo mode owns the lens (and dollied the camera to preserve framing when
    // it was set), so camera poses drive position/target/up only — otherwise the
    // publication lens snaps to whatever FOV the pose was captured at. Inside
    // the try so the session is disposed even if this throws.
    player.setLockFov?.(true)
    if (format === 'gif') {
      await _captureGIFPhoto({ animation, player, session, w: width, h: height, fps, totalDur, onProgress, onPhase, signal })
    } else {
      await _captureWebMPhoto({ animation, player, session, w: width, h: height, fps, totalDur, onProgress, onPhase, signal })
    }
  } finally {
    player.setLockFov?.(false)
    session.dispose()
    player.stop()
  }
}

/**
 * Get one photo-mode frame onto a 2D context we can composite and read.
 *
 * Fast path: `renderFrameToCanvas()` hands back the session's own stitch canvas —
 * the pixels are already there. The Blob path below existed only because that was
 * the session's only public output, and it costs a PNG deflate-encode plus a decode
 * plus a redundant full-frame blit PER FRAME (~0.2–0.5 s at 1080p) to recover bytes
 * we already had. Kept as a fallback so an older session object still works.
 */
async function _frameToCanvas(session, w, h, scratch, ctx) {
  if (typeof session.renderFrameToCanvas === 'function') {
    const src = session.renderFrameToCanvas()
    ctx.clearRect(0, 0, w, h)
    ctx.drawImage(src, 0, 0, w, h)
    return scratch
  }
  const blob = await session.renderFrame()
  // Decode the blob into an ImageBitmap — the fastest path on modern browsers.
  const bmp = await createImageBitmap(blob)
  ctx.clearRect(0, 0, w, h)
  ctx.drawImage(bmp, 0, 0, w, h)
  bmp.close?.()
  return scratch
}

async function _captureWebMPhoto({ animation, player, session, w, h, fps, totalDur, onProgress, onPhase, signal }) {
  const scratch = Object.assign(document.createElement('canvas'), { width: w, height: h })
  const ctx = scratch.getContext('2d', { willReadFrequently: true })
  if (typeof scratch.captureStream !== 'function') {
    throw new Error('canvas.captureStream() not supported in this browser.')
  }
  const stream     = scratch.captureStream(0)
  const videoTrack = stream.getVideoTracks()[0]
  if (!videoTrack) throw new Error('Could not acquire video track from canvas stream.')

  const mimeType = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm', '']
    .find(m => !m || MediaRecorder.isTypeSupported(m))
  const chunks   = []
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
  recorder.ondataavailable = e => { if (e.data?.size > 0) chunks.push(e.data) }
  recorder.start()

  const frameCount = Math.ceil(totalDur * fps)
  let aborted = false
  for (let i = 0; i <= frameCount; i++) {
    if (signal?.aborted) { aborted = true; break }
    const t = Math.min((i / frameCount) * totalDur, totalDur)
    player.seekTo(t)
    // Single shared offscreen renderer (see beginFrameSession).
    await _frameToCanvas(session, w, h, scratch, ctx)
    _drawTextOverlay(ctx, player.getActiveTextOverlay?.(), w, h)
    videoTrack.requestFrame()
    onProgress?.(i / frameCount, { frame: i, frames: frameCount })
    onPhase?.('capture', { done: i, total: frameCount })
    await _yield()
  }

  if (aborted) {
    try { recorder.stop() } catch {}
    const e = new Error('Aborted'); e.name = 'AbortError'; throw e
  }
  // Flushing the recorder is not instant on a long capture — it is the phase the
  // user waits through at "100%" if nobody says otherwise.
  onPhase?.('encode')
  await _yield()
  return new Promise((resolve, reject) => {
    recorder.onstop = () => {
      onPhase?.('save')
      const blob = new Blob(chunks, { type: 'video/webm' })
      _download(blob, `${animation.name || 'animation'}-photo.webm`)
      resolve()
    }
    recorder.onerror = e => reject(e.error ?? new Error('MediaRecorder error'))
    recorder.stop()
  })
}

async function _captureGIFPhoto({ animation, player, session, w, h, fps, totalDur, onProgress, onPhase, signal }) {
  const { GIFEncoder, quantize, applyPalette } = await import('gifenc')
  const scratch = Object.assign(document.createElement('canvas'), { width: w, height: h })
  const ctx = scratch.getContext('2d', { willReadFrequently: true })
  const frameCount = Math.ceil(totalDur * fps)
  const gif = GIFEncoder({ initialCapacity: _gifCapacity(w, h, frameCount) })
  const delay = Math.round(1000 / fps)

  let palette = null
  for (let i = 0; i <= frameCount; i++) {
    if (signal?.aborted) { const e = new Error('Aborted'); e.name = 'AbortError'; throw e }
    const t = Math.min((i / frameCount) * totalDur, totalDur)
    player.seekTo(t)
    await _frameToCanvas(session, w, h, scratch, ctx)
    _drawTextOverlay(ctx, player.getActiveTextOverlay?.(), w, h)
    const { data } = ctx.getImageData(0, 0, w, h)
    if (!palette || i % _PALETTE_EVERY === 0) palette = quantize(data, 256)
    const index = applyPalette(data, palette)
    gif.writeFrame(index, w, h, { palette, delay })
    onProgress?.(i / frameCount, { frame: i, frames: frameCount })
    onPhase?.('capture', { done: i, total: frameCount })
    await _yield()
  }
  // gif.finish() concatenates every encoded frame into one buffer — synchronous,
  // and hundreds of MB on a long high-res GIF. Announce it and yield first, or the
  // popup sits frozen at the last capture tick through the whole concat.
  onPhase?.('encode')
  await _yield()
  gif.finish()
  onPhase?.('save')
  await _yield()
  _download(new Blob([gif.bytesView()], { type: 'image/gif' }), `${animation.name || 'animation'}-photo.gif`)
}

// ── WebM via MediaRecorder + captureStream(0) ─────────────────────────────────

async function _captureWebM({ animation, canvas, renderer, scene, camera, player, fps, totalDur, onProgress, onPhase, signal }) {
  // Route through a 2D scratch canvas so we can composite the text overlay on
  // top of the WebGL frame before capture.
  const w   = canvas.width
  const h   = canvas.height
  const tmp = Object.assign(document.createElement('canvas'), { width: w, height: h })
  const ctx = tmp.getContext('2d', { willReadFrequently: true })

  if (typeof tmp.captureStream !== 'function') {
    throw new Error('canvas.captureStream() not supported in this browser.')
  }
  const stream     = tmp.captureStream(0)
  const videoTrack = stream.getVideoTracks()[0]
  if (!videoTrack) {
    throw new Error('Could not acquire video track from canvas stream.')
  }

  // Prefer VP9, fall back to VP8, then browser default.
  const mimeType = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm', '']
    .find(m => !m || MediaRecorder.isTypeSupported(m))

  const chunks   = []
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
  recorder.ondataavailable = e => { if (e.data?.size > 0) chunks.push(e.data) }
  recorder.start()

  const frameCount = Math.ceil(totalDur * fps)
  let aborted = false
  for (let i = 0; i <= frameCount; i++) {
    if (signal?.aborted) { aborted = true; break }
    const t = Math.min((i / frameCount) * totalDur, totalDur)
    player.seekTo(t)
    renderer.render(scene, camera)
    ctx.clearRect(0, 0, w, h)
    ctx.drawImage(canvas, 0, 0, w, h)
    _drawTextOverlay(ctx, player.getActiveTextOverlay?.(), w, h)
    videoTrack.requestFrame()
    onProgress?.(i / frameCount, { frame: i, frames: frameCount })
    onPhase?.('capture', { done: i, total: frameCount })
    await _yield()
  }

  if (aborted) {
    try { recorder.stop() } catch {}
    const e = new Error('Aborted'); e.name = 'AbortError'; throw e
  }

  onPhase?.('encode')
  await _yield()
  return new Promise((resolve, reject) => {
    recorder.onstop = () => {
      onPhase?.('save')
      const blob = new Blob(chunks, { type: 'video/webm' })
      _download(blob, `${animation.name || 'animation'}.webm`)
      resolve()
    }
    recorder.onerror = e => reject(e.error ?? new Error('MediaRecorder error'))
    recorder.stop()
  })
}

// ── GIF via gifenc ─────────────────────────────────────────────────────────────

async function _captureGIF({ animation, canvas, renderer, scene, camera, player, fps, totalDur, onProgress, onPhase, signal }) {
  const { GIFEncoder, quantize, applyPalette } = await import('gifenc')

  const w   = canvas.width
  const h   = canvas.height
  const tmp = Object.assign(document.createElement('canvas'), { width: w, height: h })
  const ctx = tmp.getContext('2d', { willReadFrequently: true })
  const frameCount = Math.ceil(totalDur * fps)
  const gif = GIFEncoder({ initialCapacity: _gifCapacity(w, h, frameCount) })
  const delay = Math.round(1000 / fps)

  let palette = null
  for (let i = 0; i <= frameCount; i++) {
    if (signal?.aborted) {
      const e = new Error('Aborted'); e.name = 'AbortError'; throw e
    }
    const t = Math.min((i / frameCount) * totalDur, totalDur)
    player.seekTo(t)
    renderer.render(scene, camera)
    ctx.clearRect(0, 0, w, h)
    ctx.drawImage(canvas, 0, 0)
    _drawTextOverlay(ctx, player.getActiveTextOverlay?.(), w, h)
    const { data } = ctx.getImageData(0, 0, w, h)
    if (!palette || i % _PALETTE_EVERY === 0) palette = quantize(data, 256)
    const index = applyPalette(data, palette)
    gif.writeFrame(index, w, h, { palette, delay })
    onProgress?.(i / frameCount, { frame: i, frames: frameCount })
    onPhase?.('capture', { done: i, total: frameCount })
    await _yield()
  }

  onPhase?.('encode')
  await _yield()
  gif.finish()
  onPhase?.('save')
  await _yield()
  _download(new Blob([gif.bytesView()], { type: 'image/gif' }), `${animation.name || 'animation'}.gif`)
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Composite the active animation text overlay onto a 2D context.
 * Mirrors the live DOM overlay: bottom-anchored, ~40px from the bottom,
 * trapezoidal fade via `state.opacity`, with a soft drop shadow.
 */
function _drawTextOverlay(ctx, state, w, h) {
  if (!state || !state.text || !state.opacity) return
  const sizePx = state.fontSizePx ?? 24
  const margin = 32
  const bottomGap = 40
  const weight = state.bold   ? 'bold '  : ''
  const style  = state.italic ? 'italic ' : ''
  const family = state.fontFamily ?? 'sans-serif'
  ctx.save()
  ctx.globalAlpha = Math.max(0, Math.min(1, state.opacity))
  ctx.font = `${style}${weight}${sizePx}px ${family}`
  ctx.fillStyle = state.color ?? '#ffffff'
  ctx.shadowColor = 'rgba(0,0,0,0.7)'
  ctx.shadowBlur = 4
  ctx.shadowOffsetY = 1
  ctx.textBaseline = 'bottom'

  // Word-wrap to fit within (w - 2*margin).
  const maxWidth = Math.max(1, w - 2 * margin)
  const lineHeight = Math.round(sizePx * 1.2)
  const lines = _wrapLines(ctx, state.text, maxWidth)

  ctx.textAlign = state.align ?? 'center'
  const x = state.align === 'left'
    ? margin
    : state.align === 'right'
      ? w - margin
      : w / 2

  // Anchor the bottom-most line `bottomGap` above the bottom edge, draw upward.
  let y = h - bottomGap
  for (let i = lines.length - 1; i >= 0; i--) {
    ctx.fillText(lines[i], x, y)
    y -= lineHeight
  }
  ctx.restore()
}

function _wrapLines(ctx, text, maxWidth) {
  const out = []
  for (const para of String(text).split(/\r?\n/)) {
    if (!para) { out.push(''); continue }
    const words = para.split(/\s+/)
    let line = ''
    for (const word of words) {
      const probe = line ? line + ' ' + word : word
      if (ctx.measureText(probe).width <= maxWidth) {
        line = probe
      } else {
        if (line) out.push(line)
        line = word
      }
    }
    if (line) out.push(line)
  }
  return out
}

/**
 * Yield to the browser event loop so UI can update (progress bar, etc.).
 *
 * NOT `setTimeout(0)`. Nested timers are clamped to 4 ms once the nesting level
 * passes 5, and — the part that matters — a BACKGROUNDED tab throttles them to
 * ≥1 s, then to once per minute after five minutes hidden. An export the user
 * starts and then switches away from would spend a full second per frame inside
 * the yield alone; on a 300-frame export that is five hours of pure waiting.
 * A MessageChannel posts a task rather than arming a timer, so it is not subject
 * to either clamp while still giving the renderer a chance to paint.
 */
const _yieldChan = typeof MessageChannel === 'function' ? new MessageChannel() : null
const _yieldQueue = []
if (_yieldChan) {
  _yieldChan.port1.onmessage = () => { _yieldQueue.shift()?.() }
  _yieldChan.port1.start?.()
}
function _yield() {
  if (!_yieldChan) return new Promise(r => setTimeout(r, 0))
  return new Promise((r) => { _yieldQueue.push(r); _yieldChan.port2.postMessage(0) })
}

/**
 * Initial byte capacity for the GIF stream.
 *
 * gifenc grows its buffer by only 1.125× past 1 MB, so a several-hundred-MB GIF
 * reallocates dozens of times, each copying the whole buffer. Sizing up front
 * turns gigabytes of memcpy into one allocation. Indexed pixels are 1 byte each;
 * LZW usually lands well under that, so this is a generous but bounded guess.
 */
function _gifCapacity(w, h, frames) {
  const est = w * h * (frames + 1) * 0.35
  return Math.max(1 << 20, Math.min(est, 512 << 20)) | 0
}

/**
 * Re-quantize the palette every N frames instead of every frame.
 *
 * `quantize()` is the dominant CPU cost of a GIF export — a histogram plus
 * pairwise-nearest-neighbour clustering over every pixel, so ~2.1 M pixels per
 * call at 1080p. `applyPalette` still runs per frame (it must), but the palette
 * itself changes slowly: a camera move or a trajectory step does not repaint the
 * scene in new hues 30 times a second. 12 frames is 0.4 s at 30 fps.
 *
 * Each frame still writes its own explicit colour table, so this only trades a
 * little colour accuracy on the frames between samples — never correctness.
 */
const _PALETTE_EVERY = 12

function _download(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a   = Object.assign(document.createElement('a'), { href: url, download: filename })
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
