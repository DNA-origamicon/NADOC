import { afterEach, expect, it } from 'vitest'
import { initDesignReadiness } from './design_readiness.js'
import { initDesignReadinessVisibility } from './design_readiness_visibility.js'
import { withMediaExport } from '../shared/media_export_activity.js'

let widget, visibility
afterEach(() => { visibility?.dispose(); widget?.dispose(); document.body.replaceChildren() })
const report = { available: true, total_steps: 5, completed_steps: 4, steps: [] }
function setup(lighting = false) {
  document.body.innerHTML = '<input id="photo-lighting-enabled" type="checkbox"><div id="host"></div>'
  document.querySelector('input').checked = lighting
  widget = initDesignReadiness({ host: document.getElementById('host') })
  widget.setReport(report)
  visibility = initDesignReadinessVisibility({ widget })
  return document.querySelector('[data-role="design-readiness"]')
}
const light = active => window.dispatchEvent(new CustomEvent('nadoc:lighting-change', { detail: { active } }))

it('hides on lighting activation, including initial state, and keeps refreshed reports hidden', () => {
  const root = setup(true)
  expect(root.hidden).toBe(true)
  widget.setLoading()
  widget.setReport(report)
  widget.open()
  expect(root.hidden).toBe(true)
  expect(root.querySelector('.design-readiness__popover').hidden).toBe(true)
  light(false)
  expect(root.hidden).toBe(false)
  widget.open()
  light(true)
  expect(root.hidden).toBe(true)
  expect(root.querySelector('.design-readiness__popover').hidden).toBe(true)
})

it('keeps overlapping captures hidden until both end, restores on failure, and respects lighting', async () => {
  const root = setup()
  let resolveFirst, rejectSecond
  const first = withMediaExport(() => new Promise(resolve => { resolveFirst = resolve }))
  const second = withMediaExport(() => new Promise((_, reject) => { rejectSecond = reject }))
  expect(root.hidden).toBe(true)
  resolveFirst()
  await first
  expect(root.hidden).toBe(true)
  rejectSecond(new Error('Capture failed'))
  await expect(second).rejects.toThrow('Capture failed')
  expect(root.hidden).toBe(false)
  await withMediaExport(() => { light(true); widget.setError('Offline') })
  expect(root.hidden).toBe(true)
  light(false)
  expect(root.hidden).toBe(false)
  widget.setReport({ ...report, completed_steps: 5, state: 'ready', simulation: { complete: true } })
  await withMediaExport(() => {})
  light(false)
  expect(root.hidden).toBe(true)
})

it('unsubscribes export and lighting listeners on disposal', async () => {
  const root = setup()
  visibility.dispose()
  light(true)
  await withMediaExport(() => expect(root.hidden).toBe(false))
  expect(root.hidden).toBe(false)
})
