import { it, expect, vi, afterEach } from 'vitest'
import { webcrypto } from 'node:crypto'
import * as THREE from 'three'
import { mountMeetingLiveFrame } from './meeting_live_frame.js'
import { prepareScene, loadPreparedScene } from './prepared_scene.js'
import { decodeContainer } from './package_container.js'
import { createLiveFrameCapture } from './live_frame_capture.js'
vi.mock('./trajectory_clip.js', async original => ({ ...await original(), gzipFrame: async b => b }))
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })
it.each([false, true])('smooths live boundaries and cancels obsolete work (WebXR: %s)', async xr => {
  vi.stubGlobal('crypto', webcrypto); document.body.innerHTML = '<main></main>'
  const scene = new THREE.Scene(), mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial()); scene.add(mesh)
  const camera = { position: [0, 0, 10], target: [0, 0, 0], up: [0, 1, 0], fov: 55, near: .1, far: 1000, orbitMode: 'orbit' }
  const buffer = prepareScene({ scene, camera }), current = await loadPreparedScene(buffer), capture = createLiveFrameCapture(decodeContainer(buffer), { scene })
  const packets = [], descriptions = [], revision = 'a'.repeat(64)
  for (let i = 1; i <= 6; i++) {
    mesh.position.x = i; const packet = capture.frame({ scene }); packets.push(packet)
    descriptions.push({ timeline: { frame: i * 10, total: 100, playing: i !== 5 }, revision, sequence: i, bytes: packet.byteLength, sha256: Buffer.from(await webcrypto.subtle.digest('SHA-256', packet)).toString('hex') })
  }
  const pending = [], request = vi.fn((url, options) => new Promise(resolve => pending.push({ options, finish: () => {
    const requested = Number(new URL(url, 'http://localhost').searchParams.get('sequence')) - 1
    const i = requested === 0 ? 1 : requested
    resolve({ ok: true, headers: new Headers({ 'Content-Length': packets[i].byteLength, 'X-NADOC-Sequence': i + 1, 'X-NADOC-SHA256': descriptions[i].sha256, 'X-NADOC-Timeline': JSON.stringify(descriptions[i].timeline) }), arrayBuffer: async () => packets[i] })
  } })))
  let poll, render, time = 0
  const runtime = xr ? { renderer: { xr: { isPresenting: true } }, addFrameCallback: fn => { render = fn }, removeFrameCallback: vi.fn() } : null
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(xr)
  const tick = () => { render?.(); poll() }
  const ui = mountMeetingLiveFrame({ viewer: { current, runtime }, base: '/meeting/room', revision, fetch: request, now: () => time, setInterval: fn => { poll = fn; return null }, clearInterval: () => {} })
  expect(document.querySelector('[data-live-smooth]').checked).toBe(true)
  for (const frame of descriptions.slice(0, 3)) ui.receive({ revision, liveFrame: frame })
  expect(document.querySelector('[data-frame-buffering]').hidden).toBe(false)
  expect(document.querySelector('[data-frame-number]').textContent).toContain('Frame — / 100')
  expect(request).toHaveBeenCalledTimes(1)
  pending[0].finish(); await vi.waitFor(() => expect(current.scene.children[0].matrix.elements[12]).toBe(2))
  expect(document.querySelector('[data-frame-number]').textContent).toContain('Frame 20 / 100')
  expect(document.querySelector('[data-live-timeline] input').value).toBe('20')
  void tick(); expect(request.mock.calls[1][0]).toContain('sequence=3')
  expect(document.querySelector('[data-frame-buffering]').hidden).toBe(false)
  time = 200; pending[1].finish()
  await vi.waitFor(() => expect(document.querySelector('[data-frame-buffering]').hidden).toBe(true))
  expect(current.scene.children[0].matrix.elements[12]).toBe(2)
  time = 300; tick()
  expect(current.scene.children[0].matrix.elements[12]).toBeCloseTo(2.5)
  expect(document.querySelector('[data-frame-buffering]').hidden).toBe(true)
  ui.receive({ revision, liveFrame: descriptions[3] })
  expect(document.querySelector('[data-frame-buffering]').hidden).toBe(false)
  time = 350; pending[2].finish()
  await vi.waitFor(() => expect(document.querySelector('[data-frame-buffering]').hidden).toBe(true))
  time = 425; tick()
  expect(current.scene.children[0].matrix.elements[12]).toBeCloseTo(3 + 25 / 150)
  ui.receive({ revision, liveFrame: descriptions[4] }); pending[3].finish()
  await vi.waitFor(() => expect(current.scene.children[0].matrix.elements[12]).toBe(5))
  time = 600; tick()
  expect(current.scene.children[0].matrix.elements[12]).toBe(5)
  expect(document.querySelector('[data-frame-number]').textContent).toContain('Paused')
  ui.receive({ revision, liveFrame: descriptions[5] })
  ui.dispose(); expect(pending[4].options.signal.aborted).toBe(true)
  if (runtime) expect(runtime.removeFrameCallback).toHaveBeenCalledWith(render)
  pending[4].finish(); await new Promise(resolve => setTimeout(resolve, 10))
  expect(current.scene.children[0].matrix.elements[12]).toBe(5)
  expect(document.querySelector('[data-live-timeline]')).toBeNull()
  current.dispose()
  hidden.mockRestore()
})

it('accepts large announced transfers and keeps buffering visible through a failed download', async () => {
  document.body.innerHTML = '<main></main>'
  const request = vi.fn(async () => { throw new Error('Offline') })
  const revision = 'a'.repeat(64)
  const ui = mountMeetingLiveFrame({ viewer: { current: {} }, base: '/meeting/room', revision, fetch: request, setInterval: () => null, clearInterval() {} })
  ui.receive({ revision, liveFrame: { revision, sequence: 1, bytes: 200 * 1024 * 1024, sha256: 'b'.repeat(64), timeline: { frame: 3, total: 10, playing: false } } })
  await vi.waitFor(() => expect(document.querySelector('[data-live-frame-status]').textContent).toContain('Retrying'))
  expect(request).toHaveBeenCalledOnce()
  expect(document.querySelector('[data-frame-buffering]').hidden).toBe(false)
  expect(document.querySelector('[data-live-timeline]').hidden).toBe(false)
  ui.dispose()
})
