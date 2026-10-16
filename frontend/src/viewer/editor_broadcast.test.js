import { it, expect, vi, afterEach } from 'vitest'
import * as THREE from 'three'
import { initEditorBroadcast } from './editor_broadcast.js'
import { broadcastFingerprint, broadcastDocument } from './broadcast_fingerprint.js'
afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })
function setup(options = {}) {
  document.body.innerHTML = '<button id="menu-help-broadcast"></button><canvas></canvas>'
  const state = { currentDesign: { id: 'part' } }, listeners = new Set()
  const scene = new THREE.Scene(), mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial()); scene.add(mesh)
  const camera = new THREE.PerspectiveCamera(), pose = { position: [0, 0, 10], target: [0, 0, 0], up: [0, 1, 0], fov: 55, orbitMode: 'orbit' }
  const prepared = { captureView: () => ({ scene, camera, pose }), sourceHash: vi.fn(async () => 'c'.repeat(64)), exportView: vi.fn(async () => ({ buffer: new ArrayBuffer(24) })) }
  let time = 0
  const fetch = vi.fn(async path => ({ ok: true, json: async () => path.endsWith('/status') ? { capabilities: ['editor-broadcast-v1'], shares: [{ id: 'a'.repeat(32), title: 'Part' }] } : { lease: 'secret', revision: 'b'.repeat(64) } }))
  const ui = initEditorBroadcast({ prepared, store: { getState: () => state, subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn) } }, fetch, now: () => time, setInterval: () => 1, clearInterval: vi.fn(), log: vi.fn(), ...options })
  document.querySelector('dialog').showModal = vi.fn(); document.querySelector('dialog').close = vi.fn()
  return { ui, state, scene, mesh, pose, prepared, fetch, advance: ms => { time += ms }, notify: () => listeners.forEach(fn => fn()) }
}
it('detects visual changes without treating camera movement as a new package', () => {
  const v = setup(), before = broadcastFingerprint(v.prepared.captureView())
  v.pose.position[0] = 20
  expect(broadcastFingerprint(v.prepared.captureView())).toBe(before)
  v.mesh.material.color.set('red'); expect(broadcastFingerprint(v.prepared.captureView())).not.toBe(before)
  expect(broadcastDocument(v.state)).toBe('part:part'); expect(broadcastDocument({ assemblyActive: true, currentAssembly: { id: 'a' } })).toBe('assembly:a')
  v.ui.dispose()
})
it('is off by default; publishes initial visuals then coalesced camera updates and settled colors', async () => {
  const v = setup(); await v.ui.tick(); expect(v.fetch).not.toHaveBeenCalled()
  await v.ui.show(); await v.ui.start(); expect(v.ui.active).toBe(true)
  expect(v.prepared.exportView).toHaveBeenCalledTimes(1)
  v.pose.position[0] = 25; await v.ui.tick(); expect(v.prepared.exportView).toHaveBeenCalledTimes(1)
  v.mesh.material.color.set('red'); v.advance(3500); await v.ui.tick(); v.advance(1100); await v.ui.tick()
  expect(v.prepared.exportView).toHaveBeenCalledTimes(2)
  v.ui.stop(); v.mesh.material.color.set('blue'); v.advance(5000); await v.ui.tick()
  expect(v.prepared.exportView).toHaveBeenCalledTimes(2)
  expect(v.fetch.mock.calls.at(-1)[0]).toContain('/pause'); v.ui.dispose()
})
it('stops before a private file can publish and drops an export still in flight', async () => {
  const v = setup(); await v.ui.show()
  let finish; v.prepared.exportView.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const starting = v.ui.start(); await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  window.dispatchEvent(new Event('nadoc:document-reset'))
  finish({ buffer: new ArrayBuffer(24) }); await starting
  expect(v.ui.active).toBe(false); expect(v.fetch.mock.calls.some(([path]) => path.endsWith('/scene'))).toBe(false)
  expect(v.fetch.mock.calls.some(([path]) => path.endsWith('/pause'))).toBe(true); v.ui.dispose()
})
it('supports camera-only mode with a source-identity check and refuses an empty selection', async () => {
  const v = setup(); await v.ui.show()
  document.querySelector('[data-visuals]').checked = false; document.querySelector('[data-camera]').checked = false
  await v.ui.start(); expect(v.ui.active).toBe(false)
  document.querySelector('[data-camera]').checked = true; await v.ui.start()
  expect(v.prepared.exportView).not.toHaveBeenCalled()
  expect(JSON.parse(v.fetch.mock.calls.find(([path]) => path.endsWith('/start'))[1].body)).toEqual({ cameraOnly: true, sourceHash: 'c'.repeat(64) })
  v.state.currentDesign = { id: 'private' }; v.notify(); expect(v.ui.active).toBe(false); v.ui.dispose()
})

it('shares the standard editor camera directly without a presenter dialog or exported scene', async () => {
  const v = setup({ embedded: true })
  const capture = v.prepared.captureView
  // The main renderer is hidden in multi-view; only the active pane is valid.
  v.prepared.captureView = (presentation = true) => { if (!presentation) throw new Error('Main renderer hidden'); return capture() }
  await v.ui.present({ id: 'a'.repeat(32), title: 'Part' })
  expect(v.ui.active).toBe(true)
  expect(document.querySelector('dialog').showModal).not.toHaveBeenCalled()
  expect(document.getElementById('editor-broadcast-status').hidden).toBe(true)
  expect(v.prepared.exportView).not.toHaveBeenCalled()
  expect(v.fetch.mock.calls.some(([path]) => path.endsWith('/camera'))).toBe(true)
  await v.ui.stop(); expect(v.ui.active).toBe(false)
  v.ui.dispose()
})
it('refreshes the scene before locking a newly edited design, then leaves later scene updates to native sharing', async () => {
  const v = setup({ embedded: true })
  await v.ui.present({ id: 'a'.repeat(32), title: 'Part' }, { refreshScene: true })
  expect(v.prepared.sourceHash).not.toHaveBeenCalled()
  const paths = v.fetch.mock.calls.map(([path]) => path.split('/').at(-1))
  expect(paths.indexOf('scene')).toBeLessThan(paths.indexOf('camera'))
  expect(v.prepared.exportView).toHaveBeenCalledOnce()
  v.mesh.material.color.set('red'); v.advance(3500); await v.ui.tick(); v.advance(1100); await v.ui.tick()
  expect(v.prepared.exportView).toHaveBeenCalledOnce()
  v.ui.dispose()
})

it('embedded scene refresh uses the host capabilities without opening the broadcast dialog', async () => {
  const v = setup({ embedded: true })
  v.prepared.exportView.mockResolvedValue({ buffer: new ArrayBuffer(24), requiresViewToolsViewer: true })
  await v.ui.present({ id: 'a'.repeat(32), title: 'Part' }, { refreshScene: true, capabilities: ['view-tools-v1'] })
  expect(v.ui.active).toBe(true)
  expect(v.fetch.mock.calls.some(([path]) => path.endsWith('/scene'))).toBe(true)
  await v.ui.stop()
  await expect(v.ui.present({ id: 'a'.repeat(32), title: 'Part' }, { refreshScene: true, capabilities: [] })).rejects.toThrow('Restart presentation hosting')
  expect(v.ui.active).toBe(false)
  v.ui.dispose()
})

it('publishes headset cameras, holds on tracking loss, recovers, and discards poses completed after stopping', async () => {
  const v=setup(), camera={...v.pose,near:.1,far:1000,source:'headset',unitsPerMeter:1}
  let value=camera
  await v.ui.present({id:'room',title:'VR'},{getCamera:async()=>value})
  const sent=()=>v.fetch.mock.calls.filter(([url])=>url.endsWith('/camera'))
  expect(JSON.parse(sent().at(-1)[1].body).camera).toEqual(camera)
  value=null;v.advance(100);await v.ui.tick()
  expect(v.fetch.mock.calls.at(-1)[0]).toContain('/hold')
  const count=sent().length;v.advance(100);await v.ui.tick();expect(sent()).toHaveLength(count)
  value=camera;v.advance(100);await v.ui.tick();expect(sent()).toHaveLength(count+1)
  await v.ui.stop()
  let finish
  const starting=v.ui.present({id:'room',title:'VR'},{getCamera:()=>new Promise(resolve=>{finish=resolve})})
  await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));await v.ui.stop();finish(camera)
  await expect(starting).rejects.toThrow()
  expect(sent()).toHaveLength(count+1);v.ui.dispose()
})

it('waits for an obsolete headset request before starting a replacement desktop camera lease', async () => {
  const v=setup();let finish,value={...v.pose,near:.1,far:1000,source:'headset',unitsPerMeter:1}
  await v.ui.present({id:'room',title:'VR'},{getCamera:()=>value})
  value=new Promise(resolve=>{finish=resolve});v.advance(100)
  const flight=v.ui.tick();await v.ui.stop()
  const replacement=v.ui.present({id:'room',title:'Desktop'})
  finish(null);await flight;await replacement
  expect(v.ui.active).toBe(true)
  const last=v.fetch.mock.calls.filter(([url])=>url.endsWith('/camera')).at(-1)
  expect(JSON.parse(last[1].body).camera.source).toBeUndefined()
  v.ui.dispose()
})

it('continues headset publication while the desktop edit view is unavailable and after scene replacement', async () => {
  const v=setup(), camera={...v.pose,near:.1,far:1000,source:'headset',unitsPerMeter:1}
  v.prepared.captureView=()=>{throw new Error('Return to the normal 3D view before exporting a prepared snapshot')}
  await v.ui.present({id:'room',title:'VR'},{getCamera:async()=>camera})
  v.advance(100);await v.ui.tick()
  expect(v.ui.active).toBe(true)
  expect(v.fetch.mock.calls.filter(([url])=>url.endsWith('/camera'))).toHaveLength(2)
  await v.ui.stop()
  // Scene publication acquires a replacement lease before following resumes.
  v.fetch.mockImplementation(async()=>({ok:true,json:async()=>({lease:'replacement',revision:'d'.repeat(64)})}))
  await v.ui.present({id:'room',title:'VR'},{getCamera:async()=>camera})
  const last=v.fetch.mock.calls.filter(([url])=>url.endsWith('/camera')).at(-1)
  expect(JSON.parse(last[1].body)).toEqual({revision:'d'.repeat(64),camera})
  v.ui.dispose()
})
