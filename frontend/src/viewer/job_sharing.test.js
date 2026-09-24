import { restoreNativePresentation } from './native_presentation.js'
import { initSurfaceStrandsOverlay } from '../scene/surface_strands_overlay.js'
import { it, expect, vi, afterEach } from 'vitest'
import * as THREE from 'three'
import { Blob } from 'node:buffer'
import { gunzipSync } from 'node:zlib'
import { initJobSharing } from './job_sharing.js'
import { prepareScene } from './prepared_scene.js'
import { decodeContainer } from './package_container.js'
import { createLiveFrameCapture } from './live_frame_capture.js'
import { createClipApplier } from './trajectory_clip.js'
import { loadPreparedScene } from './prepared_scene.js'

afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks(); vi.unstubAllGlobals() })
const camera = { position: [0, 0, 10], target: [0, 0, 0], up: [0, 1, 0], fov: 55, near: .1, far: 1000, orbitMode: 'orbit' }
function setup(controller) {
  vi.stubGlobal('Blob', Blob)
  document.body.innerHTML = '<button id="menu-help-broadcast"></button>' + ['oxdna', 'md'].map(p => `<div><div id="${p}-jobs-viz-toggle"></div><input type="radio" id="${p}-jobs-viz-off"></div>`).join('') + '<div data-job-id="a"></div><div data-job-id="b"></div>'
  let selected = { engine: 'oxdna', id: 'a' }, room = null, fail = false
  const scene = new THREE.Scene(), mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial())
  scene.add(mesh)
  const source = { scene, camera, pose: camera }
  const prepared = { captureView: () => source, exportView: vi.fn(async () => ({ buffer: prepareScene({ scene, camera }) })) }
  const request = vi.fn(async (path, options) => ({ ok: !fail, json: async () => fail ? { error: 'Transfer failed' } : { lease: 'token', revision: 'a'.repeat(64) } }))
  const showNative = vi.fn(async () => { mesh.position.set(0, 0, 0) })
  const ui = initJobSharing({ prepared, store: { getState: () => ({ currentDesign: { id: 'design' } }) }, getSelection: () => selected,
    getSource: () => ({ controller }), showNative, getRoom: () => room, fetch: request, setInterval: () => null, clearInterval: () => {} })
  return { ui, request, mesh, prepared, showNative, select: job => { selected = job }, host: capabilities => { room = { id: 'room', capabilities: capabilities ?? ['live-unlimited-frames-v1', 'job-stream-v1', 'guest-visualizations-v1', ...(controller ? ['live-timeline-v1'] : [])] }; ui.refresh() }, fail: () => { fail = true } }
}
it('shows job controls only with an invitation and preserves publication across private selection and list rerender', async () => {
  const v = setup(), button = document.querySelector('[data-share-job="oxdna"]')
  expect(button.hidden).toBe(true); v.host(); expect(button.hidden).toBe(false)
  await v.ui.toggle('oxdna')
  expect(button.textContent).toBe('Stop sharing'); expect(button.dataset.sharing).toBe('true')
  expect(document.querySelector('[data-job-id="a"] [data-job-sharing-dot]').title).toBe('currently sharing this job for presentation')
  v.select({ engine: 'namd', id: 'b' }); v.mesh.position.x = 9
  v.request.mockClear(); await v.ui.tick()
  expect(v.request.mock.calls.some(([path]) => /\/(scene|frame|camera)$/.test(path))).toBe(false)
  expect(document.querySelector('[data-share-job="namd"]').textContent).toBe('Share')
  document.querySelector('[data-job-id="a"]').innerHTML = ''; v.ui.refresh()
  expect(document.querySelector('[data-job-id="a"] [data-job-sharing-dot]')).not.toBeNull()
  await v.ui.toggle('namd')
  expect(v.ui.shared).toEqual({ engine: 'namd', id: 'b' })
  expect(document.querySelector('[data-job-id="a"] [data-job-sharing-dot]')).toBeNull()
  expect(document.querySelector('[data-job-id="b"] [data-job-sharing-dot]')).not.toBeNull()
  expect(v.request.mock.calls.every(([path]) => path.includes('/shares/room/'))).toBe(true)
  v.ui.dispose()
})
it('streams coordinates without exporting another scene and returns guests to native on stop', async () => {
  const v = setup(); v.host(); await v.ui.toggle('oxdna'); v.mesh.position.x = 2
  await v.ui.tick()
  expect(v.prepared.exportView).toHaveBeenCalledTimes(1)
  expect(v.request.mock.calls.some(([path]) => path.endsWith('/frame'))).toBe(true)
  v.mesh.material.color.set('red'); await v.ui.tick()
  expect(v.prepared.exportView).toHaveBeenCalledTimes(2)
  await v.ui.toggle('oxdna')
  expect(v.showNative).toHaveBeenCalledOnce(); expect(v.ui.shared).toBeNull()
  const scenes = v.request.mock.calls.filter(([path]) => path.endsWith('/scene'))
  const restored = await loadPreparedScene(scenes.at(-1)[1].body)
  const packet = v.request.mock.calls.filter(([path]) => path.endsWith('/frame')).at(-1)[1].body
  const raw = gunzipSync(packet.subarray(64))
  createClipApplier(restored).apply(new Uint8Array(raw).buffer)
  expect(restored.scene.children[0].matrix.elements[12]).toBe(0); restored.dispose()
  expect(document.querySelectorAll('[data-job-sharing-dot]')).toHaveLength(0)
  v.ui.dispose()
})
it('keeps the old shared-job marker when a replacement fails', async () => {
  const v = setup(); v.host(); await v.ui.toggle('oxdna'); v.select({ engine: 'namd', id: 'b' }); v.fail()
  await v.ui.toggle('namd')
  expect(v.ui.shared.id).toBe('a'); expect(document.querySelector('[role="status"]').textContent).toContain('Transfer failed')
  v.ui.dispose()
})
it('discards an export if selection changes before publication', async () => {
  const v = setup(); v.host()
  const original = v.prepared.exportView
  v.prepared.exportView = async () => { const result = await original(); v.select({ engine: 'namd', id: 'b' }); return result }
  await v.ui.toggle('oxdna')
  expect(v.ui.shared).toBeNull(); expect(v.request.mock.calls.some(([path]) => path.endsWith('/scene'))).toBe(false)
  v.ui.dispose()
})
it('absolute render packets restore coordinates when returning to the base frame and detect material changes', async () => {
  const scene = new THREE.Scene(), mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial()); scene.add(mesh)
  const buffer = prepareScene({ scene, camera }), capture = createLiveFrameCapture(decodeContainer(buffer), { scene })
  mesh.material.needsUpdate = true // GPU bookkeeping alone must not republish geometry.
  const viewer = await loadPreparedScene(buffer), apply = createClipApplier(viewer)
  mesh.position.x = 17; apply.apply(capture.frame({ scene }))
  expect(viewer.scene.children[0].matrix.elements[12]).toBe(17)
  mesh.position.x = 0; apply.apply(capture.frame({ scene }))
  expect(viewer.scene.children[0].matrix.elements[12]).toBe(0)
  mesh.material.color.set('red'); expect(capture.frame({ scene })).toBeNull()
  viewer.dispose()
})

it('toggles camera sharing without stopping frames and keeps private selections private', async () => {
  const v = setup(); v.host(); await v.ui.setPerspective(false); await v.ui.toggle('oxdna')
  v.request.mockClear(); v.mesh.position.x = 2; await v.ui.tick()
  expect(v.request.mock.calls.some(([path]) => path.endsWith('/frame'))).toBe(true)
  expect(v.request.mock.calls.some(([path]) => path.endsWith('/camera'))).toBe(false)
  await v.ui.setPerspective(true)
  expect(v.request.mock.calls.some(([path]) => path.endsWith('/camera'))).toBe(true)
  await v.ui.setPerspective(false)
  expect(v.request.mock.calls.at(-1)[0]).toMatch(/\/hold$/)
  v.request.mockClear(); v.select({ engine: 'namd', id: 'b' }); await v.ui.setPerspective(true)
  expect(v.request.mock.calls.some(([path]) => /\/(camera|scene|frame)$/.test(path))).toBe(false)
  v.ui.dispose()
})

it('relays visualization progress while holding the previous scene and does not leak private work', async () => {
  const v = setup(); v.host(); await v.ui.toggle('oxdna')
  const body = document.createElement('div'); body.id = 'oxdna-jobs-viz-body'; body.innerHTML = '<progress max="100" value="35"></progress>'; document.body.append(body)
  v.request.mockClear(); v.mesh.material.color.set('red'); await v.ui.tick()
  await vi.waitFor(() => expect(v.request.mock.calls.some(([p, o]) => p.endsWith('/progress') && o.body === '{"fraction":0.35}')).toBe(true))
  expect(v.request.mock.calls.some(([p]) => p.endsWith('/scene'))).toBe(false)
  v.select({ engine: 'namd', id: 'b' }); await v.ui.tick()
  await vi.waitFor(() => expect(v.request.mock.calls.some(([p, o]) => p.endsWith('/progress') && o.body === 'null')).toBe(true))
  v.select({ engine: 'oxdna', id: 'a' }); body.querySelector('progress').value = 100; await v.ui.tick()
  expect(v.request.mock.calls.some(([p]) => p.endsWith('/scene'))).toBe(true); v.ui.dispose()
})


it.each(['oxdna', 'namd'])('stopping %s sharing removes PEG results AND resumed setup previews before publishing native', async engine => {
  const v = setup(), scene = v.prepared.captureView().scene
  v.select({ engine, id: 'a' })
  const overlay = initSurfaceStrandsOverlay({ scene, camera: new THREE.PerspectiveCamera(), canvas: document.createElement('canvas') })
  overlay.update({ material: 'PEG', shape: 'square', sizeNm: 10, densityPerUm2: 10000, segments: 2, beadDiameterNm: .5 }, true)
  overlay.setResults([[[1, 2, 3], [1, 3, 3]]])
  document.getElementById(`${engine === 'namd' ? 'md' : 'oxdna'}-jobs-viz-off`).onclick = () => overlay.setResults(null)
  let finishRepresentation
  const stopLive = vi.fn()
  v.showNative.mockImplementation(() => restoreNativePresentation({
    stopLive,
    setRepresentation: async repr => {
      expect(repr).toBe('full')
      await new Promise(resolve => { finishRepresentation = resolve })
      v.mesh.position.set(0, 0, 0)
    },
    clearSimulationVisuals: () => overlay.clear(),
  }))
  v.mesh.position.x = 5; v.host(); await v.ui.toggle(engine)
  let guest = await loadPreparedScene(v.request.mock.calls.find(([p]) => p.endsWith('/scene'))[1].body)
  expect(guest.scene.getObjectByName('peg-surface-beads')).toBeTruthy(); guest.dispose()
  v.request.mockClear()
  const stopping = v.ui.toggle(engine)
  await vi.waitFor(() => expect(finishRepresentation).toBeTypeOf('function'))
  expect(stopLive).toHaveBeenCalledOnce()
  // Off by itself leaves the seed preview visible: the original regression.
  expect(scene.getObjectByName('peg-surface-beads').children.length).toBeGreaterThan(0)
  expect(v.request.mock.calls.some(([p]) => p.endsWith('/scene'))).toBe(false)
  finishRepresentation(); await stopping
  guest = await loadPreparedScene(v.request.mock.calls.find(([p]) => p.endsWith('/scene'))[1].body)
  expect(guest.scene.getObjectByName('peg-surface-beads')).toBeUndefined()
  expect(guest.scene.getObjectByProperty('uuid', v.mesh.uuid).matrix.elements[12]).toBe(0)
  expect(v.ui.shared).toBeNull()
  v.request.mockClear(); v.select({ engine, id: null }); await v.ui.tick()
  expect(v.request.mock.calls.some(([p]) => /\/(scene|frame)$/.test(p))).toBe(false)
  guest.dispose(); overlay.dispose(); v.ui.dispose()
})

it('streams playback through background loading and sends pause/seek metadata with each packet', async () => {
  let info = { frame: 1, total: 100, playing: true }
  const v = setup({ activeJobId: () => 'a', trajectoryInfo: () => info })
  v.host(); await v.ui.setPerspective(false); await v.ui.toggle('oxdna')
  const body = document.createElement('div'); body.id = 'oxdna-jobs-viz-body'
  body.innerHTML = '<progress max="100" value="35"></progress>'; document.body.append(body)
  for (const frame of [2, 3, 80]) {
    info = { frame, total: 100, playing: frame !== 80 }; v.mesh.position.x = frame
    await v.ui.tick()
    const packet = v.request.mock.calls.filter(([p]) => p.endsWith('/frame')).at(-1)[1].body
    const size = new DataView(packet.buffer).getUint32(64)
    expect(JSON.parse(new TextDecoder().decode(packet.subarray(68, 68 + size)))).toEqual(info)
    expect(gunzipSync(packet.subarray(68 + size)).length).toBeGreaterThan(0)
  }
  info.playing = true; await v.ui.tick()
  expect(v.request.mock.calls.filter(([p]) => p.endsWith('/frame'))).toHaveLength(5)
  expect(v.prepared.exportView).toHaveBeenCalledTimes(1)
  expect(v.request.mock.calls.some(([p]) => p.endsWith('/camera'))).toBe(false)
  v.ui.dispose()
})

it('renews the lease while a large frame upload is still pending', async () => {
  const v = setup(); v.host(); await v.ui.toggle('oxdna')
  let finish
  const original = v.request.getMockImplementation()
  v.request.mockImplementation((path, options) => path.endsWith('/frame') ? new Promise(resolve => { finish = () => resolve({ ok: true, json: async () => ({}) }) }) : original(path, options))
  v.mesh.position.x = 42
  const upload = v.ui.tick()
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  const before = v.request.mock.calls.filter(([p]) => p.endsWith('/heartbeat')).length
  const later = Date.now() + 6000; vi.spyOn(Date, 'now').mockReturnValue(later)
  void v.ui.tick()
  await vi.waitFor(() => expect(v.request.mock.calls.filter(([p]) => p.endsWith('/heartbeat')).length).toBeGreaterThan(before))
  finish(); await upload; v.ui.dispose()
})

it('refuses a stale sharing host before acquiring a lease or exporting a trajectory', async () => {
  const v = setup(); v.host(['job-stream-v1', 'live-timeline-v1'])
  await v.ui.toggle('oxdna')
  expect(v.prepared.exportView).not.toHaveBeenCalled()
  expect(v.request).not.toHaveBeenCalled()
  expect(v.ui.active).toBe(false)
  expect(document.querySelector('.sharing-job-status').textContent).toContain('sharing host is out of date')
  v.ui.dispose()
})
