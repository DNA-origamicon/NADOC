/**
 * Primitive preview capture — render a design through its saved camera poses and
 * encode a small looping GIF (+ a static first-frame poster) for the "Add
 * Primitive" panel's hover preview.
 *
 * Used ONLY by the offline `build-primitives` pipeline (via a dev-only
 * `__nadocTest` hook), never in the shipped UI. It renders explicitly and grabs
 * the pixels in the same synchronous tick — the proven `export_video.js` pattern
 * — so it needs no `preserveDrawingBuffer` on the live renderer.
 *
 * `buildCameraPath` is a pure function (arrays + easing, no THREE/DOM) and is the
 * unit-tested core; `capturePosesGif` is the thin stateful shell that drives the
 * real renderer.
 */

function _lerp(a, b, t) { return a + (b - a) * t }
function _lerpArr(a, b, t) { return a.map((v, i) => _lerp(v, b[i] ?? v, t)) }

// Ease-in-out, matching scene.js animateCameraTo so capture motion looks like a
// hand-applied pose tween (slow at each pose, smooth in between).
function _ease(t) { return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t }

function _normalize(pose) {
  return {
    position: pose.position,
    target: pose.target,
    up: pose.up ?? [0, 1, 0],
    fov: pose.fov ?? null,
  }
}

/**
 * Expand a list of saved camera poses into a dense, eased sequence of camera
 * states that loops seamlessly.
 *
 *  - 0 poses → [] (caller falls back to a static thumbnail)
 *  - 1 pose  → that single static state
 *  - N poses → ping-pong there-and-back ending at the start (p0→…→pN-1→…→p0),
 *    so the GIF wraps with no visible jump. `pingPong:false` makes a one-way
 *    cycle (p0→…→pN-1→p0) instead.
 *
 * @param {Array<{position:number[],target:number[],up?:number[],fov?:number}>} poses
 * @param {{stepsPerSegment?:number, pingPong?:boolean}} [opts]
 * @returns {Array<{position:number[],target:number[],up:number[],fov:number|null}>}
 */
export function buildCameraPath(poses, { stepsPerSegment = 18, pingPong = true } = {}) {
  if (!poses || poses.length === 0) return []
  const norm = poses.map(_normalize)
  if (norm.length === 1) return [norm[0]]

  // Key poses to interpolate through (a closed loop back to the start).
  const keys = pingPong
    ? [...norm, ...norm.slice(0, -1).reverse()]   // p0..pN-1, pN-2..p0
    : [...norm, norm[0]]                          // p0..pN-1, p0

  const frames = []
  for (let k = 0; k < keys.length - 1; k++) {
    const a = keys[k]
    const b = keys[k + 1]
    // Emit [0, stepsPerSegment) — the endpoint is the next segment's start (or,
    // for the final segment, the loop wrap back to frame 0), so no duplicates.
    for (let s = 0; s < stepsPerSegment; s++) {
      const t = _ease(s / stepsPerSegment)
      frames.push({
        position: _lerpArr(a.position, b.position, t),
        target: _lerpArr(a.target, b.target, t),
        up: _lerpArr(a.up, b.up, t),
        fov: a.fov == null || b.fov == null ? (a.fov ?? b.fov) : _lerp(a.fov, b.fov, t),
      })
    }
  }
  return frames
}

function _applyCameraState(camera, controls, s) {
  camera.position.set(s.position[0], s.position[1], s.position[2])
  controls.target.set(s.target[0], s.target[1], s.target[2])
  if (s.up) camera.up.set(s.up[0], s.up[1], s.up[2]).normalize()
  if (s.fov != null && s.fov !== camera.fov) {
    camera.fov = s.fov
    camera.updateProjectionMatrix()
  }
  controls.update()
}

// Chunked base64 of a byte array — `btoa(String.fromCharCode(...big))` overflows
// the call stack, so build the binary string in slices.
function _bytesToBase64(bytes) {
  let bin = ''
  const CHUNK = 0x8000
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK))
  }
  return btoa(bin)
}

/**
 * Render `poses` (or the supplied path) and encode a looping GIF + poster.
 * Returns plain strings so the result crosses the Playwright page.evaluate
 * boundary intact.
 *
 * @returns {Promise<null | {gifBase64:string, posterDataUrl:string, frames:number, width:number, height:number}>}
 */
export async function capturePosesGif({
  renderer, scene, camera, controls, poses,
  maxWidth = 360, fps = 20, stepsPerSegment = 18, pingPong = true, onFrame,
} = {}) {
  const path = buildCameraPath(poses, { stepsPerSegment, pingPong })
  if (path.length === 0) return null

  const { GIFEncoder, quantize, applyPalette } = await import('gifenc')
  const canvas = renderer.domElement
  const scale = Math.min(1, maxWidth / canvas.width)
  const w = Math.max(1, Math.round(canvas.width * scale))
  const h = Math.max(1, Math.round(canvas.height * scale))

  const tmp = Object.assign(document.createElement('canvas'), { width: w, height: h })
  const ctx = tmp.getContext('2d', { willReadFrequently: true })
  const gif = GIFEncoder()
  const delay = Math.round(1000 / fps)
  let posterDataUrl = null

  for (let i = 0; i < path.length; i++) {
    _applyCameraState(camera, controls, path[i])
    renderer.render(scene, camera)
    ctx.clearRect(0, 0, w, h)
    ctx.drawImage(canvas, 0, 0, w, h)
    const { data } = ctx.getImageData(0, 0, w, h)
    const palette = quantize(data, 256)
    const index = applyPalette(data, palette)
    gif.writeFrame(index, w, h, { palette, delay })
    if (i === 0) posterDataUrl = tmp.toDataURL('image/png')
    onFrame?.(i, path.length)
    await new Promise((r) => requestAnimationFrame(r))
  }
  gif.finish()

  return {
    gifBase64: _bytesToBase64(gif.bytesView()),
    posterDataUrl,
    frames: path.length,
    width: w,
    height: h,
  }
}
