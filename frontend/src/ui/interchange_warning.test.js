import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createInterchangeExport, showInterchangeWarning } from './interchange_warning.js'

const report = (blocked = false) => ({ format: 'cadnano', token: 'reviewed-design', blocked,
  issues: [{ code: 'extras', label: 'Junction extra bases', count: 2, effect: 'Cannot preserve TT.', severity: blocked ? 'error' : 'warning' },
    { code: 'transforms', label: 'Cluster transforms', count: 3, effect: 'Omitted.', severity: 'warning' }] })

beforeEach(() => {
  document.body.innerHTML = ''
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.open = false }
})

describe('interchange review dialog', () => {
  it('lists every issue and cancels without acknowledging', async () => {
    const done = showInterchangeWarning(report())
    expect(document.querySelectorAll('li')).toHaveLength(2)
    expect(document.body.textContent).toContain('Cluster transforms (3)')
    document.querySelector('button').click()
    expect(await done).toBe(false)
    expect(document.querySelector('dialog')).toBeNull()
  })
  it('allows explicit loss acknowledgment only without blockers', async () => {
    const done = showInterchangeWarning(report())
    document.querySelectorAll('button')[1].click()
    expect(await done).toBe(true)
    const blocked = showInterchangeWarning(report(true))
    expect(document.querySelectorAll('button')).toHaveLength(1)
    expect(document.body.textContent).toContain('blocks export')
    document.querySelector('dialog').dispatchEvent(new Event('cancel', { cancelable: true }))
    expect(await blocked).toBe(false)
  })
  it('does not interpret design-provided text as HTML', async () => {
    const r = report(); r.issues[0].effect = '<img src=x onerror=alert(1)>'
    const done = showInterchangeWarning(r)
    expect(document.querySelector('img')).toBeNull()
    document.querySelector('button').click(); await done
  })
})

it('downloads only after acceptance with the exact reviewed token', async () => {
  const api = { getExportCompatibility: vi.fn().mockResolvedValue(report()), exportCadnano: vi.fn().mockResolvedValue(true) }
  const confirm = vi.fn().mockResolvedValue(false)
  const onError = vi.fn()
  const run = createInterchangeExport({ api, showWarning: confirm, onError })
  await run('cadnano'); expect(api.exportCadnano).not.toHaveBeenCalled()
  confirm.mockResolvedValue(true)
  await run('cadnano'); expect(api.exportCadnano).toHaveBeenCalledWith('reviewed-design')
  api.getExportCompatibility.mockResolvedValue(report(true))
  await run('cadnano'); expect(api.exportCadnano).toHaveBeenCalledTimes(1)
})

it('never downloads when preflight fails, and releases its busy state', async () => {
  const api = { getExportCompatibility: vi.fn().mockRejectedValue(new Error('offline')), exportScadnano: vi.fn() }
  const onError = vi.fn()
  const run = createInterchangeExport({ api, onError })
  await run('scadnano'); await run('scadnano')
  expect(api.getExportCompatibility).toHaveBeenCalledTimes(2)
  expect(onError).toHaveBeenCalledTimes(2)
  expect(api.exportScadnano).not.toHaveBeenCalled()
})
