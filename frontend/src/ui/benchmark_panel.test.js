/**
 * Unit tests for the Dynamics-panel Benchmark controls.
 *
 *   initBenchmarkPanel — factory wiring, jsdom DOM + mocked api client.
 *   Covers: collapsible card, a full sweep (start → poll → completed → apply fills
 *   inputs + saves), the loading-bar/ETA + spinner, Cancel (kills + keeps defaults),
 *   the single-config "nothing to compare" guard, and panel-locking during a run.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { initBenchmarkPanel } from './benchmark_panel.js'

function makeApi(overrides = {}) {
  return {
    // Default: a 2-config oxDNA grid + 4-config NAMD grid (so no "nothing to compare").
    benchmarkHardware: vi.fn(async () => ({
      oxdna_grid: ['CPU', 'CUDA:0'], namd_grid: ['+p4 CPU', '+p4 GPU:0', '+p8 CPU', '+p8 GPU:0'],
    })),
    startOxdnaBenchmark: vi.fn(async () => ({ benchmark_id: 'b1', trials_total: 2 })),
    startNamdBenchmark: vi.fn(async () => ({ benchmark_id: 'n1', trials_total: 2 })),
    getBenchmark: vi.fn(),
    applyBenchmark: vi.fn(async () => ({ hostname: 'host', saved_to: '/ws/foo.nadoc' })),
    cancelBenchmark: vi.fn(async () => ({ cancelled: true })),
    ...overrides,
  }
}

beforeEach(() => {
  // ox-mount/md-mount live inside the real panel sections so _lockPanels can find
  // sibling controls (the "other" buttons) to disable.
  document.body.innerHTML = `
    <div id="oxdna-jobs-panel">
      <button id="ox-other-btn">Relax</button>
      <select id="oxdna-jobs-backend"><option>CUDA</option><option>CPU</option></select>
      <input id="oxdna-jobs-device" value="0">
      <div id="ox-mount"></div>
    </div>
    <div id="md-jobs-panel">
      <button id="md-other-btn">Relax</button>
      <input id="md-jobs-threads" value="16">
      <input id="md-jobs-devices" value="0">
      <div id="md-mount"></div>
    </div>`
})

describe('mount — collapsible card', () => {
  it('renders a collapsed Benchmark card into each mount and toggles open', () => {
    const panel = initBenchmarkPanel({ api: makeApi(), sleep: async () => {} })
    panel.mountOxdna(document.getElementById('ox-mount'))
    const card = document.querySelector('#ox-mount .bench-card')
    const body = card.querySelector('.bench-card__body')
    expect(card).toBeTruthy()
    expect(body.style.display).toBe('none')           // collapsed by default
    card.querySelector('.bench-card__header').click()
    expect(body.style.display).toBe('')               // expands on header click
  })
})

describe('oxDNA sweep', () => {
  it('polls to completion, shows winner + progress, Apply fills inputs + saves', async () => {
    const api = makeApi({
      getBenchmark: vi.fn()
        .mockResolvedValueOnce({ state: 'running', trials_done: 1, trials_total: 2,
          fraction: 0.5, eta_seconds: 3, current_label: 'CUDA:0', results: [] })
        .mockResolvedValueOnce({ state: 'completed', trials_done: 2, trials_total: 2,
          fraction: 1, results: [
            { label: 'CPU', backend: 'CPU', device: '0', steps_per_s: 100 },
            { label: 'CUDA:0', backend: 'CUDA', device: '0', steps_per_s: 900 },
          ],
          recommendation: { backend: 'CUDA', device: '0', steps_per_s: 900 },
          note: 'measured on a 1200-nt proxy' }),
    })
    const panel = initBenchmarkPanel({ api, getWorkspacePath: () => '/ws/foo.nadoc', sleep: async () => {} })
    const el = document.getElementById('ox-mount')
    panel.mountOxdna(el)

    const state = await panel.runSweep('oxdna', el)
    expect(state.state).toBe('completed')
    expect(api.startOxdnaBenchmark).toHaveBeenCalledWith({ design_source_path: '/ws/foo.nadoc' })
    expect(el.querySelector('.bench-status').textContent).toContain('CUDA')
    expect(el.querySelector('.bench-results').textContent).toContain('900')
    expect(el.querySelector('.bench-note').textContent).toContain('proxy')
    expect(el.querySelector('.bench-bar-fill').style.width).toBe('100%')
    // Spinner + progress hidden after completion.
    expect(el.querySelector('.bench-spinner').style.display).toBe('none')
    expect(el.querySelector('.bench-progress').style.display).toBe('none')

    const applyBtn = el.querySelector('.bench-apply-btn')
    expect(applyBtn.style.display).not.toBe('none')
    applyBtn.click()
    await Promise.resolve(); await Promise.resolve()
    expect(api.applyBenchmark).toHaveBeenCalledWith('b1', { design_source_path: '/ws/foo.nadoc' })
    expect(document.getElementById('oxdna-jobs-backend').value).toBe('CUDA')
    expect(document.getElementById('oxdna-jobs-device').value).toBe('0')
  })

  it('locks other panel buttons during the run and restores after', async () => {
    const seen = {}
    const api = makeApi({
      getBenchmark: vi.fn().mockResolvedValue({ state: 'completed', trials_done: 1, trials_total: 1,
        fraction: 1, results: [{ label: 'CPU', backend: 'CPU', device: '0', steps_per_s: 5 }],
        recommendation: { backend: 'CPU', device: '0', steps_per_s: 5 }, note: '' }),
      // Record lock state right when the sweep starts (mid-run).
      startOxdnaBenchmark: vi.fn(async () => {
        seen.oxLocked = document.getElementById('ox-other-btn').disabled
        seen.mdLocked = document.getElementById('md-other-btn').disabled
        return { benchmark_id: 'b1', trials_total: 1 }
      }),
    })
    const panel = initBenchmarkPanel({ api, sleep: async () => {} })
    const el = document.getElementById('ox-mount')
    panel.mountOxdna(el)
    await panel.runSweep('oxdna', el)
    expect(seen.oxLocked).toBe(true)                  // both panels locked mid-run
    expect(seen.mdLocked).toBe(true)
    expect(document.getElementById('ox-other-btn').disabled).toBe(false)   // restored
    expect(document.getElementById('md-other-btn').disabled).toBe(false)
  })

  it('reports a failed sweep without showing Apply', async () => {
    const api = makeApi({
      getBenchmark: vi.fn().mockResolvedValue({ state: 'failed', error: 'no oxDNA binary',
        trials_done: 0, trials_total: 2, fraction: 0, results: [] }),
    })
    const panel = initBenchmarkPanel({ api, sleep: async () => {} })
    const el = document.getElementById('ox-mount')
    panel.mountOxdna(el)
    await panel.runSweep('oxdna', el)
    expect(el.querySelector('.bench-status').textContent).toContain('failed')
    expect(el.querySelector('.bench-apply-btn').style.display).toBe('none')
    expect(document.getElementById('ox-other-btn').disabled).toBe(false)   // unlocked even on failure
  })
})

describe('cancel', () => {
  it('Cancel kills the run, calls the API, and keeps defaults (no Apply)', async () => {
    let polls = 0
    const api = makeApi({
      getBenchmark: vi.fn(async () => {
        polls += 1
        return polls === 1
          ? { state: 'running', trials_done: 1, trials_total: 2, fraction: 0.5, results: [] }
          : { state: 'cancelled', trials_done: 1, trials_total: 2, fraction: 0.5, results: [] }
      }),
    })
    const el = document.getElementById('ox-mount')
    let cancelClicked = false
    // During the first poll's sleep, click Cancel.
    const sleep = async () => {
      if (!cancelClicked) { cancelClicked = true; el.querySelector('.bench-cancel-btn').click(); await Promise.resolve() }
    }
    const panel = initBenchmarkPanel({ api, sleep })
    panel.mountOxdna(el)
    const state = await panel.runSweep('oxdna', el)
    expect(api.cancelBenchmark).toHaveBeenCalledWith('b1')
    expect(state.state).toBe('cancelled')
    expect(el.querySelector('.bench-status').textContent).toContain('kept existing defaults')
    expect(el.querySelector('.bench-apply-btn').style.display).toBe('none')
    expect(document.getElementById('ox-other-btn').disabled).toBe(false)
  })
})

describe('dummy-proof single-config guard', () => {
  it('warns and aborts when only one config exists and the user declines', async () => {
    const api = makeApi({ benchmarkHardware: vi.fn(async () => ({ oxdna_grid: ['CPU'], namd_grid: ['+p4 CPU'] })) })
    const confirm = vi.fn(() => false)
    const panel = initBenchmarkPanel({ api, confirm, sleep: async () => {} })
    const el = document.getElementById('ox-mount')
    panel.mountOxdna(el)
    const r = await panel.runSweep('oxdna', el)
    expect(confirm).toHaveBeenCalled()
    expect(r).toBeNull()
    expect(api.startOxdnaBenchmark).not.toHaveBeenCalled()
    expect(el.querySelector('.bench-status').textContent).toContain('nothing to compare')
  })

  it('proceeds when the user accepts the single-config warning', async () => {
    const api = makeApi({
      benchmarkHardware: vi.fn(async () => ({ oxdna_grid: ['CPU'], namd_grid: ['+p4 CPU'] })),
      getBenchmark: vi.fn().mockResolvedValue({ state: 'completed', trials_done: 1, trials_total: 1,
        fraction: 1, results: [{ label: 'CPU', backend: 'CPU', device: '0', steps_per_s: 5 }],
        recommendation: { backend: 'CPU', device: '0', steps_per_s: 5 }, note: '' }),
    })
    const panel = initBenchmarkPanel({ api, confirm: () => true, sleep: async () => {} })
    const el = document.getElementById('ox-mount')
    panel.mountOxdna(el)
    await panel.runSweep('oxdna', el)
    expect(api.startOxdnaBenchmark).toHaveBeenCalled()
  })
})

describe('start failure', () => {
  it('handles a null start response (engine not installed)', async () => {
    const api = makeApi({ startOxdnaBenchmark: vi.fn(async () => null) })
    const panel = initBenchmarkPanel({ api, sleep: async () => {} })
    const el = document.getElementById('ox-mount')
    panel.mountOxdna(el)
    const r = await panel.runSweep('oxdna', el)
    expect(r).toBeNull()
    expect(el.querySelector('.bench-status').textContent).toContain('Could not start')
    expect(api.getBenchmark).not.toHaveBeenCalled()
    expect(document.getElementById('ox-other-btn').disabled).toBe(false)
  })
})
