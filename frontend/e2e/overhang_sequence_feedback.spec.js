import { test, expect } from '@playwright/test'
import path from 'node:path'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
const fixture = path.resolve('../workspace/VoltronCoreArmV2.nadoc')
const hash = async () => createHash('sha256').update(await readFile(fixture)).digest('hex')
test.skip(!existsSync(fixture), 'Requires local VoltronCoreArmV2 diagnostic fixture')
test.use({ launchOptions: { args: ['--enable-webgl', '--ignore-gpu-blocklist', '--use-angle=gl'] } })
let original
// Only disposable context storage and configured Playwright outputs are written.
// Save routes are blocked; session caching is disabled by the dedicated test server.
// Standard global teardown removes __e2e__ caches; the reporter removes screenshots.
test.beforeEach(async ({ page }) => {
  page.on('console', message => { if (message.text().startsWith('[operation')) console.log(message.text()) })
  await page.route('**/src/state/store.js', async route => {
    const response = await route.fetch()
    const body = (await response.text()).replace('timingLabel ?? `store-subscriber:${++_nextListener}`',
      'timingLabel ?? new Error().stack.split("\\n")[2]')
    await route.fulfill({ response, body })
  })
  original = await hash()
  await page.route('**/api/design/save**', route => route.fulfill({ status: 200,
    contentType: 'application/json', body: '{"identity_disposition":"confirmed"}' }))
  await page.goto('/?doc=__e2e__sequence-feedback')
  await page.waitForSelector('#canvas')
  await page.evaluate(async fixture => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(fixture)
    document.getElementById('welcome-screen')?.classList.add('hidden')
    await (await import('/src/perf/operation_timing.js')).whenOperationIdle()
  }, fixture)
  await page.waitForTimeout(2200)
})
test.afterEach(async () => { expect(await hash()).toBe(original) })
test('sequence spinner permits superseding edits and preserves the active spreadsheet draft', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  const id = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.overhangs.find(o => o.label === 'QD_OH1').id)
  if (await page.locator('#spreadsheet-panel').evaluate(el => el.getBoundingClientRect().height < 20)) await page.locator('#sheet-toggle').click()
  await page.locator('#spreadsheet-panel').evaluate(el => { el.style.display = ''; el.style.height = '320px' })
  const input = page.locator(`#spreadsheet-tbody input[data-overhang-sequence="${id}"]`)
  console.log('SEQUENCE_INPUT_VIEW', await input.evaluate(el => { const rows = []; for (let p = el; p; p = p.parentElement) rows.push({ tag: p.tagName, id: p.id, display: getComputedStyle(p).display, visibility: getComputedStyle(p).visibility, rect: [p.getBoundingClientRect().width, p.getBoundingClientRect().height] }); return rows }))
  await input.scrollIntoViewIfNeeded()
  await expect(input).toBeVisible()
  let release, held = false
  const gate = new Promise(resolve => { release = resolve })
  const writes = []
  await page.route(`**/api/design/overhang/${id}`, async route => {
    writes.push(route.request().postDataJSON().sequence)
    const response = await route.fetch()
    if (writes.length === 1) { held = true; await gate }
    await route.fulfill({ response })
  })
  await input.fill('A'.repeat(10)); await input.press('Enter')
  await expect(page.locator('#overhang-sequence-activity')).toBeVisible()
  await expect.poll(() => held).toBe(true)
  await input.fill('A'.repeat(9)); await input.press('Enter')
  await input.fill('A'.repeat(8)); await input.press('Enter')
  await input.fill('A'.repeat(7)) // unfinished draft must survive both server replies
  const review = testInfo.outputPath('sequence-spinner.png')
  await page.screenshot({ path: review })
  console.log('SEQUENCE_REVIEW_IMAGE', review)
  release()
  await expect.poll(() => page.evaluate(id => window.__nadocTest.store.getState().currentDesign.overhangs.find(o => o.id === id).sequence.length, id)).toBe(8)
  await expect(page.locator('#overhang-sequence-activity')).toBeHidden({ timeout: 15000 })
  expect(writes).toEqual(['A'.repeat(10), 'A'.repeat(8)])
  await expect(input).toBeFocused(); await expect(input).toHaveValue('A'.repeat(7))
  await input.press('Enter')
  await expect.poll(() => page.evaluate(id => window.__nadocTest.store.getState().currentDesign.overhangs.find(o => o.id === id).sequence.length, id)).toBe(7)
  await expect(page.locator('#overhang-sequence-activity')).toBeHidden({ timeout: 15000 })
  // Natural completion timings, with no delayed routes and including the final paint.
  await page.unroute(`**/api/design/overhang/${id}`)
  // Frame the edited overhang outside the measurement. The API-only fixture
  // load otherwise leaves the camera inside the model after row selection.
  const camera = await page.evaluate(id => {
    const app = window.__nadocTest, state = app.store.getState()
    const domain = state.currentDesign.strands.flatMap(s => s.domains).find(d => d.overhang_id === id)
    const root = state.currentGeometry.find(n => n.helix_id === domain.helix_id && n.bp_index === domain.start_bp && n.direction === domain.direction)
    const [x, y, z] = root.backbone_position
    const pose = { position: [x + 18, y - 25, z + 4], target: [x, y, z], up: [0, 0, 1], fov: 35 }
    app.applyCameraPoseForTest(pose)
    return pose
  }, id)
  console.log('SEQUENCE_REVIEW_CAMERA', JSON.stringify(camera))
  await page.waitForTimeout(1000)
  const times = await page.evaluate(async id => {
    const api = await import('/src/api/client.js')
    const { sequenceActivity } = await import('/src/ui/sequence_activity.js')
    window.__nadocOperationTraceAll = true
    const times = []
    for (const [length, base] of [[10, 'A'], [9, 'A'], [8, 'A'], [8, 'T']]) {
      const start = performance.now()
      await api.patchOverhang(id, { sequence: base.repeat(length) })
      times.push({ ms: performance.now() - start, pending: sequenceActivity.pending })
    }
    return times
  }, id)
  console.log('SEQUENCE_COMPLETION', JSON.stringify(times))
  expect(times.every(t => t.pending === 0)).toBe(true)
  const finalReview = testInfo.outputPath('sequence-final.png')
  await page.screenshot({ path: finalReview })
  console.log('SEQUENCE_FINAL_IMAGE', finalReview)
  await page.waitForTimeout(60000) // review hold outside timing, standard cleanup owns image
})
