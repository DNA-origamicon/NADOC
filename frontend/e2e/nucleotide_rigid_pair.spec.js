import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { randomUUID } from 'node:crypto'

for (const fixturePath of ['../../workspace/2hb_1xT.nadoc', './fixtures/nucleotide_partial_owner.nadoc']) {
const fixture = JSON.parse(readFileSync(fileURLToPath(new URL(fixturePath, import.meta.url)), 'utf8'))
fixture.id = randomUUID()
fixture.metadata = { ...fixture.metadata, name: '__e2e__nucleotide-locality' }
delete fixture.metadata.identity_last_known_path
const FIXTURE = JSON.stringify(fixture)

test(`${fixturePath} nucleotide drag preserves its neighbors and placement owners`, async ({ page }) => {
  test.setTimeout(60_000)
  await page.goto('/?doc=e2e-nucleotide-rigid-pair')
  await page.waitForSelector('#canvas')
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, FIXTURE)
  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest.getBackboneBeadScreenPositions(400).length)).toBeGreaterThan(0)

  await page.locator('#canvas').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('F4')
  await page.keyboard.press('f')
  await page.waitForTimeout(400)
  // Q/E is the current selection-level shortcut (Tab now changes focus).
  for (let i = 0; i < 7; i++) {
    if (await page.evaluate(() => window.__nadocTest.getSelectionLevel()) === 'base') break
    await page.keyboard.press('e')
  }
  expect(await page.evaluate(() => window.__nadocTest.getSelectionLevel())).toBe('base')

  const canvas = await page.locator('#canvas').boundingBox()
  const candidates = await page.evaluate(() => window.__nadocTest.getBackboneBeadScreenPositions(400))
  const bead = candidates.find(p =>
    p.x > canvas.x + 80 && p.x < canvas.x + canvas.width - 320 &&
    p.y > canvas.y + 80 && p.y < canvas.y + canvas.height - 80)
  expect(bead, 'fixture must expose a pickable standard nucleotide').toBeTruthy()
  await page.mouse.click(bead.x, bead.y)
  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest.getSelectedBaseKeys().length)).toBe(1)

  const before = await page.evaluate(() => window.__nadocTest.getSelectedResidueArrangement())
  expect(before, 'selected nucleotide has a bead and slab').toBeTruthy()
  const allBefore = await page.evaluate(() => window.__nadocTest.getResidueArrangements())
  const posesBefore = await page.evaluate(async () =>
    (await import('/src/state/store.js')).store.getState().currentDesign.nucleotide_transforms.length)
  const ownersBefore = await page.evaluate(async () =>
    (await import('/src/state/store.js')).store.getState().currentDesign.cluster_transforms)
  const resizeRequests = []
  page.on('request', request => {
    if (request.url().includes('/design/strand-end-resize')) resizeRequests.push(request.url())
  })

  await page.keyboard.press('m')
  await expect(page.locator('#move-rotate-panel')).toBeVisible()
  const gizmo = await page.evaluate(() => window.__nadocTest.getNucleotideTransformScreenState())
  expect(gizmo.active).toBe(true)
  expect(gizmo.mode).toBe('translate')
  expect(await page.evaluate(async () => (await import('/src/state/store.js')).store.getState().nucleotideTransformActive)).toBe(true)
  const activated = await page.evaluate(() => window.__nadocTest.getSelectedResidueArrangement())
  expect(activated, JSON.stringify({ before, activated, gizmo })).toEqual(before)

  // The center handle translates in the view plane. Use a real TransformControls drag.
  await page.mouse.move(gizmo.screenPivot.x, gizmo.screenPivot.y)
  await page.mouse.down()
  await page.mouse.move(gizmo.screenPivot.x + 90, gizmo.screenPivot.y - 45, { steps: 12 })
  await page.mouse.up()
  await page.waitForTimeout(150)

  const during = await page.evaluate(() => window.__nadocTest.getSelectedResidueArrangement())
  expect(resizeRequests, 'Move must not invoke strand-end resize').toEqual([])
  expect(during.key).toBe(before.key)
  expect(during.bead).not.toEqual(before.bead)
  expect(during.distance).toBeCloseTo(before.distance, 5)
  for (let i = 0; i < 3; i++) expect(during.offset[i], JSON.stringify({ before, activated, during, gizmo })).toBeCloseTo(before.offset[i], 4)

  const saved = page.waitForResponse(response =>
    response.request().method() === 'PUT' && response.url().endsWith('/design/nucleotide-transforms'))
  await page.keyboard.press('m')
  expect((await saved).ok()).toBe(true)
  await expect.poll(() => page.evaluate(async () =>
    (await import('/src/state/store.js')).store.getState().currentDesign.nucleotide_transforms.length)).toBe(posesBefore + 1)
  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest.getNucleotideTransformScreenState().active)).toBe(false)
  const after = await page.evaluate(() => window.__nadocTest.getSelectedResidueArrangement())
  const allAfter = await page.evaluate(() => window.__nadocTest.getResidueArrangements())
  expect(await page.evaluate(async () =>
    (await import('/src/state/store.js')).store.getState().currentDesign.cluster_transforms)).toEqual(ownersBefore)
  expect(after.distance, JSON.stringify({ before, during, after })).toBeCloseTo(before.distance, 5)
  for (let i = 0; i < 3; i++) expect(after.offset[i]).toBeCloseTo(before.offset[i], 4)

  // Applying one pose must not swap the entire scene to a different display
  // projection. Every untouched bead/slab offset remains exactly registered.
  for (const [key, arrangement] of Object.entries(allBefore)) {
    if (key === before.key || key === `${before.key}:0`) continue
    expect(allAfter[key], `untouched residue disappeared: ${key}`).toBeTruthy()
    expect(allAfter[key].bead, `unselected nucleotide moved: ${key}`).toEqual(arrangement.bead)
    for (let i = 0; i < 3; i++) {
      expect(allAfter[key].offset[i], `global bead/slab shift at ${key}`).toBeCloseTo(arrangement.offset[i], 5)
    }
  }
})
}
