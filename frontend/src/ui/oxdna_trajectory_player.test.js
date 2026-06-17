// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { markerPositions, initOxdnaTrajectoryPlayer } from './oxdna_trajectory_player.js'

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
})
