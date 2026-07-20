import { describe, it, expect } from 'vitest'
import {
  dirLabel, formatField, formatSurface, metaTags, lineageForJob,
  buildExportModel, buildJobRows, runJobsOf, segmentTooltip, clampRange,
  frameToPct, pctToFrame, segmentsSpanned, rangeSummary,
  runBoundaries, snapValue, chimeraxOpenCommand,
  exportPhaseLabel, exportProgressView,
} from './oxdna_export_card.js'

// A stub runConfigForJob: reads test-friendly fields off the job.
const stubRC = (job) => ({
  advanced: job.parent_job_id ? null : { mcSteps: 1000, mdSteps: 500, equilSteps: 2000 },
  field: job.field ?? null,
  surface: job.surface ?? null,
  surfaceStrands: job.surfaceStrands ?? null,
  anchors: job.anchors ?? [],
})

const prodStage = (frames) => ({ kind: 'production', n_frames: frames })

describe('dirLabel', () => {
  it('picks the dominant signed axis of a vector', () => {
    expect(dirLabel([0, 0, 1])).toBe('+Z')
    expect(dirLabel([0, 0, -3])).toBe('-Z')
    expect(dirLabel([-2, 0.1, 0])).toBe('-X')
  })
  it('passes a string direction through', () => {
    expect(dirLabel('+z')).toBe('+z')
    expect(dirLabel(null)).toBe('?')
  })
})

describe('formatField / formatSurface', () => {
  it('formats an E-field record', () => {
    expect(formatField({ field_pN: 12, dir: [0, 0, 1] })).toBe('12 pN/nt, +Z')
    expect(formatField(null)).toBe('—')
  })
  it('formats a hard-surface record and notes capture strands', () => {
    expect(formatSurface({ dir: [0, 0, 1], offset_nm: 2 })).toBe('hard wall +Z, offset 2 nm')
    expect(formatSurface({ dir: [0, 0, 1], offset_nm: 2 }, [1, 2, 3])).toContain('3 capture strands')
    expect(formatSurface(null)).toBe('—')
  })
})

describe('metaTags', () => {
  it('emits [A][H][E] only for present elements', () => {
    expect(metaTags({ anchors: [1, 2], surface: {}, field: {} })).toBe('[A][H][E]')
    expect(metaTags({ anchors: [], surface: {}, field: null })).toBe('[H]')
    expect(metaTags(null)).toBe('')
  })
})

describe('lineageForJob', () => {
  // star: two runs branch directly off one root
  const star = [
    { job_id: 'p1', created_at: 1 },
    { job_id: 'c1', parent_job_id: 'p1', created_at: 2 },
    { job_id: 'c2', parent_job_id: 'p1', created_at: 3 },
    { job_id: 'other', created_at: 9 },
  ]
  // chain: r1 ← r2 ← r3 ← r4 (each run's parent is the previous run)
  const chain = [
    { job_id: 'r1', created_at: 1 },
    { job_id: 'r2', parent_job_id: 'r1', created_at: 2 },
    { job_id: 'r3', parent_job_id: 'r2', created_at: 3 },
    { job_id: 'r4', parent_job_id: 'r3', created_at: 4 },
  ]
  it('ancestor chain: selecting the root gives just the root', () => {
    expect(lineageForJob({ job_id: 'p1', created_at: 1 }, star).map((j) => j.job_id)).toEqual(['p1'])
  })
  it('ancestor chain: a star child resolves to [root, child] only (siblings excluded)', () => {
    expect(lineageForJob(star[2], star).map((j) => j.job_id)).toEqual(['p1', 'c2'])
  })
  it('includes every run LEADING UP TO a deep selection (run 4 → runs 1-4)', () => {
    expect(lineageForJob(chain[3], chain).map((j) => j.job_id)).toEqual(['r1', 'r2', 'r3', 'r4'])
  })
  it('excludes runs AFTER the selected one (select r2 → [r1, r2], not r3/r4)', () => {
    expect(lineageForJob(chain[1], chain).map((j) => j.job_id)).toEqual(['r1', 'r2'])
  })
  it('returns [] for no job', () => {
    expect(lineageForJob(null, star)).toEqual([])
  })
})

describe('runJobsOf', () => {
  it('lists lineage jobs that contribute a run stage, skipping a relax-only root', () => {
    const lineage = [
      { job_id: 'root', stages: [{ kind: 'mc' }, { kind: 'equil' }] },   // relaxation only
      { job_id: 'run1', stages: [{ kind: 'production' }] },
      { job_id: 'run2', stages: [{ kind: 'production' }] },
    ]
    expect(runJobsOf(lineage).map((j) => j.job_id)).toEqual(['run1', 'run2'])
  })
})

describe('buildExportModel (from composite meta stages)', () => {
  // lineage: root carries relaxation + its own production; one child run
  const lineage = [
    { job_id: 'p1', status: 'completed', stages: [{ kind: 'mc' }, { kind: 'equil' }, { kind: 'production' }], anchors: [1, 2] },
    { job_id: 'c1', parent_job_id: 'p1', status: 'running', stages: [{ kind: 'production' }] },
  ]
  it('lays meta relaxation stages then runs into contiguous frame spans', () => {
    const metaStages = [
      { kind: 'mc', n_frames: 5 }, { kind: 'equil', n_frames: 10 },
      { kind: 'production', n_frames: 100, field: null },
      { kind: 'production', n_frames: 200, field: { field_pN: 12, dir: [0, 0, 1] } },
    ]
    const m = buildExportModel(metaStages, lineage, stubRC)
    expect(m.unit).toBe('frame')
    expect(m.total).toBe(315)
    expect(m.segments.map((s) => s.label)).toEqual(['MC min', 'Equilibrate', 'Run 1', 'Run 2'])
    expect(m.segments.map((s) => [s.start, s.end])).toEqual([[0, 5], [5, 15], [15, 115], [115, 315]])
    expect(m.segments[0].meta).toBeNull()
    expect(m.segments[2].jobId).toBe('p1')           // Run 1 ← root
    expect(m.segments[2].meta.anchors).toEqual([1, 2])
    expect(m.segments[3].jobId).toBe('c1')           // Run 2 ← child
    expect(m.segments[3].meta.field).toEqual({ field_pN: 12, dir: [0, 0, 1] })   // from the meta stage
  })
  it('maps runs correctly when the root is relaxation-only (runs come from children)', () => {
    const relaxRoot = [
      { job_id: 'root', stages: [{ kind: 'mc' }, { kind: 'equil' }] },
      { job_id: 'runA', stages: [{ kind: 'production' }], anchors: [9] },
      { job_id: 'runB', stages: [{ kind: 'production' }] },
    ]
    const metaStages = [
      { kind: 'mc', n_frames: 5 }, { kind: 'equil', n_frames: 5 },
      { kind: 'production', n_frames: 50 }, { kind: 'production', n_frames: 60 },
    ]
    const m = buildExportModel(metaStages, relaxRoot, stubRC)
    expect(m.segments[2].jobId).toBe('runA')         // first run ← runA, not the relax-only root
    expect(m.segments[2].meta.anchors).toEqual([9])
    expect(m.segments[3].jobId).toBe('runB')
  })
  it('is empty (total 0) for no meta stages', () => {
    expect(buildExportModel([], lineage, stubRC).total).toBe(0)
  })
})

describe('buildJobRows', () => {
  it('produces a row per lineage job with tags + summary', () => {
    const lineage = [
      { job_id: 'parent01', status: 'completed', stages: [prodStage(100)], surface: { dir: [0, 0, 1], offset_nm: 2 }, anchors: [1, 2] },
      { job_id: 'child001', parent_job_id: 'parent01', status: 'running', stages: [prodStage(50)], field: { field_pN: 8, dir: [0, 1, 0] } },
    ]
    const rows = buildJobRows(lineage, stubRC)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({ runLabel: 'Run 1', isChild: false, tags: '[A][H]', status: 'completed' })
    expect(rows[0].relax).toContain('MC 1,000')
    expect(rows[1]).toMatchObject({ runLabel: 'Run 2', isChild: true, tags: '[E]' })
    expect(rows[1].relax).toBeNull()
  })
})

describe('segmentTooltip', () => {
  it('lists count, anchors, surface and field for a production run', () => {
    const seg = { kind: 'production', label: 'Run 2', weight: 200, meta: { anchors: [1, 2, 3], surface: { dir: [0, 0, 1], offset_nm: 2 }, field: { field_pN: 12, dir: [0, 0, 1] } } }
    const t = segmentTooltip(seg, 'frame')
    expect(t).toContain('Run 2 — production run · 200 frames')
    expect(t).toContain('Anchors: 3')
    expect(t).toContain('Surface: hard wall +Z')
    expect(t).toContain('E-field: 12 pN/nt, +Z')
  })
  it('notes when a run has none of the three elements', () => {
    const seg = { kind: 'production', label: 'Run 1', weight: 100, meta: { anchors: [], surface: null, field: null } }
    expect(segmentTooltip(seg)).toContain('No anchors / surface / E-field')
  })
  it('marks relaxation segments as not-normally-exported', () => {
    const seg = { kind: 'mc', label: 'MC min', weight: 5, meta: null }
    expect(segmentTooltip(seg)).toContain('Relaxation stage')
  })
})

describe('range math', () => {
  it('clampRange orders and bounds', () => {
    expect(clampRange(900, 100, 500)).toEqual({ lo: 100, hi: 500 })
    expect(clampRange(-5, 50, 300)).toEqual({ lo: 0, hi: 50 })
  })
  it('frameToPct / pctToFrame round-trip', () => {
    expect(frameToPct(50, 200)).toBe(25)
    expect(pctToFrame(25, 200)).toBe(50)
    expect(frameToPct(5, 0)).toBe(0)   // no divide-by-zero
  })
  it('segmentsSpanned returns half-open intersections', () => {
    const segs = [{ label: 'a', start: 0, end: 100 }, { label: 'b', start: 100, end: 300 }]
    expect(segmentsSpanned(segs, 50, 150).map((s) => s.label)).toEqual(['a', 'b'])
    expect(segmentsSpanned(segs, 120, 200).map((s) => s.label)).toEqual(['b'])
  })
})

describe('rangeSummary', () => {
  const model = {
    unit: 'frame', total: 315,
    segments: [
      { kind: 'mc', label: 'MC min', start: 0, end: 15 },
      { kind: 'production', label: 'Run 1', start: 15, end: 115 },
      { kind: 'production', label: 'Run 2', start: 115, end: 315 },
    ],
  }
  it('names the production runs the range spans', () => {
    expect(rangeSummary(model, 50, 200)).toBe('Frames 50–200 · 150 of 315 · spans Run 1, Run 2')
  })
  it('handles the empty model', () => {
    expect(rangeSummary({ unit: 'frame', total: 0, segments: [] }, 0, 0)).toContain('No production frames')
  })
})

describe('runBoundaries / snapValue (snap to run starts/ends)', () => {
  const model = {
    total: 315,
    segments: [
      { kind: 'mc', start: 0, end: 15 },
      { kind: 'production', start: 15, end: 115 },
      { kind: 'production', start: 115, end: 315 },
    ],
  }
  it('collects every run/stage start+end plus 0 and total, sorted & unique', () => {
    expect(runBoundaries(model)).toEqual([0, 15, 115, 315])
  })
  it('snaps a value that lands near a boundary', () => {
    const b = runBoundaries(model)
    expect(snapValue(118, b, 10)).toBe(115)   // within threshold → snaps to run start
    expect(snapValue(310, b, 10)).toBe(315)   // near the end → snaps to total
  })
  it('leaves a value free when no boundary is within threshold', () => {
    const b = runBoundaries(model)
    expect(snapValue(200, b, 10)).toBe(200)   // mid-run, far from any boundary
  })
  it('picks the nearest boundary when two are in range', () => {
    expect(snapValue(20, [0, 15, 115, 315], 30)).toBe(15)
  })
})

describe('chimeraxOpenCommand (Direct-to-ChimeraX popup command)', () => {
  it('loads the exported PDB as a trajectory with the frame player', () => {
    expect(chimeraxOpenCommand('VoltronCore_frames_0-4.pdb'))
      .toBe('open "VoltronCore_frames_0-4.pdb" coordsets true slider true')
  })
  it('emits an obvious editable placeholder when no filename is known', () => {
    expect(chimeraxOpenCommand(null)).toBe('open "PATH_TO_YOUR_EXPORT.pdb" coordsets true slider true')
    expect(chimeraxOpenCommand('')).toContain('PATH_TO_YOUR_EXPORT.pdb')
  })
  it('quotes the name and escapes an embedded quote so paste survives', () => {
    expect(chimeraxOpenCommand('a b/x".pdb')).toBe('open "a b/x\\".pdb" coordsets true slider true')
  })
})

describe('exportPhaseLabel / exportProgressView (live export bar)', () => {
  it('labels the two backend phases and falls back for anything else', () => {
    expect(exportPhaseLabel('align')).toBe('Aligning frames')
    expect(exportPhaseLabel('write')).toBe('Writing PDB')
    expect(exportPhaseLabel(undefined)).toBe('Building')
  })
  it('computes pct + label from a progress payload', () => {
    expect(exportProgressView({ done: 45, total: 200, phase: 'align' }))
      .toEqual({ pct: 23, text: 'Aligning frames — 45/200 frames · 23%' })
    expect(exportProgressView({ done: 120, total: 120, phase: 'write' }))
      .toEqual({ pct: 100, text: 'Writing PDB — 120/120 frames · 100%' })
  })
  it('clamps and handles a zero/empty total gracefully', () => {
    expect(exportProgressView({ done: 0, total: 0 })).toEqual({ pct: 0, text: 'Preparing…' })
    expect(exportProgressView(null)).toEqual({ pct: 0, text: 'Preparing…' })
    expect(exportProgressView({ done: 999, total: 100, phase: 'write' }).pct).toBe(100)
  })
})
