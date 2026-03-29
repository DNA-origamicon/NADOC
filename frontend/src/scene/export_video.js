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
export async function exportVideo({ animation, renderer, scene, camera, player, options = {}, onProgress }) {
  const { format = 'webm', fps: fpsOpt, resolution = 'current' } = options
  const fps = Math.max(1, Math.min(60, fpsOpt ?? animation.fps ?? 30))

  // Ensure schedule is built without visible playback.
  player.play(animation)
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
      await _captureGIF({ animation, canvas, renderer, scene, camera, player, fps, totalDur, onProgress })
    } else {
      await _captureWebM({ animation, canvas, renderer, scene, camera, player, fps, totalDur, onProgress })
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

// ── WebM via MediaRecorder + captureStream(0) ─────────────────────────────────

async function _captureWebM({ animation, canvas, renderer, scene, camera, player, fps, totalDur, onProgress }) {
  if (typeof canvas.captureStream !== 'function') {
    throw new Error('canvas.captureStream() not supported in this browser.')
  }
  const stream     = canvas.captureStream(0)
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
  for (let i = 0; i <= frameCount; i++) {
    const t = Math.min((i / frameCount) * totalDur, totalDur)
    player.seekTo(t)
    renderer.render(scene, camera)
    videoTrack.requestFrame()
    onProgress?.(i / frameCount)
    await _yield()
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

async function _captureGIF({ animation, canvas, renderer, scene, camera, player, fps, totalDur, onProgress }) {
  const { GIFEncoder, quantize, applyPalette } = await import('gifenc')

  const w   = canvas.width
  const h   = canvas.height
  const tmp = Object.assign(document.createElement('canvas'), { width: w, height: h })
  const ctx = tmp.getContext('2d')
  const gif = GIFEncoder()
  const delay = Math.round(1000 / fps)

  const frameCount = Math.ceil(totalDur * fps)
  for (let i = 0; i <= frameCount; i++) {
    const t = Math.min((i / frameCount) * totalDur, totalDur)
    player.seekTo(t)
    renderer.render(scene, camera)
    ctx.drawImage(canvas, 0, 0)
    const { data } = ctx.getImageData(0, 0, w, h)
    const palette  = quantize(data, 256)
    const index    = applyPalette(data, palette)
    gif.writeFrame(index, w, h, { palette, delay })
    onProgress?.(i / frameCount)
    await _yield()
  }

  gif.finish()
  _download(new Blob([gif.bytesView()], { type: 'image/gif' }), `${animation.name || 'animation'}.gif`)
}

// ── Helpers ───────────────────────────────────────────────────────────────────

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
