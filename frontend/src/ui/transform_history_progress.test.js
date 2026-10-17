import { afterEach, expect, it, vi } from 'vitest'
import { createTransformHistoryProgress } from './transform_history_progress.js'

const owned = []
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve() }
function create(options = {}) {
  const value = createTransformHistoryProgress({ onCancel: async () => true, ...options })
  owned.push(value); return value
}
const dialog = () => document.querySelector('[data-transform-history-progress]')
const cancel = () => [...dialog().querySelectorAll('button')].find(button => button.textContent === 'Cancel')
afterEach(() => { owned.splice(0).forEach(item => item.dispose()); vi.useRealTimers(); document.body.innerHTML = '' })

it('uses an owned modal with elapsed time and no percentage or completion estimate', () => {
  vi.useFakeTimers(); const progress = create(); progress.show({ operation: 'prepare' })
  expect(dialog().getAttribute('role')).toBe('dialog')
  expect(dialog().textContent).toMatch(/preparing.*historical/i)
  vi.advanceTimersByTime(2500)
  expect(dialog().textContent).toContain('2.5s')
  expect(dialog().textContent).not.toMatch(/%|ETA|estimated completion/i)
  expect(dialog().querySelector('[role="progressbar"]')).toBeNull()
})
it('shows validated server computation phase and elapsed without turning its remaining allowance into an ETA', () => {
  vi.useFakeTimers(); const progress = create()
  progress.show({ operation: 'apply', computation: { version: 1, operation: 'apply', request_sequence: 4,
    elapsed_seconds: 12.25, remaining_seconds: 167.75 } })
  expect(dialog().textContent).toMatch(/rebuilding.*later features/i)
  expect(dialog().textContent).toContain('12.3s')
  vi.advanceTimersByTime(1000)
  expect(dialog().textContent).toContain('13.3s')
  expect(dialog().textContent).not.toMatch(/167|ETA|%/)
})
it.each(['button', 'escape', 'close'])('%s cancellation is bound to this owner and closes on acknowledgement', async action => {
  const onCancel = vi.fn(async () => true), progress = create({ onCancel })
  progress.show({ operation: 'prepare' })
  if (action === 'button') cancel().click()
  if (action === 'escape') window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  if (action === 'close') dialog().querySelector('[aria-label="Close"]').click()
  await tick(); expect(onCancel).toHaveBeenCalledOnce(); expect(dialog()).toBeNull()
})
it('deduplicates a held cancellation and keeps the window if publication cannot be cancelled', async () => {
  let resolve; const onCancel = vi.fn(() => new Promise(done => { resolve = done })), progress = create({ onCancel })
  progress.show({ operation: 'apply' }); const button = cancel(); button.click()
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); expect(onCancel).toHaveBeenCalledOnce()
  expect(button.disabled).toBe(true); resolve(false); await tick()
  expect(dialog()).not.toBeNull(); expect(dialog().textContent).toMatch(/not.*confirmed|saved result|commit/i)
  expect(cancel().disabled).toBe(false)
})
it('reports a cancellation failure as text and permits a deliberate retry', async () => {
  const onCancel = vi.fn().mockRejectedValueOnce(new Error('<b>connection lost</b>')).mockResolvedValue(true)
  const progress = create({ onCancel }); progress.show({ operation: 'apply' })
  cancel().click(); await tick()
  expect(dialog().textContent).toContain('<b>connection lost</b>'); expect(dialog().querySelector('b')).toBeNull()
  cancel().click(); await tick(); expect(dialog()).toBeNull()
})
it('a disposed cancellation continuation cannot close a newer owner or retain a timer', async () => {
  vi.useFakeTimers(); let resolve
  const first = create({ onCancel: () => new Promise(done => { resolve = done }) })
  first.show({ operation: 'prepare' }); cancel().click(); first.dispose()
  const second = create(); second.show({ operation: 'prepare' }); const next = dialog()
  resolve(true); await tick(); expect(dialog()).toBe(next)
  second.dispose(); expect(dialog()).toBeNull()
  // Each real focus schedules JSDOM's one-shot selectionchange. An uncleared
  // recurring clock would remain counted after this zero-duration flush.
  vi.advanceTimersByTime(0); expect(vi.getTimerCount()).toBe(0)
})
