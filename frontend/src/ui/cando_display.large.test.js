import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { initCandoDisplay } from './cando_display.js'
import { initCandoLargeView } from '../scene/cando_large_view.js'

function buffer(kind) {
  const h = new TextEncoder().encode(JSON.stringify({ kind, count: 2, min: 0, max: 1, identities: false }))
  const offset = Math.ceil((12 + h.length) / 4) * 4
  const b = new ArrayBuffer(offset + 32), v = new DataView(b)
  ;[0x5A495643, 1, h.length].forEach((n,i) => v.setUint32(4*i,n,true))
  new Uint8Array(b,12,h.length).set(h)
  return b
}
function deps() {
  const scene = new THREE.Scene()
  const api = { getCandoJob: vi.fn(async () => ({ n_nucleotides: 424144 })),
    getCandoVisualizationBin: vi.fn(async (id, mode) => buffer(mode)),
    getCandoSnapshotGeometry: vi.fn(), getCandoThermalTrajectory: vi.fn() }
  const designRenderer = { clearScalarColors: vi.fn(), clearExternalGeometry: vi.fn() }
  const restoreDesignVisible = vi.fn(), setDesignVisible = vi.fn()
  return { scene, api, designRenderer, restoreDesignVisible, setDesignVisible,
    largeView: initCandoLargeView(scene) }
}
it('all four large views avoid full scenes and ensembles, then Off frees the overlay', async () => {
  const d = deps(), controller = initCandoDisplay(d)
  for (const fn of ['showDeform', 'showFlex', 'showDeviation', 'showCandoStyle']) {
    expect((await controller[fn]('job')).ok).toBe(true)
    expect(d.scene.children).toHaveLength(1)
    expect(controller.lastStats().large).toBe(true)
  }
  expect(d.api.getCandoSnapshotGeometry).not.toHaveBeenCalled()
  expect(d.api.getCandoThermalTrajectory).not.toHaveBeenCalled()
  controller.stopDeform()
  expect(d.scene.children).toHaveLength(0)
  expect(d.restoreDesignVisible).toHaveBeenCalled()
})
it('Off and newer modes win even when an aborted transport resolves late', async () => {
  const d = deps(), controller = initCandoDisplay(d)
  let finish
  d.api.getCandoVisualizationBin.mockImplementationOnce(() => new Promise(r => { finish = r }))
  const old = controller.showDeform('old').catch(e => e.name)
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  controller.stopDeform()
  await controller.showFlex('new')
  finish(buffer('deform'))
  expect(await old).toBe('AbortError')
  expect(controller.deformJobId()).toBe('new')
  expect(controller.mode()).toBe('flex')
  expect(d.scene.children).toHaveLength(1)
})
it('failed compact results do not fall back to an unbounded full scene', async () => {
  const d = deps(), controller = initCandoDisplay(d)
  d.api.getCandoVisualizationBin.mockResolvedValue(null)
  await expect(controller.showDeform('job')).rejects.toThrow('unavailable')
  expect(d.scene.children).toHaveLength(0)
  expect(d.api.getCandoSnapshotGeometry).not.toHaveBeenCalled()
})
it('hides the expensive native scene immediately when panel metadata identifies a large job', async () => {
  const d = deps(), controller = initCandoDisplay(d)
  let finish
  d.api.getCandoVisualizationBin.mockImplementationOnce(() => new Promise(r => { finish = r }))
  const pending = controller.showDeform('job', null, { nNucleotides: 424144 }).catch(e => e.name)
  expect(d.setDesignVisible).toHaveBeenCalledWith(false)
  expect(d.api.getCandoJob).not.toHaveBeenCalled()
  controller.cancelPending()
  finish(buffer('deform'))
  expect(await pending).toBe('AbortError')
  expect(d.restoreDesignVisible).toHaveBeenCalled()
  expect(d.scene.children).toHaveLength(0)
})
