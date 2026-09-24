import * as THREE from 'three'
import { it, expect, vi } from 'vitest'
import { initNativeViewToolSharing } from './native_view_tool_sharing.js'
function setup() {
  let context = 'native', room = 'room', busy = false
  const state = { currentDesign: { id: 'part' } }, view = { viewTools: { sequences: false } }
  const sourceScene = new THREE.Scene(), pose = { position: [0, 0, 10] }
  const prepared = { captureView: () => ({ scene: sourceScene, view, pose }), exportView: vi.fn(async () => ({ buffer: new ArrayBuffer(1) })) }
  const publish = vi.fn(async () => true)
  const ui = initNativeViewToolSharing({ prepared, store: { getState: () => state }, getContext: () => context, getRoom: () => ({ id: room }), isBusy: () => busy, publish, onError: vi.fn(), setInterval: () => 1, clearInterval: () => {} })
  return { ui, sourceScene, pose, prepared, publish, view, state, context: v => { context = v }, room: v => { room = v }, busy: v => { busy = v } }
}
it('mirrors toggles after explicit publication, without requiring camera sharing', async () => {
  const v = setup(); await v.ui.tick(); expect(v.publish).not.toHaveBeenCalled()
  v.ui.remember(); await v.ui.tick(); expect(v.publish).not.toHaveBeenCalled()
  v.view.viewTools.sequences = true; await v.ui.tick(); expect(v.publish).toHaveBeenCalledOnce()
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledOnce()
  v.view.viewTools.sequences = false; await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(2)
  v.ui.dispose()
})
it('holds private jobs, different documents and rooms; drops stale in-flight exports', async () => {
  const v = setup(); v.ui.remember(); v.view.viewTools.sequences = true
  v.context('private-job'); await v.ui.tick(); expect(v.publish).not.toHaveBeenCalled()
  v.context('native'); v.room('different'); await v.ui.tick(); expect(v.publish).not.toHaveBeenCalled()
  v.room('room'); v.state.currentDesign.id = 'private'; await v.ui.tick(); expect(v.publish).not.toHaveBeenCalled()
  v.state.currentDesign.id = 'part'; v.busy(true); await v.ui.tick(); expect(v.publish).not.toHaveBeenCalled()
  v.busy(false); let finish
  v.prepared.exportView.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const flight = v.ui.tick(); await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  v.ui.clear(); finish({ buffer: new ArrayBuffer(1) }); await flight
  expect(v.publish).not.toHaveBeenCalled(); v.ui.dispose()
})

it('mirrors annotation visibility, text edits and manual placement without a tool toggle', async () => {
  const v = setup(); v.view.annotations = []; v.ui.remember()
  v.view.annotations = [{ id: 'a', text: 'Target', screenPos: null }]
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(1)
  v.view.annotations[0].text = 'Edited target'
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(2)
  v.view.annotations[0].screenPos = { x: .5, y: .2 }
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(3)
  v.view.annotations = []
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(4)
  v.ui.dispose()
})

it('mirrors selection, deselection and repeated ping events without sharing the camera', async () => {
  const v = setup(); v.view.selection = null; v.ui.remember()
  v.view.selection = { label: 'Base', revision: 1, target: 'cloud', ping: null }
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(1)
  v.view.selection.ping = { id: 'one', createdAt: 10 }
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(2)
  v.view.selection.ping = { id: 'two', createdAt: 20 }
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(3)
  v.view.selection = null
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(4)
  v.ui.dispose()
})

it('mirrors representations and volume transforms while ignoring camera movement', async () => {
  const v = setup(), volume = new THREE.Group()
  v.sourceScene.add(volume); v.ui.remember()
  v.pose.position[0] = 25
  await v.ui.tick(); expect(v.publish).not.toHaveBeenCalled()
  v.view.representation = 'mrdna-coarse'
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(1)
  volume.position.x = 3
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(2)
  volume.visible = false
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(3)
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(3)
  v.ui.dispose()
})
it('shares changing hull windows even when their editing outlines are hidden', async () => {
  const v = setup(), hull = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshPhongMaterial())
  v.sourceScene.add(hull); v.ui.remember()
  hull.material.userData.hullCutouts = [{ inverse: new THREE.Matrix4().toArray(), half: [1,1,1], hex: false }]
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(1)
  hull.material.userData.hullCutouts[0].half[0] = 2
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(2)
  v.ui.dispose()
})

it('coalesces design and geometry updates and publishes the final revision without a toggle', async () => {
  const v = setup(); v.ui.remember()
  v.state.currentDesign = { id: 'part', overhangs: [{ id: 'new' }] }
  await v.ui.tick(); expect(v.publish).not.toHaveBeenCalled()
  v.state.currentGeometry = [{ helix_id: 'new' }]
  await v.ui.tick(); expect(v.publish).not.toHaveBeenCalled()
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledOnce()
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledOnce()
  v.ui.dispose()
})

it('discards an export superseded by another design edit and retries the latest scene', async () => {
  const v = setup(); v.ui.remember()
  v.state.currentDesign = { id: 'part', name: 'resized' }
  await v.ui.tick()
  let finish
  v.prepared.exportView.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const flight = v.ui.tick()
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  v.state.currentDesign = { id: 'part', name: 'extruded' }
  finish({ buffer: new ArrayBuffer(1) }); await flight
  expect(v.publish).not.toHaveBeenCalled()
  await v.ui.tick(); await v.ui.tick()
  expect(v.publish).toHaveBeenCalledOnce()
  v.ui.dispose()
})

it('does not send a partially changed display after asynchronous preparation', async () => {
  const v = setup(); v.ui.remember(); v.view.representation = 'stick'
  v.prepared.exportView.mockImplementationOnce(async () => {
    v.sourceScene.add(new THREE.Group())
    return { buffer: new ArrayBuffer(1) }
  })
  await v.ui.tick(); expect(v.publish).not.toHaveBeenCalled()
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledOnce()
  v.ui.dispose()
})

it('does not starve design updates when render frames refresh GPU upload counters', async () => {
  const v = setup(), mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial())
  v.sourceScene.add(mesh); v.ui.remember()
  v.state.currentDesign = { id: 'part', overhangs: ['new'] }
  await v.ui.tick()
  mesh.material.needsUpdate = true; mesh.geometry.attributes.position.needsUpdate = true
  await v.ui.tick()
  expect(v.publish).toHaveBeenCalledOnce()
  v.ui.dispose()
})

it('does not republish idle GPU uploads, but still shares actual buffer edits', async () => {
  const v = setup(), mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial(), 2)
  mesh.setColorAt(0, new THREE.Color('red')); v.sourceScene.add(mesh); v.ui.remember()
  for (let frame = 0; frame < 4; frame++) {
    mesh.material.needsUpdate = true
    for (const attribute of [mesh.instanceMatrix, mesh.instanceColor, mesh.geometry.attributes.position, mesh.geometry.index]) attribute.needsUpdate = true
    await v.ui.tick()
  }
  expect(v.prepared.exportView).not.toHaveBeenCalled()
  mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(4, 0, 0)); mesh.instanceMatrix.needsUpdate = true
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(1)
  mesh.geometry.attributes.position.setX(0, 6); mesh.geometry.attributes.position.needsUpdate = true
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(2)
  mesh.setColorAt(0, new THREE.Color('blue')); mesh.instanceColor.needsUpdate = true
  await v.ui.tick(); expect(v.publish).toHaveBeenCalledTimes(3)
  v.ui.dispose()
})
