import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { prepareScene } from './prepared_scene.js'
it.each(['vdw', 'ballstick', 'stick'])('streams real %s atom/bond buffers during live playback', async mode => {
  const { initAtomisticRenderer } = await import('../scene/atomistic_renderer.js')
  const { initOxdnaDisplay } = await import('../ui/oxdna_display.js')
  const { decodeContainer } = await import('./package_container.js')
  const { loadPreparedScene } = await import('./prepared_scene.js')
  const { createClipApplier } = await import('./trajectory_clip.js')
  const scene = new THREE.Scene(), atom = initAtomisticRenderer(scene)
  atom.setMode(mode)
  const api = {
    trajectoryImpostors: true,
    getOxdnaTrajectory: async () => ({ ready: true, n_frames: 3, keys: [['h', 0, 'FORWARD']], frames: [0, 1, 2].map(i => [i, 0, 0, 1, 0, 0]) }),
    getOxdnaAtomisticModel: async () => ({ n_serials: 2, atoms: [
      { serial: 0, element: 'P', helix_id: 'h', strand_id: 's', x: 0, y: 0, z: 0 },
      { serial: 1, element: 'O', helix_id: 'h', strand_id: 's', x: .15, y: 0, z: 0 },
    ], bonds: [[0, 1]] }),
    getOxdnaFramesAtomistic: async (_job, indices) => Object.fromEntries(indices.map(i => [String(i), [i, 0, 0, i + .15, 0, 0]])),
  }
  const controller = initOxdnaDisplay({ designRenderer: { applyFemPositions() {}, clearScalarColors() {} }, api,
    getCurrentRepr: () => mode, getAtomisticRenderer: () => atom })
  await controller.loadTrajectory('job', true, 'job'); await controller.showFrameForExport(0)
  const { createLiveFrameCapture } = await import('./live_frame_capture.js')
  const source = { scene }
  const buffer = prepareScene({ scene, camera: { position: [0,0,10], target: [0,0,0], up: [0,1,0], fov: 55, orbitMode: 'orbit' } })
  const capture = createLiveFrameCapture(decodeContainer(buffer), source)
  const guest = await loadPreparedScene(buffer), apply = createClipApplier(guest)
  controller.setPlaying(true)
  for (const index of [2, 0, 1]) {
    controller.showFrame(index)
    await vi.waitFor(() => {
      const mesh = scene.children.find(o => o.isInstancedMesh)
      expect(mesh.instanceMatrix.array[12]).toBeCloseTo(mode === 'stick' ? index + .075 : index)
    })
    const packet = capture.frame(source)
    expect(packet).not.toBeNull()
    apply.apply(packet)
    scene.traverseVisible(object => {
      if (!object.isInstancedMesh) return
      expect(guest.scene.getObjectByProperty('uuid', object.uuid).instanceMatrix.array).toEqual(object.instanceMatrix.array)
    })
  }
  guest.dispose(); controller.stopAndRestore(); atom.dispose()
})

it.skipIf(!process.env.NADOC_LIVE_ATOM_FIXTURE)('streams measured 3x6SQ_norm_skips ball-and-stick frames beyond the clip limit', async () => {
  const { readFile } = await import('node:fs/promises')
  const { gzipSync } = await import('node:zlib')
  const { initAtomisticRenderer } = await import('../scene/atomistic_renderer.js')
  const { createLiveFrameCapture, LIVE_FRAME_LIMITS } = await import('./live_frame_capture.js')
  const { decodeContainer } = await import('./package_container.js')
  const { loadPreparedScene } = await import('./prepared_scene.js')
  const { createClipApplier, FRAME_LIMIT } = await import('./trajectory_clip.js')
  const data = JSON.parse(await readFile(process.env.NADOC_LIVE_ATOM_FIXTURE, 'utf8'))
  const scene = new THREE.Scene(), atom = initAtomisticRenderer(scene)
  atom.setMode('ballstick')
  atom.update({ atoms: data.elements.map((element, serial) => ({ serial, element, x: data.frames[0][serial*3], y: data.frames[0][serial*3+1], z: data.frames[0][serial*3+2] })), bonds: data.bonds })
  const buffer = prepareScene({ scene, camera: { position: [0,0,100], target: [0,0,0], up: [0,1,0], fov: 55, orbitMode: 'orbit' } })
  const capture = createLiveFrameCapture(decodeContainer(buffer), { scene }, LIVE_FRAME_LIMITS)
  const legacy = createLiveFrameCapture(decodeContainer(buffer), { scene })
  atom.applyPositionLerp(data.frames[1], data.frames[1], 0)
  expect(() => legacy.frame({ scene })).toThrow('16 MiB')
  const raw = capture.frame({ scene }), compressed = gzipSync(new Uint8Array(raw))
  expect(raw.byteLength).toBeGreaterThan(FRAME_LIMIT)
  expect(compressed.byteLength).toBeLessThan(FRAME_LIMIT)
  const guest = await loadPreparedScene(buffer), apply = createClipApplier(guest, LIVE_FRAME_LIMITS)
  apply.apply(raw)
  scene.traverseVisible(o => {
    if (!o.isInstancedMesh) return
    const received = guest.scene.getObjectByProperty('uuid', o.uuid)
    const a = received.instanceMatrix.array, b = o.instanceMatrix.array
    expect(a.length).toBe(b.length)
    expect(a.findIndex((value, i) => value !== b[i])).toBe(-1)
  })
  process.stdout.write('Measured atomistic stream: ' + JSON.stringify({ atoms: data.elements.length, bonds: data.bonds.length, rawBytes: raw.byteLength, compressedBytes: compressed.byteLength }) + '\n')
  guest.dispose(); atom.dispose()
}, 60000)
