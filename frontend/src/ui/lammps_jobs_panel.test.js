// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../api/client.js', () => {
  const pos = { helix_id: 'h', bp_index: 0, direction: 'FORWARD', copy: 0, backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0 }
  return {
    lammpsAvailable: vi.fn().mockResolvedValue({ available: true, cgdna_capable: true }),
    listLammpsJobs: vi.fn().mockResolvedValue([]),
    createLammpsJob: vi.fn().mockResolvedValue({ job_id: 'l1', status: 'preparing', n_atoms: 504 }),
    stopLammpsJob: vi.fn().mockResolvedValue({ job_id: 'l1', status: 'stopped' }),
    getLammpsTrajectory: vi.fn().mockResolvedValue({
      ready: true, n_frames: 3, n_nucleotides: 1, keys: [['h', 0, 'FORWARD']],
      frames: [[0, 0, 0, 1, 0, 0], [0, 0, 1, 1, 0, 0], [0, 0, 2, 1, 0, 0]], stages: [], markers: [],
    }),
    getLammpsDisplay: vi.fn().mockResolvedValue({ ready: true, positions: [pos] }),
    getLammpsRmsf: vi.fn().mockResolvedValue({ ready: true, positions: [{ ...pos, rmsf: 0.01 }], min_rmsf: 0, max_rmsf: 0.05, mean_rmsf: 0.02, n_frames: 6 }),
    getLammpsDeviation: vi.fn().mockResolvedValue({ ready: true, positions: [{ ...pos, deviation: 0.3 }], min_deviation: 0, max_deviation: 0.5, mean_deviation: 0.3, n_frames: 6 }),
    lastErrorMessage: () => null,
  }
})

import * as api from '../api/client.js'
import { initLammpsJobsPanel } from './lammps_jobs_panel.js'

const flush = async (n = 14) => { for (let i = 0; i < n; i++) await Promise.resolve() }

const MARKUP = `
  <div class="panel-section" id="lammps-jobs-panel">
    <h2 id="lammps-jobs-heading"><span id="lammps-jobs-arrow"></span></h2>
    <div id="lammps-jobs-body" style="display:none">
      <div id="lammps-jobs-status"></div>
      <div id="lammps-jobs-progress"><div class="bar" style="width:0%"></div></div>
      <button id="lammps-jobs-run-btn" disabled>▶ Run on LAMMPS</button>
      <label><input id="lammps-jobs-show-all" type="checkbox"> show all designs</label>
      <div id="lammps-jobs-list"></div>
      <div id="lammps-jobs-adv-toggle"><span id="lammps-jobs-adv-arrow">▸</span></div>
      <div id="lammps-jobs-adv-body" style="display:none">
        <input id="lammps-jobs-steps" value="100000"><input id="lammps-jobs-dump" value="1000">
        <input id="lammps-jobs-temp" value="0.1"><input id="lammps-jobs-salt" value="0.5"><input id="lammps-jobs-ranks" value="1">
      </div>
      <div id="lammps-jobs-viz-toggle"><span id="lammps-jobs-viz-arrow"></span></div>
      <div id="lammps-jobs-viz-body">
        <label><input id="lammps-jobs-viz-off" name="lammps-viz" type="radio" checked> Off</label>
        <label><input id="lammps-jobs-display-toggle" name="lammps-viz" type="radio" disabled> Display</label>
        <label><input id="lammps-jobs-align-toggle" type="checkbox" checked> Align</label>
        <div id="lammps-jobs-display-status"></div>
        <label><input id="lammps-jobs-flex-toggle" name="lammps-viz" type="radio" disabled> Flex</label>
        <div id="lammps-jobs-flex-status"></div>
        <label><input id="lammps-jobs-deviation-toggle" name="lammps-viz" type="radio" disabled> Deviation</label>
        <div id="lammps-jobs-deviation-status"></div>
        <label><input id="lammps-jobs-traj-toggle" name="lammps-viz" type="radio" disabled> Trajectory</label>
        <div id="lammps-jobs-traj-status"></div>
        <div id="lammps-jobs-traj-controls" style="display:none">
          <button id="lammps-jobs-traj-play">▶</button>
          <input id="lammps-jobs-traj-slider" type="range" min="0" max="0" value="0">
          <div id="lammps-jobs-traj-markers"></div><div id="lammps-jobs-traj-label"></div>
        </div>
      </div>
    </div>
  </div>`

const $ = (id) => document.getElementById(id)
const openPanel = () => $('lammps-jobs-heading').click()
const WS = '/ws/6hb.nadoc'
const COMPLETED = [{ job_id: 'l1', design_name: '6hb', status: 'completed', frames: 3, n_atoms: 1, steps: 1000, current_step: 1000, design_source_path: WS }]
const RUNNING = [{ job_id: 'l9', design_name: '6hb', status: 'running', current_step: 500, steps: 1000, n_atoms: 504, design_source_path: WS }]

function renderer() {
  return { applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
}
async function openWithCompletedSelected(dr) {
  api.listLammpsJobs.mockResolvedValue(COMPLETED)
  initLammpsJobsPanel({ designRenderer: dr, getWorkspacePath: () => WS })
  openPanel(); await flush()
  ;[...$('lammps-jobs-list').children][0].click()   // select the run
  await flush()
}

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
  document.body.innerHTML = MARKUP
  api.lammpsAvailable.mockResolvedValue({ available: true, cgdna_capable: true })
  api.listLammpsJobs.mockResolvedValue([])
})
afterEach(() => { vi.useRealTimers(); document.body.innerHTML = '' })

describe('initLammpsJobsPanel — launch + list', () => {
  it('no-op returning {refresh} when the section is absent', () => {
    document.body.innerHTML = ''
    expect(typeof initLammpsJobsPanel().refresh).toBe('function')
  })
  it('opening enables Run when LAMMPS + CG-DNA are ready', async () => {
    initLammpsJobsPanel(); openPanel(); await flush()
    expect($('lammps-jobs-run-btn').disabled).toBe(false)
    expect($('lammps-jobs-status').textContent).toMatch(/ready/)
  })
  it('Run posts a create with the Advanced-card params', async () => {
    initLammpsJobsPanel(); openPanel(); await flush()
    $('lammps-jobs-steps').value = '5000'; $('lammps-jobs-dump').value = '500'
    $('lammps-jobs-run-btn').click(); await flush()
    expect(api.createLammpsJob).toHaveBeenCalledWith(expect.objectContaining({ steps: 5000, dump_every: 500 }))
  })
  it('shows an empty-state with no runs', async () => {
    initLammpsJobsPanel(); openPanel(); await flush()
    expect($('lammps-jobs-list').textContent).toMatch(/No LAMMPS runs yet/)
  })
})

describe('initLammpsJobsPanel — current-design filtering', () => {
  const MIX = [
    { job_id: 'a', design_name: 'this', status: 'completed', frames: 2, steps: 1, current_step: 1, design_source_path: WS },
    { job_id: 'b', design_name: 'other', status: 'completed', frames: 2, steps: 1, current_step: 1, design_source_path: '/ws/other.nadoc' },
  ]
  it('only shows jobs whose design_source_path matches the loaded design', async () => {
    api.listLammpsJobs.mockResolvedValue(MIX)
    initLammpsJobsPanel({ designRenderer: renderer(), getWorkspacePath: () => WS })
    openPanel(); await flush()
    const rows = [...$('lammps-jobs-list').children].map(c => c.textContent)
    expect(rows.some(t => /this/.test(t))).toBe(true)
    expect(rows.some(t => /other/.test(t))).toBe(false)
  })
  it('"show all designs" reveals other designs\' runs', async () => {
    api.listLammpsJobs.mockResolvedValue(MIX)
    initLammpsJobsPanel({ designRenderer: renderer(), getWorkspacePath: () => WS })
    openPanel(); await flush()
    $('lammps-jobs-show-all').checked = true
    $('lammps-jobs-show-all').dispatchEvent(new Event('change'))
    await flush()
    expect([...$('lammps-jobs-list').children].some(c => /other/.test(c.textContent))).toBe(true)
  })
  it('empty-state notes other designs exist when filtered to none', async () => {
    api.listLammpsJobs.mockResolvedValue([MIX[1]])   // only the other design's run
    initLammpsJobsPanel({ designRenderer: renderer(), getWorkspacePath: () => WS })
    openPanel(); await flush()
    expect($('lammps-jobs-list').textContent).toMatch(/show all designs/)
  })
})

describe('initLammpsJobsPanel — forces payload', () => {
  it('Run includes design_source_path + forces from the forces setup', async () => {
    const forcesSetup = {
      fieldNeedsAnchor: () => false,
      getForces: () => ({ field: { field_pN: 30, dir: [1, 0, 0] }, anchors: [{ kind: 'strand', id: 's1' }] }),
      detachGizmo: () => {},
    }
    initLammpsJobsPanel({ getWorkspacePath: () => WS, forcesSetup })
    openPanel(); await flush()
    $('lammps-jobs-run-btn').click(); await flush()
    expect(api.createLammpsJob).toHaveBeenCalledWith(expect.objectContaining({
      design_source_path: WS,
      field: { field_pN: 30, dir: [1, 0, 0] },
      anchors: [{ kind: 'strand', id: 's1' }],
    }))
  })
  it('blocks the run (no POST) when a field has no anchor', async () => {
    const forcesSetup = { fieldNeedsAnchor: () => true, getForces: () => ({ field: { field_pN: 30, dir: [1, 0, 0] }, anchors: [] }), detachGizmo: () => {} }
    initLammpsJobsPanel({ getWorkspacePath: () => WS, forcesSetup })
    openPanel(); await flush()
    api.createLammpsJob.mockClear()
    $('lammps-jobs-run-btn').click(); await flush()
    expect(api.createLammpsJob).not.toHaveBeenCalled()
  })
})

describe('initLammpsJobsPanel — visualization card', () => {
  it('view radios are disabled until a finished run is selected', async () => {
    api.listLammpsJobs.mockResolvedValue(COMPLETED)
    initLammpsJobsPanel({ designRenderer: renderer(), getWorkspacePath: () => WS })
    openPanel(); await flush()
    expect($('lammps-jobs-display-toggle').disabled).toBe(true)   // nothing selected
    ;[...$('lammps-jobs-list').children][0].click(); await flush()
    expect($('lammps-jobs-display-toggle').disabled).toBe(false)  // selected → enabled
    expect($('lammps-jobs-traj-toggle').disabled).toBe(false)
  })

  it('Display view deforms the model to the final structure', async () => {
    const dr = renderer(); await openWithCompletedSelected(dr)
    $('lammps-jobs-display-toggle').click(); await flush()
    expect(api.getLammpsDisplay).toHaveBeenCalledWith('l1', true)
    expect(dr.applyFemPositions).toHaveBeenCalled()
    expect(dr.clearScalarColors).toHaveBeenCalled()
    expect($('lammps-jobs-display-status').textContent).toMatch(/final structure/)
  })

  it('Flexibility view deforms + recolours (applyScalarColors)', async () => {
    const dr = renderer(); await openWithCompletedSelected(dr)
    $('lammps-jobs-flex-toggle').click(); await flush()
    expect(api.getLammpsRmsf).toHaveBeenCalledWith('l1')
    expect(dr.applyFemPositions).toHaveBeenCalled()
    expect(dr.applyScalarColors).toHaveBeenCalled()
    expect($('lammps-jobs-flex-status').textContent).toMatch(/RMSF/)
  })

  it('Deviation view recolours by distance from design', async () => {
    const dr = renderer(); await openWithCompletedSelected(dr)
    $('lammps-jobs-deviation-toggle').click(); await flush()
    expect(api.getLammpsDeviation).toHaveBeenCalledWith('l1')
    expect(dr.applyScalarColors).toHaveBeenCalled()
    expect($('lammps-jobs-deviation-status').textContent).toContain('mean 0.30 nm')
  })

  it('Trajectory view shows controls + scrubs frames onto the model', async () => {
    const dr = renderer(); await openWithCompletedSelected(dr)
    $('lammps-jobs-traj-toggle').click(); await flush()
    expect(api.getLammpsTrajectory).toHaveBeenCalledWith('l1')
    expect($('lammps-jobs-traj-controls').style.display).not.toBe('none')
    expect(dr.applyFemPositions).toHaveBeenCalled()   // frame 0 applied
    // scrub the slider → another frame applied
    const before = dr.applyFemPositions.mock.calls.length
    const slider = $('lammps-jobs-traj-slider'); slider.value = '2'; slider.dispatchEvent(new Event('input'))
    expect(dr.applyFemPositions.mock.calls.length).toBeGreaterThan(before)
  })

  it('Off restores the design model', async () => {
    const dr = renderer(); await openWithCompletedSelected(dr)
    $('lammps-jobs-display-toggle').click(); await flush()
    $('lammps-jobs-viz-off').click()
    expect(dr.applyFemPositions).toHaveBeenLastCalledWith(null)
  })

  it('a not-ready view (design mismatch) reports the reason and reverts to Off', async () => {
    api.getLammpsDisplay.mockResolvedValueOnce({ ready: false, reason: 'the loaded design has 10 nucleotides but this run used 1' })
    const dr = renderer(); await openWithCompletedSelected(dr)
    $('lammps-jobs-display-toggle').click(); await flush()
    expect($('lammps-jobs-display-status').textContent).toMatch(/but this run used/)
    expect($('lammps-jobs-viz-off').checked).toBe(true)
  })
})

// UNIFIED-PANEL UPDATE (was the U3 slice 2c-2 collapse parity): the per-engine
// section no longer collapses — the *Simulate* header owns the one collapse and the
// LAMMPS header is a static label (`collapsible:false`). These pin the new invariant:
// the panel is PERMANENTLY OPEN (heading click is a no-op, views are NOT torn down),
// the advanced drawer still works, and the poll runs whenever a run is active.
describe('initLammpsJobsPanel — permanently-open section (no per-engine collapse)', () => {
  it('the heading click does not collapse the section or tear down views', async () => {
    const detachGizmo = vi.fn()
    api.listLammpsJobs.mockResolvedValue(COMPLETED)
    initLammpsJobsPanel({
      designRenderer: renderer(), getWorkspacePath: () => WS,
      forcesSetup: { getForces: () => ({ field: null, anchors: [], wall: null }), fieldNeedsAnchor: () => false, detachGizmo },
    })
    await flush()
    expect($('lammps-jobs-body').style.display).not.toBe('none')     // open on init
    ;[...$('lammps-jobs-list').children][0].click(); await flush()   // select the run
    $('lammps-jobs-display-toggle').click(); await flush()           // turn a view ON
    expect($('lammps-jobs-viz-off').checked).toBe(false)
    openPanel()                                                      // heading click → no-op
    expect($('lammps-jobs-body').style.display).not.toBe('none')     // still open
    expect($('lammps-jobs-viz-off').checked).toBe(false)            // view NOT torn down
    expect(detachGizmo).not.toHaveBeenCalled()
  })

  it('the advanced-drawer toggle shows/hides its body and flips the text arrow', async () => {
    initLammpsJobsPanel({ getWorkspacePath: () => WS }); await flush()
    const advBody = $('lammps-jobs-adv-body'), advArrow = $('lammps-jobs-adv-arrow')
    expect(advBody.style.display).toBe('none')
    $('lammps-jobs-adv-toggle').click()
    expect(advBody.style.display).toBe(''); expect(advArrow.textContent).toBe('▾')
    $('lammps-jobs-adv-toggle').click()
    expect(advBody.style.display).toBe('none'); expect(advArrow.textContent).toBe('▸')
  })

  it('polls while a run is active (section is always open)', async () => {
    api.listLammpsJobs.mockResolvedValue(RUNNING)
    initLammpsJobsPanel({ getWorkspacePath: () => WS }); await flush()
    const n0 = api.listLammpsJobs.mock.calls.length
    await vi.advanceTimersByTimeAsync(1500); await flush()
    expect(api.listLammpsJobs.mock.calls.length).toBeGreaterThan(n0)  // poll fired (open + active)
    const n1 = api.listLammpsJobs.mock.calls.length
    openPanel()                                                       // no collapse → poll keeps running
    await vi.advanceTimersByTimeAsync(1500); await flush()
    expect(api.listLammpsJobs.mock.calls.length).toBeGreaterThan(n1)
  })
})
