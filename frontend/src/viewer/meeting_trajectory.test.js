import { it, expect, vi } from 'vitest'
import { webcrypto } from 'node:crypto'
import * as THREE from 'three'
import { mountMeetingTrajectory } from './meeting_trajectory.js'
import { prepareScene, loadPreparedScene } from './prepared_scene.js'
import { decodeContainer } from './package_container.js'
import { sceneChannels, encodeFrame } from './trajectory_clip.js'
vi.mock('./trajectory_clip.js', async original => ({ ...await original(), gzipFrame: async b => b }))

async function setup() {
  vi.stubGlobal('crypto', webcrypto)
  document.body.innerHTML = '<main></main>'
  const scene = new THREE.Scene(), mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial()); scene.add(mesh)
  const pack = () => prepareScene({ scene, camera: { position: [0,0,10], target: [0,0,0], up: [0,1,0], fov: 55, orbitMode: 'orbit' } })
  const buffer = pack(), layout = sceneChannels(decodeContainer(buffer)), current = await loadPreparedScene(buffer), frames = []
  for (let i = 0; i < 12; i++) { mesh.position.x = i; frames.push(encodeFrame(layout, sceneChannels(decodeContainer(pack())))) }
  current.data.trajectory = { version: 1, encoding: 'absolute-render-patch-gzip', id: 'a'.repeat(64), fps: 8, sourceFrames: frames.map((_, i) => i), frames: await Promise.all(frames.map(async frame => ({ bytes: frame.byteLength, sha256: [...new Uint8Array(await webcrypto.subtle.digest('SHA-256', frame))].map(b => b.toString(16).padStart(2, '0')).join('') }))) }
  let tick, time = 0
  const pending = [], request = vi.fn((url, options) => new Promise(resolve => pending.push({ url, options, finish: () => { const index = Number(new URL(url, 'http://localhost').searchParams.get('index')); resolve({ ok: true, headers: new Headers({ 'Content-Length': frames[index].byteLength }), arrayBuffer: async () => frames[index] }) } })))
  const viewer = { current, performanceApi: { busy: false } }, log = vi.fn()
  const api = mountMeetingTrajectory({ viewer, base: '/meeting/x', role: 'guest', fetch: request, now: () => time, setInterval: fn => { tick = fn; return 1 }, clearInterval: vi.fn(), log })
  const state = (frame, playing, at = 1000) => api.receive({ serverTime: at, trajectory: { id: 'a'.repeat(64), frame, playing, fps: 8, at } })
  return { api, viewer, pending, request, state, tick: () => tick(), advance: ms => { time += ms }, log }
}
it('bounds requests and skips obsolete playback work instead of draining a historical queue', async () => {
  const v = await setup(); v.state(0, true)
  for (let i = 0; i < 30; i++) { v.advance(33); v.tick() }
  expect(v.request).toHaveBeenCalledTimes(1)
  v.pending[0].finish(); await vi.waitFor(() => expect(document.querySelector('[data-progress]')).toBeTruthy())
  // Download completion includes asynchronous SHA-256 verification. Wait for the
  // next request instead of assuming that crypto finishes within 10 ms under load.
  await vi.waitFor(() => { v.tick(); expect(v.pending).toHaveLength(2) })
  expect(Number(new URL(v.pending[1].url, 'http://localhost').searchParams.get('index'))).toBeGreaterThan(7)
  v.api.dispose(); v.viewer.current.dispose(); vi.unstubAllGlobals()
})
it('a pause cancels in-flight work, ignores late results, and applies the exact requested frame', async () => {
  const v = await setup(); v.state(0, true); v.state(5, false, 2000)
  expect(v.pending[0].options.signal.aborted).toBe(true)
  v.pending[0].finish(); v.pending[1].finish()
  await vi.waitFor(() => { v.tick(); expect(v.viewer.current.scene.children[0].matrix.elements[12]).toBe(5) })
  expect(document.querySelector('[data-follow]')).toBeNull()
  v.api.dispose(); expect(document.querySelector('[data-trajectory]')).toBeNull(); v.viewer.current.dispose(); vi.unstubAllGlobals()
})
it('ignores an older timeline snapshot arriving after a newer seek', async () => {
  const v = await setup(), id = v.viewer.current.data.trajectory.id
  v.api.receive({ sequence: 4, serverTime: 2000, trajectory: { id, frame: 5, playing: false, fps: 8, at: 2000 } })
  v.api.receive({ sequence: 3, serverTime: 1000, trajectory: { id, frame: 1, playing: true, fps: 8, at: 1000 } })
  expect(v.request).toHaveBeenCalledTimes(1)
  expect(v.pending[0].options.signal.aborted).toBe(false)
  v.pending[0].finish()
  await vi.waitFor(() => { v.tick(); expect(v.viewer.current.scene.children[0].matrix.elements[12]).toBe(5) })
  v.api.dispose(); v.viewer.current.dispose(); vi.unstubAllGlobals()
})
