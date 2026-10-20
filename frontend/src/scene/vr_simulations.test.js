// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { simulationControls, simulationViewActive, createVRSimulations } from './vr_simulations.js'
import { simulationJobSummary, simulationProgress } from './vr_simulation_controls.js'
it('shows observed completion time, running progress, and finished relaxation state', () => {
  expect(simulationJobSummary({status:'running',progress_fraction:.723})).toBe('72%')
  expect(simulationJobSummary({status:'completed',segments:[{stage:'production',completed_ns:24.5},{stage:'production',completed_ns:1.25}]})).toBe('25.75 ns')
  expect(simulationJobSummary({status:'completed',segments:[{stage:'relaxation',status:'done'}]})).toBe('DONE')
})
function mount() {
  document.body.innerHTML = `<div id="simulate-jobs-list"><div data-job-id="complete">Completed result</div></div>
    <div id="cando-display-card"><label><input name="mode" type="radio" value="off" checked>Off</label>
    <label><input name="mode" type="radio" value="deform">Predicted shape</label>
    <label><input name="mode" type="radio" value="flex" disabled>RMSF unavailable</label>
    <label><input name="mode" type="radio" value="trajectory">Trajectory</label>
    <label>Metric<select id="metric"><option value="a">A</option><option value="b">B</option></select></label>
    <label>Opacity<input id="opacity" type="number" min="0" max="1" step="0.1" value="1"></label></div>`
}
it('keeps disabled result choices, includes trajectory setup, and reflects checked state', () => {
  mount();const choices = simulationControls(document, 'cando')
  expect(choices.find(c => c.label === 'RMSF unavailable').enabled).toBe(false)
  expect(choices.some(c => /Trajectory/.test(c.label))).toBe(true)
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
    document.querySelector('[value="off"]').checked = true
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
    const b = bridge.snapshot().controls.find(c => c.choice === 'b')
    await bridge.activate({ sequence: 2, version: state.version, id: b.id })
    expect(document.getElementById('metric').value).toBe('b')
    const plus = bridge.snapshot().controls.find(c => c.kind === 'number')
    await bridge.activate({ sequence: 3, version: state.version, id: plus.id, value: 2 })
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

it('keeps shared overlays with the active mode and mirrors native progress values', () => {
 document.body.innerHTML = `<div id="md-jobs-viz-body"><input name="md-viz" type="radio" value="traj" checked><input name="md-viz" type="radio" value="ion-vector-field"><div id="md-jobs-solvent-opts"><label><input id="ions" type="checkbox">Ions</label></div><progress value="30" max="40" aria-label="Loading ions"></progress></div>`
 expect(simulationControls(document, 'namd').find(c => c.element.id === 'ions').group).toBe('traj')
 expect(simulationProgress(document, 'namd')).toEqual([{label:'Loading ions',fraction:.75,busy:true}])
})
it('disables visualization choices while representation preparation owns an action', async () => {
 mount(); let release, state
 const bridge = createVRSimulations({ jobs: { getSelected: () => ({id:'complete'}) }, engineSelector: {getSelected: () => 'cando'}, ensureFull: () => new Promise(resolve => {release=resolve}), request: async (_,init) => {state=JSON.parse(init.body);return {ok:true}} })
 await bridge.publish()
 const pending=bridge.activate({sequence:1,version:state.version,id:state.controls.find(c=>c.label==='Predicted shape').id})
 await vi.waitFor(()=>expect(release).toBeTypeOf('function'))
 expect(bridge.snapshot().controls.every(c=>!c.enabled)).toBe(true)
 expect(bridge.snapshot().progress.at(-1).label).toBe('Preparing visualization')
 release();await pending
 expect(bridge.snapshot().controls.find(c=>c.label==='Predicted shape').enabled).toBe(true)
})

it('removes completed status text from the loading indicators', () => {
 document.body.innerHTML = '<div id="md-jobs-viz-body"><span id="md-solvent-status">Ions / box ready · 8/8 frames</span></div>'
 expect(simulationProgress(document, 'namd')).toEqual([])
 document.getElementById('md-solvent-status').textContent = 'Preparing ions / box · 0/8 frames…'
 expect(simulationProgress(document, 'namd')).toEqual([{label:'Preparing ions / box · 0/8 frames…',fraction:-1,busy:true}])
})

it('publishes and acknowledges the native loop toggle exactly once', async () => {
 mount();let state
 const bridge=createVRSimulations({jobs:{getSelected:()=>({id:'complete',engine:'cando'})},
  engineSelector:{getSelected:()=> 'cando'},api:{getSnupiTrajectoryMeta:async()=>({n_frames:8})},
  controller:()=>({}),request:async(_,init)=>{state=JSON.parse(init.body);return {ok:true}}})
 await bridge.publish()
 await bridge.activate({sequence:1,version:state.version,id:state.controls.find(c=>c.label==='Trajectory').id})
 await vi.waitFor(()=>expect(bridge.snapshot().trajectory?.available).toBe(8))
 await bridge.publish()
 const event={sequence:2,version:state.version,id:'t:loop'}
 await bridge.activate(event)
 expect(state.trajectory.loop).toBe(true)
 expect(state.acknowledged).toBe(2)
 await bridge.activate(event)
 expect(bridge.snapshot().trajectory.loop).toBe(true)
 bridge.reset()
})

it('reads wrapped and external labels without controls or DOM cloning',()=>{
 document.body.innerHTML='<div id="cando-display-card"><label>Alpha <span>beta</span><input id="a" type="checkbox"><button>Ignore</button><select><option>Ignore too</option></select></label><label for="b">External gamma</label><input id="b" type="checkbox"></div>'
 const clone=vi.spyOn(Element.prototype,'cloneNode')
 try {
  const controls=simulationControls(document,'cando')
  expect(controls.find(c=>c.element.id==='a').label).toBe('Alpha beta')
  expect(controls.find(c=>c.element.id==='b').label).toBe('External gamma')
  expect(clone).not.toHaveBeenCalled()
 }finally{clone.mockRestore()}
})
