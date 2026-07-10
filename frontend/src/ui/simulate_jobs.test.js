import { describe, it, expect, vi, beforeEach } from 'vitest'

// Keep the heavy oxDNA panel + display/player graphs out of the unit test — the master
// card only uses a few pure label fns from the oxDNA panel and dispatches to controllers.
vi.mock('./oxdna_jobs_panel.js', () => ({
  jobDisplayName: (j) => j.design_name || 'design',
  runRowLabel: (j, i) => `Run ${i}`,
  runChildTitle: () => 'child run',
}))
vi.mock('./lammps_display.js', () => ({
  initLammpsDisplay: () => ({
    displayJob: vi.fn(), displayRmsf: vi.fn(), displayDeviation: vi.fn(),
    loadTrajectory: vi.fn(), showFrame: vi.fn(), stopAndRestore: vi.fn(),
    recolorRmsf: vi.fn(), recolorDeviation: vi.fn(), mode: () => null,
  }),
}))
vi.mock('./oxdna_trajectory_player.js', () => ({
  initOxdnaTrajectoryPlayer: () => ({ stop: vi.fn(), pause: vi.fn(), setTrajectory: vi.fn() }),
}))
vi.mock('./toast.js', () => ({ showToast: vi.fn() }))

import {
  initSimulateJobs, nodeIsActive, nodeIsResumable, verbForNode,
  masterProgressPct, masterStatusText, nodeDetailText,
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
  it('masterProgressPct: LAMMPS from steps, oxDNA from stages', () => {
    expect(masterProgressPct(lmNode({ current_step: 500, steps: 1000 }))).toBe(50)
    expect(masterProgressPct(oxNode({ stages: [{ status: 'done' }, { status: 'running' }] }))).toBe(50)
    expect(masterProgressPct(null)).toBe(0)
  })
  it('masterStatusText labels the engine + state', () => {
    expect(masterStatusText(lmNode({ status: 'running', current_step: 500, steps: 1000 }))).toMatch(/LAMMPS \(CPU\) · running · 50%/)
    expect(masterStatusText(oxNode({ production_state: 'done' }))).toMatch(/oxDNA · production done/)
    expect(masterStatusText(null)).toMatch(/Select a run/)
  })
  it('nodeDetailText explains the LAMMPS CPU fallback', () => {
    expect(nodeDetailText(lmNode({ ranks: 6 }))).toMatch(/CPU \(LAMMPS, 6 cores\) because the GPU was busy/)
    expect(nodeDetailText(oxNode({ n_units: 100 }))).toMatch(/oxDNA \(GPU\) · 100 nucleotides/)
  })
})

// ── factory drive (jsdom) ──────────────────────────────────────────────────────

function mount() {
  document.body.innerHTML = `
    <div id="simulate-body">
      <div id="simulate-jobs">
        <div id="simulate-jobs-list"></div>
        <div id="simulate-jobs-progress"><div class="bar"></div></div>
        <div id="simulate-jobs-status"></div>
        <button id="simulate-jobs-run-btn"></button>
        <div id="simulate-jobs-detail"></div>
        <div id="simulate-jobs-viz" style="display:none">
          <label><input id="simulate-jobs-viz-off" name="simulate-viz" type="radio" checked></label>
          <label><input id="simulate-jobs-display-toggle" name="simulate-viz" type="radio" disabled></label>
          <input id="simulate-jobs-align-toggle" type="checkbox" checked>
          <div id="simulate-jobs-display-status"></div>
          <label><input id="simulate-jobs-flex-toggle" name="simulate-viz" type="radio" disabled></label>
          <div id="simulate-jobs-flex-status"></div>
          <label><input id="simulate-jobs-deviation-toggle" name="simulate-viz" type="radio" disabled></label>
          <div id="simulate-jobs-deviation-status"></div>
          <label><input id="simulate-jobs-traj-toggle" name="simulate-viz" type="radio" disabled></label>
          <div id="simulate-jobs-traj-status"></div>
          <div id="simulate-jobs-traj-controls" style="display:none">
            <button id="simulate-jobs-traj-play"></button>
            <input id="simulate-jobs-traj-slider" type="range">
            <div id="simulate-jobs-traj-markers"></div>
            <div id="simulate-jobs-traj-label"></div>
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
  const oxdnaPanel = { selectJob: vi.fn(), launchRelax: vi.fn(), autorefineJobIds: () => new Set() }
  const engineSelector = { select: vi.fn() }
  const sim = initSimulateJobs({ api, getWorkspacePath: () => '/w/D.nadoc', oxdnaPanel, engineSelector })
  return { sim, api, oxdnaPanel, engineSelector }
}

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

  it('selecting a LAMMPS node shows the master viz card + reflects its status', async () => {
    mount()
    const { sim } = make([oxNode(), lmNode()])
    await sim.refresh()
    sim.selectJob('lm1')
    expect(document.getElementById('simulate-jobs-viz').style.display).toBe('')
    expect(document.getElementById('simulate-jobs-status').textContent).toMatch(/LAMMPS \(CPU\)/)
    expect(document.getElementById('simulate-jobs-detail').textContent).toMatch(/CPU \(LAMMPS/)
    expect(sim.getSelected()).toEqual({ engine: 'lammps', id: 'lm1' })
  })

  it('selecting an oxDNA node delegates detail/viz to the oxDNA panel + hides the LAMMPS viz', async () => {
    mount()
    const { sim, oxdnaPanel, engineSelector } = make([oxNode(), lmNode()])
    await sim.refresh()
    sim.selectJob('lm1')                       // show viz first…
    sim.selectJob('ox1')                        // …then switch to oxDNA
    expect(oxdnaPanel.selectJob).toHaveBeenCalledWith('ox1')
    expect(engineSelector.select).toHaveBeenCalledWith('oxdna')
    expect(document.getElementById('simulate-jobs-viz').style.display).toBe('none')
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
