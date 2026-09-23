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
