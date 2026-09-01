/**
 * md_health_tiles.test.js — why a Health tile is blank.
 *
 * The bug this pins: the card used to draw a spinner for ANY missing value on an active
 * job, so a metric that would never arrive (old sample, disabled probe, failed probe)
 * spun forever and told the user it was still computing. Every case below is a value
 * that is absent for a reason OTHER than "in flight", and none of them may be PENDING.
 */
import { describe, it, expect } from 'vitest'
import {
  mdHealthTileState, mdHealthTileStates, hasValue, TILE_STATE, DEFAULT_PROBE_INTERVAL_S,
} from './md_health_tiles.js'

const NOW = 1_800_000_000_000          // fixed clock; nothing here may read Date.now()
const NOW_S = NOW / 1000

/** A local job mid-production, with a probe that just sampled successfully. */
function runningJob(over = {}) {
  return {
    status: 'running',
    created_at: NOW_S - 3600,
    execution_target: 'local',
    current_segment_idx: 0,
    segments: [{ name: 'seg1', stage: '310K NPT production', status: 'running' }],
    health_probe: { enabled: true, interval_s: 300, last_at: NOW_S - 10, last_error: null, reason: null },
    ...over,
  }
}

const ctx = (over = {}) => ({
  job: runningJob(), health: null, probe: runningJob().health_probe,
  active: true, nowMs: NOW, ...over,
})

describe('hasValue', () => {
  it('treats 0 as a real reading, not an absence', () => {
    // Zero remains a legitimate scalar reading — it must never mean "no data".
    expect(hasValue(0)).toBe(true)
    expect(hasValue(0.0)).toBe(true)
    expect(hasValue(null)).toBe(false)
    expect(hasValue(undefined)).toBe(false)
    expect(hasValue(NaN)).toBe(false)
  })
})

describe('mdHealthTileState — a present value always wins', () => {
  it('classifies any non-null raw as VALUE regardless of probe state', () => {
    const s = mdHealthTileState('energy', -199108, ctx({
      probe: { enabled: false, reason: 'disabled' },
    }))
    expect(s.state).toBe(TILE_STATE.VALUE)
    expect(s.reason).toBe(null)
  })
})

describe('mdHealthTileState — nothing is running', () => {
  it('a finished run that never measured a metric is UNAVAILABLE, not pending', () => {
    const s = mdHealthTileState('basePairs', null, ctx({ active: false }))
    expect(s.state).toBe(TILE_STATE.UNAVAILABLE)
    expect(s.reason).toMatch(/not measured/i)
  })

  it('applies to log-derived tiles too', () => {
    expect(mdHealthTileState('temp', null, ctx({ active: false })).state)
      .toBe(TILE_STATE.UNAVAILABLE)
  })
})

describe('mdHealthTileState — the probe will never run', () => {
  it('a disabled probe is UNAVAILABLE and surfaces its reason', () => {
    const s = mdHealthTileState('basePairs', null, ctx({
      probe: { enabled: false, reason: 'adopted after an orchestrator restart' },
    }))
    expect(s.state).toBe(TILE_STATE.UNAVAILABLE)
    expect(s.reason).toMatch(/adopted after an orchestrator restart/)
  })

  it('still shows a spinner for the LOG-derived tiles, which do not need the probe', () => {
    // Temp/Pressure/Speed/Energy are parsed from the NAMD log independently
    // of the runner's health probe — that asymmetry is the original symptom.
    const s = mdHealthTileState('temp', null, ctx({ probe: { enabled: false, reason: 'x' } }))
    expect(s.state).toBe(TILE_STATE.PENDING)
  })
})

describe('mdHealthTileState — the probe failed', () => {
  it('reports FAILED with the error rather than hiding it behind a spinner', () => {
    const s = mdHealthTileState('wcHealth', null, ctx({
      probe: { enabled: true, interval_s: 300, last_at: NOW_S - 10, last_error: 'PSF or PDB not found' },
    }))
    expect(s.state).toBe(TILE_STATE.FAILED)
    expect(s.reason).toMatch(/PSF or PDB not found/)
  })
})

describe('mdHealthTileState — per-frame diagnostics provenance', () => {
  it('an OLD sample (diagnostics absent) is UNAVAILABLE — the regression that mattered', () => {
    // Samples written before the field existed round-trip through MdHealthSample(**h)
    // as diagnostics: null. They must read "—", never spin.
    const s = mdHealthTileState('shellCharge', null, ctx({ health: { stage: 'x' } }))
    expect(s.state).toBe(TILE_STATE.UNAVAILABLE)
    expect(s.reason).toMatch(/not recorded/i)
  })

  it('a captured diagnostics error is FAILED with that text', () => {
    const s = mdHealthTileState('shellCharge', null, ctx({
      health: { stage: 'x', diagnostics: 'frame 812: truncated DCD' },
    }))
    expect(s.state).toBe(TILE_STATE.FAILED)
    expect(s.reason).toMatch(/truncated DCD/)
  })

  it('diagnostics=ok with a null value means measured-as-none, not pending', () => {
    const s = mdHealthTileState('shellCharge', null, ctx({
      health: { stage: 'x', diagnostics: 'ok' },
    }))
    expect(s.state).toBe(TILE_STATE.UNAVAILABLE)
    expect(s.reason).toMatch(/measured as none/i)
  })
})

describe('mdHealthTileState — the overdue watchdogs', () => {
  it('a probe that stopped reporting is FAILED', () => {
    const s = mdHealthTileState('basePairs', null, ctx({
      probe: { enabled: true, interval_s: 300, started_at: NOW_S - 7200,
               last_tick_at: NOW_S - 3600, last_at: NOW_S - 3600, last_error: null },
    }))
    expect(s.state).toBe(TILE_STATE.FAILED)
    expect(s.reason).toMatch(/stopped reporting/i)
  })

  it('stays PENDING inside the grace window', () => {
    const s = mdHealthTileState('basePairs', null, ctx({
      probe: { enabled: true, interval_s: 300, started_at: NOW_S - 400,
               last_tick_at: NOW_S - 100, last_at: NOW_S - 100, last_error: null },
    }))
    expect(s.state).toBe(TILE_STATE.PENDING)
  })

  it('THE RESUME BUG: a live probe on an hours-old job is PENDING, not FAILED', () => {
    // A resumed run is old but its probe is seconds old. Anchoring staleness on
    // job.created_at made every resume paint failed tiles the instant it came back —
    // and the honest state is "measuring shortly", with the probe's own note.
    const resumed = runningJob({ created_at: NOW_S - 12.8 * 3600 })
    const s = mdHealthTileState('basePairs', null, ctx({
      job: resumed,
      probe: { enabled: true, interval_s: 300, started_at: NOW_S - 240,
               last_tick_at: NOW_S - 30, last_at: null, last_error: null,
               reason: 'waiting for the first trajectory frames' },
    }))
    expect(s.state).toBe(TILE_STATE.PENDING)
    expect(s.reason).toMatch(/waiting for the first trajectory frames/)
  })

  it('a probe ticking for ages with no sample ever is eventually FAILED', () => {
    const s = mdHealthTileState('basePairs', null, ctx({
      probe: { enabled: true, interval_s: 300, started_at: NOW_S - 20 * 300,
               last_tick_at: NOW_S - 10, last_at: null, last_error: null,
               reason: 'waiting for the first trajectory frames' },
    }))
    expect(s.state).toBe(TILE_STATE.FAILED)
    expect(s.reason).toMatch(/no health sample in/i)
    expect(s.reason).toMatch(/waiting for the first trajectory frames/)
  })

  it('the first sample needs several frames, so a few minutes of nothing is normal', () => {
    // safe_back+1 frames at a production dcdFreq (one frame per ~100 ps) is minutes of
    // wall-clock. A 2-interval bound here would fail a perfectly healthy run.
    const s = mdHealthTileState('basePairs', null, ctx({
      probe: { enabled: true, interval_s: 300, started_at: NOW_S - 3 * 300,
               last_tick_at: NOW_S - 20, last_at: null, last_error: null },
    }))
    expect(s.state).toBe(TILE_STATE.PENDING)
  })

  it('no probe at all: PENDING while young, UNAVAILABLE once that is implausible', () => {
    const justStarted = runningJob({ created_at: NOW_S - 5, health_probe: null })
    expect(mdHealthTileState('basePairs', null, ctx({ job: justStarted, probe: null })).state)
      .toBe(TILE_STATE.PENDING)

    const old = runningJob({ created_at: NOW_S - 50 * DEFAULT_PROBE_INTERVAL_S, health_probe: null })
    const s = mdHealthTileState('basePairs', null, ctx({ job: old, probe: null }))
    expect(s.state).toBe(TILE_STATE.UNAVAILABLE)
    expect(s.reason).toMatch(/has not reported/i)
  })
})

describe('mdHealthTileStates — the whole card', () => {
  it('reproduces the reported bug shape: log tiles have values, health tiles do not', () => {
    // Temp/Pressure/Speed populate from live_metrics while the runner samples nothing —
    // this is exactly what the user saw, and the health-derived tiles must not spin.
    const job = runningJob({
      health_probe: { enabled: false, reason: 'adopted after an orchestrator restart' },
    })
    const states = mdHealthTileStates({
      job,
      health: null,
      raws: {
        temp: 310.2, pressure: 1.01, speed: 42.7, energy: -199108,
        basePairs: null, wcHealth: null, latest: '500ns production',
        shellCharge: null,
      },
      nowMs: NOW,
    })
    expect(states.temp.state).toBe(TILE_STATE.VALUE)
    expect(states.pressure.state).toBe(TILE_STATE.VALUE)
    expect(states.speed.state).toBe(TILE_STATE.VALUE)
    expect(states.energy.state).toBe(TILE_STATE.VALUE)
    expect(states.latest.state).toBe(TILE_STATE.VALUE)
    for (const k of ['basePairs', 'wcHealth', 'shellCharge']) {
      expect(states[k].state).toBe(TILE_STATE.UNAVAILABLE)
      expect(states[k].reason).toBeTruthy()
    }
    // The invariant: nothing on this card claims to be computing.
    expect(Object.values(states).some(s => s.state === TILE_STATE.PENDING)).toBe(false)
  })

  it('reads the probe off the job when not passed explicitly', () => {
    const states = mdHealthTileStates({
      job: runningJob({ health_probe: { enabled: false, reason: 'sampling disabled' } }),
      health: null,
      raws: { basePairs: null },
      nowMs: NOW,
    })
    expect(states.basePairs.reason).toMatch(/sampling disabled/)
  })

  it('a healthy live run keeps its un-arrived health tiles PENDING', () => {
    const states = mdHealthTileStates({
      job: runningJob(),
      health: null,
      raws: { temp: 300, basePairs: null, wcHealth: null },
      nowMs: NOW,
    })
    expect(states.basePairs.state).toBe(TILE_STATE.PENDING)
    expect(states.wcHealth.state).toBe(TILE_STATE.PENDING)
  })
})
