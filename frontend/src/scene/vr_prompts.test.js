// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { createVRPrompts } from './vr_prompts.js'
import { setNativePromptHandler } from '../ui/primitives/native_prompt.js'
import { showConfirm } from '../ui/primitives/confirm.js'

const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve() }
function harness() {
  let current = {}, allowed = true
  const packets = [], onError = vi.fn()
  const bridge = createVRPrompts({ context: () => current, detailAllowed: () => allowed, onError,
    request: vi.fn(async (_, init) => { packets.push(JSON.parse(init.body));return { ok: true } }) })
  setNativePromptHandler(opts => bridge.ask(opts))
  bridge.setActive(true)
  return { bridge, packets, onError, changeContext: () => { current = {} }, restrict: () => { allowed = false },
    answer(id = '1', version = packets.at(-1).version) { bridge.activate({ sequence: 1, version, id }) } }
}
afterEach(() => { setNativePromptHandler(null);document.body.innerHTML = '' })
it('runs the original continuation only after an affirmative headset answer, without a desktop modal', async () => {
  const h = harness();await flush()
  const action = vi.fn()
  const waiting = showConfirm({ title: 'Delete strand', message: 'Remove S1?', confirmLabel: 'Delete', vr: true }).then(ok => { if(ok)action() })
  await flush()
  expect(document.querySelector('.modal__overlay')).toBeNull()
  expect(action).not.toHaveBeenCalled()
  expect(h.packets.at(-1)).toMatchObject({ title: 'Delete strand', options: [{ id: '0', label: 'Cancel' }, { id: '1', label: 'Delete' }] })
  h.answer('3');h.answer('1', 0);expect(action).not.toHaveBeenCalled()
  const version = h.packets.at(-1).version
  h.answer();await waiting;h.answer('1', version)
  expect(action).toHaveBeenCalledOnce()
})
it('queues decisions, cancels on context changes and session shutdown, and rejects late replies', async () => {
  const h = harness();await flush()
  const first = showConfirm({ vr: true, title: 'First' })
  const second = showConfirm({ vr: true, title: 'Second' })
  await flush();h.answer('0');expect(await first).toBe(false);await flush()
  expect(h.packets.at(-1).title).toBe('Second')
  h.changeContext();h.answer();expect(await second).toBe(false)
  const third = showConfirm({ vr: true, title: 'Third' });await flush()
  h.bridge.reset();h.answer();expect(await third).toBe(false)
})
it('treats a native heartbeat timeout as cancellation', async () => {
  const h = harness();await flush()
  const pending = showConfirm({ vr: true });await flush()
  h.answer('dismiss');expect(await pending).toBe(false)
})
it('preserves desktop dialogs while inactive and for workflows not opted in', async () => {
  const h = harness();h.bridge.reset()
  for (const opts of [{ vr: true }, {}]) {
    const pending = showConfirm(opts)
    const buttons = document.querySelectorAll('.modal__overlay button')
    const cancel = [...buttons].find(b => b.textContent === 'Cancel')
    expect(cancel).toBeTruthy();cancel.click();expect(await pending).toBe(false)
  }
})
it('publishes presentation restrictions even when no decision is open', async () => {
  const h = harness();await flush();h.restrict();await h.bridge.publish()
  expect(h.packets.at(-1)).toMatchObject({ detail_allowed: false, options: [] })
})
it('fails closed when the transport cannot publish, without retry loops or a hidden desktop modal', async () => {
  const onError = vi.fn()
  const request = vi.fn(async () => ({ ok: false }))
  const bridge = createVRPrompts({ request, onError });setNativePromptHandler(opts => bridge.ask(opts))
  bridge.setActive(true)
  const pending = showConfirm({ vr: true });await flush()
  expect(await pending).toBe(false)
  expect(await showConfirm({ vr: true })).toBe(false)
  expect(request).toHaveBeenCalledOnce();expect(onError).toHaveBeenCalledOnce()
  expect(document.querySelector('.modal__overlay')).toBeNull()
})
