/**
 * Flexible-segment latency probe.
 *
 * This deliberately uses Hinge_test.nadoc and the browser's real API/store/render
 * path.  Run with `window.__nadocOperationTraceAll` enabled so a failure leaves a
 * paste-friendly phase breakdown in the Playwright output.
 */
import { test, expect } from '@playwright/test'
import path from 'node:path'

const FIXTURE = path.resolve('../workspace/Hinge_test.nadoc')

async function loadHinge(page, doc) {
  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')
  await page.evaluate(async fixture => {
    window.__nadocOperationTraceAll = true
    const api = await import('/src/api/client.js')
    await api.loadDesign(fixture)
  }, FIXTURE)
  await page.waitForFunction(() =>
    (window.__nadocTest?.store?.getState?.().currentGeometry?.length ?? 0) > 0)
  // Loading Hinge_test performs a large initial scene build and autosave. Measure
  // the edit after that work has presented, as a user right-clicking the settled
  // design would experience it.
  await page.waitForFunction(async () => {
    const { activeOperationTiming } = await import('/src/perf/operation_timing.js')
    return activeOperationTiming() == null
  })
  await page.waitForTimeout(500)
}

async function unmarkedRuns(page, wanted) {
  return page.evaluate(async count => {
    const state = window.__nadocTest.store.getState()
    const { flexibleRunForBead } = await import('/src/scene/design_queries.js')
    const marked = new Set((state.currentDesign.flexible_segment_marks ?? []).map(mark =>
      `${mark.strand_id}:${mark.domain_index}:${mark.bp_index}:${mark.direction}`))
    const seen = new Set()
    const runs = []
    for (const nuc of state.currentGeometry.filter(n => n.is_unpaired && n.strand_id)) {
      const run = flexibleRunForBead(state.currentDesign, state.currentGeometry, nuc)
      const signature = run.map(mark =>
        `${mark.strand_id}:${mark.domain_index}:${mark.bp_index}:${mark.direction}`
      ).sort().join('|')
      if (!signature || seen.has(signature) || run.some(mark => marked.has(
        `${mark.strand_id}:${mark.domain_index}:${mark.bp_index}:${mark.direction}`))) continue
      seen.add(signature)
      runs.push(run)
      if (runs.length === count) break
    }
    return runs
  }, wanted)
}

test('mark flexible segment confirms within 200 ms and records the final frame', async ({ page }) => {
  test.setTimeout(120_000)
  await loadHinge(page, '__e2e__flexible-latency')
  const [run] = await unmarkedRuns(page, 1)
  expect(run?.length).toBeGreaterThan(0)
  await page.evaluate(marks => {
    window.__flexMarkProbe = { clickAt: null, confirmationAt: null, timing: null }
    const observer = new MutationObserver(() => {
      const visible = [...document.querySelectorAll('.toast--visible .toast-message')]
        .some(el => /^Marked \d+-base flexible segment$/.test(el.textContent ?? ''))
      if (visible && window.__flexMarkProbe.confirmationAt == null) {
        window.__flexMarkProbe.confirmationAt = performance.now()
        observer.disconnect()
      }
    })
    observer.observe(document.body, { childList: true, subtree: true, attributes: true })
    addEventListener('nadoc:operation-timing', event => {
      if (event.detail?.label === 'Mark flexible segment') {
        window.__flexMarkProbe.timing = event.detail
      }
    })
    // This is the exact named callback the context-menu handler enters after it
    // has resolved the clicked bead to a contiguous run.
    window.__flexMarkProbe.clickAt = performance.now()
    void window.__nadocTest.markFlexibleRun(marks)
  }, run)
  await page.waitForFunction(() => window.__flexMarkProbe?.timing != null)
  const probe = await page.evaluate(() => window.__flexMarkProbe)
  const timing = probe.timing

  console.log('flexible segment timing', JSON.stringify(timing))
  const confirmationMs = probe.confirmationAt - probe.clickAt
  console.log('flexible segment optimistic confirmation ms', confirmationMs)
  expect(confirmationMs).toBeLessThan(200)
  expect(timing.marks.map(mark => mark.name)).toEqual(expect.arrayContaining([
    'optimistic-confirmation-visible', 'response-received', 'response-parsed',
    'store-applied', 'final-render',
  ]))
  // Full persistence/render remains measured even though the interaction is
  // acknowledged immediately; keep a generous software-WebGL regression cap.
  expect(timing.totalMs).toBeLessThan(5000)
})

test('two rapid additive marks both survive', async ({ page }) => {
  test.setTimeout(120_000)
  await loadHinge(page, '__e2e__flexible-rapid')
  const runs = await unmarkedRuns(page, 2)
  expect(runs).toHaveLength(2)
  const before = await page.evaluate(() =>
    window.__nadocTest.store.getState().currentDesign.flexible_segment_marks.length)
  await page.evaluate(([first, second]) => Promise.all([
    window.__nadocTest.markFlexibleRun(first),
    window.__nadocTest.markFlexibleRun(second),
  ]), runs)
  const added = runs[0].length + runs[1].length

  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest.store.getState().currentDesign.flexible_segment_marks.length),
    { timeout: 15_000 },
  ).toBe(before + added)
})
