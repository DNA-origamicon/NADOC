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
 */
export async function exportVideo({ animation, renderer, scene, camera, player, options = {}, onProgress, signal }) {
  const { format = 'webm', fps: fpsOpt, resolution = 'current' } = options
  const fps = Math.max(1, Math.min(60, fpsOpt ?? animation.fps ?? 30))

  // Ensure schedule is built without visible playback.
  // play() is async (bakes geometry); await it so _totalDur is set before we read it.
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
  if (needsResize) {
    renderer.setSize(targetW, targetH, false)
    camera.aspect = targetW / targetH
    camera.updateProjectionMatrix()
  }

  try {
    if (format === 'gif') {
      await _captureGIF({ animation, canvas, renderer, scene, camera, player, fps, totalDur, onProgress, signal })
    } else {
      await _captureWebM({ animation, canvas, renderer, scene, camera, player, fps, totalDur, onProgress, signal })
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
export async function exportPhotoVideo({ animation, player, photoRenderer, width, height, options = {}, onProgress, signal }) {
  const { format = 'webm', fps: fpsOpt } = options
  const fps = Math.max(1, Math.min(60, fpsOpt ?? animation.fps ?? 30))

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
  const session = photoRenderer.beginFrameSession(width, height)

  try {
    if (format === 'gif') {
      await _captureGIFPhoto({ animation, player, session, w: width, h: height, fps, totalDur, onProgress, signal })
    } else {
      await _captureWebMPhoto({ animation, player, session, w: width, h: height, fps, totalDur, onProgress, signal })
    }
  } finally {
    session.dispose()
    player.stop()
  }
}

async function _blobToCanvas(blob, w, h, scratch, ctx) {
  // Reuse scratch canvas across frames; decode the blob into an ImageBitmap
  // which is the fastest path on modern browsers.
  const bmp = await createImageBitmap(blob)
  ctx.clearRect(0, 0, w, h)
  ctx.drawImage(bmp, 0, 0, w, h)
  bmp.close?.()
  return scratch
}

async function _captureWebMPhoto({ animation, player, session, w, h, fps, totalDur, onProgress, signal }) {
  const scratch = Object.assign(document.createElement('canvas'), { width: w, height: h })
  const ctx = scratch.getContext('2d')
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
    const blob = await session.renderFrame()
    await _blobToCanvas(blob, w, h, scratch, ctx)
    _drawTextOverlay(ctx, player.getActiveTextOverlay?.(), w, h)
    videoTrack.requestFrame()
    onProgress?.(i / frameCount, { frame: i, frames: frameCount })
    await _yield()
  }

  if (aborted) {
    try { recorder.stop() } catch {}
    const e = new Error('Aborted'); e.name = 'AbortError'; throw e
  }
  return new Promise((resolve, reject) => {
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: 'video/webm' })
      _download(blob, `${animation.name || 'animation'}-photo.webm`)
      resolve()
    }
    recorder.onerror = e => reject(e.error ?? new Error('MediaRecorder error'))
    recorder.stop()
  })
}

async function _captureGIFPhoto({ animation, player, session, w, h, fps, totalDur, onProgress, signal }) {
  const { GIFEncoder, quantize, applyPalette } = await import('gifenc')
  const scratch = Object.assign(document.createElement('canvas'), { width: w, height: h })
  const ctx = scratch.getContext('2d')
  const gif = GIFEncoder()
  const delay = Math.round(1000 / fps)

  const frameCount = Math.ceil(totalDur * fps)
  for (let i = 0; i <= frameCount; i++) {
    if (signal?.aborted) { const e = new Error('Aborted'); e.name = 'AbortError'; throw e }
    const t = Math.min((i / frameCount) * totalDur, totalDur)
    player.seekTo(t)
    const blob = await session.renderFrame()
    await _blobToCanvas(blob, w, h, scratch, ctx)
    _drawTextOverlay(ctx, player.getActiveTextOverlay?.(), w, h)
    const { data } = ctx.getImageData(0, 0, w, h)
    const palette  = quantize(data, 256)
    const index    = applyPalette(data, palette)
    gif.writeFrame(index, w, h, { palette, delay })
    onProgress?.(i / frameCount, { frame: i, frames: frameCount })
    await _yield()
  }
  gif.finish()
  _download(new Blob([gif.bytesView()], { type: 'image/gif' }), `${animation.name || 'animation'}-photo.gif`)
}

// ── WebM via MediaRecorder + captureStream(0) ─────────────────────────────────

async function _captureWebM({ animation, canvas, renderer, scene, camera, player, fps, totalDur, onProgress, signal }) {
  // Route through a 2D scratch canvas so we can composite the text overlay on
  // top of the WebGL frame before capture.
  const w   = canvas.width
  const h   = canvas.height
  const tmp = Object.assign(document.createElement('canvas'), { width: w, height: h })
  const ctx = tmp.getContext('2d')

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
    await _yield()
  }

  if (aborted) {
    try { recorder.stop() } catch {}
    const e = new Error('Aborted'); e.name = 'AbortError'; throw e
  }

  return new Promise((resolve, reject) => {
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: 'video/webm' })
      _download(blob, `${animation.name || 'animation'}.webm`)
      resolve()
    }
    recorder.onerror = e => reject(e.error ?? new Error('MediaRecorder error'))
    recorder.stop()
  })
}

// ── GIF via gifenc ─────────────────────────────────────────────────────────────

async function _captureGIF({ animation, canvas, renderer, scene, camera, player, fps, totalDur, onProgress, signal }) {
  const { GIFEncoder, quantize, applyPalette } = await import('gifenc')

  const w   = canvas.width
  const h   = canvas.height
  const tmp = Object.assign(document.createElement('canvas'), { width: w, height: h })
  const ctx = tmp.getContext('2d')
  const gif = GIFEncoder()
  const delay = Math.round(1000 / fps)

  const frameCount = Math.ceil(totalDur * fps)
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
    const palette  = quantize(data, 256)
    const index    = applyPalette(data, palette)
    gif.writeFrame(index, w, h, { palette, delay })
    onProgress?.(i / frameCount, { frame: i, frames: frameCount })
    await _yield()
  }

  gif.finish()
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

/** Yield to the browser event loop so UI can update (progress bar, etc.). */
function _yield() { return new Promise(r => setTimeout(r, 0)) }

function _download(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a   = Object.assign(document.createElement('a'), { href: url, download: filename })
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
