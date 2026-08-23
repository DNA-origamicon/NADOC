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
  let playBtn, slider, markersEl, label, loadProgressEl, seeks, player
  beforeEach(() => {
    playBtn = document.createElement('button')
    slider = document.createElement('input'); slider.type = 'range'
    markersEl = document.createElement('div')
    label = document.createElement('div')
    loadProgressEl = document.createElement('div')
    seeks = []
    player = initOxdnaTrajectoryPlayer({
      playBtn, slider, markersEl, label, loadProgressEl,
      onSeek: (i) => seeks.push(i), fps: 10,
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

  it('renders one shared trajectory-loading bar with frame N of total', () => {
    player.setLoading({ done: 17, total: 80 })
    expect(loadProgressEl.style.display).not.toBe('none')
    expect(loadProgressEl.querySelector('[data-trajectory-load-fill]').style.width).toBe('21.25%')
    expect(loadProgressEl.textContent).toContain('Aligning frames… 21%')
    player.setLoading(null)
    expect(loadProgressEl.style.display).toBe('none')
  })

  describe('◂ / ▸ frame steppers', () => {
    let prevBtn, nextBtn
    beforeEach(() => {
      prevBtn = document.createElement('button')
      nextBtn = document.createElement('button')
      seeks = []
      player.stop()
      player = initOxdnaTrajectoryPlayer({
        playBtn, slider, markersEl, label, prevBtn, nextBtn,
        onSeek: (i) => seeks.push(i), fps: 10,
      })
    })

    it('steps one frame and moves the slider + label with it', () => {
      player.setTrajectory(10, [])
      player.seek(4)
      nextBtn.click()
      expect(player.current()).toBe(5)
      expect(slider.value).toBe('5')
      expect(label.textContent).toContain('6 / 10')
      prevBtn.click()
      prevBtn.click()
      expect(seeks).toEqual([4, 5, 4, 3])
    })

    it('greys out at whichever end the trajectory is parked on', () => {
      player.setTrajectory(10, [])
      expect(prevBtn.disabled).toBe(true)     // reset to frame 0
      expect(nextBtn.disabled).toBe(false)
      player.seek(9)
      expect(prevBtn.disabled).toBe(false)
      expect(nextBtn.disabled).toBe(true)
    })

    it('both are dead with no trajectory loaded', () => {
      expect(prevBtn.disabled).toBe(true)
      expect(nextBtn.disabled).toBe(true)
      player.setTrajectory(1, [])             // single frame: nothing to step to
      expect(nextBtn.disabled).toBe(true)
      nextBtn.click()
      expect(seeks).toEqual([])
    })

    it('stepping pauses playback', () => {
      vi.useFakeTimers()
      player.setTrajectory(10, [])
      player.play()
      expect(player.isPlaying()).toBe(true)
      nextBtn.click()
      expect(player.isPlaying()).toBe(false)
    })
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
    expect(playBtn.querySelector('.nadoc-spinner'), 'spinner while preparing').toBeTruthy()
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

// A heavy trajectory cannot play until every coarse cell is in memory — at 8 fps the loop
// cannot stop for a ~2 s fetch per frame. The button used to show a ready ▶ throughout the
// background prepare, so the user pressed it expecting instant playback and got a
// multi-second wait. Scrubbing keeps working during that window (it needs only the one
// cell you stop on), which made the button look broken rather than busy.
describe('background prepare is visible on the play button', () => {
  let playBtn, slider, player

  beforeEach(() => {
    document.body.innerHTML = ''
    playBtn = document.createElement('button')
    slider = document.createElement('input')
    slider.type = 'range'
    document.body.append(playBtn, slider)
    player = initOxdnaTrajectoryPlayer({ playBtn, slider, fps: 10 })
    player.setTrajectory(5, [])
  })
  afterEach(() => { player.stop() })

  const spinner = () => playBtn.querySelector('.nadoc-spinner')

  it('shows ▶ and is clickable when nothing is being prepared', () => {
    expect(playBtn.textContent).toBe('▶')
    expect(playBtn.disabled).toBe(false)
  })

  it('swaps ▶ for a spinner and refuses the click while preparing', () => {
    player.setPreparing({ done: 12, total: 200 })
    expect(spinner()).toBeTruthy()
    expect(playBtn.textContent).not.toContain('▶')
    expect(playBtn.disabled).toBe(true)
    expect(player.isPreparing()).toBe(true)
    // …and the click really is inert, not merely styled as such.
    playBtn.click()
    expect(player.isPlaying()).toBe(false)
  })

  it('puts the frame count in the tooltip so the wait is quantified', () => {
    player.setPreparing({ done: 12, total: 200 })
    expect(playBtn.title).toMatch(/12\/200/)
  })

  it('restores a clickable ▶ when the prepare finishes', () => {
    player.setPreparing({ done: 200, total: 200 })
    player.setPreparing(null)
    expect(spinner()).toBeNull()
    expect(playBtn.textContent).toBe('▶')
    expect(playBtn.disabled).toBe(false)
    playBtn.click()
    expect(player.isPlaying()).toBe(true)
  })

  // Whatever was being prepared belonged to the old trajectory; leaving the spinner up
  // would disable playback for a job with nothing pending.
  it('clears the spinner on stop (job switch)', () => {
    player.setPreparing({ done: 1, total: 200 })
    player.stop()
    expect(spinner()).toBeNull()
    expect(playBtn.disabled).toBe(false)
  })

  it('a zero-length prepare is treated as nothing to do', () => {
    player.setPreparing({ done: 0, total: 0 })
    expect(spinner()).toBeNull()
    expect(playBtn.disabled).toBe(false)
  })

  it('pausing mid-playback returns to ▶, not to a spinner', () => {
    playBtn.click()
    expect(player.isPlaying()).toBe(true)
    expect(playBtn.textContent).toBe('⏸')
    playBtn.click()
    expect(playBtn.textContent).toBe('▶')
    expect(spinner()).toBeNull()
  })
})
