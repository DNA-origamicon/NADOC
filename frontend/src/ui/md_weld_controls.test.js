// md_weld_controls.test.js
//
// The case worth pinning hardest is the COMMON one: most designs have no weld pair at
// all (only extra bases on a reciprocal crossover pair make one), so "nothing to show"
// has to read as information, not as a failure the user goes hunting for.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  weldStatusText, weldReadoutLines, initMdWeldControls,
  weldTraceSeries, weldTraceSummary, TRACE_META,
} from './md_weld_controls.js'

describe('weldStatusText', () => {
  it('is blank when the layer is off', () => {
    expect(weldStatusText({ enabled: false, ready: true, pairs: [{}] })).toBe('')
  })

  it('states plainly that a design has no weld pair', () => {
    expect(weldStatusText({ enabled: true, ready: true, pairs: [] }))
      .toBe('no weld pair in this design')
  })

  it('prefers the backend reason when it gives one', () => {
    expect(weldStatusText({
      enabled: true, ready: true, pairs: [],
      reason: 'design has no extra-base reciprocal crossover pair',
    })).toBe('design has no extra-base reciprocal crossover pair')
  })

  it('surfaces a not-ready reason (no trajectory yet, no topology, …)', () => {
    expect(weldStatusText({ enabled: true, ready: false, reason: 'no NAMD trajectory yet', pairs: [] }))
      .toBe('no NAMD trajectory yet')
  })

  it('counts pairs, singular and plural', () => {
    expect(weldStatusText({ enabled: true, ready: true, pairs: [{}] })).toBe('1 weld pair')
    expect(weldStatusText({ enabled: true, ready: true, pairs: [{}, {}, {}, {}] })).toBe('4 weld pairs')
  })
})

describe('weldReadoutLines', () => {
  it('omits the label when there is only one pair', () => {
    expect(weldReadoutLines([{ label: 'a~b', readout: 'd 3.40 Å' }])).toEqual(['d 3.40 Å'])
  })

  it('labels each line when there are several', () => {
    expect(weldReadoutLines([
      { label: 'a~b', readout: 'd 3.40 Å' },
      { label: 'c~d', readout: 'd 9.10 Å' },
    ])).toEqual(['a~b  d 3.40 Å', 'c~d  d 9.10 Å'])
  })

  it('is empty for nothing, so the block hides instead of showing a stale value', () => {
    expect(weldReadoutLines([])).toEqual([])
    expect(weldReadoutLines(null)).toEqual([])
  })
})

// ── trace over the whole run ─────────────────────────────────────────────────

const TRACE = {
  ready: true, n_frames: 3, n_total_frames: 600, stride: 20,
  times_ps: [0, 2000, 4000],
  pairs: [{
    id: 'a:0~b:0', label: 'a[k=0]~b[k=0]',
    d_nm: [1.14, 0.90, 1.05], eta_deg: [-170, 30, 90], k: [0.08, 0.20, 0.05],
    d_min_nm: 0.90, d_mean_nm: 1.03, k_max: 0.20, k_mean: 0.11, reactive_frames: 0,
  }],
}

describe('weldTraceSeries', () => {
  it('plots time in ns on x, not a frame index', () => {
    // Once the stride widens, a frame index no longer maps to anything the user can
    // reason about; the run's own clock does.
    const [s] = weldTraceSeries(TRACE, 'd')
    expect(s.points.map((p) => p[0])).toEqual([0, 2, 4])
  })

  it('converts distance to Angstrom, the unit every other readout uses', () => {
    const [s] = weldTraceSeries(TRACE, 'd')
    const ys = s.points.map((p) => p[1])
    // toBeCloseTo, not toEqual: 1.14 * 10 is 11.399999999999999 in IEEE754.
    ;[11.4, 9, 10.5].forEach((want, i) => expect(ys[i]).toBeCloseTo(want, 10))
    expect(TRACE_META.d.scale).toBe(10)
  })

  it('leaves eta and k unscaled', () => {
    expect(weldTraceSeries(TRACE, 'eta')[0].points.map((p) => p[1])).toEqual([-170, 30, 90])
    expect(weldTraceSeries(TRACE, 'k')[0].points.map((p) => p[1])).toEqual([0.08, 0.2, 0.05])
  })

  it('gives each pair its own colour', () => {
    const two = { ...TRACE, pairs: [TRACE.pairs[0], { ...TRACE.pairs[0], id: 'x', label: 'x' }] }
    const s = weldTraceSeries(two, 'd')
    expect(s).toHaveLength(2)
    expect(s[0].color).not.toBe(s[1].color)
  })

  it('falls back to the distance metric for an unknown one', () => {
    expect(weldTraceSeries(TRACE, 'nonsense')[0].points[0][1]).toBeCloseTo(11.4, 10)
  })

  it('is empty for a missing or pairless result', () => {
    expect(weldTraceSeries(null, 'd')).toEqual([])
    expect(weldTraceSeries({ pairs: [] }, 'd')).toEqual([])
  })

  it('drops a pair with no samples rather than charting an empty line', () => {
    expect(weldTraceSeries({ ...TRACE, pairs: [{ ...TRACE.pairs[0], d_nm: [] }] }, 'd'))
      .toEqual([])
  })
})

describe('weldTraceSummary', () => {
  it('leads with the minimum distance, which is the actual question', () => {
    const s = weldTraceSummary(TRACE)
    expect(s).toContain('min 9.00 Å')
    expect(s.indexOf('min')).toBeLessThan(s.indexOf('mean'))
  })

  it('says plainly when the pair was never reactive', () => {
    expect(weldTraceSummary(TRACE)).toContain('never reactive')
  })

  it('counts reactive frames when there are any', () => {
    const hot = { ...TRACE, pairs: [{ ...TRACE.pairs[0], reactive_frames: 7 }] }
    expect(weldTraceSummary(hot)).toContain('7 reactive')
  })

  it('states the coverage so a strided trace is not mistaken for the whole run', () => {
    expect(weldTraceSummary(TRACE)).toContain('3 of 600 frames (stride 20)')
  })

  it('is blank with nothing to summarise', () => {
    expect(weldTraceSummary(null)).toBe('')
    expect(weldTraceSummary({ pairs: [] })).toBe('')
  })
})

// ── factory ──────────────────────────────────────────────────────────────────

const MARKUP = `
  <input id="md-jobs-weld-toggle" type="checkbox">
  <div id="md-jobs-weld-readout" style="display:none"></div>
  <div id="md-jobs-weld-status"></div>`

function makeOverlay (pairs = [{ id: 'p1' }]) {
  return {
    loadForJob: vi.fn().mockResolvedValue({ ready: true, pairs, reason: null }),
    setPairs: vi.fn(),
    setVisible: vi.fn(),
    getReadouts: vi.fn().mockReturnValue(
      pairs.map((p, i) => ({ id: p.id, label: `l${i}`, readout: 'd 3.40 Å   η +0°   k 0.418' }))),
  }
}

const els = () => ({
  toggle: document.getElementById('md-jobs-weld-toggle'),
  readout: document.getElementById('md-jobs-weld-readout'),
  status: document.getElementById('md-jobs-weld-status'),
})

describe('initMdWeldControls', () => {
  beforeEach(() => {
    document.body.innerHTML = MARKUP
    try { localStorage.clear() } catch { /* ignore */ }
    vi.useFakeTimers()
  })
  afterEach(() => { vi.useRealTimers() })

  it('returns null when its markup is absent, rather than throwing', () => {
    document.body.innerHTML = ''
    expect(initMdWeldControls({ api: {}, getWeldOverlay: () => makeOverlay() })).toBeNull()
  })

  it('does nothing until the checkbox is ticked', async () => {
    const overlay = makeOverlay()
    const c = initMdWeldControls({ api: {}, getWeldOverlay: () => overlay })
    c.setJob('job-a')
    await vi.runOnlyPendingTimersAsync()
    expect(overlay.loadForJob).not.toHaveBeenCalled()
  })

  // The overlay used to be persisted in localStorage, which made the control look like it
  // switched ITSELF on: a stored `true` re-checked the box at boot and setJob() re-applied
  // it to the next job selected — but the markers are drawn from inside the atomistic
  // renderer, so nothing appeared until the user switched to a heavy representation. From
  // the user's seat, "changing the representation turned on weld pair".
  describe('is opt-in per session (never self-arms)', () => {
    it('ignores a stale persisted preference', async () => {
      try { localStorage.setItem('nadoc:md:weldPair', 'true') } catch { /* private mode */ }
      const overlay = makeOverlay()
      const c = initMdWeldControls({ api: {}, getWeldOverlay: () => overlay })
      expect(els().toggle.checked).toBe(false)
      c.setJob('job-a')
      await vi.runOnlyPendingTimersAsync()
      expect(overlay.loadForJob).not.toHaveBeenCalled()
      expect(overlay.setVisible).not.toHaveBeenCalledWith(true)
    })

    it('does not write the preference when ticked', async () => {
      const overlay = makeOverlay()
      const c = initMdWeldControls({ api: {}, getWeldOverlay: () => overlay })
      c.setJob('job-a')
      els().toggle.checked = true
      els().toggle.dispatchEvent(new Event('change'))
      await vi.runOnlyPendingTimersAsync()
      expect(overlay.loadForJob).toHaveBeenCalled()          // it DID turn on for this session…
      expect(localStorage.getItem('nadoc:md:weldPair')).toBeNull()   // …but left no trace
    })

    // Following the job WITHIN a session is correct and not surprising: the user ticked it.
    it('still follows a job change while ticked in this session', async () => {
      const overlay = makeOverlay()
      const c = initMdWeldControls({ api: {}, getWeldOverlay: () => overlay })
      c.setJob('job-a')
      els().toggle.checked = true
      els().toggle.dispatchEvent(new Event('change'))
      await vi.runOnlyPendingTimersAsync()
      overlay.loadForJob.mockClear()
      c.setJob('job-b')
      await vi.runOnlyPendingTimersAsync()
      expect(overlay.loadForJob).toHaveBeenCalledWith({}, 'job-b')
    })
  })

  it('asks the user to select a job when ticked with none', async () => {
    const overlay = makeOverlay()
    const c = initMdWeldControls({ api: {}, getWeldOverlay: () => overlay })
    els().toggle.checked = true
    els().toggle.dispatchEvent(new Event('change'))
    await vi.runOnlyPendingTimersAsync()
    expect(els().status.textContent).toBe('select a job first')
    expect(overlay.loadForJob).not.toHaveBeenCalled()
    void c
  })

  it('loads pairs and reports the count once a job is selected', async () => {
    const overlay = makeOverlay()
    const api = {}
    const c = initMdWeldControls({ api, getWeldOverlay: () => overlay })
    c.setJob('job-a')
    els().toggle.checked = true
    els().toggle.dispatchEvent(new Event('change'))
    await vi.runOnlyPendingTimersAsync()
    expect(overlay.loadForJob).toHaveBeenCalledWith(api, 'job-a')
    expect(els().status.textContent).toBe('1 weld pair')
  })

  it('says so plainly, in a warning colour, when the design has no weld pair', async () => {
    const overlay = makeOverlay([])
    overlay.loadForJob.mockResolvedValue({ ready: true, pairs: [], reason: null })
    const c = initMdWeldControls({ api: {}, getWeldOverlay: () => overlay })
    c.setJob('job-a')
    els().toggle.checked = true
    els().toggle.dispatchEvent(new Event('change'))
    await vi.runOnlyPendingTimersAsync()
    expect(els().status.textContent).toBe('no weld pair in this design')
    expect(els().status.style.color).not.toBe('')
    expect(els().readout.style.display).toBe('none')
  })

  it('ticks a live readout while pairs are shown', async () => {
    const overlay = makeOverlay()
    const c = initMdWeldControls({ api: {}, getWeldOverlay: () => overlay })
    c.setJob('job-a')
    els().toggle.checked = true
    els().toggle.dispatchEvent(new Event('change'))
    await vi.runOnlyPendingTimersAsync()
    await vi.advanceTimersByTimeAsync(300)
    expect(els().readout.style.display).toBe('')
    expect(els().readout.textContent).toContain('3.40 Å')
  })

  it('hides the overlay and stops ticking when unticked', async () => {
    const overlay = makeOverlay()
    const c = initMdWeldControls({ api: {}, getWeldOverlay: () => overlay })
    c.setJob('job-a')
    els().toggle.checked = true
    els().toggle.dispatchEvent(new Event('change'))
    await vi.runOnlyPendingTimersAsync()

    els().toggle.checked = false
    els().toggle.dispatchEvent(new Event('change'))
    await vi.runOnlyPendingTimersAsync()
    expect(overlay.setVisible).toHaveBeenCalledWith(false)
    expect(els().readout.style.display).toBe('none')
  })

  it('clears the previous job pairs when the selection changes', async () => {
    const overlay = makeOverlay()
    const c = initMdWeldControls({ api: {}, getWeldOverlay: () => overlay })
    c.setJob('job-a')
    els().toggle.checked = true
    els().toggle.dispatchEvent(new Event('change'))
    await vi.runOnlyPendingTimersAsync()

    c.setJob('job-b')
    await vi.runOnlyPendingTimersAsync()
    expect(overlay.setPairs).toHaveBeenCalledWith([])
    expect(overlay.loadForJob).toHaveBeenLastCalledWith({}, 'job-b')
  })

  it('ignores a re-selection of the same job', async () => {
    const overlay = makeOverlay()
    const c = initMdWeldControls({ api: {}, getWeldOverlay: () => overlay })
    c.setJob('job-a')
    els().toggle.checked = true
    els().toggle.dispatchEvent(new Event('change'))
    await vi.runOnlyPendingTimersAsync()
    const calls = overlay.loadForJob.mock.calls.length
    c.setJob('job-a')
    await vi.runOnlyPendingTimersAsync()
    expect(overlay.loadForJob.mock.calls.length).toBe(calls)
  })

  it('surfaces a load failure instead of leaving a stale status', async () => {
    const overlay = makeOverlay()
    overlay.loadForJob.mockRejectedValue(new Error('boom'))
    const c = initMdWeldControls({ api: {}, getWeldOverlay: () => overlay })
    c.setJob('job-a')
    els().toggle.checked = true
    els().toggle.dispatchEvent(new Event('change'))
    await vi.runOnlyPendingTimersAsync()
    expect(els().status.textContent).toBe('boom')
  })

  // SUPERSEDED 2026-08-01. This used to assert the opposite — that the checkbox state
  // survived a rebuild, via localStorage. That persistence is exactly what made the
  // control appear to switch itself on (see the "opt-in per session" block above), so the
  // intent was reversed on user report. Kept as an explicit pin of the NEW behaviour
  // rather than deleted, so nobody re-adds the key thinking it was an oversight.
  it('does NOT remember the checkbox state across a rebuild', async () => {
    const overlay = makeOverlay()
    const c1 = initMdWeldControls({ api: {}, getWeldOverlay: () => overlay })
    c1.setJob('job-a')
    els().toggle.checked = true
    els().toggle.dispatchEvent(new Event('change'))
    await vi.runOnlyPendingTimersAsync()

    document.body.innerHTML = MARKUP
    initMdWeldControls({ api: {}, getWeldOverlay: () => overlay })
    expect(els().toggle.checked).toBe(false)
  })

  it('reports when the atomistic view is unavailable', async () => {
    const c = initMdWeldControls({ api: {}, getWeldOverlay: () => null })
    c.setJob('job-a')
    els().toggle.checked = true
    els().toggle.dispatchEvent(new Event('change'))
    await vi.runOnlyPendingTimersAsync()
    expect(els().status.textContent).toBe('atomistic view not available')
  })
})
