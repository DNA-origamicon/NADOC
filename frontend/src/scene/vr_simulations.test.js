// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { simulationControls, simulationViewActive, createVRSimulations } from './vr_simulations.js'
function mount() {
  document.body.innerHTML = `<div id="simulate-jobs-list"><div data-job-id="complete">Completed result</div></div>
    <div id="cando-display-card"><label><input name="mode" type="radio" value="off" checked>Off</label>
    <label><input name="mode" type="radio" value="deform">Predicted shape</label>
    <label><input name="mode" type="radio" value="flex" disabled>RMSF unavailable</label>
    <label><input name="mode" type="radio" value="trajectory">Trajectory</label>
    <label>Metric<select id="metric"><option value="a">A</option><option value="b">B</option></select></label>
    <label>Opacity<input id="opacity" type="number" min="0" max="1" step="0.1" value="1"></label></div>`
}
it('keeps disabled result choices, excludes trajectories, and reflects checked state', () => {
  mount();const choices = simulationControls(document, 'cando')
  expect(choices.find(c => c.label === 'RMSF unavailable').enabled).toBe(false)
  expect(choices.some(c => /Trajectory/.test(c.label))).toBe(false)
  expect(simulationViewActive(document)).toBe(false)
  document.querySelector('[value="deform"]').click()
  expect(simulationViewActive(document)).toBe(true)
  expect(choices.filter(c => c.element.id === 'metric')).toHaveLength(2)
})
describe('desktop action bridge', () => {
  it('rejects stale snapshots, deduplicates trigger events, and dispatches normal controls', async () => {
    mount();const requests = [], changed = vi.fn()
    document.querySelector('[value="deform"]').addEventListener('change', changed)
    const selected = { id: 'complete', engine: 'cando' }
    const bridge = createVRSimulations({ jobs: { getSelected: () => selected, refresh: vi.fn() }, engineSelector: { getSelected: () => 'cando', select: vi.fn() }, request: async (_, init) => { requests.push(JSON.parse(init.body));return { ok: true } } })
    await bridge.publish()
    const first = requests.at(-1), id = first.controls.find(c => c.label === 'Predicted shape').id
    await bridge.activate({ sequence: 1, version: first.version, id })
    expect(changed).toHaveBeenCalledTimes(1)
    await bridge.activate({ sequence: 1, version: first.version, id })
    expect(changed).toHaveBeenCalledTimes(1)
    document.querySelector('[value="deform"]').checked = false
    await bridge.activate({ sequence: 2, version: first.version, id })
    expect(changed).toHaveBeenCalledTimes(1)
    expect(requests.at(-1).acknowledged).toBe(2)
    selected.id = 'another-job'
    expect(bridge.snapshot().controls).toEqual([])
  })
  it('selects the actual job row, changes select values, and clamps numeric options', async () => {
    mount();const selected = { id: '', engine: 'cando' }, clicked = vi.fn(() => { selected.id = 'complete' })
    document.querySelector('[data-job-id]').addEventListener('click', clicked)
    let state
    const bridge = createVRSimulations({ jobs: { getSelected: () => selected }, engineSelector: { getSelected: () => 'cando' }, request: async (_, init) => { state = JSON.parse(init.body);return { ok: true } } })
    await bridge.publish();await bridge.activate({ sequence: 1, version: state.version, id: state.jobs[0].id })
    expect(clicked).toHaveBeenCalledTimes(1)
    const b = bridge.snapshot().controls.find(c => c.value === 'b')
    await bridge.activate({ sequence: 2, version: state.version, id: b.id })
    expect(document.getElementById('metric').value).toBe('b')
    const plus = bridge.snapshot().controls.find(c => c.delta === 1)
    await bridge.activate({ sequence: 3, version: state.version, id: plus.id })
    expect(document.getElementById('opacity').value).toBe('1')
  })
})
it('does not confuse a solvent-scope radio with an active simulation view', () => {
  document.body.innerHTML = '<div id="md-jobs-viz-body"><input name="md-viz" type="radio" value="off" checked><input name="water-scope" type="radio" value="shell" checked></div>'
  expect(simulationViewActive(document)).toBe(false)
})
it('acknowledges an event arriving while the previous snapshot is still in flight', async () => {
  mount(); let release, sent = []
  const bridge = createVRSimulations({ jobs: { getSelected: () => ({ id: 'complete' }) }, engineSelector: { getSelected: () => 'cando' }, request: async (_, init) => {
    sent.push(JSON.parse(init.body))
    if (sent.length === 1) await new Promise(resolve => { release = resolve })
    return { ok: true }
  } })
  const pending = bridge.publish()
  await bridge.activate({ sequence: 8, version: 1, id: 'v:0' })
  release();await pending;await bridge.publish()
  expect(sent.at(-1).acknowledged).toBe(8)
  expect(sent).toHaveLength(2)
})
