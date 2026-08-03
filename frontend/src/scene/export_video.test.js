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
const writeFrame = vi.fn()
vi.mock('gifenc', () => ({
  GIFEncoder: () => ({ writeFrame, finish: vi.fn(), bytesView: () => new Uint8Array([1, 2, 3]) }),
  quantize: () => [[0, 0, 0]],
  applyPalette: () => new Uint8Array(4),
}))

const { exportPhotoVideo } = await import('./export_video.js')

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

function makePhotoRenderer() {
  const session = {
    renderFrame: vi.fn(async () => new Blob(['x'], { type: 'image/png' })),
    dispose: vi.fn(),
  }
  return {
    session,
    opts: null,
    beginFrameSession(w, h, opts) { this.opts = { w, h, ...opts }; return session },
  }
}

beforeEach(() => {
  writeFrame.mockClear()
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
    photoRenderer.session.renderFrame = vi.fn(async () => {
      if (++n === 3) ctl.abort()
      return new Blob(['x'], { type: 'image/png' })
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
