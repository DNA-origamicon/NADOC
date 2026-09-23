import { it, expect, vi, afterEach } from 'vitest'
import { webcrypto } from 'node:crypto'
import * as THREE from 'three'
import { mountMeetingLiveFrame } from './meeting_live_frame.js'
import { prepareScene, loadPreparedScene } from './prepared_scene.js'
import { decodeContainer } from './package_container.js'
import { createLiveFrameCapture } from './live_frame_capture.js'
vi.mock('./trajectory_clip.js', async original => ({ ...await original(), gzipFrame: async b => b }))
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })
it('automatically applies frames, coalesces slow transfers, and cancels obsolete scene work', async () => {
  vi.stubGlobal('crypto', webcrypto); document.body.innerHTML = '<main></main>'
  const scene = new THREE.Scene(), mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial()); scene.add(mesh)
  const camera = { position: [0, 0, 10], target: [0, 0, 0], up: [0, 1, 0], fov: 55, near: .1, far: 1000, orbitMode: 'orbit' }
  const buffer = prepareScene({ scene, camera }), current = await loadPreparedScene(buffer), capture = createLiveFrameCapture(decodeContainer(buffer), { scene })
  const packets = [], descriptions = [], revision = 'a'.repeat(64)
  for (let i = 1; i <= 3; i++) {
    mesh.position.x = i; const packet = capture.frame({ scene }); packets.push(packet)
    descriptions.push({ revision, sequence: i, bytes: packet.byteLength, sha256: Buffer.from(await webcrypto.subtle.digest('SHA-256', packet)).toString('hex') })
  }
  const pending = [], request = vi.fn((url, options) => new Promise(resolve => pending.push({ options, finish: () => {
    const i = Number(new URL(url, 'http://localhost').searchParams.get('sequence')) - 1
    resolve({ ok: true, headers: new Headers({ 'Content-Length': packets[i].byteLength }), arrayBuffer: async () => packets[i] })
  } })))
  let tick
  const ui = mountMeetingLiveFrame({ viewer: { current }, base: '/meeting/room', revision, fetch: request, setInterval: fn => { tick = fn; return null }, clearInterval: () => {} })
  for (const frame of descriptions) ui.receive({ revision, liveFrame: frame })
  expect(request).toHaveBeenCalledTimes(1)
  pending[0].finish(); await vi.waitFor(() => expect(current.scene.children[0].matrix.elements[12]).toBe(1))
  void tick(); expect(request.mock.calls[1][0]).toContain('sequence=3')
  ui.dispose(); expect(pending[1].options.signal.aborted).toBe(true)
  pending[1].finish(); await new Promise(resolve => setTimeout(resolve, 10))
  expect(current.scene.children[0].matrix.elements[12]).toBe(1)
  current.dispose()
})
