import { describe, it, expect, vi, beforeEach } from 'vitest'

// Keep the heavy oxDNA panel out of the unit test — the master card only uses a few pure
// label fns from it + dispatches to the panels.
vi.mock('./oxdna_jobs_panel.js', () => ({
  relaxIndexMap: (jobs) => new Map((jobs || []).map((j, i) => [j.job_id, i + 1])),
  relaxRowLabel: (j, n) => (n ? `relax ${n}` : j.design_name || 'design'),
  runRowLabel: (j, i) => `Run ${i}`,
  runChildTitle: () => 'child run',
}))
vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
// Light stand-ins for the other engines' label fns / row ctx (the unified list only uses
// these to render their rows; the real panels are heavy).
vi.mock('./mrdna_jobs_panel.js', () => ({ jobDisplayName: (j) => j.design_name || 'mr' }))
vi.mock('./cando_jobs_panel.js', () => ({ jobDisplayName: (j) => j.design_name || 'cd' }))
vi.mock('./md_jobs_panel.js', () => ({
  mdJobRowCtx: () => ({
    displayName: (j) => j.design_name || 'md',
    childLabel: (j, i) => `Refit ${i}`,
    childTitle: () => 'md child',
    postLabelMarkers: () => [],
    symbolOverride: () => null,
  }),
}))

import {
  initSimulateJobs, nodeIsActive, nodeNeedsPolling, nodeIsResumable, verbForNode,
  masterProgressPct, masterProgressColor, masterProgressTooltip, masterStatusText, nodeDetailText, formatEta,
  masterStepText,
} from './simulate_jobs.js'

// ── pure helpers ──────────────────────────────────────────────────────────────

const oxNode = (o = {}) => ({ engine: 'oxdna', job_id: 'ox1', parent_job_id: null,
  created_at: 1, status: 'completed', production_state: 'none', kind: 'relax',
  n_units: 100, design_name: 'D', stages: [], viewable: false, ...o })
const lmNode = (o = {}) => ({ engine: 'lammps', job_id: 'lm1', parent_job_id: null,
  created_at: 2, status: 'completed', production_state: null, kind: 'lammps',
  n_units: 200, design_name: 'D', ranks: 6, frames: 5, viewable: true, steps: 1000,
  current_step: 1000, ...o })

describe('pure helpers', () => {
  it('nodeNeedsPolling excludes a job that was created but never started', () => {
    // `＋ New job → Create job` leaves a solvated package at `queued` waiting for the
    // user. It is "active" for spinner purposes but its state cannot change on its own,
    // so polling it every 1.5 s forever is pure waste.
    expect(nodeNeedsPolling(oxNode({ status: 'queued' }))).toBe(false)
    expect(nodeIsActive(oxNode({ status: 'queued' }))).toBe(true)   // still shows as pending
  })
  it('nodeNeedsPolling keeps polling a SUBMITTED remote job — its scheduler moves it', () => {
    expect(nodeNeedsPolling(oxNode({ status: 'queued', slurm_job_id: '9' }))).toBe(true)
    expect(nodeNeedsPolling(oxNode({ status: 'queued', runpod_pod_id: 'p' }))).toBe(true)
  })
  it('nodeNeedsPolling follows a job that is actually executing', () => {
    expect(nodeNeedsPolling(oxNode({ status: 'running' }))).toBe(true)
    expect(nodeNeedsPolling(oxNode({ status: 'preparing' }))).toBe(true)
    expect(nodeNeedsPolling(oxNode({ status: 'completed' }))).toBe(false)
  })
  it('nodeIsActive tracks the shared status vocab', () => {
    expect(nodeIsActive(lmNode({ status: 'running' }))).toBe(true)
    expect(nodeIsActive(oxNode({ status: 'completed' }))).toBe(false)
  })
  it('only a stopped/failed oxDNA node is resumable (never LAMMPS)', () => {
    expect(nodeIsResumable(oxNode({ status: 'stopped' }))).toBe(true)
    expect(nodeIsResumable(oxNode({ status: 'failed' }))).toBe(true)
    expect(nodeIsResumable(lmNode({ status: 'stopped' }))).toBe(false)
    expect(nodeIsResumable(oxNode({ status: 'completed' }))).toBe(false)
  })
  it('verbForNode: null/relax → Relax; run child / LAMMPS → Run', () => {
    expect(verbForNode(null)).toBe('Relax')
    expect(verbForNode(oxNode({ kind: 'relax' }))).toBe('Relax')
    expect(verbForNode(oxNode({ kind: 'run' }))).toBe('Run')
    expect(verbForNode(lmNode())).toBe('Run')
  })
  it('masterProgressPct: completed→100; LAMMPS steps / oxDNA stages / NAMD segments while running', () => {
    expect(masterProgressPct(lmNode({ status: 'running', current_step: 500, steps: 1000 }))).toBe(50)
    expect(masterProgressPct(oxNode({ status: 'running', stages: [{ status: 'done' }, { status: 'running' }] }))).toBe(50)
    expect(masterProgressPct({ engine: 'namd', status: 'running', segments: [{ status: 'done' }, { status: 'done' }, { status: 'running' }, { status: 'pending' }] })).toBe(50)
    expect(masterProgressPct(lmNode({ status: 'completed' }))).toBe(100)   // completed → full
    expect(masterProgressPct(null)).toBe(0)
  })
  it('masterProgressPct: a running oxDNA job uses the backend live fraction (single-stage run)', () => {
    // A single-stage e-field/surface run: stage-count alone reads 0 (0 of 1 done) — the
    // backend-stamped progress_fraction must win so the bar advances.
    expect(masterProgressPct(oxNode({
      status: 'running', progress_fraction: 0.73, stages: [{ status: 'running' }],
    }))).toBe(73)
    // Falls back to completed-stage count when the backend didn't stamp a fraction.
    expect(masterProgressPct(oxNode({
      status: 'running', stages: [{ status: 'done' }, { status: 'running' }],
    }))).toBe(50)
  })
  it('masterProgressColor: green done · red failed · orange stale · grey stopped · blue active', () => {
    expect(masterProgressColor(oxNode({ status: 'completed' }))).toBe('#5cb85c')
    expect(masterProgressColor(oxNode({ status: 'failed' }))).toBe('#d9534f')
    expect(masterProgressColor(oxNode({ status: 'running', out_of_date: true }))).toBe('#e0a800')  // warning
    expect(masterProgressColor(oxNode({ status: 'stopped' }))).toBe('#8a8a8a')
    expect(masterProgressColor(oxNode({ status: 'running' }))).toBe('#4a9eff')
  })
  it('masterProgressTooltip: NAMD lists segments + current stage; stale adds a ⚠', () => {
    const t = masterProgressTooltip({ engine: 'namd', status: 'running',
      segments: [{ status: 'done' }, { status: 'running', name: 'heat', percent: 40 }], out_of_date: true })
    expect(t).toMatch(/NAMD · running/)
    expect(t).toMatch(/1\/2 segments · 50% overall/)
    expect(t).toMatch(/Current: heat · 40%/)
    expect(t).toMatch(/⚠ design changed/)
  })
  it('masterProgressTooltip: names the minimisation, which sits outside the segment count', () => {
    // Minimisation runs before segment 1 and is not one of them, so the bar is honestly
    // at 0 % — the tooltip has to say what is running or the job reads as hung.
    const t = masterProgressTooltip({ engine: 'namd', status: 'running',
      minimization: { name: 'B_00_min', stage: 'Minimization ENM k=0.5', steps: 9600, status: 'running' },
      segments: [{ status: 'pending' }, { status: 'pending' }] })
    expect(t).toMatch(/0\/2 segments · 0% overall/)
    expect(t).toMatch(/Current: Minimization ENM k=0\.5 \(before segment 1\)/)
  })
  it('masterProgressTooltip: no minimisation line once a segment is running', () => {
    const t = masterProgressTooltip({ engine: 'namd', status: 'running',
      minimization: { name: 'B_00_min', stage: 'Minimization ENM k=0.5', steps: 9600, status: 'done' },
      segments: [{ status: 'running', name: 'heat', percent: 40 }] })
    expect(t).not.toMatch(/Minimization/)
    expect(t).toMatch(/Current: heat · 40%/)
  })
  it('masterProgressPct: a running NAMD job uses the backend live fraction (single-segment production)', () => {
    // A single-segment production child: done/total reads 0 (0 of 1 done) — the
    // backend-stamped progress_fraction must win so the bar advances instead of "hung".
    expect(masterProgressPct({ engine: 'namd', status: 'running', progress_fraction: 0.42, segments: [{ status: 'running' }] })).toBe(42)
    // Falls back to done/total segment count when no fraction was stamped.
    expect(masterProgressPct({ engine: 'namd', status: 'running', segments: [{ status: 'done' }, { status: 'running' }] })).toBe(50)
  })
  it('masterProgressPct: reports ONE decimal, so a long production leaves 0 % early', () => {
    // A 500 ns / 125M-step production is a fraction of a percent for its first hour.
    // Whole-percent rounding pinned the bar at a flat 0 while the run was demonstrably
    // advancing (measured: 585,000 steps in, bar still reading 0 %).
    const namd = (f) => ({ engine: 'namd', status: 'running', progress_fraction: f, segments: [{ status: 'running' }] })
    expect(masterProgressPct(namd(585000 / 125e6))).toBe(0.5)
    expect(masterProgressPct(namd(42500 / 125e6))).toBe(0)      // genuinely below a tenth
    expect(masterProgressPct(namd(0.00126))).toBe(0.1)
    expect(masterProgressPct(namd(0.4237))).toBe(42.4)
    // Whole values are untouched — short runs read exactly as they did before.
    expect(masterProgressPct(namd(0.42))).toBe(42)
    expect(masterProgressPct(namd(1))).toBe(100)
    expect(masterProgressPct(oxNode({ status: 'running', progress_fraction: 0.7312, stages: [{ status: 'running' }] }))).toBe(73.1)
    expect(masterProgressPct(lmNode({ status: 'running', current_step: 3, steps: 1000 }))).toBe(0.3)
  })
  it('masterStepText: the step count comes from the raw fraction, not the rounded percent', () => {
    // 0.1 % of a 125M-step run is 125,000 steps — deriving the count from the DISPLAYED
    // percent would make the readout disagree with the checkpoint it was measured from.
    expect(masterStepText({ engine: 'namd', status: 'running', progress_fraction: 585000 / 125e6,
      segments: [{ status: 'running', steps: 125000000 }] }))
      .toBe('0.5% · 585,000 / 125,000,000 steps · 124,415,000 left')
  })
  it('masterStatusText labels the engine + state (NAMD/mrDNA/CanDo are NOT mislabeled oxDNA)', () => {
    expect(masterStatusText(lmNode({ status: 'running', current_step: 500, steps: 1000 }))).toMatch(/LAMMPS \(CPU\) · running · 50%/)
    expect(masterStatusText(oxNode({ production_state: 'done' }))).toMatch(/oxDNA · production done/)
    // Regression: these used to all read "oxDNA · …".
    expect(masterStatusText({ engine: 'namd', status: 'running', segments: [{ status: 'done' }, { status: 'running' }] })).toMatch(/^NAMD · running · 50%/)
    expect(masterStatusText({ engine: 'namd', status: 'running', progress_fraction: 0.42, segments: [{ status: 'running' }] })).toMatch(/^NAMD · running · 42%/)
    expect(masterStatusText({ engine: 'namd', status: 'completed' })).toMatch(/^NAMD · completed/)
    expect(masterStatusText({ engine: 'mrdna', status: 'running' })).toMatch(/^mrDNA · running/)
    expect(masterStatusText({ engine: 'cando', status: 'queued' })).toMatch(/^CanDo · queued/)
    expect(masterStatusText(null)).toMatch(/Select a run/)
  })
  it('masterStepText shows percent, completed/total steps, and remaining steps for every engine shape', () => {
    expect(masterStepText(lmNode({ status: 'running', current_step: 250, steps: 1000 })))
      .toBe('25% · 250 / 1,000 steps · 750 left')
    expect(masterStepText(oxNode({ status: 'running', progress_fraction: 0.5,
      stages: [{ status: 'running', steps: 2000 }] })))
      .toBe('50% · 1,000 / 2,000 steps · 1,000 left')
    expect(masterStepText({ engine: 'mrdna', status: 'running', progress_fraction: 0.25,
      coarse_steps: 1000, fine_steps: 1000 })).toBe('25% · 500 / 2,000 steps · 1,500 left')
    expect(masterStepText({ engine: 'cando', status: 'running', progress_fraction: 0.4, n_steps: 20 }))
      .toBe('40% · 8 / 20 steps · 12 left')
    expect(masterStepText({ engine: 'snupi', status: 'running', progress_fraction: 0.5, n_steps: 20 }))
      .toBe('50% · 10 / 20 steps · 10 left')
    expect(masterStepText({ engine: 'namd', status: 'running', progress_fraction: 0.5,
      segments: [{ status: 'running', num_steps: 4000 }] }))
      .toBe('50% · 2,000 / 4,000 steps · 2,000 left')
  })
  it('masterStatusText carries the SNUPI %, ETA and phase under the one master bar', () => {
    // SNUPI has a SINGLE stage, so the stage-count fallback would read 0% for the whole solve —
    // it stamps a real progress_fraction instead, and the master bar/status is the only place it shows.
    const running = { engine: 'snupi', status: 'running', progress_fraction: 0.42,
                      eta_seconds: 95, phase: 'trajectory' }
    expect(masterProgressPct(running)).toBe(42)
    const t = masterStatusText(running)
    expect(t).toMatch(/^SNUPI · running · 42%/)
    // The ETA now comes from masterStepText (one place, every engine), so it reads
    // "remaining" and appears exactly once — it used to be appended here as well.
    expect(t).toContain('~1m 35s remaining')  // ETA is formatted, not a bare "95s"
    expect(t.match(/1m 35s/g)).toHaveLength(1)
    expect(t).toContain('trajectory')
    // The slow, step-less friction build must name itself or the bar looks stuck.
    expect(masterStatusText({ engine: 'snupi', status: 'running', progress_fraction: 0.02,
                              phase: 'building hydrodynamic friction' }))
      .toContain('building hydrodynamic friction')
    expect(masterStatusText({ engine: 'snupi', status: 'completed' })).toMatch(/^SNUPI · completed/)
  })
  it('formatEta reads as m:ss for multi-minute solves', () => {
    expect(formatEta(45)).toBe('45s')
    expect(formatEta(95)).toBe('1m 35s')
    expect(formatEta(650)).toBe('10m 50s')
  })
  it('formatEta coarsens to h:mm and d:hh — an MD run is measured in DAYS, not minutes', () => {
    expect(formatEta(3600)).toBe('1h 00m')
    expect(formatEta(11220)).toBe('3h 07m')
    expect(formatEta(86400)).toBe('1d 00h')
    // The live 500 ns production: 124.0M steps left at 1.565 ms/step.
    expect(formatEta(124035000 * 0.00156458)).toBe('2d 05h')
  })
  it('masterStepText appends the time remaining after the steps left', () => {
    expect(masterStepText({ engine: 'namd', status: 'running', progress_fraction: 965000 / 125e6,
      eta_seconds: 124035000 * 0.00156458, segments: [{ status: 'running', steps: 125000000 }] }))
      .toBe('0.8% · 965,000 / 125,000,000 steps · 124,035,000 left · ~2d 05h remaining')
    // No engine-supplied estimate → no fabricated one.
    expect(masterStepText({ engine: 'namd', status: 'running', progress_fraction: 0.5,
      segments: [{ status: 'running', steps: 4000 }] }))
      .toBe('50% · 2,000 / 4,000 steps · 2,000 left')
    // A step-less engine still gets the estimate next to its percent.
    expect(masterStepText({ engine: 'mrdna', status: 'running', progress_fraction: 0.3, eta_seconds: 95 }))
      .toBe('30% · ~1m 35s remaining')
  })
  it('nodeDetailText explains the LAMMPS CPU fallback', () => {
    expect(nodeDetailText(lmNode({ ranks: 6 }), 'oxdna')).toMatch(/CPU \(LAMMPS, 6 cores\) because the GPU was busy/)
    expect(nodeDetailText(oxNode({ n_units: 100 }), 'oxdna')).toMatch(/oxDNA \(GPU\) · 100 nucleotides/)
  })
  it('nodeDetailText never labels another engine\'s run as oxDNA', () => {
    // Regression: this used to FALL THROUGH — any non-LAMMPS node with n_units got the
    // "oxDNA (GPU) · N nucleotides" line, so a SNUPI/mrDNA/CanDo/NAMD run claimed it ran on oxDNA.
    for (const engine of ['snupi', 'mrdna', 'cando', 'namd']) {
      expect(nodeDetailText({ engine, status: 'completed', n_units: 1260 }, engine)).toBe('')
    }
  })
  it('nodeDetailText only shows on the oxDNA tab', () => {
    // "Show all job types" lets you select an oxDNA run from any tab — the oxDNA-flavoured note must
    // not appear under another engine's panel.
    const ox = oxNode({ n_units: 100 })
    expect(nodeDetailText(ox, 'oxdna')).toMatch(/oxDNA \(GPU\)/)
    for (const tab of ['snupi', 'mrdna', 'cando', 'namd']) {
      expect(nodeDetailText(ox, tab)).toBe('')
    }
    expect(nodeDetailText(lmNode(), 'snupi')).toBe('')   // LAMMPS groups under oxDNA — same gate
  })
})

// ── factory drive (jsdom) ──────────────────────────────────────────────────────

function mount() {
  document.body.innerHTML = `
    <div id="simulate-body">
      <div id="simulate-job-actions" style="display:none">
        <button id="simulate-jobs-archive-btn"></button>
        <button id="simulate-jobs-delete-btn"></button>
        <div id="simulate-jobs-archive-progress" style="display:none"></div>
      </div>
      <div id="simulate-jobs">
        <div id="simulate-jobs-toggle"><span id="simulate-jobs-arrow"></span><span id="simulate-jobs-engine-label"></span></div>
        <div id="simulate-jobs-body">
        <label><input id="simulate-jobs-show-all-types" type="checkbox"></label>
        <div id="simulate-jobs-list"></div>
        <div id="simulate-jobs-progress"><div class="bar"></div></div>
        <div id="simulate-jobs-status"></div>
        <button id="simulate-jobs-run-btn"></button>
        <div id="simulate-jobs-detail"></div>
        <div id="simulate-jobs-timeline" style="display:none">
          <div id="simulate-jobs-timeline-host">
            <div id="oxdna-jobs-timeline"></div>
            <div id="md-jobs-timeline"></div>
            <div id="mrdna-jobs-timeline"></div>
            <div id="cando-jobs-timeline"></div>
          </div>
        </div>
        </div>
      </div>
    </div>`
}

function make(nodes, apiOverrides = {}) {
  const api = {
    listSimJobs: vi.fn().mockResolvedValue(nodes),
    stopOxdnaJob: vi.fn().mockResolvedValue({}), startOxdnaJob: vi.fn().mockResolvedValue({}),
    stopLammpsJob: vi.fn().mockResolvedValue({}), createLammpsJob: vi.fn().mockResolvedValue({ n_atoms: 200 }),
    lastErrorMessage: () => '', ...apiOverrides,
  }
  const oxdnaPanel = { selectJob: vi.fn(), selectLammpsJob: vi.fn(), launchRelax: vi.fn(),
    autorefineJobIds: () => new Set(), deselectJob: vi.fn(),
    deleteSelected: vi.fn().mockResolvedValue(true), archiveSelected: vi.fn().mockResolvedValue(undefined) }
  const mrdnaPanel = { selectJob: vi.fn(), deselectJob: vi.fn(), deleteSelected: vi.fn().mockResolvedValue(true) }
  const candoPanel = { selectJob: vi.fn(), deselectJob: vi.fn(), deleteSelected: vi.fn().mockResolvedValue(true) }
  const mdPanel = { selectJob: vi.fn(), deselectJob: vi.fn(),
    deleteSelected: vi.fn().mockResolvedValue(true), archiveSelected: vi.fn().mockResolvedValue(undefined) }
  const engineSelector = { select: vi.fn(), getSelected: () => 'oxdna' }
  const sim = initSimulateJobs({ api, getWorkspacePath: () => '/w/D.nadoc',
    oxdnaPanel, mrdnaPanel, candoPanel, mdPanel, engineSelector })
  return { sim, api, oxdnaPanel, mrdnaPanel, candoPanel, mdPanel, engineSelector }
}

const mrNode = (o = {}) => ({ engine: 'mrdna', job_id: 'mr1', parent_job_id: null,
  created_at: 3, status: 'completed', production_state: null, kind: 'relax',
  n_units: 64, design_name: 'D', ...o })
const mdNode = (o = {}) => ({ engine: 'namd', job_id: 'md1', parent_job_id: null,
  created_at: 4, status: 'completed', production_state: null, kind: 'relax',
  n_units: 100, design_name: 'D', ...o })

beforeEach(() => { document.body.innerHTML = ''; vi.clearAllMocks() })

describe('unified list + master card', () => {
  it('renders both engines in one list, LAMMPS carrying an [L] badge', async () => {
    mount()
    const { sim } = make([oxNode(), lmNode()])
    await sim.refresh()
    const list = document.getElementById('simulate-jobs-list')
    expect(list.childElementCount).toBe(2)
    expect(list.textContent).toContain('[L]')       // LAMMPS badge
  })

  it('a nadoc:sim-jobs-changed event wakes the idle master list (launch-not-showing bug)', async () => {
    mount()
    // Master starts with nothing active → its poll is NOT armed (it only self-polls
    // while it already has a running node). This is the state when a production run is
    // launched off a completed parent.
    const { sim, api } = make([oxNode({ status: 'completed' })])
    await sim.refresh()
    const before = api.listSimJobs.mock.calls.length
    // A production child now exists in the backend; the engine panel fires the wake event.
    api.listSimJobs.mockResolvedValue([
      oxNode({ status: 'completed' }),
      oxNode({ job_id: 'ox2', parent_job_id: 'ox1', kind: 'run', status: 'running',
               production_state: 'running', stages: [{ status: 'running' }] }),
    ])
    window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed'))
    for (let i = 0; i < 5; i++) await Promise.resolve()   // let the async _fetch settle
    // The idle master re-fetched on the event (the bug: it did nothing → the running
    // job never surfaced until a manual page refresh).
    expect(api.listSimJobs.mock.calls.length).toBeGreaterThan(before)
    // and the newly-running child is now in the list (2 oxDNA rows on the oxDNA tab).
    expect(document.querySelectorAll('#simulate-jobs-list [data-job-id]').length).toBe(2)
  })

  it('selecting a LAMMPS node routes viz to the oxDNA panel (same card) + reflects status', async () => {
    mount()
    const { sim, oxdnaPanel, engineSelector } = make([oxNode(), lmNode()])
    await sim.refresh()
    sim.selectJob('lm1')
    expect(engineSelector.select).toHaveBeenCalledWith('oxdna')
    expect(oxdnaPanel.selectLammpsJob).toHaveBeenCalledWith(expect.objectContaining({ engine: 'lammps', job_id: 'lm1' }))
    expect(document.getElementById('simulate-jobs-status').textContent).toMatch(/LAMMPS \(CPU\)/)
    expect(document.getElementById('simulate-jobs-detail').textContent).toMatch(/CPU \(LAMMPS/)
    expect(sim.getSelected()).toEqual({ engine: 'lammps', id: 'lm1' })
  })

  it('selecting an oxDNA node delegates detail/viz to the oxDNA panel', async () => {
    mount()
    const { sim, oxdnaPanel, engineSelector } = make([oxNode(), lmNode()])
    await sim.refresh()
    sim.selectJob('lm1')
    sim.selectJob('ox1')
    expect(oxdnaPanel.selectJob).toHaveBeenCalledWith('ox1')
    expect(engineSelector.select).toHaveBeenCalledWith('oxdna')
  })

  it('run button is LAMMPS-only: hidden for oxDNA / no selection, shown to Stop an [L] run', async () => {
    mount()
    const { sim, api } = make([oxNode(), lmNode({ status: 'running' })])
    await sim.refresh()
    const btn = document.getElementById('simulate-jobs-run-btn')
    expect(btn.style.display).toBe('none')             // nothing selected → no duplicate button
    sim.selectJob('ox1')
    expect(btn.style.display).toBe('none')             // oxDNA node → its button lives in the oxDNA panel
    sim.selectJob('lm1')
    expect(btn.style.display).toBe('')                 // [L] node → the master card owns its control
    expect(btn.dataset.runAction).toBe('stop')
    btn.click()
    await Promise.resolve()
    expect(api.stopLammpsJob).toHaveBeenCalledWith('lm1')
  })
})

describe('consolidated Archive / Delete (above the jobs card)', () => {
  const host = () => document.getElementById('simulate-job-actions')
  const archiveBtn = () => document.getElementById('simulate-jobs-archive-btn')
  const deleteBtn = () => document.getElementById('simulate-jobs-delete-btn')

  it('hidden with no selection; shown for a selected oxDNA run with both buttons', async () => {
    mount()
    const { sim } = make([oxNode()])
    await sim.refresh()
    expect(host().style.display).toBe('none')
    sim.selectJob('ox1')
    expect(host().style.display).toBe('')
    expect(deleteBtn().style.display).toBe('')
    expect(archiveBtn().style.display).toBe('')            // oxDNA supports archive
    expect(archiveBtn().textContent).toBe('Archive')
  })

  it('mrDNA / CanDo offer Delete only (no Archive)', async () => {
    mount()
    const { sim } = make([mrNode()])
    await sim.refresh()
    sim.selectJob('mr1')
    expect(deleteBtn().style.display).toBe('')
    expect(archiveBtn().style.display).toBe('none')
  })

  it('an archived run shows Unarchive', async () => {
    mount()
    const { sim } = make([mdNode({ archived: true })])
    await sim.refresh()
    sim.selectJob('md1')
    expect(archiveBtn().textContent).toBe('Unarchive')
  })

  it('hidden for a LAMMPS run (no per-job delete UI) and while a run is running', async () => {
    mount()
    const { sim } = make([oxNode({ status: 'running' }), lmNode()])
    await sim.refresh()
    sim.selectJob('lm1')
    expect(host().style.display).toBe('none')
    sim.selectJob('ox1')
    expect(host().style.display).toBe('none')              // running → not deletable
  })

  it('Delete dispatches to the selected run’s engine panel', async () => {
    mount()
    const { sim, mdPanel } = make([mdNode()])
    await sim.refresh()
    sim.selectJob('md1')
    deleteBtn().click()
    await Promise.resolve(); await Promise.resolve()
    expect(mdPanel.deleteSelected).toHaveBeenCalled()
  })

  it('Archive dispatches to the selected run’s engine panel with a progress callback', async () => {
    mount()
    const { sim, oxdnaPanel } = make([oxNode()])
    await sim.refresh()
    sim.selectJob('ox1')
    archiveBtn().click()
    await Promise.resolve(); await Promise.resolve()
    expect(oxdnaPanel.archiveSelected).toHaveBeenCalledWith(
      expect.objectContaining({ onProgress: expect.any(Function) }))
  })
})

describe('engine-scoped list + Show-all-job-types toggle', () => {
  it('scopes to the active engine tab by default (LAMMPS grouped under oxDNA)', async () => {
    mount()
    const { sim } = make([oxNode(), lmNode(), mrNode(), mdNode()])
    await sim.refresh()
    const list = document.getElementById('simulate-jobs-list')
    // active engine = oxdna → only oxDNA + LAMMPS rows show
    expect(list.childElementCount).toBe(2)
    expect(list.textContent).toContain('[L]')
  })

  it('switching the active engine re-filters the list', async () => {
    mount()
    const { sim } = make([oxNode(), mrNode(), mdNode()])
    await sim.refresh()
    const list = document.getElementById('simulate-jobs-list')
    expect(list.childElementCount).toBe(1)          // oxDNA only
    sim.setActiveEngine('namd')
    expect(list.childElementCount).toBe(1)          // now the NAMD row
    sim.setActiveEngine('mrdna')
    expect(list.childElementCount).toBe(1)          // now the mrDNA row
  })

  it('Show all job types reveals every engine, each tagged, and labels the header', async () => {
    mount()
    const { sim } = make([oxNode(), lmNode(), mrNode(), mdNode()])
    await sim.refresh()
    const toggle = document.getElementById('simulate-jobs-show-all-types')
    toggle.checked = true
    toggle.dispatchEvent(new Event('change'))
    const list = document.getElementById('simulate-jobs-list')
    expect(list.childElementCount).toBe(4)          // all four engines
    expect(list.textContent).toContain('[mr]')      // engine badges in mixed mode
    expect(list.textContent).toContain('[MD]')
    expect(document.getElementById('simulate-jobs-engine-label').textContent).toMatch(/all engines/)
  })

  it('selecting a mrDNA / NAMD row routes to that engine tab + panel', async () => {
    mount()
    const { sim, mrdnaPanel, mdPanel, engineSelector } = make([oxNode(), mrNode(), mdNode()])
    await sim.refresh()
    document.getElementById('simulate-jobs-show-all-types').checked = true
    document.getElementById('simulate-jobs-show-all-types').dispatchEvent(new Event('change'))
    sim.selectJob('mr1')
    expect(engineSelector.select).toHaveBeenCalledWith('mrdna')
    expect(mrdnaPanel.selectJob).toHaveBeenCalledWith('mr1')
    sim.selectJob('md1')
    expect(engineSelector.select).toHaveBeenCalledWith('namd')
    expect(mdPanel.selectJob).toHaveBeenCalledWith('md1')
  })

  it('collapsible card: clicking the header toggles the body + chevron', async () => {
    mount()
    const { sim } = make([oxNode()])
    await sim.refresh()
    const header = document.getElementById('simulate-jobs-toggle')
    const body = document.getElementById('simulate-jobs-body')
    const arrow = document.getElementById('simulate-jobs-arrow')
    expect(body.style.display).toBe('')             // open by default
    header.click()
    expect(body.style.display).toBe('none')
    expect(arrow.classList.contains('is-collapsed')).toBe(true)
    header.click()
    expect(body.style.display).toBe('')
  })
})

describe('one consolidated progress bar + relocated timeline', () => {
  it('the single bar paints width + status colour + a detail tooltip for the selected job', async () => {
    mount()
    const { sim } = make([mdNode({ status: 'running',
      segments: [{ status: 'done' }, { status: 'running', name: 'heat', percent: 40 }] })])
    await sim.refresh()
    sim.selectJob('md1')
    const bar = document.querySelector('#simulate-jobs-progress .bar')
    expect(bar.style.width).toBe('50%')
    expect(bar.style.background).toBe('rgb(74, 158, 255)')        // blue = active
    expect(document.getElementById('simulate-jobs-progress').title).toMatch(/1\/2 segments · 50% overall/)
  })

  it('shows the selected engine’s timeline at the card bottom, hides the others', async () => {
    mount()
    const { sim } = make([mdNode(), oxNode({ job_id: 'ox9' })])
    await sim.refresh()
    document.getElementById('simulate-jobs-show-all-types').checked = true
    document.getElementById('simulate-jobs-show-all-types').dispatchEvent(new Event('change'))
    sim.selectJob('md1')
    expect(document.getElementById('simulate-jobs-timeline').style.display).toBe('')
    expect(document.getElementById('md-jobs-timeline').style.display).toBe('')
    expect(document.getElementById('oxdna-jobs-timeline').style.display).toBe('none')
  })

  it('switching to a different engine tab clears the previous engine’s stages + status', async () => {
    // Select a NAMD run (its stage timeline + status paint into the shared master card),
    // then switch to a DIFFERENT engine tab — the NAMD stages must not linger.
    mount()
    const { sim } = make([mdNode({ status: 'running', segments: [{ status: 'running', name: 'heat' }] }),
      oxNode({ job_id: 'ox9' })])
    await sim.refresh()
    sim.selectJob('md1')
    expect(document.getElementById('md-jobs-timeline').style.display).toBe('')
    sim.setActiveEngine('cando')                       // user clicks another engine tab
    expect(sim.getSelected().id).toBe(null)            // selection dropped
    expect(document.getElementById('simulate-jobs-timeline').style.display).toBe('none')
    expect(document.getElementById('md-jobs-timeline').style.display).toBe('none')
    expect(document.getElementById('simulate-jobs-status').textContent).toMatch(/Select a run/)
    expect(document.querySelector('#simulate-jobs-progress .bar').style.width).toBe('0%')
  })

  // ── Click-the-selected-row-to-deselect ──────────────────────────────────────
  // This unified list is the ONE list the user clicks (every engine panel's own list is
  // display:none in index.html), so deselection is defined here and routed to the owning
  // engine panel. Selecting a DIFFERENT job is the only thing that unloads cached viz.
  it('clicking the already-selected row deselects it and tells that engine panel to deselect', async () => {
    mount()
    const { sim, candoPanel } = make([{ engine: 'cando', job_id: 'cd1', parent_job_id: null,
      created_at: 5, status: 'completed', production_state: null, kind: 'relax', design_name: 'D' }])
    sim.setActiveEngine('cando')
    await sim.refresh()
    const row = () => document.querySelector('#simulate-jobs-list [data-job-id="cd1"]')
    row().click()
    expect(sim.getSelected().id).toBe('cd1')
    expect(candoPanel.selectJob).toHaveBeenCalledWith('cd1')

    row().click()                                       // second click on the SAME row
    expect(sim.getSelected().id).toBe(null)             // deselected
    expect(sim.getSelected().engine).toBe(null)
    expect(candoPanel.deselectJob).toHaveBeenCalled()   // panel dropped its selection too
    expect(candoPanel.selectJob).toHaveBeenCalledTimes(1)   // NOT re-selected
    expect(document.getElementById('simulate-jobs-status').textContent).toMatch(/Select a run/)
  })

  it('re-clicking the row after a deselect selects it again', async () => {
    mount()
    const { sim, candoPanel } = make([{ engine: 'cando', job_id: 'cd1', parent_job_id: null,
      created_at: 5, status: 'completed', production_state: null, kind: 'relax', design_name: 'D' }])
    sim.setActiveEngine('cando')
    await sim.refresh()
    const row = () => document.querySelector('#simulate-jobs-list [data-job-id="cd1"]')
    row().click(); row().click(); row().click()
    expect(sim.getSelected().id).toBe('cd1')
    expect(candoPanel.selectJob).toHaveBeenCalledTimes(2)
  })

  it('deselecting a LAMMPS node routes the deselect to the oxDNA panel (it hosts the LAMMPS viz)', async () => {
    mount()
    const { sim, oxdnaPanel } = make([oxNode(), lmNode()])
    await sim.refresh()
    const row = () => document.querySelector('#simulate-jobs-list [data-job-id="lm1"]')
    row().click()
    expect(oxdnaPanel.selectLammpsJob).toHaveBeenCalled()
    row().click()
    expect(sim.getSelected().id).toBe(null)
    expect(oxdnaPanel.deselectJob).toHaveBeenCalled()
  })

  it('“show all job types” keeps the selection when the engine tab changes (still visible)', async () => {
    mount()
    const { sim } = make([mdNode(), oxNode({ job_id: 'ox9' })])
    await sim.refresh()
    document.getElementById('simulate-jobs-show-all-types').checked = true
    document.getElementById('simulate-jobs-show-all-types').dispatchEvent(new Event('change'))
    sim.selectJob('md1')
    sim.setActiveEngine('cando')
    expect(sim.getSelected().id).toBe('md1')           // every run stays visible → preserved
    expect(document.getElementById('md-jobs-timeline').style.display).toBe('')
  })
})

// ── progress carried forward while signed out of the cluster ─────────────────
import { progressIsEstimated, masterStepText as _stepText, masterProgressPct as _pct } from './simulate_jobs.js'

describe('estimated progress (a cluster job is only observable while signed in)', () => {
  const base = { engine: 'namd', status: 'running', segments: [{ status: 'running', steps: 500000 }] }

  it('progressIsEstimated reflects the backend flag', () => {
    expect(progressIsEstimated({ ...base, progress_estimated: true })).toBe(true)
    expect(progressIsEstimated(base)).toBe(false)
    expect(progressIsEstimated(null)).toBe(false)
  })

  it('an estimate is marked "~" and named, so it cannot pass for a measurement', () => {
    const est = { ...base, progress_fraction: 0.57, progress_estimated: true, steps: 500000 }
    const txt = _stepText(est)
    expect(txt.startsWith('~')).toBe(true)
    expect(txt).toContain('estimated from last cluster sync')
  })

  it('a measured reading carries no hedge', () => {
    const measured = { ...base, progress_fraction: 0.57, steps: 500000 }
    const txt = _stepText(measured)
    expect(txt.startsWith('~')).toBe(false)
    expect(txt).not.toContain('estimated')
  })

  it('a disconnected RunPod observation is named last-known and keeps its percent', () => {
    const paused = { ...base, status: 'paused', progress_fraction: 0.0498,
      progress_last_known: true, runpod_sync_notice: 'No live RunPod pod is connected.' }
    expect(_pct(paused)).toBe(5)
    expect(_stepText(paused)).toContain('last known')
    expect(masterStatusText(paused)).toContain('⚠ No live RunPod pod is connected.')
  })

  it('the flag does not disturb the percentage itself', () => {
    expect(_pct({ ...base, progress_fraction: 0.57, progress_estimated: true }))
      .toBe(_pct({ ...base, progress_fraction: 0.57 }))
  })
})
