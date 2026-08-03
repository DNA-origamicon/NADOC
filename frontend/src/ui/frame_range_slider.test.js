import { describe, it, expect, vi } from 'vitest'
import {
  frameAtOffset, pctForFrame, pickHandle, applyDrag, initFrameRangeSlider,
} from './frame_range_slider.js'

describe('frameAtOffset', () => {
  it('maps the two ends of the track onto frame 0 and n-1', () => {
    expect(frameAtOffset(0, 200, 101)).toBe(0)
    expect(frameAtOffset(200, 200, 101)).toBe(100)
  })

  it('rounds to the nearest frame at the midpoint', () => {
    expect(frameAtOffset(100, 200, 101)).toBe(50)
  })

  it('clamps a press dragged off either edge of the track', () => {
    expect(frameAtOffset(-40, 200, 101)).toBe(0)
    expect(frameAtOffset(999, 200, 101)).toBe(100)
  })

  it('is 0 for a degenerate track or a single-frame trajectory', () => {
    expect(frameAtOffset(50, 0, 101)).toBe(0)
    expect(frameAtOffset(50, 200, 1)).toBe(0)
  })

  it('resolves individual frames of a full-scope trajectory', () => {
    // 12 000 frames over 200 px is 60 frames/px — the case the old 200-frame
    // sparse view never produced.
    expect(frameAtOffset(100, 200, 12000)).toBe(6000)
    expect(frameAtOffset(199, 200, 12000)).toBe(11939)
  })
})

describe('pctForFrame', () => {
  it('spans 0..100 across the trajectory', () => {
    expect(pctForFrame(0, 101)).toBe(0)
    expect(pctForFrame(50, 101)).toBe(50)
    expect(pctForFrame(100, 101)).toBe(100)
  })

  it('pins a single-frame (or empty) trajectory to 0 instead of dividing by zero', () => {
    expect(pctForFrame(0, 1)).toBe(0)
    expect(pctForFrame(3, 0)).toBe(0)
  })

  it('clamps an out-of-span index', () => {
    expect(pctForFrame(999, 101)).toBe(100)
    expect(pctForFrame(-5, 101)).toBe(0)
  })
})

describe('pickHandle', () => {
  const st = { start: 10, end: 90, playhead: 50 }

  it('grabs the nearest of the three', () => {
    expect(pickHandle(12, st)).toBe('start')
    expect(pickHandle(85, st)).toBe('end')
    expect(pickHandle(48, st)).toBe('playhead')
  })

  it('gives an exact tie to the playhead', () => {
    expect(pickHandle(30, { start: 10, end: 90, playhead: 50 })).toBe('playhead')
  })

  it('ignores the playhead entirely when no preview is loaded', () => {
    expect(pickHandle(48, { start: 10, end: 90, playhead: null })).toBe('start')
    expect(pickHandle(60, { start: 10, end: 90, playhead: null })).toBe('end')
  })

  it('still lets a bound be grabbed when the playhead sits on top of it', () => {
    // The tie goes to the playhead, but dragging it away leaves the bound uniquely
    // nearest — so the bound is never permanently unreachable.
    const stacked = { start: 0, end: 90, playhead: 0 }
    expect(pickHandle(0, stacked)).toBe('playhead')
    expect(pickHandle(0, { ...stacked, playhead: 40 })).toBe('start')
  })
})

describe('applyDrag', () => {
  const st = { start: 10, end: 90, playhead: 50 }

  it('moves only the dragged handle', () => {
    expect(applyDrag('start', 20, st, 101)).toEqual({ start: 20, end: 90, playhead: 50 })
    expect(applyDrag('end', 70, st, 101)).toEqual({ start: 10, end: 70, playhead: 50 })
    expect(applyDrag('playhead', 33, st, 101)).toEqual({ start: 10, end: 90, playhead: 33 })
  })

  it('pushes end when start is dragged past it', () => {
    expect(applyDrag('start', 95, st, 101)).toEqual({ start: 95, end: 95, playhead: 95 })
  })

  it('pushes start when end is dragged below it', () => {
    expect(applyDrag('end', 4, st, 101)).toEqual({ start: 4, end: 4, playhead: 4 })
  })

  it('pulls the playhead back inside the window when a bound crosses it', () => {
    // A needle left outside the authored range shows a frame this keyframe will
    // never render.
    expect(applyDrag('start', 60, st, 101).playhead).toBe(60)
    expect(applyDrag('end', 30, st, 101).playhead).toBe(30)
  })

  it('leaves a playhead already inside the window alone', () => {
    expect(applyDrag('start', 20, st, 101).playhead).toBe(50)
    expect(applyDrag('end', 70, st, 101).playhead).toBe(50)
  })

  it('lets the playhead itself roam outside the window while you hunt for bounds', () => {
    expect(applyDrag('playhead', 2, st, 101).playhead).toBe(2)
    expect(applyDrag('playhead', 99, st, 101).playhead).toBe(99)
  })

  it('clamps every handle to [0, n-1]', () => {
    expect(applyDrag('end', 5000, st, 101).end).toBe(100)
    expect(applyDrag('start', -3, st, 101).start).toBe(0)
    expect(applyDrag('playhead', 5000, st, 101).playhead).toBe(100)
  })

  it('keeps a null playhead null', () => {
    expect(applyDrag('start', 20, { start: 10, end: 90, playhead: null }, 101).playhead).toBeNull()
  })
})

describe('initFrameRangeSlider', () => {
  it('clamps the range into a shorter trajectory when the resolution changes', () => {
    const s = initFrameRangeSlider()
    s.setFrames(12000)
    s.setRange(4000, 9000)
    // Switching the same keyframe from full-job back to the 200-frame lineage view.
    s.setFrames(200)
    expect(s.getRange()).toEqual({ start: 199, end: 199 })
  })

  it('hides the playhead until a preview sets one', () => {
    const s = initFrameRangeSlider()
    s.setFrames(100)
    expect(s.getPlayhead()).toBeNull()
    s.setPlayhead(42)
    expect(s.getPlayhead()).toBe(42)
    s.setPlayhead(null)
    expect(s.getPlayhead()).toBeNull()
  })

  it('nudges the playhead one frame per arrow key and reports it', () => {
    const onPlayhead = vi.fn()
    const s = initFrameRangeSlider({ onPlayhead })
    s.setFrames(12000)
    s.setEnabled(true)
    s.setPlayhead(6000)
    s.el.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    expect(s.getPlayhead()).toBe(6001)
    expect(onPlayhead).toHaveBeenCalledWith(6001)
    s.el.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }))
    expect(s.getPlayhead()).toBe(6000)
  })

  it('ignores arrow keys with no preview loaded', () => {
    const onPlayhead = vi.fn()
    const s = initFrameRangeSlider({ onPlayhead })
    s.setFrames(100)
    s.setEnabled(true)
    s.el.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    expect(onPlayhead).not.toHaveBeenCalled()
  })

  it('keeps setRange ordered even when the caller passes them backwards', () => {
    const s = initFrameRangeSlider()
    s.setFrames(500)
    s.setRange(400, 100)
    expect(s.getRange()).toEqual({ start: 400, end: 400 })
  })
})

describe('initFrameRangeSlider drag lifecycle', () => {
  /** A 1000 px track over 1001 frames, so one pixel is exactly one frame. jsdom's real
   *  getBoundingClientRect is all zeros, which would collapse every press onto frame 0. */
  function makeDraggable(opts) {
    const s = initFrameRangeSlider(opts)
    s.el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 18 })
    s.setFrames(1001)
    s.setEnabled(true)
    return s
  }
  const at = (type, frame) =>
    new MouseEvent(type, { clientX: frame, bubbles: true, cancelable: true })

  it('saves ONCE on release, not on every pointer move', () => {
    const onRangeChange = vi.fn()
    const onRangeCommit = vi.fn()
    const s = makeDraggable({ onRangeChange, onRangeCommit })
    s.setRange(100, 900)

    s.el.dispatchEvent(at('pointerdown', 100))     // grab the start grip
    s.el.dispatchEvent(at('pointermove', 200))
    s.el.dispatchEvent(at('pointermove', 300))
    s.el.dispatchEvent(at('pointermove', 400))
    expect(onRangeCommit).not.toHaveBeenCalled()   // ← nothing saved mid-drag
    expect(onRangeChange.mock.calls.length).toBeGreaterThan(1)

    s.el.dispatchEvent(at('pointerup', 400))
    expect(onRangeCommit).toHaveBeenCalledTimes(1)
    expect(onRangeCommit).toHaveBeenCalledWith({ start: 400, end: 900 })
    expect(s.getRange()).toEqual({ start: 400, end: 900 })
  })

  it('does not save when a press moved nothing', () => {
    const onRangeCommit = vi.fn()
    const s = makeDraggable({ onRangeCommit })
    s.setRange(100, 900)
    s.el.dispatchEvent(at('pointerdown', 100))
    s.el.dispatchEvent(at('pointerup', 100))
    expect(onRangeCommit).not.toHaveBeenCalled()
  })

  it('does not save when the PLAYHEAD is the thing dragged', () => {
    const onRangeCommit = vi.fn()
    const onPlayhead = vi.fn()
    const s = makeDraggable({ onRangeCommit, onPlayhead })
    s.setRange(100, 900)
    s.setPlayhead(500)
    s.el.dispatchEvent(at('pointerdown', 500))
    s.el.dispatchEvent(at('pointermove', 600))
    s.el.dispatchEvent(at('pointerup', 600))
    expect(s.getPlayhead()).toBe(600)
    expect(onPlayhead).toHaveBeenCalledWith(600)
    expect(onRangeCommit).not.toHaveBeenCalled()
  })

  it('drags the playhead along and reports it when a bound crosses it', () => {
    const onPlayhead = vi.fn()
    const s = makeDraggable({ onPlayhead })
    s.setRange(100, 900)
    s.setPlayhead(200)
    s.el.dispatchEvent(at('pointerdown', 100))     // start grip
    s.el.dispatchEvent(at('pointermove', 400))     // dragged past the playhead
    s.el.dispatchEvent(at('pointerup', 400))
    expect(s.getPlayhead()).toBe(400)
    expect(onPlayhead).toHaveBeenLastCalledWith(400)
  })

  it('a cancelled pointer still commits what the drag reached', () => {
    const onRangeCommit = vi.fn()
    const s = makeDraggable({ onRangeCommit })
    s.setRange(100, 900)
    s.el.dispatchEvent(at('pointerdown', 900))     // end grip
    s.el.dispatchEvent(at('pointermove', 700))
    s.el.dispatchEvent(at('pointercancel', 700))
    expect(onRangeCommit).toHaveBeenCalledWith({ start: 100, end: 700 })
  })
})
