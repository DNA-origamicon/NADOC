import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const FIXTURE = readFileSync(fileURLToPath(
  new URL('../../workspace/2hb_1xT.nadoc', import.meta.url)), 'utf8')

test('2hb_1xT nucleotide drag keeps its bead and slab rigidly arranged', async ({ page }) => {
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
  for (let i = 0; i < 5; i++) await page.keyboard.press('Tab')
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

  await page.keyboard.press('m')
  await expect(page.locator('#move-rotate-panel')).toBeVisible()
  const gizmo = await page.evaluate(() => window.__nadocTest.getNucleotideTransformScreenState())
  expect(gizmo.active).toBe(true)

  // The center handle translates in the view plane. Use a real TransformControls drag.
  await page.mouse.move(gizmo.screenPivot.x, gizmo.screenPivot.y)
  await page.mouse.down()
  await page.mouse.move(gizmo.screenPivot.x + 90, gizmo.screenPivot.y - 45, { steps: 12 })
  await page.mouse.up()
  await page.waitForTimeout(150)

  const during = await page.evaluate(() => window.__nadocTest.getSelectedResidueArrangement())
  expect(during.bead).not.toEqual(before.bead)
  expect(during.distance).toBeCloseTo(before.distance, 5)
  for (let i = 0; i < 3; i++) expect(during.offset[i]).toBeCloseTo(before.offset[i], 4)

  await page.keyboard.press('m')
  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest.getNucleotideTransformScreenState().active)).toBe(false)
  const after = await page.evaluate(() => window.__nadocTest.getSelectedResidueArrangement())
  const allAfter = await page.evaluate(() => window.__nadocTest.getResidueArrangements())
  expect(after.independentPose, JSON.stringify({ before, during, after })).toBe(true)
  expect(after.savedDisplayOffset, JSON.stringify({ before, during, after })).not.toBeNull()
  expect(after.distance, JSON.stringify({ before, during, after })).toBeCloseTo(before.distance, 5)
  for (let i = 0; i < 3; i++) expect(after.offset[i]).toBeCloseTo(before.offset[i], 4)

  // Applying one pose must not swap the entire scene to a different display
  // projection. Every untouched bead/slab offset remains exactly registered.
  for (const [key, arrangement] of Object.entries(allBefore)) {
    if (key === before.key) continue
    expect(allAfter[key], `untouched residue disappeared: ${key}`).toBeTruthy()
    for (let i = 0; i < 3; i++) {
      expect(allAfter[key].offset[i], `global bead/slab shift at ${key}`).toBeCloseTo(arrangement.offset[i], 5)
    }
  }
})
