/**
 * Examples menu tests — File > Examples submenu
 *
 * Verifies that each of the four pre-built M13 example designs can be loaded
 * via the File > Examples submenu and that the resulting design has a scaffold
 * strand of exactly 7249 nucleotides.
 */

import { test, expect } from '@playwright/test'

const TARGET_SCAFFOLD = 7249

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Open File > Examples and click an example item by its button ID. */
async function loadExample(page, exampleBtnId) {
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  // Hover the nested Examples item to reveal its submenu
  await page.locator('#menu-file-examples-btn').hover()
  await page.locator(`#${exampleBtnId}`).click()
}

/** Wait for the scene to load (mode indicator changes away from the loading state). */
async function waitForDesign(page) {
  await expect(page.locator('#splash-screen')).toBeHidden({ timeout: 15_000 })
}

/** Return scaffold length via the /api/design/atomistic-scaffold-info endpoint
 *  (or compute it from the active design via GET /api/design). */
async function fetchScaffoldLength(page) {
  const response = await page.request.get('/api/design')
  expect(response.ok()).toBeTruthy()
  const data = await response.json()
  const strands = data?.design?.strands ?? []
  let total = 0
  for (const strand of strands) {
    if (strand.strand_type !== 'scaffold') continue
    for (const domain of strand.domains ?? []) {
      total += Math.abs(domain.end_bp - domain.start_bp) + 1
    }
  }
  return total
}

// ── Tests ────────────────────────────────────────────────────────────────────

test.describe('File > Examples menu', () => {

  test('Examples submenu is visible on File hover', async ({ page }) => {
    await page.goto('/')
    const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
    await fileMenu.hover()
    // The nested Examples trigger button should appear
    await expect(page.locator('#menu-file-examples-btn')).toBeVisible()
  })

  test('Examples submenu contains all four items', async ({ page }) => {
    await page.goto('/')
    const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
    await fileMenu.hover()
    await page.locator('#menu-file-examples-btn').hover()
    await expect(page.locator('#menu-example-6hb')).toBeVisible()
    await expect(page.locator('#menu-example-18hb')).toBeVisible()
    await expect(page.locator('#menu-example-2x20sq')).toBeVisible()
    await expect(page.locator('#menu-example-3x6sq')).toBeVisible()
  })

  test('/api/design/examples lists all four examples as available', async ({ page }) => {
    await page.goto('/')
    const response = await page.request.get('/api/design/examples')
    expect(response.ok()).toBeTruthy()
    const data = await response.json()
    expect(data.examples).toHaveLength(4)
    for (const ex of data.examples) {
      expect(ex.available).toBe(true)
    }
  })

  for (const [label, btnId, key] of [
    ['6HB Honeycomb (M13)',  'menu-example-6hb',    '6hb'],
    ['18HB Honeycomb (M13)', 'menu-example-18hb',   '18hb'],
    ['2×20 Square (M13)',    'menu-example-2x20sq', '2x20sq'],
    ['3×6 Square (M13)',     'menu-example-3x6sq',  '3x6sq'],
  ]) {
    test(`loading ${label} gives scaffold = ${TARGET_SCAFFOLD} nt`, async ({ page }) => {
      await page.goto('/')

      // Load via menu
      await loadExample(page, btnId)
      await waitForDesign(page)

      // Verify scaffold length
      const scaffoldLen = await fetchScaffoldLength(page)
      expect(scaffoldLen).toBe(TARGET_SCAFFOLD)
    })

    test(`${label}: API load-example by key '${key}' returns 200`, async ({ page }) => {
      await page.goto('/')
      const response = await page.request.post('/api/design/load-example', {
        data: { key },
      })
      expect(response.ok()).toBeTruthy()
      const data = await response.json()
      expect(data?.design?.strands).toBeDefined()
    })
  }

})
