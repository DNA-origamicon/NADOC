/** Scientific artifact review, opt-in. All test writes are in an isolated
 * NADOC_WORKSPACE on Archive. The private __e2e__ design/revisions are removed
 * in afterAll even on failure; session cache is disabled by the smoke config.
 * Screenshots use Playwright outputPath and its cleanup reporter. The only
 * retained external output is the compact verification JSON requested by env.
 * No original design is imported into or saved over the user's active document.
 */
import { test, expect } from '@playwright/test'
import { readFile, writeFile, mkdir, rm } from 'node:fs/promises'
import path from 'node:path'

const source = process.env.NADOC_GERLING_RECONSTRUCTED
const workspace = process.env.NADOC_WORKSPACE
const project = '__e2e__gerling_reconstruction_review'
const file = `${project}.nadoc`
test.afterAll(async () => {
  if (!source || !workspace) return
  await rm(path.join(workspace, file), { force: true })
  await rm(path.join(workspace, '.nadoc-projects', project), { recursive: true, force: true })
})

test('complete Gerling reconstruction loads in NADOC and both maps share staple selection', async ({ page, request, context }, info) => {
  test.skip(!source || !workspace || !process.env.NADOC_GERLING_REVIEW_HTML, 'Requires generated scientific artifacts and isolated workspace.')
  test.setTimeout(150000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  const design = JSON.parse(await readFile(source, 'utf8'))
  design.id = project
  design.metadata.name = project
  design.metadata.identity_last_known_path = file
  await mkdir(workspace, { recursive: true })
  await writeFile(path.join(workspace, file), JSON.stringify(design))
  const api = `${process.env.NADOC_E2E_API_BASE}/api`
  const created = await request.post(`${api}/documents`, { data: {} })
  expect(created.ok()).toBeTruthy()
  const { doc_id: doc } = await created.json()
  const headers = { 'X-NADOC-Doc': doc }
  try {
    const loaded = await request.post(`${api}/design/load`, { headers, data: { path: path.join(workspace, file) }, timeout: 60000 })
    expect(loaded.ok(), await loaded.text()).toBeTruthy()
    await page.setViewportSize({ width: 1800, height: 1200 })
    await page.goto(`/?doc=${doc}`)
    await page.waitForFunction(() => !!window.__nadocTest)
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      await api.getDesign(); await api.getGeometry()
    })
    await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentDesign?.strands.length), { timeout: 30000 }).toBe(214)
    const counts = await page.evaluate(() => {
      const s = window.__nadocTest.store.getState()
      return { helices: s.currentDesign.helices.length, strands: s.currentDesign.strands.length,
        labels: s.currentDesign.helices.map(h => h.label), geometry: s.currentGeometry.length }
    })
    expect(counts.helices).toBe(42)
    expect(counts.labels).toEqual(Array.from({ length: 42 }, (_, i) => String(i)))
    expect(counts.geometry).toBeGreaterThan(15000)
    const editor = await context.newPage()
    editor.on('pageerror', e => errors.push(e.message))
    await editor.setViewportSize({ width: 1800, height: 1200 })
    await editor.goto(`/cadnano-editor.html?doc=${doc}`)
    await expect(editor.locator('#pathview-canvas')).toBeVisible()
    await editor.waitForFunction(async () => (await import('/src/state/store.js')).store.getState().currentDesign?.strands.length === 214)
    await editor.keyboard.press('f')
    await editor.waitForTimeout(800)
    const capture = info.outputPath('nadoc-schematic.png')
    await editor.screenshot({ path: capture })
    console.log(`GERLING_REVIEW_CAPTURE=${capture}`)
    if (process.env.NADOC_GERLING_REVIEW_PAUSE) await editor.waitForTimeout(20000)
    const review = await context.newPage()
    review.on('pageerror', e => errors.push(e.message))
    await review.setContent(await readFile(process.env.NADOC_GERLING_REVIEW_HTML, 'utf8'))
    expect(errors).toEqual([])
    await expect(review.locator('#pick option')).toHaveCount(214)
    await expect(review.locator('g.staple')).toHaveCount(426)
    await review.locator('#pick').selectOption('46')
    await expect(review.locator('g.chosen')).toHaveCount(2)
    await expect(review.locator('#detail')).toContainText('40 → 41')
    // A horizontal SVG line has a zero-height DOM box despite its visible
    // stroke. Click the actual painted stroke at its browser coordinates.
    const segment = review.locator('g[data-id="142"]').first().locator('line').first()
    await segment.evaluate(el => el.scrollIntoView({ block: 'center' }))
    const bounds = await segment.boundingBox()
    expect(bounds).toBeTruthy()
    await review.mouse.click(bounds.x + bounds.width / 2, bounds.y)
    await expect(review.locator('#detail')).toContainText('41 → 40 → 31 → 30')
    await expect(review.locator('#detail')).not.toContainText('h_XY_')
    await review.locator('#reset').click()
    await expect(review.locator('g.chosen')).toHaveCount(0)
    expect(errors).toEqual([])
    if (process.env.NADOC_GERLING_VERIFICATION) await writeFile(process.env.NADOC_GERLING_VERIFICATION,
      JSON.stringify({ passed: true, ...counts, cadnanoCanvasVisible: true, linkedSelectionPassed: true, pageErrors: errors }, null, 2))
  } finally {
    await request.delete(`${api}/documents/${encodeURIComponent(doc)}`).catch(() => {})
  }
})
