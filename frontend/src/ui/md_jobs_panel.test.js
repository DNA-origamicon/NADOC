import { describe, it, expect } from 'vitest'
import { normalizeWorkspacePath, filterJobsForPart, seededBadge } from './md_jobs_panel.js'

describe('seededBadge', () => {
  it('labels oxDNA- and mrDNA-seeded jobs and nothing else', () => {
    expect(seededBadge({ seed_oxdna_job_id: 'abc123' })).toBe('oxDNA seeded')
    expect(seededBadge({ seed_mrdna_job_id: 'def456' })).toBe('mrDNA seeded')
    expect(seededBadge({ seed_oxdna_job_id: null })).toBe('')
    expect(seededBadge({})).toBe('')
    expect(seededBadge(null)).toBe('')
  })
})

describe('normalizeWorkspacePath', () => {
  it('returns empty string for null/undefined/empty', () => {
    expect(normalizeWorkspacePath(null)).toBe('')
    expect(normalizeWorkspacePath(undefined)).toBe('')
    expect(normalizeWorkspacePath('')).toBe('')
  })

  it('converts backslashes to forward slashes', () => {
    expect(normalizeWorkspacePath('a\\b\\c.nadoc')).toBe('a/b/c.nadoc')
  })

  it('strips trailing slashes', () => {
    expect(normalizeWorkspacePath('foo/bar/')).toBe('foo/bar')
    expect(normalizeWorkspacePath('foo/bar///')).toBe('foo/bar')
  })
})

describe('filterJobsForPart', () => {
  const jobs = [
    { job_id: 'a', design_source_path: '18hb.nadoc' },
    { job_id: 'b', design_source_path: '6hb_84bp.nadoc' },
    { job_id: 'c', design_source_path: null },
    { job_id: 'd', design_source_path: '18hb.nadoc' },
  ]

  it('shows only jobs matching the active part path', () => {
    const out = filterJobsForPart(jobs, '18hb.nadoc', false)
    expect(out.map(j => j.job_id)).toEqual(['a', 'd'])
  })

  it('shows nothing when no part path is known (no leaking other designs)', () => {
    expect(filterJobsForPart(jobs, null, false)).toEqual([])
    expect(filterJobsForPart(jobs, '', false)).toEqual([])
  })

  it('never matches jobs with a null source path under a real part', () => {
    const out = filterJobsForPart(jobs, '18hb.nadoc', false)
    expect(out.some(j => j.job_id === 'c')).toBe(false)
  })

  it('normalizes both sides before comparing', () => {
    const winJobs = [{ job_id: 'x', design_source_path: 'sub\\18hb.nadoc' }]
    expect(filterJobsForPart(winJobs, 'sub/18hb.nadoc/', false).map(j => j.job_id)).toEqual(['x'])
  })

  it('showAll returns every job unfiltered', () => {
    expect(filterJobsForPart(jobs, '18hb.nadoc', true)).toEqual(jobs)
    expect(filterJobsForPart(jobs, null, true)).toEqual(jobs)
  })
})

import { mdJobIsActive, makeSpinner, mdHasMetrics, mdListSignature, mdChildRowLabel } from './md_jobs_panel.js'

describe('mdChildRowLabel', () => {
  it('labels a derived child by its global run number', () => {
    expect(mdChildRowLabel({ job_id: 'x' }, 1)).toBe('Refit 1')
    expect(mdChildRowLabel({ job_id: 'y' }, 3)).toBe('Refit 3')
  })
})

describe('mdJobIsActive', () => {
  it('is true for in-progress statuses, false otherwise', () => {
    for (const s of ['queued', 'preparing', 'running']) {
      expect(mdJobIsActive({ status: s })).toBe(true)
    }
    for (const s of ['completed', 'failed', 'stopped']) {
      expect(mdJobIsActive({ status: s })).toBe(false)
    }
    expect(mdJobIsActive(null)).toBe(false)
  })
})

describe('makeSpinner', () => {
  it('builds a .nadoc-spinner span sized + colored', () => {
    const s = makeSpinner('#e3b341', 10)
    expect(s.className).toBe('nadoc-spinner')
    expect(s.style.width).toBe('10px')
    expect(s.style.height).toBe('10px')
    expect(s.getAttribute('aria-hidden')).toBe('true')
  })
})

describe('mdHasMetrics', () => {
  it('detects health samples, live temperature, or a persisted metric', () => {
    expect(mdHasMetrics({ health_samples: [{ stage: 'x' }] })).toBe(true)
    expect(mdHasMetrics({ live_metrics: { temperature_k: 301 } })).toBe(true)
    expect(mdHasMetrics({}, { ns_per_day: 12 })).toBe(true)
    expect(mdHasMetrics({}, null)).toBe(false)
    expect(mdHasMetrics({ live_metrics: { temperature_k: null } }, null)).toBe(false)
  })
})

describe('mdListSignature', () => {
  it('changes on status, segment, selection; stable otherwise', () => {
    const jobs = [{ job_id: 'a', status: 'running', current_segment_idx: 1 }]
    const base = mdListSignature(jobs, 'a')
    expect(mdListSignature(jobs, 'a')).toBe(base)                                   // stable
    expect(mdListSignature([{ ...jobs[0], status: 'completed' }], 'a')).not.toBe(base)
    expect(mdListSignature([{ ...jobs[0], current_segment_idx: 2 }], 'a')).not.toBe(base)
    expect(mdListSignature(jobs, 'b')).not.toBe(base)                               // selection
  })
})

import { mdShouldShowInheritedSeed } from './md_jobs_panel.js'

describe('mdShouldShowInheritedSeed', () => {
  it('true only when oxDNA-seeded AND no MD frame written yet', () => {
    // seeded + no MD trajectory → show inherited oxDNA-seed positions
    expect(mdShouldShowInheritedSeed({ seed_oxdna_job_id: 'ox1' }, { ready: false })).toBe(true)
    expect(mdShouldShowInheritedSeed({ seed_oxdna_job_id: 'ox1' }, null)).toBe(true)
    expect(mdShouldShowInheritedSeed({ seed_oxdna_job_id: 'ox1' }, {})).toBe(true)
    // seeded but MD already has a frame → MD positions take over
    expect(mdShouldShowInheritedSeed({ seed_oxdna_job_id: 'ox1' }, { ready: true })).toBe(false)
    // not seeded → never inherited
    expect(mdShouldShowInheritedSeed({ seed_oxdna_job_id: null }, { ready: false })).toBe(false)
    expect(mdShouldShowInheritedSeed({}, { ready: false })).toBe(false)
    expect(mdShouldShowInheritedSeed(null, null)).toBe(false)
  })
})

import { fastPhaseSpeedNote, FAST_PHASE_SPEEDUP } from './md_jobs_panel.js'

describe('fastPhaseSpeedNote', () => {
  const fastJob = (idx) => ({ prep_params: { fast: true }, current_segment_idx: idx })

  it('flags the slow strain-relief first segment of a fast job', () => {
    const note = fastPhaseSpeedNote(fastJob(0), 1.7)
    expect(note).not.toBeNull()
    expect(note.asterisk).toBe(true)
    expect(note.tooltip).toContain(`~${Math.round(1.7 * FAST_PHASE_SPEEDUP)} ns/day`)
    expect(note.tooltip).toMatch(/GPU-resident/)
  })

  it('returns null once past segment 0 (production speed is real)', () => {
    expect(fastPhaseSpeedNote(fastJob(1), 16)).toBeNull()
  })

  it('returns null for non-fast jobs', () => {
    expect(fastPhaseSpeedNote({ prep_params: { fast: false }, current_segment_idx: 0 }, 3.8)).toBeNull()
    expect(fastPhaseSpeedNote({ current_segment_idx: 0 }, 3.8)).toBeNull()
    expect(fastPhaseSpeedNote(null, 3.8)).toBeNull()
  })

  it('omits the estimate when speed is not yet known', () => {
    const note = fastPhaseSpeedNote(fastJob(0), null)
    expect(note.asterisk).toBe(true)
    expect(note.tooltip).not.toMatch(/ns\/day,/)   // no "~N ns/day," estimate clause
  })
})
