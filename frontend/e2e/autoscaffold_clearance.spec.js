import { test, expect } from '@playwright/test'
import { existsSync } from 'node:fs'
import { rm } from 'node:fs/promises'
import { trackConsoleErrors } from './helpers/scene_harness.js'

const doc = '__e2e__autoscaffold-clearance'
// Public feature-recording commands; no save target and session cache disabled.
// Optional review capture is removed after review or timeout, including failure.
const capture = process.env.NADOC_REVIEW_SCREENSHOT

test.afterAll(async () => {
  if (capture) await rm(capture, { force: true })
})

test('autoscaffold skips crowded end sites in an extrude and Sweep', async ({ page, request }) => {
  test.setTimeout(90000)
  const errors = trackConsoleErrors(page)
  const headers = { 'X-NADOC-Doc': doc }
  const post = async (endpoint, data) => {
    const result = await request.post(`${process.env.NADOC_E2E_API_BASE}/api${endpoint}`, { headers, data })
    expect(result.ok(), await result.text()).toBe(true)
    return result.json()
  }
  const cells = [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2], [1, 4], [1, 5], [0, 5], [0, 4]]
  const source = await post('/design/bundle', { cells, length_bp: 56, lattice_type: 'HONEYCOMB', name: doc })
  await post('/design/sweep', {
    cells, points_nm: [[0, 0, 0], [0, 13.01427642891104, 18.408057500584952], [-25.977535346791882, 26.02855285782208, 36.816115001169905]],
    source_helix_id: source.design.helices.find(h => h.grid_pos[0] === 1 && h.grid_pos[1] === 2).id,
    source_end: 'end',
  })
  await page.setViewportSize({ width: 1800, height: 1000 })
  await page.goto(`/cadnano-editor.html?doc=${doc}`)
  const getDesign = () => page.evaluate(async () => (await import('/src/cadnano-editor/store.js')).editorStore.getState().design)
  await expect.poll(async () => (await getDesign())?.helices.length).toBe(20)
  await page.keyboard.press('1')
  await expect(page.locator('#autoscaffold-modal')).toBeVisible()
  const response = page.waitForResponse(r => r.url().endsWith('/design/auto-scaffold-seamed') && r.request().method() === 'POST')
  await page.locator('#as-run').click()
  const routed = await response
  expect(routed.ok(), await routed.text()).toBe(true)
  await expect.poll(async () => (await getDesign())?.strands.filter(s => s.strand_type === 'scaffold').length).toBe(1)
  const design = await getDesign()
  expect(design.feature_log.map(f => f.op_kind)).toEqual(['bundle-create', 'sweep', 'auto-scaffold-seamed'])
  const near = design.crossovers.filter(x => x.process_id === 'create_near_ends')
  expect(near.some(x => x.half_a.index === -12)).toBe(true)
  expect(near.every(x => x.half_a.index <= -3)).toBe(true)
  await page.keyboard.press('f')
  if (capture) {
    const box = await page.locator('#pathview-canvas').boundingBox()
    await page.mouse.move(box.x + 500, box.y + 200)
    await page.mouse.down({ button: 'middle' })
    await page.mouse.move(box.x + 680, box.y + 200, { steps: 5 })
    await page.mouse.up({ button: 'middle' })
    await page.screenshot({ path: capture })
    // Give the reviewer time to inspect; removing the image completes review.
    await expect.poll(() => existsSync(capture), { timeout: 45000 }).toBe(false)
  }
  await page.keyboard.press('Control+z')
  await expect.poll(async () => (await getDesign())?.crossovers.length).toBe(0)
  await page.keyboard.press('Control+Shift+z')
  await expect.poll(async () => (await getDesign())?.crossovers.length).toBe(design.crossovers.length)
  await page.reload()
  await expect.poll(async () => (await getDesign())?.crossovers.length).toBe(design.crossovers.length)
  expect(errors).toEqual([])
})
