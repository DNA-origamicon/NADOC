/** Read-only view exercise: opens an existing example, never authors/saves a part.
 * Persistence inventory: optional temperature-scale-{3d,cadnano}.png screenshots in
 * NADOC_TEMPERATURE_SCREENSHOTS are retained review evidence; Playwright reports use configured cleanup,
 * server session cache disabled; test-port bridge key removed by global teardown.
 */
import { test, expect } from '@playwright/test'
import path from 'node:path'
import { trackConsoleErrors } from './helpers/scene_harness.js'
// Real geometry loading plus four GPU recolor/restoration passes on a sequenced origami.
// Optional read-only large local design; no copy/import snapshot is authored.
const temperatureSource = process.env.NADOC_TEMPERATURE_DESIGN
const expectedScaffolds = Number(process.env.NADOC_TEMPERATURE_EXPECT_SCAFFOLDS || 1)
// Numeric edits, dragging and reset add multiple real GPU redraws to each exercise.
test.setTimeout(180000)
async function exerciseBounds(page, colors) {
  const before = await colors()
  const low = page.locator('[data-temperature-low]'), high = page.locator('[data-temperature-high]')
  await low.fill('50'); await low.press('Tab')
  await high.fill('60'); await high.press('Tab')
  expect(await colors()).not.toEqual(before)
  await expect(low).toHaveValue('50')
  const handle = page.locator('[data-temperature-handle="lo"]')
  const rect = await handle.boundingBox(), track = await page.locator('[data-temperature-track]').boundingBox()
  await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2)
  await page.mouse.down(); await page.mouse.move(track.x + track.width * .25, rect.y + rect.height / 2)
  await page.mouse.up()
  expect(await low.inputValue()).not.toBe('50')
  await page.locator('[data-temperature-reset]').click()
  expect(Number(await high.inputValue())).toBeGreaterThan(Number(await low.inputValue()))
  await low.fill('20'); await low.press('Tab'); await high.fill('90'); await high.press('Tab')
  expect(await colors()).toEqual(before)
  await low.fill('50'); await low.press('Tab'); await high.fill('60'); await high.press('Tab')
  if (process.env.NADOC_TEMPERATURE_SCREENSHOTS) await page.screenshot({ path: path.join(process.env.NADOC_TEMPERATURE_SCREENSHOTS, `temperature-scale-${page.url().includes('cadnano') ? 'cadnano' : '3d'}.png`) })
}
test('temperature button colors a sequenced origami and cycles back to its original colors', async ({ page, request }) => {
  const errors = trackConsoleErrors(page)
  const doc = 'e2e-temperature-readonly'
  const source = temperatureSource || path.resolve(process.cwd(), '..', 'Examples', 'U6hb.nadoc')
  const api = process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8001'
  const loaded = await request.post(`${api}/api/design/load`, {
    headers: { 'X-NADOC-Doc': doc }, data: { path: source },
  })
  expect(loaded.ok()).toBe(true)
  // Explicit same-document handoff restores via GET; ordinary startup is welcome-only.
  await page.goto(`/?doc=${doc}&readiness=simulation`)
  await page.waitForFunction(() => window.__nadocTest?.getDesignRenderer()?.getBackboneEntries()?.length > 0, null, { timeout: temperatureSource ? 60000 : 20000 }).catch(async error => {
    throw new Error(`${error.message}\nBrowser errors: ${errors.join('\n')}\nPrompt: ${await page.evaluate(() => document.querySelector('#prompt-box')?.textContent ?? '')}\nURL: ${page.url()}`)
  })
  const button = page.locator('[data-vt="stapleTemperature"]')
  await expect(button).toBeVisible()
  const census = () => page.evaluate(() => window.__nadocTest.nativeBackboneColorCensus().active.sort((a, b) => a - b))
  const before = await census()
  await button.click()
  await expect(button).toHaveAttribute('data-mode', 'domain')
  await expect(page.locator('[data-temperature-title]')).toHaveText('Domain Tm (°C)')
  await expect(page.locator('[data-temperature-status]')).not.toContainText('No estimates')
  expect(await census()).not.toEqual(before)
  await exerciseBounds(page, census)
  await button.click()
  await expect(button).toHaveAttribute('data-mode', 'total')
  await expect(page.locator('[data-temperature-low]')).toHaveValue('50')
  await expect(page.locator('[data-temperature-title]')).toContainText('Tfold')
  const coverage = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const { estimateStapleTemperatures } = await import('/src/scene/staple_temperature.js')
    const { temperatureColor } = await import('/src/scene/staple_temperature_colors.js')
    const estimates = estimateStapleTemperatures(store.getState().currentDesign)
    const owners = new Set(); let mismatches = 0
    for (const entry of window.__nadocTest.getDesignRenderer().getBackboneEntries()) {
      const estimate = estimates.get(entry.nuc.strand_id)
      if (estimate?.total == null) continue
      owners.add(estimate.scaffoldId)
      const color = entry.instMesh.material.color.clone()
      entry.instMesh.getColorAt(entry.id, color)
      if (color.getHex() !== temperatureColor(estimate.total, { lo: Number(document.querySelector('[data-temperature-low]').value), hi: Number(document.querySelector('[data-temperature-high]').value) })) mismatches++
    }
    return { scaffolds: owners.size, mismatches }
  })
  expect(coverage).toEqual({ scaffolds: expectedScaffolds, mismatches: 0 })
  await expect(page.locator('[data-temperature-status]')).not.toContainText('No estimates')
  expect(await census()).not.toEqual(before)
  await button.click()
  await expect(page.locator('#staple-temperature-legend')).toBeHidden()
  expect(await census()).toEqual(before)
  await button.click()
  await page.locator('[data-vt="lengthHeatmap"]').click()
  await expect(button).toHaveAttribute('data-mode', 'off')
  expect(errors.filter(e => !/favicon|WebSocket/.test(e))).toEqual([])
})

test('cadnano temperature modes recolor the path canvas and restore it exactly', async ({ page, request }) => {
  const errors = trackConsoleErrors(page)
  const doc = 'e2e-temperature-cadnano-readonly'
  const api = process.env.NADOC_E2E_API_BASE || 'http://127.0.0.1:8001'
  expect((await request.post(`${api}/api/design/load`, {
    headers: { 'X-NADOC-Doc': doc }, data: { path: temperatureSource || path.resolve(process.cwd(), '..', 'Examples', 'U6hb.nadoc') },
  })).ok()).toBe(true)
  await page.goto(`/cadnano-editor.html?doc=${doc}`)
  await page.waitForFunction(async () => (await import('/src/cadnano-editor/store.js')).editorStore.getState().design?.strands?.length > 0)
  const button = page.locator('[data-vt="stapleTemperature"]')
  await expect(button).toBeVisible()
  const canvasHash = () => page.evaluate(async () => {
    // Store/toolbar updates precede the scheduled canvas draw and initial fit.
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    const canvas = document.getElementById('pathview-canvas')
    const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
    let hash = 2166136261
    for (const value of pixels) hash = Math.imul(hash ^ value, 16777619) >>> 0
    return hash
  })
  const original = await canvasHash()
  await button.click()
  await expect(button).toHaveAttribute('data-mode', 'domain')
  await expect(page.locator('[data-temperature-status]')).toContainText('°C')
  await exerciseBounds(page, canvasHash)
  const domains = await canvasHash()
  expect(domains).not.toBe(original)
  await button.click()
  await expect(button).toHaveAttribute('data-mode', 'total')
  await expect(page.locator('[data-temperature-low]')).toHaveValue('50')
  await expect(page.locator('[data-temperature-title]')).toContainText('Tfold')
  const ownerCount = await page.evaluate(async () => {
    const { editorStore } = await import('/src/cadnano-editor/store.js')
    const { estimateStapleTemperatures } = await import('/src/scene/staple_temperature.js')
    const estimates = estimateStapleTemperatures(editorStore.getState().design)
    return new Set([...estimates.values()].filter(e => e.total != null).map(e => e.scaffoldId)).size
  })
  expect(ownerCount).toBe(expectedScaffolds)
  const total = await canvasHash()
  expect(total).not.toBe(domains)
  expect(total).not.toBe(original)
  await button.click()
  await expect(page.locator('#staple-temperature-legend')).toBeHidden()
  expect(await canvasHash()).toBe(original)
  await button.click()
  await page.locator('[data-vt="lengthHeatmap"]').click()
  await expect(button).toHaveAttribute('data-mode', 'off')
  await expect(page.locator('#staple-temperature-legend')).toBeHidden()
  await page.locator('[data-vt="lengthHeatmap"]').click()
  expect(await canvasHash()).toBe(original)
  expect(errors.filter(e => !/favicon|WebSocket/.test(e))).toEqual([])
})
