import { afterEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { initNamdPegReview, openPegQualification } from './namd_peg_review.js'

let ui
afterEach(() => { ui?.dispose(); ui = null; document.body.replaceChildren(); vi.useRealTimers() })
const payload = () => ({ schema: 'nadoc.namd_peg_review.v1', title: 'PEG review', note: 'Initial',
  coordinates_nm: [[1, 1, .4], [1, 1, .5], [2, 2, 2]], elements: ['C', 'H', 'O'],
  bonds: [[0, 1]], peg_indices: [0, 1], anchor_indices: [0], atoms: 3,
  slit: { box_nm: [4.8, 4.8, 4.8], inset_nm: .2 }, jobs: [{ job_id: 'job1', stage: 'resident' }] })
function setup(api = {}) {
  let listener
  const state = { currentDesign: { id: 'review', metadata: { namd_peg_review: payload() } } }
  const store = { getState: () => state, subscribe: fn => { listener = fn; return () => {} } }
  const scene = new THREE.Scene()
  ui = initNamdPegReview({ scene, camera: new THREE.PerspectiveCamera(),
    controls: { target: new THREE.Vector3(), update() {} }, store, api })
  return { scene, state, update: currentDesign => { state.currentDesign = currentDesign; listener(state) } }
}
it('renders the saved molecular geometry and clears it when switching documents', () => {
  const { scene, update } = setup()
  expect(document.querySelector('.namd-peg-review').hidden).toBe(false)
  expect(scene.children[0].children[0].geometry.attributes.position.count).toBe(2)
  document.querySelector('input[type=checkbox]').click()
  expect(scene.children[0].children[0].geometry.attributes.position.count).toBe(3)
  update({ id: 'empty', metadata: {} })
  expect(document.querySelector('.namd-peg-review').hidden).toBe(true)
  expect(scene.children[0].children).toHaveLength(0)
})
it('plays recorded coordinates without changing the persisted design', async () => {
  vi.useFakeTimers()
  const data = payload(); data.frames = [{ step: 100, coordinates_nm: data.coordinates_nm },
    { step: 200, coordinates_nm: [[1.1, 1, .4], [1.1, 1, .5], [2, 2, 2]] }]
  data.job_id = 'job1'; data.stage = 'resident'
  const { state, scene } = setup({ getPegQualification: async () => data })
  const before = JSON.stringify(state)
  await ui.loadJob('job1')
  const play = [...document.querySelectorAll('button')].find(b => b.textContent === 'Play'); play.click()
  vi.advanceTimersByTime(150)
  expect(document.body.textContent).toContain('Frame 2/2')
  expect(scene.children[0].children[0].geometry.attributes.position.array[0]).toBeCloseTo(1.1)
  expect(JSON.stringify(state)).toBe(before)
  ui.dispose(); ui = null
  expect(vi.getTimerCount()).toBe(0)
})
it('ignores a late job load after switching away', async () => {
  let resolve
  const { update } = setup({ getPegQualification: () => new Promise(r => { resolve = r }) })
  const pending = ui.loadJob('job1'); update({ id: 'other', metadata: {} }); resolve(payload()); await pending
  expect(document.querySelector('.namd-peg-review').hidden).toBe(true)
})
it('routes only PEG qualification jobs to the dedicated viewer', () => {
  const handler = vi.fn(); window.addEventListener('nadoc:peg-qualification', handler)
  expect(openPegQualification({ run_kind: 'production' })).toBe(false)
  expect(openPegQualification({ run_kind: 'peg_wall_qualification', job_id: 'abc' })).toBe(true)
  expect(handler.mock.calls[0][0].detail.jobId).toBe('abc')
  window.removeEventListener('nadoc:peg-qualification', handler)
})
it('creates a managed fast relaxation without starting it and announces its job', async () => {
  const api = { createPegFastRelax: vi.fn(async () => ({ job_id: 'child' })),
    getPegQualification: vi.fn(async () => ({ ...payload(), job_id: 'child', stage: 'fast relax', frames: [] })) }
  setup(api)
  const event = vi.fn(); window.addEventListener('nadoc:md-job-created', event)
  const button = [...document.querySelectorAll('button')].find(b => b.textContent === 'Create fast relax job')
  button.click(); button.click()
  await vi.waitFor(() => expect(document.body.textContent).toContain('Use Run in Simulations'))
  expect(api.createPegFastRelax).toHaveBeenCalledTimes(1)
  expect(api.createPegFastRelax).toHaveBeenCalledWith('job1')
  expect(event.mock.calls[0][0].detail.jobId).toBe('child')
  expect(button.hidden).toBe(true)
  window.removeEventListener('nadoc:md-job-created', event)
})

it('shares Display, Flex, trajectory, solvent and Off controls without invoking DNA handlers', async () => {
  const labels = ['viz-off', 'display-toggle', 'flex-toggle', 'traj-toggle', 'photoproduct-toggle', 'occupancy-toggle']
  document.body.innerHTML = labels.map(s => `<label><input id="md-jobs-${s}" name="md-viz" type="radio"></label>`).join('')
    + '<input type="checkbox" id="md-jobs-water-toggle"><input type="checkbox" id="md-jobs-box-toggle"><input type="range" disabled id="md-jobs-traj-slider"><button id="md-jobs-traj-next"></button><p id="md-jobs-photoproduct-status"></p><p id="md-jobs-occupancy-status"></p>'
  const data = { ...payload(), job_id: 'job1', stage: 'resident', raw_frames: 2,
    frames: [{ step: 1, coordinates_nm: payload().coordinates_nm },
      { step: 2, coordinates_nm: [[1.2, 1, .4], [1.2, 1, .5], [2, 2, 2]] }] }
  const { scene } = setup({ getPegQualification: async () => data })
  window.dispatchEvent(new CustomEvent('nadoc:peg-viz-availability', { detail: { job: { job_id: 'job1', run_kind: 'peg_fast_relax' } } }))
  openPegQualification({ job_id: 'job1', run_kind: 'peg_fast_relax' })
  const card = document.querySelector('.namd-peg-review')
  await vi.waitFor(() => expect(card.dataset.frames).toBe('2'))
  const legacy = vi.fn(); document.getElementById('md-jobs-display-toggle').addEventListener('change', legacy)
  document.getElementById('md-jobs-display-toggle').click()
  await vi.waitFor(() => expect(card.dataset.mode).toBe('display'))
  expect(scene.children[0].children[0].geometry.attributes.position.array[0]).toBeCloseTo(1.2)
  expect(legacy).not.toHaveBeenCalled()
  document.getElementById('md-jobs-flex-toggle').click()
  await vi.waitFor(() => expect(card.dataset.mode).toBe('flex'))
  expect(document.querySelector('.peg-rmsf-scale').textContent).toContain('1.000 Å')
  expect(scene.children[0].children[0].geometry.attributes.position.array[0]).toBeCloseTo(1.1)
  expect(document.getElementById('md-jobs-water-toggle').disabled).toBe(true)
  document.getElementById('md-jobs-traj-toggle').click()
  await vi.waitFor(() => expect(card.dataset.mode).toBe('traj'))
  expect(document.getElementById('md-jobs-traj-slider').disabled).toBe(false)
  document.getElementById('md-jobs-traj-next').click()
  expect(card.textContent).toContain('Frame 2/2')
  document.getElementById('md-jobs-water-toggle').click()
  expect(card.dataset.waterAtoms).toBe('1')
  document.getElementById('md-jobs-box-toggle').click()
  expect(scene.children[0].children).toHaveLength(6)
  document.getElementById('md-jobs-viz-off').click()
  expect(card.dataset.mode).toBe('off')
  expect(scene.children[0].children[0].geometry.attributes.position.array[0]).toBeCloseTo(1)
  expect(document.getElementById('md-jobs-photoproduct-toggle').disabled).toBe(true)
  expect(document.body.textContent).toContain('validated production')
  window.dispatchEvent(new CustomEvent('nadoc:peg-viz-availability', { detail: { job: { run_kind: 'production' } } }))
  expect(card.hidden).toBe(true)
  expect(scene.children[0].children).toHaveLength(0)
  document.getElementById('md-jobs-display-toggle').dispatchEvent(new Event('change', { bubbles: true }))
  expect(legacy).toHaveBeenCalledOnce()
})

it('polls the latest active frame, preserves the camera and stops on Off', async () => {
  vi.useFakeTimers()
  const data = { ...payload(), job_id: 'job1', stage: 'resident', job: { status: 'running' },
    frames: [{ step: 1, coordinates_nm: payload().coordinates_nm }] }
  const api = { getPegQualification: vi.fn(async () => data) }
  setup(api); await ui.loadJob('job1'); ui.setMode('display')
  await vi.advanceTimersByTimeAsync(0)
  expect(api.getPegQualification).toHaveBeenLastCalledWith('job1', undefined, 1)
  await vi.advanceTimersByTimeAsync(5000)
  expect(api.getPegQualification).toHaveBeenCalledTimes(3)
  ui.setMode('off'); await vi.advanceTimersByTimeAsync(10000)
  expect(api.getPegQualification).toHaveBeenCalledTimes(3)
})

it('follows shared atomistic representations and keeps fixed walls in every mode', () => {
  const { scene, state } = setup()
  const before = JSON.stringify(state)
  for (const [representation, meshCount] of [['vdw', 1], ['ballstick', 2], ['stick', 1], ['beads', 1]]) {
    window.dispatchEvent(new CustomEvent('nadoc:representation-change', { detail: { representation } }))
    const nodes = scene.children[0].children
    expect(nodes.filter(n => n.isInstancedMesh)).toHaveLength(meshCount)
    expect(nodes.filter(n => n.geometry?.type === 'PlaneGeometry')).toHaveLength(2)
    expect(document.querySelector('.namd-peg-review').dataset.representation).toBe(representation)
  }
  window.dispatchEvent(new CustomEvent('nadoc:representation-change', { detail: { representation: 'surface' } }))
  expect(document.body.textContent).toContain('DNA coarse/surface representations do not define a PEG model')
  expect(scene.children[0].children[0].isPoints).toBe(true)
  expect(JSON.stringify(state)).toBe(before)
})

it('sizes non-cubic barrier planes on each declared normal axis', () => {
  const { scene, update } = setup()
  for (const axis of [0, 1, 2]) {
    const data = payload(); data.slit = { box_nm: [4, 6, 8], axis, inset_nm: .2 }
    update({ id: `axis${axis}`, metadata: { namd_peg_review: data } })
    const plane = scene.children[0].children.find(n => n.geometry?.type === 'PlaneGeometry')
    const bounds = new THREE.Box3().setFromObject(plane)
    const sizes = bounds.getSize(new THREE.Vector3()).toArray()
    for (let a = 0; a < 3; a++) expect(sizes[a]).toBeCloseTo(a === axis ? 0 : data.slit.box_nm[a])
    expect(plane.position.toArray()[axis]).toBeCloseTo(.2)
  }
})
