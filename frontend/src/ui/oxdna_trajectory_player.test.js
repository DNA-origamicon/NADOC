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

  it('prepares while paused, then starts synchronously without redoing preparation', async () => {
    let release, settings = 'atoms'
    const onBeforePlay = vi.fn(() => new Promise(resolve => { release = resolve }))
    const p = initOxdnaTrajectoryPlayer({ playBtn, onBeforePlay, preparationKey: () => settings })
    p.setTrajectory(4)
    try {
      const prepared = p.prepare()
      expect(playBtn.disabled).toBe(true)
      expect(p.isPlaying()).toBe(false)
      release(true); expect(await prepared).toBe(true)
      expect(playBtn.disabled).toBe(false)
      p.play()
      expect(p.isPlaying()).toBe(true)
      expect(onBeforePlay).toHaveBeenCalledTimes(1)
      p.pause()
      settings = 'atoms+ions'
      const reprepare = p.prepare()
      expect(playBtn.disabled).toBe(true)
      release(true); await reprepare
      p.play()
      expect(p.isPlaying()).toBe(true)
      expect(onBeforePlay).toHaveBeenCalledTimes(2)
    } finally { p.stop() }
  })

  it('blends only during play, pauses on the last saved frame, and resumes from it', async () => {
    vi.useFakeTimers()
    const interpolationToggle = document.createElement('input')
    interpolationToggle.checked = true
    const onInterpolate = vi.fn(), onSeek = vi.fn()
    const p = initOxdnaTrajectoryPlayer({ interpolationToggle, onInterpolate, onSeek, fps: 10 })
    p.setTrajectory(3)
    try {
      await p.play()
      await vi.advanceTimersByTimeAsync(64)
      expect(onInterpolate.mock.calls.at(-1)).toEqual([0, 1, expect.any(Number), { before: null, after: 2 }])
      expect(onInterpolate.mock.calls.at(-1)[2]).toBeGreaterThan(0)
      expect(onInterpolate.mock.calls.at(-1)[2]).toBeLessThan(1)
      p.pause()
      expect(onSeek).toHaveBeenLastCalledWith(0)
      const calls = onInterpolate.mock.calls.length
      await vi.advanceTimersByTimeAsync(200)
      expect(onInterpolate).toHaveBeenCalledTimes(calls)
      await p.play()
      await vi.advanceTimersByTimeAsync(150)
      expect(p.current()).toBe(1)
      p.pause()
      expect(onSeek).toHaveBeenLastCalledWith(1)
    } finally { p.stop() }
  })

  it('does not blend before endpoints load or repaint after pause cancels the load', async () => {
    vi.useFakeTimers()
    const interpolationToggle = { checked: true, addEventListener() {} }
    let release
    const onInterpolate = vi.fn(), onSeek = vi.fn()
    const p = initOxdnaTrajectoryPlayer({ interpolationToggle, onInterpolate, onSeek,
      onBeforeInterpolate: () => new Promise(resolve => { release = resolve }) })
    p.setTrajectory(3)
    try {
      const playing = p.play(); await vi.advanceTimersByTimeAsync(500)
      expect(onInterpolate).not.toHaveBeenCalled()
      expect(p.current()).toBe(0)
      p.pause(); release(true)
      await playing
      await vi.advanceTimersByTimeAsync(500)
      expect(onInterpolate).not.toHaveBeenCalled()
      expect(onSeek).not.toHaveBeenCalled()
    } finally { p.stop() }
  })

  it('snaps across stage and loop boundaries and when smoothing is switched off', async () => {
    vi.useFakeTimers()
    const interpolationToggle = document.createElement('input')
    interpolationToggle.checked = true
    const onInterpolate = vi.fn(), onSeek = vi.fn()
    const p = initOxdnaTrajectoryPlayer({ interpolationToggle, onInterpolate, onSeek, fps: 10 })
    p.setTrajectory(3, [{ frame: 1 }])
    try {
      await p.play(); await vi.advanceTimersByTimeAsync(120)
      // Residual time now draws the next valid segment in the boundary callback.
      expect(onInterpolate.mock.calls.every(([a, b]) => a === 1 && b === 2)).toBe(true)
      expect(p.current()).toBe(1)
      await vi.advanceTimersByTimeAsync(210)
      expect(onInterpolate.mock.calls.every(([a, b]) => a === 1 && b === 2)).toBe(true)
      await vi.advanceTimersByTimeAsync(180)
      interpolationToggle.checked = false
      interpolationToggle.dispatchEvent(new Event('change'))
      const calls = onInterpolate.mock.calls.length
      expect(onSeek.mock.calls.at(-1)[0]).toBe(p.current())
      await vi.advanceTimersByTimeAsync(300)
      expect(onInterpolate).toHaveBeenCalledTimes(calls)
      expect(p.isPlaying()).toBe(true)
    } finally { p.stop() }
  })

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

  it('holds the frame and clock while a companion seek waits, and ignores cancelled results', async () => {
    vi.useFakeTimers()
    let release
    const onSeek = vi.fn()
    const ready = vi.fn(() => new Promise(resolve => { release = resolve }))
    const p = initOxdnaTrajectoryPlayer({ playBtn, slider, label, onSeek,
      onBeforeSeek: ready, fps: 10 })
    p.setTrajectory(100)
    try {
      await p.play()
      await vi.advanceTimersByTimeAsync(1000)
      expect(p.current()).toBe(0)
      expect(ready).toHaveBeenCalledTimes(1)
      expect(onSeek).not.toHaveBeenCalled()
      release(true)
      await vi.advanceTimersByTimeAsync(0)
      expect(p.current()).toBe(1)
      expect(onSeek).toHaveBeenCalledWith(1)
      await vi.advanceTimersByTimeAsync(100)
      p.pause()
      release(true)
      await vi.advanceTimersByTimeAsync(1000)
      expect(p.current()).toBe(1)
      expect(onSeek).toHaveBeenCalledTimes(1)
      expect(p.isPlaying()).toBe(false)
    } finally { p.stop() }
  })

  it('applies only the newest manual seek and pauses on a missing companion frame', async () => {
    const pending = new Map()
    const onSeek = vi.fn()
    const p = initOxdnaTrajectoryPlayer({ onSeek,
      onBeforeSeek: i => new Promise(resolve => pending.set(i, resolve)) })
    p.setTrajectory(100)
    try {
      const first = p.seek(20), second = p.seek(40)
      pending.get(40)(true); await second
      pending.get(20)(true); await first
      expect(p.current()).toBe(40)
      expect(onSeek.mock.calls).toEqual([[40]])
      await p.play()
      const fail = p.seek(50)
      pending.get(50)(false); await fail
      expect(p.current()).toBe(40)
      expect(p.isPlaying()).toBe(false)
    } finally { p.stop() }
  })

  it('renders one shared trajectory-loading bar with frame N of total', () => {
    player.setLoading({ done: 17, total: 80 })
    expect(loadProgressEl.style.display).not.toBe('none')
    expect(loadProgressEl.querySelector('[data-trajectory-load-fill]').style.width).toBe('21.25%')
    expect(loadProgressEl.textContent).toContain('Aligning frames… 21%')
    player.setLoading(null)
    expect(loadProgressEl.style.display).toBe('none')
  })

  it('retains one labelled progress bar per subprocess until the load finishes', () => {
    player.setLoading({ reset: true, phase: 'align', label: 'Read & align frames', done: 4, total: 8 })
    player.setLoading({ phase: 'pack', label: 'Pack display frames', done: 2, total: 8 })
    player.setLoading({ phase: 'download', label: 'Download trajectory', done: 5, total: 10 })
    const rows = loadProgressEl.querySelectorAll('[data-trajectory-load-phase]')
    expect(rows).toHaveLength(3)
    expect(Array.from(rows).map(r => r.dataset.trajectoryLoadPhase))
      .toEqual(['align', 'pack', 'download'])
    expect(rows[0].textContent).toContain('Read & align frames · 4 of 8')
    expect(rows[1].querySelector('[data-trajectory-load-fill]').style.width).toBe('25%')
    expect(rows[2].textContent).toContain('Download trajectory · 5 of 10')
    player.setLoading(null)
    expect(loadProgressEl.querySelectorAll('[data-trajectory-load-phase]')).toHaveLength(0)
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

it('reports buffering without advancing the scene and clears it after the exact frame arrives',async()=>{
  const label=document.createElement('span'),slider=document.createElement('input')
  let release
  const onSeek=vi.fn(),p=initOxdnaTrajectoryPlayer({label,slider,onSeek,
    onBeforeSeek:()=>new Promise(resolve=>{release=resolve})})
  p.setTrajectory(250)
  const pending=p.seek(249)
  expect(label.textContent).toBe('Frame 1 / 250 · buffering…')
  expect(p.current()).toBe(0)
  expect(onSeek).not.toHaveBeenCalled()
  release(true);await pending
  expect(label.textContent).toBe('Frame 250 / 250')
  expect(onSeek).toHaveBeenCalledWith(249)
  p.stop()
})

// Scrubs preview immediately; playback waits for saved frames. Stale exact
// completion must never replace a newer requested point.
describe('interactive preview and exact settling', () => {
  it('shows each scrub immediately, debounces exact reads, and labels failures honestly', async () => {
    vi.useFakeTimers()
    const slider = document.createElement('input'), label = document.createElement('div')
    const preview = vi.fn(), exact = vi.fn()
    let finish
    exact.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const p = initOxdnaTrajectoryPlayer({ slider, label, previewReady: () => true,
      onPreview: preview, onExactSeek: exact })
    p.setTrajectory(100)
    const scrub = i => { slider.value = String(i); slider.dispatchEvent(new Event('input')) }
    scrub(12); scrub(57); scrub(90)
    expect(preview.mock.calls.map(c => c[0])).toEqual([12, 57, 90])
    expect(label.textContent).toContain('Frame 91 / 100 · preview')
    expect(exact).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(180)
    expect(exact).toHaveBeenCalledTimes(1)
    expect(exact.mock.calls[0][0]).toBe(90)
    expect(label.textContent).toContain('loading exact')
    scrub(20)
    expect(exact.mock.calls[0][1]()).toBe(false)
    finish(true); await Promise.resolve()
    expect(label.textContent).toContain('Frame 21 / 100 · preview')
    await vi.advanceTimersByTimeAsync(180)
    finish(false); await Promise.resolve(); await Promise.resolve()
    expect(label.textContent).toContain('exact frame unavailable')
    scrub(30); await vi.advanceTimersByTimeAsync(180)
    finish(true); await Promise.resolve(); await Promise.resolve()
    expect(label.textContent).toBe('Frame 31 / 100')
    p.stop(); vi.useRealTimers()
  })

  it('plays every saved frame with smoothing off even when previews are available', async () => {
    vi.useFakeTimers()
    const preview = vi.fn(), exact = vi.fn(), before = vi.fn(async () => true), saved = vi.fn()
    const p = initOxdnaTrajectoryPlayer({ previewReady: () => true,
      onPreview: preview, onExactSeek: exact, onBeforeSeek: before, onSeek: saved, fps: 10 })
    p.setTrajectory(100)
    await p.play(); await vi.advanceTimersByTimeAsync(1000)
    expect(saved.mock.calls.map(c => c[0])).toEqual([1,2,3,4,5,6,7,8,9,10])
    expect(before).toHaveBeenCalledTimes(10)
    expect(preview).not.toHaveBeenCalled(); expect(exact).not.toHaveBeenCalled()
    p.pause(); p.stop(); vi.useRealTimers()
  })
})

it('smooth playback waits for adjacent saved endpoints and never uses sparse previews', async () => {
  vi.useFakeTimers()
  let release
  const onPreview = vi.fn(), onBeforeInterpolate = vi.fn(() => new Promise(resolve => { release = resolve }))
  const onInterpolate = vi.fn()
  const p = initOxdnaTrajectoryPlayer({ previewReady: () => true, onPreview,
    onBeforeInterpolate, onInterpolate, interpolationToggle: { checked: true, addEventListener() {} } })
  p.setTrajectory(100)
  try {
    const playing = p.play(); await vi.advanceTimersByTimeAsync(400)
    expect(onPreview).not.toHaveBeenCalled(); expect(onInterpolate).not.toHaveBeenCalled()
    onBeforeInterpolate.mockResolvedValue(true); release(true); await playing
    await vi.advanceTimersByTimeAsync(400)
    expect(p.current()).toBeGreaterThan(0)
    expect(onPreview).not.toHaveBeenCalled()
    expect(onInterpolate.mock.calls.length).toBeGreaterThan(0)
    for (const [from,to] of onInterpolate.mock.calls) expect(to).toBe(from + 1)
  } finally { p.stop(); vi.useRealTimers() }
})

it('holds the saved frame on a cache miss instead of substituting a sparse preview', async () => {
  vi.useFakeTimers()
  const onPreview = vi.fn(), onSeek = vi.fn()
  let release
  const p = initOxdnaTrajectoryPlayer({ previewReady: () => true, onPreview, onSeek,
    onBeforeSeek: () => new Promise(resolve => { release = resolve }), fps: 10 })
  p.setTrajectory(100)
  try {
    await p.play(); await vi.advanceTimersByTimeAsync(600)
    expect(p.current()).toBe(0); expect(onSeek).not.toHaveBeenCalled(); expect(onPreview).not.toHaveBeenCalled()
    release(true); await Promise.resolve(); await Promise.resolve()
    expect(p.current()).toBe(1); expect(onSeek).toHaveBeenCalledWith(1)
  } finally { p.stop(); vi.useRealTimers() }
})

it('loads the exact scrub position before playback and allows that load to be cancelled', async () => {
  const slider = document.createElement('input'), onSeek = vi.fn(), onPreview = vi.fn()
  let release
  const p = initOxdnaTrajectoryPlayer({ slider, previewReady: () => true, onPreview, onSeek,
    onBeforeSeek: () => new Promise(resolve => { release = resolve }) })
  p.setTrajectory(100)
  try {
    slider.value = '55'; slider.dispatchEvent(new Event('input'))
    const pending = p.play()
    expect(p.isPlaying()).toBe(false); expect(onSeek).not.toHaveBeenCalled()
    p.pause(); release(true); await pending
    expect(p.isPlaying()).toBe(false); expect(onSeek).not.toHaveBeenCalled()
    const resumed = p.play(); release(true); await resumed
    expect(onSeek).toHaveBeenCalledWith(55); expect(p.isPlaying()).toBe(true)
  } finally { p.stop() }
})
