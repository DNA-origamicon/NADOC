/**
 * exportPhotoVideo — driving the animation player frame-by-frame through a
 * photo-mode frame session.
 *
 * The encode branches themselves (MediaRecorder / gifenc) are browser
 * machinery; what is worth pinning is the CONTRACT around them: how many frames
 * at which times, the play/pause/stop lifecycle, the FOV lock, abort, and that
 * the GL session is always disposed.
 *
 * The GIF branch is used throughout because it needs no MediaRecorder — it is
 * the same frame loop as WebM.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

// gifenc is a real dependency but does real quantization; stub it so the tests
// pin the loop rather than the encoder.
const writeFrame  = vi.fn()
const quantizeSpy = vi.fn(() => [[0, 0, 0]])
const encoderOpts = []
vi.mock('gifenc', () => ({
  GIFEncoder: (opts) => {
    encoderOpts.push(opts)
    return { writeFrame, finish: vi.fn(), bytesView: () => new Uint8Array([1, 2, 3]) }
  },
  quantize: (...a) => quantizeSpy(...a),
  applyPalette: () => new Uint8Array(4),
}))

const { exportPhotoVideo, exportVideo } = await import('./export_video.js')

// ── Fakes ────────────────────────────────────────────────────────────────────

function makePlayer(totalDur = 2) {
  return {
    seeks: [],
    fovLock: [],
    play: vi.fn(async () => {}),
    pause: vi.fn(),
    stop: vi.fn(),
    getTotalDuration: () => totalDur,
    seekTo(t) { this.seeks.push(t) },
    setLockFov(on) { this.fovLock.push(on) },
    getActiveTextOverlay: () => null,
  }
}

/**
 * @param {{canvasPath?: boolean}} [o] — `canvasPath` gives the session the direct
 *   `renderFrameToCanvas()` output the real photo-mode session has. Defaults ON so the
 *   suite exercises the path production uses; pass false for the legacy Blob fallback.
 */
function makePhotoRenderer({ canvasPath = true } = {}) {
  const session = {
    renderFrame: vi.fn(async () => new Blob(['x'], { type: 'image/png' })),
    dispose: vi.fn(),
  }
  if (canvasPath) {
    const c = Object.assign(document.createElement('canvas'), { width: 640, height: 480 })
    session.renderFrameToCanvas = vi.fn(() => c)
  }
  return {
    session,
    opts: null,
    beginFrameSession(w, h, opts) { this.opts = { w, h, ...opts }; return session },
  }
}

beforeEach(() => {
  writeFrame.mockClear()
  quantizeSpy.mockClear()
  encoderOpts.length = 0
  // jsdom has no canvas 2D context and no createImageBitmap.
  HTMLCanvasElement.prototype.getContext = () => ({
    drawImage: vi.fn(), clearRect: vi.fn(), save: vi.fn(), restore: vi.fn(),
    fillText: vi.fn(), measureText: () => ({ width: 10 }),
    getImageData: () => ({ data: new Uint8ClampedArray(4) }),
  })
  globalThis.createImageBitmap = async () => ({ close: vi.fn() })
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:x')
  globalThis.URL.revokeObjectURL = vi.fn()
})

const run = (over = {}) => exportPhotoVideo({
  animation: { id: 'a1', name: 'clip', keyframes: [{}] },
  player: over.player ?? makePlayer(),
  photoRenderer: over.photoRenderer ?? makePhotoRenderer(),
  width: 640, height: 480,
  options: { format: 'gif', fps: 10, ...(over.options ?? {}) },
  ...over.rest,
})

describe('exportPhotoVideo', () => {
  it('renders ceil(duration × fps) + 1 frames, spanning the whole timeline', async () => {
    const player = makePlayer(2)          // 2 s at 10 fps
    await run({ player })

    expect(player.seeks).toHaveLength(21)   // both endpoints included
    expect(player.seeks[0]).toBe(0)
    expect(player.seeks.at(-1)).toBe(2)
    // Evenly spaced, and never past the end.
    expect(player.seeks[10]).toBeCloseTo(1.0, 9)
    expect(Math.max(...player.seeks)).toBeLessThanOrEqual(2)
    expect(writeFrame).toHaveBeenCalledTimes(21)
  })

  it('follows the animation: play → pause → seek → stop', async () => {
    const player = makePlayer()
    await run({ player })
    // play() is what builds the schedule and bakes geometry; seekTo is a no-op
    // before it. pause() kills the rAF so stepping is ours alone.
    expect(player.play).toHaveBeenCalledTimes(1)
    expect(player.pause).toHaveBeenCalledTimes(1)
    expect(player.stop).toHaveBeenCalledTimes(1)
  })

  it('opens the session with followMotion — the structure moves as it plays', async () => {
    const photoRenderer = makePhotoRenderer()
    await run({ photoRenderer })
    expect(photoRenderer.opts).toEqual({ w: 640, h: 480, followMotion: true })
  })

  it('locks the lens for the whole export and releases it after', async () => {
    const player = makePlayer()
    await run({ player })
    // Photo mode owns the FOV (and dollied for it); a camera pose captured at
    // the editor's 55° must not yank the publication lens back.
    expect(player.fovLock).toEqual([true, false])
  })

  it('disposes the GL session even when the export throws', async () => {
    const photoRenderer = makePhotoRenderer()
    // Stub BOTH outputs: the loop prefers the direct-canvas path and only falls
    // back to the Blob one on an older session object.
    photoRenderer.session.renderFrameToCanvas = vi.fn(() => { throw new Error('GL died') })
    photoRenderer.session.renderFrame = vi.fn(async () => { throw new Error('GL died') })
    const player = makePlayer()

    await expect(run({ photoRenderer, player })).rejects.toThrow('GL died')
    expect(photoRenderer.session.dispose).toHaveBeenCalledTimes(1)
    expect(player.fovLock).toEqual([true, false])   // and unlocks the lens
    expect(player.stop).toHaveBeenCalled()
  })

  it('aborts mid-loop without finishing the file', async () => {
    const ctl = new AbortController()
    const photoRenderer = makePhotoRenderer()
    let n = 0
    const realCanvas = photoRenderer.session.renderFrameToCanvas
    photoRenderer.session.renderFrameToCanvas = vi.fn(() => {
      if (++n === 3) ctl.abort()
      return realCanvas()
    })

    await expect(run({ photoRenderer, rest: { signal: ctl.signal } }))
      .rejects.toMatchObject({ name: 'AbortError' })
    expect(writeFrame.mock.calls.length).toBeLessThan(21)
    expect(photoRenderer.session.dispose).toHaveBeenCalledTimes(1)
  })

  it('aborts before any rendering when the signal is already tripped', async () => {
    const photoRenderer = makePhotoRenderer()
    await expect(run({ photoRenderer, rest: { signal: AbortSignal.abort() } }))
      .rejects.toMatchObject({ name: 'AbortError' })
    expect(photoRenderer.session.renderFrameToCanvas).not.toHaveBeenCalled()
    expect(photoRenderer.session.renderFrame).not.toHaveBeenCalled()
  })

  it('reports progress as a fraction plus frame counts', async () => {
    const seen = []
    await run({ rest: { onProgress: (p, info) => seen.push([p, info.frame, info.frames]) } })
    expect(seen[0]).toEqual([0, 0, 20])
    expect(seen.at(-1)).toEqual([1, 20, 20])
  })

  it('refuses a photo renderer with no frame session', async () => {
    await expect(run({ photoRenderer: {} }))
      .rejects.toThrow(/beginFrameSession/)
  })

  it('refuses an animation with no duration', async () => {
    await expect(run({ player: makePlayer(0) }))
      .rejects.toThrow(/no duration/)
  })

  it('clamps fps to 1–60', async () => {
    const fast = makePlayer(1)
    await run({ player: fast, options: { format: 'gif', fps: 999 } })
    expect(fast.seeks).toHaveLength(61)     // 60 fps, not 999
  })
})

// ── Phase reporting ──────────────────────────────────────────────────────────

/**
 * Both exporters feed `scene/export_progress.js`. What has to hold is that every
 * step which can take real time announces itself — before this, `beginFrameSession`
 * (probe GL + shadow map + silhouette pass chain) and the whole `gif.finish()` +
 * Blob + download tail ran silently, the latter *after* the last progress event,
 * so a big GIF sat at "100%" for a long time with the user assuming a hang.
 */
describe('phase reporting', () => {
  const phasesOf = (calls) => calls.map(c => c[0])

  it('exportPhotoVideo announces session, capture, encode and save, in order', async () => {
    const calls = []
    await run({ rest: { onPhase: (k, info) => calls.push([k, info]) } })
    const keys = phasesOf(calls)
    expect(keys[0]).toBe('prepare')
    expect(keys.indexOf('session')).toBeGreaterThan(keys.indexOf('prepare'))
    expect(keys.indexOf('capture')).toBeGreaterThan(keys.indexOf('session'))
    expect(keys.indexOf('encode')).toBeGreaterThan(keys.lastIndexOf('capture'))
    expect(keys.indexOf('save')).toBeGreaterThan(keys.indexOf('encode'))
  })

  it('announces the render session BEFORE building it, not after', async () => {
    // The whole point: the pass chain is what makes silhouettes+shadows slow to
    // set up, so the label has to be on screen while it happens.
    const order = []
    const photoRenderer = makePhotoRenderer()
    const inner = photoRenderer.beginFrameSession.bind(photoRenderer)
    photoRenderer.beginFrameSession = (...a) => { order.push('beginFrameSession'); return inner(...a) }
    await run({ photoRenderer, rest: { onPhase: (k) => order.push(`phase:${k}`) } })
    expect(order.indexOf('phase:session')).toBeLessThan(order.indexOf('beginFrameSession'))
  })

  it('carries per-frame counts through the capture phase', async () => {
    const calls = []
    await run({ player: makePlayer(2), rest: { onPhase: (k, info) => calls.push([k, info]) } })
    const cap = calls.filter(c => c[0] === 'capture')
    expect(cap).toHaveLength(21)                       // 2 s × 10 fps + 1
    expect(cap[0][1]).toEqual({ done: 0, total: 20 })
    expect(cap.at(-1)[1]).toEqual({ done: 20, total: 20 })
  })

  it('reports encode and save AFTER the last capture tick, so 100% is not the end', async () => {
    const calls = []
    await run({ rest: { onPhase: (k) => calls.push(k) } })
    const lastCapture = calls.lastIndexOf('capture')
    expect(calls.slice(lastCapture + 1)).toEqual(['encode', 'save'])
  })

  it('exportVideo (the raw-canvas twin used by the Animations tab) reports the same phases', async () => {
    const calls = []
    const player = makePlayer(2)
    await exportVideo({
      animation: { id: 'a1', name: 'clip', keyframes: [{}] },
      renderer: { domElement: Object.assign(document.createElement('canvas'), { width: 320, height: 240 }), setSize: vi.fn(), render: vi.fn() },
      scene: {}, camera: { aspect: 4 / 3, updateProjectionMatrix: vi.fn() },
      player,
      options: { format: 'gif', fps: 10 },
      onPhase: (k) => calls.push(k),
    })
    expect(calls[0]).toBe('prepare')
    expect(new Set(calls)).toEqual(new Set(['prepare', 'session', 'capture', 'encode', 'save']))
    expect(calls.lastIndexOf('capture')).toBeLessThan(calls.indexOf('encode'))
    expect(player.stop).toHaveBeenCalled()
  })

  it('emits no phase after an abort — a cancelled run must not report "save"', async () => {
    const calls = []
    const ctl = new AbortController()
    const player = makePlayer(2)
    const orig = player.seekTo.bind(player)
    player.seekTo = (t) => { orig(t); if (player.seeks.length === 5) ctl.abort() }
    await expect(run({ player, rest: { signal: ctl.signal, onPhase: (k) => calls.push(k) } }))
      .rejects.toMatchObject({ name: 'AbortError' })
    expect(calls).not.toContain('encode')
    expect(calls).not.toContain('save')
  })

  it('works with no onPhase supplied at all (the callback is optional)', async () => {
    await expect(run({})).resolves.toBeUndefined()
  })
})

// ── Efficiency ───────────────────────────────────────────────────────────────

/**
 * These pin work the export must NOT do. Each was measured or read out of the
 * library source in the 2026-08-03 audit; the risk is that a later refactor
 * quietly reinstates the cost, which is invisible except as "the export got slow
 * again" on a workflow nobody runs casually.
 */
describe('efficiency', () => {
  it('reads frames straight off the session canvas — no PNG encode/decode per frame', async () => {
    const photoRenderer = makePhotoRenderer()
    await run({ photoRenderer, player: makePlayer(2) })
    expect(photoRenderer.session.renderFrameToCanvas).toHaveBeenCalledTimes(21)
    // The Blob round trip (toBlob → createImageBitmap → blit) is the thing removed.
    expect(photoRenderer.session.renderFrame).not.toHaveBeenCalled()
  })

  it('still works against a session that only offers the Blob output', async () => {
    const photoRenderer = makePhotoRenderer({ canvasPath: false })
    await run({ photoRenderer, player: makePlayer(2) })
    expect(photoRenderer.session.renderFrame).toHaveBeenCalledTimes(21)
    expect(writeFrame).toHaveBeenCalledTimes(21)
  })

  it('re-quantizes the GIF palette periodically, not once per frame', async () => {
    // quantize() is a full histogram + PNN clustering pass over every pixel — the
    // dominant CPU cost of a GIF export. applyPalette still runs per frame.
    await run({ player: makePlayer(6) })          // 6 s × 10 fps → 61 frames
    expect(writeFrame).toHaveBeenCalledTimes(61)
    expect(quantizeSpy.mock.calls.length).toBeLessThan(61)
    expect(quantizeSpy.mock.calls.length).toBeGreaterThan(0)
  })

  it('every written frame still carries an explicit palette', async () => {
    // Reusing a palette must not degrade into writing frames with no colour table.
    await run({ player: makePlayer(3) })
    for (const call of writeFrame.mock.calls) {
      expect(call[3]?.palette, 'writeFrame opts.palette').toBeTruthy()
    }
  })

  it('pre-sizes the GIF buffer instead of letting it grow 1.125x at a time', async () => {
    await run({ player: makePlayer(2) })
    const cap = encoderOpts.at(-1)?.initialCapacity
    expect(cap).toBeGreaterThanOrEqual(1 << 20)
    expect(cap).toBeLessThanOrEqual(512 << 20)
  })

  it('yields without arming a timer, so a backgrounded tab is not throttled', async () => {
    // setTimeout(0) is clamped to >=1 s in a hidden tab and to once per MINUTE after
    // five minutes hidden — 300 frames of that is hours spent purely in the yield.
    const spy = vi.spyOn(globalThis, 'setTimeout')
    const before = spy.mock.calls.length
    await run({ player: makePlayer(2) })      // 21 frames, so 21 yields
    // Not "zero" — the download path schedules one. The property that matters is
    // that the yield itself is not a timer, i.e. this does not scale with frames.
    expect(spy.mock.calls.length - before).toBeLessThan(5)
    spy.mockRestore()
  })
})
