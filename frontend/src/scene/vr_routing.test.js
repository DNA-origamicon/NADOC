// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { createVRRouting, ROUTING_ACTIONS } from './vr_routing.js'
import { initAutoscaffoldPicker } from '../ui/autoscaffold_picker.js'
import { showConfirm } from '../ui/primitives/confirm.js'
let bridge
const setup = () => {
  document.body.innerHTML = ROUTING_ACTIONS.map(([id,label]) => `<button id="${id}">${label}</button>`).join('') + `<div id="autoscaffold-modal"><label><input type="radio" name="as-mode" value="seamed" checked>Seamed</label><label><input type="radio" name="as-mode" value="seamless">Seamless</label><button id="as-cancel">Cancel</button><button id="as-run">Run</button></div>`
  let wire, sequence = 0
  bridge = createVRRouting({ request: async (_, opts) => { wire = JSON.parse(opts.body); return { ok: true } } })
  return { async click(id) { await bridge.publish(); await bridge.activate({ sequence: ++sequence, version: wire.version, id }) }, state: () => wire }
}
afterEach(() => bridge?.dispose())
it('uses the real routing picker, both strategies, and deduplicates events', async () => {
  const driver = setup(), seamed = vi.fn(async () => true), seamless = vi.fn(async () => true)
  initAutoscaffoldPicker({ store: { getState: () => ({ currentDesign: {} }) }, api: { autoScaffoldSeamed: seamed, autoScaffoldSeamless: seamless }, setRoutingCheck: vi.fn() })
  await driver.click('menu-routing-scaffold-ends')
  expect(bridge.snapshot().title).toBe('Autoscaffold')
  await driver.click(bridge.snapshot().controls.find(c => c.label === 'Seamless').id)
  expect(document.querySelector('[value=seamless]').checked).toBe(true)
  await driver.click(bridge.snapshot().controls.find(c => c.label === 'Run').id)
  expect(seamless).toHaveBeenCalledTimes(1)
  await bridge.activate({ sequence: 3, version: driver.state().version, id: 'dialog-3' })
  expect(seamless).toHaveBeenCalledTimes(1)
  await driver.click('dismiss'); await driver.click('menu-routing-scaffold-ends')
  await driver.click(bridge.snapshot().controls.find(c => c.label === 'Seamed').id)
  await driver.click(bridge.snapshot().controls.find(c => c.label === 'Run').id)
  expect(seamed).toHaveBeenCalledTimes(1)
})
it('routes confirmation cancel and confirm, and blocks background actions', async () => {
  const driver = setup(), cleared = vi.fn(), undo = vi.fn()
  document.getElementById('menu-edit-undo').onclick = undo
  document.getElementById('menu-seq-clear-all-loop-skips').onclick = async () => { if (await showConfirm({ title: 'Clear loops & skips', message: 'Remove all?', confirmLabel: 'Clear all' })) cleared() }
  await driver.click('menu-seq-clear-all-loop-skips')
  await driver.click('menu-edit-undo'); expect(undo).not.toHaveBeenCalled()
  await driver.click(bridge.snapshot().controls.find(c => c.label === 'Cancel').id)
  expect(cleared).not.toHaveBeenCalled()
  await driver.click('dismiss'); await driver.click('menu-seq-clear-all-loop-skips')
  await driver.click(bridge.snapshot().controls.find(c => c.label === 'Clear all').id)
  expect(cleared).toHaveBeenCalledTimes(1)
})
it('edits a custom sequence through input events, preserves it, and accepts preset choices', async () => {
  const driver = setup()
  document.body.insertAdjacentHTML('beforeend', '<div class="modal__overlay"><div class="modal__title">Assign Scaffold Sequence</div><div class="modal__body"><label><input type="radio" name="preset" value="p8064">p8064</label><textarea id="asc-custom-seq"></textarea></div><button>Apply</button></div>')
  const input = vi.fn(); document.querySelector('textarea').oninput = input
  await driver.click('custom-sequence')
  for (const base of ['a','c','g','t','n']) await driver.click(`key-${base}`)
  expect(document.querySelector('textarea').value).toBe('ACGTN')
  expect(input).toHaveBeenCalledTimes(5)
  await driver.click('key-delete'); await driver.click('key-done')
  expect(document.querySelector('textarea').value).toBe('ACGT')
  await driver.click(bridge.snapshot().controls.find(c => c.label === 'p8064').id)
  expect(document.querySelector('input[name=preset]').checked).toBe(true)
})
it('rejects stale and disabled actions, waits for requests, and exposes errors and history', async () => {
  const driver = setup(), run = vi.fn(() => window.dispatchEvent(new CustomEvent('nadoc:api-request', { detail: { phase:'start', id:1, method:'POST', path:'/design/full-autostaple' } })))
  document.getElementById('menu-routing-full-autostaple').onclick = run
  await bridge.publish(); const stale = driver.state().version
  document.getElementById('menu-routing-full-autostaple').disabled = true
  await bridge.activate({ sequence: 1, version: stale, id:'menu-routing-full-autostaple' })
  expect(run).not.toHaveBeenCalled()
  bridge.reset(); document.getElementById('menu-routing-full-autostaple').disabled = false
  await driver.click('menu-routing-full-autostaple')
  expect(bridge.snapshot().controls.every(row => !row.enabled)).toBe(true)
  window.dispatchEvent(new CustomEvent('nadoc:api-request', { detail: { phase:'error', id:1, message:'Routing failed' } }))
  expect(bridge.snapshot().controls.some(row => row.label === 'Routing failed')).toBe(true)
  const undo = vi.fn();document.getElementById('menu-edit-undo').onclick = undo
  await driver.click('menu-edit-undo');expect(undo).toHaveBeenCalledOnce()
})
it('keeps autosave out of dialog busy state and reflects checker toggles', async () => {
  const driver = setup()
  await driver.click('menu-seq-hairpin-dimer')
  window.dispatchEvent(new CustomEvent('nadoc:api-request', { detail: { phase:'start', id:9, method:'POST', path:'/design/save-workspace' } }))
  expect(bridge.snapshot().controls.find(c => c.id === 'dismiss').enabled).toBe(true)
  document.getElementById('menu-seq-hairpin-dimer').classList.add('is-on')
  expect(bridge.snapshot().roots.find(c => c.id === 'menu-seq-hairpin-dimer').active).toBe(true)
})
it('keeps generated native actions aligned with the bridge allowlist', async () => {
  const { readFileSync } = await import('node:fs')
  const catalog = JSON.parse(readFileSync('../native/vr_viewer/sidebar_catalog.json', 'utf8'))
  const tools = catalog.tabs.find(tab => tab.side === 'right' && tab.key === 'tools')
  expect(tools.rows.filter(row => row.action.startsWith('routing:')).map(row => row.action.slice(8))).toEqual(ROUTING_ACTIONS.map(([id]) => id))
})
