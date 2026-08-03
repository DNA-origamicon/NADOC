/**
 * export_progress — the phase-weighted export bar.
 *
 * The behaviour under test is a UX guarantee, not an algorithm: during the
 * longest workflow NADOC has (VoltronCoreScad + a full-resolution oxDNA
 * trajectory keyframe + surface representation + silhouettes + shadows → GIF)
 * the user must never see a bar that has stopped moving with no explanation.
 * So the assertions are about COVERAGE and CONTINUITY:
 *
 *   - every subprocess owns a slice and reports into it
 *   - the fraction only ever goes forward
 *   - no window of wall-clock passes without the status text changing
 *   - the phases a run cannot have are removed, not silently skipped mid-bar
 */

import { describe, it, expect, vi } from 'vitest'
import {
  PHASE_ORDER, PHASE_WEIGHTS, planExportPhases, createExportProgress,
  createExportSession, bakeEventPhase, phaseStatusText, elapsedText,
} from './export_progress.js'

// ── planExportPhases ─────────────────────────────────────────────────────────

describe('planExportPhases', () => {
  it('normalises weights to exactly 1 for every combination', () => {
    for (const hasTrajectory of [false, true]) {
      for (const hasHeavyFrames of [false, true]) {
        const sum = planExportPhases({ hasTrajectory, hasHeavyFrames })
          .reduce((s, p) => s + p.weight, 0)
        expect(sum).toBeCloseTo(1, 10)
      }
    }
  })

  it('keeps the canonical order and never invents a phase', () => {
    const keys = planExportPhases({ hasTrajectory: true, hasHeavyFrames: true }).map(p => p.key)
    expect(keys).toEqual(PHASE_ORDER)
  })

  it('drops both trajectory phases when the animation has no trajectory keyframe', () => {
    const keys = planExportPhases({ hasTrajectory: false }).map(p => p.key)
    expect(keys).not.toContain('traj_load')
    expect(keys).not.toContain('traj_frames')
    // …and still covers the rest end to end.
    expect(keys).toEqual(['prepare', 'geometry', 'session', 'capture', 'encode', 'save'])
  })

  it('drops only the heavy prebuild when a trajectory plays in a bead representation', () => {
    // oxdna_display.prebuildHeavy() returns immediately for kind 'cg', so that
    // phase would report nothing at all and its slice would be dead weight.
    const keys = planExportPhases({ hasTrajectory: true, hasHeavyFrames: false }).map(p => p.key)
    expect(keys).toContain('traj_load')
    expect(keys).not.toContain('traj_frames')
  })

  it('names the encode phase after the container the user picked', () => {
    const gif  = planExportPhases({ format: 'gif' }).find(p => p.key === 'encode')
    const webm = planExportPhases({ format: 'webm' }).find(p => p.key === 'encode')
    expect(gif.label).toBe('Encoding GIF')
    expect(webm.label).toBe('Encoding WebM')
  })

  it('gives the full workflow no phase worth more than half the bar', () => {
    // A single phase owning most of the range is the failure this replaced —
    // "Rendering frames" used to be the whole bar with everything before it at 0.
    for (const p of planExportPhases({ hasTrajectory: true, hasHeavyFrames: true })) {
      expect(p.weight).toBeLessThan(0.5)
    }
  })
})

// ── createExportProgress ─────────────────────────────────────────────────────

/** Recorder around a progress accumulator with a controllable clock. */
function harness(spec = { hasTrajectory: true, hasHeavyFrames: true, format: 'gif' }, opts = {}) {
  const updates = []
  let t = 0
  const prog = createExportProgress({
    phases: planExportPhases(spec),
    now: () => t,
    onUpdate: (u) => updates.push(u),
    ...opts,
  })
  return { prog, updates, advance: (ms) => { t += ms }, at: () => t }
}

describe('createExportProgress', () => {
  it('starts at zero and ends at exactly 1', () => {
    const { prog, updates } = harness()
    prog.begin('prepare')
    expect(updates[0].fraction).toBe(0)
    prog.finish()
    expect(updates.at(-1).fraction).toBe(1)
    expect(updates.at(-1).text).toBe('Done')
  })

  it('each phase completing advances the bar by its own weight share', () => {
    const { prog } = harness()
    const phases = prog.phases
    let expected = 0
    for (const p of phases) {
      prog.setFraction(p.key, 1)
      expected += p.weight
      expect(prog.snapshot().fraction).toBeCloseTo(expected, 10)
    }
  })

  it('is monotonic even when events arrive out of order', () => {
    const { prog, updates } = harness()
    prog.tick('capture', 50, 100)
    prog.tick('geometry', 1, 4)     // a late tick from a phase already passed
    prog.begin('prepare')           // and a stale begin
    prog.tick('capture', 90, 100)
    const fracs = updates.map(u => u.fraction)
    for (let i = 1; i < fracs.length; i++) expect(fracs[i]).toBeGreaterThanOrEqual(fracs[i - 1])
  })

  it('credits every skipped phase when a later one begins, so the bar never sticks', () => {
    // The real case: the user exports with no trajectory loaded into the plan by
    // mistake, or a phase completes with zero work. The bar must jump forward.
    const { prog } = harness()
    prog.begin('prepare')
    const before = prog.snapshot().fraction
    prog.begin('capture')
    const after = prog.snapshot().fraction
    expect(after).toBeGreaterThan(before)
    // …to exactly the cumulative weight of everything before 'capture'.
    const cum = prog.phases
      .slice(0, prog.phases.findIndex(p => p.key === 'capture'))
      .reduce((s, p) => s + p.weight, 0)
    expect(after).toBeCloseTo(cum, 10)
  })

  it('reports interior progress within a phase rather than only its endpoints', () => {
    const { prog, updates } = harness()
    prog.begin('capture')
    const start = prog.snapshot().fraction
    for (let i = 1; i <= 10; i++) prog.tick('capture', i, 10)
    const seen = updates.filter(u => u.key === 'capture').map(u => u.fraction)
    // Strictly increasing across the phase, not a single jump at the end.
    expect(seen.length).toBeGreaterThan(10)
    expect(new Set(seen).size).toBeGreaterThan(10)
    expect(seen.at(-1)).toBeGreaterThan(start)
  })

  it('always emits a status naming the running subprocess', () => {
    const { prog, updates } = harness()
    for (const p of prog.phases) prog.tick(p.key, 1, 2)
    for (const u of updates) {
      expect(u.text).toMatch(/^Step \d+\/\d+ · \S/)
      expect(u.text).toContain(u.label)
      expect(u.label.length).toBeGreaterThan(0)
    }
  })

  it('covers every phase label across a full run — no anonymous work', () => {
    const { prog, updates } = harness()
    for (const p of prog.phases) prog.begin(p.key)
    const labelled = new Set(updates.map(u => u.key))
    expect([...labelled].sort()).toEqual(prog.phases.map(p => p.key).sort())
  })

  it('clamps a phase fraction to its own slice — a phase cannot overrun the next', () => {
    const { prog } = harness()
    prog.tick('geometry', 999, 4)
    const cumThrough = prog.phases
      .slice(0, prog.phases.findIndex(p => p.key === 'geometry') + 1)
      .reduce((s, p) => s + p.weight, 0)
    expect(prog.snapshot().fraction).toBeCloseTo(cumThrough, 10)
  })

  it('tolerates a phase that cannot count (total 0) without moving backwards', () => {
    const { prog } = harness()
    prog.tick('traj_load', 0, 0)
    expect(prog.snapshot().fraction).toBeGreaterThanOrEqual(0)
    expect(prog.snapshot().key).toBe('traj_load')
  })

  it('ignores phases that are not in this run\'s plan', () => {
    const { prog } = harness({ hasTrajectory: false })
    expect(prog.begin('traj_load')).toBe(false)
    expect(prog.tick('traj_frames', 1, 2)).toBe(false)
  })
})

// ── The stall guarantee ──────────────────────────────────────────────────────

describe('stall heartbeat — the "is it hung?" guard', () => {
  it('stays quiet while a phase is actively reporting', () => {
    const { prog, updates, advance } = harness(undefined, { stallMs: 2500 })
    prog.begin('capture')
    advance(1000)
    const n = updates.length
    expect(prog.heartbeat()).toBe(false)
    expect(updates.length).toBe(n)
  })

  it('re-emits with an elapsed tail once a phase has gone quiet', () => {
    const { prog, updates, advance } = harness(undefined, { stallMs: 2500 })
    prog.begin('traj_load')
    advance(9000)
    expect(prog.heartbeat()).toBe(true)
    expect(updates.at(-1).text).toContain('still working')
    expect(updates.at(-1).text).toContain('0:09')
  })

  it('keeps the elapsed tail growing so the text never repeats during a long await', () => {
    // The trajectory download is ONE await that returns only at the end. Without a
    // growing tail the status is byte-identical for minutes, which reads as frozen.
    const { prog, updates, advance } = harness(undefined, { stallMs: 2500 })
    prog.begin('traj_load')
    const texts = []
    for (let i = 0; i < 8; i++) { advance(3000); prog.heartbeat(); texts.push(updates.at(-1).text) }
    expect(new Set(texts).size).toBe(texts.length)
  })

  it('a heartbeat never advances the bar — it explains, it does not fake progress', () => {
    const { prog, advance } = harness(undefined, { stallMs: 1000 })
    prog.tick('capture', 3, 10)
    const f = prog.snapshot().fraction
    advance(60_000)
    prog.heartbeat()
    expect(prog.snapshot().fraction).toBe(f)
  })

  it('warns, on the phases that really do freeze the tab, once they go quiet', () => {
    // Measured live: parsing the ~50 MB trajectory response body blocks the main
    // thread for 7–18 s, during which no timer fires — not even the heartbeat. The
    // freeze cannot be shortened from here, so it gets ANNOUNCED before it happens.
    const { prog, updates, advance } = harness(undefined, { stallMs: 2500 })
    prog.begin('traj_load')
    advance(4000); prog.heartbeat()
    expect(updates.at(-1).text).toContain('may stop responding')
    prog.begin('capture')
    advance(4000); prog.heartbeat()
    expect(updates.at(-1).text).not.toContain('may stop responding')
  })

  it('does not warn before the phase has gone quiet', () => {
    const { prog, updates } = harness()
    prog.tick('traj_load', 3, 251)
    expect(updates.at(-1).text).not.toContain('may stop responding')
  })

  it('a real tick resets the idle clock, so the tail disappears again', () => {
    const { prog, updates, advance } = harness(undefined, { stallMs: 2500 })
    prog.begin('traj_frames')
    advance(5000); prog.heartbeat()
    expect(updates.at(-1).text).toContain('still working')
    prog.tick('traj_frames', 1, 251)
    expect(updates.at(-1).text).not.toContain('still working')
  })
})

describe('elapsedText / phaseStatusText', () => {
  it('formats mm:ss', () => {
    expect(elapsedText(0)).toBe('0:00')
    expect(elapsedText(9_000)).toBe('0:09')
    expect(elapsedText(95_000)).toBe('1:35')
    expect(elapsedText(-5)).toBe('0:00')
  })

  it('adds the count only when the phase can count', () => {
    const base = { label: 'Rendering frames', phaseIndex: 5, phaseCount: 8 }
    expect(phaseStatusText({ ...base, done: 12, total: 251 }))
      .toBe('Step 6/8 · Rendering frames 12 of 251')
    expect(phaseStatusText({ ...base })).toBe('Step 6/8 · Rendering frames')
    expect(phaseStatusText({ ...base, done: 3, total: 0 })).toBe('Step 6/8 · Rendering frames')
  })
})

// ── bake-event routing ───────────────────────────────────────────────────────

describe('bakeEventPhase', () => {
  it('routes the player\'s tagged stages', () => {
    expect(bakeEventPhase({ type: 'baking_progress', stage: 'geometry' })).toBe('geometry')
    expect(bakeEventPhase({ type: 'baking_progress', stage: 'traj_load' })).toBe('traj_load')
    expect(bakeEventPhase({ type: 'baking_progress', stage: 'traj_frames' })).toBe('traj_frames')
  })

  it('falls back to the human label when a stage tag is missing', () => {
    expect(bakeEventPhase({ type: 'baking_progress', label: 'Loading trajectory…' })).toBe('traj_load')
    expect(bakeEventPhase({ type: 'baking_progress', label: 'Preparing trajectory frames 3 of 9' }))
      .toBe('traj_frames')
  })

  it('defaults an untagged bake tick to the geometry phase rather than dropping it', () => {
    expect(bakeEventPhase({ type: 'baking' })).toBe('geometry')
    expect(bakeEventPhase({ type: 'baking_progress', done: 1, total: 2 })).toBe('geometry')
    expect(bakeEventPhase({ type: 'tick' })).toBe(null)
    expect(bakeEventPhase(null)).toBe(null)
  })
})

// ── createExportSession ──────────────────────────────────────────────────────

function fakeUi() {
  return {
    show: vi.fn(), hide: vi.fn(), label: vi.fn(), fraction: vi.fn(),
    texts() { return this.label.mock.calls.map(c => c[1]) },
    fractions() { return this.fraction.mock.calls.map(c => c[0]) },
  }
}
function fakeTimer() {
  const fns = []
  return {
    fns,
    set: vi.fn((fn) => { fns.push(fn); return fns.length - 1 }),
    clear: vi.fn(),
    beat() { for (const fn of fns) fn() },
  }
}

describe('createExportSession', () => {
  const spec = { hasTrajectory: true, hasHeavyFrames: true, format: 'gif' }

  it('opens the popup once with the export\'s own header and cancel handler', () => {
    const ui = fakeUi()
    const onCancel = vi.fn()
    createExportSession({ header: 'Exporting Video', phases: planExportPhases(spec), ui, timer: fakeTimer(), onCancel })
    expect(ui.show).toHaveBeenCalledTimes(1)
    expect(ui.show.mock.calls[0][0]).toBe('Exporting Video')
    expect(ui.show.mock.calls[0][2].onCancel).toBe(onCancel)
  })

  it('drives the bar and the label from bake events the panel used to drop', () => {
    const ui = fakeUi()
    const s = createExportSession({ header: 'x', phases: planExportPhases(spec), ui, timer: fakeTimer() })
    s.handleBakeEvent({ type: 'baking', stage: 'geometry', hasSlow: true })
    s.handleBakeEvent({ type: 'baking_progress', stage: 'geometry', done: 2, total: 4 })
    s.handleBakeEvent({ type: 'baking_progress', stage: 'traj_load', done: 120, total: 251 })
    s.handleBakeEvent({ type: 'baking_progress', stage: 'traj_frames', done: 30, total: 251 })
    const texts = ui.texts()
    expect(texts.some(t => t.includes('Fetching model geometry'))).toBe(true)
    expect(texts.some(t => t.includes('Downloading trajectory 120 of 251'))).toBe(true)
    expect(texts.some(t => t.includes('Building trajectory frames 30 of 251'))).toBe(true)
    const fr = ui.fractions()
    for (let i = 1; i < fr.length; i++) expect(fr[i]).toBeGreaterThanOrEqual(fr[i - 1])
  })

  it('ignores bake events for phases this run does not have', () => {
    const ui = fakeUi()
    const s = createExportSession({
      header: 'x', phases: planExportPhases({ hasTrajectory: false }), ui, timer: fakeTimer(),
    })
    expect(s.handleBakeEvent({ type: 'baking_progress', stage: 'traj_load', done: 1, total: 2 })).toBe(false)
  })

  it('registers a heartbeat timer and clears it on end', () => {
    const ui = fakeUi(); const timer = fakeTimer()
    const s = createExportSession({ header: 'x', phases: planExportPhases(spec), ui, timer })
    expect(timer.set).toHaveBeenCalledTimes(1)
    s.end()
    expect(timer.clear).toHaveBeenCalledTimes(1)
    expect(ui.hide).toHaveBeenCalledTimes(1)
  })

  it('the heartbeat keeps the label alive through an opaque phase', () => {
    const ui = fakeUi(); const timer = fakeTimer()
    let t = 0
    const s = createExportSession({
      header: 'x', phases: planExportPhases(spec), ui, timer,
      now: () => t, stallMs: 2000,
    })
    s.begin('traj_load')
    const before = ui.texts().length
    t += 30_000
    timer.beat()
    expect(ui.texts().length).toBeGreaterThan(before)
    expect(ui.texts().at(-1)).toContain('0:30')
  })

  it('end() is idempotent — the popup ref-count cannot be over-decremented', () => {
    const ui = fakeUi()
    const s = createExportSession({ header: 'x', phases: planExportPhases(spec), ui, timer: fakeTimer() })
    s.end(); s.end(); s.end()
    expect(ui.hide).toHaveBeenCalledTimes(1)
  })
})

// ── The whole workflow, end to end ───────────────────────────────────────────

/**
 * Replay the exact event stream the VoltronCoreScad / oxDNA-run-17 / surface /
 * silhouette+shadow / GIF export produces, and assert the user-facing guarantee:
 * the bar is never quiet and never still without saying why.
 */
function replayFullWorkflow({ trajectoryHeld = false, heartbeatEveryMs = 1000 } = {}) {
  const ui = fakeUi(); const timer = fakeTimer()
  let t = 0
  const TRAJ_FRAMES = 251        // run 17, scope='job': 250 written + 1 seed
  const CAPTURE     = 300        // 10 s at 30 fps

  const s = createExportSession({
    header: 'Exporting Video',
    phases: planExportPhases({ hasTrajectory: true, hasHeavyFrames: true, format: 'gif' }),
    ui, timer, now: () => t, stallMs: 2500, heartbeatMs: heartbeatEveryMs,
  })

  const log = []          // [{ ms, text, fraction }]
  const record = () => {
    log.push({ ms: t, text: ui.texts().at(-1), fraction: ui.fractions().at(-1) })
  }
  /** Advance the clock, firing the heartbeat on its interval as the browser would. */
  const wait = (ms) => {
    for (let e = 0; e < ms; e += heartbeatEveryMs) {
      t += heartbeatEveryMs
      timer.beat()
      record()
    }
  }

  s.begin('prepare');                                              record()
  // ── player.play() → bake ───────────────────────────────────────────────────
  s.handleBakeEvent({ type: 'baking', stage: 'geometry', hasSlow: true }); record()
  for (let i = 1; i <= 6; i++) {
    wait(400)
    s.handleBakeEvent({ type: 'baking_progress', stage: 'geometry', done: i, total: 6 }); record()
  }
  if (!trajectoryHeld) {
    // Cold: the 1 GB composite trajectory is parsed + aligned + shipped. The
    // backend's frames-processed counter is polled through it.
    s.handleBakeEvent({ type: 'baking_progress', stage: 'traj_load', done: 0, total: 0 }); record()
    for (let f = 25; f <= TRAJ_FRAMES; f += 25) {
      wait(4000)
      s.handleBakeEvent({ type: 'baking_progress', stage: 'traj_load', done: f, total: TRAJ_FRAMES }); record()
    }
  } else {
    // Warm: the jobs panel is already scrubbing this job, so _loadInto's reuse
    // path skips the download entirely and the phase reports only its close.
    s.handleBakeEvent({ type: 'baking_progress', stage: 'traj_load', done: TRAJ_FRAMES, total: TRAJ_FRAMES })
    record()
  }
  for (let f = 10; f <= TRAJ_FRAMES; f += 10) {
    wait(2000)
    s.handleBakeEvent({ type: 'baking_progress', stage: 'traj_frames', done: f, total: TRAJ_FRAMES }); record()
  }
  // ── beginFrameSession: probe GL, shadow map, RenderPass/FigurePass/SMAA ─────
  s.begin('session'); record()
  wait(3000)
  // ── per-frame tiled render + quantize ──────────────────────────────────────
  for (let i = 0; i <= CAPTURE; i++) {
    wait(1000)
    s.tick('capture', i, CAPTURE); record()
  }
  // ── gif.finish() byte concat, then the Blob + download ─────────────────────
  s.begin('encode'); record()
  wait(20_000)
  s.begin('save'); record()
  wait(2000)
  s.finish(); record()

  return { log, session: s, phases: s.phases }
}

describe('full VoltronCoreScad trajectory → surface → GIF export', () => {
  it('every phase in the plan produces at least one status the user can read', () => {
    const { log, phases } = replayFullWorkflow()
    for (const p of phases) {
      expect(log.some(e => e.text?.includes(p.label)),
        `no status line ever mentioned "${p.label}"`).toBe(true)
    }
  })

  it('the bar never goes backwards', () => {
    const { log } = replayFullWorkflow()
    const fr = log.map(e => e.fraction)
    for (let i = 1; i < fr.length; i++) expect(fr[i]).toBeGreaterThanOrEqual(fr[i - 1])
  })

  it('reaches exactly 100% and only at the end', () => {
    const { log } = replayFullWorkflow()
    expect(log.at(-1).fraction).toBe(1)
    expect(log.slice(0, -1).every(e => e.fraction < 1)).toBe(true)
  })

  it('the status text is never unchanged for more than 5 s of wall-clock', () => {
    // THE headline guarantee. Anything longer and the user concludes NADOC has
    // hung and hits Cancel — throwing away the trajectory download that is the
    // single most expensive part of the run.
    const { log } = replayFullWorkflow()
    let lastChangeMs = log[0].ms
    let lastText = log[0].text
    let worst = 0
    for (const e of log) {
      if (e.text !== lastText) { worst = Math.max(worst, e.ms - lastChangeMs); lastChangeMs = e.ms; lastText = e.text }
    }
    worst = Math.max(worst, log.at(-1).ms - lastChangeMs)
    expect(worst).toBeLessThanOrEqual(5000)
  })

  it('no phase silently owns more than 45% of the elapsed run without moving the bar', () => {
    // A phase can legitimately be long; what it may not do is be long AND flat.
    const { log } = replayFullWorkflow()
    let flatStart = log[0]
    let worst = 0
    for (const e of log) {
      if (e.fraction > flatStart.fraction) { worst = Math.max(worst, e.ms - flatStart.ms); flatStart = e }
    }
    worst = Math.max(worst, log.at(-1).ms - flatStart.ms)
    const totalMs = log.at(-1).ms - log[0].ms
    expect(worst / totalMs).toBeLessThan(0.45)
  })

  it('behaves identically whether the model starts on a loaded frame or native positions', () => {
    // trajectoryHeld=true is the "user was already scrubbing run 17 in the
    // Simulations tab" case: _loadInto's reuse path skips the download. The phase
    // set, the ordering and the 100% endpoint must not change — only the timing.
    const cold = replayFullWorkflow({ trajectoryHeld: false })
    const warm = replayFullWorkflow({ trajectoryHeld: true })

    const phaseOrder = (r) => {
      const seen = []
      for (const p of r.phases) if (r.log.some(e => e.text?.includes(p.label))) seen.push(p.key)
      return seen
    }
    expect(phaseOrder(warm)).toEqual(phaseOrder(cold))
    expect(warm.log.at(-1).fraction).toBe(1)
    const fr = warm.log.map(e => e.fraction)
    for (let i = 1; i < fr.length; i++) expect(fr[i]).toBeGreaterThanOrEqual(fr[i - 1])
  })

  it('a held trajectory still shows the download phase rather than skipping past it', () => {
    // Even the instant case must name the step — a bar that leaps 15% with no
    // explanation is its own kind of confusing.
    const { log } = replayFullWorkflow({ trajectoryHeld: true })
    expect(log.some(e => e.text?.includes('Downloading trajectory'))).toBe(true)
  })
})
