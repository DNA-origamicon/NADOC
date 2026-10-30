import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { gunzipSync } from 'node:zlib'

// All output uses testInfo.outputPath under the runner's scratch root. The imported
// part is prefixed for global-teardown; no candidate is imported, saved or exported.
const evidence = JSON.parse(gunzipSync(readFileSync(new URL('../src/ui/geometry_review_data/platform-attachment.json.gz', import.meta.url))))
const design = evidence.controls.clear.current_design
design.metadata.name = '__e2e__geometry-review'

test('Help geometry Review renders evidence, switches cases, and releases private scenes', async ({ page }, testInfo) => {
  test.setTimeout(180_000)
  page.setDefaultTimeout(15_000)
  await page.setViewportSize({ width: 1280, height: 960 })
  const errors = [], writes = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  await page.addInitScript(() => {
    window.__reviewContexts = new Set()
    const getContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function (type, ...args) {
      const context = getContext.call(this, type, ...args)
      if (context && type.startsWith('webgl')) window.__reviewContexts.add(context)
      return context
    }
  })
  await page.goto('/?doc=__e2e__geometry-review')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, JSON.stringify(design))
  const snapshot = () => page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const s = store.getState()
    return JSON.stringify({ design: s.currentDesign, geometry: s.currentGeometry, selection: s.selectedObject })
  })
  const before = await snapshot()
  await page.evaluate(() => window.__reviewContexts.clear())
  page.on('request', request => {
    if (request.url().includes('/api/') && !['GET', 'HEAD'].includes(request.method())) writes.push(request.url())
  })
  const open = async () => {
    await page.locator('#menu-bar > .menu-item').filter({ has: page.getByRole('button', { name: 'Help', exact: true }) }).hover()
    await page.locator('#menu-help-geometry-review').click()
  }
  await open()
  const modal = page.locator('#geometry-review')
  await expect(modal).toBeVisible()
  await expect(modal).toHaveAttribute('data-ready', 'true', { timeout: 60_000 })
  await expect(modal.locator('canvas')).toHaveCount(4)
  // Two frame turns allow the demand-rendered GPU completion callback to finish.
  const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await settle()
  await modal.screenshot({ path: testInfo.outputPath('geometry-review-overview.png') })
  const selects = modal.locator('.gr-bar select')
  for (let i = 0; i < 4; i++) await selects.nth(i).selectOption('full')
  await settle()
  await modal.screenshot({ path: testInfo.outputPath('geometry-review-full.png') })
  for (let i = 0; i < 4; i++) await selects.nth(i).selectOption('ballstick')
  await modal.getByRole('button', { name: 'Focus attachment collision' }).click()
  await settle()
  await modal.screenshot({ path: testInfo.outputPath('geometry-review-focus.png') })
  const marker = () => modal.locator('[data-ref="current-annotation"] circle').first()
    .evaluate(node => [node.getAttribute('cx'), node.getAttribute('cy')])
  const beforeOrbit = await marker()
  const box = await modal.locator('[data-ref="current-view"] canvas').boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + 70, box.y + box.height / 2 + 30, { steps: 4 })
  await page.mouse.up()
  await expect.poll(marker).not.toEqual(beforeOrbit)
  const overlayMarker = await modal.locator('[data-ref="difference-annotation"] circle').first()
    .evaluate(node => [Number(node.getAttribute('cx')), Number(node.getAttribute('cy'))])
  const currentMarker = (await marker()).map(Number)
  // Camera quaternion roundoff is far below a pixel, not a molecular tolerance.
  for (let i = 0; i < 2; i++) expect(overlayMarker[i]).toBeCloseTo(currentMarker[i], 8)
  await expect(modal.locator('[data-ref="features"] li')).toHaveCount(53)
  for (const value of ['clear', 'pierced']) {
    await modal.getByLabel('Review case', { exact: true }).selectOption(value)
    await expect(modal).toHaveAttribute('data-case', value)
    await expect(modal.locator('canvas')).toHaveCount(4)
    if (value === 'pierced') await expect(modal.locator('[data-ref="defect-list"]')).toContainText('PIERCING')
    else await expect(modal.locator('[data-ref="defect-list"] li')).toHaveCount(0)
    await expect(modal.locator('[data-ref="features"]')).not.toBeVisible()
  }
  await page.keyboard.press('Escape')
  await expect(modal).not.toBeVisible()
  await expect(modal.locator('canvas')).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => [...window.__reviewContexts].every(gl => gl.isContextLost()))).toBe(true)
  await open()
  await expect(modal).toHaveAttribute('data-ready', 'true')
  await modal.getByLabel('Review case', { exact: true }).selectOption('platform')
  await expect(modal).toHaveAttribute('data-case', 'platform')
  await modal.getByRole('button', { name: 'Close', exact: true }).click()
  await expect.poll(() => page.evaluate(() => [...window.__reviewContexts].every(gl => gl.isContextLost()))).toBe(true)
  expect(await snapshot()).toBe(before)
  expect(writes).toEqual([])
  expect(errors).toEqual([])
})
