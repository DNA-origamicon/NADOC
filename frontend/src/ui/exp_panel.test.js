// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createExpPreview, initExpPanel } from './exp_panel.js'

let panel
afterEach(() => { panel?.dispose(); vi.useRealTimers(); document.body.innerHTML = '' })
function setup(request, getCurrentRepr = () => 'full', state = {}) {
  document.body.innerHTML = '<button id="exp-run">Run</button><progress id="exp-progress" max="1" value="0"></progress><div id="exp-status"></div><input id="exp-viz" type="checkbox" disabled><div id="simulate-jobs"></div>'
  const preview = { show: vi.fn(), clear: vi.fn() }
  const api = { prepareExpPrediction: vi.fn() }
  let subscriber
  panel = initExpPanel({ request, preview, api, getCurrentRepr, store: { getState: () => state, subscribe(fn) { subscriber = fn; return () => {} } } })
  return { preview, api, changed: () => subscriber({ currentDesign: {} }, { currentDesign: {} }) }
}
const response = data => ({ ok: true, json: async () => data })
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve() }
const clickRun = () => document.getElementById('exp-run').click()

describe('Exp screening controls', () => {
  it('reports missing weights without materializing or launching anything', async () => {
    const request = vi.fn(async () => response({ available: false, message: 'No trained model installed.' }))
    const { api } = setup(request)
    clickRun(); await flush()
    expect(request).toHaveBeenCalledTimes(1)
    expect(api.prepareExpPrediction).not.toHaveBeenCalled()
    expect(document.getElementById('exp-status').textContent).toContain('No trained model')
    expect(document.getElementById('exp-progress').value).toBe(0)
    expect(document.getElementById('exp-viz').disabled).toBe(true)
    expect(document.getElementById('exp-run').textContent).toBe('Run')
  })

  it('only previews on opt-in and discards results after a design change', async () => {
    const result = { positions_nm: [[0, 0, 0]], label: 'fixture' }
    const request = vi.fn(async url => response(url.endsWith('/status') ? { available: true } :
      { job_id: 'test', status: 'completed', progress: 1, message: 'Complete', result }))
    const { preview, changed } = setup(request)
    clickRun(); await flush()
    expect(preview.show).not.toHaveBeenCalled()
    document.getElementById('exp-viz').click()
    expect(preview.show).toHaveBeenCalledWith(result, null)
    window.dispatchEvent(new CustomEvent('nadoc:simulation-engine', { detail: { engine: 'namd' } }))
    expect(document.getElementById('exp-viz').checked).toBe(false)
    changed()
    expect(document.getElementById('exp-viz').disabled).toBe(true)
    expect(preview.clear).toHaveBeenCalled()
  })

  it('Stop while launch is pending cancels the returned job and shows no late result', async () => {
    let resolveLaunch
    const request = vi.fn(url => {
      if (url.endsWith('/status')) return Promise.resolve(response({ available: true }))
      if (url.endsWith('/stop')) return Promise.resolve(response({ status: 'stopped' }))
      return new Promise(resolve => { resolveLaunch = resolve })
    })
    setup(request)
    clickRun(); await flush()
    clickRun()
    resolveLaunch(response({ job_id: 'late', status: 'running' }))
    await flush()
    expect(request.mock.calls.some(([url]) => url.endsWith('/late/stop'))).toBe(true)
    expect(document.getElementById('exp-viz').disabled).toBe(true)
    expect(document.getElementById('exp-status').textContent).toBe('Stopped')
  })

  it('shows backend progress and polls to completion', async () => {
    vi.useFakeTimers()
    const request = vi.fn(async (url, opts) => response(url.endsWith('/status') ? { available: true } :
      opts.method === 'POST' ? { job_id: 'test', status: 'running', progress: .35, message: 'Predicting' } :
        { job_id: 'test', status: 'completed', progress: 1, message: 'Done', result: { positions_nm: [[1, 2, 3]], label: 'fixture' } }))
    setup(request)
    clickRun(); await flush()
    expect(document.getElementById('exp-progress').value).toBe(.35)
    await vi.advanceTimersByTimeAsync(400)
    expect(document.getElementById('exp-progress').value).toBe(1)
    expect(document.getElementById('exp-viz').disabled).toBe(false)
  })
})

it('moves the existing Full model using atom-derived NAMD frames and restores only its own preview', () => {
  const renderer = { applyFemPositions: vi.fn() }
  const preview = createExpPreview(renderer)
  preview.clear()
  expect(renderer.applyFemPositions).not.toHaveBeenCalled()
  preview.show({ full: { keys: [['h', 5, 'FORWARD', 0]], frame: [1, 2, 3, 1, 0, 0, 0, 0, 1, 2, 2, 3] } })
  expect(renderer.applyFemPositions).toHaveBeenLastCalledWith([expect.objectContaining({
    helix_id: 'h', bp_index: 5, backbone_position: [1, 2, 3],
    base_position: [2, 2, 3], tx: 0, ty: 0, tz: 1, measured_base: true,
  })])
  preview.clear()
  expect(renderer.applyFemPositions).toHaveBeenLastCalledWith(null)
  preview.clear()
  expect(renderer.applyFemPositions).toHaveBeenCalledTimes(2)
})

it('enables predictions only in Full and restores native positions on representation changes', async () => {
  let representation = 'atomistic'
  const result = { label: 'fixture' }
  const request = vi.fn(async url => response(url.endsWith('/status') ? { available: true } :
    { job_id: 'test', status: 'completed', progress: 1, message: 'Complete', result }))
  const { preview } = setup(request, () => representation)
  clickRun(); await flush()
  const viz = document.getElementById('exp-viz')
  expect(viz.disabled).toBe(true)
  const change = repr => {
    representation = repr
    window.dispatchEvent(new CustomEvent('nadoc:representation-change', { detail: { representation: repr } }))
  }
  change('full')
  expect(viz.disabled).toBe(false)
  viz.click()
  expect(preview.show).toHaveBeenCalledWith(result, null)
  change('oxdna')
  expect(viz.disabled).toBe(true)
  expect(viz.checked).toBe(false)
  expect(preview.clear).toHaveBeenCalled()
  change('full')
  expect(viz.disabled).toBe(false)
  expect(viz.checked).toBe(false)
})

it('uses a frozen Full model and shared visibility ownership for an assembly preview', () => {
  const renderer = { applyFemPositions: vi.fn(), renderExternalGeometry: vi.fn(), clearExternalGeometry: vi.fn() }
  const setVisible = vi.fn(), restoreNative = vi.fn()
  const preview = createExpPreview(renderer, { setVisible, restoreNative })
  const snapshot = { design: { id: 'flattened' }, nucleotides: [{ helix_id: 'part:h' }], helix_axes: [] }
  preview.show({ full: { keys: [['part:h', 0, 'FORWARD', 0]], frame: [1, 2, 3, 1, 0, 0, 0, 0, 1, 2, 2, 3] } }, snapshot)
  expect(renderer.renderExternalGeometry).toHaveBeenCalledWith(snapshot.design, snapshot.nucleotides, {})
  expect(setVisible).toHaveBeenCalledWith(true)
  preview.clear()
  expect(renderer.clearExternalGeometry).toHaveBeenCalled()
  expect(restoreNative).toHaveBeenCalledOnce()
})

it('loads the frozen assembly display model without replacing the authoring store', async () => {
  const snapshot = { design: { id: 'frozen' }, nucleotides: [{}], helix_axes: [] }
  const result = { label: 'assembly result' }
  const state = { assemblyActive: true, currentAssembly: { id: 'authored' } }
  const request = vi.fn(async url => response(url.endsWith('/status') ? { available: true } :
    url.endsWith('/snapshot-geometry') ? snapshot :
      { job_id: 'test', status: 'completed', progress: 1, message: 'Complete', result }))
  const { preview } = setup(request, () => 'full', state)
  clickRun(); await flush()
  document.getElementById('exp-viz').click()
  expect(preview.show).toHaveBeenCalledWith(result, snapshot)
  expect(state).toEqual({ assemblyActive: true, currentAssembly: { id: 'authored' } })
})
