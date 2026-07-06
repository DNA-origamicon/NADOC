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

import { mdJobIsActive, mdRemoteAwaitingSubmit, makeSpinner, mdHasMetrics, mdListSignature, mdChildRowLabel, hasActiveRemoteJob } from './md_jobs_panel.js'

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
  it('is NOT active for an Alpine job queued but never submitted to SLURM', () => {
    // The failed-submit / never-submitted case: shows no running spinner.
    expect(mdJobIsActive({ status: 'queued', execution_target: 'alpine' })).toBe(false)
    expect(mdJobIsActive({ status: 'queued', execution_target: 'alpine', error: 'Cluster submission failed: x' })).toBe(false)
  })
  it('IS active once the Alpine job has a SLURM id (on the cluster)', () => {
    expect(mdJobIsActive({ status: 'queued', execution_target: 'alpine', slurm_job_id: '123' })).toBe(true)
    expect(mdJobIsActive({ status: 'running', execution_target: 'alpine', slurm_job_id: '123' })).toBe(true)
  })
  it('local jobs are unaffected (queued = active)', () => {
    expect(mdJobIsActive({ status: 'queued', execution_target: 'local' })).toBe(true)
  })
})

describe('hasActiveRemoteJob (gates the remote-poll timer)', () => {
  it('true only when a submitted Alpine job is in flight', () => {
    expect(hasActiveRemoteJob([{ status: 'running', execution_target: 'alpine', slurm_job_id: '9' }])).toBe(true)
    expect(hasActiveRemoteJob([{ status: 'queued', execution_target: 'alpine', slurm_job_id: '9' }])).toBe(true)
  })
  it('false for local, terminal, or not-yet-submitted remote jobs', () => {
    expect(hasActiveRemoteJob([{ status: 'running', execution_target: 'local' }])).toBe(false)
    expect(hasActiveRemoteJob([{ status: 'completed', execution_target: 'alpine', slurm_job_id: '9' }])).toBe(false)
    expect(hasActiveRemoteJob([{ status: 'queued', execution_target: 'alpine' }])).toBe(false)  // awaiting submit
    expect(hasActiveRemoteJob([])).toBe(false)
    expect(hasActiveRemoteJob(null)).toBe(false)
  })
})

describe('mdRemoteAwaitingSubmit', () => {
  it('is true only for an Alpine, queued, no-slurm-id job', () => {
    expect(mdRemoteAwaitingSubmit({ status: 'queued', execution_target: 'alpine' })).toBe(true)
  })
  it('is false once submitted, for local jobs, or non-queued states', () => {
    expect(mdRemoteAwaitingSubmit({ status: 'queued', execution_target: 'alpine', slurm_job_id: '9' })).toBe(false)
    expect(mdRemoteAwaitingSubmit({ status: 'queued', execution_target: 'local' })).toBe(false)
    expect(mdRemoteAwaitingSubmit({ status: 'running', execution_target: 'alpine' })).toBe(false)
    expect(mdRemoteAwaitingSubmit(null)).toBe(false)
  })
})

import { mdDetailErrorText } from './md_jobs_panel.js'

describe('mdDetailErrorText', () => {
  it('shows nothing for a clean user-stop (no error)', () => {
    expect(mdDetailErrorText({ status: 'stopped' })).toBe(null)
    expect(mdDetailErrorText({ status: 'stopped', error: null })).toBe(null)
  })
  it('shows the error for a stopped job that carries one (raced a real failure / legacy)', () => {
    expect(mdDetailErrorText({ status: 'stopped', error: 'disk full' })).toBe('disk full')
  })
  it('shows Unknown error only for a failed job with no message', () => {
    expect(mdDetailErrorText({ status: 'failed' })).toBe('Unknown error')
    expect(mdDetailErrorText({ status: 'failed', error: 'boom' })).toBe('boom')
  })
  it('shows a failed Alpine submit and a resumable timed-out job', () => {
    expect(mdDetailErrorText({ status: 'queued', execution_target: 'alpine', error: 'rejected' })).toBe('rejected')
    expect(mdDetailErrorText({ status: 'stopped', resumable: true, error: 'click Resume' })).toBe('click Resume')
  })
  it('hides the box for live / non-terminal jobs', () => {
    expect(mdDetailErrorText({ status: 'running' })).toBe(null)
    expect(mdDetailErrorText({ status: 'preparing' })).toBe(null)
    expect(mdDetailErrorText({ status: 'completed' })).toBe(null)
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

import { mdResumeButtonState, mdResumeHistoryRows } from './md_jobs_panel.js'

describe('mdResumeButtonState (one-click Resume for a timed-out remote job)', () => {
  it('hidden for a non-resumable or non-alpine job', () => {
    expect(mdResumeButtonState({ execution_target: 'alpine', resumable: false }, 'connected').show).toBe(false)
    expect(mdResumeButtonState({ execution_target: 'local', resumable: true }, 'connected').show).toBe(false)
  })
  it('shown+enabled only when connected', () => {
    const j = { execution_target: 'alpine', resumable: true }
    expect(mdResumeButtonState(j, 'connected')).toMatchObject({ show: true, disabled: false })
    const off = mdResumeButtonState(j, 'disconnected')
    expect(off.show).toBe(true)
    expect(off.disabled).toBe(true)
    expect(off.reason).toMatch(/Duo/)
  })
})

describe('mdResumeHistoryRows (expand-chevron content)', () => {
  it('formats newest-first with numbering', () => {
    const job = { resume_history: [
      { slurm_job_id: '100', state: 'TIMEOUT', segment_reached: 2, segments_total: 12, walltime: '1:00:00' },
      { slurm_job_id: '200', state: 'TIMEOUT', segment_reached: 5, segments_total: 12, walltime: '1:00:00' },
    ] }
    const rows = mdResumeHistoryRows(job)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toContain('#2')            // newest first
    expect(rows[0]).toContain('SLURM 200')
    expect(rows[0]).toContain('seg 5/12')
    expect(rows[1]).toContain('#1')
  })
  it('empty for no history', () => {
    expect(mdResumeHistoryRows({})).toEqual([])
    expect(mdResumeHistoryRows(null)).toEqual([])
  })
})

import { mdIsRemoteQueued, mdQueueWaitLabel, fmtDurationShort } from './md_jobs_panel.js'

describe('mdIsRemoteQueued (SLURM PENDING, not running / not awaiting-submit)', () => {
  it('true for a submitted alpine job that is queued and not yet running', () => {
    expect(mdIsRemoteQueued({ execution_target: 'alpine', status: 'queued', slurm_job_id: '9', slurm_state: 'PENDING' })).toBe(true)
    expect(mdIsRemoteQueued({ execution_target: 'alpine', status: 'queued', slurm_job_id: '9' })).toBe(true)
  })
  it('false for awaiting-submit (no slurm id), running, or local', () => {
    expect(mdIsRemoteQueued({ execution_target: 'alpine', status: 'queued' })).toBe(false)          // no slurm id
    expect(mdIsRemoteQueued({ execution_target: 'alpine', status: 'queued', slurm_job_id: '9', slurm_state: 'RUNNING' })).toBe(false)
    expect(mdIsRemoteQueued({ execution_target: 'alpine', status: 'running', slurm_job_id: '9' })).toBe(false)
    expect(mdIsRemoteQueued({ execution_target: 'local', status: 'queued', slurm_job_id: '9' })).toBe(false)
  })
})

describe('fmtDurationShort', () => {
  it('formats seconds/minutes/hours compactly', () => {
    expect(fmtDurationShort(45)).toBe('45s')
    expect(fmtDurationShort(6 * 60)).toBe('6m')
    expect(fmtDurationShort(3 * 3600 + 4 * 60)).toBe('3h 4m')
    expect(fmtDurationShort(-5)).toBe('0s')
  })
})

describe('mdQueueWaitLabel', () => {
  it('reports elapsed time since queued_at', () => {
    const now = 1000000
    const job = { queued_at: now - 300 }        // 5 min ago
    expect(mdQueueWaitLabel(job, now * 1000)).toMatch(/Queued 5m ago/)
  })
  it('falls back when queued_at is missing', () => {
    expect(mdQueueWaitLabel({})).toMatch(/waiting for the cluster scheduler/)
  })
})
