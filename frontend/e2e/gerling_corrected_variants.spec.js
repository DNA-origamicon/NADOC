/** Opt-in scientific-file review. Private __e2e__ files and revision stores
 * are removed in afterEach (also on failure). Session cache is disabled by the
 * isolated config. Screenshots live only in Playwright's cleaned outputDir;
 * NADOC_GERLING_VARIANTS_VERIFICATION is the sole retained audit output.
 */
import { test, expect } from '@playwright/test'
import { readFile, writeFile, mkdir, rm } from 'node:fs/promises'
import path from 'node:path'

const folder = process.env.NADOC_GERLING_VARIANTS
const workspace = process.env.NADOC_WORKSPACE
const results = []
const variants = ['WITH_EXTRA_T', 'WITHOUT_EXTRA_T']

test.afterEach(async () => {
  if (!folder || !workspace) return
  for (const variant of variants) {
    const id = `__e2e__gerling_${variant.toLowerCase()}`
    await rm(path.join(workspace, `${id}.nadoc`), { force: true })
    await rm(path.join(workspace, '.nadoc-projects', id), { recursive: true, force: true })
  }
})

test.afterAll(async () => {
  if (process.env.NADOC_GERLING_VARIANTS_VERIFICATION) {
    await writeFile(process.env.NADOC_GERLING_VARIANTS_VERIFICATION,
      JSON.stringify({ passed: results.length === 2 && results.every(r => r.passed), variants: results }, null, 2))
  }
})

for (const variant of variants) test(`Gerling corrected ${variant} loads with its scaffold loop and terminal topology`, async ({ page, request, context }, info) => {
  test.skip(!folder || !workspace, 'Requires generated variants and a private Archive workspace.')
  test.setTimeout(120000)
  const full = variant === 'WITH_EXTRA_T'
  const id = `__e2e__gerling_${variant.toLowerCase()}`
  const design = JSON.parse(await readFile(path.join(folder,
    `Gerling2018_FigS1_p7560_LOOP_OVERHANGS_${variant}.nadoc`), 'utf8'))
  design.id = id
  design.metadata.name = id
  design.metadata.identity_last_known_path = `${id}.nadoc`
  await mkdir(workspace, { recursive: true })
  const file = path.join(workspace, `${id}.nadoc`)
  await writeFile(file, JSON.stringify(design))
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  const api = `${process.env.NADOC_E2E_API_BASE}/api`
  const created = await request.post(`${api}/documents`, { data: {} })
  expect(created.ok()).toBeTruthy()
  const { doc_id: doc } = await created.json()
  const headers = { 'X-NADOC-Doc': doc }
  try {
    const loaded = await request.post(`${api}/design/load`, { headers, data: { path: file }, timeout: 60000 })
    expect(loaded.ok(), await loaded.text()).toBeTruthy()
    await page.setViewportSize({ width: 1800, height: 1200 })
    await page.goto(`/?doc=${doc}`)
    await page.waitForFunction(() => !!window.__nadocTest)
    await page.evaluate(async () => {
      const client = await import('/src/api/client.js')
      await client.getDesign(); await client.getGeometry()
    })
    await expect.poll(() => page.evaluate(() => window.__nadocTest.store.getState().currentGeometry?.length),
      { timeout: 30000 }).toBe(full ? 16209 : 15054)
    const counts = await page.evaluate(() => {
      const s = window.__nadocTest.store.getState()
      const d = s.currentDesign, g = s.currentGeometry
      const loop = d.helices.find(h => h.label === '42')
      const loopBeads = g.filter(n => n.helix_id === loop.id)
      const loopJoins = d.forced_ligations.filter(f => f.three_prime_helix_id === loop.id || f.five_prime_helix_id === loop.id)
      return { helices: d.helices.length, strands: d.strands.length,
        labels: d.helices.map(h => h.label), geometry: g.length,
        overhangs: d.overhangs.length, overhangBeads: g.filter(n => n.overhang_id).length,
        extensions: d.extensions.length, extensionSequences: [...new Set(d.extensions.map(e => e.sequence))],
        loopBeads: loopBeads.length, loopUnpaired: loopBeads.every(n => n.is_unpaired && n.strand_type === 'scaffold'),
        loopJoins: loopJoins.length, loopOnOwnHelix: loopBeads.every(n => !n.overhang_id),
      }
    })
    expect(counts.helices).toBe(43)
    expect(counts.strands).toBe(214)
    expect(counts.labels).toEqual(Array.from({ length: 43 }, (_, i) => String(i)))
    expect(counts.overhangs).toBe(full ? 84 : 0)
    expect(counts.overhangBeads).toBe(full ? 813 : 0)
    expect(counts.extensions).toBe(full ? 342 : 0)
    expect(counts.extensionSequences).toEqual(full ? ['T'] : [])
    expect(counts.loopBeads).toBe(66)
    expect(counts.loopUnpaired && counts.loopOnOwnHelix).toBeTruthy()
    expect(counts.loopJoins).toBe(2)
    await page.evaluate(() => {
      document.getElementById('welcome-screen')?.classList.add('hidden')
      window.__nadocTest.applyCameraPoseForTest({ position: [112, 15, 28], target: [7, 13, 28], up: [0, 1, 0] })
    })
    await page.waitForTimeout(600)
    const threeCapture = info.outputPath('three-dimensional.png')
    await page.screenshot({ path: threeCapture })
    const editor = await context.newPage()
    editor.on('pageerror', e => errors.push(e.message))
    await editor.setViewportSize({ width: 1800, height: 1200 })
    await editor.goto(`/cadnano-editor.html?doc=${doc}`)
    await expect(editor.locator('#pathview-canvas')).toBeVisible()
    await editor.waitForFunction(async () => (await import('/src/state/store.js')).store.getState().currentDesign?.helices.length === 43)
    await editor.keyboard.press('f')
    await editor.waitForTimeout(800)
    const schematicCapture = info.outputPath('schematic.png')
    await editor.screenshot({ path: schematicCapture })
    console.log(`GERLING_VARIANT_CAPTURE=${threeCapture}`)
    console.log(`GERLING_VARIANT_CAPTURE=${schematicCapture}`)
    if (process.env.NADOC_GERLING_VARIANT_REVIEW_PAUSE) await editor.waitForTimeout(25000)
    expect(errors).toEqual([])
    results.push({ variant, passed: true, ...counts, cadnanoCanvasVisible: true, pageErrors: errors })
  } finally {
    await request.delete(`${api}/documents/${encodeURIComponent(doc)}`).catch(() => {})
  }
})
