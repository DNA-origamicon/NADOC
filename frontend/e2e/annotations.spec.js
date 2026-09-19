import { test, expect } from '@playwright/test'
import { copyFileSync, readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { beadCandidates, loadScaffoldedPart, trackConsoleErrors } from './helpers/scene_harness.js'

// Persistent artifacts: the `__e2e__` part is removed by global-teardown.js; annotation state lives
// only in this browser context's localStorage; screenshots go to Playwright's output dir (cleaned
// by the cleanup reporter) and, when NADOC_E2E_SHOT is set, one copy to that path.
test('annotation tab: target, text/icon gating, highlight, manual drag', async ({ page }, testInfo) => {
  test.setTimeout(90_000)
  await page.setViewportSize({ width: 1800, height: 1000 })
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__annotations', name: 'annotations' })
  await page.keyboard.press('f')

  await page.locator('#right-tab-strip [data-tab="annotations"]').click()
  const column = page.locator('#right-panel .sidebar-column[data-panel-type="annotations"]')
  await expect(column).toBeVisible()

  // Select a strand in the viewport (default click level = strand).
  const [bead] = await beadCandidates(page)
  await page.mouse.click(bead.x, bead.y)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getCanonicalSelection().items.length)).toBeGreaterThan(0)

  await column.locator('.anno-add').click()
  const card = column.locator('.anno-card').first()
  await card.locator('[data-field="useSelection"]').click()
  await expect(card.locator('.anno-target')).toContainText('Strand')

  // No text / icon yet → nothing drawn, but the highlight must not exist either.
  const callout = page.locator('.nadoc-anno:not([hidden])')
  await expect(callout).toHaveCount(0)
  expect(await page.evaluate(() => window.__nadocTest.scene.getObjectByName('Annotation highlights').children.length)).toBe(0)

  await card.locator('[data-field="text"]').fill('Check this strand')
  await expect(callout).toHaveCount(1)
  await expect(callout).toContainText('Check this strand')
  await expect.poll(() => page.evaluate(() => window.__nadocTest.scene.getObjectByName('Annotation highlights').children.length)).toBe(1)

  await card.locator('[data-field="color"]').fill('#ff4d4d')
  await expect(callout).toHaveCSS('--anno-color', '#ff4d4d')

  await card.locator('[data-field="icon"]').click()
  await column.locator('.anno-icon-pop [title="Green check"]').click()
  await expect(callout.locator('.nadoc-anno__icon svg')).toBeVisible()

  // Manual: the box keeps its screen position while the camera moves.
  await card.locator('[data-field="manual"]').check()
  const grip = callout.locator('.nadoc-anno__grip')
  await expect(grip).toBeVisible()
  const before = await callout.boundingBox()
  const g = await grip.boundingBox()
  await page.mouse.move(g.x + 8, g.y + 8)
  await page.mouse.down()
  const area = await page.locator('#canvas-area').boundingBox()
  const dx = before.x - 150 < area.x + 24 ? 120 : -150   // stay clear of the viewport-margin clamp
  await page.mouse.move(g.x + 8 + dx, g.y + 8 + 140, { steps: 6 })
  await page.mouse.up()
  const pinned = await callout.boundingBox()
  expect(Math.abs(pinned.x - (before.x + dx))).toBeLessThan(3)
  expect(Math.abs(pinned.y - (before.y + 140))).toBeLessThan(3)
  const canvas = await page.locator('#canvas').boundingBox()
  await page.mouse.move(canvas.x + canvas.width / 2, canvas.y + canvas.height / 2)
  for (let i = 0; i < 4; i++) await page.mouse.wheel(0, 120)
  await page.waitForTimeout(400)
  const after = await callout.boundingBox()
  expect(Math.abs(after.x - pinned.x)).toBeLessThan(2)
  expect(Math.abs(after.y - pinned.y)).toBeLessThan(2)

  const shot = testInfo.outputPath('annotations.png')
  await page.screenshot({ path: shot })
  if (process.env.NADOC_E2E_SHOT) copyFileSync(shot, process.env.NADOC_E2E_SHOT)

  // Hiding via the eye toggle removes callout and highlight.
  await card.locator('[data-field="visible"]').click()
  await expect(callout).toHaveCount(0)
  await card.locator('[data-field="delete"]').click()
  await expect(column.locator('.anno-card')).toHaveCount(0)
  expect(errors, errors.join('\n')).toEqual([])
})

const PDB = [
  'ATOM      1  N   ALA     1       0.000   0.000   0.000  1.00  0.00      PROA',
  'ATOM      2  CA  ALA     1       1.500   0.000   0.000  1.00  0.00      PROA',
  'ATOM      3  C   ALA     1       2.000   1.400   0.000  1.00  0.00      PROA',
  'ATOM      4  O   ALA     1       1.300   2.400   0.000  1.00  0.00      PROA',
  'ATOM      5  CB  ALA     1       2.000  -1.000   1.000  1.00  0.00      PROA',
  'ATOM      6  N   CYS     2       3.300   1.500   0.000  1.00  0.00      PROA',
  'ATOM      7  CA  CYS     2       4.100   2.700   0.000  1.00  0.00      PROA',
  'ATOM      8  CB  CYS     2       5.600   2.400   0.000  1.00  0.00      PROA',
  'ATOM      9  SG  CYS     2       6.700   3.900   0.000  1.00  0.00      PROA',
  'END',
].join('\n')

// Persistent artifacts: the `__e2e__` part (with its gold nanosphere + protein attachment) is removed by
// global-teardown.js; the protein asset library is in-memory on the throwaway e2e backend.
test('annotations: protein + nanoparticle targets, auto placement off the design, icon popup on screen', async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 1400, height: 900 })
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__annotations-targets', name: 'annotations-targets' })
  await page.keyboard.press('f')

  const goldId = await page.evaluate(async () => {
    await window.__nadocTest.nanoparticles.create(10)
    const d = window.__nadocTest.store.getState().currentDesign
    return d.nanoparticles.at(-1).id
  })
  await page.evaluate(pdb => window.__nadocTest.importProteinForTest(pdb), PDB)
  const proteinId = await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.protein_attachments.at(-1).id)

  // Annotations alone in the far-right column, so the icon popup has the screen edge to run into.
  await page.locator('#right-tab-strip [data-tab="annotations"]').click()
  const props = page.locator('#right-panel .sidebar-column[data-panel-type="properties"] .sidebar-close')
  if (await props.count()) await props.click()
  const column = page.locator('#right-panel .sidebar-column[data-panel-type="annotations"]')
  await expect(column).toBeVisible()

  // Nanoparticle target.
  await page.evaluate(id => window.__nadocTest.nanoparticles.select(id), goldId)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getCanonicalSelection().items[0]?.kind)).toBe('nanoparticle')
  await column.locator('.anno-add').click()
  const gold = column.locator('.anno-card').nth(0)
  await gold.locator('[data-field="text"]').fill('Gold')
  await gold.locator('[data-field="color"]').fill('#ffd700')
  await gold.locator('[data-field="useSelection"]').click()
  await expect(gold.locator('.anno-target')).toContainText('Gold nanosphere')

  // Protein target.
  await page.evaluate(id => window.__nadocTest.selectProteinForTest(id), proteinId)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getCanonicalSelection().items[0]?.kind)).toBe('protein')
  await column.locator('.anno-add').click()
  const prot = column.locator('.anno-card').nth(1)
  await prot.locator('[data-field="text"]').fill('Protein')
  await prot.locator('[data-field="color"]').fill('#39c5cf')
  await prot.locator('[data-field="useSelection"]').click()
  await expect(prot.locator('.anno-target')).toContainText('Protein')

  const state = () => page.evaluate(() => {
    const halos = []
    window.__nadocTest.scene.getObjectByName('Annotation highlights').traverse(o => { if (o.isSprite) halos.push({ name: o.name, visible: o.visible, scale: o.scale.x }) })
    return halos
  })
  await expect.poll(async () => (await state()).filter(h => h.visible).length).toBe(2)
  for (const h of await state()) expect(h.scale).toBeGreaterThan(1)
  const callouts = page.locator('.nadoc-anno:not([hidden])')
  await expect(callouts).toHaveCount(2)
  for (const id of ['Gold', 'Protein']) {
    await expect(callouts.filter({ hasText: id })).toBeVisible()
    await expect(page.locator('.nadoc-anno-leaders g').nth(id === 'Gold' ? 0 : 1)).toBeVisible()
  }

  // Auto placement: neither box sits over a visible backbone bead (helix runs through the view).
  await page.waitForTimeout(500)
  const beads = await page.evaluate(() => window.__nadocTest.getBackboneBeadScreenPositions(400))
  const area = await page.locator('#canvas-area').boundingBox()
  for (const box of await callouts.evaluateAll(es => es.map(e => { const r = e.querySelector('.nadoc-anno__box').getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height } }))) {
    const under = beads.filter(b => b.x >= box.x && b.x <= box.x + box.w && b.y >= box.y && b.y <= box.y + box.h)
    expect(under.length, `callout at ${box.x},${box.y} covers ${under.length} beads`).toBe(0)
    expect(box.x).toBeGreaterThanOrEqual(area.x)
    expect(box.x + box.w).toBeLessThanOrEqual(area.x + area.width)
  }

  // Icon popup stays fully on screen even from the right-most column.
  await gold.locator('[data-field="icon"]').click()
  const pop = await column.locator('.anno-icon-pop').boundingBox()
  expect(pop.x).toBeGreaterThanOrEqual(0)
  expect(pop.x + pop.width).toBeLessThanOrEqual(1400)
  expect(pop.y + pop.height).toBeLessThanOrEqual(900)
  await column.locator('.anno-icon-pop [title="Warning"]').click()

  const shot = testInfo.outputPath('annotations-targets.png')
  await page.screenshot({ path: shot })
  if (process.env.NADOC_E2E_SHOT2) copyFileSync(shot, process.env.NADOC_E2E_SHOT2)
  expect(errors, errors.join('\n')).toEqual([])
})

const WORKSPACE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'workspace')
const savedFile = prefix => readdirSync(WORKSPACE).find(f => f.startsWith(prefix) && f.endsWith('.nadoc'))
const readSaved = prefix => { const f = savedFile(prefix); return f ? JSON.parse(readFileSync(path.join(WORKSPACE, f), 'utf8')) : null }

// Persistent artifacts: the `__e2e__annotations-file*.nadoc` autosave is removed by global-teardown.js
// (name prefix); this test only reads it.
test('annotations are written to the .nadoc file, the global toggle is saved, and reopening restores both', async ({ page }) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 1600, height: 900 })
  const errors = trackConsoleErrors(page)
  await loadScaffoldedPart(page, { doc: '__e2e__annotations-file', name: 'annotations-file' })
  await page.keyboard.press('f')
  await page.locator('#right-tab-strip [data-tab="annotations"]').click()
  const column = page.locator('#right-panel .sidebar-column[data-panel-type="annotations"]')
  const [bead] = await beadCandidates(page)
  await page.mouse.click(bead.x, bead.y)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getCanonicalSelection().items.length)).toBeGreaterThan(0)

  await column.locator('.anno-add').click()
  const card = column.locator('.anno-card').first()
  await card.locator('[data-field="text"]').fill('Saved in the file')
  await card.locator('[data-field="color"]').fill('#3fb950')
  await card.locator('[data-field="calloutType"]').selectOption('rounded')
  await card.locator('[data-field="useSelection"]').click()

  // Autosave writes the backend design to workspace/<name>.nadoc after an idle period.
  await expect.poll(() => readSaved('__e2e__annotations-file')?.annotations?.length, { timeout: 20_000 }).toBe(1)
  let file = readSaved('__e2e__annotations-file')
  expect(file.annotations[0]).toMatchObject({ text: 'Saved in the file', color: '#3fb950', callout_type: 'rounded', visible: true })
  expect(file.annotations[0].refs[0].kind).toBe('strand')
  expect(file.annotations_enabled).toBe(true)

  // Global toggle: hides everything in the viewport, keeps the entry, and is saved.
  await column.locator('[data-field="enabled"]').uncheck()
  await expect(page.locator('.nadoc-anno-layer')).toBeHidden()
  await expect(column.locator('.anno-card')).toHaveCount(1)
  await expect.poll(() => readSaved('__e2e__annotations-file')?.annotations_enabled, { timeout: 20_000 }).toBe(false)
  expect(readSaved('__e2e__annotations-file').annotations).toHaveLength(1)

  // Reopen from the file text: first delete the entry from the live session, so only the file can bring it back.
  const fileText = readFileSync(path.join(WORKSPACE, savedFile('__e2e__annotations-file')), 'utf8')
  await page.evaluate(() => { for (const k of Object.keys(localStorage)) if (k.includes('annotations')) localStorage.removeItem(k) })
  await card.locator('[data-field="delete"]').click()
  await expect(column.locator('.anno-card')).toHaveCount(0)
  await page.evaluate(async text => { const api = await import('/src/api/client.js'); await api.importDesign(text) }, fileText)
  await expect(column.locator('.anno-card')).toHaveCount(1)
  await expect(column.locator('.anno-card [data-field="text"]')).toHaveValue('Saved in the file')
  await expect(column.locator('[data-field="enabled"]')).not.toBeChecked()
  await expect(page.locator('.nadoc-anno-layer:not([hidden]) .nadoc-anno:not([hidden])')).toHaveCount(0)
  await column.locator('[data-field="enabled"]').check()
  await expect(page.locator('.nadoc-anno-layer:not([hidden]) .nadoc-anno:not([hidden])')).toHaveCount(1)
  await expect(page.locator('.nadoc-anno-layer:not([hidden]) .nadoc-anno:not([hidden])')).toContainText('Saved in the file')
  expect(errors, errors.join('\n')).toEqual([])
})
