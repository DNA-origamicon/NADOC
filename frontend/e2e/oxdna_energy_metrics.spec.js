/** Reads an existing job; no molecular authoring or simulation launch.
 * Downloads/screenshots stay in testInfo.outputPath (cleanup reporter).
 * __e2e__ autosaves/playback caches and test credentials: global teardown.
 */
import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'

const jobId = process.env.NADOC_ENERGY_REVIEW_JOB

test('real energy Generate → Display → annotated PNG and CSV export', async ({ page, request }, testInfo) => {
  test.skip(!jobId, 'Set NADOC_ENERGY_REVIEW_JOB to an existing thermal ramp')
  test.setTimeout(120000)
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  const jobResponse = await request.get(`/api/oxdna/jobs/${jobId}`)
  expect(jobResponse.ok()).toBe(true)
  const job = await jobResponse.json()
  await page.goto(`/?doc=__e2e__energy-metrics&open=${encodeURIComponent(job.design_source_path)}&open-type=design`)
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentGeometry?.length)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="oxdna"]').click()
  const row = page.locator(`#simulate-jobs-list [data-job-id="${jobId}"]`)
  await expect(row).toBeVisible({ timeout: 15000 })
  if (await row.evaluate(el => getComputedStyle(el).backgroundColor) !== 'rgb(42, 58, 74)') await row.click()
  await expect(row).toHaveCSS('background-color', 'rgb(42, 58, 74)', { timeout: 15000 })
  await page.locator('#oxdna-metrics-toggle').click()
  const generated = page.waitForResponse(async r => r.url().includes('/oxdna/metrics/')
    && r.request().method() === 'GET' && (await r.json()).state === 'done').catch(() => null)
  await page.locator('#oxdna-metrics-energy-gen').click()
  await expect(page.locator('#oxdna-metrics-energy-status')).toContainText('Ready', { timeout: 20000 })
  await expect(page.locator('#oxdna-metrics-energy-display')).toBeEnabled()
  const response = await generated
  const payload = await response.json()
  const data = payload.result.oxdna_energy.temporal
  expect(data.boundaries.length).toBeGreaterThan(0)
  await page.locator('#oxdna-metrics-energy-display').click()
  await expect(page.locator('#metric-popup-title')).toContainText('Potential energy')
  await expect(page.locator('#metric-popup-spatial')).toBeHidden()
  const yellowPixels = await page.locator('#metric-popup-temporal').evaluate(canvas => {
    const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
    let count = 0
    for (let i = 0; i < data.length; i += 4) if (data[i] > 90 && data[i+1] > 70 && data[i+2] < 100 && data[i] > data[i+1]) count++
    return count
  })
  expect(yellowPixels).toBeGreaterThan(50)
  for (const kind of ['png', 'data']) {
    await page.locator('#metric-popup-export').click()
    await page.locator(`#metric-export-${kind === 'png' ? 'data' : 'png'}`).uncheck()
    const downloading = page.waitForEvent('download')
    await page.locator('#metric-export-ok').click()
    const download = await downloading
    const filename = testInfo.outputPath(download.suggestedFilename())
    await download.saveAs(filename)
    const content = await readFile(filename)
    if (kind === 'png') expect(content.subarray(1,4).toString()).toBe('PNG')
    else {
      expect(content.toString()).toContain('temperature_c,stage,job_id')
      expect(content.toString().split('\n')).toHaveLength(data.per_frame.length + 2)
      expect(content.toString()).toContain(`,${data.temperature_c[0]},`)
    }
  }
  await page.screenshot({ path: testInfo.outputPath('energy-metrics.png') })
  // Deterministic 13-temperature layout fixture: no simulation or structure writes.
  const markerCount = await page.evaluate(async () => {
    const { openMetricGraphPopup, metricSpecs } = await import('/src/ui/metric_graph_popup.js')
    const temporal = { per_frame: [], x_values: [], boundaries: [] }
    for (let stage = 0; stage < 13; stage++) {
      temporal.boundaries.push({ start_x: stage * 100, temperature_c: 25 + stage * 5 })
      for (let t = 0; t <= 100; t += 10) {
        temporal.x_values.push(stage * 100 + t)
        temporal.per_frame.push(-1.4 + stage * .02 + .04 * Math.exp(-t/20))
      }
    }
    const result = { oxdna_energy: { temporal } }
    openMetricGraphPopup({ metric: 'oxdna_energy', result })
    return metricSpecs('oxdna_energy', result, 'latest').temporal.annotations.length
  })
  expect(markerCount).toBe(13)
  await page.screenshot({ path: testInfo.outputPath('energy-13-temperatures-fixture.png') })
  if (process.env.NADOC_ENERGY_VISUAL_REVIEW) {
    console.log('ENERGY_VISUAL_READY', testInfo.outputPath('energy-metrics.png'))
    await page.waitForTimeout(45000)
  }
  expect(errors).toEqual([])
})
