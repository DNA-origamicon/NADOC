// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { markerPositions, initOxdnaTrajectoryPlayer, stageAtFrame, fieldAtFrame } from './oxdna_trajectory_player.js'

describe('markerPositions', () => {
  it('maps frame index → slider pct', () => {
    const m = markerPositions([{ frame: 0, kind: 'mc' }, { frame: 5, kind: 'production' }], 11)
    expect(m[0].pct).toBe(0)
    expect(m[1].pct).toBe(50)   // 5 / (11-1)
  })
  it('is empty for <2 frames or no markers', () => {
    expect(markerPositions([{ frame: 0 }], 1)).toEqual([])
    expect(markerPositions(null, 10)).toEqual([])
  })
})

describe('stageAtFrame / fieldAtFrame', () => {
  // relaxation (3 frames, no field) → field run +x (2 frames) → field run −x (2 frames)
  const stages = [
    { name: '1_relax', kind: 'equil', n_frames: 3, field: null },
    { name: '1_field', kind: 'field', n_frames: 2, field: { dir: [1, 0, 0], field_pN: 5 } },
    { name: '1_field', kind: 'field', n_frames: 2, field: { dir: [-1, 0, 0], field_pN: 5 } },
  ]
  it('maps a frame index to its contiguous stage', () => {
    expect(stageAtFrame(stages, 0).name).toBe('1_relax')
    expect(stageAtFrame(stages, 2).kind).toBe('equil')
    expect(stageAtFrame(stages, 3).field.dir).toEqual([1, 0, 0])
    expect(stageAtFrame(stages, 4).field.dir).toEqual([1, 0, 0])
    expect(stageAtFrame(stages, 5).field.dir).toEqual([-1, 0, 0])
  })
  it('clamps a past-the-end index to the last stage; null for empty', () => {
    expect(stageAtFrame(stages, 99).field.dir).toEqual([-1, 0, 0])
    expect(stageAtFrame([], 0)).toBe(null)
    expect(stageAtFrame(null, 0)).toBe(null)
  })
  it('fieldAtFrame is null in the relaxation stage and the run field elsewhere', () => {
    expect(fieldAtFrame(stages, 1)).toBe(null)          // relaxation → arrow hidden
    expect(fieldAtFrame(stages, 3).dir).toEqual([1, 0, 0])
    expect(fieldAtFrame(stages, 5).dir).toEqual([-1, 0, 0])
    expect(fieldAtFrame([], 0)).toBe(null)
  })
})

describe('initOxdnaTrajectoryPlayer', () => {
  let playBtn, slider, markersEl, label, seeks, player
  beforeEach(() => {
    playBtn = document.createElement('button')
    slider = document.createElement('input'); slider.type = 'range'
    markersEl = document.createElement('div')
    label = document.createElement('div')
    seeks = []
    player = initOxdnaTrajectoryPlayer({
      playBtn, slider, markersEl, label, onSeek: (i) => seeks.push(i), fps: 10,
    })
  })
  afterEach(() => { player.stop(); vi.useRealTimers() })

  it('setTrajectory configures the slider, markers, and frame label', () => {
    player.setTrajectory(8, [{ frame: 4, label: '→ production', kind: 'production' }])
    expect(slider.max).toBe('7')
    expect(slider.disabled).toBe(false)
    expect(markersEl.querySelectorAll('div').length).toBe(1)   // one transition tick
    expect(label.textContent).toContain('1 / 8')
  })

  it('seek fires onSeek and updates slider + label', () => {
    player.setTrajectory(10, [])
    player.seek(3)
    expect(seeks).toContain(3)
    expect(slider.value).toBe('3')
    expect(label.textContent).toContain('4 / 10')
  })

  it('play advances frames on a timer; pause stops it', () => {
    vi.useFakeTimers()
    player.setTrajectory(5, [])
    player.play()
    expect(player.isPlaying()).toBe(true)
    vi.advanceTimersByTime(320)               // ~3 ticks at 10fps
    expect(player.current()).toBeGreaterThan(0)
    player.pause()
    const at = player.current()
    vi.advanceTimersByTime(320)
    expect(player.current()).toBe(at)          // frozen after pause
  })

  it('play loops back to 0 at the end', () => {
    vi.useFakeTimers()
    player.setTrajectory(2, [])
    player.play()
    vi.advanceTimersByTime(100)   // frame 0 → 1
    vi.advanceTimersByTime(100)   // frame 1 → wrap to 0
    expect(player.current()).toBe(0)
  })

  it('stop clears everything', () => {
    player.setTrajectory(5, [{ frame: 2, kind: 'production' }])
    player.stop()
    expect(player.count()).toBe(0)
    expect(markersEl.innerHTML).toBe('')
    expect(slider.disabled).toBe(true)
  })

  it('with onBeforePlay, play awaits the pre-build (spinner shown) before the loop starts', async () => {
    let release
    const onBeforePlay = vi.fn(() => new Promise((r) => { release = () => r(true) }))
    const onPlayStateChange = vi.fn()
    const p = initOxdnaTrajectoryPlayer({ playBtn, slider, onBeforePlay, onPlayStateChange, fps: 10 })
    p.setTrajectory(5, [])
    p.play()
    await Promise.resolve()
    expect(onBeforePlay).toHaveBeenCalledTimes(1)
    expect(p.isPlaying()).toBe(false)            // not playing yet — still pre-building
    expect(playBtn.textContent).toBe('⏳')        // spinner while preparing
    expect(onPlayStateChange).not.toHaveBeenCalled()
    release()                                     // pre-build finished
    await Promise.resolve(); await Promise.resolve()
    expect(p.isPlaying()).toBe(true)
    expect(onPlayStateChange).toHaveBeenCalledWith(true)
    p.stop()
  })

  it('clicking again while preparing cancels — the loop never starts when the pre-build resolves', async () => {
    let release
    const onBeforePlay = vi.fn(() => new Promise((r) => { release = () => r(true) }))
    const p = initOxdnaTrajectoryPlayer({ playBtn, slider, onBeforePlay, fps: 10 })
    p.setTrajectory(5, [])
    p.play()
    await Promise.resolve()
    p.pause()                                     // user clicks again mid-prepare → cancel
    release()
    await Promise.resolve(); await Promise.resolve()
    expect(p.isPlaying()).toBe(false)             // the resolved prepare did NOT start the loop
    expect(playBtn.textContent).toBe('▶')
    p.stop()
  })
})
