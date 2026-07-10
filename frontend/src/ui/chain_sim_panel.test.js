// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { initChainSimPanel } from './chain_sim_panel.js'

// Minimal DOM the panel binds to (mirrors index.html #chain-sim-* ids).
function mountDom() {
  document.body.innerHTML = `
    <div id="chain-sim-panel">
      <h2 id="chain-sim-heading"><span>Chain Simulations</span><span id="chain-sim-arrow"></span></h2>
      <div id="chain-sim-body">
        <input id="chain-sim-enable" type="checkbox">
        <select id="chain-sim-project-select"></select>
        <input id="chain-sim-rename-input" type="text">
        <button id="chain-sim-new-btn">+</button>
        <button id="chain-sim-dup-btn">⧉</button>
        <button id="chain-sim-del-btn">×</button>
        <div id="chain-sim-queue"></div>
        <div id="chain-sim-total"></div>
        <button id="chain-sim-launch-btn"></button>
        <div id="chain-sim-status"></div>
      </div>
    </div>`
}

// A tiny fake store whose currentDesign.chain_sim_projects the fake api mutates.
function makeStore(design) {
  const state = { currentDesign: design }
  const subs = []
  return {
    getState: () => state,
    subscribeSlice: (_slice, fn) => { subs.push(fn) },
    _emit: () => subs.forEach((f) => f()),
    _setDesign: (d) => { state.currentDesign = d },
  }
}

function makeApi(store) {
  const design = () => store.getState().currentDesign
  return {
    createChainSimProject: vi.fn(async (name, stages = null) => {
      const proj = { id: `p${design().chain_sim_projects.length + 1}`, name, stages: stages || [] }
      design().chain_sim_projects.push(proj)
      store._emit()
      return design()
    }),
    setChainSimStages: vi.fn(async (id, stages) => {
      const p = design().chain_sim_projects.find((x) => x.id === id)
      if (p) p.stages = stages.map((s) => ({ ...s }))
      store._emit()
      return design()
    }),
    updateChainSimProject: vi.fn(async () => design()),
    deleteChainSimProject: vi.fn(async (id) => {
      design().chain_sim_projects = design().chain_sim_projects.filter((x) => x.id !== id)
      store._emit()
      return design()
    }),
    createChain: vi.fn(async () => ({ chain: { chain_id: 'c1', status: 'running', stages: [] } })),
    getMdChain: vi.fn(async () => ({ chain: { chain_id: 'c1', status: 'completed', stages: [] } })),
    lastErrorMessage: () => 'err',
  }
}

const oxRun = { field: null, surface: null, anchors: [] }

beforeEach(() => {
  mountDom()
  localStorage.clear()
})

describe('chain_sim_panel', () => {
  it('enable toggle fires nadoc:chain-mode-change and reports isEnabled', () => {
    const store = makeStore({ chain_sim_projects: [] })
    const panel = initChainSimPanel({ store, api: makeApi(store), engines: {} })
    const spy = vi.fn()
    window.addEventListener('nadoc:chain-mode-change', spy)
    expect(panel.isEnabled()).toBe(false)
    const box = document.getElementById('chain-sim-enable')
    box.checked = true
    box.dispatchEvent(new Event('change'))
    expect(panel.isEnabled()).toBe(true)
    expect(spy).toHaveBeenCalled()
  })

  it('enqueue auto-creates a project, adds a stage, and persists it', async () => {
    const store = makeStore({ chain_sim_projects: [] })
    const api = makeApi(store)
    const engines = { oxdna: { getRunElements: () => oxRun, getAdvanced: () => ({ steps: 1_000_000 }) } }
    const panel = initChainSimPanel({ store, api, engines })

    await panel.enqueue('oxdna', 'relax')
    expect(api.createChainSimProject).toHaveBeenCalledTimes(1)   // auto-created
    expect(api.setChainSimStages).toHaveBeenCalled()
    const rows = document.getElementById('chain-sim-queue').querySelectorAll('div[style*="cursor: pointer"]')
    expect(rows.length).toBe(1)
    // A relax stage is preflight-ok → green check.
    expect(document.getElementById('chain-sim-queue').textContent).toContain('✓')
  })

  it('a lone production stage renders a red ✕ and blocks Launch with a popup', async () => {
    const store = makeStore({ chain_sim_projects: [{ id: 'p1', name: 'P', stages: [] }] })
    const api = makeApi(store)
    const engines = { oxdna: { getRunElements: () => oxRun, getAdvanced: () => ({}) } }
    const panel = initChainSimPanel({ store, api, engines })

    await panel.enqueue('oxdna', 'production')
    const queue = document.getElementById('chain-sim-queue')
    expect(queue.textContent).toContain('✕')
    // Launch is enabled (has a stage) but createChain must NOT fire on an errored queue.
    document.getElementById('chain-sim-launch-btn').click()
    await Promise.resolve()
    expect(api.createChain).not.toHaveBeenCalled()
  })

  it('relax then production launches one chain', async () => {
    const store = makeStore({ chain_sim_projects: [{ id: 'p1', name: 'P', stages: [] }] })
    const api = makeApi(store)
    const engines = { oxdna: { getRunElements: () => oxRun, getAdvanced: () => ({ steps: 1e6 }) } }
    const panel = initChainSimPanel({ store, api, engines })

    await panel.enqueue('oxdna', 'relax')
    await panel.enqueue('oxdna', 'production')
    expect(document.getElementById('chain-sim-queue').textContent).toContain('seeds from stage 1')

    document.getElementById('chain-sim-launch-btn').click()
    await new Promise((r) => setTimeout(r, 0))
    expect(api.createChain).toHaveBeenCalledTimes(1)
    const payload = api.createChain.mock.calls[0][0]
    expect(payload.root_job_id).toBeNull()
    expect(payload.stages).toHaveLength(2)
  })

  it('refreshes the launched engine job list immediately after launch', async () => {
    const store = makeStore({ chain_sim_projects: [{ id: 'p1', name: 'P', stages: [] }] })
    const api = makeApi(store)
    const refreshJobs = vi.fn()
    const engines = { oxdna: { getRunElements: () => oxRun, getAdvanced: () => ({}), refreshJobs } }
    const panel = initChainSimPanel({ store, api, engines })

    await panel.enqueue('oxdna', 'relax')
    document.getElementById('chain-sim-launch-btn').click()
    await new Promise((r) => setTimeout(r, 0))
    // The spawned stage-0 job must be pulled into the oxDNA panel's list at once.
    expect(refreshJobs).toHaveBeenCalled()
  })

  it('clicking a queue row echoes the stage field/surface/anchors into the engine (glow/arrow/surface) + switches engine', async () => {
    const store = makeStore({ chain_sim_projects: [{ id: 'p1', name: 'P', stages: [] }] })
    const api = makeApi(store)
    const applyRunConfig = vi.fn()
    const selectEngine = vi.fn()
    // getRunElements returns a field + surface + anchors, exactly the shape the oxDNA
    // Simulate cards emit; enqueue must capture them and a row-click must feed them back
    // to applyRunConfig — the SAME call the real job-select makes (→ purple glow, field
    // arrow, surface grid).
    const runEl = {
      field: { enabled: true, field_pN: 5, dir: [1, 0, 0] },
      surface: { enabled: true, dir: [0, 0, 1], offsetNm: 1.5, stiff: 5 },
      anchors: [{ strand_id: 's1' }],
    }
    const engines = { oxdna: { getRunElements: () => runEl, applyRunConfig, getAdvanced: () => ({ steps: 2e6 }) } }
    const panel = initChainSimPanel({ store, api, engines, selectEngine })

    await panel.enqueue('oxdna', 'production')
    const row = document.querySelector('#chain-sim-queue > div')
    row.click()

    expect(selectEngine).toHaveBeenCalledWith('oxdna')
    expect(applyRunConfig).toHaveBeenCalledTimes(1)
    const cfg = applyRunConfig.mock.calls[0][0]
    expect(cfg.field).toEqual({ field_pN: 5, dir: [1, 0, 0] })            // arrow: dir + magnitude
    expect(cfg.surface).toEqual({ dir: [0, 0, 1], offset_nm: 1.5, stiff: 5 }) // surface toggles on
    expect(cfg.anchors).toEqual([{ strand_id: 's1' }])                    // purple glow
  })

  it('after launch, each queue row tracks its stage live status + a health dot', async () => {
    // Preload a project with known stage ids so we can map chain stages back to rows.
    const design = { chain_sim_projects: [{ id: 'p1', name: 'P', stages: [
      { id: 'a', engine: 'oxdna', protocol: 'relax' },
      { id: 'b', engine: 'oxdna', protocol: 'production' },
    ] }] }
    const store = makeStore(design)
    const api = makeApi(store)
    // Launch → one chain; poll returns stage 0 running (healthy) + stage 1 queued.
    api.createChain = vi.fn(async () => ({ chain: { chain_id: 'c1', status: 'running', stages: [] } }))
    api.getMdChain = vi.fn(async () => ({ chain: { chain_id: 'c1', status: 'running', stages: [
      { index: 0, engine: 'oxdna', status: 'running', job_id: 'j0' },
      { index: 1, engine: 'oxdna', status: 'pending', job_id: null },
    ] } }))
    api.getOxdnaJob = vi.fn(async () => ({ job_id: 'j0', health_samples: [{ passed: true, reason: 'ok' }] }))
    const engines = { oxdna: { getRunElements: () => oxRun, applyRunConfig: vi.fn(), getAdvanced: () => ({}) } }
    const panel = initChainSimPanel({ store, api, engines, getDesignSourcePath: () => '/ws/d.nadoc' })

    document.getElementById('chain-sim-launch-btn').click()
    // let launch + the first poll tick (getMdChain → getOxdnaJob → render) settle
    for (let k = 0; k < 6; k++) await new Promise((r) => setTimeout(r, 0))

    // design_source_path is stamped onto the chain request.
    expect(api.createChain.mock.calls[0][0].design_source_path).toBe('/ws/d.nadoc')
    const rows = document.querySelectorAll('#chain-sim-queue > div')
    expect(rows.length).toBe(2)
    expect(rows[0].textContent).toContain('⟳')   // stage 0 running
    expect(rows[0].textContent).toContain('running')
    expect(rows[0].querySelector('span[title="ok"]')).toBeTruthy()   // green health dot
    expect(rows[1].textContent).toContain('○')   // stage 1 queued
  })

  it('pushes a stage into the engine job list as soon as it STARTS mid-chain (not just at launch)', async () => {
    vi.useFakeTimers()
    try {
      const design = { chain_sim_projects: [{ id: 'p1', name: 'P', stages: [
        { id: 'a', engine: 'oxdna', protocol: 'relax' },
        { id: 'b', engine: 'oxdna', protocol: 'production' },
      ] }] }
      const store = makeStore(design)
      const api = makeApi(store)
      const refreshJobs = vi.fn()
      api.createChain = vi.fn(async () => ({ chain: { chain_id: 'c1', status: 'running', stages: [] } }))
      // Poll 1: stage 0 running (job j0). Poll 2: stage 0 done, stage 1 now running (job j1).
      const polls = [
        { chain: { chain_id: 'c1', status: 'running', stages: [
          { index: 0, engine: 'oxdna', status: 'running', job_id: 'j0' },
          { index: 1, engine: 'oxdna', status: 'pending', job_id: null } ] } },
        { chain: { chain_id: 'c1', status: 'running', stages: [
          { index: 0, engine: 'oxdna', status: 'done', job_id: 'j0' },
          { index: 1, engine: 'oxdna', status: 'running', job_id: 'j1' } ] } },
      ]
      let call = 0
      api.getMdChain = vi.fn(async () => polls[Math.min(call++, polls.length - 1)])
      api.getOxdnaJob = vi.fn(async () => ({ job_id: 'x', health_samples: [] }))
      const engines = { oxdna: { getRunElements: () => oxRun, applyRunConfig: vi.fn(), getAdvanced: () => ({}), refreshJobs } }
      initChainSimPanel({ store, api, engines, getDesignSourcePath: () => '/ws/d.nadoc' })

      document.getElementById('chain-sim-launch-btn').click()
      await vi.advanceTimersByTimeAsync(1)        // launch + first poll → stage 0 (j0) starts
      const afterStage0 = refreshJobs.mock.calls.length
      expect(afterStage0).toBeGreaterThan(0)
      await vi.advanceTimersByTimeAsync(4000)      // next poll → stage 1 (j1) starts
      expect(refreshJobs.mock.calls.length).toBeGreaterThan(afterStage0)   // j1 pushed on START
    } finally {
      vi.useRealTimers()
    }
  })

  it('clicking a LAUNCHED queue row selects the real job in the engine list (not just the plan echo)', async () => {
    const design = { chain_sim_projects: [{ id: 'p1', name: 'P', stages: [
      { id: 'a', engine: 'oxdna', protocol: 'relax' },
    ] }] }
    const store = makeStore(design)
    const api = makeApi(store)
    api.createChain = vi.fn(async () => ({ chain: { chain_id: 'c1', status: 'running', stages: [] } }))
    api.getMdChain = vi.fn(async () => ({ chain: { chain_id: 'c1', status: 'running', stages: [
      { index: 0, engine: 'oxdna', status: 'running', job_id: 'j0' } ] } }))
    api.getOxdnaJob = vi.fn(async () => ({ job_id: 'j0', health_samples: [] }))
    const selectJob = vi.fn()
    const applyRunConfig = vi.fn()
    const engines = { oxdna: { getRunElements: () => oxRun, applyRunConfig, selectJob, refreshJobs: vi.fn(), getAdvanced: () => ({}) } }
    initChainSimPanel({ store, api, engines, selectEngine: vi.fn(), getDesignSourcePath: () => '/ws/d.nadoc' })

    document.getElementById('chain-sim-launch-btn').click()
    for (let k = 0; k < 6; k++) await new Promise((r) => setTimeout(r, 0))   // launch + first poll realises j0
    applyRunConfig.mockClear()
    document.querySelector('#chain-sim-queue > div').click()
    expect(selectJob).toHaveBeenCalledWith('j0')     // selects the REAL job (highlight + cards)
    expect(applyRunConfig).not.toHaveBeenCalled()    // the plan-echo path is superseded
  })

  it('the ✎ update button overwrites a stage with the engine’s current settings (keeps id + position)', async () => {
    const store = makeStore({ chain_sim_projects: [{ id: 'p1', name: 'P', stages: [] }] })
    const api = makeApi(store)
    // Initial cards → field A. Enqueue captures it.
    let runEl = { field: { enabled: true, field_pN: 5, dir: [0, -1, 0] }, surface: null, anchors: [] }
    const engines = { oxdna: { getRunElements: () => runEl, applyRunConfig: vi.fn(), getAdvanced: () => ({ steps: 1e6 }) } }
    const panel = initChainSimPanel({ store, api, engines, selectEngine: vi.fn() })

    await panel.enqueue('oxdna', 'production')
    const q = document.getElementById('chain-sim-queue')
    expect(q.textContent).toContain('E 5.0')                       // captured field A
    const idBefore = api.setChainSimStages.mock.calls[0][1][0].id

    // Reconfigure the cards → field B (re-aimed + stronger) + an anchor, then click ✎.
    runEl = { field: { enabled: true, field_pN: 9, dir: [1, 0, 0] }, surface: null, anchors: [{ strand_id: 's1' }] }
    const updateBtn = [...q.querySelectorAll('button')].find((b) => b.textContent === '✎')
    updateBtn.click()
    await Promise.resolve()

    const saved = api.setChainSimStages.mock.calls.at(-1)[1]
    expect(saved).toHaveLength(1)
    expect(saved[0].id).toBe(idBefore)                            // same stage, updated in place
    expect(saved[0].field).toEqual({ field_pN: 9, dir: [1, 0, 0] })  // now field B
    expect(saved[0].anchors).toEqual([{ strand_id: 's1' }])          // captured the new anchor
    expect(q.textContent).toContain('E 9.0')                       // row re-rendered with field B
    expect(q.textContent).toContain('⚓1')
  })

  it('clicking a relax row (no field/surface/anchors) clears the echo so a prior stage does not linger', async () => {
    const store = makeStore({ chain_sim_projects: [{ id: 'p1', name: 'P', stages: [] }] })
    const api = makeApi(store)
    const applyRunConfig = vi.fn()
    const engines = { oxdna: { getRunElements: () => oxRun, applyRunConfig, getAdvanced: () => ({}) } }
    const panel = initChainSimPanel({ store, api, engines, selectEngine: vi.fn() })

    await panel.enqueue('oxdna', 'relax')   // oxRun has no field/surface/anchors
    document.querySelector('#chain-sim-queue > div').click()
    const cfg = applyRunConfig.mock.calls[0][0]
    expect(cfg.field).toBeNull()
    expect(cfg.surface).toBeNull()
    expect(cfg.anchors).toBeNull()
  })
})
