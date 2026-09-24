import { it, expect, vi } from 'vitest'
import { initNativeViewToolSharing } from './native_view_tool_sharing.js'
function setup() {
  let context = 'native', room = 'room', busy = false
  const state = { currentDesign: { id: 'part' } }, view = { viewTools: { sequences: false } }
  const prepared = { captureView: () => ({ scene: { uuid: 'scene' }, view }), exportView: vi.fn(async () => ({ buffer: new ArrayBuffer(1) })) }
  const publish = vi.fn(async () => true)
  const ui = initNativeViewToolSharing({ prepared, store: { getState: () => state }, getContext: () => context, getRoom: () => ({ id: room }), isBusy: () => busy, publish, onError: vi.fn(), setInterval: () => 1, clearInterval: () => {} })
  return { ui, prepared, publish, view, state, context: v => { context = v }, room: v => { room = v }, busy: v => { busy = v } }
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
