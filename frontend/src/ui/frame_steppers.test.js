import { describe, it, expect, vi } from 'vitest'
import { stepFrameIndex, frameStepperDisabled, initFrameSteppers } from './frame_steppers.js'

describe('stepFrameIndex', () => {
  it('steps one frame in each direction', () => {
    expect(stepFrameIndex(5, +1, 10)).toBe(6)
    expect(stepFrameIndex(5, -1, 10)).toBe(4)
  })

  it('clamps at both ends by default', () => {
    expect(stepFrameIndex(0, -1, 10)).toBe(0)
    expect(stepFrameIndex(9, +1, 10)).toBe(9)
  })

  it('wraps around when asked', () => {
    expect(stepFrameIndex(0, -1, 10, { wrap: true })).toBe(9)
    expect(stepFrameIndex(9, +1, 10, { wrap: true })).toBe(0)
  })

  it('returns 0 for an empty trajectory', () => {
    expect(stepFrameIndex(3, +1, 0)).toBe(0)
    expect(stepFrameIndex(3, +1, undefined)).toBe(0)
  })

  it('tolerates non-integer / missing state', () => {
    expect(stepFrameIndex(NaN, +1, 10)).toBe(1)
    expect(stepFrameIndex(4.7, +1, 10)).toBe(5)
    expect(stepFrameIndex(undefined, -1, 10)).toBe(0)
  })
})

describe('frameStepperDisabled', () => {
  it('disables both when there is nothing to step through', () => {
    expect(frameStepperDisabled(0, 0)).toEqual({ prev: true, next: true })
    expect(frameStepperDisabled(0, 1)).toEqual({ prev: true, next: true })
  })

  it('disables the end the current frame sits on', () => {
    expect(frameStepperDisabled(0, 10)).toEqual({ prev: true, next: false })
    expect(frameStepperDisabled(9, 10)).toEqual({ prev: false, next: true })
    expect(frameStepperDisabled(5, 10)).toEqual({ prev: false, next: false })
  })

  it('never disables a wrapping trajectory', () => {
    expect(frameStepperDisabled(0, 10, { wrap: true })).toEqual({ prev: false, next: false })
    expect(frameStepperDisabled(9, 10, { wrap: true })).toEqual({ prev: false, next: false })
  })
})

describe('initFrameSteppers', () => {
  function setup({ n = 10, start = 5, wrap = false } = {}) {
    const prevBtn = document.createElement('button')
    const nextBtn = document.createElement('button')
    let frame = start
    const onStep = vi.fn((i) => { frame = i })
    const api = initFrameSteppers({
      prevBtn, nextBtn, wrap, count: () => n, current: () => frame, onStep,
    })
    return { prevBtn, nextBtn, onStep, api, frame: () => frame }
  }

  it('clicking the buttons steps the frame by ±1', () => {
    const { prevBtn, nextBtn, onStep, frame } = setup()
    nextBtn.click()
    expect(onStep).toHaveBeenLastCalledWith(6)
    prevBtn.click()
    prevBtn.click()
    expect(frame()).toBe(4)
  })

  it('greys out at the ends and does not fire there', () => {
    const { prevBtn, nextBtn, onStep } = setup({ start: 0 })
    expect(prevBtn.disabled).toBe(true)
    expect(nextBtn.disabled).toBe(false)
    prevBtn.click()
    expect(onStep).not.toHaveBeenCalled()
    // stepping to the last frame disables the other end
    for (let i = 0; i < 9; i++) nextBtn.click()
    expect(nextBtn.disabled).toBe(true)
    expect(prevBtn.disabled).toBe(false)
  })

  it('disables both buttons for a single-frame trajectory', () => {
    const { prevBtn, nextBtn, onStep } = setup({ n: 1, start: 0 })
    expect(prevBtn.disabled).toBe(true)
    expect(nextBtn.disabled).toBe(true)
    nextBtn.click()
    expect(onStep).not.toHaveBeenCalled()
  })

  it('wraps past the ends when wrap is set', () => {
    const { prevBtn, nextBtn, onStep, frame } = setup({ start: 0, wrap: true })
    expect(prevBtn.disabled).toBe(false)
    prevBtn.click()
    expect(frame()).toBe(9)
    nextBtn.click()
    expect(onStep).toHaveBeenLastCalledWith(0)
  })

  it('refresh() re-syncs disabled state after an external frame change', () => {
    const prevBtn = document.createElement('button')
    const nextBtn = document.createElement('button')
    let frame = 5
    const api = initFrameSteppers({
      prevBtn, nextBtn, count: () => 10, current: () => frame, onStep: () => {},
    })
    expect(prevBtn.disabled).toBe(false)
    frame = 0                       // e.g. the player looped back around
    api.refresh()
    expect(prevBtn.disabled).toBe(true)
  })

  it('is a no-op factory when the buttons are absent', () => {
    expect(() => initFrameSteppers({ count: () => 5, current: () => 0 })).not.toThrow()
    expect(() => initFrameSteppers().step(+1)).not.toThrow()
  })
})
