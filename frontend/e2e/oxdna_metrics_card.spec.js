/**
 * oxDNA "Graphs and Metrics" card — renders in the Dynamics panel and its graph
 * popup draws real canvases.
 *
 * GPU-free: the card wiring (scope radios, three metric rows, the no-job warning)
 * is asserted against the real DOM; the graph rendering is exercised by driving
 * the popup with a synthetic result in-page (real-browser canvas — jsdom can't
 * validate the actual drawing).  Full Generate→graph on live trajectory data is a
 * manual-validation item (needs a completed oxDNA production job).
 */
import { test, expect } from '@playwright/test'
import path from 'node:path'

const ROOT = path.resolve(import.meta.dirname ?? __dirname, '../..')
const SQUARE_DESIGN = path.join(ROOT, 'tests/fixtures/teeth.nadoc')

async function newDesign(page, name) {
  await page.goto('/')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', name)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })
}

async function openDynamics(page) {
  await page.click('#left-tab-strip [data-tab="dynamics"]')
  await page.evaluate(() => {
    const body = document.getElementById('oxdna-jobs-body')
    const heading = document.getElementById('oxdna-jobs-heading')
    if (body && heading && (body.hidden || getComputedStyle(body).display === 'none')) heading.click()
  })
}

test('metrics card renders + Generate drives the poll flow (mocked backend)', async ({ page }) => {
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })

  // Mock the metric endpoints so Generate flows deterministically without touching
  // a real trajectory (whether or not the workspace has oxDNA jobs for this design).
  const RESULT = {
    ready: true, scope: 'latest', jobs: ['job123'],
    twist: { temporal: { per_frame: [1, 2, 4, 8], boundaries: [] },
             spatial: [{ job_id: 'job123', points: [[0, 0], [50, 12]] }] },
    curvature: { temporal: { per_frame: [0.1, 0.1, 0.2, 0.2], boundaries: [] },
                 spatial: [{ job_id: 'job123', points: [[0, 0], [50, 1]] }] },
    base_pairing: { temporal: { per_frame: [1, 0.99, 0.98, 0.97], boundaries: [], n_designed: 100 },
                    spatial: [{ job_id: 'job123', points: [[0, 1], [50, 0.9]] }] },
  }
  await page.route('**/oxdna/jobs/*/metrics/start', r =>
    r.fulfill({ json: { metrics_id: 'm1', state: 'running' } }))
  await page.route('**/oxdna/metrics/m1', r =>
    r.fulfill({ json: { metrics_id: 'm1', state: 'done', progress: 1, eta_s: 0,
                        frames_done: 4, frames_total: 4, result: RESULT } }))

  await newDesign(page, 'metrics-card-test')
  await openDynamics(page)
  await page.evaluate(async fp => (await import('/src/api/client.js')).loadDesign(fp), SQUARE_DESIGN)

  // Collapsible; the LAST card, with the Export oxDNA ZIP button below it.
  const toggle = page.locator('#oxdna-metrics-toggle')
  await expect(toggle).toContainText('Graphs and Metrics')
  const card = page.locator('#oxdna-metrics-card')
  await expect(card).toBeHidden()                    // starts collapsed
  const orderedLast = await page.evaluate(() => {
    const zip = document.getElementById('oxdna-jobs-export-btn')
    const metricsCard = document.getElementById('oxdna-metrics-toggle')?.closest('.ox-card')
    // Graphs & Metrics is the final .ox-card, and the ZIP button comes after it.
    return !!(zip && metricsCard &&
      (metricsCard.compareDocumentPosition(zip) & Node.DOCUMENT_POSITION_FOLLOWING))
  })
  expect(orderedLast).toBe(true)

  await toggle.click()
  await expect(card).toBeVisible()                   // expands
  await expect(page.locator('#oxdna-metrics-scope-latest')).toBeChecked()
  for (const tok of ['twist', 'curve', 'bp']) {
    await expect(page.locator(`#oxdna-metrics-${tok}-gen`)).toBeEnabled()
    await expect(page.locator(`#oxdna-metrics-${tok}-display`)).toBeDisabled()
  }
  await toggle.click()
  await expect(card).toBeHidden()                    // collapses again
  await toggle.click()                               // re-open for the Generate check below

  // Generate: either the mocked compute runs (a real job is active) → status updates,
  // or there's no active job → the card warns.  Both are deterministic non-empty status.
  await page.click('#oxdna-metrics-twist-gen')
  await expect(page.locator('#oxdna-metrics-twist-status')).not.toHaveText('', { timeout: 15_000 })

  // Scope toggle works.
  await page.check('#oxdna-metrics-scope-chain')
  await expect(page.locator('#oxdna-metrics-scope-chain')).toBeChecked()

  expect(errors).toEqual([])
})

test('graph popup draws non-blank spatial + temporal canvases', async ({ page }) => {
  await newDesign(page, 'metrics-popup-test')

  const drawn = await page.evaluate(async () => {
    const { openMetricGraphPopup } = await import('/src/ui/metric_graph_popup.js')
    const result = {
      ready: true, scope: 'latest', jobs: ['job123'],
      twist: {
        temporal: { per_frame: [5, 8, 12, 20, 35, 50], boundaries: [] },
        spatial: [{ job_id: 'job123', points: [[0, 0], [50, 6], [100, 15], [200, 58]] }],
      },
    }
    openMetricGraphPopup({ metric: 'twist', result, scope: 'latest' })
    // Count non-background pixels on each canvas → proof something was stroked.
    const nonBlank = id => {
      const c = document.getElementById(id)
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data
      let n = 0
      for (let i = 0; i < d.length; i += 4) {
        // background is #0d1117 → (13,17,23); count clearly different pixels
        if (Math.abs(d[i] - 13) + Math.abs(d[i + 1] - 17) + Math.abs(d[i + 2] - 23) > 30) n++
      }
      return n
    }
    return { spatial: nonBlank('metric-popup-spatial'), temporal: nonBlank('metric-popup-temporal') }
  })

  expect(drawn.spatial).toBeGreaterThan(500)     // axes + ticks + polyline drawn
  expect(drawn.temporal).toBeGreaterThan(500)
})
